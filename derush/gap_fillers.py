#!/usr/bin/env python3
"""gap_fillers.py — hesitations whisper heard but did not write.

Even with a disfluent initial_prompt, whisper drops most "euh"/"mmh" from the
text: they survive only as a NON-SILENT gap between two word timestamps.
INPUT MUST BE align_words.py OUTPUT, never raw whisper: whisper word edges drift
0.1-0.4 s, and on IMG_4542 the "gaps" after TikTok/Instagram/system were the
end of the word itself (clipped in the first cut). Gaps bordered by a word whose
alignment score is < --min-score are skipped: the edge is not trustworthy.
Measured on IMG_4542 (2026-10-07): 1 "euh" written by whisper, while 4 of 8
sampled non-silent gaps re-transcribed as "Euh...". So: any gap between
consecutive words >= --min is cut (prune.py unions it with the silence
cuts, so overlap is harmless), shrunk by --pad on each side so word edges are never clipped.

Usage:
  gap_fillers.py --words audio.json --out gap_cuts.json
                 [--min 0.3] [--pad 0.04] [--min-score 0.3]

Output: {"filler_cuts": [{"start","end","kind":"gap","after","before"}]}
"""

from __future__ import annotations

import argparse
import json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--words", required=True, help="whisper JSON with segments[].words[]"
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--min", type=float, default=0.3)
    ap.add_argument("--pad", type=float, default=0.04)
    ap.add_argument("--min-score", type=float, default=0.3)
    a = ap.parse_args()

    words = [
        w for s in json.load(open(a.words))["segments"] for w in s.get("words", [])
    ]
    cuts = []
    for w, nxt in zip(words, words[1:]):
        gs, ge = w["end"], nxt["start"]
        if ge - gs < a.min:
            continue
        if min(w.get("score", 0.0), nxt.get("score", 0.0)) < a.min_score:
            continue
        cs, ce = gs + a.pad, ge - a.pad
        if ce - cs > 0.1:
            cuts.append(
                {
                    "start": round(cs, 3),
                    "end": round(ce, 3),
                    "kind": "gap",
                    "after": w["word"].strip(),
                    "before": nxt["word"].strip(),
                }
            )
    json.dump({"filler_cuts": cuts}, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(
        f"{len(cuts)} hidden-hesitation gaps, {sum(c['end'] - c['start'] for c in cuts):.1f}s"
    )


if __name__ == "__main__":
    main()
