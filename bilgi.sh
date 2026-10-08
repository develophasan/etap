#!/usr/bin/env bash
# Sunucu kapalıysa başlatır ve bağlantı bilgisini (adres + PIN) tahtada tam ekran gösterir.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$DIR/ayarlar.env" ]] && { set -a; . "$DIR/ayarlar.env"; set +a; }
PORT="${TAHTA_PORT:-8000}"
"$DIR/start.sh" --arka-plan >/dev/null
for _ in $(seq 1 20); do
  curl -fs "http://127.0.0.1:$PORT/api/info" >/dev/null 2>&1 && break
  sleep 0.5
done
xdg-open "http://127.0.0.1:$PORT/bilgi" >/dev/null 2>&1 &
