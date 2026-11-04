#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
cd "$ROOT" || exit 1

# 1. No bare system python3 left in the scripts.
hits="$(grep -nE '(^|[^_A-Z])python3 ' bin/derush derush/vendor/cut.sh)"
assert_eq "" "$hits" "no bare python3 in bin/derush and cut.sh"

# 2. DERUSH_PY is really what runs: with /usr/bin/false, prep must fail.
T="$(mktemp -d)"
bash tests/make_fixture.sh "$T" >/dev/null
env -i HOME="$T/home" PATH="$PATH" DERUSH_PY=/usr/bin/false DERUSH_OUT_ROOT="$T/out" \
  bin/derush prep "$T/fixture test.mov" >"$T/log" 2>&1
rc=$?
[ "$rc" -ne 0 ] && r=nonzero || r=zero
assert_eq nonzero "$r" "prep fails when DERUSH_PY=/usr/bin/false"
rm -rf "$T"
summary
