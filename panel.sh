#!/usr/bin/env bash
# Tahta Kumanda masaüstü panelini açar (panel, sunucu kapalıysa onu da başlatır).
# Panel zaten açıksa gizlenmiş pencereyi yeniden gösterir.
#   ./panel.sh           -> paneli göster
#   ./panel.sh --gizli   -> arka planda başlat, pencere açma
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
[[ -f "$DIR/ayarlar.env" ]] && { set -a; . "$DIR/ayarlar.env"; set +a; }

if /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null; then
  exec /usr/bin/python3 "$DIR/app/panel.py" "$@"
fi

# GTK yoksa: sunucuyu başlat, bilgiyi bildirim olarak göster
export TAHTA_BILDIRIM=1
exec "$DIR/start.sh" --arka-plan
