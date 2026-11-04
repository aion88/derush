#!/usr/bin/env bash
# install.sh in a throwaway HOME. Caches (uv, python, HF, whisper) stay the real ones so nothing re-downloads.
# Never touches /Applications (DERUSH_APP_DIR) nor launchctl (DERUSH_NO_LAUNCHCTL=1).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
REALHOME="$HOME"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$(uv cache dir)}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$(uv python dir)}"
export HF_HOME="${HF_HOME:-$REALHOME/.cache/huggingface}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$REALHOME/.cache}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME/.claude"
export DERUSH_APP_DIR="$T/apps" DERUSH_NO_LAUNCHCTL=1
mkdir -p "$DERUSH_APP_DIR"
tree_sum() { (cd "$HOME" && find . -print0 | sort -z | xargs -0 stat -f '%N %z %m' 2>/dev/null | shasum | cut -d' ' -f1); }

# 0. --check on an empty HOME: reports MANQUE, exit 1, changes nothing
before="$(tree_sum)"
out="$("$ROOT/install.sh" --check 2>&1)"; rc=$?
assert_eq 1 "$rc" "--check on empty HOME exits 1"
assert_contains "$out" "MANQUE" "--check reports MANQUE"
assert_eq "$before" "$(tree_sum)" "--check changed nothing"

# 1. first run
out="$("$ROOT/install.sh" 2>&1)"; rc=$?
assert_eq 0 "$rc" "first run exits 0"
assert_contains "$out" "INSTALLÉ" "first run installs things"
assert_eq 0 "$(echo "$out" | grep -c MANQUE)" "first run: no MANQUE"
[ -f "$HOME/.config/derush/config" ] && ok=1 || ok=0; assert_eq 1 "$ok" "config file written"
show="$(PATH="/usr/bin:/bin:$HOME/.local/bin" "$HOME/.local/bin/derush" config show 2>&1)"
assert_contains "$show" "DERUSH_OUT_ROOT" "derush config show works through ~/.local/bin/derush"
assert_eq "$ROOT/skill" "$(readlink "$HOME/.claude/skills/derush")" "skill linked"
[ -d "$DERUSH_APP_DIR/Derush.app" ] && ok=1 || ok=0; assert_eq 1 "$ok" "Derush.app built in DERUSH_APP_DIR"
imp="$("$HOME/.local/share/derush/venv/bin/python" -W ignore -c 'import torch,torchaudio,numpy,soundfile,qwen_asr,whisper;print("fine")' 2>/dev/null)"
assert_eq fine "$imp" "venv imports all packages"

# 2. second run: only OK
out="$("$ROOT/install.sh" 2>&1)"; rc=$?
assert_eq 0 "$rc" "second run exits 0"
assert_eq 0 "$(echo "$out" | grep -cE 'INSTALLÉ|MANQUE')" "second run: only OK lines"
assert_contains "$out" "OK" "second run prints OK"

# 3. --check after install: nothing changes, exit 0
before="$(tree_sum)"
"$ROOT/install.sh" --check >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "--check after install exits 0"
assert_eq "$before" "$(tree_sum)" "--check after install changed nothing"

# 4. existing config is never overwritten
printf 'DERUSH_OUT_ROOT=/custom/place\n' > "$HOME/.config/derush/config"
"$ROOT/install.sh" >/dev/null 2>&1
assert_eq "DERUSH_OUT_ROOT=/custom/place" "$(cat "$HOME/.config/derush/config")" "existing config untouched"

# 5. a real dir at ~/.claude/skills/derush is left alone and reported
rm "$HOME/.claude/skills/derush"; mkdir -p "$HOME/.claude/skills/derush"; echo mine > "$HOME/.claude/skills/derush/x"
out="$("$ROOT/install.sh" 2>&1)"; rc=$?
assert_eq 1 "$rc" "real skills dir: exit 1"
assert_contains "$out" "existe déjà, pas touché" "real skills dir reported"
assert_eq mine "$(cat "$HOME/.claude/skills/derush/x")" "real skills dir untouched"
rm -rf "$HOME/.claude/skills/derush"

# 6. --at-login writes the LaunchAgent in the throwaway HOME, loads nothing
"$ROOT/install.sh" --at-login >/dev/null 2>&1
P="$HOME/Library/LaunchAgents/com.derush.studio.plist"
[ -f "$P" ] && ok=1 || ok=0; assert_eq 1 "$ok" "LaunchAgent plist written under throwaway HOME"
assert_eq 0 "$(plutil -lint "$P" >/dev/null 2>&1; echo $?)" "plist lints"
assert_eq false "$(plutil -extract KeepAlive raw -o - "$P")" "KeepAlive false"
assert_eq true "$(plutil -extract RunAtLoad raw -o - "$P")" "RunAtLoad true"
assert_contains "$(plutil -p "$P")" "$ROOT/bin/derush" "plist runs bin/derush"
assert_contains "$(plutil -p "$P")" "--no-open" "plist passes --no-open"

# 7. --models: only when both models are already cached (never a real download in tests)
if [ -f "$XDG_CACHE_HOME/whisper/large-v3-turbo.pt" ] && [ -d "$HF_HOME/hub/models--Qwen--Qwen3-ASR-1.7B" ]; then
  HF_HUB_OFFLINE=1 "$ROOT/install.sh" --models >/dev/null 2>&1; rc=$?
  assert_eq 0 "$rc" "--models against a warm cache exits 0"
else
  echo "skip - --models: models not both cached, no 6 GB download in tests"
fi
summary
