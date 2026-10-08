"""Ağ bilgileri: yerel IP ve bağlı Wi-Fi adı (SSID)."""

import os
import shutil
import socket
import subprocess
import time

_cache = {"t": 0.0, "ssid": None}


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # paket gönderilmez, yalnızca arayüz seçilir
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _run(args):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=3,
                             env={**os.environ, "LC_ALL": "C"})
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _split_terse(line: str):
    """nmcli -t çıktısı: alanlar ':' ile ayrılır, değerdeki ':' '\\:' olarak kaçar."""
    parts, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def wifi_name(max_age: float = 10.0):
    """Bağlı Wi-Fi ağının adı; kablolu ağda 'Kablolu ağ', bilinmiyorsa None."""
    now = time.monotonic()
    if now - _cache["t"] < max_age:
        return _cache["ssid"]
    ssid = None
    if shutil.which("nmcli"):
        for line in _run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"]).splitlines():
            f = _split_terse(line)
            if len(f) >= 2 and f[0] == "yes" and f[1]:
                ssid = f[1]
                break
        if not ssid:
            for line in _run(["nmcli", "-t", "-f", "TYPE,STATE", "device"]).splitlines():
                f = _split_terse(line)
                if len(f) >= 2 and f[0] == "ethernet" and f[1] == "connected":
                    ssid = "Kablolu ağ"
                    break
    if not ssid and shutil.which("iwgetid"):
        ssid = _run(["iwgetid", "-r"]).strip() or None
    _cache.update(t=now, ssid=ssid)
    return ssid
