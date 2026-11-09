#!/usr/bin/env bash
# Tahta Kumanda masaüstü panelini açar (panel, sunucu kapalıysa onu da başlatır).
# Panel zaten açıksa gizlenmiş pencereyi yeniden gösterir.
#   ./panel.sh           -> paneli göster
#   ./panel.sh --gizli   -> arka planda başlat, pencere açma
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$DIR"
# Ayarları yükle: sistem geneli -> program klasörü -> kullanıcı (sonraki öncekini ezer)
for f in /etc/tahta-kumanda/ayarlar.env "$DIR/ayarlar.env" "${XDG_CONFIG_HOME:-$HOME/.config}/tahta-kumanda/ayarlar.env"; do
  [[ -f "$f" ]] && { set -a; . "$f"; set +a; }
done

if /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null; then
  exec /usr/bin/python3 "$DIR/app/panel.py" "$@"
fi

# GTK yoksa: sunucuyu başlat, bilgiyi bildirim olarak göster
export TAHTA_BILDIRIM=1
exec "$DIR/start.sh" --arka-plan
