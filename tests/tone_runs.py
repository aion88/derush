"""Transitions de tonalité d'un fichier audio (tests de rendu de projet, stdlib seule).

Usage : tone_runs.py <fichier> <hz>[,<hz>…]
Fenêtres de 10 ms sur le son mono 16 kHz ; la fréquence d'une fenêtre = croisements de zéro × 50. Une fenêtre
est classée sur le plus proche des Hz donnés si elle en est à moins de 25 %, sinon c'est du silence.
Sort une ligne par changement de tonalité : « fin_du_dernier_son_précédent début_du_premier_son_suivant de vers ».
"""

import array
import subprocess
import sys

f, hz = sys.argv[1], [float(x) for x in sys.argv[2].split(",")]
pcm = subprocess.run(
    ["ffmpeg", "-nostdin", "-v", "error", "-i", f, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
    capture_output=True, check=True,
).stdout
s = array.array("h")
s.frombytes(pcm[: len(pcm) // 2 * 2])
W = 160
segs = []  # [classe, début, fin, nombre de fenêtres]
for k in range(len(s) // W):
    w = s[k * W : (k + 1) * W]
    if max(abs(x) for x in w) < 800:
        continue
    n = sum(1 for a, b in zip(w, w[1:]) if (a < 0) != (b < 0))
    freq = n * 50.0
    c = min(hz, key=lambda h: abs(h - freq))
    if abs(c - freq) > 0.25 * c:
        continue
    t0, t1 = k * 0.01, (k + 1) * 0.01
    if segs and segs[-1][0] == c:
        segs[-1][2] = t1
        segs[-1][3] += 1
    else:
        segs.append([c, t0, t1, 1])
# un transitoire de quelques fenêtres n'est pas une tonalité : on le retire, puis on refusionne
segs = [g for g in segs if g[3] >= 5]
fus = []
for g in segs:
    if fus and fus[-1][0] == g[0]:
        fus[-1][2] = g[2]
    else:
        fus.append(list(g))
for a, b in zip(fus, fus[1:]):
    print(f"{a[2]:.3f} {b[1]:.3f} {int(a[0])} {int(b[0])}")
