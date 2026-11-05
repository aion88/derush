#!/usr/bin/env python3
"""Collage : des mots d'une prise collés dans une autre, montés à partir du texte.

`inserts.json` (dans le dossier de la prise A) = {"inserts": [{"apres", "rush", "debut", "fin", "mots", "barres"}]} :
  apres  : instant SOURCE de A après lequel la passe est insérée (fin du mot cliqué)
  rush   : le STEM de la prise B d'où viennent les mots ; debut/fin : ses bornes dans la source de B
  mots   : [{"w","s","e"}] les mots collés (pour les réafficher), barres : [{"start","end"}] ceux que Cynthia a barrés
Le rendu de A garde ses plages (keep.json), les coupe à chaque point d'insertion et y met les plages de B
(son keep.json borné à [debut, fin], moins les mots barrés ; sans keep.json, l'étendue des mots).
Coupes franches, sortie à la résolution, au fps et à la fréquence d'échantillonnage de A. Un seul passage
ffmpeg (trim/atrim + concat), comme cut.sh : aucun raccord ne peut dériver.

Usage (root = $DERUSH_OUT_ROOT) :
  collage.py count  <dossier de la prise>        nombre d'insertions (0 si absent ou vide)
  collage.py plan   <root> <STEM>                plan de rendu en JSON : [{rush, src, start, end}]
  collage.py render <root> <STEM> <sortie>       monte A + les collages (mp4 ou m4a)
  collage.py fcpxml <root> <STEM> <sortie> <nom> timeline éditable qui cite les deux sources
  collage.py cuts   <root> <STEM>                section « Insertions » de cuts.md
Les erreurs sortent en français sur stderr, code 1, sans traceback.
"""

import json
import math
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MARGE = 0.04  # aux bords d'une passe collée, sans mordre sur le mot voisin
MIN_FRAG = 0.03
FADE = 0.012  # même fondu que cut.sh : un raccord sans clic


class ErreurCollage(ValueError):
    """Message en français, montré tel quel par la CLI et le studio."""


# ---------------------------------------------------------------- fichiers


def _stem_ok(stem):
    return (
        isinstance(stem, str)
        and stem
        and not stem.startswith(("_", "."))
        and "/" not in stem
        and "\\" not in stem
    )


def rush(root, stem):
    """{"stem","kind","source","dir"} ; ErreurCollage si la prise n'existe pas."""
    if not _stem_ok(stem):
        raise ErreurCollage(f"rush inconnu : {stem}")
    d = os.path.join(root, stem)
    st = os.path.join(d, "_work", "source.txt")
    if not os.path.isfile(st):
        raise ErreurCollage(f"rush inconnu : {stem}")
    source = open(st).read().strip()
    if not os.path.isfile(source):
        raise ErreurCollage(f"rush introuvable : {stem}")
    kp = os.path.join(d, "_work", "kind")
    kind = (open(kp).read().strip() or "video") if os.path.isfile(kp) else "video"
    return {"stem": stem, "kind": kind, "source": source, "dir": d}


def mots(root, stem):
    a = os.path.join(root, stem, "_work", "aligned.json")
    if not os.path.isfile(a):
        raise ErreurCollage(f"rush introuvable : {stem}")
    return [
        {"w": str(w["word"]).strip(), "s": float(w["start"]), "e": float(w["end"])}
        for seg in json.load(open(a)).get("segments", [])
        for w in seg.get("words", [])
    ]


def _nombre(x, nom):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ErreurCollage(f"collage : {nom} invalide")
    return float(x)


def normaliser(root, liste):
    """Valide la liste d'insertions reçue du navigateur ; rend la forme écrite dans inserts.json."""
    if not isinstance(liste, list):
        raise ErreurCollage("collage : liste attendue")
    out = []
    for it in liste:
        if not isinstance(it, dict):
            raise ErreurCollage("collage : insertion invalide")
        apres = _nombre(it.get("apres"), "apres")
        debut, fin = _nombre(it.get("debut"), "debut"), _nombre(it.get("fin"), "fin")
        if apres < 0 or debut < 0 or fin <= debut:
            raise ErreurCollage("collage : bornes invalides")
        r = it.get("rush")
        rush(root, r)  # inconnu ou introuvable : refus
        m = [
            {
                "w": str(x.get("w", "")),
                "s": _nombre(x.get("s"), "s"),
                "e": _nombre(x.get("e"), "e"),
            }
            for x in it.get("mots", [])
        ]
        b = []
        for x in it.get("barres", []):
            s, e = _nombre(x.get("start"), "start"), _nombre(x.get("end"), "end")
            if e > s:
                b.append({"start": s, "end": e})
        out.append(
            {
                "apres": apres,
                "rush": r,
                "debut": debut,
                "fin": fin,
                "mots": m,
                "barres": b,
            }
        )
    return out


