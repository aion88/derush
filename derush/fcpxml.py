#!/usr/bin/env python3
"""keep.json -> <STEM>.fcpxml : le montage du dérush en timeline éditable (DaVinci Resolve, FCP).

Chaque plage gardée devient un clip qui pointe sur la SOURCE entière, pas sur le montage :
dans Resolve, tirer le bord d'un clip (trim) fait réapparaître ce qui a été coupé. C'est ce
qui rend le dérush rattrapable à la main quand une coupe est fausse.

Usage : fcpxml.py <source> <keep.json> <sortie.fcpxml> <nom>
        fcpxml.py --multi <clips.json> <sortie.fcpxml> <nom>   (projet : [{"source","start","end"}])
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
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        sys.exit("source audio : pas de timeline vidéo")
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
    return ts(r)


def ts(r):
    """Temps rationnel (secondes, Fraction) -> texte FCPXML."""
    return (
        f"{r.numerator}/{r.denominator}s" if r.denominator != 1 else f"{r.numerator}s"
    )


def build(clips, out, name):
    """clips = [(source, début s, fin s)] -> <out>.fcpxml ; renvoie la ligne de résumé.

    Chaque source distincte a son asset (r2, r4, …) et son format (r3, r5, …) ; la séquence (r1)
    prend le format de la première. Un clip est arrondi à la grille d'images de SA source. Pour un
    seul rush le texte est identique à celui d'avant le mode multi-sources (test_fcpxml.py).
    """
    infos, ordre = {}, []
    for src, _, _ in clips:
        if src not in infos:
            infos[src] = probe(src)
            ordre.append(src)
    w, h, _, _, fps, _, a0 = infos[ordre[0]]
    fd = Fraction(1) / fps
    rate0 = int(a0["sample_rate"]) if a0 else 48000
    res = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.9">',
        "  <resources>",
        # r1 = la séquence (dimensions affichées, iPhone vertical = 1080x1920) ;
        # r3 = l'asset tel qu'il est codé (1920x1080 + rotation), Resolve applique la rotation.
        f'    <format id="r1" frameDuration="{fd.numerator}/{fd.denominator}s" width="{w}" height="{h}"/>',
    ]
    ids = {}
    for n, src in enumerate(ordre):
        _, _, cw, chh, sfps, dur, a = infos[src]
        sfd = Fraction(1) / sfps
        aid, fid = f"r{2 + 2 * n}", f"r{3 + 2 * n}"
        ids[src] = (aid, sfps)
        ch = int(a["channels"]) if a else 0
        rate = int(a["sample_rate"]) if a else 48000
        url = "file://" + quote(str(Path(src).resolve()))
        res += [
            f'    <format id="{fid}" frameDuration="{sfd.numerator}/{sfd.denominator}s" width="{cw}" height="{chh}"/>',
            f'    <asset id="{aid}" name={quoteattr(Path(src).name)} start="0s" duration="{t(round(dur * sfps), sfps)}" '
            f'hasVideo="1" format="{fid}"'
            + (
                f' hasAudio="1" audioSources="1" audioChannels="{ch}" audioRate="{rate}"'
                if a
                else ""
            )
            + ">",
            f'      <media-rep kind="original-media" src={quoteattr(url)}/>',
            "    </asset>",
        ]
    # l'ordre r1, r3, r2 d'origine (format de la séquence, format de l'asset, asset) est gardé
    lignes_clips, off = [], Fraction(0)
    for src, s0, e0 in clips:
        aid, sfps = ids[src]
        s, e = round(s0 * sfps), round(e0 * sfps)
        if e <= s:
            continue
        d = Fraction(e - s) / sfps
        lignes_clips.append(
            f'            <asset-clip ref="{aid}" name={quoteattr(name)} offset="{ts(off)}" '
            f'start="{t(s, sfps)}" duration="{ts(d)}" tcFormat="NDF"/>'
        )
        off += d
    res += [
        "  </resources>",
        "  <library>",
        f"    <event name={quoteattr(name)}>",
        f"      <project name={quoteattr(name + ' derush')}>",
        f'        <sequence format="r1" duration="{ts(off)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="{SEQ_RATE.get(rate0, "48k")}">',
        "          <spine>",
    ]
    res += lignes_clips
    res += [
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
        "",
    ]
    Path(out).write_text("\n".join(res))
    return f"{len(lignes_clips)} clips, {float(off):.2f} s, {w}x{h} @ {float(fps):.3f} -> {out}"


def main():
    if sys.argv[1] == "--multi":
        clips_path, out, name = sys.argv[2:5]
        clips = [(c["source"], c["start"], c["end"]) for c in json.load(open(clips_path))]
    else:
        src, keep_path, out, name = sys.argv[1:5]
        clips = [(src, k["start"], k["end"]) for k in json.load(open(keep_path))]
    print(build(clips, out, name))


if __name__ == "__main__":
    main()
