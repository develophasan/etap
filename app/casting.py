"""
Ekran yansıtma yöneticisi.

  iPhone / iPad  -> UxPlay (AirPlay alıcısı). Sürekli arka planda çalışır;
                    telefonda Denetim Merkezi > Ekran Yansıtma > "Akıllı Tahta".
  Android        -> scrcpy, Wi-Fi üzerinden ADB (Kablosuz hata ayıklama).
                    Telefondaki "Ekranımı Yansıt" butonu sunucuya istek atar,
                    sunucu adb ile telefona bağlanıp scrcpy'yi tam ekran açar.

Not: Telefon tarayıcılarında getDisplayMedia() (ekran paylaşımı) API'si yoktur
(Android Chrome ve iOS Safari desteklemez) ve ayrıca HTTPS ister. Bu yüzden
tarayıcı tabanlı WebRTC yansıtma telefonda çalışmaz; işletim sisteminin kendi
yansıtma protokolleri (AirPlay / ADB) en düşük gecikmeli ve kararlı yoldur.
"""

import asyncio
import logging
import os
import re
import shlex
import shutil
import time
from pathlib import Path

log = logging.getLogger("tahta.cast")


def _log_dir() -> Path:
    d = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "tahta-kumanda"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tail(path: Path, n: int = 6) -> str:
    try:
        lines = path.read_text(errors="replace").strip().splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


async def _terminate(proc, timeout=4):
    if proc is None or proc.returncode is not None:
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    except ProcessLookupError:
        pass


