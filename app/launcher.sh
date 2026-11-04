#!/bin/bash
# Derush.app launcher. ROOT is baked in by build-app.sh. Finder gives a bare PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
ROOT=@ROOT@
LOG="$HOME/Library/Logs/derush/studio.log"
err="$("$ROOT/bin/derush" studio 2>&1)"; rc=$?
if [ "$rc" -ne 0 ]; then
  [ -n "$err" ] || err="Le studio ne démarre pas (code $rc)."
  msg="$(printf '%s' "$err" | tr -d '"\\' | tr '\n' ' ')"
  osascript -e "display notification \"$msg Journal : $LOG\" with title \"Derush\""
  exit "$rc"
fi
