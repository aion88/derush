#!/usr/bin/env bash
# Projet bout à bout sur deux prises dites (say) : reprise (cas A), cas B (LLM simulé), rendu, export, fcpxml,
# dépôt d'une prise dans un projet par le studio. Port 8796.
#
# Transcription : DERUSH_PY est un petit enveloppeur qui répond SEULEMENT à transcribe_qwen.py avec le texte
# dit (tests/test_audio.sh en fait autant), lu dans $T/textes/<STEM>.txt, STEM = le dossier du rush.
# Alignement, silences, coupes et gardes tournent pour de vrai. Un seul passage de vrai Qwen vérifie l'ordre
# du rendu, seulement avec DERUSH_E2E=1.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
REAL_PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"
T="$(mktemp -d)"; PORT=8796
export HOME="$T/home"; mkdir -p "$HOME"
export DERUSH_CONFIG="$T/none" DERUSH_EDIT_PORT=$PORT DERUSH_OUT_ROOT="$T/out"
D="$ROOT/bin/derush"; PJ="$ROOT/derush/projet.py"
cleanup() { "$D" stop >/dev/null 2>&1; pkill -f "edit_server.py $T/out" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
mkdir -p "$T/textes" "$T/in" "$T/out"

cat > "$T/py" <<WRAP
#!/bin/bash
case "\${1:-}" in
  */transcribe_qwen.py)
    out=""; prev=""; for a in "\$@"; do [ "\$prev" = --out ] && out="\$a"; prev="\$a"; done
    stem="\$(basename "\$(dirname "\$(dirname "\$2")")")"
    exec "$REAL_PY" -I -c '
import json,sys,soundfile as sf
sys.path.insert(0, sys.argv[1]); from transcribe_qwen import to_whisper_shape
json.dump(to_whisper_shape(open(sys.argv[4]).read(), "fr", sf.info(sys.argv[2]).duration), open(sys.argv[3], "w"))
print("stub")' "\$(dirname "\$1")" "\$2" "\$out" "$T/textes/\$stem.txt" ;;
esac
exec "$REAL_PY" "\$@"
WRAP
chmod +x "$T/py"; export DERUSH_PY="$T/py"
pj() { "$DERUSH_PY" -I "$PJ" "$@"; }
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
close() { "$DERUSH_PY" -I -c "import sys;print(abs(float(sys.argv[1])-float(sys.argv[2]))<=float(sys.argv[3]))" "$1" "$2" "$3"; }
jget() { "$DERUSH_PY" -I -c "import json,sys;print(json.loads(sys.argv[1])$2)" "$1"; }
O="$T/out"

