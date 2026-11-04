#!/usr/bin/env bash
# Studio lifecycle: --no-open, reuse, job through bin/derush, stop, foreign port. Port 8799.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
DERUSH_PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"
export DERUSH_PY
T="$(mktemp -d)"; PORT=8799
export HOME="$T/home"; mkdir -p "$HOME"          # throwaway HOME: logs and pid stay out of the real one
export DERUSH_CONFIG="$T/none" DERUSH_EDIT_PORT=$PORT DERUSH_OUT_ROOT="$T/out"
HTTP_PID=""
cleanup() { "$ROOT/bin/derush" stop >/dev/null 2>&1; [ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null
  pkill -f "edit_server.py $T/out" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
D="$ROOT/bin/derush"
count() { pgrep -f "edit_server.py $T/out" | wc -l | tr -d ' '; }

# 1. start detached, no browser
out="$("$D" studio --no-open 2>&1)"; rc=$?
assert_eq 0 "$rc" "studio --no-open exits 0"
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "/health answers derush"
pid1="$(cat "$HOME/Library/Logs/derush/studio.pid")"
assert_eq 1 "$(count)" "one server process"

# 2. second start reuses; with an opener it opens once, without --no-open
echo 0 > "$T/opened"
cat > "$T/opener" <<OP
#!/bin/sh
echo "\$1" >> "$T/opened.log"
OP
chmod +x "$T/opener"
DERUSH_OPEN="$T/opener" "$D" studio >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "second studio exits 0"
assert_eq "$pid1" "$(cat "$HOME/Library/Logs/derush/studio.pid")" "same pid after reuse"
assert_eq 1 "$(count)" "still one server process"
assert_contains "$(cat "$T/opened.log" 2>/dev/null)" "http://127.0.0.1:$PORT" "reuse opened the browser"
# edit <STEM> on a running studio: opens /edit?v=, no second server
mkdir -p "$T/out/fixture test/_work"
bash "$ROOT/tests/make_fixture.sh" "$T" >/dev/null
echo "$T/fixture test.mov" > "$T/out/fixture test/_work/source.txt"
echo "{}" > "$T/out/fixture test/_work/aligned.json"
DERUSH_OPEN="$T/opener" "$D" edit "fixture test" >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "edit on running studio exits 0"
assert_contains "$(cat "$T/opened.log")" "/edit?v=fixture%20test" "edit opened /edit?v=<stem>"
assert_eq 1 "$(count)" "edit started no second server"

# 3. a real job through the HTTP API runs bin/derush (proves the path passed to the server)
rm -f "$T/out/fixture test/_work/proxy.mp4"   # edit already made one: remove it so the job must recreate it
curl -s -X POST "http://127.0.0.1:$PORT/proxy?v=fixture%20test" >/dev/null
for _ in $(seq 1 60); do [ -s "$T/out/fixture test/_work/proxy.mp4" ] && break; sleep 1; done
[ -s "$T/out/fixture test/_work/proxy.mp4" ] && ok=1 || ok=0
assert_eq 1 "$ok" "studio job (derush proxy) produced proxy.mp4"

# 3b. detached into its own session: a launcher that dies with its process group leaves the studio up
"$D" stop >/dev/null 2>&1
# The launcher leads its own group (pgid = its pid) and stays alive after starting the studio, so
# that group exists and WOULD hold the server if it were not detached. kill errors are not hidden.
"$DERUSH_PY" -c 'import os,sys;os.setpgid(0,0);os.execvp(sys.argv[1],sys.argv[1:])' \
  bash -c '"$0" studio --no-open >/dev/null 2>&1; sleep 30' "$D" >/dev/null 2>&1 &
LPG=$!
for _ in $(seq 1 40); do [ "$(curl -s "http://127.0.0.1:$PORT/health")" = derush ] && break; sleep 0.5; done
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "studio up from the launcher"
kill -9 -- -"$LPG"; assert_eq 0 "$?" "launcher group killed"
sleep 1
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "studio survives its launcher's process group"

# 4. stop
"$D" stop >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "stop exits 0"
sleep 1
curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && up=1 || up=0
assert_eq 0 "$up" "port closed after stop"
[ -e "$HOME/Library/Logs/derush/studio.pid" ] && ok=1 || ok=0
assert_eq 0 "$ok" "pidfile removed"
"$D" stop >/dev/null 2>&1; assert_eq 0 "$?" "stop when not running exits 0"

# 4b. stop refuses a pid that is not our server (bogus pidfile -> sleep)
sleep 60 & SL=$!
mkdir -p "$HOME/Library/Logs/derush"; echo "$SL" > "$HOME/Library/Logs/derush/studio.pid"
"$D" stop >/dev/null 2>&1
kill -0 "$SL" 2>/dev/null && ok=1 || ok=0
assert_eq 1 "$ok" "stop leaves a foreign pid alive"
[ -e "$HOME/Library/Logs/derush/studio.pid" ] && ok=1 || ok=0
assert_eq 0 "$ok" "bogus pidfile removed"
kill "$SL" 2>/dev/null

# 5. foreign program on the port
"$DERUSH_PY" -m http.server $PORT --bind 127.0.0.1 >/dev/null 2>&1 & HTTP_PID=$!
sleep 1
out="$("$D" studio --no-open 2>&1)"; rc=$?
assert_eq 3 "$rc" "foreign port exits 3"
assert_contains "$out" "le port $PORT est pris par un autre programme (DERUSH_EDIT_PORT pour en changer)" "foreign port message"
"$D" stop >/dev/null 2>&1
kill -0 "$HTTP_PID" 2>/dev/null && ok=1 || ok=0
assert_eq 1 "$ok" "stop never kills a foreign process"
summary
