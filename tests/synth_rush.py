"""Fabrique un rush synthétique (sans ASR) : source ffmpeg + aligned/silence/keep écrits à la main.

Usage : synth_rush.py <root> <stem> [--size 1080x1920] [--fps 30] [--rate 48000] [--paras 4]
                      [--audio] [--freq 440]
Chaque paragraphe = 3 mots de 0,4 s (pas 0,5 s), 1,3 s de silence entre deux paragraphes ;
le dernier mot d'un paragraphe finit par un point. keep.json = un paragraphe par plage (0,1 s de
marge), silence_cuts.json = les silences entre eux.
"""

import argparse
import json
import os
import subprocess

ap = argparse.ArgumentParser()
ap.add_argument("root")
ap.add_argument("stem")
ap.add_argument("--size", default="1080x1920")
ap.add_argument("--fps", type=int, default=30)
ap.add_argument("--rate", type=int, default=48000)
ap.add_argument("--paras", type=int, default=4)
ap.add_argument("--audio", action="store_true")
ap.add_argument("--freq", type=int, default=440)
a = ap.parse_args()

work = os.path.join(a.root, a.stem, "_work")
os.makedirs(work, exist_ok=True)
words, keep, sil = [], [], []
prev_end = 0.0
for p in range(a.paras):
    start = 0.5 + p * 2.7
    ws = []
    for j in range(3):
        s = round(start + j * 0.5, 3)
        w = {"word": f"{a.stem}{p}m{j}" + ("." if j == 2 else ""), "start": s, "end": round(s + 0.4, 3)}
        ws.append(w)
        words.append(w)
    keep.append((round(ws[0]["start"] - 0.1, 3), round(ws[-1]["end"] + 0.1, 3)))
    sil.append((round(prev_end, 3), keep[-1][0]))
    prev_end = keep[-1][1]
dur = round(prev_end + 1.0, 3)
sil.append((prev_end, dur))
gate = "+".join(f"between(t,{w['start']},{w['end']})" for w in words)
src = os.path.join(a.root, a.stem, a.stem + (".m4a" if a.audio else ".mp4"))
audio = ["-f", "lavfi", "-i", f"sine=frequency={a.freq}:sample_rate={a.rate}:duration={dur},volume='{gate}':eval=frame"]
if a.audio:
    cmd = audio + ["-c:a", "aac", src]
else:
    cmd = ["-f", "lavfi", "-i", f"color=c=blue:s={a.size}:r={a.fps}:d={dur}"] + audio + [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src]
subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y"] + cmd, check=True)
open(os.path.join(work, "source.txt"), "w").write(src + "\n")
open(os.path.join(work, "kind"), "w").write(("audio" if a.audio else "video") + "\n")
paras = [words[i : i + 3] for i in range(0, len(words), 3)]
json.dump({"segments": [{"text": " ".join(x["word"] for x in ws), "words": ws} for ws in paras]},
          open(os.path.join(work, "aligned.json"), "w"))
json.dump({"filler_cuts": [{"start": s, "end": e, "kind": "silence"} for s, e in sil]},
          open(os.path.join(work, "silence_cuts.json"), "w"))
json.dump([{"start": s, "end": e} for s, e in keep], open(os.path.join(a.root, a.stem, "keep.json"), "w"))
print(src)