# prises dites : fixtures
printf '%s [[slnc 1400]] %s [[slnc 1400]] %s\n' "Bonjour, aujourd'hui je vous parle du montage vidéo." "Le montage prend beaucoup de temps quand on filme seul." "Merci de m'avoir écouté jusqu'au bout." > "$T/in/un.txt"
printf '%s [[slnc 1400]] %s\n' "Les girafes dorment debout pendant quelques minutes." "Le montage prend beaucoup de temps, et il faut aussi couper les silences." > "$T/in/deux.txt"
printf '%s [[slnc 1400]] %s\n' "Un dernier mot sur les prises." "On les range toutes dans le même projet." > "$T/in/trois.txt"
cp "$T/in/un.txt" "$T/textes/prise un.txt"; cp "$T/in/deux.txt" "$T/textes/prise deux.txt"; cp "$T/in/trois.txt" "$T/textes/prise_trois.txt"
for f in "$T"/textes/*.txt; do sed -i '' -e 's/ \[\[slnc [0-9]*\]\]//g' "$f"; done
bash "$ROOT/tests/make_fixture.sh" "$T/in" "prise un" "$T/in/un.txt" >/dev/null
FIXTURE_SIZE=720x1280 bash "$ROOT/tests/make_fixture.sh" "$T/in" "prise deux" "$T/in/deux.txt" >/dev/null
bash "$ROOT/tests/make_fixture.sh" "$T/in" "prise trois" "$T/in/trois.txt" >/dev/null

"$D" prep "$T/in/prise un.mov" >/dev/null 2>&1; assert_eq 0 $? "prep: prise un"
"$D" render "prise un" >/dev/null 2>&1; assert_eq 0 $? "render: prise un"
"$D" prep "$T/in/prise deux.mov" >/dev/null 2>&1; assert_eq 0 $? "prep: prise deux (render left to the project)"
[ -e "$O/prise deux/keep.json" ] && ok=1 || ok=0; assert_eq 0 "$ok" "prise deux has no keep.json yet"

# projet
"$D" projet new demo "prise un" >/dev/null 2>&1; assert_eq 0 $? "projet new"
assert_eq 3 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "montrer: 3 blocs of prise un"
"$D" projet add demo "prise deux" >/dev/null 2>&1; assert_eq 0 $? "projet add"
bloc() { "$DERUSH_PY" -I -c '
import sys; sys.path.insert(0, sys.argv[1]); import projet
b = projet.blocs(sys.argv[2], sys.argv[3])[int(sys.argv[4])]; print(b["debut"], b["fin"])' "$ROOT/derush" "$O" "$1" "$2"; }

# cas A : « le montage prend beaucoup de temps » est repris
set -- $(bloc "prise deux" 1)
PROP="$(pj placer "$O" demo "prise deux" "$1" "$2")"
assert_eq A "$(jget "$PROP" '["cas"]')" "case A detected"
assert_eq 3 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "case A: nothing applied before accepter"
pj accepter "$O" demo 0
assert_eq 5 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "case A: 5 blocs after accepter"
case "$(pj montrer "$O" demo | sed -n 3p | cut -f4)" in "et il faut"*) ok=1;; *) ok=0;; esac
assert_eq 1 "$ok" "case A: the inserted bloc starts after the duplicate (« et il faut »)"

# cas B : LLM simulé
set -- $(bloc "prise deux" 0)
export DERUSH_LLM='cat >/dev/null; echo "{\"apres\": 0, \"couper_a_mot\": 2, \"raison\": \"test\"}"'
PROP="$(pj placer "$O" demo "prise deux" "$1" "$2")"
assert_eq B "$(jget "$PROP" '["cas"]')" "case B proposed"
assert_eq 5 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "case B: nothing applied before accepter"
pj accepter "$O" demo 0
assert_eq 7 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "case B: 7 blocs after accepter"
case "$(pj montrer "$O" demo | sed -n 2p)" in *girafes*) ok=1;; *) ok=0;; esac
assert_eq 1 "$ok" "case B: girafes bloc is second"
unset DERUSH_LLM

# rendu : prise deux n'a pas de keep.json, le projet lance son render d'abord
out="$("$D" projet render demo 2>&1)"; rc=$?
assert_eq 0 "$rc" "projet render exits 0 ($(echo "$out" | tail -2))"
[ -e "$O/prise deux/keep.json" ] && ok=1 || ok=0; assert_eq 1 "$ok" "prise deux was rendered by the project render"
M="$O/_projets/demo/demo.derush.mp4"
R="$(pj resume "$O" demo)"; TOTAL="$(jget "$R" '["total"]')"; FOND="$(jget "$R" '["fondus"]')"
assert_eq 4 "$FOND" "4 fades (A D A D A)"
assert_eq True "$(close "$(dur "$M")" "$("$DERUSH_PY" -I -c "print($TOTAL - 0.2*$FOND)")" 0.25)" "duration = total - 0.2 per fade ($(dur "$M"))"

# ordre : vrai Qwen sur le rendu (lent), seulement avec DERUSH_E2E=1
if [ "${DERUSH_E2E:-0}" = 1 ]; then
  if ! "$REAL_PY" -c 'import importlib.util as u,sys;sys.exit(u.find_spec("qwen_asr") is None)' 2>/dev/null; then
    FAILS=$((FAILS+1)); echo "FAIL - qwen_asr n'est pas importable dans $REAL_PY (DERUSH_E2E=1 le demande)"
  else
    export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
    ffmpeg -nostdin -y -loglevel error -i "$M" -vn -ac 1 -ar 16000 "$T/rendu.wav"
    "$REAL_PY" "$ROOT/derush/transcribe_qwen.py" "$T/rendu.wav" --lang fr --out "$T/rendu.json" >/dev/null 2>&1
    ORD="$("$REAL_PY" -I - "$T/rendu.json" <<'PY'
import json, re, sys, unicodedata
t = json.load(open(sys.argv[1]))["text"].lower()
t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
pos = [t.find(k) for k in ("bonjour", "girafes", "parle", "beaucoup", "silences", "filme", "merci")]
print("ok" if all(p >= 0 for p in pos) and pos == sorted(pos) else f"ordre {pos} dans : {t}")
print(len(re.findall("beaucoup", t)))
PY
)"
    assert_eq ok "$(echo "$ORD" | sed -n 1p)" "Qwen: the render follows the bloc order"
    assert_eq 1 "$(echo "$ORD" | sed -n 2p)" "Qwen: « beaucoup » appears once (duplicate removed)"
  fi
else
  echo "skip - ordre par Qwen (DERUSH_E2E=1 pour le lancer)"
fi

# export
out="$("$D" projet export demo 2>&1)"; rc=$?
assert_eq 0 "$rc" "projet export exits 0"
RL="$O/_projets/demo/demo.reel.mp4"
assert_eq "1080,1920,30/1" "$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$RL")" "reel 1080x1920 30 fps"
LUFS="$(ffmpeg -nostdin -i "$RL" -af "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=summary" -f null - 2>&1 | grep "Input Integrated" | awk '{print $3}')"
assert_eq True "$(close "$LUFS" -14 1)" "reel loudness $LUFS within 1 LU of -14"
FX="$(cat "$O/_projets/demo/demo.fcpxml")"
assert_contains "$FX" "prise un" "fcpxml cites prise un"
assert_contains "$FX" "prise deux" "fcpxml cites prise deux"

# dépôt d'une prise dans un projet, par le studio
"$D" studio --no-open >/dev/null 2>&1
r=$(curl -s -X POST --data-binary @"$T/in/prise trois.mov" "http://127.0.0.1:$PORT/upload?name=prise%20trois.mov&lang=fr&projet=demo")
assert_contains "$r" "prise_trois" "upload into the project accepted"
for _ in $(seq 1 120); do case "$(curl -s "http://127.0.0.1:$PORT/projet/data?p=demo")" in *prise_trois*) break;; esac; sleep 1; done
assert_contains "$(curl -s "http://127.0.0.1:$PORT/projet/data?p=demo")" "prise_trois" "the uploaded rush joined the project"
[ -s "$O/prise_trois/_work/proxy.mp4" ] && ok=1 || ok=0; assert_eq 1 "$ok" "the uploaded rush has its proxy"

# anti-objectifs : aucun chemin privé ni chaîne interdite dans les fichiers suivis (la liste vit dans test_paths.sh)
bash "$ROOT/tests/test_paths.sh" >/dev/null 2>&1; assert_eq 0 $? "test_paths.sh green (no private path in tracked files)"
summary
