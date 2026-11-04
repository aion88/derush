#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
cd "$ROOT" || exit 1

# 1. Nothing tracked points outside the repo (this file holds the list, so it is excluded).
FORBIDDEN='/Users/cyn|Social Medias|llm-fallback|Library/Python|video-ingest|kaizn|/opt/homebrew/bin/ffmpeg'
hits="$(git ls-files -z | grep -zv '^tests/test_paths.sh$' | xargs -0 grep -lE "$FORBIDDEN" 2>/dev/null)"
assert_eq "" "$hits" "no forbidden strings in tracked files"

# Run derush with a clean environment and a throwaway HOME.
run() { # home [VAR=val...] -- args...
  local h="$1"; shift
  local envs=()
  while [ "$1" != -- ]; do envs+=("$1"); shift; done; shift
  env -i HOME="$h" PATH="$PATH" "${envs[@]}" "$ROOT/bin/derush" "$@"
}

# 2. Defaults with no config.
H="$(mktemp -d)"
out="$(run "$H" -- config show 2>&1)"
assert_contains "$out" "DERUSH_OUT_ROOT=$H/Movies/Derush" "default out root"
assert_contains "$out" "DERUSH_ASR=qwen" "default asr"
assert_contains "$out" "DERUSH_EDIT_PORT=8790" "default port"
assert_contains "$out" "DERUSH_OPENAI_MODEL=gpt-4o-mini" "default openai model"
assert_contains "$out" "DERUSH_PY=$H/.local/share/derush/venv/bin/python" "default python in venv"

# 3. Config file, spaces, tilde, env override, empty = unset.
mkdir -p "$H/.config/derush"
printf 'DERUSH_OUT_ROOT="$HOME/dir with space"\nDERUSH_LOOK=~/looks/a.cube\nDERUSH_ASR=\n' > "$H/.config/derush/config"
out="$(run "$H" -- config show 2>&1)"
assert_contains "$out" "DERUSH_OUT_ROOT=$H/dir with space" "config file out root with spaces"
assert_contains "$out" "DERUSH_LOOK=$H/looks/a.cube" "tilde expanded"
assert_contains "$out" "DERUSH_ASR=qwen" "empty value counts as unset"
out="$(run "$H" DERUSH_OUT_ROOT=/tmp/x -- config show 2>&1)"
assert_contains "$out" "DERUSH_OUT_ROOT=/tmp/x" "env beats file"

# 4. Symlink from elsewhere still resolves ROOT.
L="$(mktemp -d)"; ln -s "$ROOT/bin/derush" "$L/derush"
out="$(env -i HOME="$H" PATH="$PATH" "$L/derush" config show 2>&1)"
assert_contains "$out" "DERUSH_PY=$H/.local/share/derush/venv/bin/python" "config show through a symlink"

# 5. Config keys are exported to children; edit URL percent-encodes the STEM.
STUB="$(mktemp -d)"; REC="$STUB/rec"
printf '#!/bin/sh\nprintf "%%s\\n%%s\\n" "$DERUSH_FOO_TEST" "$1" > "%s"\n' "$REC" > "$STUB/open.sh"; chmod +x "$STUB/open.sh"
H2="$(mktemp -d)"; mkdir -p "$H2/.config/derush"
printf 'DERUSH_FOO_TEST=1\nDERUSH_OPEN=%s\nDERUSH_OUT_ROOT=%s\nDERUSH_EDIT_PORT=8799\n' "$STUB/open.sh" "$H2/rushs" > "$H2/.config/derush/config"
STEM2="Movie on 11-10-2026 at 20.42 #2"
mkdir -p "$H2/rushs/$STEM2/_work"; : > "$H2/src.mov"; echo x > "$H2/rushs/$STEM2/_work/proxy.mp4"; echo '{}' > "$H2/rushs/$STEM2/_work/aligned.json"
echo "$H2/src.mov" > "$H2/rushs/$STEM2/_work/source.txt"
env -i HOME="$H2" PATH="$PATH" "$ROOT/bin/derush" edit "$STEM2" >/dev/null 2>&1 &
EPID=$!
for _ in $(seq 1 50); do [ -s "$REC" ] && break; sleep 0.2; done
pkill -P $EPID 2>/dev/null; kill $EPID 2>/dev/null; wait $EPID 2>/dev/null
rec="$(cat "$REC" 2>/dev/null)"
assert_eq "1" "$(sed -n 1p "$REC")" "config key exported to child (DERUSH_FOO_TEST)"
assert_contains "$rec" "/edit?v=Movie%20on%2011-10-2026%20at%2020.42%20%232" "STEM percent-encoded in edit URL"

# 6. The API key never shows in config show, from env or from the config file.
printf 'OPENAI_API_KEY=sk-fake-123\n' >> "$H2/.config/derush/config"
out="$(run "$H2" OPENAI_API_KEY=sk-fake-123 -- config show 2>&1)"
case "$out" in *sk-fake-123*) FAILS=$((FAILS+1)); echo "FAIL - key leaked in config show";; *) PASSES=$((PASSES+1)); echo "ok   - key not in config show";; esac
assert_contains "$out" "DERUSH_EDIT_PORT=8799" "config show still prints with a key present"
summary
