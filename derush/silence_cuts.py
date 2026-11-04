#!/usr/bin/env python3
"""silence_cuts.py — real acoustic silences (ffmpeg silencedetect) → padded cut spans.

Whisper segment gaps miss short pauses (whisper stretches words over them), so
for a jump-cut edit we measure the waveform directly. Each detected silence is
shrunk by --pad on both sides so the cut keeps a breath of air around speech
and never clips a consonant.

Usage:
  silence_cuts.py <audio_or_video> --out cuts.json
                  [--noise -35] [--min 0.45] [--pad 0.12]

Output: {"filler_cuts": [{"start","end","kind":"silence"}]}  (prune.py-compatible:
pass it as --filler-cuts, or merge it with detect_fillers.py output).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess

FFMPEG = "/opt/homebrew/bin/ffmpeg"


def detect(src: str, noise: float, min_dur: float) -> list[tuple[float, float]]:
    proc = subprocess.run(
        [
            FFMPEG,
            "-nostdin",
            "-i",
            src,
            "-vn",
            "-af",
            f"silencedetect=noise={noise}dB:d={min_dur}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    spans, start = [], None
    for line in proc.stderr.splitlines():
        if m := re.search(r"silence_start: (-?[\d.]+)", line):
            start = max(0.0, float(m.group(1)))
        elif (m := re.search(r"silence_end: ([\d.]+)", line)) and start is not None:
            spans.append((start, float(m.group(1))))
            start = None
    if start is not None:  # silence runs to end of file
        spans.append((start, float("inf")))
    return spans


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--noise", type=float, default=-35.0, help="dB threshold")
    ap.add_argument("--min", type=float, default=0.45, help="min silence seconds")
    ap.add_argument("--pad", type=float, default=0.12, help="air kept each side")
    a = ap.parse_args()

    cuts = []
    for s, e in detect(a.src, a.noise, a.min):
        cs = s if s == 0.0 else s + a.pad  # file head: cut from 0
        ce = e if e == float("inf") else e - a.pad  # file tail: cut to end
        if ce == float("inf"):
            ce = 1e9
        if ce - cs > 0.05:
            cuts.append({"start": round(cs, 3), "end": round(ce, 3), "kind": "silence"})
    json.dump({"filler_cuts": cuts}, open(a.out, "w"), indent=1)
    total = sum(min(c["end"], 1e8) - c["start"] for c in cuts if c["end"] < 1e8)
    print(
        f"{len(cuts)} silence cuts, {total:.1f}s (pad {a.pad}s, >= {a.min}s @ {a.noise}dB)"
    )


if __name__ == "__main__":
    main()