class CastManager:
    def __init__(self, base_dir: Path):
        self.name = os.environ.get("TAHTA_ADI", "Akıllı Tahta")
        self.uxplay = shutil.which("uxplay")
        self.scrcpy = shutil.which("scrcpy")
        bundled_adb = base_dir / "tools" / "platform-tools" / "adb"
        self.adb = str(bundled_adb) if bundled_adb.exists() else shutil.which("adb")

        self._ux_proc = None
        self._ux_task = None
        self._ux_wanted = False
        self._ux_log = _log_dir() / "uxplay.log"

        self._sc_proc = None
        self._sc_serial = None
        self._sc_log = _log_dir() / "scrcpy.log"
        self._lock = asyncio.Lock()

    # ================================================================ AirPlay
    async def start_airplay(self):
        if not self.uxplay:
            log.warning("uxplay bulunamadı; iPhone yansıtma kapalı.")
            return
        self._ux_wanted = True
        if self._ux_task is None or self._ux_task.done():
            self._ux_task = asyncio.create_task(self._uxplay_loop())

    async def _uxplay_loop(self):
        backoff = 2
        while self._ux_wanted:
            args = [self.uxplay, "-n", self.name, "-nh", "-fs", "-p"]
            args += shlex.split(os.environ.get("TAHTA_UXPLAY_ARGS", ""))
            started = time.monotonic()
            try:
                with open(self._ux_log, "ab") as lf:
                    lf.write(f"\n=== {time.ctime()} {' '.join(args)}\n".encode())
                    lf.flush()
                    self._ux_proc = await asyncio.create_subprocess_exec(
                        *args, stdout=lf, stderr=lf, stdin=asyncio.subprocess.DEVNULL)
                    log.info("UxPlay başladı (pid %s), AirPlay adı: %s", self._ux_proc.pid, self.name)
                    rc = await self._ux_proc.wait()
                log.warning("UxPlay kapandı (kod %s)", rc)
            except OSError as ex:
                log.error("UxPlay başlatılamadı: %s", ex)
            finally:
                self._ux_proc = None
            if not self._ux_wanted:
                break
            backoff = 2 if time.monotonic() - started > 30 else min(backoff * 2, 60)
            await asyncio.sleep(backoff)

    async def restart_airplay(self):
        if not self.uxplay:
            return False, "uxplay kurulu değil (sudo apt install uxplay)"
        if self._ux_proc:
            await _terminate(self._ux_proc)  # döngü otomatik yeniden başlatır
        await self.start_airplay()
        return True, "AirPlay alıcısı yeniden başlatılıyor"

    async def stop_airplay(self):
        self._ux_wanted = False
        await _terminate(self._ux_proc)

    # ================================================================ Android
    def _env(self):
        env = os.environ.copy()
        if self.adb:
            env["ADB"] = self.adb  # scrcpy aynı adb'yi kullansın
        return env

    async def _run(self, *args, timeout=20):
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, env=self._env())
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, "zaman aşımı"
        return proc.returncode, out.decode(errors="replace").strip()

    def _check_android_tools(self):
        if not self.adb:
            return "adb bulunamadı (install.sh platform-tools'u indirir)"
        if not self.scrcpy:
            return "scrcpy kurulu değil (sudo apt install scrcpy)"
        return None

    async def android_pair(self, ip: str, port, code):
        err = self._check_android_tools()
        if err:
            return False, err
        try:
            port = int(port)
            assert 0 < port < 65536
        except (TypeError, ValueError, AssertionError):
            return False, "Geçersiz eşleştirme portu"
        code = re.sub(r"\D", "", str(code or ""))
        if len(code) != 6:
            return False, "Eşleştirme kodu 6 haneli olmalı"
        rc, out = await self._run(self.adb, "pair", f"{ip}:{port}", code)
        log.info("adb pair %s:%s -> %s", ip, port, out)
        if "Successfully paired" in out:
            return True, "Eşleştirildi. Şimdi 'Yansıtmayı Başlat'a basın."
        return False, f"Eşleştirme başarısız: {out or rc}"

    async def _discover_port(self, ip: str):
        """Eşleşmiş telefonun kablosuz hata ayıklama portunu mDNS ile bul."""
        rc, out = await self._run(self.adb, "mdns", "services", timeout=8)
        for line in out.splitlines():
            if "_adb-tls-connect" in line:
                m = re.search(r"(\d+\.\d+\.\d+\.\d+):(\d+)", line)
                if m and m.group(1) == ip:
                    return int(m.group(2))
        return None

    async def android_connect(self, ip: str, port=None):
        err = self._check_android_tools()
        if err:
            return False, err
        async with self._lock:
            if port in (None, "", 0, "0"):
                port = await self._discover_port(ip)
                if not port:
                    return False, ("Telefon otomatik bulunamadı. Kablosuz hata ayıklama ekranındaki "
                                   "'IP adresi ve bağlantı noktası' bilgisindeki portu yazın.")
            try:
                port = int(port)
                assert 0 < port < 65536
            except (TypeError, ValueError, AssertionError):
                return False, "Geçersiz bağlantı portu"

            serial = f"{ip}:{port}"
            rc, out = await self._run(self.adb, "connect", serial, timeout=15)
            log.info("adb connect %s -> %s", serial, out)
            low = out.lower()
            if "connected to" not in low or "failed" in low or "cannot" in low:
                return False, f"Bağlanılamadı: {out}. Önce eşleştirme yaptınız mı?"

            rc, state = await self._run(self.adb, "-s", serial, "get-state", timeout=8)
            if state.strip() != "device":
                if "unauthorized" in state:
                    return False, "Telefonda çıkan hata ayıklama iznini onaylayıp tekrar deneyin."
                return False, f"Telefon hazır değil: {state}"

            await self._stop_scrcpy()
            max_size = os.environ.get("TAHTA_SCRCPY_BOYUT", "1920")
            bitrate = os.environ.get("TAHTA_SCRCPY_BITRATE", "8M")
            args = [self.scrcpy, "-s", serial, "--fullscreen", "--stay-awake",
                    "-m", max_size, "-b", bitrate, "--max-fps", "30",
                    "--window-title", f"{self.name} - Android"]
            args += shlex.split(os.environ.get("TAHTA_SCRCPY_ARGS", ""))
            with open(self._sc_log, "ab") as lf:
                lf.write(f"\n=== {time.ctime()} {' '.join(args)}\n".encode())
                lf.flush()
                self._sc_proc = await asyncio.create_subprocess_exec(
                    *args, stdout=lf, stderr=lf, stdin=asyncio.subprocess.DEVNULL, env=self._env())
            self._sc_serial = serial

            # scrcpy hemen kapanırsa (ör. ekran yok) hatayı göster
            try:
                await asyncio.wait_for(self._sc_proc.wait(), 3)
                tail = _tail(self._sc_log)
                self._sc_proc = None
                self._sc_serial = None
                return False, f"scrcpy başlatılamadı:\n{tail}"
            except asyncio.TimeoutError:
                pass
            return True, "Yansıtma başladı"

    async def _stop_scrcpy(self):
        await _terminate(self._sc_proc)
        self._sc_proc = None
        self._sc_serial = None

    async def android_stop(self):
        async with self._lock:
            serial = self._sc_serial
            await self._stop_scrcpy()
        return True, f"Yansıtma durduruldu{f' ({serial})' if serial else ''}"

    # ================================================================== genel
    def status(self) -> dict:
        sc_running = self._sc_proc is not None and self._sc_proc.returncode is None
        if not sc_running:
            self._sc_serial = None
        return {
            "airplay": {
                "available": bool(self.uxplay),
                "running": self._ux_proc is not None and self._ux_proc.returncode is None,
                "name": self.name,
            },
            "android": {
                "available": bool(self.adb and self.scrcpy),
                "running": sc_running,
                "serial": self._sc_serial,
            },
        }

    async def shutdown(self):
        await self.stop_airplay()
        await self._stop_scrcpy()
