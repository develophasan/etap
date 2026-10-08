"""
Masaüstü panelinin arayüzden bağımsız kısmı: ayarları okuma, sunucuyu
başlatma/durdurma ve sunucudan durum çekme. (GTK'sız test edilebilir.)
"""

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def read_env_file(path: Path) -> dict:
    """ayarlar.env içindeki KEY=VALUE satırlarını okur (tırnaklar soyulur)."""
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    except OSError:
        pass
    return out


def settings() -> dict:
    s = read_env_file(BASE_DIR / "ayarlar.env")
    for k in ("TAHTA_PORT", "TAHTA_ADI"):
        if os.environ.get(k):
            s[k] = os.environ[k]
    return s


def port() -> int:
    try:
        return int(settings().get("TAHTA_PORT") or 8000)
    except ValueError:
        return 8000


def _req(path: str, method="GET", timeout=1.5):
    url = f"http://127.0.0.1:{port()}{path}"
    req = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"Content-Type": "application/json"})
    # Yerel istek: sistem vekil sunucu ayarlarını atla
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_status():
    """Sunucu çalışıyorsa panel bilgisini, çalışmıyorsa None döndürür."""
    try:
        d = _req("/api/panel")
        return d if d.get("ok") else None
    except Exception:
        return None


def new_pin():
    try:
        return _req("/api/panel/newpin", "POST", timeout=4)
    except Exception as ex:
        return {"ok": False, "message": str(ex)}


def start_server():
    """start.sh --arka-plan ile sunucuyu başlatır (zaten çalışıyorsa bir şey yapmaz)."""
    env = {**os.environ, "TAHTA_BILDIRIM": "0"}
    subprocess.Popen([str(BASE_DIR / "start.sh"), "--arka-plan"], cwd=str(BASE_DIR), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def stop_server():
    subprocess.run(["pkill", "-f", r"python[0-9.]* -m uvicorn app\.main:app"], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def open_path(target: str):
    exe = shutil.which("xdg-open")
    if exe:
        subprocess.Popen([exe, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def make_qr_png(text: str):
    """Adres için QR kod PNG'si üretir; qrencode yoksa None."""
    exe = shutil.which("qrencode")
    if not exe:
        return None
    path = Path(tempfile.gettempdir()) / f"tahta-kumanda-qr-{os.getuid()}.png"
    try:
        subprocess.run([exe, "-t", "PNG", "-s", "6", "-m", "2", "-o", str(path), text],
                       check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(path)
    except (OSError, subprocess.SubprocessError):
        return None


def describe(d) -> dict:
    """Panel bilgisini ekranda gösterilecek metinlere çevirir."""
    if not d:
        return {"state": "off", "headline": "Sunucu başlatılıyor…", "rows": []}
    if not d.get("online"):
        headline = "Ağ bağlantısı bekleniyor…"
        state = "wait"
    else:
        n = d.get("clients", 0)
        headline = f"{n} telefon bağlı" if n else "Telefon bekleniyor"
        state = "on"
    inp = d.get("input") or {}
    cast = d.get("cast") or {}
    air = cast.get("airplay") or {}
    andr = cast.get("android") or {}
    rows = [
        ("Fare / klavye", "Hazır" if inp.get("ok") else "Hata: " + str(inp.get("error") or "bilinmiyor"),
         bool(inp.get("ok"))),
        ("iPhone yansıtma",
         f"Hazır – \"{air.get('name')}\"" if air.get("running")
         else ("Kurulu değil" if not air.get("available") else "Başlatılıyor…"),
         bool(air.get("running"))),
        ("Android yansıtma",
         f"Yansıtılıyor ({andr.get('serial')})" if andr.get("running")
         else ("Hazır" if andr.get("available") else "Kurulu değil"),
         bool(andr.get("available"))),
    ]
    return {"state": state, "headline": headline, "rows": rows}
