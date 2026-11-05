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
export DERUSH_PROJET_FONDU=1  # sections 1 à 7 : le code de fondu, gardé derrière son drapeau ; la section 4a le coupe
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
assert_eq 2 "$(pj montrer "$O" demo | wc -l | tr -d ' ')" "montrer: one clip per rush"
# Y inséré entre X0 et X1 (séquence écrite comme le ferait le studio)
"$DERUSH_PY" -I -c '
import sys; sys.path.insert(0, sys.argv[1]); import projet
root = sys.argv[2]; p = projet.charger(root, "demo")
y = projet.blocs(root, "Y")[0]
p["sequence"] = projet.valider(root, p, projet.inserer(projet.blocs(root, "X"), 0, y)); projet.ecrire(root, "demo", p)' "$ROOT/derush" "$O"
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

# 3b. le format de sortie est celui du PREMIER RUSH du projet, même si la séquence commence par un autre
"$D" projet new ord X >/dev/null 2>&1; "$D" projet add ord Y >/dev/null 2>&1
"$DERUSH_PY" -I -c '
import sys; sys.path.insert(0, sys.argv[1]); import projet
root = sys.argv[2]; p = projet.charger(root, "ord")
p["sequence"] = projet.valider(root, p, [projet.blocs(root, "Y")[0], projet.blocs(root, "X")[0]]); projet.ecrire(root, "ord", p)' "$ROOT/derush" "$O"
out="$("$D" projet render ord 2>&1)"; rc=$?
assert_eq 0 "$rc" "project starting with the second rush renders ($out)"
assert_eq "1080,1920,30/1" "$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$O/_projets/ord/ord.derush.mp4")" "output format = first rush (X), not first bloc (Y)"

# 4. le montage de Y exclut le bloc inséré : le clip se joue quand même (le temps du clip est à elle)
cp "$O/Y/keep.json" "$T/y.keep"
"$DERUSH_PY" -I -c '
import json,sys; k=json.load(open(sys.argv[1])); json.dump(k[1:], open(sys.argv[1],"w"))' "$O/Y/keep.json"
out="$("$D" projet render demo 2>&1)"; rc=$?
assert_eq 0 "$rc" "empty bloc: render exits 0 ($out)"
case "$(cat "$O/_projets/demo/cuts.md")" in *"bloc vide"*) ok=0;; *) ok=1;; esac; assert_eq 1 "$ok" "clip outside the rush edit still plays: no empty bloc"
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

# 4a. coupes franches (défaut) : durée = somme des passages, synchro A/V par passage, bascule de tonalité sur chaque raccord
unset DERUSH_PROJET_FONDU
"$DERUSH_PY" -I "$S" "$O" Z --size 1080x1920 --fps 30 --rate 48000 --paras 2 --freq 880 >/dev/null
"$D" projet new dur X Z >/dev/null 2>&1
"$DERUSH_PY" -I -c '
import json, sys; sys.path.insert(0, sys.argv[1]); import projet
root = sys.argv[2]; p = projet.charger(root, "dur")
def para(stem, k):
    w = projet.mots(root, stem)[3 * k : 3 * k + 3]
    return {"rush": stem, "debut": w[0]["s"], "fin": w[-1]["e"]}
