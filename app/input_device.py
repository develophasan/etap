"""
Sanal fare ve klavye (Linux çekirdeği uinput).

Neden uinput?
  xdotool / pyautogui / pynput yalnızca X11'de çalışır; Wayland oturumunda
  ya hiç çalışmaz ya da yalnızca XWayland pencerelerini etkiler. uinput ise
  çekirdek seviyesinde "gerçek bir USB fare/klavye takılmış gibi" aygıt
  oluşturur; X11, Wayland, giriş ekranı ve tam ekran uygulamalar dahil her
  yerde aynı şekilde çalışır. Pardus'un hem X11 hem Wayland oturumları için
  en kararlı yöntem budur.
"""

import asyncio
import logging
import os
import shutil

from .keymap import ALTGR, SHIFT, SPECIAL_KEYS, get_layout, normalize

log = logging.getLogger("tahta.input")

try:
    from evdev import UInput, ecodes as e
except ImportError:  # pragma: no cover
    UInput = None
    e = None

BUTTONS = {"l": "BTN_LEFT", "r": "BTN_RIGHT", "m": "BTN_MIDDLE"}
HI_RES_STEP = 120  # 1 tekerlek "çentiği" = 120 yüksek çözünürlük birimi


class InputController:
    def __init__(self, layout: str = "tr"):
        self.layout_name = (layout or "tr").lower()
        self.charmap = get_layout(self.layout_name)
        self.mouse = None
        self.kbd = None
        self.error = None
        self._wheel_acc = {"v": 0, "h": 0}
        self._held_buttons = set()
        self._held_keys = set()
        self._has_hires = False
        self._xdotool = shutil.which("xdotool") if os.environ.get("DISPLAY") else None

        if UInput is None:
            self.error = "python3-evdev kurulu değil (sudo apt install python3-evdev)"
            log.error(self.error)
            return
        try:
            self._create_devices()
            log.info("Sanal fare/klavye oluşturuldu (düzen: %s)", self.layout_name)
        except (OSError, PermissionError) as ex:
            self.error = (
                f"/dev/uinput açılamadı: {ex}. install.sh'i çalıştırıp oturumu "
                "kapatıp açın (ya da: sudo modprobe uinput)."
            )
            log.error(self.error)

    # ------------------------------------------------------------------ kurulum
    def _create_devices(self):
        rel = [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL]
        hires = [getattr(e, n) for n in ("REL_WHEEL_HI_RES", "REL_HWHEEL_HI_RES") if hasattr(e, n)]
        self._has_hires = len(hires) == 2
        rel += hires
        self.mouse = UInput(
            {e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE], e.EV_REL: rel},
            name="Tahta Kumanda Fare",
        )
        keys = sorted({v for k, v in e.ecodes.items()
                       if k.startswith("KEY_") and isinstance(v, int) and 0 < v < 0x100})
        self.kbd = UInput({e.EV_KEY: keys}, name="Tahta Kumanda Klavye")

    @property
    def ok(self) -> bool:
        return self.mouse is not None and self.kbd is not None

    def status(self) -> dict:
        return {"ok": self.ok, "error": self.error, "layout": self.layout_name}

    def close(self):
        self.release_all()
        for dev in (self.mouse, self.kbd):
            try:
                if dev:
                    dev.close()
            except OSError:
                pass
        self.mouse = self.kbd = None

    # -------------------------------------------------------------------- fare
    def move(self, dx: int, dy: int):
        if not self.mouse or (dx == 0 and dy == 0):
            return
        if dx:
            self.mouse.write(e.EV_REL, e.REL_X, dx)
        if dy:
            self.mouse.write(e.EV_REL, e.REL_Y, dy)
        self.mouse.syn()

    def scroll(self, v: int, h: int):
        """v>0 yukarı, h>0 sağa kaydırır. Değerler 120 = 1 çentik biriminde."""
        if not self.mouse:
            return
        wrote = False
        for axis, val in (("v", v), ("h", h)):
            if not val:
                continue
            lo = e.REL_WHEEL if axis == "v" else e.REL_HWHEEL
            if self._has_hires:
                hi = e.REL_WHEEL_HI_RES if axis == "v" else e.REL_HWHEEL_HI_RES
                self.mouse.write(e.EV_REL, hi, val)
                wrote = True
            self._wheel_acc[axis] += val
            notches = int(self._wheel_acc[axis] / HI_RES_STEP)
            if notches:
                self.mouse.write(e.EV_REL, lo, notches)
                self._wheel_acc[axis] -= notches * HI_RES_STEP
                wrote = True
        if wrote:
            self.mouse.syn()

    def button(self, b: str, down: bool):
        if not self.mouse:
            return
        code = getattr(e, BUTTONS.get(b, "BTN_LEFT"))
        self.mouse.write(e.EV_KEY, code, 1 if down else 0)
        self.mouse.syn()
        (self._held_buttons.add if down else self._held_buttons.discard)(code)

    def click(self, b: str = "l", n: int = 1):
        for _ in range(max(1, min(n, 3))):
            self.button(b, True)
            self.button(b, False)

    # ----------------------------------------------------------------- klavye
    def _code(self, name: str):
        return e.ecodes.get(name) if e else None

    def _tap(self, keyname: str, mods=()):
        if not self.kbd:
            return
        code = self._code(keyname)
        if code is None:
            return
        mod_codes = [self._code(m) for m in mods]
        for mc in mod_codes:
            self.kbd.write(e.EV_KEY, mc, 1)
        if mod_codes:
            self.kbd.syn()
        self.kbd.write(e.EV_KEY, code, 1)
        self.kbd.syn()
        self.kbd.write(e.EV_KEY, code, 0)
        self.kbd.syn()
        for mc in reversed(mod_codes):
            self.kbd.write(e.EV_KEY, mc, 0)
        if mod_codes:
            self.kbd.syn()

    def key(self, name: str, n: int = 1):
        keyname = SPECIAL_KEYS.get(name.lower())
        if not keyname:
            return
        for _ in range(max(1, min(n, 200))):
            self._tap(keyname)

    def combo(self, names):
        """Örn. ["ctrl", "c"] veya ["alt", "tab"]"""
        if not self.kbd or not names:
            return
        codes = []
        for n in names[:5]:
            n = str(n)
            keyname = SPECIAL_KEYS.get(n.lower())
            if not keyname and len(n) == 1:
                entry = self.charmap.get(n.lower()) or self.charmap.get(n)
                keyname = entry[0] if entry else None
            code = self._code(keyname) if keyname else None
            if code is None:
                return
            codes.append(code)
        for c in codes:
            self.kbd.write(e.EV_KEY, c, 1)
            self.kbd.syn()
        for c in reversed(codes):
            self.kbd.write(e.EV_KEY, c, 0)
        self.kbd.syn()

    async def type_text(self, text: str):
        if not self.kbd:
            return
        text = normalize(text)
        unmapped = []
        for ch in text:
            if ch == "\n":
                await self._flush_unmapped(unmapped)
                self._tap("KEY_ENTER")
            elif ch == "\t":
                await self._flush_unmapped(unmapped)
                self._tap("KEY_TAB")
            elif ch in self.charmap:
                await self._flush_unmapped(unmapped)
                keyname, mods, dead = self.charmap[ch]
                self._tap(keyname, mods)
                if dead:
                    self._tap("KEY_SPACE")
            else:
                unmapped.append(ch)
                continue
            # Uygulamaların olayları kaçırmaması için çok kısa bekleme
            await asyncio.sleep(0.003)
        await self._flush_unmapped(unmapped)

    async def _flush_unmapped(self, buf: list):
        """Düzende olmayan karakterler (emoji, Arapça vb.) için X11'de xdotool."""
        if not buf:
            return
        text = "".join(buf)
        buf.clear()
        if not self._xdotool:
            log.info("Klavye düzeninde karşılığı olmayan karakter atlandı: %r", text)
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                self._xdotool, "type", "--delay", "5", "--", text,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), 10)
        except (OSError, asyncio.TimeoutError) as ex:
            log.warning("xdotool hatası: %s", ex)

    # ------------------------------------------------------------------ genel
    def release_all(self):
        """Bağlantı koparsa basılı kalan tuş/düğme kalmasın."""
        if self.mouse:
            for code in list(self._held_buttons):
                try:
                    self.mouse.write(e.EV_KEY, code, 0)
                    self.mouse.syn()
                except OSError:
                    pass
        self._held_buttons.clear()


__all__ = ["InputController", "SHIFT", "ALTGR"]
