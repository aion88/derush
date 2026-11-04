# Tiny assert harness. Source from tests/test_*.sh, call `summary` last.
FAILS=0
PASSES=0
assert_eq() { # expected actual label
  if [ "$1" = "$2" ]; then PASSES=$((PASSES+1)); echo "ok   - $3"
  else FAILS=$((FAILS+1)); echo "FAIL - $3: expected [$1] got [$2]"; fi
}
assert_contains() { # haystack needle label
  case "$1" in *"$2"*) PASSES=$((PASSES+1)); echo "ok   - $3";;
    *) FAILS=$((FAILS+1)); echo "FAIL - $3: [$2] not found in [$1]";; esac
}
fail_count() { echo "$FAILS"; }
summary() {
  echo "$PASSES passed, $FAILS failed"
  [ "$FAILS" -eq 0 ]
}
