#!/usr/bin/env bash
# Collage : coller des mots d'une prise dans une autre (inserts.json), du /save au rendu.
# Deux prises générées (say), transcription remplacée comme dans test_audio.sh (le texte connu de
# chaque prise, selon le chemin du wav), alignement, coupes et rendu pour de vrai. Port 8798.
# L'ordre des mots dans la sortie se prouve par corrélation audio avec les sources (pas d'ASR).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
REAL_PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"
T="$(mktemp -d)"; PORT=8798
export HOME="$T/home"; mkdir -p "$HOME"
export DERUSH_CONFIG="$T/none" DERUSH_EDIT_PORT=$PORT DERUSH_OUT_ROOT="$T/out"
D="$ROOT/bin/derush"
cleanup() { "$D" stop >/dev/null 2>&1; pkill -f "edit_server.py $T/out" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT

TEXT_A="Bonjour, je voulais vous parler d'une idée simple. Le montage prend du temps. Merci de m'avoir écouté."
TEXT_B="Voici une phrase totalement différente sur les chats. Ils dorment toute la journée au soleil. Fin."
cat > "$T/py" <<WRAP
#!/bin/bash
case "\${1:-}" in
  */transcribe_qwen.py)
    out=""; prev=""; for a in "\$@"; do [ "\$prev" = --out ] && out="\$a"; prev="\$a"; done
    case "\$2" in *"Prise B"*) txt="$TEXT_B";; *) txt="$TEXT_A";; esac
    exec "$REAL_PY" -I -c '
import json,sys,soundfile as sf
sys.path.insert(0, sys.argv[1]); from transcribe_qwen import to_whisper_shape
json.dump(to_whisper_shape(sys.argv[4], "fr", sf.info(sys.argv[2]).duration), open(sys.argv[3], "w"))
print("stub")' "\$(dirname "\$1")" "\$2" "\$out" "\$txt" ;;
esac
exec "$REAL_PY" "\$@"
WRAP
chmod +x "$T/py"; export DERUSH_PY="$T/py"
PY="$REAL_PY"; C="$ROOT/derush/collage.py"

mkdir -p "$T/in"
FIXTURE_TEXT="$TEXT_A" bash "$ROOT/tests/make_fixture.sh" "$T/in" "Prise A" >/dev/null
FIXTURE_TEXT="$TEXT_B" bash "$ROOT/tests/make_fixture.sh" "$T/in" "Prise B" >/dev/null
"$D" prep "$T/in/Prise A.mov" >/dev/null 2>&1; assert_eq 0 "$?" "prep prise A"
"$D" prep "$T/in/Prise B.mov" >/dev/null 2>&1; assert_eq 0 "$?" "prep prise B"
A="$T/out/Prise A"; B="$T/out/Prise B"
"$D" render "Prise B" >/dev/null 2>&1; assert_eq 0 "$?" "render prise B (son keep.json)"

# mots utiles : insertion après « simple. » de A, collage de « phrase totalement différente » de B
wordat() { "$PY" -I - "$1" "$2" "$3" <<'P'
import json,sys,re
n=lambda s: re.sub(r"\W","",s.lower())
ws=[w for s in json.load(open(sys.argv[1]+"/_work/aligned.json"))["segments"] for w in s.get("words",[])]
i=[n(w["word"]) for w in ws].index(sys.argv[2])
print(json.dumps(ws[i:i+int(sys.argv[3])]))
P
}
SIMPLE=$(wordat "$A" simple 1); APRES=$("$PY" -I -c "import json,sys;print(json.loads(sys.argv[1])[0]['end'])" "$SIMPLE")
PASTE=$(wordat "$B" phrase 3)
DEB=$("$PY" -I -c "import json,sys;print(json.loads(sys.argv[1])[0]['start'])" "$PASTE")
FIN=$("$PY" -I -c "import json,sys;print(json.loads(sys.argv[1])[-1]['end'])" "$PASTE")
MIDW=$("$PY" -I -c "import json,sys;w=json.loads(sys.argv[1])[1];print(w['start'],w['end'])" "$PASTE")
mkins() { # <barres json> → inserts.json de A
  "$PY" -I -c "
import json,sys
json.dump({'inserts':[{'apres':$APRES,'rush':'Prise B','debut':$DEB,'fin':$FIN,'barres':json.loads(sys.argv[1])}]}, open('$A/inserts.json','w'))" "$1"
}
nstreams() { ffprobe -v error -select_streams "$2" -show_entries stream=duration -of csv=p=0 "$1"; }
within() { "$PY" -I -c "import sys;sys.exit(0 if abs(float(sys.argv[1])-float(sys.argv[2]))<=float(sys.argv[3]) else 1)" "$@" && echo 1 || echo 0; }

