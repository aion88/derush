#!/usr/bin/env /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
"""align_words.py — re-time whisper words by CTC forced alignment (torchaudio MMS_FA).

Why: whisper's word timestamps (DTW on attention) drift 0.1-0.4 s. Measured on
IMG_4542 (2026-10-07): word ENDS land early, so a "gap" after "TikTok" or
"Instagram" was really the end of the word, and cutting it clipped the word.
Any cut that trusts whisper edges eats words. CTC alignment pins each word on
the acoustics instead.

The text is whisper's; only the timing changes. Words with no alignable letter
(numbers, "%") keep a position interpolated between their aligned neighbours.

Usage: align_words.py audio16k.wav whisper.json --out aligned.json
Output: same JSON, segments[].words[] start/end replaced, plus "aligned": true|false.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata

import soundfile as sf
import torch
import torchaudio

SR = 16000
CHUNK_S, CTX_S = 20.0, 1.0  # emission computed in chunks with context on each side


def norm(word: str) -> str:
    if re.search(r"\d", word):
        # "5h" would align as "h" alone, leaving "cinq" in a gap that gap_fillers
        # then cuts (IMG_4549: "à 5h" -> "à h"). Interpolate the whole token instead.
        return ""
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z']", "", w).strip("'")


def emissions(model, wav: torch.Tensor) -> tuple[torch.Tensor, float]:
    n, step, ctx = wav.shape[1], int(CHUNK_S * SR), int(CTX_S * SR)
    outs, ratio = [], None
    with torch.inference_mode():
        for s in range(0, n, step):
            lo, hi = max(0, s - ctx), min(n, s + step + ctx)
            em, _ = model(wav[:, lo:hi])
            r = em.shape[1] / (hi - lo)
            ratio = ratio or r
            a, b = int(round((s - lo) * r)), int(round((min(n, s + step) - lo) * r))
            outs.append(em[:, a:b])
    return torch.cat(outs, dim=1), ratio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("words")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    bundle = torchaudio.pipelines.MMS_FA
    model, tok = bundle.get_model(), bundle.get_tokenizer()
    # soundfile, not torchaudio.load : torchaudio >= 2.9 delegates loading to torchcodec (not installed)
    data_, sr = sf.read(a.audio, dtype="float32", always_2d=True)
    wav = torch.from_numpy(data_.T.copy())
    assert sr == SR, "pass 16 kHz mono audio"
    em, ratio = emissions(model, wav)

    data = json.load(open(a.words))
    words = [w for s in data["segments"] for w in s.get("words", [])]
    idx = [i for i, w in enumerate(words) if norm(w["word"])]
    transcript = [norm(words[i]["word"]) for i in idx]

    tokens = tok(transcript)
    flat = torch.tensor([[t for wt in tokens for t in wt]], dtype=torch.int32)
    ali, scores = torchaudio.functional.forced_align(em, flat, blank=0)
    spans = torchaudio.functional.merge_tokens(ali[0], scores[0].exp())
    k = 0
    for i, wt in zip(idx, tokens):
        sp = spans[k : k + len(wt)]
        k += len(wt)
        words[i]["start"] = round(sp[0].start / ratio / SR, 3)
        words[i]["end"] = round(sp[-1].end / ratio / SR, 3)
        words[i]["score"] = round(
            sum(s.score * (s.end - s.start) for s in sp)
            / max(1, sum(s.end - s.start for s in sp)),
            3,
        )
        words[i]["aligned"] = True
    for i, w in enumerate(words):  # numbers etc.: squeeze between aligned neighbours
        if not w.get("aligned"):
            prev = next(
                (
                    words[j]["end"]
                    for j in range(i - 1, -1, -1)
                    if words[j].get("aligned")
                ),
                0.0,
            )
            nxt = next(
                (
                    words[j]["start"]
                    for j in range(i + 1, len(words))
                    if words[j].get("aligned")
                ),
                prev,
            )
            w["start"], w["end"], w["aligned"] = prev, max(prev, nxt), False
    if (
        data.get("engine") == "qwen3-asr"
    ):  # qwen gives no segment times: prune.py needs them
        for s in data["segments"]:
            if s.get("words"):
                s["start"], s["end"] = s["words"][0]["start"], s["words"][-1]["end"]
    json.dump(data, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"aligned {len(idx)}/{len(words)} words")


if __name__ == "__main__":
    main()
