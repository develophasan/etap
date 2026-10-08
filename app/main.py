"""
Tahta Kumanda - Pardus akıllı tahta için telefondan fare/klavye ve ekran yansıtma.

Çalıştırma:  ./start.sh   (ya da)   python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import html
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .casting import CastManager
from .input_device import InputController

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tahta")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
PORT = int(os.environ.get("TAHTA_PORT", "8000"))
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tahta-kumanda"


# ----------------------------------------------------------------------- PIN
def load_pin():
    env = os.environ.get("TAHTA_PIN", "").strip()
    if env.lower() in ("off", "kapali", "kapalı", "yok"):
        return None
    if env:
        return env
    f = CONFIG_DIR / "pin"
    try:
        p = f.read_text().strip()
        if p:
            return p
    except OSError:
        pass
    p = f"{secrets.randbelow(10000):04d}"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(p)
    return p


PIN = load_pin()


class Guard:
    """Basit kaba-kuvvet koruması: 5 hatalı PIN -> 60 sn engel."""

    def __init__(self):
        self.fails = {}

    def check(self, ip: str, pin) -> str:
        if PIN is None:
            return "ok"
        count, until = self.fails.get(ip, (0, 0.0))
        if time.monotonic() < until:
            return "blocked"
        if secrets.compare_digest(str(pin or "").strip().encode(), PIN.encode()):
            self.fails.pop(ip, None)
            return "ok"
        count += 1
        if count >= 5:
            self.fails[ip] = (0, time.monotonic() + 60)
        else:
            self.fails[ip] = (count, 0.0)
        return "bad"


guard = Guard()


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # paket gönderilmez, yalnızca arayüz seçilir
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def server_url() -> str:
    port = "" if PORT == 80 else f":{PORT}"
    return f"http://{local_ip()}{port}"


# ----------------------------------------------------------------- uygulama
app = FastAPI(title="Tahta Kumanda", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

inp: InputController = None  # type: ignore
cast: CastManager = None  # type: ignore
clients = set()


async def _notify_when_online():
    """Ağ geldiğinde tahtada adres ve PIN bildirimini göster."""
    for _ in range(30):
        if local_ip() != "127.0.0.1":
            break
        await asyncio.sleep(2)
    url = server_url()
    msg = f"Telefondan şu adrese girin:\n{url}" + (f"\nPIN: {PIN}" if PIN else "")
    log.info("Hazır: %s  PIN: %s", url, PIN or "(kapalı)")
    if shutil.which("notify-send") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        try:
            subprocess.Popen(["notify-send", "-t", "15000", "-i", "input-tablet",
                              "Tahta Kumanda hazır", msg],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


@app.on_event("startup")
async def on_startup():
    global inp, cast
    inp = InputController(os.environ.get("TAHTA_KLAVYE", "tr"))
    cast = CastManager(BASE_DIR)
    if os.environ.get("TAHTA_AIRPLAY", "1") != "0":
        await cast.start_airplay()
    asyncio.create_task(_notify_when_online())


@app.on_event("shutdown")
async def on_shutdown():
    if cast:
        await cast.shutdown()
    if inp:
        inp.close()


# --------------------------------------------------------------- yardımcılar
def _client_ip(request) -> str:
    return request.client.host if request.client else "?"


def _auth(request: Request):
    res = guard.check(_client_ip(request), request.headers.get("x-pin"))
    if res == "ok":
        return None
    msg = "Çok fazla hatalı deneme, 1 dakika bekleyin" if res == "blocked" else "PIN hatalı"
    return JSONResponse({"ok": False, "reason": res, "message": msg}, status_code=401)


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except (ValueError, json.JSONDecodeError):
        return {}


def _int(v, lo=-4000, hi=4000) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------ sayfalar
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/bilgi", response_class=HTMLResponse)
async def info_page(request: Request):
    """Yalnızca tahtanın kendisinden açılabilir: adresi ve PIN'i büyük gösterir."""
    if _client_ip(request) not in ("127.0.0.1", "::1"):
        return HTMLResponse("Bu sayfa yalnızca tahtadan açılabilir.", status_code=403)
    url = html.escape(server_url())
    pin = html.escape(PIN or "PIN kapalı")
    return f"""<!doctype html><html lang="tr"><meta charset="utf-8">
<title>Tahta Kumanda</title>
<style>body{{margin:0;height:100vh;display:grid;place-items:center;background:#11151c;color:#e8edf4;
font-family:system-ui,sans-serif;text-align:center}}h1{{font-size:3vw;font-weight:500;margin:0 0 4vh;color:#9aa7b8}}
.u{{font-size:6vw;font-weight:700;letter-spacing:.02em}}.p{{font-size:4vw;margin-top:5vh;color:#7cc4ff}}
.n{{font-size:1.6vw;margin-top:6vh;color:#9aa7b8;max-width:70vw;line-height:1.5}}</style>
<div><h1>Telefonunuzun tarayıcısından şu adrese girin</h1><div class="u">{url}</div>
<div class="p">PIN: <b>{pin}</b></div>
<div class="n">Telefon ve tahta aynı Wi-Fi ağında olmalı.<br>
iPhone yansıtma: Denetim Merkezi → Ekran Yansıtma → <b>{html.escape(cast.name if cast else "")}</b></div></div></html>"""


