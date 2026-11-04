#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"

for f in bin/derush skill/SKILL.md LICENSE .gitignore tests/lib.sh \
  derush/edit.html derush/home.html derush/edit_server.py derush/propose_cuts.py \
  derush/transcribe_qwen.py derush/fcpxml.py \
  derush/vendor/prune.py derush/vendor/detect_fillers.py derush/vendor/cut.sh; do
  [ -f "$ROOT/$f" ]; assert_eq 0 $? "exists: $f"
done
[ -x "$ROOT/bin/derush" ]; assert_eq 0 $? "bin/derush executable"

out="$("$ROOT/bin/derush" 2>&1)"; rc=$?
assert_eq 1 "$rc" "no args exits 1"
assert_contains "$out" "derush prep" "usage mentions derush prep"
summary
