#!/usr/bin/env bash
# Tahta Kumanda .deb paketini üretir:  ./paketle.sh   ->  dist/tahta-kumanda_<sürüm>_all.deb
# Gereken: dpkg-deb (Pardus/Debian'da hazır gelir)
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
VERSION="$(tr -d '[:space:]' < "$DIR/VERSION")"
PKG=tahta-kumanda
MAINTAINER="${PAKET_SORUMLUSU:-Hasan Özdemir <gamzehasanozdemir@gmail.com>}"
OUT="$DIR/dist"
ROOT="$(mktemp -d)/${PKG}_${VERSION}_all"
trap 'rm -rf "$(dirname "$ROOT")"' EXIT

SHARE="$ROOT/usr/share/$PKG"
mkdir -p "$SHARE/app" "$SHARE/static" "$ROOT/usr/bin" "$ROOT/DEBIAN" \
         "$ROOT/usr/share/applications" "$ROOT/etc/xdg/autostart" "$ROOT/etc/$PKG" \
         "$ROOT/lib/udev/rules.d" "$ROOT/usr/lib/modules-load.d" \
         "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/metainfo" \
         "$ROOT/usr/share/doc/$PKG"

# ---------------------------------------------------------------- program dosyaları
install -m 644 "$DIR"/app/*.py "$SHARE/app/"
install -m 755 "$DIR/app/panel.py" "$SHARE/app/panel.py"
install -m 644 "$DIR"/static/* "$SHARE/static/"
for f in start.sh panel.sh bilgi.sh android-araclari.sh; do install -m 755 "$DIR/$f" "$SHARE/$f"; done
install -m 644 "$DIR/ayarlar.env.ornek" "$SHARE/ayarlar.env.ornek"
ln -s "../share/$PKG/panel.sh" "$ROOT/usr/bin/tahta-kumanda"
ln -s "../share/$PKG/start.sh" "$ROOT/usr/bin/tahta-kumanda-sunucu"

# Sistem geneli ayar dosyası (kullanıcı ~/.config/tahta-kumanda/ayarlar.env ile ezebilir)
install -m 644 "$DIR/ayarlar.env.ornek" "$ROOT/etc/$PKG/ayarlar.env"

# ---------------------------------------------------------------- masaüstü entegrasyonu
install -m 644 "$DIR/data/tahta-kumanda.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/tahta-kumanda.svg"

cat > "$ROOT/usr/share/applications/tahta-kumanda.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Tahta Kumanda
Name[en]=Board Remote
GenericName=Telefondan Tahta Kontrolü
Comment=Akıllı tahtayı telefondan fare/klavye ile yönetin, ekranı yansıtın, dosya aktarın
Comment[en]=Control the smart board from a phone: mouse/keyboard, screen mirroring, file transfer
Exec=tahta-kumanda
Icon=tahta-kumanda
Terminal=false
Categories=Education;Utility;
Keywords=tahta;kumanda;telefon;yansıtma;airplay;dosya;etap;remote;mirror;
StartupNotify=false
EOF

cat > "$ROOT/etc/xdg/autostart/tahta-kumanda.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Tahta Kumanda
Comment=Oturum açılınca bağlantı panelini ve sunucuyu başlatır
Exec=tahta-kumanda
Icon=tahta-kumanda
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
EOF

cat > "$ROOT/lib/udev/rules.d/60-tahta-kumanda-uinput.rules" <<'EOF'
# Tahta Kumanda: oturumdaki kullanıcı sanal fare/klavye (uinput) oluşturabilsin
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF
echo uinput > "$ROOT/usr/lib/modules-load.d/tahta-kumanda.conf"

cat > "$ROOT/usr/share/metainfo/tr.org.tahtakumanda.metainfo.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>tr.org.tahtakumanda</id>
  <launchable type="desktop-id">tahta-kumanda.desktop</launchable>
  <name>Tahta Kumanda</name>
  <summary>Akıllı tahtayı telefondan yönetin</summary>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <developer id="io.github.develophasan"><name>Hasan Özdemir</name></developer>
  <description>
    <p>Sınıftaki Pardus akıllı tahtayı, aynı Wi-Fi ağındaki telefondan uygulama kurmadan, yalnızca tarayıcıyla yönetin.</p>
    <ul>
      <li>Dokunmatik fare (trackpad) ve Türkçe klavye</li>
      <li>Sunum kumandası: slayt ileri/geri, siyah ekran, ses</li>
      <li>iPhone/iPad ekranını AirPlay ile, Android ekranını Wi-Fi üzerinden tahtaya yansıtma</li>
      <li>Telefondan tahtaya dosya gönderme, tahtadaki dosyaları telefona indirme</li>
      <li>Tahta açılınca adres, PIN, Wi-Fi adı ve QR kodu gösteren panel</li>
    </ul>
  </description>
  <url type="homepage">https://github.com/develophasan/etap</url>
  <url type="bugtracker">https://github.com/develophasan/etap/issues</url>
  <categories><category>Education</category><category>Utility</category></categories>
  <releases><release version="$VERSION" date="$(date +%Y-%m-%d)"/></releases>
  <content_rating type="oars-1.1"/>
</component>
EOF

# ---------------------------------------------------------------- belgeler
cat > "$ROOT/usr/share/doc/$PKG/copyright" <<'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: tahta-kumanda
Upstream-Contact: Hasan Özdemir
Source: https://github.com/develophasan/etap

Files: *
Copyright: 2026 Hasan Özdemir
License: GPL-3+
 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.
 .
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in "/usr/share/common-licenses/GPL-3".
EOF
gzip -9n -c "$DIR/debian-changelog" > "$ROOT/usr/share/doc/$PKG/changelog.gz"

# ---------------------------------------------------------------- DEBIAN/
SIZE_KB="$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: all
Maintainer: $MAINTAINER
Installed-Size: $SIZE_KB
Depends: python3 (>= 3.9), python3-starlette (>= 0.26), python3-uvicorn, python3-websockets,
 python3-evdev, python3-gi, gir1.2-gtk-3.0, xdg-utils, xdg-user-dirs, iproute2, procps, curl, unzip
Recommends: uxplay, scrcpy, avahi-daemon, libnss-mdns, qrencode, libnotify-bin, xdotool,
 gir1.2-ayatanaappindicator3-0.1, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good,
 gstreamer1.0-plugins-bad, gstreamer1.0-libav, gstreamer1.0-gl, gstreamer1.0-x
Suggests: gstreamer1.0-vaapi
Section: education
Priority: optional
Homepage: https://github.com/develophasan/etap
Description: Akıllı tahtayı telefondan yönetme (fare, klavye, yansıtma, dosya)
 Tahta Kumanda, Pardus akıllı tahtayı aynı Wi-Fi ağındaki bir telefondan,
 telefona uygulama kurmadan yalnızca tarayıcıyla yönetmeyi sağlar:
 dokunmatik fare ve Türkçe klavye, sunum kumandası, iPhone (AirPlay) ve
 Android ekran yansıtma, telefon ile tahta arasında dosya aktarımı.
 Tahta açılınca bağlantı adresini, PIN'i, Wi-Fi adını ve QR kodu gösteren
 bir masaüstü paneli otomatik açılır.
EOF

cat > "$ROOT/DEBIAN/conffiles" <<EOF
/etc/$PKG/ayarlar.env
/etc/xdg/autostart/tahta-kumanda.desktop
EOF

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  modprobe uinput 2>/dev/null || true
  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger --name-match=uinput 2>/dev/null || true
  fi
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

cat > "$ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "upgrade" ]; then
  # Çalışan sunucuları ve panelleri kapat (yükseltmede yeni sürümle yeniden açılır)
  pkill -f 'python[0-9.]* -m uvicorn app\.main:app' 2>/dev/null || true
  pkill -f '/usr/share/tahta-kumanda/app/panel\.py' 2>/dev/null || true
  rm -rf /usr/share/tahta-kumanda/app/__pycache__
fi
exit 0
EOF

cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  command -v udevadm >/dev/null 2>&1 && udevadm control --reload-rules 2>/dev/null || true
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
fi
exit 0
EOF
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm" "$ROOT/DEBIAN/postrm"

mkdir -p "$OUT"
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "$OUT/${PKG}_${VERSION}_all.deb" >/dev/null
echo "Hazır: $OUT/${PKG}_${VERSION}_all.deb"
