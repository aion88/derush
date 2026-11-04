#!/usr/bin/env bash
# Audio-only sources (voice memo, podcast): detection, prep, render, export, fcpxml/logos refusals,
# studio upload and serving. Media is generated (say + ffmpeg). Port 8797.
#
# Transcription: no test hook exists in bin/derush, so DERUSH_PY points at a thin wrapper that
# answers ONLY transcribe_qwen.py with the known spoken text (same JSON shape, placeholder times)
# and hands every other call to the real venv python. align_words, silence detection, cuts and
# the guards all run for real; only the Qwen/whisper model is replaced.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/tests/lib.sh"
REAL_PY="${DERUSH_PY:-$HOME/.local/share/derush/venv/bin/python}"
T="$(mktemp -d)"; PORT=8797
export HOME="$T/home"; mkdir -p "$HOME"
export DERUSH_CONFIG="$T/none" DERUSH_EDIT_PORT=$PORT DERUSH_OUT_ROOT="$T/out"
D="$ROOT/bin/derush"
cleanup() { "$D" stop >/dev/null 2>&1; pkill -f "edit_server.py $T/out" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT

TEXT="Bonjour, je voulais vous parler d'une idée simple. Le montage prend du temps. Merci de m'avoir écouté."
cat > "$T/py" <<WRAP
#!/bin/bash
case "\${1:-}" in
  */transcribe_qwen.py)
    out=""; prev=""; for a in "\$@"; do [ "\$prev" = --out ] && out="\$a"; prev="\$a"; done
    exec "$REAL_PY" -I -c '
import json,sys,soundfile as sf
sys.path.insert(0, sys.argv[1]); from transcribe_qwen import to_whisper_shape
json.dump(to_whisper_shape(sys.argv[4], "fr", sf.info(sys.argv[2]).duration), open(sys.argv[3], "w"))
print("stub")' "\$(dirname "\$1")" "\$2" "\$out" "$TEXT" ;;
esac
exec "$REAL_PY" "\$@"
WRAP
chmod +x "$T/py"; export DERUSH_PY="$T/py"

# media: ~6 s of speech with a 1.5 s digital silence in the middle
mkdir -p "$T/in"
printf '%s [[slnc 1500]] %s [[slnc 400]] %s\n' "Bonjour, je voulais vous parler d'une idée simple." "Le montage prend du temps." "Merci de m'avoir écouté." > "$T/say.txt"
say -v Thomas -r 160 -f "$T/say.txt" -o "$T/in/memo.aiff"
ffmpeg -nostdin -loglevel error -y -i "$T/in/memo.aiff" -c:a aac -b:a 128k "$T/in/memo vocal.m4a"
ffmpeg -nostdin -loglevel error -y -f lavfi -i "color=c=red:s=320x320:d=1" -frames:v 1 "$T/cover.png"
ffmpeg -nostdin -loglevel error -y -i "$T/in/memo.aiff" -i "$T/cover.png" -map 0:a -map 1:v \
  -c:a libmp3lame -c:v mjpeg -id3v2_version 3 -disposition:v attached_pic "$T/in/cover.mp3"
ffmpeg -nostdin -loglevel error -y -f lavfi -i "color=c=black:s=320x240:r=24:d=3" -i "$T/in/memo.aiff" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$T/in/clip.mp4"
M4A="$T/in/memo vocal.m4a"; SRC_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$M4A")
nstreams() { ffprobe -v error -select_streams "$2" -show_entries stream=index -of csv=p=0 "$1" | wc -l | tr -d ' '; }

# 1. detection
assert_eq audio "$("$D" kind "$M4A")" "is_audio_only: m4a"
assert_eq audio "$("$D" kind "$T/in/cover.mp3")" "is_audio_only: mp3 with attached cover"
assert_eq video "$("$D" kind "$T/in/clip.mp4")" "is_audio_only: mp4 with video is not audio"
assert_eq 1 "$(nstreams "$T/in/cover.mp3" v)" "fixture: the mp3 really carries a cover stream"
# ffprobe prints "0," (trailing comma) for a video stream with side data (camera .mov with rotation):
# the stub reproduces that exact line; the real file that exposed it was a 4K HEVC iPhone-style .mov.
mkdir -p "$T/stub"; printf '#!/bin/bash\ncase "$*" in *attached_pic*) echo "0,";; *) exec "$(PATH="${PATH#$(dirname "$0"):}" command -v ffprobe)" "$@";; esac\n' > "$T/stub/ffprobe"; chmod +x "$T/stub/ffprobe"
assert_eq video "$(PATH="$T/stub:$PATH" "$D" kind "$T/in/clip.mp4")" "is_audio_only: ffprobe line '0,' still means video"

