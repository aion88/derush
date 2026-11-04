#!/usr/bin/env python3
"""keep.json -> <STEM>.fcpxml : le montage du dérush en timeline éditable (DaVinci Resolve, FCP).

Chaque plage gardée devient un clip qui pointe sur la SOURCE entière, pas sur le montage :
dans Resolve, tirer le bord d'un clip (trim) fait réapparaître ce qui a été coupé. C'est ce
qui rend le dérush rattrapable à la main quand une coupe est fausse.

Usage : fcpxml.py <source> <keep.json> <sortie.fcpxml> <nom>
Import Resolve : File > Import > Timeline > (choisir le .fcpxml), décocher rien.
"""

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import quoteattr


def probe(src):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", src],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    cw, ch_ = int(v["width"]), int(v["height"])
    w, h = cw, ch_
    rot = 0
    for sd in v.get("side_data_list", []):
        rot = int(sd.get("rotation", rot) or rot)
    rot = int(v.get("tags", {}).get("rotate", rot) or rot)
    if abs(rot) % 180 == 90:
        w, h = h, w
    fps = Fraction(v["r_frame_rate"])
    return w, h, cw, ch_, fps, float(d["format"]["duration"]), a


SEQ_RATE = {32000: "32k", 44100: "44.1k", 48000: "48k", 88200: "88.2k", 96000: "96k"}


def t(frames, fps):
    """n images -> temps rationnel FCPXML, exact (pas de dérive en 29.97)."""
    r = Fraction(frames) / fps
    return (
        f"{r.numerator}/{r.denominator}s" if r.denominator != 1 else f"{r.numerator}s"
    )


def main():
    src, keep_path, out, name = sys.argv[1:5]
    w, h, cw, chh, fps, dur, a = probe(src)
    keep = json.load(open(keep_path))
    fd = Fraction(1) / fps
    clips, off = [], 0
    for k in keep:
        s, e = round(k["start"] * fps), round(k["end"] * fps)
        if e <= s:
            continue
        clips.append((off, s, e - s))
        off += e - s
    ch = int(a["channels"]) if a else 0
    rate = int(a["sample_rate"]) if a else 48000
    url = "file://" + quote(str(Path(src).resolve()))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.9">',
        "  <resources>",
        # r1 = la séquence (dimensions affichées, iPhone vertical = 1080x1920) ;
        # r3 = l'asset tel qu'il est codé (1920x1080 + rotation), Resolve applique la rotation.
        f'    <format id="r1" frameDuration="{fd.numerator}/{fd.denominator}s" width="{w}" height="{h}"/>',
        f'    <format id="r3" frameDuration="{fd.numerator}/{fd.denominator}s" width="{cw}" height="{chh}"/>',
        f'    <asset id="r2" name={quoteattr(Path(src).name)} start="0s" duration="{t(round(dur * fps), fps)}" '
        f'hasVideo="1" format="r3"'
        + (
            f' hasAudio="1" audioSources="1" audioChannels="{ch}" audioRate="{rate}"'
            if a
            else ""
        )
        + ">",
        f'      <media-rep kind="original-media" src={quoteattr(url)}/>',
        "    </asset>",
        "  </resources>",
        "  <library>",
        f"    <event name={quoteattr(name)}>",
        f"      <project name={quoteattr(name + ' derush')}>",
        f'        <sequence format="r1" duration="{t(off, fps)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="{SEQ_RATE.get(rate, "48k")}">',
        "          <spine>",
    ]
    for o, s, d in clips:
        lines.append(
            f'            <asset-clip ref="r2" name={quoteattr(name)} offset="{t(o, fps)}" '
            f'start="{t(s, fps)}" duration="{t(d, fps)}" tcFormat="NDF"/>'
        )
    lines += [
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
        "",
    ]
    Path(out).write_text("\n".join(lines))
    print(
        f"{len(clips)} clips, {float(off / fps):.2f} s, {w}x{h} @ {float(fps):.3f} -> {out}"
    )


if __name__ == "__main__":
    main()