# 1. sans inserts : rendu identique avec un inserts.json vide ou absent (aucun changement de comportement)
"$D" render "Prise A" >/dev/null 2>&1; assert_eq 0 "$?" "render A sans inserts"
H0=$(ffmpeg -nostdin -loglevel error -i "$A/Prise A.derush.mp4" -map 0 -f md5 - 2>&1)
D0=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$A/Prise A.derush.mp4")
echo '{"inserts":[]}' > "$A/inserts.json"
"$D" render "Prise A" >/dev/null 2>&1
H1=$(ffmpeg -nostdin -loglevel error -i "$A/Prise A.derush.mp4" -map 0 -f md5 - 2>&1)
assert_eq "$H0" "$H1" "inserts.json vide : sortie identique à l'absence de fichier"
assert_eq 0 "$(grep -c Insertions "$A/cuts.md")" "cuts.md : pas de section Insertions sans collage"

# 2. plan : l'ordre, les coupes dures, les mots collés entiers
mkins '[]'
"$PY" -I "$C" plan "$T/out" "Prise A" > "$T/plan.json"; assert_eq 0 "$?" "collage plan s'exécute"
ORD=$("$PY" -I - "$T/plan.json" "$APRES" "$DEB" "$FIN" <<'P'
import json,sys
p=json.load(open(sys.argv[1])); apres,deb,fin=map(float,sys.argv[2:5])
r=[s["rush"] for s in p]
k=[i for i,x in enumerate(r) if x=="Prise B"]
ok = bool(k) and k==list(range(k[0],k[-1]+1)) and r[0]=="Prise A" and r[-1]=="Prise A"
ok = ok and p[k[0]-1]["end"] <= apres+1e-6 and p[k[-1]+1]["start"] >= apres-1e-6
b=[p[i] for i in k]
ok = ok and b[0]["start"] <= deb and b[-1]["end"] >= fin   # aucun mot rogné aux bords
ok = ok and all(b[i]["end"] <= b[i+1]["start"] for i in range(len(b)-1))
print(1 if ok else 0)
P
)
assert_eq 1 "$ORD" "plan : A jusqu'à « simple », puis B (mots entiers), puis le reste de A"