def inserts(out_dir):
    """Les insertions de la prise (dossier de sortie de A), [] si le fichier manque ou est vide."""
    p = os.path.join(out_dir, "inserts.json")
    if not os.path.isfile(p) or not os.path.getsize(p):
        return []
    d = json.load(open(p))
    return d.get("inserts", []) if isinstance(d, dict) else []


# ---------------------------------------------------------------- plan


def _soustraire(plages, trous):
    for ts, te in trous:
        n = []
        for s, e in plages:
            if te <= s or ts >= e:
                n.append((s, e))
                continue
            if ts > s:
                n.append((s, ts))
            if te < e:
                n.append((te, e))
        plages = n
    return [(s, e) for s, e in plages if e - s >= MIN_FRAG]


def plages_b(root, ins):
    """Les plages de B (en temps source de B) qui entrent à la place d'une insertion."""
    r = rush(root, ins["rush"])
    debut, fin = ins["debut"], ins["fin"]
    ws = mots(root, ins["rush"])
    prec = max((w["e"] for w in ws if w["e"] <= debut + 1e-6), default=None)
    suiv = min((w["s"] for w in ws if w["s"] >= fin - 1e-6), default=None)
    pd = MARGE if prec is None else min(MARGE, max(0.0, debut - prec) / 2)
    pf = MARGE if suiv is None else min(MARGE, max(0.0, suiv - fin) / 2)
    d0, f0 = max(0.0, debut - pd), fin + pf
    kp = os.path.join(r["dir"], "keep.json")
    if os.path.isfile(kp):
        plages = []
        for k in json.load(open(kp)):
            s, e = max(k["start"], d0), min(k["end"], f0)
            if e > s:
                plages.append((s, e))
    else:
        plages = [(d0, f0)]
    return _soustraire(plages, [(b["start"], b["end"]) for b in ins.get("barres", [])])


def plan(root, stem):
    """[{rush, src, start, end}] : A coupé à chaque insertion, B inséré. Sans insertion : le keep.json de A."""
    a = rush(root, stem)
    keep = json.load(open(os.path.join(a["dir"], "keep.json")))
    ins = sorted(
        enumerate(inserts(a["dir"])), key=lambda x: (float(x[1]["apres"]), x[0])
    )
    ins = [i for _, i in ins]
    res = []

    def a_(s, e):
        if e > s:
            res.append({"rush": stem, "src": a["source"], "start": s, "end": e})

    def bloc(i):
        src = rush(root, i["rush"])["source"]
        for s, e in plages_b(root, i):
            res.append({"rush": i["rush"], "src": src, "start": s, "end": e})

    j = 0
    for k in sorted(keep, key=lambda k: k["start"]):
        s, e = k["start"], k["end"]
        while j < len(ins) and ins[j]["apres"] <= s:
            bloc(ins[j])
            j += 1
        cur = s
        while j < len(ins) and ins[j]["apres"] < e:
            a_(cur, ins[j]["apres"])
            cur = max(cur, ins[j]["apres"])
            bloc(ins[j])
            j += 1
        a_(cur, e)
    while j < len(ins):
        bloc(ins[j])
        j += 1
    return res


# ---------------------------------------------------------------- rendu


def _audio(src):
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels",
            "-of",
            "json",
            src,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    s = json.loads(out).get("streams")
    if not s:
        raise ErreurCollage(f"pas de son dans {os.path.basename(src)}")
    return int(s[0]["sample_rate"]), int(s[0]["channels"])


