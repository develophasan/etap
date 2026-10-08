#!/usr/bin/env bash
# Tahta Kumanda sunucusunu başlatır.
#   ./start.sh              -> ön planda (terminalde loglar görünür)
#   ./start.sh --arka-plan  -> arka planda başlatıp hemen döner
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Ayarları yükle
if [[ -f "$DIR/ayarlar.env" ]]; then
  set -a; . "$DIR/ayarlar.env"; set +a
fi
export TAHTA_PORT="${TAHTA_PORT:-8000}"

LOG_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/tahta-kumanda"
mkdir -p "$LOG_DIR"

PY="$DIR/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

# Zaten çalışıyor mu?
if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${TAHTA_PORT}\$"; then
  echo "Tahta Kumanda zaten çalışıyor (port $TAHTA_PORT)."
  exit 0
fi

CMD=("$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$TAHTA_PORT" --no-access-log)

if [[ "${1:-}" == "--arka-plan" ]]; then
  nohup "${CMD[@]}" >>"$LOG_DIR/sunucu.log" 2>&1 &
  echo "Arka planda başlatıldı. Log: $LOG_DIR/sunucu.log"
elif [[ -t 1 ]]; then
  exec "${CMD[@]}"
else
  # Otomatik başlatmada terminal yok: logu dosyaya yaz (büyüyünce sıfırla)
  [[ -f "$LOG_DIR/sunucu.log" && $(stat -c%s "$LOG_DIR/sunucu.log") -gt 5000000 ]] && : > "$LOG_DIR/sunucu.log"
  exec "${CMD[@]}" >>"$LOG_DIR/sunucu.log" 2>&1
fi
