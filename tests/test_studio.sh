#!/usr/bin/env bash
# Studio lifecycle: --no-open, reuse, job through bin/derush, stop, foreign port. Port 8799.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
DERUSH_PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"
export DERUSH_PY
T="$(mktemp -d)"; PORT=8799
export HOME="$T/home"; mkdir -p "$HOME"          # throwaway HOME: logs and pid stay out of the real one
export DERUSH_CONFIG="$T/none" DERUSH_EDIT_PORT=$PORT DERUSH_OUT_ROOT="$T/out"
# Cas B du placement d'un projet : un LLM simulé (commande qui répond un JSON fixe), jamais un vrai appel.
export DERUSH_LLM='cat >/dev/null; echo "{\"apres\": 0, \"couper_a_mot\": null, \"raison\": \"test\"}"'
HTTP_PID=""
cleanup() { "$ROOT/bin/derush" stop >/dev/null 2>&1; [ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null
  pkill -f "edit_server.py $T/out" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
D="$ROOT/bin/derush"
count() { pgrep -f "edit_server.py $T/out" | wc -l | tr -d ' '; }

# 1. start detached, no browser
out="$("$D" studio --no-open 2>&1)"; rc=$?
assert_eq 0 "$rc" "studio --no-open exits 0"
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "/health answers derush"
pid1="$(cat "$HOME/Library/Logs/derush/studio-$PORT.pid")"
assert_eq 1 "$(count)" "one server process"

# 2. second start reuses; with an opener it opens once, without --no-open
echo 0 > "$T/opened"
cat > "$T/opener" <<OP
#!/bin/sh
echo "\$1" >> "$T/opened.log"
OP
chmod +x "$T/opener"
DERUSH_OPEN="$T/opener" "$D" studio >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "second studio exits 0"
assert_eq "$pid1" "$(cat "$HOME/Library/Logs/derush/studio-$PORT.pid")" "same pid after reuse"
assert_eq 1 "$(count)" "still one server process"
assert_contains "$(cat "$T/opened.log" 2>/dev/null)" "http://127.0.0.1:$PORT" "reuse opened the browser"
# edit <STEM> on a running studio: opens /edit?v=, no second server
mkdir -p "$T/out/fixture test/_work"
bash "$ROOT/tests/make_fixture.sh" "$T" >/dev/null
echo "$T/fixture test.mov" > "$T/out/fixture test/_work/source.txt"
echo "{}" > "$T/out/fixture test/_work/aligned.json"
DERUSH_OPEN="$T/opener" "$D" edit "fixture test" >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "edit on running studio exits 0"
assert_contains "$(cat "$T/opened.log")" "/edit?v=fixture%20test" "edit opened /edit?v=<stem>"
assert_eq 1 "$(count)" "edit started no second server"

# 3. a real job through the HTTP API runs bin/derush (proves the path passed to the server)
rm -f "$T/out/fixture test/_work/proxy.mp4"   # edit already made one: remove it so the job must recreate it
curl -s -X POST "http://127.0.0.1:$PORT/proxy?v=fixture%20test" >/dev/null
for _ in $(seq 1 60); do [ -s "$T/out/fixture test/_work/proxy.mp4" ] && break; sleep 1; done
[ -s "$T/out/fixture test/_work/proxy.mp4" ] && ok=1 || ok=0
assert_eq 1 "$ok" "studio job (derush proxy) produced proxy.mp4"
r=$(curl -s -X POST "http://127.0.0.1:$PORT/reveal?v=fixture%20test")
case "$r" in *"fixture test"*) ok=1;; *) ok=0;; esac
assert_eq 1 "$ok" "/reveal answers with the video path or folder"

