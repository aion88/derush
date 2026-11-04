#!/usr/bin/env python3
"""verify_diff.py — word-level diff between the source transcript and a re-transcript
of the derushed output. Every `delete` must be an intended cut (filler, retraction);
an unexpected deleted content word = a clipped edge or a too-wide retraction.

Whisper re-transcription is noisy: `replace`/`insert` lines are mostly ASR variance
(t'as/tu as, "c'est c'est c'est" repetition loops). Before blaming the cut, re-run
whisper on that short region alone (no initial_prompt) and compare.

Usage: verify_diff.py source.json output.json
"""

from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher

FILLERS = {"euh", "heu", "hum", "mmh", "hmm", "mh", "um", "uh"}


def toks(path: str) -> list[str]:
    d = json.load(open(path))
    return [
        re.sub(r"[^\w']", "", w["word"].lower())
        for s in d["segments"]
        for w in s.get("words", [])
    ]


def main() -> None:
    a, b = toks(sys.argv[1]), toks(sys.argv[2])
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            print(f"{op:8} {' '.join(a[i1:i2])!r} => {' '.join(b[j1:j2])!r}")
    print(
        f"words {len(a)} -> {len(b)} | fillers left in output: {sum(t in FILLERS for t in b)}"
    )


if __name__ == "__main__":
    main()
