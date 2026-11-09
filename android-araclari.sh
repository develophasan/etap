#!/usr/bin/env bash
# Android ekran yansıtma için güncel adb'yi (Google platform-tools) kullanıcı klasörüne indirir.
# Pardus 23 deposundaki adb, kablosuz eşleştirmeyi (adb pair) desteklemeyen eski bir sürümdür.
# Tahta Kumanda paneli "Android desteğini kur" düğmesiyle bu betiği çalıştırır.
set -euo pipefail
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/tahta-kumanda"
URL="https://dl.google.com/android/repository/platform-tools-latest-linux.zip"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "Bu bilgisayar x86_64 değil; Google platform-tools yalnızca x86_64 için yayınlanıyor." >&2
  exit 2
fi
mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "İndiriliyor: $URL"
curl -fL --retry 2 --connect-timeout 15 -o "$TMP/pt.zip" "$URL"
unzip -q "$TMP/pt.zip" -d "$TMP"
rm -rf "$DEST/platform-tools"
mv "$TMP/platform-tools" "$DEST/platform-tools"
"$DEST/platform-tools/adb" version | head -2
echo "Tamam: $DEST/platform-tools/adb"
