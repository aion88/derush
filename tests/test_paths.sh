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

# 5. Keys are exported to children (config sourced under set -a).
out="$(run "$H" -- config show 2>&1)"
case "$out" in *OPENAI_API_KEY*|*sk-*) FAILS=$((FAILS+1)); echo "FAIL - key leaked";; *) PASSES=$((PASSES+1)); echo "ok   - no key in config show";; esac
summary
