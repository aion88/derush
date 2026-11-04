#!/usr/bin/env bash
# build-app.sh <dest_dir> : builds <dest_dir>/Derush.app, with this checkout's path baked in the launcher.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEST="${1:?usage: build-app.sh <dest_dir>}"
APP="$DEST/Derush.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
cp "$HERE/icon.icns" "$APP/Contents/Resources/icon.icns"
# '|' as sed delimiter; a path holding '|' or '&' is escaped
esc="$(printf '%s' "$ROOT" | sed -e 's/[\\|&]/\\&/g')"
sed "s|@ROOT@|$esc|" "$HERE/launcher.sh" > "$APP/Contents/MacOS/Derush"
chmod +x "$APP/Contents/MacOS/Derush"
plutil -lint "$APP/Contents/Info.plist" >/dev/null
echo "$APP"
