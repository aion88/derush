#!/usr/bin/env bash
# Rendu d'un projet : fondus entre rushs, sorties, export, derush projet. Sans ASR (rushs synthétiques).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
DERUSH_PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"; export DERUSH_PY
T="$(mktemp -d)"
export HOME="$T/home"; mkdir -p "$HOME"
export DERUSH_CONFIG="$T/none" DERUSH_OUT_ROOT="$T/out"
D="$ROOT/bin/derush"; PJ="$ROOT/derush/projet.py"; S="$ROOT/tests/synth_rush.py"
trap 'rm -rf "$T"' EXIT
O="$T/out"; mkdir -p "$O"
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
close() { "$DERUSH_PY" -I -c "import sys;print(abs(float(sys.argv[1])-float(sys.argv[2]))<=float(sys.argv[3]))" "$1" "$2" "$3"; }
pj() { "$DERUSH_PY" -I "$PJ" "$@"; }

"$DERUSH_PY" -I "$S" "$O" X --size 1080x1920 --fps 30 --rate 48000 --paras 4 --freq 440 >/dev/null
"$DERUSH_PY" -I "$S" "$O" Y --size 720x1280 --fps 25 --rate 44100 --paras 2 --freq 330 >/dev/null
"$DERUSH_PY" -I "$S" "$O" MA --audio --paras 2 >/dev/null
"$DERUSH_PY" -I "$S" "$O" MB --audio --paras 2 --freq 300 >/dev/null

# 1. creation
"$D" projet new demo X >/dev/null 2>&1; assert_eq 0 $? "projet new exits 0"
"$D" projet add demo Y >/dev/null 2>&1; assert_eq 0 $? "projet add exits 0"
assert_eq 4 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "montrer: X's 4 blocs only"
# Y inséré entre X0 et X1 (séquence écrite comme le ferait le studio)
"$DERUSH_PY" -I -c '
import sys; sys.path.insert(0, sys.argv[1]); import projet
root = sys.argv[2]; p = projet.charger(root, "demo")
y = projet.blocs(root, "Y")[0]
p["sequence"] = projet.valider(root, p, projet.inserer(p["sequence"], 0, y)); projet.ecrire(root, "demo", p)' "$ROOT/derush" "$O"
assert_eq 5 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "Y bloc inserted"
R="$(pj resume "$O" demo)"
FOND="$("$DERUSH_PY" -I -c 'import json,sys;print(json.loads(sys.argv[1])["fondus"])' "$R")"
TOTAL="$("$DERUSH_PY" -I -c 'import json,sys;print(json.loads(sys.argv[1])["total"])' "$R")"
assert_eq 2 "$FOND" "resume: 2 fondus (hand count X|Y|X)"

# 2. rendu
out="$("$D" projet render demo 2>&1)"; rc=$?
assert_eq 0 "$rc" "projet render exits 0 ($out)"
M="$O/_projets/demo/demo.derush.mp4"
[ -s "$M" ] && ok=1 || ok=0; assert_eq 1 "$ok" "demo.derush.mp4 exists"
attendu="$("$DERUSH_PY" -I -c "print($TOTAL - 0.2*$FOND)")"
assert_eq True "$(close "$(dur "$M")" "$attendu" 0.25)" "duration = total - 0.2 per fade (+-0.25): $(dur "$M") vs $attendu"
assert_eq "1080,1920,30/1" "$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$M")" "output takes the first rush's format"
CM="$(cat "$O/_projets/demo/cuts.md")"
assert_contains "$CM" "Y : 720x1280" "cuts.md names the scaled rush"
assert_contains "$CM" "mis à l'échelle" "cuts.md says it was scaled"
assert_contains "$CM" "2 fondus de 0,2 s" "cuts.md counts the fades"
assert_contains "$CM" "Mots dans un fondu" "cuts.md has the fade-words section"
assert_contains "$CM" "coupes franches" "cuts.md says the timeline has hard cuts"
FX="$(cat "$O/_projets/demo/demo.fcpxml")"
assert_contains "$FX" "X.mp4" "fcpxml cites source X"
assert_contains "$FX" "Y.mp4" "fcpxml cites source Y"
assert_eq "projet.json" "$(ls "$O/_projets/demo" | grep -v -E '^(demo\.|cuts\.md|_work)' | tr '\n' ' ' | sed 's/ $//')" "project dir holds no copied media"

