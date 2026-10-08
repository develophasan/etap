"""
Tahta Kumanda - Pardus akıllı tahta için telefondan fare/klavye, ekran yansıtma
ve dosya aktarımı.

Çalıştırma:  ./start.sh   (ya da)   python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import contextlib
import html
import json
import logging
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from .casting import CastManager
from .files import FileStore
from .input_device import InputController
from .netinfo import local_ip, wifi_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tahta")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
PORT = int(os.environ.get("TAHTA_PORT", "8000"))
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tahta-kumanda"
LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")


# ----------------------------------------------------------------------- PIN
def _pin_disabled() -> bool:
    return os.environ.get("TAHTA_PIN", "").strip().lower() in ("off", "kapali", "kapalı", "yok")


def _new_pin() -> str:
    p = f"{secrets.randbelow(10000):04d}"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "pin").write_text(p)
    return p


def load_pin():
    if _pin_disabled():
        return None
    env = os.environ.get("TAHTA_PIN", "").strip()
    if env:
        return env
    try:
        p = (CONFIG_DIR / "pin").read_text().strip()
        if p:
            return p
    except OSError:
        pass
    return _new_pin()


class State:
    pin = load_pin()
    inp: InputController = None
    cast: CastManager = None
    files: FileStore = None
    clients = set()
    show_seq = 0        # telefondan "paneli göster" istendikçe artar
    started = time.time()


S = State


class Guard:
    """Basit kaba-kuvvet koruması: 5 hatalı PIN -> 60 sn engel."""

    def __init__(self):
        self.fails = {}

    def check(self, ip: str, pin) -> str:
        if S.pin is None:
            return "ok"
        count, until = self.fails.get(ip, (0, 0.0))
        if time.monotonic() < until:
            return "blocked"
        if secrets.compare_digest(str(pin or "").strip().encode(), S.pin.encode()):
            self.fails.pop(ip, None)
            return "ok"
        count += 1
        self.fails[ip] = (0, time.monotonic() + 60) if count >= 5 else (count, 0.0)
        return "bad"


guard = Guard()


def server_url() -> str:
    port = "" if PORT == 80 else f":{PORT}"
    return f"http://{local_ip()}{port}"


# --------------------------------------------------------------- yardımcılar
def _client_ip(conn) -> str:
    return conn.client.host if conn.client else "?"


def _is_local(conn) -> bool:
    return _client_ip(conn) in LOCAL_HOSTS


def _deny(res: str):
    msg = "Çok fazla hatalı deneme, 1 dakika bekleyin" if res == "blocked" else "PIN hatalı"
    return JSONResponse({"ok": False, "reason": res, "message": msg}, status_code=401)


def _auth(request: Request, allow_query=False):
    """Tahtanın kendisinden gelen istekler PIN'siz kabul edilir."""
    if _is_local(request):
        return None
    pin = request.headers.get("x-pin")
    if pin is None and allow_query:
        pin = request.query_params.get("pin")
    res = guard.check(_client_ip(request), pin)
    return None if res == "ok" else _deny(res)


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _int(v, lo=-4000, hi=4000) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _notify(title: str, body: str):
    if shutil.which("notify-send") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        try:
            subprocess.Popen(["notify-send", "-t", "8000", "-i", "input-tablet", title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


# ------------------------------------------------------------------ yaşam döngüsü
async def _announce_when_online():
    for _ in range(30):
        if local_ip() != "127.0.0.1":
            break
        await asyncio.sleep(2)
    log.info("Hazır: %s  PIN: %s  Wi-Fi: %s", server_url(), S.pin or "(kapalı)", wifi_name() or "?")
    # Masaüstü paneli kullanılmıyorsa (start.sh doğrudan) bildirim göster
    if os.environ.get("TAHTA_BILDIRIM", "0") == "1":
        _notify("Tahta Kumanda hazır",
                f"Telefondan şu adrese girin:\n{server_url()}" + (f"\nPIN: {S.pin}" if S.pin else ""))


@contextlib.asynccontextmanager
async def lifespan(app):
    S.inp = InputController(os.environ.get("TAHTA_KLAVYE", "tr"))
    S.cast = CastManager(BASE_DIR)
    S.files = FileStore()
    try:
        S.files.ensure()
        log.info("Dosya klasörü: %s", S.files.dir)
    except OSError as ex:
        log.error("Dosya klasörü oluşturulamadı: %s", ex)
    if os.environ.get("TAHTA_AIRPLAY", "1") != "0":
        await S.cast.start_airplay()
    task = asyncio.create_task(_announce_when_online())
    try:
        yield
    finally:
        task.cancel()
        await S.cast.shutdown()
        S.inp.close()


# ------------------------------------------------------------------ sayfalar
async def index(request):
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


async def qr_svg(request):
    """Bağlantı adresinin QR kodu (qrencode kuruluysa)."""
    exe = shutil.which("qrencode")
    if not exe:
        return Response(status_code=404)
    proc = await asyncio.create_subprocess_exec(
        exe, "-t", "SVG", "-m", "1", "-o", "-", server_url(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return Response(out, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})


async def info_page(request):
    """Yalnızca tahtanın kendisinden açılabilir: adres, Wi-Fi ve PIN'i büyük gösterir."""
    if not _is_local(request):
        return HTMLResponse("Bu sayfa yalnızca tahtadan açılabilir.", status_code=403)
    url = html.escape(server_url())
    pin = html.escape(S.pin or "PIN kapalı")
    ssid = html.escape(wifi_name() or "bilinmiyor")
    qr = '<img class="q" src="/qr.svg" alt="">' if shutil.which("qrencode") else ""
    return HTMLResponse(f"""<!doctype html><html lang="tr"><meta charset="utf-8">
<title>Tahta Kumanda</title>
<style>body{{margin:0;height:100vh;display:grid;place-items:center;background:#11151c;color:#e8edf4;
font-family:system-ui,sans-serif;text-align:center}}h1{{font-size:2.6vw;font-weight:500;margin:0 0 3vh;color:#9aa7b8}}
.w{{display:flex;gap:5vw;align-items:center;justify-content:center}}.q{{width:22vw;height:22vw;background:#fff;padding:1vw;border-radius:1vw}}
.u{{font-size:5.5vw;font-weight:700;letter-spacing:.02em}}.p{{font-size:4vw;margin-top:3vh;color:#7cc4ff}}
.s{{font-size:2.2vw;margin-top:2vh;color:#c9d3df}}
.n{{font-size:1.5vw;margin-top:5vh;color:#9aa7b8;max-width:70vw;line-height:1.5}}
.c{{position:fixed;bottom:2vh;left:0;right:0;font-size:1.1vw;color:#6f7b8c}}.c a{{color:#7cc4ff;text-decoration:none}}</style>
<div><h1>Telefonunuzun tarayıcısından şu adrese girin</h1><div class="w">{qr}<div>
<div class="u">{url}</div><div class="p">PIN: <b>{pin}</b></div><div class="s">Wi-Fi: <b>{ssid}</b></div></div></div>
<div class="n">Telefon ve tahta aynı Wi-Fi ağında olmalı.{" QR kodu telefon kamerasıyla okutabilirsiniz." if qr else ""}<br>
iPhone yansıtma: Denetim Merkezi → Ekran Yansıtma → <b>{html.escape(S.cast.name if S.cast else "")}</b></div></div>
<div class="c">© 2026 <a href="https://github.com/develophasan" target="_blank">Hasan Özdemir</a>. Tüm hakları saklıdır.</div></html>""")


# ---------------------------------------------------------------------- API
async def api_info(request):
    return JSONResponse({"pin_required": S.pin is not None})


async def api_auth(request):
    data = await _json(request)
    res = guard.check(_client_ip(request), data.get("pin"))
    return JSONResponse({"ok": True}) if res == "ok" else _deny(res)


async def api_status(request):
    if (r := _auth(request)):
        return r
    return JSONResponse({
        "ok": True, "input": S.inp.status(), "cast": S.cast.status(),
        "clients": len(S.clients), "your_ip": _client_ip(request), "url": server_url(),
        "files_dir": str(S.files.dir),
    })


# ----- yansıtma
async def api_airplay_restart(request):
    if (r := _auth(request)):
        return r
    ok, msg = await S.cast.restart_airplay()
    return JSONResponse({"ok": ok, "message": msg})


async def api_android_pair(request):
    if (r := _auth(request)):
        return r
    d = await _json(request)
    ok, msg = await S.cast.android_pair(_client_ip(request), d.get("port"), d.get("code"))
    return JSONResponse({"ok": ok, "message": msg})


async def api_android_connect(request):
    if (r := _auth(request)):
        return r
    d = await _json(request)
    ok, msg = await S.cast.android_connect(_client_ip(request), d.get("port"))
    return JSONResponse({"ok": ok, "message": msg})


async def api_android_stop(request):
    if (r := _auth(request)):
        return r
    ok, msg = await S.cast.android_stop()
    return JSONResponse({"ok": ok, "message": msg})


# ----- dosyalar
async def api_files_list(request):
    if (r := _auth(request)):
        return r
    try:
        items = await asyncio.to_thread(S.files.list)
    except OSError as ex:
        return JSONResponse({"ok": False, "message": f"Klasör okunamadı: {ex}"}, status_code=500)
    free = shutil.disk_usage(S.files.dir).free
    return JSONResponse({"ok": True, "files": items, "dir": str(S.files.dir),
                         "free": free, "max": S.files.max_bytes})


async def api_files_upload(request):
    if (r := _auth(request)):
        return r
    name = request.query_params.get("name", "")
    size = request.headers.get("content-length")
    size = int(size) if size and size.isdigit() else None
    ok, res = await S.files.save_stream(name, request.stream(), size)
    if not ok:
        return JSONResponse({"ok": False, "message": res}, status_code=400)
    if request.query_params.get("open") == "1":
        S.files.open_on_board(res)
    elif os.environ.get("TAHTA_DOSYA_BILDIRIM", "1") == "1":
        _notify("Telefondan dosya geldi", res)
    return JSONResponse({"ok": True, "name": res})


async def api_files_download(request):
    if (r := _auth(request, allow_query=True)):
        return r
    p = S.files.path_for(request.path_params["name"])
    if not p:
        return JSONResponse({"ok": False, "message": "Dosya bulunamadı"}, status_code=404)
    return FileResponse(p, filename=p.name)


async def api_files_open(request):
    if (r := _auth(request)):
        return r
    d = await _json(request)
    ok, msg = S.files.open_on_board(d.get("name"))
    return JSONResponse({"ok": ok, "message": msg}, status_code=200 if ok else 404)


async def api_files_delete(request):
    if (r := _auth(request)):
        return r
    d = await _json(request)
    ok = await asyncio.to_thread(S.files.delete, str(d.get("name", "")))
    return JSONResponse({"ok": ok, "message": "Silindi" if ok else "Dosya bulunamadı"},
                        status_code=200 if ok else 404)


# ----- masaüstü paneli
async def api_panel(request):
    """Tahtadaki masaüstü panelinin okuduğu bilgiler (yalnızca tahtadan)."""
    if not _is_local(request):
        return JSONResponse({"ok": False}, status_code=403)
    ip = local_ip()
    return JSONResponse({
        "ok": True, "url": server_url(), "ip": ip, "port": PORT, "online": ip != "127.0.0.1",
        "pin": S.pin, "wifi": wifi_name(), "clients": len(S.clients),
        "input": S.inp.status(), "cast": S.cast.status(),
        "files_dir": str(S.files.dir), "show_seq": S.show_seq, "started": S.started,
    })


async def api_panel_newpin(request):
    if not _is_local(request):
        return JSONResponse({"ok": False}, status_code=403)
    if _pin_disabled() or os.environ.get("TAHTA_PIN", "").strip():
        return JSONResponse({"ok": False, "message": "PIN ayarlar.env dosyasında sabitlenmiş"})
    S.pin = _new_pin()
    guard.fails.clear()
    for ws in list(S.clients):  # eski PIN'le bağlı telefonları çıkar
        with contextlib.suppress(Exception):
            await ws.close(code=4001)
    log.info("Yeni PIN üretildi")
    return JSONResponse({"ok": True, "pin": S.pin})


async def api_panel_show(request):
    """Telefondan 'paneli tahtada göster' isteği."""
    if (r := _auth(request)):
        return r
    S.show_seq += 1
    return JSONResponse({"ok": True})


# ----------------------------------------------------------------- WebSocket
async def ws_endpoint(ws: WebSocket):
    ip = _client_ip(ws)
    res = "ok" if ip in LOCAL_HOSTS else guard.check(ip, ws.query_params.get("pin"))
    await ws.accept()
    if res != "ok":
        await ws.send_text(json.dumps({"t": "auth", "ok": False, "reason": res}))
        await ws.close(code=4001)
        return

    inp = S.inp
    S.clients.add(ws)
    log.info("Telefon bağlandı: %s (toplam %d)", ip, len(S.clients))
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
        S.clients.discard(ws)
        inp.release_all()
        log.info("Telefon ayrıldı: %s (kalan %d)", ip, len(S.clients))


routes = [
    Route("/", index),
    Route("/bilgi", info_page),
    Route("/qr.svg", qr_svg),
    Route("/api/info", api_info),
    Route("/api/auth", api_auth, methods=["POST"]),
    Route("/api/status", api_status),
    Route("/api/cast/airplay/restart", api_airplay_restart, methods=["POST"]),
    Route("/api/cast/android/pair", api_android_pair, methods=["POST"]),
    Route("/api/cast/android/connect", api_android_connect, methods=["POST"]),
    Route("/api/cast/android/stop", api_android_stop, methods=["POST"]),
    Route("/api/files", api_files_list),
    Route("/api/files/upload", api_files_upload, methods=["PUT", "POST"]),
    Route("/api/files/open", api_files_open, methods=["POST"]),
    Route("/api/files/delete", api_files_delete, methods=["POST"]),
    Route("/api/files/download/{name:path}", api_files_download),
    Route("/api/panel", api_panel),
    Route("/api/panel/newpin", api_panel_newpin, methods=["POST"]),
    Route("/api/panel/show", api_panel_show, methods=["POST"]),
    WebSocketRoute("/ws", ws_endpoint),
    Mount("/static", app=StaticFiles(directory=str(STATIC_DIR)), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT)
