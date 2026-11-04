#!/usr/bin/env bash
# Runs every tests/test_*.sh except test_e2e.sh (slow, run it explicitly).
cd "$(dirname "$0")" || exit 1
rc=0
for t in test_*.sh; do
  [ "$t" = test_e2e.sh ] && continue
  echo "== $t"
  bash "$t" || rc=1
done
exit $rc
