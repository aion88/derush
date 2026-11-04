#!/usr/bin/env python3
"""prune.py — turn detector output + whisper segments into KEEP ranges.

Deterministic runtime combiner for step (2) of the ingest pipeline. It does NOT do
any semantic reasoning — that already happened (the LLM emitted retraction_cuts
following the rubric in SKILL.md). prune.py mechanically unions:

  1. SILENCE cuts  — gaps between consecutive whisper segments >= min-silence-gap
                     (whisper emits ONLY speech, so inter-segment gaps ARE
                     silence). Plus the leading gap before the first segment and
                     the trailing gap after the last (to --duration if given).
                     Optionally unioned with video_analyze silence_intervals.
  2. RETRACTION cuts — the `retraction_cuts` array from the detector.
  3. FILLER cuts     — the `filler_cuts` array from detect_fillers.py (hesitation
                       sounds "euh"/"um"/… + function-word stutters; optional
                       lexical fillers). Deterministic, like silence; unioned here.

then computes KEEP = complement of the merged cut set over
[0, duration_or_last_segment_end], dropping KEEP ranges shorter than --min-keep.

The output KEEP-ranges JSON feeds directly into scripts/cut.sh:
  [{"start": <float>, "end": <float>}, ...]

NOTE: prune.py is the RUNTIME edit path; it is NOT in the scoring loop.
score.py compares detector cuts to gold directly. Keep them separate.

Inputs:
  --segments              whisper JSON {language, segments:[{start,end,text}]}
  --retraction-cuts       detector JSON: either the bare `retraction_cuts`
                          array [{start,end,...}], an object
                          {"retraction_cuts":[...]}, a path to such a file,
                          or "[]" / omitted for no retractions.
  --video-analyze-silence (optional) video_analyze JSON with
                          silence_intervals:[{start:"HH:MM:SS",end:"HH:MM:SS"}]
  --duration              (optional) total video duration in seconds; enables
                          the trailing-silence cut after the last segment.
  --min-silence-gap       default 2.0s
  --min-keep              default 0.8s
  --out                   KEEP-ranges JSON output path

Usage:
  prune.py --segments rec.segments.json \\
           --retraction-cuts cuts.json \\
           --duration 132.4 --out keep.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MERGE_GAP = 0.1  # merge cuts that are within this many seconds of each other


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _hhmmss_to_sec(value) -> float:
    """Convert 'HH:MM:SS(.fff)' (or a bare number) to seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    parts = [float(p) for p in parts]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def _load_cut_list(arg: str | None, key: str) -> list[dict]:
    """Accept a file path, an inline JSON string, an object with `key`, or None.

    Shared by --retraction-cuts and --filler-cuts: both resolve to a list of
    {start,end,...} spans (a bare array, or wrapped under their named key).
    """
    if not arg:
        return []
    text = arg
    candidate = Path(arg)
    if candidate.exists():
        text = candidate.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get(key, [])
    if not isinstance(data, list):
        raise ValueError(f"{key} must resolve to a list")
    return data


def _load_retraction_cuts(arg: str | None) -> list[dict]:
    return _load_cut_list(arg, "retraction_cuts")


def _load_filler_cuts(arg: str | None) -> list[dict]:
    return _load_cut_list(arg, "filler_cuts")


# ---------------------------------------------------------------------------
# Interval algebra
# ---------------------------------------------------------------------------


def _merge(spans: list[list[float]], gap: float) -> list[list[float]]:
    """Merge overlapping or near-adjacent (within `gap`) spans. Sorted, disjoint."""
    if not spans:
        return []
    ordered = sorted([list(s) for s in spans])
    out = [ordered[0][:]]
    for start, end in ordered[1:]:
        if start <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out