# 3. export
out="$("$D" projet export demo 2>&1)"; rc=$?
assert_eq 0 "$rc" "projet export exits 0 ($out)"
RL="$O/_projets/demo/demo.reel.mp4"
assert_eq "1080,1920,30/1" "$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$RL")" "reel 1080x1920 30 fps"
LUFS="$(ffmpeg -nostdin -i "$RL" -af "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=summary" -f null - 2>&1 | grep "Input Integrated" | awk '{print $3}')"
assert_eq True "$(close "$LUFS" -14 1)" "reel loudness $LUFS within 1 LU of -14"

# 4. bloc vide : le montage de Y exclut le bloc inséré
cp "$O/Y/keep.json" "$T/y.keep"
"$DERUSH_PY" -I -c '
import json,sys; k=json.load(open(sys.argv[1])); json.dump(k[1:], open(sys.argv[1],"w"))' "$O/Y/keep.json"
out="$("$D" projet render demo 2>&1)"; rc=$?
assert_eq 0 "$rc" "empty bloc: render exits 0 ($out)"
assert_contains "$(cat "$O/_projets/demo/cuts.md")" "bloc vide" "empty bloc: cuts.md says so"
case "$out" in *Traceback*) bad=1;; *) bad=0;; esac; assert_eq 0 "$bad" "empty bloc: no traceback"
cp "$T/y.keep" "$O/Y/keep.json"

# 5. rush introuvable
mv "$O/Y/Y.mp4" "$T/Y.mp4.away"
out="$("$D" projet render demo 2>&1)"; rc=$?
assert_eq 1 "$rc" "missing rush: exit 1"
assert_contains "$out" "rush introuvable : Y" "missing rush: French message"
case "$out" in *Traceback*) bad=1;; *) bad=0;; esac; assert_eq 0 "$bad" "missing rush: no traceback"
mv "$T/Y.mp4.away" "$O/Y/Y.mp4"

# 6. rush sans keep.json
mv "$O/X/keep.json" "$T/x.keep"
assert_eq X "$(pj a-rendre "$O" demo)" "a-rendre lists the rush without keep.json"
mv "$T/x.keep" "$O/X/keep.json"
assert_eq "" "$(pj a-rendre "$O" demo)" "a-rendre empty when every rush is rendered"

# 7. projet audio
"$D" projet new sons MA >/dev/null 2>&1; "$D" projet add sons MB >/dev/null 2>&1
"$DERUSH_PY" -I -c '
import sys; sys.path.insert(0, sys.argv[1]); import projet
root = sys.argv[2]; p = projet.charger(root, "sons")
b = projet.blocs(root, "MB")[0]
p["sequence"] = projet.valider(root, p, projet.inserer(p["sequence"], 0, b)); projet.ecrire(root, "sons", p)' "$ROOT/derush" "$O"
out="$("$D" projet render sons 2>&1)"; rc=$?
assert_eq 0 "$rc" "audio project render exits 0 ($out)"
A="$O/_projets/sons/sons.derush.m4a"
[ -s "$A" ] && ok=1 || ok=0; assert_eq 1 "$ok" "sons.derush.m4a exists"
assert_eq "" "$(ffprobe -v error -select_streams v -show_entries stream=index -of csv=p=0 "$A")" "audio project: no video stream"
[ -e "$O/_projets/sons/sons.fcpxml" ] && ok=1 || ok=0; assert_eq 0 "$ok" "audio project: no fcpxml"
out="$("$D" projet new mix X MA 2>&1)"; rc=$?
assert_eq 1 "$rc" "mixed project refused"
assert_contains "$out" "ne mélange pas" "mixed project: French message"

# 8. CLI
"$D" projet frob demo >/dev/null 2>&1; assert_eq 1 $? "unknown projet sub-command exits 1"
assert_contains "$("$D" 2>&1)" "derush prep" "no args still prints the single-rush usage"
assert_contains "$("$D" 2>&1)" "derush projet" "usage lists derush projet"
summary
