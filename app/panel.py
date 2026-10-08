#!/usr/bin/env python3
"""
Tahta Kumanda masaüstü paneli (GTK3).

- Oturum açılınca otomatik açılır, sunucu kapalıysa başlatır.
- Telefondan bağlanmak için adres, PIN, Wi-Fi adı ve QR kodu gösterir.
- "Gizle" ile kaybolur; tekrar göstermek için uygulama menüsünden
  "Tahta Kumanda"yı açın, sistem tepsisindeki simgeye tıklayın ya da
  telefondaki Ayarlar > "Bağlantı panelini tahtada göster" düğmesine basın.

Kullanım:  python3 app/panel.py [--gizli]
"""

import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import panel_core as core  # noqa: E402

APP_ID = "tr.org.tahtakumanda.Panel"
POLL_SECONDS = 2

# Sistem tepsisi simgesi (varsa). Pardus GNOME'da AppIndicator eklentisi ile görünür.
Indicator = None
for _ns in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(_ns, "0.1")
        Indicator = getattr(__import__("gi.repository", fromlist=[_ns]), _ns)
        break
    except (ValueError, ImportError, AttributeError):
        continue

CSS = b"""
window.tk-panel { background-color: #11151c; color: #e8edf4; }
.tk-title { font-size: 18px; font-weight: bold; color: #e8edf4; }
.tk-sub { font-size: 13px; color: #9aa7b8; }
.tk-card { background-color: #171c25; border-radius: 16px; padding: 18px; border: 1px solid #2b3442; }
.tk-hint { font-size: 13px; color: #9aa7b8; }
.tk-url { font-size: 28px; font-weight: bold; color: #ffffff; }
.tk-pin-label { font-size: 15px; color: #9aa7b8; }
.tk-pin { font-size: 44px; font-weight: bold; color: #7cc4ff; letter-spacing: 6px; }
.tk-wifi { font-size: 16px; color: #c9d3df; }
.tk-qr { background-color: #ffffff; border-radius: 12px; padding: 8px; }
.tk-row-k { font-size: 13px; color: #9aa7b8; }
.tk-row-v { font-size: 13px; color: #e8edf4; }
.tk-ok { color: #3ccf8e; }
.tk-bad { color: #ff8a8a; }
.tk-dot-on { color: #3ccf8e; }
.tk-dot-wait { color: #f5b84a; }
.tk-dot-off { color: #ff6b6b; }
.tk-copy { font-size: 12px; color: #6f7b8c; }
.tk-copy link, .tk-copy *:link { color: #7cc4ff; }
button.tk-btn { min-height: 40px; border-radius: 10px; font-weight: bold; padding: 0 12px; }
button.tk-primary { background-image: none; background-color: #1f7fe0; color: #ffffff; border-color: #3fa2ff; }
"""


class PanelWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Tahta Kumanda")
        self.app = app
        self.set_default_size(470, -1)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("input-tablet")
        self.get_style_context().add_class("tk-panel")
        self.connect("delete-event", self._on_close)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_border_width(18)
        self.add(outer)

        # Başlık
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.dot = Gtk.Label(label="●")
        self.dot.get_style_context().add_class("tk-dot-off")
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t = Gtk.Label(label="Tahta Kumanda", xalign=0)
        t.get_style_context().add_class("tk-title")
        self.headline = Gtk.Label(label="Sunucu başlatılıyor…", xalign=0)
        self.headline.get_style_context().add_class("tk-sub")
        titles.pack_start(t, False, False, 0)
        titles.pack_start(self.headline, False, False, 0)
        head.pack_start(self.dot, False, False, 0)
        head.pack_start(titles, True, True, 0)
        outer.pack_start(head, False, False, 0)

        # Bağlantı kartı
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("tk-card")
        hint = Gtk.Label(label="Telefonun tarayıcısına bu adresi yazın\nya da QR kodu kamerayla okutun",
                         justify=Gtk.Justification.CENTER)
        hint.get_style_context().add_class("tk-hint")
        card.pack_start(hint, False, False, 0)

        self.qr = Gtk.Image()
        self.qr.get_style_context().add_class("tk-qr")
        self.qr.set_halign(Gtk.Align.CENTER)
        self.qr.set_no_show_all(True)
        card.pack_start(self.qr, False, False, 6)

        self.url = Gtk.Label(label="…", selectable=True)
        self.url.get_style_context().add_class("tk-url")
        card.pack_start(self.url, False, False, 0)

        pinbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        pinbox.set_halign(Gtk.Align.CENTER)
        pl = Gtk.Label(label="PIN")
        pl.get_style_context().add_class("tk-pin-label")
        self.pin = Gtk.Label(label="----", selectable=True)
        self.pin.get_style_context().add_class("tk-pin")
        pinbox.pack_start(pl, False, False, 0)
        pinbox.pack_start(self.pin, False, False, 0)
        card.pack_start(pinbox, False, False, 2)

        self.wifi = Gtk.Label(label="Wi-Fi: …")
        self.wifi.get_style_context().add_class("tk-wifi")
        card.pack_start(self.wifi, False, False, 0)
        outer.pack_start(card, False, False, 0)

        # Durum satırları
        self.grid = Gtk.Grid(column_spacing=14, row_spacing=6)
        self.row_vals = []
        for i, name in enumerate(("Fare / klavye", "iPhone yansıtma", "Android yansıtma")):
            k = Gtk.Label(label=name, xalign=0)
            k.get_style_context().add_class("tk-row-k")
            v = Gtk.Label(label="…", xalign=0)
            v.set_line_wrap(True)
            v.set_max_width_chars(40)
            v.get_style_context().add_class("tk-row-v")
            self.grid.attach(k, 0, i, 1, 1)
            self.grid.attach(v, 1, i, 1, 1)
            self.row_vals.append(v)
        outer.pack_start(self.grid, False, False, 0)

        # Düğmeler
        bgrid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        b_hide = self._btn("Gizle", self.hide_panel, primary=True)
        b_full = self._btn("Tam ekran göster", lambda *_: self.app.show_fullscreen_info())
        b_files = self._btn("Gelen dosyalar", lambda *_: self.app.open_files())
        b_pin = self._btn("Yeni PIN", self._on_new_pin)
        b_restart = self._btn("Sunucuyu yeniden başlat", self._on_restart)
        bgrid.attach(b_hide, 0, 0, 1, 1)
        bgrid.attach(b_full, 1, 0, 1, 1)
        bgrid.attach(b_files, 0, 1, 1, 1)
        bgrid.attach(b_pin, 1, 1, 1, 1)
        bgrid.attach(b_restart, 0, 2, 2, 1)
        outer.pack_start(bgrid, False, False, 0)

        tip = ("Gizledikten sonra tekrar açmak için: uygulama menüsünden “Tahta Kumanda”"
               + (", sistem tepsisindeki simge" if Indicator else "")
               + " ya da telefonda Ayarlar → “Bağlantı panelini tahtada göster”.")
        self.tip = Gtk.Label(label=tip, xalign=0)
        self.tip.set_line_wrap(True)
        self.tip.set_max_width_chars(52)
        self.tip.get_style_context().add_class("tk-hint")
        outer.pack_start(self.tip, False, False, 0)

        copy = Gtk.Label(xalign=0.5)
        copy.set_markup('© 2026 <a href="https://github.com/develophasan" title="github.com/develophasan">'
                        'Hasan Özdemir</a>. Tüm hakları saklıdır.')
        copy.get_style_context().add_class("tk-copy")
        outer.pack_start(copy, False, False, 0)

        self._qr_for = None

    def _btn(self, label, cb, primary=False):
        b = Gtk.Button(label=label)
        b.get_style_context().add_class("tk-btn")
        if primary:
            b.get_style_context().add_class("tk-primary")
        b.connect("clicked", cb)
        return b

    # ------------------------------------------------------------ olaylar
    def _on_close(self, *_):
        self.hide_panel()
        return True  # pencereyi yok etme, yalnızca gizle

    def hide_panel(self, *_):
        self.hide()

    def _on_new_pin(self, *_):
        def work():
            r = core.new_pin()
            GLib.idle_add(self._after_new_pin, r)
        threading.Thread(target=work, daemon=True).start()

    def _after_new_pin(self, r):
        if r.get("ok"):
            self.pin.set_text(r.get("pin", ""))
        else:
            self._message("PIN değiştirilemedi", r.get("message", ""))
        return False

    def _on_restart(self, button):
        button.set_sensitive(False)
        self.headline.set_text("Sunucu yeniden başlatılıyor…")

        def work():
            core.stop_server()
            import time
            time.sleep(1.5)
            core.start_server()
            GLib.timeout_add_seconds(3, lambda: (button.set_sensitive(True), False)[1])
        threading.Thread(target=work, daemon=True).start()

    def _message(self, title, text):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.OK, text=title)
        dlg.format_secondary_text(text)
        dlg.run()
        dlg.destroy()

    # ------------------------------------------------------------ güncelle
    def update(self, d):
        info = core.describe(d)
        ctx = self.dot.get_style_context()
        for c in ("tk-dot-on", "tk-dot-wait", "tk-dot-off"):
            ctx.remove_class(c)
        ctx.add_class("tk-dot-" + info["state"])
        self.headline.set_text(info["headline"])

        if d:
            self.url.set_text(d.get("url", "").replace("http://", ""))
            self.pin.set_text(d.get("pin") or "kapalı")
            self.wifi.set_markup("Wi-Fi: <b>%s</b>" % GLib.markup_escape_text(d.get("wifi") or "bilinmiyor"))
            if d.get("url") != self._qr_for and d.get("online"):
                self._qr_for = d.get("url")
                png = core.make_qr_png(self._qr_for)
                if png:
                    self.qr.set_from_file(png)
                    self.qr.show()
                else:
                    self.qr.hide()
        for lbl, (_, text, ok) in zip(self.row_vals, info["rows"]):
            lbl.set_text(text)
            c = lbl.get_style_context()
            c.remove_class("tk-ok")
            c.remove_class("tk-bad")
            c.add_class("tk-ok" if ok else "tk-bad")


