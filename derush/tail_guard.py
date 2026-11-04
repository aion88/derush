"""Garde des fins de mots : un trou coupé ne commence qu'une fois la voix du mot d'avant éteinte.

Cause mesurée le 2026-10-17 (IMG_4631) : l'alignement CTC finit souvent un mot trop tôt
sur une voyelle tenue, et gap_fillers ouvre la coupe à fin CTC + 0.04 s. La queue du mot
part avec : « Deux, mes emails » rendu « De mes emails » (voyelle à -7 dB coupée de 109.26
à 109.40), « requiert » amputé de 340 ms. 26 coupes sur 82 dans IMG_4631, 14 dans IMG_4632.

Pour chaque coupe de type trou (gap) ou euh écrit (filler) : on mesure l'énergie, et on
repousse le début de la coupe tant que le son reste à moins de 15 dB du pic du mot d'avant,
au plus 0.40 s (au-delà c'est un « euh » collé, qui doit partir). Même chose, en miroir, pour
l'attaque du mot d'après (au plus 0.20 s). Les silences (silencedetect) et les rétractions
ne sont pas touchés.

Usage : tail_guard.py <work_dir>   (réécrit work_dir/all_cuts.json, garde une copie .pre-tail)
"""

import json
import shutil
import sys
import wave

import numpy as np

TAIL_MAX, ONSET_MAX, DROP_DB, MIN_CUT = 0.40, 0.20, 15.0, 0.06

work = sys.argv[1]
cuts = json.load(open(f"{work}/all_cuts.json"))
al = json.load(open(f"{work}/aligned.json"))
words = [w for sg in al["segments"] for w in sg.get("words", [])]
w = wave.open(f"{work}/audio.wav")
sr = w.getframerate()
x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
if w.getnchannels() > 1:
    x = x.reshape(-1, w.getnchannels()).mean(1)
hop = sr // 100  # 10 ms
fr = x[: len(x) // hop * hop].reshape(-1, hop)
db = 20 * np.log10(np.sqrt((fr**2).mean(1)) + 1e-9)


def peak(wd):
    seg = db[int(wd["start"] * 100) : int(wd["end"] * 100) + 1]
    return seg.max() if len(seg) else -99.0


moved = dropped = 0
out = []
for c in cuts:
    if c.get("kind") not in ("gap", "filler"):
        out.append(c)
        continue
    s, e = c["start"], c["end"]
    prev = [wd for wd in words if s - 0.6 < wd["end"] <= s + 0.05]
    if prev:
        lim = peak(prev[-1]) - DROP_DB
        k, kmax = int(s * 100), int((s + TAIL_MAX) * 100)
        while k < min(kmax, len(db)) and db[k] > lim:
            k += 1
        s = max(s, k / 100)
    nxt = [wd for wd in words if e - 0.05 <= wd["start"] < e + 0.6]
    if nxt:
        lim = peak(nxt[0]) - DROP_DB
        k, kmin = int(e * 100) - 1, int((e - ONSET_MAX) * 100)
        while k > max(kmin, 0) and db[k] > lim:
            k -= 1
        e = min(e, (k + 1) / 100)
    if (s, e) != (c["start"], c["end"]):
        moved += 1
    if e - s < MIN_CUT:
        dropped += 1
        continue
    out.append({**c, "start": round(s, 3), "end": round(e, 3)})

shutil.copy(f"{work}/all_cuts.json", f"{work}/all_cuts.pre-tail.json")
json.dump(out, open(f"{work}/all_cuts.json", "w"))
print(
    f"tail_guard : {moved} coupes resserrées sur la voix, {dropped} supprimées (plus rien à couper)"
)