# 3. rendu : durée = somme des plages à une image près, A/V d'accord, contenu à sa place
r="$("$D" render "Prise A" 2>&1)"; rc=$?
[ "$rc" -ne 0 ] && echo "$r" | tail -8
assert_eq 0 "$rc" "render A avec un collage"
O="$A/Prise A.derush.mp4"
SUM=$("$PY" -I -c "import json;print(sum(s['end']-s['start'] for s in json.load(open('$T/plan.json'))))")
VD=$(nstreams "$O" v:0); AD=$(nstreams "$O" a:0)
assert_eq 1 "$(within "$VD" "$SUM" 0.0334)" "durée vidéo = somme des plages (une image) : $VD / $SUM"
assert_eq 1 "$(within "$AD" "$VD" 0.0334)" "audio et vidéo d'accord à une image près : $AD / $VD"
assert_eq "1080x1920" "$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$O")" "résolution de A"
assert_eq "30/1" "$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$O")" "fps de A"
ffmpeg -nostdin -loglevel error -y -i "$O" -vn -ac 1 -ar 16000 "$T/o.wav"
for pr in A B; do ffmpeg -nostdin -loglevel error -y -i "$T/out/Prise $pr/Prise $pr.mov" -vn -ac 1 -ar 16000 "$T/src$pr.wav"; done
CORR=$("$PY" -I - "$T/plan.json" "$T/o.wav" "$T/srcA.wav" "$T/srcB.wav" <<'P'
import json,sys,numpy as np,soundfile as sf
plan=json.load(open(sys.argv[1])); o,_=sf.read(sys.argv[2]); src={"Prise A":sf.read(sys.argv[3])[0],"Prise B":sf.read(sys.argv[4])[0]}
other={"Prise A":"Prise B","Prise B":"Prise A"}
sr=16000; off=0.0; res=[]
def c(a,b):
    n=min(len(a),len(b)); a=a[:n]; b=b[:n]
    return float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-12))
def best(seg,ref,t0,rush):  # meilleure corrélation sur ±40 ms
    n=len(seg); r=[]
    for d in range(-640,641,16):
        i=int(t0*sr)+d
        if i<0 or i+n>len(ref): continue
        r.append(c(seg,ref[i:i+n]))
    return max(r) if r else -1.0
bad=0
for s in plan:
    d=s["end"]-s["start"]; n=int(d*sr)
    seg=o[int(off*sr):int(off*sr)+n]; n=len(seg)
    if np.sqrt(np.mean(seg**2))>0.01 and d>0.15:
        good=best(seg,src[s["rush"]],s["start"],s["rush"])
        wrong=best(seg,src[other[s["rush"]]],s["start"],s["rush"])
        if not (good>0.8 and good>wrong+0.3): bad+=1
    off+=d
print(bad)
P
)
assert_eq 0 "$CORR" "chaque plage de la sortie est bien l'audio de sa source, à sa place"
assert_contains "$(cat "$A/cuts.md")" "Insertions" "cuts.md liste les collages"
assert_contains "$(cat "$A/cuts.md")" "Prise B" "cuts.md cite la prise source"
X="$A/Prise A.fcpxml"
assert_eq 2 "$(grep -c '<asset id=' "$X")" "fcpxml : deux sources citées"
assert_contains "$(cat "$X")" "Prise%20B.mov" "fcpxml pointe sur le média de B"
assert_eq 1 "$(within "$(grep -o 'sequence format="r1" duration="[^"]*"' "$X" | sed 's/.*duration="//;s/s"//' | "$PY" -I -c "
import sys;from fractions import Fraction as F;print(float(F(sys.stdin.read().strip())))")" "$SUM" 0.0334)" "fcpxml : durée de séquence = somme des plages"

# 3b. source audio seule : même plan, rendu m4a sans image (kind=audio forcé sur A)
mkins '[]'; "$PY" -I "$C" plan "$T/out" "Prise A" > "$T/plan.json"
echo audio > "$A/_work/kind"
"$PY" -I "$C" render "$T/out" "Prise A" "$T/aud.m4a" >/dev/null 2>&1; assert_eq 0 "$?" "collage audio : rendu m4a"
rm -f "$A/_work/kind"
assert_eq "" "$(nstreams "$T/aud.m4a" v:0)" "collage audio : pas de flux vidéo"
SUM=$("$PY" -I -c "import json;print(sum(s['end']-s['start'] for s in json.load(open('$T/plan.json'))))")
assert_eq 1 "$(within "$(nstreams "$T/aud.m4a" a:0)" "$SUM" 0.05)" "collage audio : durée = somme des plages"