p["sequence"] = projet.valider(root, p, [para("X", 0), para("Z", 0), para("X", 1)]); projet.ecrire(root, "dur", p)' "$ROOT/derush" "$O"
out="$("$D" projet render dur 2>&1)"; rc=$?
assert_eq 0 "$rc" "hard cuts: render exits 0 ($out)"
CD="$(cat "$O/_projets/dur/cuts.md")"
assert_contains "$CD" "coupes franches" "hard cuts: cuts.md says so"
case "$(echo "$CD" | tr 'A-Z' 'a-z')" in *fondu*) ok=0;; *) ok=1;; esac; assert_eq 1 "$ok" "hard cuts: cuts.md has no fade line"
RUNS="$O/_projets/dur/_work/runs.json"
[ -s "$RUNS" ] && ok=1 || ok=0; assert_eq 1 "$ok" "hard cuts: runs.json written"
FR="$(printf '%s' 0.0334)"
assert_eq True "$("$DERUSH_PY" -I -c '
import json, sys
r = json.load(open(sys.argv[1]))
print(len(r) == 3 and all(abs(x["duree"] - x["vduree"]) <= float(sys.argv[2]) for x in r))' "$RUNS" "$FR")" "hard cuts: per-run |duree - vduree| within one frame ($(cat "$RUNS"))"
MD="$O/_projets/dur/dur.derush.mp4"
SUMV="$("$DERUSH_PY" -I -c 'import json,sys;print(sum(x["vduree"] for x in json.load(open(sys.argv[1]))))' "$RUNS")"
assert_eq True "$(close "$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 "$MD")" "$SUMV" 0.0334)" "hard cuts: video duration = sum of the runs, no overlap"
assert_eq True "$(close "$(ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv=p=0 "$MD")" "$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 "$MD")" 0.0334)" "hard cuts: audio and video lengths agree within one frame"
SW="$("$DERUSH_PY" -I "$ROOT/tests/tone_runs.py" "$MD" 440,880)"
assert_eq 2 "$(echo "$SW" | wc -l | tr -d ' ')" "hard cuts: two tone switches (440 880 440)"
B1="$("$DERUSH_PY" -I -c 'import json,sys;print(json.load(open(sys.argv[1]))[0]["vduree"])' "$RUNS")"
B2="$("$DERUSH_PY" -I -c 'import json,sys;r=json.load(open(sys.argv[1]));print(r[0]["vduree"]+r[1]["vduree"])' "$RUNS")"
for k in 1 2; do
  B=$([ $k = 1 ] && echo "$B1" || echo "$B2")
  FIN="$(echo "$SW" | sed -n ${k}p | cut -d' ' -f1)"; DEB="$(echo "$SW" | sed -n ${k}p | cut -d' ' -f2)"
  assert_eq True "$(close "$FIN" "$B" 0.0434)" "hard cuts: previous tone ends at run boundary $k ($FIN vs $B)"
  assert_eq True "$(close "$DEB" "$B" 0.0434)" "hard cuts: next tone starts at run boundary $k ($DEB vs $B)"
done
assert_contains "$(cat "$O/_projets/dur/dur.fcpxml")" "Z.mp4" "hard cuts: fcpxml timeline cites each source"
export DERUSH_PROJET_FONDU=1

# 4b. bord tiré à la main : dans un mot = prévenu (jamais refusé) ; vers l'extérieur d'une coupe du rush = joué
unset DERUSH_PROJET_FONDU
"$D" projet new mc X >/dev/null 2>&1
ATT="$("$DERUSH_PY" -I -c '
import json, sys; sys.path.insert(0, sys.argv[1]); import projet
root = sys.argv[2]; p = projet.charger(root, "mc"); w = projet.mots(root, "X")
mid = round((w[1]["s"] + w[1]["e"]) / 2, 3)
a = {"rush": "X", "debut": mid, "fin": w[2]["e"]}
b = {"rush": "X", "debut": round(w[3]["s"] - 0.6, 3), "fin": w[5]["e"]}
p["sequence"] = projet.valider(root, p, [a, b]); projet.ecrire(root, "mc", p)
print(round((a["fin"] - a["debut"]) + (b["fin"] - b["debut"]), 3))' "$ROOT/derush" "$O")"
out="$("$D" projet render mc 2>&1)"; rc=$?
assert_eq 0 "$rc" "hand-set edge in a word and outward trim: render exits 0 ($out)"
case "$out" in *"GARDE ROUGE"*) ok=0;; *) ok=1;; esac; assert_eq 1 "$ok" "no GARDE ROUGE for hand-set edges"
assert_contains "$(cat "$O/_projets/mc/cuts.md")" "Mots coupés, à écouter" "cuts.md lists the word cut by hand"
assert_eq True "$(close "$(dur "$O/_projets/mc/mc.derush.mp4")" "$ATT" 0.25)" "the outward trim is played: duration $(dur "$O/_projets/mc/mc.derush.mp4") vs $ATT"
assert_eq 1 "$(jget_mc=$("$DERUSH_PY" -I "$PJ" resume "$O" mc); "$DERUSH_PY" -I -c 'import json,sys;print(json.loads(sys.argv[1])["mots_coupes"])' "$jget_mc")" "resume counts one word cut by hand"
export DERUSH_PROJET_FONDU=1