# 2. prep + render
p="$("$D" prep "$M4A" 2>&1)"; rc=$?
assert_eq 0 "$rc" "prep exits 0 on an audio source"
STEM="memo vocal"; O="$T/out/$STEM"
assert_eq audio "$(cat "$O/_work/kind" 2>/dev/null)" "prep writes _work/kind = audio"
[ -f "$O/memo vocal.m4a" ] && ok=1 || ok=0
assert_eq 1 "$ok" "source moved in with its extension"
r="$("$D" render "$STEM" 2>&1)"; rc=$?
[ "$rc" -ne 0 ] && echo "$r" | tail -8
assert_eq 0 "$rc" "render exits 0"
OUTM="$O/$STEM.derush.m4a"
[ -f "$OUTM" ] && ok=1 || ok=0
assert_eq 1 "$ok" "<STEM>.derush.m4a exists"
if [ -f "$OUTM" ]; then
  assert_eq 0 "$(nstreams "$OUTM" v)" "derush.m4a has no video stream"
  OD=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUTM")
  "$REAL_PY" -I -c "import sys;sys.exit(0 if $SRC_DUR-$OD>=1.0 else 1)" && ok=1 || ok=0
  assert_eq 1 "$ok" "output at least 1 s shorter than the source ($SRC_DUR -> $OD)"
fi
[ -f "$O/cuts.md" ] && ok=1 || ok=0
assert_eq 1 "$ok" "cuts.md written"
[ -e "$O/$STEM.fcpxml" ] || [ -e "$O/$STEM.apercu-look.mp4" ] && ok=0 || ok=1
assert_eq 1 "$ok" "no fcpxml, no look preview for an audio"

# 3. export
e="$("$D" export "$STEM" 2>&1)"; rc=$?
assert_eq 0 "$rc" "export exits 0"
EXPM="$O/$STEM.export.m4a"
[ -f "$EXPM" ] && ok=1 || ok=0
assert_eq 1 "$ok" "<STEM>.export.m4a exists"
[ -f "$EXPM" ] && assert_eq 0 "$(nstreams "$EXPM" v)" "export.m4a has no video stream"
[ -e "$O/$STEM.reel.mp4" ] && ok=1 || ok=0
assert_eq 0 "$ok" "no reel.mp4 for an audio"

# 4. fcpxml / logos refuse in French, no traceback
f="$("$D" fcpxml "$STEM" 2>&1)"; rc=$?
assert_eq 1 "$rc" "fcpxml on audio exits 1"
assert_contains "$f" "source audio : pas de timeline vidéo" "fcpxml French message"
case "$f" in *Traceback*) ok=0;; *) ok=1;; esac
assert_eq 1 "$ok" "fcpxml: no traceback"
f="$("$D" logos "$STEM" 2>&1)"; rc=$?
assert_eq 1 "$rc" "logos on audio exits 1"
assert_contains "$f" "pas de logos sur un audio" "logos French message"
f="$("$REAL_PY" -I "$ROOT/derush/fcpxml.py" "$O/memo vocal.m4a" "$O/keep.json" "$T/x.fcpxml" x 2>&1)"; rc=$?
assert_eq 1 "$rc" "fcpxml.py direct on audio exits 1"
assert_contains "$f" "source audio : pas de timeline vidéo" "fcpxml.py direct message"

# 5. studio: upload an .m4a, it is accepted, prepped, served as audio with Range
"$D" studio --no-open >/dev/null 2>&1
assert_eq derush "$(curl -s "http://127.0.0.1:$PORT/health")" "studio up"
cp "$T/in/memo.aiff" "$T/in/up.aiff"; ffmpeg -nostdin -loglevel error -y -i "$T/in/up.aiff" -c:a aac "$T/in/Mon Upload.m4a"
res="$(curl -s -X POST --data-binary @"$T/in/Mon Upload.m4a" "http://127.0.0.1:$PORT/upload?name=Mon%20Upload.m4a&lang=fr")"
assert_eq '{"stem": "Mon_Upload"}' "$res" "upload .m4a accepted"
bad="$(curl -s -X POST --data-binary "x" "http://127.0.0.1:$PORT/upload?name=notes.txt")"
assert_contains "$bad" "format non pris en charge" "upload .txt refused"
U="$T/out/Mon_Upload"
for _ in $(seq 1 90); do [ -s "$U/_work/proxy.m4a" ] && break; sleep 1; done
[ -s "$U/_work/proxy.m4a" ] && ok=1 || ok=0
assert_eq 1 "$ok" "studio job made proxy.m4a"
h="$(curl -s -D - -o /dev/null "http://127.0.0.1:$PORT/proxy.m4a?v=Mon_Upload")"
assert_contains "$h" "Content-Type: audio/mp4" "proxy served as audio/mp4"
h="$(curl -s -D - -o /dev/null -H 'Range: bytes=0-99' "http://127.0.0.1:$PORT/proxy.m4a?v=Mon_Upload")"
assert_contains "$h" "206" "Range answered 206"
assert_contains "$h" "Content-Range: bytes 0-99/" "Content-Range kept"
assert_contains "$(curl -s "http://127.0.0.1:$PORT/videos")" '"kind": "audio"' "/videos reports kind audio"
curl -s -X POST "http://127.0.0.1:$PORT/render?v=Mon_Upload" >/dev/null
for _ in $(seq 1 90); do [ -s "$U/Mon_Upload.derush.m4a" ] && break; sleep 1; done
sleep 1
h="$(curl -s -D - -o /dev/null "http://127.0.0.1:$PORT/result.m4a?v=Mon_Upload")"
assert_contains "$h" "Content-Type: audio/mp4" "result served as audio/mp4"
assert_contains "$(curl -s "http://127.0.0.1:$PORT/data?v=Mon_Upload")" '"rendered": true' "/data rendered true on .derush.m4a"
summary