def _complement(
    cuts: list[list[float]], lo: float, hi: float, min_keep: float
) -> list[dict]:
    """KEEP = [lo,hi] minus merged cuts, dropping ranges shorter than min_keep."""
    keep: list[dict] = []
    cursor = lo
    for cs, ce in cuts:
        cs = max(cs, lo)
        ce = min(ce, hi)
        if cs > cursor:
            if cs - cursor >= min_keep:
                keep.append({"start": round(cursor, 3), "end": round(cs, 3)})
            cursor = max(cursor, ce)
        else:
            cursor = max(cursor, ce)
    if hi - cursor >= min_keep:
        keep.append({"start": round(cursor, 3), "end": round(hi, 3)})
    return keep


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute KEEP ranges for cut.sh.")
    parser.add_argument("--segments", required=True, help="Whisper segments JSON.")
    parser.add_argument(
        "--retraction-cuts",
        default=None,
        help="Detector cuts: file path, inline JSON array/object, or omitted.",
    )
    parser.add_argument(
        "--filler-cuts",
        default=None,
        help="detect_fillers.py output: file path, inline JSON array/object, or omitted.",
    )
    parser.add_argument(
        "--video-analyze-silence",
        default=None,
        help="Optional video_analyze JSON with silence_intervals.",
    )
    parser.add_argument("--duration", type=float, default=None, help="Video seconds.")
    parser.add_argument("--min-silence-gap", type=float, default=2.0)
    parser.add_argument("--min-keep", type=float, default=0.8)
    parser.add_argument("--out", required=True, help="KEEP-ranges JSON output.")
    args = parser.parse_args()

    seg_data = json.loads(Path(args.segments).read_text(encoding="utf-8"))
    segments = seg_data.get("segments", [])
    if not segments:
        print("ERROR: no segments in --segments file", file=sys.stderr)
        sys.exit(1)

    seg_spans = [(float(s["start"]), float(s["end"])) for s in segments]
    seg_spans.sort()
    first_start = seg_spans[0][0]
    last_end = seg_spans[-1][1]

    hi = args.duration if args.duration is not None else last_end
    lo = 0.0

    # --- 1. silence cuts from whisper gaps --------------------------------
    silence_cuts: list[list[float]] = []
    # leading gap
    if first_start - lo >= args.min_silence_gap:
        silence_cuts.append([lo, first_start])
    # inter-segment gaps
    for (a_start, a_end), (b_start, b_end) in zip(seg_spans, seg_spans[1:]):
        if b_start - a_end >= args.min_silence_gap:
            silence_cuts.append([a_end, b_start])
    # trailing gap (only meaningful if duration given and beyond last segment)
    if args.duration is not None and hi - last_end >= args.min_silence_gap:
        silence_cuts.append([last_end, hi])

    n_whisper_silence = len(silence_cuts)

    # --- optional: union with video_analyze silence -----------------------
    n_va_silence = 0
    if args.video_analyze_silence:
        va = json.loads(Path(args.video_analyze_silence).read_text(encoding="utf-8"))
        for iv in va.get("silence_intervals", []):
            s = _hhmmss_to_sec(iv["start"])
            e = _hhmmss_to_sec(iv["end"])
            if e > s:
                silence_cuts.append([s, e])
                n_va_silence += 1

    # --- 2. retraction cuts ------------------------------------------------
    retraction = _load_retraction_cuts(args.retraction_cuts)
    retraction_cuts = [
        [float(c["start"]), float(c["end"])]
        for c in retraction
        if float(c["end"]) > float(c["start"])
    ]
    n_retraction = len(retraction_cuts)

    # --- 3. filler cuts ----------------------------------------------------
    filler = _load_filler_cuts(args.filler_cuts)
    filler_cuts = [
        [float(c["start"]), float(c["end"])]
        for c in filler
        if float(c["end"]) > float(c["start"])
    ]
    n_filler = len(filler_cuts)

    # --- union + merge -----------------------------------------------------
    all_cuts = silence_cuts + retraction_cuts + filler_cuts
    merged = _merge(all_cuts, MERGE_GAP)
    # clamp to [lo,hi]
    merged = [[max(lo, c[0]), min(hi, c[1])] for c in merged if c[1] > lo and c[0] < hi]

    total_cut = round(sum(c[1] - c[0] for c in merged), 3)

    keep = _complement(merged, lo, hi, args.min_keep)
    total_keep = round(sum(k["end"] - k["start"] for k in keep), 3)

    Path(args.out).write_text(
        json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"silence cuts: {n_whisper_silence} whisper-gap"
        + (f" + {n_va_silence} video_analyze" if args.video_analyze_silence else "")
        + f" | retraction cuts: {n_retraction}"
        + f" | filler cuts: {n_filler}",
        file=sys.stderr,
    )
    print(
        f"merged cut spans: {len(merged)} | total cut: {total_cut}s | "
        f"total keep: {total_keep}s | keep ranges: {len(keep)} -> {args.out}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