# 4c. acceptation de la révision : couper la prise 1, insérer un morceau de la prise 2 au milieu, trimmer de 3 images
unset DERUSH_PROJET_FONDU
op() { "$DERUSH_PY" -I "$PJ" op "$O" "$1" "$2" >/dev/null; }
"$D" projet new unc X >/dev/null 2>&1; "$D" projet render unc >/dev/null 2>&1
"$D" projet new cut X >/dev/null 2>&1; op cut '{"op":"couper","i":0,"t":5.2}'
"$D" projet render cut >/dev/null 2>&1
assert_eq 2 "$(pj montrer "$O" cut | wc -l | tr -d ' ')" "acceptance: the cut gives two clips"
assert_eq True "$(close "$(dur "$O/_projets/cut/cut.derush.mp4")" "$(dur "$O/_projets/unc/unc.derush.mp4")" 0.0334)" "acceptance: cutting in a rush-cut gap loses nothing (cut $(dur "$O/_projets/cut/cut.derush.mp4") vs uncut $(dur "$O/_projets/unc/unc.derush.mp4"))"
"$D" projet new acc X Z >/dev/null 2>&1
op acc '{"op":"couper","i":0,"t":5.2}'; op acc '{"op":"deplacer","i":2,"j":1}'
"$D" projet render acc >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "acceptance: render X1 Z X2"
A="$O/_projets/acc/acc.derush.mp4"; D0="$(dur "$A")"
assert_eq "440 880 440" "$("$DERUSH_PY" -I "$ROOT/tests/tone_runs.py" "$A" 440,880 | awk '{printf "%s%s", (NR==1?$3:""), (NR==1?" "$4:" "$4)}')" "acceptance: the order of the render is X, Z, X"
FIN="$(pj montrer "$O" acc | sed -n 2p | cut -f3)"
op acc "{\"op\":\"trimmer\",\"i\":1,\"cote\":\"fin\",\"t\":$("$DERUSH_PY" -I -c "print($FIN - 0.1)")}"
"$D" projet render acc >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "acceptance: render after the trim"
D1="$(dur "$A")"
assert_eq True "$(close "$("$DERUSH_PY" -I -c "print($D0 - $D1)")" 0.1 0.0334)" "acceptance: trimming 3 frames shortens the render by 0.1 s ($D0 to $D1)"
assert_eq "440 880 440" "$("$DERUSH_PY" -I "$ROOT/tests/tone_runs.py" "$A" 440,880 | awk '{printf "%s%s", (NR==1?$3:""), (NR==1?" "$4:" "$4)}')" "acceptance: the order is unchanged after the trim"
CA="$(cat "$O/_projets/acc/cuts.md")"
case "$(echo "$CA" | tr 'A-Z' 'a-z')" in *fondu*) ok=0;; *) ok=1;; esac; assert_eq 1 "$ok" "acceptance: no fade anywhere"
assert_eq True "$(close "$D1" "$("$DERUSH_PY" -I -c 'import json,sys;print(sum(x["vduree"] for x in json.load(open(sys.argv[1]))))' "$O/_projets/acc/_work/runs.json")" 0.0334)" "acceptance: duration = sum of the runs (no overlap)"
export DERUSH_PROJET_FONDU=1

# 8. CLI
"$D" projet frob demo >/dev/null 2>&1; assert_eq 1 $? "unknown projet sub-command exits 1"
assert_contains "$("$D" 2>&1)" "derush prep" "no args still prints the single-rush usage"
assert_contains "$("$D" 2>&1)" "derush projet" "usage lists derush projet"
summary
