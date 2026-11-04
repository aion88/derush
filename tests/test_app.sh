#!/usr/bin/env bash
# Derush.app: built into a temp dir, launched from a bare environment. Port 8799. No /Applications.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
DERUSH_PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"
REALHOME="$HOME"
T="$(mktemp -d)"; PORT=8799
cleanup() { HOME="$T/home" DERUSH_EDIT_PORT=$PORT "$ROOT/bin/derush" stop >/dev/null 2>&1
  pkill -f "edit_server.py $T/out" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
mkdir -p "$T/home" "$T/dest"
# the real venv is found through HOME, so the throwaway HOME links to it
mkdir -p "$T/home/.local/share/derush"; ln -s "$REALHOME/.local/share/derush/venv" "$T/home/.local/share/derush/venv"
count() { pgrep -f "edit_server.py $T/out" | wc -l | tr -d ' '; }

# 1. build
bash "$ROOT/app/build-app.sh" "$T/dest" >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "build-app.sh exits 0"
APP="$T/dest/Derush.app"
assert_eq 0 "$(plutil -lint "$APP/Contents/Info.plist" >/dev/null 2>&1; echo $?)" "Info.plist lints"
pl() { plutil -extract "$1" raw -o - "$APP/Contents/Info.plist" 2>/dev/null; }
assert_eq com.derush.app "$(pl CFBundleIdentifier)" "bundle id"
assert_eq Derush "$(pl CFBundleName)" "bundle name"
assert_eq false "$(pl LSUIElement)" "LSUIElement false"
assert_eq Derush "$(pl CFBundleExecutable)" "executable name"
[ -x "$APP/Contents/MacOS/Derush" ] && ok=1 || ok=0; assert_eq 1 "$ok" "launcher executable"
[ -s "$APP/Contents/Resources/icon.icns" ] && ok=1 || ok=0; assert_eq 1 "$ok" "icon.icns present"
assert_contains "$(cat "$APP/Contents/MacOS/Derush")" "$ROOT" "ROOT baked into the launcher"

cat > "$T/opener" <<OP
#!/bin/sh
echo "\$1" >> "$T/opened.log"
OP
chmod +x "$T/opener"

# 2. bare environment: no PATH to Homebrew, launcher must find ffmpeg and the venv itself
env -i HOME="$T/home" DERUSH_EDIT_PORT=$PORT DERUSH_CONFIG="$T/none" DERUSH_OUT_ROOT="$T/out" \
  DERUSH_OPEN="$T/opener" "$APP/Contents/MacOS/Derush" >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "launcher exits 0 from env -i"
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "studio answers after launch"
assert_contains "$(cat "$T/opened.log" 2>/dev/null)" "http://127.0.0.1:$PORT" "browser stub got the studio URL"
assert_eq 1 "$(count)" "one server process"

# 3. second launch reuses
env -i HOME="$T/home" DERUSH_EDIT_PORT=$PORT DERUSH_CONFIG="$T/none" DERUSH_OUT_ROOT="$T/out" \
  DERUSH_OPEN="$T/opener" "$APP/Contents/MacOS/Derush" >/dev/null 2>&1
assert_eq 1 "$(count)" "second launch: still one server"
assert_eq 2 "$(wc -l < "$T/opened.log" | tr -d ' ')" "second launch opened the browser again"

# 4. a render job through the studio, server started from a bare env (ffmpeg only via the launcher's PATH)
bash "$ROOT/tests/make_fixture.sh" "$T" >/dev/null
env -i HOME="$T/home" DERUSH_CONFIG="$T/none" DERUSH_OUT_ROOT="$T/out" \
  "$ROOT/bin/derush" prep "$T/fixture test.mov" >"$T/prep.log" 2>&1; rc=$?
assert_eq 0 "$rc" "prep on the fixture"
curl -s -X POST "http://127.0.0.1:$PORT/render?v=fixture%20test" >/dev/null
M="$T/out/fixture test/fixture test.derush.mp4"
for _ in $(seq 1 120); do [ -s "$M" ] && break; sleep 1; done
[ -s "$M" ] && ok=1 || ok=0
assert_eq 1 "$ok" "render job through the studio produced derush.mp4"

# 5. failure path: foreign program on the port -> notification command, no browser
HOME="$T/home" DERUSH_EDIT_PORT=$PORT "$ROOT/bin/derush" stop >/dev/null 2>&1; sleep 1
"$DERUSH_PY" -m http.server $PORT --bind 127.0.0.1 >/dev/null 2>&1 & HP=$!
for _ in $(seq 1 20); do nc -z 127.0.0.1 $PORT 2>/dev/null && break; sleep 0.5; done
mkdir -p "$T/shim"
cat > "$T/shim/osascript" <<OS
#!/bin/sh
echo "\$*" >> "$T/notif.log"
OS
chmod +x "$T/shim/osascript"
: > "$T/opened.log"
PATH="$T/shim:$PATH" HOME="$T/home" DERUSH_EDIT_PORT=$PORT DERUSH_CONFIG="$T/none" DERUSH_OUT_ROOT="$T/out" \
  DERUSH_OPEN="$T/opener" "$APP/Contents/MacOS/Derush" >/dev/null 2>&1; rc=$?
kill "$HP" 2>/dev/null
assert_eq 3 "$rc" "launcher passes on exit 3"
assert_contains "$(cat "$T/notif.log" 2>/dev/null)" "display notification" "failure shows a notification"
assert_contains "$(cat "$T/notif.log" 2>/dev/null)" "pris par un autre programme" "notification carries the message"
assert_contains "$(cat "$T/notif.log" 2>/dev/null)" "studio.log" "notification names the log"
assert_eq 0 "$(wc -c < "$T/opened.log" | tr -d ' ')" "no browser opened on failure"

# 6. a clone under a path with a space AND an apostrophe: ROOT must be baked safely
HOME="$T/home" DERUSH_EDIT_PORT=$PORT "$ROOT/bin/derush" stop >/dev/null 2>&1; sleep 1
Q="$T/Cynthia's Projects/der ush"; mkdir -p "$Q" "$T/dest2"
cp -R "$ROOT/bin" "$ROOT/derush" "$ROOT/app" "$Q/"
bash "$Q/app/build-app.sh" "$T/dest2" >/dev/null 2>&1
: > "$T/opened.log"
env -i HOME="$T/home" DERUSH_EDIT_PORT=$PORT DERUSH_CONFIG="$T/none" DERUSH_OUT_ROOT="$T/out" \
  DERUSH_OPEN="$T/opener" "$T/dest2/Derush.app/Contents/MacOS/Derush" >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "apostrophe path: launcher exits 0"
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "apostrophe path: studio answers"
assert_contains "$(ps -ax -o command= | grep edit_server.py | grep -v grep)" "$Q/derush/edit_server.py" "apostrophe path: it runs that copy's server"
summary
