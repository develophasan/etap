#!/usr/bin/env bash
# Sunucu kapalıysa başlatır ve bağlantı bilgisini (adres + PIN) tahtada tam ekran gösterir.
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# Ayarları yükle: sistem geneli -> program klasörü -> kullanıcı (sonraki öncekini ezer)
for f in /etc/tahta-kumanda/ayarlar.env "$DIR/ayarlar.env" "${XDG_CONFIG_HOME:-$HOME/.config}/tahta-kumanda/ayarlar.env"; do
  [[ -f "$f" ]] && { set -a; . "$f"; set +a; }
done
PORT="${TAHTA_PORT:-8000}"
"$DIR/start.sh" --arka-plan >/dev/null
for _ in $(seq 1 20); do
  curl -fs "http://127.0.0.1:$PORT/api/info" >/dev/null 2>&1 && break
  sleep 0.5
done
xdg-open "http://127.0.0.1:$PORT/bilgi" >/dev/null 2>&1 &