def _video(src, stem):
    import fcpxml

    try:
        return fcpxml.probe(src)
    except SystemExit:
        raise ErreurCollage(
            f"la prise {stem} est un audio seul : pas de collage dans une vidéo"
        )


def graphe(root, stem, p, audio_only):
    """(graphe filter_complex, [sources], durée totale)."""
    a = rush(root, stem)
    srcs = [a["source"]] + [
        s for s in dict.fromkeys(x["src"] for x in p) if s != a["source"]
    ]
    rate, ch = _audio(a["source"])
    layout = {1: "mono", 2: "stereo"}.get(ch)
    vid = {}
    if not audio_only:
        vid[a["source"]] = _video(a["source"], stem)
        for x in p:
            if x["src"] not in vid:
                vid[x["src"]] = _video(x["src"], x["rush"])
    wa, ha, _, _, fa, _, _ = vid.get(a["source"], (0, 0, 0, 0, None, 0, None))
    parts, labels, total = [], [], 0.0
    for n, x in enumerate(p):
        i = srcs.index(x["src"])
        s, e = x["start"], x["end"]
        if not audio_only:
            fs = vid[x["src"]][4]
            s = float(round(Fraction(s).limit_denominator(10**6) * fs) / fs)
            e = float(round(Fraction(e).limit_denominator(10**6) * fs) / fs)
        if e <= s:
            continue
        d = e - s
        autre = i != 0
        af = (
            f",afade=t=in:st=0:d={FADE},afade=t=out:st={d - FADE:.6f}:d={FADE}"
            if d > 2 * FADE
            else ""
        )
        if autre:
            ar, ach = _audio(x["src"])
            norm = f",aresample={rate}" + (
                f",aformat=channel_layouts={layout}" if layout and ach != ch else ""
            )
        else:
            norm = ""
        parts.append(
            f"[{i}:a]atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS{norm}{af}[a{n}];"
        )
        if audio_only:
            labels.append(f"[a{n}]")
        else:
            vf = ""
            if autre:
                wb, hb, _, _, fb, _, _ = vid[x["src"]]
                vf = f",fps={fa.numerator}/{fa.denominator}" if fb != fa else ""
                vf += (
                    f",scale={wa}:{ha}:force_original_aspect_ratio=decrease,"
                    f"pad={wa}:{ha}:(ow-iw)/2:(oh-ih)/2"
                    if (wb, hb) != (wa, ha)
                    else ""
                )
                vf += ",setsar=1"
            parts.append(
                f"[{i}:v]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS{vf}[v{n}];"
            )
            labels.append(f"[v{n}][a{n}]")
        total += d
    if not labels:
        raise ErreurCollage("collage : rien à monter")
    parts.append(
        "".join(labels)
        + f"concat=n={len(labels)}:v={0 if audio_only else 1}:a=1"
        + ("[ao]" if audio_only else "[vo][ao]")
    )
    return "\n".join(parts), srcs, total


