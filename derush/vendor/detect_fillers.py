#!/usr/bin/env python3
"""detect_fillers.py — turn whisper word-timestamps into filler-word cut spans.

The deterministic, language-aware sibling of the semantic retraction detector. Where
retraction detection is an LLM judgment (a thought taken back), filler removal is a
mechanical lexicon + adjacency rule over the word stream that transcribe_local.py already
emits (`segments[].words[] = [{word,start,end}]`). It finds:

  1. HESITATION sounds — "euh", "heu", "hum", "um", "uh", "erm"… (CORE lexicon, default on).
     These are non-lexical: they are almost never a real word, so cutting them is safe.
  2. STUTTER repeats — the same short FUNCTION word said twice in a row with a tiny gap
     ("je je", "the the", "et et"). Cut all but the last. Restricted to function words +
     hesitations so intentional emphasis on a content word ("très très bien") is NOT cut.
  3. (opt-in, --extended) LEXICAL fillers — "du coup", "genre", "tu vois", "you know",
     "like"… These ARE real words in other contexts, so they false-positive; off by default.

Output is the same span shape prune.py already unions (like retraction_cuts):
  [{"start": <float>, "end": <float>, "word": "euh", "kind": "filler|stutter"}, ...]

prune.py reads it via --filler-cuts and unions it with silence + retraction before computing
KEEP. The cuts are reviewed downstream (overseer / Cynthia) like every other edit.

Usage:
  detect_fillers.py --segments rec.segments.json --out fillers.json [--extended]
                    [--extra "tu sais,bon"] [--max-stutter-gap 0.6] [--lang fr]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Non-lexical hesitation sounds — safe to cut anywhere. FR + EN + shared.
CORE_FILLERS: set[str] = {
    # FR
    "euh",
    "euhh",
    "euheu",
    "heu",
    "heuu",
    "hein",
    # EN
    "um",
    "umm",
    "uh",
    "uhh",
    "uhm",
    "erm",
    "er",
    # shared / cross-lingual hesitation hums
    "hum",
    "humm",
    "hmm",
    "hmmm",
    "mmh",
    "mmm",
    "mh",
}

# Lexical fillers — real words in other contexts. OPT-IN only (--extended).
EXTENDED_UNIGRAMS: set[str] = {
    # FR
    "ben",
    "bah",
    "genre",
    "quoi",
    "voilà",
    "voila",
    "enfin",
    # EN
    "like",
    "basically",
    "literally",
    "anyway",
}
EXTENDED_BIGRAMS: set[str] = {
    # FR
    "du coup",
    "tu vois",
    "tu sais",
    "en fait",
    "je veux dire",
    # EN
    "you know",
    "i mean",
    "kind of",
    "sort of",
}

# Short function words: a consecutive repeat of one of these is a stutter, not emphasis.
FUNCTION_WORDS: set[str] = {
    # FR
    "je",
    "j",
    "tu",
    "il",
    "elle",
    "on",
    "nous",
    "vous",
    "ils",
    "elles",
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "de",
    "du",
    "et",
    "est",
    "que",
    "qui",
    "à",
    "a",
    "ce",
    "se",
    "ne",
    "ça",
    "mais",
    "ou",
    "où",
    # EN
    "the",
    "i",
    "it",
    "to",
    "and",
    "that",
    "of",
    "you",
    "we",
    "is",
    "a",
    "in",
    "so",
}

_STRIP = " \t\n\r.,!?;:…\"'«»()[]—–-"


def normalize(word: str) -> str:
    """Lowercase + strip surrounding punctuation/whitespace. Keep inner apostrophes."""
    return word.strip(_STRIP).lower()


def word_stream(segments: list[dict]) -> list[dict]:
    """Flatten segments[].words[] into one time-ordered stream with normalized forms."""
    stream: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []) or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            raw = w.get("word") or w.get("text") or ""
            stream.append(
                {
                    "raw": raw.strip(),
                    "norm": normalize(raw),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                }
            )
    stream.sort(key=lambda x: (x["start"], x["end"]))
    return stream


def detect(
    segments: list[dict],
    extended: bool = False,
    extra: set[str] | None = None,
    max_stutter_gap: float = 0.6,
) -> list[dict]:
    """Return filler/stutter cut spans for the given segments. Pure + testable."""
    stream = word_stream(segments)
    extra = extra or set()
    unigrams = set(CORE_FILLERS)
    bigrams: set[str] = set()
    if extended:
        unigrams |= EXTENDED_UNIGRAMS
        bigrams |= EXTENDED_BIGRAMS
    unigrams |= {e for e in extra if " " not in e}
    bigrams |= {e for e in extra if " " in e}

    cuts: list[dict] = []
    cut_idx: set[int] = set()

    # --- 1+3. unigram + bigram filler matches ------------------------------
    i = 0
    n = len(stream)
    while i < n:
        norm = stream[i]["norm"]
        # bigram first (longer match wins)
        if i + 1 < n and bigrams:
            bg = f"{norm} {stream[i + 1]['norm']}"
            if bg in bigrams:
                cuts.append(
                    {
                        "start": round(stream[i]["start"], 3),
                        "end": round(stream[i + 1]["end"], 3),
                        "word": bg,
                        "kind": "filler",
                    }
                )
                cut_idx.update({i, i + 1})
                i += 2
                continue
        if norm and norm in unigrams:
            cuts.append(
                {
                    "start": round(stream[i]["start"], 3),
                    "end": round(stream[i]["end"], 3),
                    "word": norm,
                    "kind": "filler",
                }
            )
            cut_idx.add(i)
        i += 1

    # --- 2. stutter repeats (cut all but the last in a run) ----------------
    j = 0
    while j < n:
        norm = stream[j]["norm"]
        stutterable = norm and (norm in FUNCTION_WORDS or norm in CORE_FILLERS)
        if not stutterable:
            j += 1
            continue
        # extend the run of identical adjacent norms within the gap
        run = [j]
        k = j + 1
        while (
            k < n
            and stream[k]["norm"] == norm
            and stream[k]["start"] - stream[k - 1]["end"] <= max_stutter_gap
        ):
            run.append(k)
            k += 1
        if len(run) >= 2:
            for idx in run[:-1]:  # keep the LAST utterance
                if idx in cut_idx:
                    continue
                cuts.append(
                    {
                        "start": round(stream[idx]["start"], 3),
                        "end": round(stream[idx]["end"], 3),
                        "word": norm,
                        "kind": "stutter",
                    }
                )
                cut_idx.add(idx)
        j = k

    cuts.sort(key=lambda c: c["start"])
    return cuts


def main() -> None:
    ap = argparse.ArgumentParser(description="Detect filler-word + stutter cut spans.")
    ap.add_argument(
        "--segments", required=True, help="Whisper segments JSON (with words[])."
    )
    ap.add_argument("--out", default=None, help="Output JSON path (default: stdout).")
    ap.add_argument(
        "--extended",
        action="store_true",
        help="Also cut lexical fillers (du coup/genre/you know/like…). May false-positive.",
    )
    ap.add_argument(
        "--extra", default=None, help="Comma-separated extra fillers (uni or bigram)."
    )
    ap.add_argument("--max-stutter-gap", type=float, default=0.6)
    ap.add_argument("--lang", default=None, help="Hint only; lexicon is bilingual.")
    args = ap.parse_args()

    seg_data = json.loads(Path(args.segments).read_text(encoding="utf-8"))
    segments = seg_data.get("segments", [])
    if not any(s.get("words") for s in segments):
        print(
            "ERROR: no word-level timestamps in --segments. Re-run transcribe_local.py "
            "(it passes --word_timestamps True).",
            file=sys.stderr,
        )
        sys.exit(1)

    extra = {
        normalize(x) if " " not in x else x.strip().lower()
        for x in (args.extra.split(",") if args.extra else [])
        if x.strip()
    }
    cuts = detect(
        segments,
        extended=args.extended,
        extra=extra,
        max_stutter_gap=args.max_stutter_gap,
    )

    payload = json.dumps(cuts, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload)

    n_fill = sum(1 for c in cuts if c["kind"] == "filler")
    n_stut = sum(1 for c in cuts if c["kind"] == "stutter")
    total = round(sum(c["end"] - c["start"] for c in cuts), 3)
    print(
        f"fillers: {n_fill} | stutters: {n_stut} | total cut: {total}s"
        + (f" -> {args.out}" if args.out else ""),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