# 4. un mot barré dans le collage sort du rendu
mkins "[{\"start\":${MIDW% *},\"end\":${MIDW#* }}]"
"$PY" -I "$C" plan "$T/out" "Prise A" > "$T/plan2.json"
CUTOK=$("$PY" -I - "$T/plan.json" "$T/plan2.json" "${MIDW% *}" "${MIDW#* }" <<'P'
import json,sys
a=sum(s["end"]-s["start"] for s in json.load(open(sys.argv[1])))
p=json.load(open(sys.argv[2])); ws,we=float(sys.argv[3]),float(sys.argv[4])
b=sum(s["end"]-s["start"] for s in p)
inside=any(s["rush"]=="Prise B" and s["start"]<we-0.02 and s["end"]>ws+0.02 for s in p)
print(1 if (not inside and a-b>=(we-ws)-0.05 and p.count(None)==0) else 0)
P
)
assert_eq 1 "$CUTOK" "mot barré du collage : absent du plan, plan plus court"

# 5. B sans keep.json : l'étendue de ses mots
mkins '[]'; mv "$B/keep.json" "$B/keep.json.off"
"$PY" -I "$C" plan "$T/out" "Prise A" > "$T/plan3.json"
assert_eq 1 "$("$PY" -I -c "
import json;p=[s for s in json.load(open('$T/plan3.json')) if s['rush']=='Prise B']
print(1 if len(p)==1 and p[0]['start']<=$DEB and p[0]['end']>=$FIN and p[0]['end']-p[0]['start']<($FIN-$DEB)+0.2 else 0)")" "B sans keep.json : une plage, l'étendue des mots"
mv "$B/keep.json.off" "$B/keep.json"

# 6. refus : rush inconnu, bornes absurdes (aucun fichier écrit)
"$D" studio --no-open >/dev/null 2>&1
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "studio up"
rm -f "$A/inserts.json"
save() { curl -s -X POST -H 'Content-Type: application/json' --data "$1" "http://127.0.0.1:$PORT/save?v=Prise%20A"; }
BASE='"retraction_cuts":[],"restore":[]'
res="$(save "{$BASE,\"inserts\":[{\"apres\":1.0,\"rush\":\"Prise B\",\"debut\":$DEB,\"fin\":$FIN,\"mots\":[{\"w\":\"phrase\",\"s\":$DEB,\"e\":$FIN}],\"barres\":[]}]}")"
assert_contains "$res" '"inserts": 1' "/save accepte un collage et le compte"
assert_contains "$(curl -s "http://127.0.0.1:$PORT/data?v=Prise%20A")" '"inserts": [{"apres": 1.0, "rush": "Prise B"' "/data renvoie les collages"
assert_eq 1 "$("$PY" -I -c "import json;d=json.load(open('$A/inserts.json'))['inserts'];print(len(d))")" "inserts.json écrit par /save"
res="$(save "{$BASE,\"inserts\":[{\"apres\":1.0,\"rush\":\"Prise Z\",\"debut\":1,\"fin\":2}]}")"
assert_contains "$res" "rush inconnu" "rush inconnu refusé"
res="$(save "{$BASE,\"inserts\":[{\"apres\":1.0,\"rush\":\"Prise B\",\"debut\":5,\"fin\":2}]}")"
assert_contains "$res" "error" "bornes inversées refusées"
res="$(save "{$BASE,\"inserts\":[{\"apres\":1.0,\"rush\":\"../Prise B\",\"debut\":1,\"fin\":2}]}")"
assert_contains "$res" "rush inconnu" "rush avec chemin refusé"
assert_eq 1 "$("$PY" -I -c "import json;print(len(json.load(open('$A/inserts.json'))['inserts']))")" "un refus ne touche pas inserts.json"
res="$(save "{$BASE}")"
assert_eq 1 "$("$PY" -I -c "import json;print(len(json.load(open('$A/inserts.json'))['inserts']))")" "un /save sans clé inserts laisse le fichier"
res="$(save "{$BASE,\"inserts\":[]}")"
assert_contains "$res" '"inserts": 0' "/save avec une liste vide efface les collages"
summary
