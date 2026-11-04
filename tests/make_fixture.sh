#!/usr/bin/env bash
# make_fixture.sh <outdir> : writes "<outdir>/fixture test.mov" (space in the name on purpose).
# ~15 s of French speech (a stutter "je je" and a repeated phrase), 1080x1920 black video, AAC audio.
set -euo pipefail
OUT="${1:?usage: make_fixture.sh <outdir>}"
mkdir -p "$OUT"
TXT="$OUT/fixture.txt"
cat > "$TXT" <<'T'
Bonjour, je je voulais vous parler d'une idée simple. [[slnc 900]]
Le montage vidéo prend beaucoup de temps. [[slnc 900]]
Le montage vidéo prend beaucoup de temps. [[slnc 900]]
Alors aujourd'hui, je vous montre comment couper les silences automatiquement. [[slnc 900]]
Merci de m'avoir écouté.
T
say -v Thomas -r 150 -f "$TXT" -o "$OUT/fixture.aiff"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/fixture.aiff")
ffmpeg -nostdin -loglevel error -y -f lavfi -i "color=c=black:s=1080x1920:r=30:d=$DUR" \
  -i "$OUT/fixture.aiff" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$OUT/fixture test.mov"
rm -f "$OUT/fixture.aiff" "$TXT"
echo "$OUT/fixture test.mov"
