"""
Telefon <-> tahta dosya aktarımı.

Dosyalar tahtada tek bir klasörde toplanır (varsayılan: Masaüstü/Telefondan Gelenler).
Telefondan yüklenenler buraya yazılır; bu klasöre tahtadan konan dosyalar da
telefondan indirilebilir.

Yükleme, dosyanın ham içeriği gövdede gönderilerek (PUT) yapılır: multipart
ayrıştırmaya gerek kalmaz, büyük dosyalar belleğe alınmadan diske akar.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

log = logging.getLogger("tahta.files")

MAX_NAME_BYTES = 200
FREE_SPACE_MARGIN = 200 * 1024 * 1024  # diskte en az 200 MB boş kalsın


def _desktop_dir() -> Path:
    """Kullanıcının masaüstü klasörü (Türkçe sistemde ~/Masaüstü)."""
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=3)
        p = Path(out.stdout.strip())
        if out.returncode == 0 and p.is_dir() and p != Path.home():
            return p
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ("Masaüstü", "Desktop"):
        p = Path.home() / name
        if p.is_dir():
            return p
    return Path.home()


def default_dir() -> Path:
    env = os.environ.get("TAHTA_DOSYA_KLASORU", "").strip()
    if env:
        return Path(os.path.expanduser(env))
    return _desktop_dir() / "Telefondan Gelenler"


def safe_name(name: str) -> str:
    """Telefondan gelen dosya adını güvenli hale getirir (klasör dışına çıkamaz)."""
    name = unicodedata.normalize("NFC", str(name or ""))
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().lstrip(".").strip()
    if not name:
        name = "dosya"
    # Bayt sınırı (uzantıyı koruyarak kırp)
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 12:
        stem, ext = name, ""
    while len((stem + ("." + ext if ext else "")).encode()) > MAX_NAME_BYTES and stem:
        stem = stem[:-1]
    return (stem or "dosya") + ("." + ext if ext else "")


class FileStore:
    def __init__(self, directory: Path = None, max_bytes: int = None):
        self.dir = Path(directory or default_dir())
        mb = os.environ.get("TAHTA_DOSYA_LIMIT_MB", "").strip()
        self.max_bytes = max_bytes or (int(mb) * 1024 * 1024 if mb.isdigit() else 4 * 1024 ** 3)

    def ensure(self):
        self.dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- yollar
    def path_for(self, name: str):
        """Var olan bir dosyanın güvenli yolu; klasör dışını reddeder."""
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            return None
        p = (self.dir / name).resolve()
        try:
            p.relative_to(self.dir.resolve())
        except ValueError:
            return None
        return p if p.is_file() else None

    def _unique(self, name: str) -> Path:
        p = self.dir / name
        if not p.exists():
            return p
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        i = 1
        while True:
            cand = self.dir / f"{stem} ({i}){'.' + ext if ext else ''}"
            if not cand.exists():
                return cand
            i += 1

    # -------------------------------------------------------------- işlemler
    def list(self):
        self.ensure()
        items = []
        for p in self.dir.iterdir():
            if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".part"):
                st = p.stat()
                items.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items

    def check_space(self, size):
        self.ensure()
        if size is not None and size > self.max_bytes:
            return f"Dosya çok büyük (en fazla {self.max_bytes // (1024 * 1024)} MB)"
        free = shutil.disk_usage(self.dir).free
        need = (size or 0) + FREE_SPACE_MARGIN
        if free < need:
            return f"Tahtada yeterli boş yer yok ({free // (1024 * 1024)} MB boş)"
        return None

    async def save_stream(self, name: str, stream, size=None):
        """Akışı .part dosyasına yazar, bitince asıl adına taşır. (ok, mesaj/ad)"""
        err = self.check_space(size)
        if err:
            return False, err
        final = self._unique(safe_name(name))
        part = final.with_name("." + final.name + ".part")
        written = 0
        try:
            f = await asyncio.to_thread(open, part, "wb")
            try:
                async for chunk in stream:
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise ValueError(f"Dosya çok büyük (en fazla {self.max_bytes // (1024 * 1024)} MB)")
                    await asyncio.to_thread(f.write, chunk)
            finally:
                await asyncio.to_thread(f.close)
            if size is not None and written != size:
                raise ValueError("Yükleme yarıda kesildi")
            # Aynı anda aynı adla yükleme yapıldıysa çakışmasın
            if final.exists():
                final = self._unique(final.name)
            os.replace(part, final)
        except ValueError as ex:
            part.unlink(missing_ok=True)
            return False, str(ex)
        except Exception as ex:  # bağlantı koptu, disk doldu vb.
            part.unlink(missing_ok=True)
            log.warning("Yükleme başarısız (%s): %s", name, ex)
            return False, "Yükleme başarısız oldu"
        log.info("Dosya alındı: %s (%d bayt)", final.name, written)
        return True, final.name

    def delete(self, name: str):
        p = self.path_for(name)
        if not p:
            return False
        p.unlink()
        return True

    def open_on_board(self, name: str = None):
        """Dosyayı (ya da klasörü) tahtada varsayılan uygulamayla açar."""
        target = self.dir if name is None else self.path_for(name)
        if target is None:
            return False, "Dosya bulunamadı"
        self.ensure()
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if not opener:
            return False, "xdg-open bulunamadı"
        args = [opener, str(target)] if opener.endswith("xdg-open") else [opener, "open", str(target)]
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError as ex:
            return False, f"Açılamadı: {ex}"
        return True, "Tahtada açılıyor"
