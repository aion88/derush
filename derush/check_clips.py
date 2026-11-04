#!/usr/bin/env python3
"""check_clips.py — does keep.json clip any word that was meant to stay?

Every aligned word (align_words.py output) must be either fully kept or fully
inside a retraction cut. A word partly cut, or cut without a retraction, is a
clipped word: exit 1 and list it. This is the test that would have caught
TikTok / Instagram / design system on IMG_4542.

Loss that falls inside an acoustic silence (silence_cuts.json, energy below the
threshold) is not a clip: CTC sometimes stretches a word over the pause next to it.

A word removed by detect_fillers (filler_cuts.json: written "euh", "hein",
stutter "et et") is a deliberate cut too, pass --fillers so it is not reported.

Usage: check_clips.py aligned.json keep.json retraction_cuts.json
                      [--silence silence_cuts.json] [--fillers filler_cuts.json] [--tol 0.03]
"""

from __future__ import annotations

import argparse
import json
import re
import sys

FILLER = re.compile(r"^\W*(euh+|heu+|hum+|hmm+|mm+h?|mh|um+|uh+)\W*$", re.I)


def overlap(a: float, b: float, spans: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in spans)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("aligned")
    ap.add_argument("keep")
    ap.add_argument("retractions")
    ap.add_argument("--silence", default=None)
    ap.add_argument("--fillers", default=None, help="filler_cuts.json from detect_fillers")
    ap.add_argument(
        "--tol", type=float, default=0.03, help="seconds of edge loss tolerated"
    )
    a = ap.parse_args()

    words = [
        w for s in json.load(open(a.aligned))["segments"] for w in s.get("words", [])
    ]
    keep = [(k["start"], k["end"]) for k in json.load(open(a.keep))]
    ret = json.load(open(a.retractions))
    ret = [
        (r["start"], r["end"])
        for r in (ret.get("retraction_cuts", ret) if isinstance(ret, dict) else ret)
    ]
    sil = [(c["start"], c["end"]) for c in json.load(open(a.silence))["filler_cuts"]] if a.silence else []
    fil = [(c["start"], c["end"]) for c in json.load(open(a.fillers))] if a.fillers else []
    bad, swallowed = [], []
    for w in words:
        s, e = w["start"], w["end"]
        if e - s <= 0 or not w.get("aligned", True) or FILLER.match(w["word"]):
            continue
        if overlap(s, e, ret) >= (e - s) - a.tol:
            continue  # deliberately retracted
        if overlap(s, e, fil) >= (e - s) - a.tol:
            continue  # deliberately cut as filler / stutter
        kept = overlap(s, e, keep)
        if kept <= a.tol:
            # Nothing of the word survives. The silence exception below is for a
            # word STRETCHED over a pause, never for a word the threshold swallowed
            # whole: IMG_4594 (2026-10-11) lost « hein », « courage avec ça »,
            # « c'est cool ça » this way, all spoken 20-30 dB under the main voice,
            # and the guard said « 0 clipped word ». Fix = silence_cuts --noise lower.
            swallowed.append(f"{w['word'].strip()!r} {s:.2f}-{e:.2f} entirely inside a silence cut")
            continue
        lost = (e - s) - kept - overlap(s, e, sil)
        if lost <= a.tol:
            continue
        bad.append(f"{w['word'].strip()!r} {s:.2f}-{e:.2f} lost {lost:.2f}s")
    print("\n".join(bad) or "no clipped word")
    print(f"{len(bad)} clipped word(s)")
    if swallowed:
        print("\n".join(swallowed))
        print(f"{len(swallowed)} word(s) swallowed by the silence threshold: rerun silence_cuts.py with a lower --noise (measure the word peaks first)")
    sys.exit(1 if (bad or swallowed) else 0)


if __name__ == "__main__":
    main()
