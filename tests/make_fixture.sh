#!/usr/bin/env bash
# make_fixture.sh <outdir> [<nom> <fichier texte say>] : writes "<outdir>/<nom>.mov" (défaut : "fixture test.mov",
# un espace dans le nom exprès). Sans nom : ~15 s de français (un bégaiement « je je » et une phrase répétée),
# vidéo noire 1080x1920, AAC. Avec un nom et un fichier texte : ce texte-là est dit (voix Thomas, [[slnc N]] pour les
# silences). FIXTURE_SIZE (défaut 1080x1920) règle les dimensions de l'image.
set -euo pipefail
OUT="${1:?usage: make_fixture.sh <outdir> [<nom> <fichier texte>]}"
NOM="${2:-fixture test}"
SIZE="${FIXTURE_SIZE:-1080x1920}"
mkdir -p "$OUT"
if [ $# -ge 3 ]; then
  TXT="$3"
  KEEPTXT=1
else
  TXT="$OUT/fixture.txt"
  KEEPTXT=0
  cat > "$TXT" <<'T'
Bonjour, je je voulais vous parler d'une idée simple. [[slnc 900]]
Le montage vidéo prend beaucoup de temps. [[slnc 900]]
Le montage vidéo prend beaucoup de temps. [[slnc 900]]
Alors aujourd'hui, je vous montre comment couper les silences automatiquement. [[slnc 900]]
Merci de m'avoir écouté.
T
fi
say -v Thomas -r 150 -f "$TXT" -o "$OUT/fixture.aiff"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/fixture.aiff")
ffmpeg -nostdin -loglevel error -y -f lavfi -i "color=c=black:s=$SIZE:r=30:d=$DUR" \
  -i "$OUT/fixture.aiff" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$OUT/$NOM.mov"
rm -f "$OUT/fixture.aiff"
[ "$KEEPTXT" = 1 ] || rm -f "$TXT"
echo "$OUT/$NOM.mov"
