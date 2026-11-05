#!/usr/bin/env bash
# make_fixture.sh <outdir> [name] : writes "<outdir>/<name>.mov" (default "fixture test", space on purpose).
# FIXTURE_TEXT (env) replaces the default spoken text.
# ~15 s of French speech (a stutter "je je" and a repeated phrase), 1080x1920 black video, AAC audio.
set -euo pipefail
OUT="${1:?usage: make_fixture.sh <outdir> [name]}"
NAME="${2:-fixture test}"
mkdir -p "$OUT"
TXT="$OUT/$NAME.txt"
if [ -n "${FIXTURE_TEXT:-}" ]; then printf '%s\n' "$FIXTURE_TEXT" > "$TXT"; else cat > "$TXT" <<'T'
Bonjour, je je voulais vous parler d'une idée simple. [[slnc 900]]
Le montage vidéo prend beaucoup de temps. [[slnc 900]]
Le montage vidéo prend beaucoup de temps. [[slnc 900]]
Alors aujourd'hui, je vous montre comment couper les silences automatiquement. [[slnc 900]]
Merci de m'avoir écouté.
T
fi
say -v Thomas -r 150 -f "$TXT" -o "$OUT/$NAME.aiff"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$NAME.aiff")
ffmpeg -nostdin -loglevel error -y -f lavfi -i "color=c=black:s=1080x1920:r=30:d=$DUR" \
  -i "$OUT/$NAME.aiff" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$OUT/$NAME.mov"
rm -f "$OUT/$NAME.aiff" "$TXT"
echo "$OUT/$NAME.mov"