# ---------------------------------------------------------------------- API
@app.get("/api/info")
async def api_info():
    return {"pin_required": PIN is not None}


@app.post("/api/auth")
async def api_auth(request: Request):
    data = await _json(request)
    res = guard.check(_client_ip(request), data.get("pin"))
    if res == "ok":
        return {"ok": True}
    msg = "Çok fazla hatalı deneme, 1 dakika bekleyin" if res == "blocked" else "PIN hatalı"
    return JSONResponse({"ok": False, "reason": res, "message": msg}, status_code=401)


@app.get("/api/status")
async def api_status(request: Request):
    if (r := _auth(request)):
        return r
    return {"ok": True, "input": inp.status(), "cast": cast.status(),
            "clients": len(clients), "your_ip": _client_ip(request), "url": server_url()}


@app.post("/api/cast/airplay/restart")
async def api_airplay_restart(request: Request):
    if (r := _auth(request)):
        return r
    ok, msg = await cast.restart_airplay()
    return {"ok": ok, "message": msg}


@app.post("/api/cast/android/pair")
async def api_android_pair(request: Request):
    if (r := _auth(request)):
        return r
    d = await _json(request)
    ok, msg = await cast.android_pair(_client_ip(request), d.get("port"), d.get("code"))
    return {"ok": ok, "message": msg}


@app.post("/api/cast/android/connect")
async def api_android_connect(request: Request):
    if (r := _auth(request)):
        return r
    d = await _json(request)
    ok, msg = await cast.android_connect(_client_ip(request), d.get("port"))
    return {"ok": ok, "message": msg}


@app.post("/api/cast/android/stop")
async def api_android_stop(request: Request):
    if (r := _auth(request)):
        return r
    ok, msg = await cast.android_stop()
    return {"ok": ok, "message": msg}


# ----------------------------------------------------------------- WebSocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    ip = ws.client.host if ws.client else "?"
    res = guard.check(ip, ws.query_params.get("pin"))
    await ws.accept()
    if res != "ok":
        await ws.send_text(json.dumps({"t": "auth", "ok": False, "reason": res}))
        await ws.close(code=4001)
        return

    clients.add(ws)
    log.info("Telefon bağlandı: %s (toplam %d)", ip, len(clients))
    await ws.send_text(json.dumps({"t": "hello", "input": inp.status(), "ip": ip}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("t")
            if t == "m":
                inp.move(_int(msg.get("dx")), _int(msg.get("dy")))
            elif t == "s":
                inp.scroll(_int(msg.get("v")), _int(msg.get("h")))
            elif t == "c":
                inp.click(str(msg.get("b", "l")), _int(msg.get("n", 1), 1, 3))
            elif t == "d":
                inp.button(str(msg.get("b", "l")), True)
            elif t == "u":
                inp.button(str(msg.get("b", "l")), False)
            elif t == "txt":
                await inp.type_text(str(msg.get("v", ""))[:2000])
            elif t == "k":
                inp.key(str(msg.get("k", "")), _int(msg.get("n", 1), 1, 200))
            elif t == "combo":
                keys = msg.get("k")
                if isinstance(keys, list):
                    inp.combo([str(k) for k in keys])
            elif t == "ping":
                await ws.send_text('{"t":"pong"}')
    except WebSocketDisconnect:
        pass
    except Exception:  # bağlantı aniden koparsa
        log.exception("WebSocket hatası")
    finally:
        clients.discard(ws)
        inp.release_all()
        log.info("Telefon ayrıldı: %s (kalan %d)", ip, len(clients))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT)
