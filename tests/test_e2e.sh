#!/usr/bin/env bash
# Needs the installed venv (DERUSH_PY or ~/.local/share/derush/venv). Slow.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
bash "$ROOT/tests/make_fixture.sh" "$T" >/dev/null
SRC="$T/fixture test.mov"; cp "$SRC" "$T/keep.mov"
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }

# 1. Qwen path: prep then render.
OUT1="$T/out1"
p="$(DERUSH_OUT_ROOT="$OUT1" "$ROOT/bin/derush" prep "$SRC" 2>&1)"; echo "$p" | tail -5
assert_contains "$p" "transcription qwen3-asr" "prep used qwen3-asr"
[ -s "$OUT1/fixture test/transcript.txt" ] && ok=1 || ok=0
assert_eq 1 "$ok" "transcript.txt non-empty"
r="$(DERUSH_OUT_ROOT="$OUT1" "$ROOT/bin/derush" render "fixture test" 2>&1)"; echo "$r" | tail -3
M="$OUT1/fixture test/fixture test.derush.mp4"
[ -f "$M" ] && ok=1 || ok=0
assert_eq 1 "$ok" "derush.mp4 exists"
if [ -f "$M" ]; then
  python3 -c "import sys;sys.exit(0 if float('$(dur "$M")')<float('$(dur "$T/keep.mov")') else 1)" && ok=1 || ok=0
  assert_eq 1 "$ok" "output shorter than source"
fi

# 2. Offline fallback: model unreachable -> whisper.
OUT2="$T/out2"
mkdir "$T/s2" && cp "$T/keep.mov" "$T/s2/fixture test.mov" && SRC2="$T/s2/fixture test.mov"
p2="$(HF_HUB_OFFLINE=1 DERUSH_QWEN_MODEL=does/not-exist DERUSH_OUT_ROOT="$OUT2" "$ROOT/bin/derush" prep "$SRC2" 2>&1)"; rc=$?
echo "$p2" | tail -5
assert_contains "$p2" "→ whisper" "fallback logged"
assert_eq 0 "$rc" "prep succeeds via whisper"
summary
