#!/usr/bin/env bash
# Tahta Kumanda kurulum betiği - Pardus 23 / Debian 12 (X11 ve Wayland)
# Kullanım:  chmod +x install.sh && ./install.sh     (root olarak DEĞİL, tahtadaki kullanıcıyla)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(id -un)"
PORT="${TAHTA_PORT:-8000}"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[uyarı] %s\033[0m\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
  echo "Bu betiği root olarak değil, tahtada oturum açan kullanıcıyla çalıştırın: ./install.sh"
  echo "(Gerekli yerlerde sudo şifresi sorulacak.)"
  exit 1
fi

# ---------------------------------------------------------------- 1) Paketler
say "1/7 Sistem paketleri kuruluyor"
sudo apt-get update

REQUIRED=(
  python3 python3-venv python3-pip
  python3-evdev            # uinput ile sanal fare/klavye
  python3-fastapi python3-uvicorn python3-websockets   # internet yoksa bile çalışsın
  avahi-daemon libnss-mdns # AirPlay/mDNS keşfi
  curl unzip iproute2 libnotify-bin
)
OPTIONAL=(
  uxplay                   # iPhone/iPad AirPlay alıcısı
  scrcpy                   # Android ekran yansıtma
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
  gstreamer1.0-libav gstreamer1.0-gl gstreamer1.0-x
  gstreamer1.0-vaapi       # Intel/AMD donanımsal video çözme (varsa)
  xdotool                  # X11'de klavye düzeninde olmayan karakterler için yedek
)
sudo apt-get install -y "${REQUIRED[@]}"
for p in "${OPTIONAL[@]}"; do
  sudo apt-get install -y "$p" >/dev/null 2>&1 && echo "  + $p" || warn "$p kurulamadı (depoda yok olabilir)"
done

# ---------------------------------------------------------- 2) uinput izni
say "2/7 /dev/uinput izinleri ayarlanıyor"
echo uinput | sudo tee /etc/modules-load.d/tahta-kumanda.conf >/dev/null
sudo modprobe uinput || warn "uinput modülü yüklenemedi"
sudo tee /etc/udev/rules.d/60-tahta-kumanda-uinput.rules >/dev/null <<'EOF'
# Tahta Kumanda: oturumdaki kullanıcı ve 'input' grubu sanal fare/klavye oluşturabilsin
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput 2>/dev/null || sudo udevadm trigger
sudo usermod -aG input "$USER_NAME"

# ------------------------------------------------------- 3) adb (Android)
say "3/7 Android platform-tools (adb) indiriliyor"
if [[ "$(uname -m)" == "x86_64" ]]; then
  mkdir -p "$DIR/tools"
  TMPZIP="$(mktemp --suffix=.zip)"
  if curl -fL --retry 2 -o "$TMPZIP" https://dl.google.com/android/repository/platform-tools-latest-linux.zip; then
    rm -rf "$DIR/tools/platform-tools"
    unzip -oq "$TMPZIP" -d "$DIR/tools"
    echo "  adb sürümü: $("$DIR/tools/platform-tools/adb" version | head -1)"
  else
    warn "platform-tools indirilemedi; depodaki adb kuruluyor (kablosuz eşleştirme için adb 30+ gerekir)"
    sudo apt-get install -y adb || true
  fi
  rm -f "$TMPZIP"
else
  warn "x86_64 değil; depodaki adb kullanılacak"
  sudo apt-get install -y adb || true
fi

# ------------------------------------------------------ 4) Python ortamı
say "4/7 Python sanal ortamı hazırlanıyor"
python3 -m venv --system-site-packages "$DIR/.venv"
if ! "$DIR/.venv/bin/pip" install --upgrade -q -r "$DIR/requirements.txt"; then
  warn "pip ile güncellenemedi (internet yok?). Depodaki FastAPI/Uvicorn kullanılacak."
fi
"$DIR/.venv/bin/python" -c "import fastapi, uvicorn, evdev; print('  fastapi', fastapi.__version__, '| uvicorn', uvicorn.__version__)"

# -------------------------------------------------- 5) mDNS ve güvenlik duvarı
say "5/7 Avahi (mDNS) ve güvenlik duvarı"
sudo systemctl enable --now avahi-daemon || warn "avahi-daemon başlatılamadı"
if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow "$PORT"/tcp comment "Tahta Kumanda"
  sudo ufw allow 7000,7001,7100/tcp comment "UxPlay AirPlay"
  sudo ufw allow 6000,6001,7011/udp comment "UxPlay AirPlay"
  sudo ufw allow 5353/udp comment "mDNS"
  echo "  ufw kuralları eklendi"
else
  echo "  ufw etkin değil, atlandı"
fi

# ---------------------------------------------- 6) Otomatik başlatma + kısayollar
say "6/7 Oturum açılınca otomatik başlatma ayarlanıyor"
chmod +x "$DIR/start.sh" "$DIR/bilgi.sh"
[[ -f "$DIR/ayarlar.env" ]] || cp "$DIR/ayarlar.env.ornek" "$DIR/ayarlar.env"
mkdir -p "$HOME/.config/autostart" "$HOME/.local/share/applications"

cat > "$HOME/.config/autostart/tahta-kumanda.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tahta Kumanda
Comment=Telefondan fare/klavye ve ekran yansıtma sunucusu
Exec="$DIR/start.sh"
Icon=input-tablet
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
EOF

cat > "$HOME/.local/share/applications/tahta-kumanda-bilgi.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tahta Kumanda Bilgi
Comment=Telefondan bağlanmak için adres ve PIN
Exec="$DIR/bilgi.sh"
Icon=input-tablet
Terminal=false
Categories=Education;Utility;
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" || true

# ---------------------------------------------------------------- 7) Bitti
say "7/7 Kurulum tamamlandı"
cat <<EOF

  • ÖNEMLİ: uinput izninin kesin uygulanması için oturumu bir kez kapatıp açın
    (veya tahtayı yeniden başlatın).
  • Sunucu her oturum açılışında otomatik başlar. Elle başlatmak için:
        $DIR/start.sh
  • Uygulama menüsündeki "Tahta Kumanda Bilgi" kısayolu adresi ve PIN'i tahtada büyük gösterir.
  • Ayarlar (klavye düzeni, AirPlay adı, PIN): $DIR/ayarlar.env

EOF
