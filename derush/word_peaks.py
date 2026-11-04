#!/usr/bin/env python3
"""word_peaks.py — is the silence threshold under every spoken word?

Measures the peak level of each aligned word (<= 1 s, really aligned) and the
room floor (5th percentile of 100 ms peaks). Prints a report on stderr and ONE
number on stdout: the --noise to use. It is the given --noise when every word
peaks above it, else min(word peak) - 3 dB, never under floor + 10 dB.

Why (IMG_4594, 2026-10-11): asides spoken 20-30 dB under the main voice
(« courage avec ça » peak -37.6 dB, « c'est cool ça » -46.2 dB, floor -68 dB)
were classed silence at the default -35 dB and cut whole. 111 of 810 words
peaked under -35 dB. Rerun at -50 dB kept them all.

Usage: word_peaks.py aligned.json audio.wav --noise -35
"""
from __future__ import annotations
import argparse, json, sys
import numpy as np, soundfile as sf

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("aligned"); ap.add_argument("wav")
    ap.add_argument("--noise", type=float, required=True)
    a = ap.parse_args()
    data, sr = sf.read(a.wav, dtype="float32")
    if data.ndim > 1: data = data.mean(1)
    words = [w for s in json.load(open(a.aligned))["segments"] for w in s.get("words", [])]
    pk = []
    for w in words:
        s, e = w["start"], w["end"]
        if e <= s or e - s > 1.0 or not w.get("aligned", True): continue
        seg = np.abs(data[int(s * sr):int(e * sr)])
        if len(seg): pk.append(20 * np.log10(seg.max() + 1e-9))
    pk = np.array(pk)
    n = int(0.1 * sr); fr = data[: len(data) // n * n].reshape(-1, n)
    floor = float(np.percentile(20 * np.log10(np.abs(fr).max(1) + 1e-9), 5))
    under = int((pk < a.noise).sum()) if len(pk) else 0
    noise = a.noise
    if under:
        noise = max(floor + 10.0, float(pk.min()) - 3.0)
        noise = min(noise, a.noise)
    print(f"word_peaks: {len(pk)} mots, pic médian {np.median(pk):.1f} dB, plancher {floor:.1f} dB, "
          f"{under} mot(s) sous {a.noise:.0f} dB"
          + (f" → seuil ramené à {noise:.0f} dB" if noise != a.noise else " → seuil gardé"), file=sys.stderr)
    print(f"{noise:.0f}")

if __name__ == "__main__":
    main()