def rendre(root, stem, sortie):
    a = rush(root, stem)
    p = plan(root, stem)
    audio_only = a["kind"] == "audio"
    g, srcs, total = graphe(root, stem, p, audio_only)
    w = os.path.join(a["dir"], "_work")
    json.dump(
        [{"start": x["start"], "end": x["end"], "rush": x["rush"]} for x in p],
        open(os.path.join(w, "keep_total.json"), "w"),
    )
    gp = os.path.join(w, "collage_graph.txt")
    open(gp, "w").write(g)
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "warning"]
    for s in srcs:
        cmd += ["-i", s]
    cmd += ["-/filter_complex", gp]
    if audio_only:
        cmd += [
            "-map",
            "[ao]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]
    else:
        cmd += [
            "-map",
            "[vo]",
            "-map",
            "[ao]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]
    os.makedirs(os.path.dirname(sortie) or ".", exist_ok=True)
    subprocess.run(cmd + [sortie], check=True)
    print(f"Collage complet : {len(p)} plage(s), {total:.3f}s gardées → {sortie}")


# ---------------------------------------------------------------- fcpxml, cuts.md


def fcpxml_(root, stem, sortie, nom):
    import fcpxml as fx

    a = rush(root, stem)
    if a["kind"] == "audio":
        raise ErreurCollage("source audio : pas de timeline vidéo")
    p = plan(root, stem)
    srcs = [a["source"]] + [
        s for s in dict.fromkeys(x["src"] for x in p) if s != a["source"]
    ]
    info = {s: fx.probe(s) for s in srcs}
    w, h, _, _, fps, _, au = info[a["source"]]
    rate = int(au["sample_rate"]) if au else 48000
    fd = Fraction(1) / fps
    clips, off = [], 0
    for x in p:
        fs = info[x["src"]][4]
        s, e = round(x["start"] * fs), round(x["end"] * fs)
        d = round(Fraction(e - s) / fs * fps)
        if e <= s or d <= 0:
            continue
        clips.append((srcs.index(x["src"]), x["rush"], off, s, d, fs))
        off += d
    L = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.9">',
        "  <resources>",
        f'    <format id="r1" frameDuration="{fd.numerator}/{fd.denominator}s" width="{w}" height="{h}"/>',
    ]
    for k, s in enumerate(srcs):
        cw, chh, fs, dur, a2 = (
            info[s][2],
            info[s][3],
            info[s][4],
            info[s][5],
            info[s][6],
        )
        L.append(
            f'    <format id="r{3 + 2 * k}" frameDuration="{(Fraction(1) / fs).numerator}/{(Fraction(1) / fs).denominator}s" width="{cw}" height="{chh}"/>'
        )
        L.append(
            f'    <asset id="r{2 + 2 * k}" name={quoteattr(Path(s).name)} start="0s" duration="{fx.t(round(dur * fs), fs)}" '
            f'hasVideo="1" format="r{3 + 2 * k}"'
            + (
                f' hasAudio="1" audioSources="1" audioChannels="{int(a2["channels"])}" audioRate="{int(a2["sample_rate"])}"'
                if a2
                else ""
            )
            + ">"
        )
        L.append(
            f'      <media-rep kind="original-media" src={quoteattr("file://" + quote(str(Path(s).resolve())))}/>'
        )
        L.append("    </asset>")
    L += [
        "  </resources>",
        "  <library>",
        f"    <event name={quoteattr(nom)}>",
        f"      <project name={quoteattr(nom + ' derush')}>",
        f'        <sequence format="r1" duration="{fx.t(off, fps)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="{fx.SEQ_RATE.get(rate, "48k")}">',
        "          <spine>",
    ]
    for i, nm, o, s, d, fs in clips:
        L.append(
            f'            <asset-clip ref="r{2 + 2 * i}" name={quoteattr(nm)} offset="{fx.t(o, fps)}" '
            f'start="{fx.t(s, fs)}" duration="{fx.t(d, fps)}" tcFormat="NDF"/>'
        )
    L += [
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
        "",
    ]
    Path(sortie).write_text("\n".join(L))
    print(
        f"{len(clips)} clips, {float(off / fps):.2f} s, {w}x{h} @ {float(fps):.3f}, {len(srcs)} sources → {sortie}"
    )


def cuts(root, stem):
    a = rush(root, stem)
    L = ["", "## Insertions (mots collés d'une autre prise)"]
    for i in sorted(inserts(a["dir"]), key=lambda i: i["apres"]):
        txt = " ".join(m["w"] for m in i.get("mots", [])) or "(texte non gardé)"
        nb = len(i.get("barres", []))
        L.append(
            f"- après {i['apres']:.1f} s de la prise : « {txt} » ← {i['rush']} "
            f"{i['debut']:.1f} -> {i['fin']:.1f} s"
            + (f", {nb} mot(s) barré(s)" if nb else "")
        )
    return "\n".join(L)


def main(argv):
    if len(argv) >= 2 and argv[0] == "count":
        print(len(inserts(argv[1])))
    elif len(argv) == 3 and argv[0] == "plan":
        print(json.dumps(plan(argv[1], argv[2]), ensure_ascii=False))
    elif len(argv) == 4 and argv[0] == "render":
        rendre(argv[1], argv[2], argv[3])
    elif len(argv) == 5 and argv[0] == "fcpxml":
        fcpxml_(argv[1], argv[2], argv[3], argv[4])
    elif len(argv) == 3 and argv[0] == "cuts":
        print(cuts(argv[1], argv[2]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except ErreurCollage as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
