#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
cd "$ROOT" || exit 1

PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"
T="$(mktemp -d)/with space"
mkdir -p "$T"
bash tests/make_fixture.sh "$T" >/dev/null
ffmpeg -nostdin -loglevel error -y -i "$T/fixture test.mov" -vn -ac 1 -ar 16000 "$T/audio 16k.wav"
cat > "$T/asr in.json" <<'J'
{"segments":[{"id":0,"text":" Bonjour, je je voulais vous parler d'une idée simple.","words":[
{"word":"Bonjour,","start":0,"end":0.1},{"word":"je","start":0.1,"end":0.2},{"word":"je","start":0.2,"end":0.3},
{"word":"voulais","start":0.3,"end":0.4},{"word":"vous","start":0.4,"end":0.5},{"word":"parler","start":0.5,"end":0.6},
{"word":"d'une","start":0.6,"end":0.7},{"word":"idée","start":0.7,"end":0.8},{"word":"simple.","start":0.8,"end":0.9}]}]}
J
env -i HOME="$T/home" PATH="$PATH" DERUSH_PY="$PY" bin/derush align "$T/audio 16k.wav" "$T/asr in.json" --out "$T/aligned out.json" >"$T/log" 2>&1
assert_eq 0 "$?" "derush align exits 0 (paths with spaces)"
assert_contains "$(cat "$T/log")" "aligned 9/9 words" "align reports 9/9 words"
res="$("$PY" -I - "$T/aligned out.json" <<'PY'
import json,sys
w=[w for s in json.load(open(sys.argv[1]))["segments"] for w in s["words"]]
ok=len(w)==9 and all(x["start"]<x["end"] for x in w) and all(a["start"]<=b["start"] for a,b in zip(w,w[1:]))
print("ok" if ok else "bad")
PY
)"
assert_eq ok "$res" "every word start<end, ascending order"
bin/derush align "$T/nope.wav" "$T/asr in.json" --out "$T/x.json" >/dev/null 2>&1
[ "$?" -ne 0 ] && r=nonzero || r=zero
assert_eq nonzero "$r" "exit code passes through on failure"
rm -rf "$(dirname "$T")"
summary
