#!/usr/bin/env python3
"""transcribe_qwen.py — Qwen3-ASR-1.7B text, in whisper's JSON shape, for align_words.py.

Why: measured 2026-11-04 on A001_10281937_C010, whisper (even unprompted) erases
stutters and false starts ("des des des trucs" -> "des trucs", "j'aurais pas mes,
j'aurais pas mes, tous mes" -> "je n'aurais pas tous mes"), the exact material
derush cuts. Qwen writes them. ~20x faster on MPS (14 s for 4:32) than whisper CPU.
Neither engine writes "euh": gap_fillers.py still does that job.

Only the TEXT matters: align_words.py re-times every word by CTC. So words carry
placeholder times here, and segments (one per sentence) get their real span back
in align_words.py ("engine": "qwen3-asr").

Runs in its own venv (outils/DEPENDANCES.md), never the system python3.
Usage: transcribe_qwen.py audio16k.wav --lang fr --out audio.json
"""

import argparse
import json
import os
import re

os.environ.setdefault(
    "HF_HUB_DISABLE_IMPLICIT_TOKEN", "1"
)  # public model: an expired HF token must not break it

LANGS = {"fr": "French", "en": "English"}
MODEL = os.environ.get("DERUSH_QWEN_MODEL", "Qwen/Qwen3-ASR-1.7B")


def to_whisper_shape(text: str, lang: str, dur: float) -> dict:
    sentences = [s for s in re.split(r"(?<=[.?!…])\s+", text.strip()) if s.strip()]
    segments = []
    for i, s in enumerate(sentences):
        words = [{"word": " " + w, "start": 0.0, "end": 0.0} for w in s.split()]
        if words:
            segments.append(
                {"id": i, "start": 0.0, "end": dur, "text": " " + s, "words": words}
            )
    return {
        "engine": "qwen3-asr",
        "model": MODEL,
        "language": lang,
        "text": text,
        "segments": segments,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--lang", default="fr")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel

    dur = sf.info(a.audio).duration
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    m = Qwen3ASRModel.from_pretrained(
        MODEL, dtype=torch.bfloat16, device_map=device, max_new_tokens=8192
    )
    text = m.transcribe(audio=a.audio, language=LANGS.get(a.lang, "French"))[0].text
    if not text.strip():
        raise SystemExit("qwen: transcript vide")
    data = to_whisper_shape(text, a.lang, dur)
    json.dump(data, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(
        f"qwen {device}: {sum(len(s['words']) for s in data['segments'])} mots, {len(data['segments'])} phrases"
    )


if __name__ == "__main__":
    main()
