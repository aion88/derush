#!/usr/bin/env python3
"""gap_check.py — re-transcribe the gaps that silencedetect does NOT cover.

Why: gap_fillers.py cuts every non-silent hole >= 0.3 s between two aligned words
as a hidden "euh". A hole that is mostly real silence is safe. A hole that is NOT
silent and not a short hesitation may be speech whisper dropped (a false start, a
mumbled clause). Cutting it would eat content, the worst fault. So: for each gap
longer than --min-gap whose silence coverage is below --cover, re-transcribe the
window [word before .. word after] alone and print what is heard. If the window
transcript contains words beyond the two edge words, the gap carries speech.

Usage: gap_check.py <work_dir> [--lang fr] [--min-gap 1.0] [--cover 0.7]
Writes <work_dir>/gap_check.txt and prints it. Exit 0 always (it informs, the
agent decides: remove the gap from gap_cuts.json, or keep the cut).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROMPT = {
    "fr": "Euh, alors, hum, je... je voulais, euh, mmh, en fait, bah, voilà.",
    "en": "Um, so, uh, I... I mean, hmm, like, you know, well.",
}


def norm(s: str) -> list[str]:
    return re.findall(r"[a-zà-ÿ0-9']+", s.lower())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--lang", default="fr")
    ap.add_argument("--min-gap", type=float, default=1.0)
    ap.add_argument("--cover", type=float, default=0.7)
    a = ap.parse_args()
    w = Path(a.work)
    words = [
        x
        for s in json.load(open(w / "aligned.json"))["segments"]
        for x in s.get("words", [])
    ]
    gaps = json.load(open(w / "gap_cuts.json"))["filler_cuts"]
    sil = json.load(open(w / "silence_cuts.json"))["filler_cuts"]

    def covered(c):
        return sum(
            max(0.0, min(c["end"], x["end"]) - max(c["start"], x["start"])) for x in sil
        )

    suspects = []
    for c in gaps:
        d = c["end"] - c["start"]
        if d < a.min_gap:
            continue
        if covered(c) >= a.cover * d:
            continue
        before = max((x for x in words if x["end"] <= c["start"] + 0.05), key=lambda x: x["end"], default=None)
        after = min((x for x in words if x["start"] >= c["end"] - 0.05), key=lambda x: x["start"], default=None)
        suspects.append((c, d, covered(c), before, after))

    out = []
    if not suspects:
        out.append("gap_check : aucun trou non silencieux >= %.1f s. Rien à vérifier." % a.min_gap)
    else:
        import whisper

        model = whisper.load_model("large-v3-turbo", device="cpu")
        audio = str(w / "audio.wav")
        import soundfile as sf

        data, sr = sf.read(audio, dtype="float32")
        for c, d, cov, b, af in suspects:
            s0 = b["start"] if b else max(0.0, c["start"] - 0.5)
            s1 = af["end"] if af else c["end"] + 0.5
            clip = data[int(s0 * sr) : int(s1 * sr)]
            r = model.transcribe(
                clip, language=a.lang, initial_prompt=PROMPT.get(a.lang, PROMPT["fr"]),
                condition_on_previous_text=False, fp16=False,
            )
            heard = r["text"].strip()
            edge = set(norm(b["word"] if b else "")) | set(norm(af["word"] if af else ""))
            extra = [t for t in norm(heard) if t not in edge]
            hes = all(re.fullmatch(r"(euh+|hum+|hm+|mm+h?|bah|ben|um+|uh+|hmm+)", t) for t in extra) if extra else True
            rate = len(norm(heard)) / max(0.3, s1 - s0)  # mots/s sur la fenêtre
            fresh = len(set(extra))
            if not extra:
                verdict = "silence/souffle"
            elif hes:
                verdict = "hésitation, coupe OK"
            elif rate > 4.5:
                verdict = "hallucination whisper sur du souffle (débit impossible), coupe OK"
            elif fresh < 2:
                verdict = "un mot variant du bord, coupe OK"
            else:
                verdict = "PAROLE DANS LE TROU, ne pas couper tel quel"
            out.append(
                f"{c['start']:7.2f}-{c['end']:7.2f} {d:4.1f}s silence {cov:4.1f}s | "
                f"« {(b or {}).get('word','').strip()} | ... | {(af or {}).get('word','').strip()} » entendu : « {heard} » → {verdict}"
            )
    txt = "\n".join(out)
    (w / "gap_check.txt").write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