class PanelApp(Gtk.Application):
    def __init__(self, start_hidden=False):
        super().__init__(application_id=APP_ID)
        self.start_hidden = start_hidden
        self.win = None
        self.indicator = None
        self.last = None
        self.show_seq = None
        self._polling = False
        self._fails = 0

    # İlk açılışta bir kez
    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # pencere gizliyken de uygulama açık kalsın
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win = PanelWindow(self)
        self.win.show_all()
        self.win.qr.hide()
        if self.start_hidden:
            self.win.hide()
        self._setup_indicator()
        if core.fetch_status() is None:
            core.start_server()
        self._poll()
        GLib.timeout_add_seconds(POLL_SECONDS, self._poll)

    # Her açılışta (ikinci kez açılınca da) -> paneli göster
    def do_activate(self):
        if self.start_hidden:
            self.start_hidden = False
            return
        self.show_panel()

    # ------------------------------------------------------------ eylemler
    def show_panel(self, *_):
        self.win.show()
        self.win.deiconify()
        self.win.present()

    def toggle_panel(self, *_):
        if self.win.get_visible():
            self.win.hide()
        else:
            self.show_panel()

    def show_fullscreen_info(self, *_):
        core.open_path(f"http://127.0.0.1:{core.port()}/bilgi")

    def open_files(self, *_):
        d = self.last or {}
        core.open_path(d.get("files_dir") or str(core.BASE_DIR))

    def quit_panel(self, *_):
        self.release()
        self.quit()

    # ------------------------------------------------------------ tepsi
    def _setup_indicator(self):
        if not Indicator:
            return
        try:
            ind = Indicator.Indicator.new("tahta-kumanda", "input-tablet",
                                          Indicator.IndicatorCategory.APPLICATION_STATUS)
            ind.set_status(Indicator.IndicatorStatus.ACTIVE)
            ind.set_title("Tahta Kumanda")
            menu = Gtk.Menu()
            for label, cb in (("Paneli göster / gizle", self.toggle_panel),
                              ("Tam ekran bağlantı bilgisi", self.show_fullscreen_info),
                              ("Gelen dosyalar", self.open_files),
                              (None, None),
                              ("Paneli kapat (sunucu çalışmaya devam eder)", self.quit_panel)):
                item = Gtk.SeparatorMenuItem() if label is None else Gtk.MenuItem(label=label)
                if cb:
                    item.connect("activate", cb)
                menu.append(item)
            menu.show_all()
            ind.set_menu(menu)
            self.indicator = ind
        except Exception:  # tepsi desteklenmiyorsa panel yine çalışır
            self.indicator = None

    # ------------------------------------------------------------ yoklama
    def _poll(self):
        if not self._polling:
            self._polling = True
            threading.Thread(target=self._poll_worker, daemon=True).start()
        return True

    def _poll_worker(self):
        d = core.fetch_status()
        GLib.idle_add(self._apply, d)

    def _apply(self, d):
        self._polling = False
        if d is None:
            self._fails += 1
            # Sunucu ~20 sn yanıt vermezse yeniden başlatmayı dene
            if self._fails % 10 == 0:
                core.start_server()
        else:
            self._fails = 0
            seq = d.get("show_seq")
            if self.show_seq is not None and seq != self.show_seq:
                self.show_panel()
            self.show_seq = seq
        self.last = d or self.last
        self.win.update(d)
        return False


def main():
    hidden = "--gizli" in sys.argv[1:]
    app = PanelApp(start_hidden=hidden)
    return app.run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
