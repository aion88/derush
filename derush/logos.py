#!/usr/bin/env python3
"""logos.py — pose le logo d'un outil au moment où son nom est dit.

Entrée : videos/<STEM>/logos.json  {"cues":[{"logo":"canva","t":14.27,"dur":2.0}, ...]}
  t = instant SOURCE (lu dans `derush words`), converti vers la timeline montée via keep.json.
Logos : videos/_logos/src/<logo>.(svg|png|jpg). Sans fichier → carte avec le nom en texte.
Cartes : blanches, arrondies, 30 % de la largeur, en haut à gauche par défaut (IMG_4596 : le
visage occupe le tiers haut centré, l'étagère à gauche est libre). Fondu 0,2 s. Une cue coupe la
précédente (listes rapides). Sortie : <STEM>.logos.mp4 (vidéo ré-encodée, audio copié).

Usage: logos.py <rush_dir> [--x 0.04|center] [--y 0.03] [--width 0.30] [--dur 2.0]
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

def run(cmd): subprocess.run(cmd, check=True)

def probe(mp4):
    out = subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height",
                          "-of","csv=p=0",str(mp4)],capture_output=True,text=True,check=True).stdout.strip()
    w,h = out.split(","); return int(w),int(h)

def make_card(name: str, src_dir: Path, out: Path, size: int) -> Path:
    card = out / f"{name}.{size}.png"
    if card.exists(): return card
    out.mkdir(parents=True, exist_ok=True)
    srcs = [p for p in src_dir.glob(f"{name}.*") if p.suffix.lower() in (".svg",".png",".jpg",".jpeg")]
    logo = int(size * 0.58); pad = (size - logo) // 2
    tmp = out / f"_{name}.logo.png"
    if srcs:
        s = sorted(srcs, key=lambda p: p.suffix != ".svg")[0]
        if s.suffix == ".svg":
            run(["rsvg-convert","-w",str(logo),"-h",str(logo),"--keep-aspect-ratio",str(s),"-o",str(tmp)])
        else:
            run(["magick",str(s),"-resize",f"{logo}x{logo}",str(tmp)])
        inner = [str(tmp)]
    else:  # carte texte
        # caption: ajuste la taille de police à la boîte (label: ne le fait pas, « Xfield » sortait minuscule)
        inner = ["-font",FONT,"-fill","#111111","-background","none","-size",f"{logo}x{int(logo*0.5)}",
                 "-gravity","center",f"caption:{name.capitalize()}"]
    r = int(size * 0.12)
    run(["magick","-size",f"{size}x{size}","xc:none","-fill","white",
         "-draw",f"roundrectangle 0,0,{size-1},{size-1},{r},{r}",
         "(", *inner, ")","-gravity","center","-composite", str(card)])
    if tmp.exists(): tmp.unlink()
    return card

def to_output_time(t: float, keep: list[tuple[float,float]]) -> float | None:
    acc = 0.0
    for s,e in keep:
        if s <= t <= e: return acc + (t - s)
        if t < s: return None
        acc += e - s
    return None

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rush_dir"); ap.add_argument("--y",type=float,default=0.03)
    ap.add_argument("--x",default="0.04",help="fraction de W pour le bord gauche, ou center")
    ap.add_argument("--width",type=float,default=0.30); ap.add_argument("--dur",type=float,default=2.0)
    a = ap.parse_args()
    d = Path(a.rush_dir); stem = d.name; root = d.parent
    mp4 = d / f"{stem}.derush.mp4"; out = d / f"{stem}.logos.mp4"
    cues = json.load(open(d / "logos.json"))["cues"]
    keep = [(k["start"],k["end"]) for k in json.load(open(d / "keep.json"))]
    W,H = probe(mp4); size = int(round(W * a.width)); y = int(round(H * a.y))
    x0 = int(round(W * float(a.x))) if a.x != "center" else None
    placed = []
    for c in cues:
        t = to_output_time(c["t"], keep)
        if t is None:
            print(f"  {c['logo']:12s} {c['t']:7.2f} s : dans une coupe, ignoré", file=sys.stderr); continue
        placed.append({"logo":c["logo"],"src":c["t"],"start":round(t,3),"dur":float(c.get("dur",a.dur))})
    placed.sort(key=lambda p: p["start"])
    # Une liste dite vite (Excel, PowerPoint, Word) : les cartes se rangent côte à côte,
    # 3 colonnes max, au lieu de se couper (Excel ne restait que 0,36 s au premier essai).
    gap = int(size * 0.06); slots = [-1.0, -1.0, -1.0]
    for p in placed:
        p["end"] = round(p["start"] + p["dur"], 3); p["len"] = round(p["dur"], 3)
        free = [k for k,e in enumerate(slots) if e < p["start"]]
        k = free[0] if free else min(range(3), key=lambda k: slots[k])
        slots[k] = p["end"]; p["slot"] = k
    cmd = ["ffmpeg","-nostdin","-y","-loglevel","error","-i",str(mp4)]
    fc = []; prev = "0:v"
    for i,p in enumerate(placed):
        card = make_card(p["logo"], root / "_logos" / "src", root / "_logos" / "cards", size)
        cmd += ["-loop","1","-t",f"{p['len']:.3f}","-i",str(card)]
        fo = max(0.0, p["len"] - 0.2)
        xs = f"(W-w)/2+{(p['slot']-1)*(size+gap)}" if x0 is None else str(x0 + p["slot"]*(size+gap))
        fc.append(f"[{i+1}:v]format=rgba,fade=t=in:st=0:d=0.2:alpha=1,fade=t=out:st={fo:.3f}:d=0.2:alpha=1,"
                  f"setpts=PTS-STARTPTS+{p['start']:.3f}/TB[l{i}]")
        fc.append(f"[{prev}][l{i}]overlay=x={xs}:y={y}:eof_action=pass:enable='between(t,{p['start']:.3f},{p['end']:.3f})'[v{i}]")
        prev = f"v{i}"
        print(f"  {p['logo']:12s} source {p['src']:7.2f} s → sortie {p['start']:7.2f}-{p['end']:7.2f} s  colonne {p['slot']+1}", file=sys.stderr)
    if not placed: sys.exit("aucune cue plaçable")
    cmd += ["-filter_complex",";".join(fc),"-map",f"[{prev}]","-map","0:a","-c:v","libx264","-preset","medium","-crf","18",
            "-pix_fmt","yuv420p","-c:a","copy",str(out)]
    run(cmd)
    json.dump({"cues":placed,"card_px":size,"y_px":y}, open(d / "_work" / "logos_placed.json","w"), indent=1)
    print(f"{len(placed)} logos → {out}", file=sys.stderr)

if __name__ == "__main__":
    main()