# 3a. projets : routes /projet*
U="http://127.0.0.1:$PORT"
R="$T/out/fixture test"
"$DERUSH_PY" -I - "$R/_work/aligned.json" <<'PYEOF'
import json, sys
mm = [("un",1.0),("deux",1.5),("trois",2.0),("quatre.",2.5),("cinq",5.0),("six",5.5),("sept",6.0),("huit.",6.5)]
w = [{"word": t, "start": s, "end": round(s + 0.4, 3)} for t, s in mm]
json.dump({"segments": [{"text": "un deux trois quatre.", "words": w[:4]}, {"text": "cinq six sept huit.", "words": w[4:]}]}, open(sys.argv[1], "w"))
PYEOF
echo '[{"start":0.8,"end":3.1},{"start":4.8,"end":7.0}]' > "$R/keep.json"
assert_eq "[]" "$(curl -s "$U/projets")" "GET /projets: none yet"
r=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$U/projet/new" -d '{"nom":"essai","rushs":["fixture test"]}')
assert_eq 200 "$r" "POST /projet/new creates a project"
[ -f "$T/out/_projets/essai/projet.json" ] && ok=1 || ok=0; assert_eq 1 "$ok" "projet.json written under _projets/essai"
r=$(curl -s -w ' %{http_code}' -X POST "$U/projet/new" -d '{"nom":"essai","rushs":["fixture test"]}')
assert_contains "$r" "existe déjà" "POST /projet/new twice: message"
assert_contains "$r" "409" "POST /projet/new twice: 409"
r=$(curl -s -w ' %{http_code}' -X POST "$U/projet/new" -d '{"nom":"a b","rushs":[]}')
assert_contains "$r" "nom de projet invalide" "bad project name: message"
assert_contains "$r" "400" "bad project name: 400"
D1="$(curl -s "$U/projet/data?p=essai")"
assert_contains "$D1" '"sequence"' "/projet/data has the sequence"
assert_contains "$D1" '"texte": "un deux trois quatre. cinq six sept huit."' "/projet/data carries the first words of the clip"
assert_contains "$(curl -s "$U/projets")" '"nom": "essai"' "/projets lists the project"
cp "$T/out/_projets/essai/projet.json" "$T/projet.before"
r=$(curl -s -w ' %{http_code}' -X POST "$U/projet/save?p=essai" -d '{"sequence":[{"rush":"inconnu","debut":0,"fin":1}]}')
assert_contains "$r" "400" "save with an unknown rush: 400"
cmp -s "$T/projet.before" "$T/out/_projets/essai/projet.json" && ok=1 || ok=0
assert_eq 1 "$ok" "save refused: projet.json unchanged"
r=$(curl -s -w ' %{http_code}' -X POST "$U/projet/save?p=a%20b" -d '{"sequence":[]}')
assert_contains "$r" "404" "save on a bad project name: 404"
assert_contains "$(curl -s -o /dev/null -w '%{http_code}' "$U/projet?p=essai")" "200" "GET /projet page"
assert_eq 404 "$(curl -s -o /dev/null -w '%{http_code}' "$U/data?v=_projets")" "/data?v=_projets is not a rush"
case "$(curl -s "$U/videos")" in *_projets*) bad=1;; *) bad=0;; esac; assert_eq 0 "$bad" "/videos does not list _projets"
# placer : le projet de ce seul rush n'a pas de bloc libre, on raccourcit la séquence d'abord
B1="$("$DERUSH_PY" -I -c 'import json,sys;sys.path.insert(0,sys.argv[1]);import projet;print(json.dumps({"sequence":projet.blocs(sys.argv[2],"fixture test")[:1]}))' "$ROOT/derush" "$T/out")"
r=$(curl -s -X POST "$U/projet/save?p=essai" -d "$B1")
assert_contains "$r" '"sequence"' "save a shorter sequence"
LIB="$("$DERUSH_PY" -I -c 'import json,sys;d=json.load(sys.stdin);print(json.dumps({"bloc":{k:d["rushs"][0]["libres"][0][k] for k in ("rush","debut","fin")}}))' <<<"$(curl -s "$U/projet/data?p=essai")")"
r=$(curl -s -X POST "$U/projet/placer?p=essai" -d "$LIB")
assert_contains "$r" '"cas"' "placer answers with a proposal"
assert_contains "$(curl -s "$U/projet/data?p=essai")" '"propositions": [{' "the proposal is stored, not applied"
r=$(curl -s -X POST "$U/projet/placer?p=essai" -d '{"refuser":0}')
assert_contains "$(curl -s "$U/projet/data?p=essai")" '"propositions": []' "refuser clears the proposal"
# rendu du projet par un job, sans rush fantôme dans /videos
r=$(curl -s -X POST "$U/projet/render?p=essai")
for _ in $(seq 1 90); do case "$(curl -s "$U/job?v=projet:essai")" in *'"running": false'*) break;; esac; sleep 1; done
assert_contains "$(curl -s "$U/job?v=projet:essai")" '"running": false' "project render job ended"
assert_contains "$(curl -s "$U/job?v=projet:essai")" '"ok": true' "project render job succeeded (not just ended)"
assert_contains "$(curl -s "$U/projet/data?p=essai")" '"perime": false' "rendered project is not stale"
curl -s -X POST "$U/projet/save?p=essai" -d "$B1" >/dev/null
assert_contains "$(curl -s "$U/projet/data?p=essai")" '"perime": true' "a sequence edit after the render marks the result stale"
case "$(curl -s "$U/videos")" in *projet:*) bad=1;; *) bad=0;; esac; assert_eq 0 "$bad" "/videos has no ghost rush after a project render"
r=$(curl -s -w ' %{http_code}' -X POST "$U/upload?name=x.mov&projet=nope" -d 'x')
assert_contains "$r" "projet inconnu" "upload into an unknown project"
assert_contains "$r" "404" "upload into an unknown project: 404"
# corps JSON inattendu, nom avec saut de ligne, projet abîmé, nom de fichier en _
r=$(curl -s -w ' %{http_code}' -X POST "$U/projet/new" -d '[]'); assert_contains "$r" "400" "non-object JSON body: 400, not a dropped connection"
r=$(curl -s -w ' %{http_code}' -X POST "$U/projet/new" -d '{"nom":"demo\n","rushs":[]}'); assert_contains "$r" "400" "project name with a trailing newline: 400"
mkdir -p "$T/out/_projets/casse"; echo '{' > "$T/out/_projets/casse/projet.json"
r="$(curl -s "$U/projets")"
assert_contains "$r" '"nom": "essai"' "one broken project does not hide the others"
assert_contains "$r" '"illisible": true' "the broken project is listed as unreadable"
rm -rf "$T/out/_projets/casse"
r=$(curl -s -w ' %{http_code}' -X POST "$U/upload?name=_x.mov" -d 'x'); assert_contains "$r" "400" "upload with a name starting with _: 400"
# un rush parti : message français, le serveur répond toujours
mv "$R" "$T/out/fixture-away"
assert_contains "$(curl -s "$U/projet/data?p=essai")" "rush introuvable" "rush folder gone: French error"
assert_eq derush "$(curl -s "$U/health")" "server still answers"
mv "$T/out/fixture-away" "$R"
# 3a3. piste : opérations, données de clip, vignette
pyj() { "$DERUSH_PY" -I -c 'import json,sys;d=json.loads(sys.argv[1]);print(" ".join(str(eval(e)) for e in sys.argv[2:]))' "$@"; }
op() { curl -s -X POST "$U/projet/op?p=${2:-essai}" -d "$1"; }
opc() { curl -s -o /dev/null -w '%{http_code}' -X POST "$U/projet/op?p=${2:-essai}" -d "$1"; }
curl -s -X POST "$U/projet/save?p=essai" -d '{"sequence":[{"rush":"fixture test","debut":0.8,"fin":7.0}]}' >/dev/null
r="$(op '{"op":"couper","i":0,"t":4.0}')"
assert_eq "2 3.1 4.8" "$(pyj "$r" 'len(d["sequence"])' 'd["sequence"][0]["fin"]' 'd["sequence"][1]["debut"]')" "op couper in a rush-cut gap: two clips, lossless bounds"
assert_eq "2.3 2.2" "$(pyj "$r" 'd["sequence"][0]["duree"]' 'd["sequence"][1]["duree"]')" "clip duree = sum of its played ranges"
assert_eq "[[0.8, 3.1]]" "$(pyj "$r" 'd["sequence"][0]["plages"]')" "clip carries its played ranges"
assert_contains "$r" '"vignette": "/projet/vignette?p=essai&rush=fixture%20test&t=' "clip carries its thumbnail url"
assert_eq "un deux trois quatre." "$(pyj "$r" 'd["sequence"][0]["texte"]')" "clip carries its first words"
assert_eq "[]" "$(pyj "$r" 'd["sequence"][0]["mot_coupe"]')" "clip without a hand-cut word: empty mot_coupe"
assert_eq "30.0 True" "$(pyj "$r" 'd["rushs"][0]["fps"]' 'd["rushs"][0]["pas"] > 0.03')" "rush carries fps and frame step"
r="$(op '{"op":"deplacer","i":1,"j":0}')"
assert_eq "4.8 0.8" "$(pyj "$r" 'd["sequence"][0]["debut"]' 'd["sequence"][1]["debut"]')" "op deplacer swaps the clips"
r="$(op '{"op":"trimmer","i":0,"cote":"debut","t":4.5}')"
assert_eq "2.5" "$(pyj "$r" 'd["sequence"][0]["duree"]')" "op trimmer outward plays the time the rush edit had cut"
r="$(op '{"op":"retirer","i":0}')"
assert_eq 1 "$(pyj "$r" 'len(d["sequence"])')" "op retirer removes the clip"
assert_eq 400 "$(opc '{"op":"retirer","i":9}')" "op retirer out of range: 400"
assert_eq 400 "$(opc '{"op":"zzz"}')" "unknown op: 400"
assert_eq 400 "$(opc '[]')" "non-object op body: 400"
assert_eq 400 "$(opc '{"op":"couper","i":0,"t":0.0}')" "cut outside the clip: 400"
assert_eq 404 "$(opc '{"op":"retirer","i":0}' nope)" "op on an unknown project: 404"
V="$U/projet/vignette?p=essai&rush=fixture%20test"
assert_eq "200 image/jpeg" "$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$V&t=1.2")" "vignette: a jpeg"
VG="$T/out/_projets/essai/_work/vignettes"
ls "$VG"/*.jpg >/dev/null 2>&1 && ok=1 || ok=0; assert_eq 1 "$ok" "vignette cached under _work/vignettes"
F1="$(ls "$VG"/*.jpg | head -1)"; M1="$(stat -f %m "$F1")"; sleep 1
curl -s -o /dev/null "$V&t=1.2"
assert_eq "$M1" "$(stat -f %m "$F1")" "vignette served from the cache the second time"
assert_eq 200 "$(curl -s -o /dev/null -w '%{http_code}' "$V&t=1.3")" "vignette: t quantised (1.3 shares 1.5)"
assert_eq 400 "$(curl -s -o /dev/null -w '%{http_code}' "$U/projet/vignette?p=essai&rush=zzz&t=1")" "vignette: rush outside the project: 400"
assert_eq 400 "$(curl -s -o /dev/null -w '%{http_code}' "$V&t=nan")" "vignette: nan: 400"
assert_eq 200 "$(curl -s -o /dev/null -w '%{http_code}' "$V&t=-5")" "vignette: negative t clamped"
assert_eq 200 "$(curl -s -o /dev/null -w '%{http_code}' "$V&t=99999")" "vignette: huge t clamped"
assert_eq 4 "$(ls "$VG" | wc -l | tr -d ' ')" "vignette cache stays bounded (4 distinct quantised times)"

# 3a2. pages : projet.html, edit.html et home.html se chargent ; leur script au moins se parse
PG="$(curl -s "$U/projet?p=essai")"
assert_contains "$PG" 'id="piste"' "projet page has the track"
assert_contains "$PG" "Monter le projet" "projet page has the render button"
for page in projet edit home; do
  js="$("$DERUSH_PY" -I -c 'import re,sys;m=re.search(r"<script>(.*)</script>",open(sys.argv[1]).read(),re.S);print(m.group(1) if m else "")' "$ROOT/derush/$page.html")"
  if [ -z "$js" ]; then r="no script"; else r="$(osascript -l JavaScript -e 'function run(a){ new Function(a[0]); return "ok" }' "$js" 2>&1)"; fi
  assert_eq ok "$r" "$page.html: script parses"
done

# 3a2b. projet.html : la logique pure (messages de job, largeurs, tête de lecture, trajet) se teste hors navigateur
HELP="$("$DERUSH_PY" -I -c 'import re,sys;print(re.search(r"// <helpers>.*?// </helpers>",open(sys.argv[1]).read(),re.S).group(0))' "$ROOT/derush/projet.html")"
CASES='const W = o => o.widths.map(Math.round);
const cs = [{duree:10},{duree:10}];
const tr = trajet([{rush:"a",plages:[[0,2],[3,4]]},{rush:"b",plages:[[10,12]]}]);
const P = p => p && [p.k, Math.round(p.src*1000)/1000];
return JSON.stringify([
  msgJob({error:true,tail:["x","y"]}), msgJob({error:false,tail:["x"]}), msgJob({running:true}),
  typeJson({error:true}), typeJson({error:"boum"}), typeJson({running:false}),
  W(largeurs(cs,200,40)), W(largeurs([{duree:1},{duree:9}],100,40)), W(largeurs([{duree:1},{duree:1},{duree:1}],100,40)), W(largeurs([],100,40)),
  clipAt([100,100],50), clipAt([100,100],100), clipAt([100,100],999), clipAt([100,100],-5), clipAt([],5),
  tempsDepuisX(cs,[100,100],150), tempsDepuisX(cs,[100,100],0), tempsDepuisX(cs,[100,100],200),
  xDepuisTemps(cs,[100,100],15), xDepuisTemps(cs,[100,100],20), xDepuisTemps(cs,[100,100],0),
  pasImage({pas:0.04}), Math.round(pasImage(undefined)*10000)/10000,
  bordApres({debut:2,fin:5},"fin",3,1/30), bordApres({debut:2,fin:5},"debut",-1,1/30),
  tr.map(s => [s.clip,s.a,s.z,s.debut]), dureeTrajet(tr), dureeTrajet([]),
  P(positionGlobale(tr,2.5)), P(positionGlobale(tr,3.5)), positionGlobale(tr,5), P(positionGlobale(tr,-1)), P(positionGlobale(tr,2)),
  globalDe(tr,1,3.5), suivant(tr,0), suivant(tr,2)])'
R="$(osascript -l JavaScript -e 'function run(a){ return new Function(a[0] + String.fromCharCode(10) + a[1])() }' "$HELP" "$CASES" 2>&1)"
assert_eq '["En échec : x y",null,null,false,true,false,[100,100],[40,60],[40,40,40],[],0,1,1,0,-1,15,0,20,150,200,0,0.04,0.0333,5.1,1.9667,[[0,0,2,0],[0,3,4,2],[1,10,12,3]],5,0,[1,3.5],[2,10.5],null,[0,0],[1,3],2.5,1,null]' "$R" "projet.html helpers: job message, widths, playhead mapping, play path"
PH="$(cat "$ROOT/derush/projet.html")"
assert_contains "$PH" '"/projet/op"' "projet.html drives the track through /projet/op"
for banned in placer ".slot" "Accepter"; do case "$PH" in *"$banned"*) bad=1;; *) bad=0;; esac; assert_eq 0 "$bad" "projet.html no longer carries « $banned »"; done

# 3a3. l'accueil liste les projets au-dessus des rushs
HM="$(curl -s "$U/")"
case "$HM" in *"Tes projets"*) a=${HM%%Tes projets*}; b=${HM%%Tes rushs*}; [ ${#a} -lt ${#b} ] && ok=1 || ok=0;; *) ok=0;; esac
assert_eq 1 "$ok" "home: « Tes projets » comes before « Tes rushs »"
assert_contains "$HM" "Nouveau projet" "home: new project button"

# 3b. detached into its own session: a launcher that dies with its process group leaves the studio up
"$D" stop >/dev/null 2>&1
# The launcher leads its own group (pgid = its pid) and stays alive after starting the studio, so
# that group exists and WOULD hold the server if it were not detached. kill errors are not hidden.
"$DERUSH_PY" -c 'import os,sys;os.setpgid(0,0);os.execvp(sys.argv[1],sys.argv[1:])' \
  bash -c '"$0" studio --no-open >/dev/null 2>&1; sleep 30' "$D" >/dev/null 2>&1 &
LPG=$!
for _ in $(seq 1 40); do [ "$(curl -s "http://127.0.0.1:$PORT/health")" = derush ] && break; sleep 0.5; done
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "studio up from the launcher"
kill -9 -- -"$LPG"; assert_eq 0 "$?" "launcher group killed"
sleep 1
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "studio survives its launcher's process group"

# 4. stop
"$D" stop >/dev/null 2>&1; rc=$?
assert_eq 0 "$rc" "stop exits 0"
sleep 1
curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && up=1 || up=0
assert_eq 0 "$up" "port closed after stop"
[ -e "$HOME/Library/Logs/derush/studio-$PORT.pid" ] && ok=1 || ok=0
assert_eq 0 "$ok" "pidfile removed"
"$D" stop >/dev/null 2>&1; assert_eq 0 "$?" "stop when not running exits 0"

# 4b. stop refuses a pid that is not our server (bogus pidfile -> sleep)
sleep 60 & SL=$!
mkdir -p "$HOME/Library/Logs/derush"; echo "$SL" > "$HOME/Library/Logs/derush/studio-$PORT.pid"
"$D" stop >/dev/null 2>&1
kill -0 "$SL" 2>/dev/null && ok=1 || ok=0
assert_eq 1 "$ok" "stop leaves a foreign pid alive"
[ -e "$HOME/Library/Logs/derush/studio-$PORT.pid" ] && ok=1 || ok=0
assert_eq 0 "$ok" "bogus pidfile removed"
kill "$SL" 2>/dev/null

# 4c. two studios on two ports: stopping one leaves the other's pidfile; a lost pidfile still stops ours (lsof)
"$D" studio --no-open >/dev/null 2>&1
DERUSH_EDIT_PORT=$((PORT+1)) "$D" studio --no-open >/dev/null 2>&1
DERUSH_EDIT_PORT=$((PORT+1)) "$D" stop >/dev/null 2>&1
[ -e "$HOME/Library/Logs/derush/studio-$PORT.pid" ] && ok=1 || ok=0
assert_eq 1 "$ok" "stopping port+1 keeps port's pidfile"
rm -f "$HOME/Library/Logs/derush/studio-$PORT.pid"
"$D" stop >/dev/null 2>&1; sleep 1
curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && up=1 || up=0
assert_eq 0 "$up" "stop without pidfile stops our server found on the port"

# 5. foreign program on the port
"$DERUSH_PY" -m http.server $PORT --bind 127.0.0.1 >/dev/null 2>&1 & HTTP_PID=$!
sleep 1
out="$("$D" studio --no-open 2>&1)"; rc=$?
assert_eq 3 "$rc" "foreign port exits 3"
assert_contains "$out" "le port $PORT est pris par un autre programme (DERUSH_EDIT_PORT pour en changer)" "foreign port message"
"$D" stop >/dev/null 2>&1
kill -0 "$HTTP_PID" 2>/dev/null && ok=1 || ok=0
assert_eq 1 "$ok" "stop never kills a foreign process"
summary
