#!/usr/bin/env python3
"""Projets derush : plusieurs rushs déjà dérushés, UN montage, assemblé par blocs de texte.

Un projet vit dans $DERUSH_OUT_ROOT/_projets/<nom>/projet.json et ne référence que des
plages de temps dans la source de chaque rush : aucun média n'est recopié. Ce module porte le
modèle (blocs, plages, coupe, insertion), le placement d'une reprise, le plan de rendu et le
rendu. `bin/derush projet …`, le studio et les tests passent tous par lui.

Usage (root = $DERUSH_OUT_ROOT) :
  projet.py new <root> <nom> [STEM…]     crée un projet (séquence = blocs du premier rush)
  projet.py add <root> <nom> <STEM>      ajoute un rush
  projet.py kind <root> <nom>            audio ou video
  projet.py montrer <root> <nom>         une ligne par bloc : rush, début, fin, texte
Les erreurs sortent en français sur stderr, code 1, sans traceback.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FONDU = 0.2
NOM_RE = re.compile(r"^[\w-]+$")
MARGE_BORD = 0.25  # avant le premier mot, après le dernier mot
FIN_PHRASE = (".", "?", "!")


class ErreurProjet(ValueError):
    """Message en français, montré tel quel par la CLI et le studio."""


# ---------------------------------------------------------------- fichiers


def dossier(root, nom):
    if not isinstance(nom, str) or not NOM_RE.match(nom):
        raise ErreurProjet(f"nom de projet invalide : {nom}")
    return os.path.join(root, "_projets", nom)


def _dossier_rush(root, stem):
    if (
        not isinstance(stem, str)
        or not stem
        or stem.startswith(("_", "."))
        or "/" in stem
        or "\\" in stem
    ):
        raise ErreurProjet(f"rush inconnu : {stem}")
    return os.path.join(root, stem)


def rush(root, stem):
    """{"stem","kind","source"} ; inconnu si pas de dossier rangé, introuvable si la source a bougé."""
    d = _dossier_rush(root, stem)
    src_txt = os.path.join(d, "_work", "source.txt")
    if not os.path.isfile(src_txt):
        raise ErreurProjet(f"rush inconnu : {stem}")
    source = open(src_txt).read().strip()
    if not os.path.isfile(source):
        raise ErreurProjet(f"rush introuvable : {stem}")
    kind = "video"
    kp = os.path.join(d, "_work", "kind")
    if os.path.isfile(kp):
        kind = open(kp).read().strip() or "video"
    return {"stem": stem, "kind": kind, "source": source}


def _kind(root, stem):
    d = _dossier_rush(root, stem)
    kp = os.path.join(d, "_work", "kind")
    if os.path.isfile(kp):
        return open(kp).read().strip() or "video"
    return "video"


def charger(root, nom):
    p = os.path.join(dossier(root, nom), "projet.json")
    if not os.path.isfile(p):
        raise ErreurProjet(f"projet inconnu : {nom}")
    with open(p) as f:
        return json.load(f)


def ecrire(root, nom, p):
    d = dossier(root, nom)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "projet.json.tmp")
    with open(tmp, "w") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "projet.json"))


# ---------------------------------------------------------------- mots et blocs


def mots(root, stem):
    """Les mots alignés du rush, dans l'ordre : [{"w","s","e"}]."""
    a = os.path.join(_dossier_rush(root, stem), "_work", "aligned.json")
    if not os.path.isfile(a):
        raise ErreurProjet(f"rush introuvable : {stem}")
    out = []
    for seg in json.load(open(a)).get("segments", []):
        for w in seg.get("words", []):
            out.append(
                {
                    "w": str(w["word"]).strip(),
                    "s": float(w["start"]),
                    "e": float(w["end"]),
                }
            )
    return out


def garde(root, stem):
    """Les plages de keep.json du rush, ou None si le rush n'a pas encore été rendu."""
    k = os.path.join(_dossier_rush(root, stem), "keep.json")
    if not os.path.isfile(k):
        return None
    return [(float(r["start"]), float(r["end"])) for r in json.load(open(k))]


def caler(t, ms):
    """Une borne tombée dans un mot est ramenée au bord le plus proche de ce mot."""
    for m in ms:
        if m["s"] < t < m["e"]:
            return m["s"] if (t - m["s"]) <= (m["e"] - t) else m["e"]
    return t


def blocs(root, stem):
    ms = mots(root, stem)
    if not ms:
        return []
    groupes, cur = [], [0]
    for i in range(len(ms) - 1):
        trou = ms[i + 1]["s"] - ms[i]["e"]
        phrase = ms[i]["w"].rstrip("\"'»)”").endswith(FIN_PHRASE)
        if (phrase and trou >= 0.6 - 1e-9) or trou >= 1.2 - 1e-9:
            groupes.append(cur)
            cur = []
        cur.append(i + 1)
    groupes.append(cur)
    # un bloc a au moins 3 mots : sinon fusion avec le précédent (le premier, avec le suivant)
    fus = []
    for g in groupes:
        if fus and len(g) < 3:
            fus[-1] = fus[-1] + g
        else:
            fus.append(g)
    while len(fus) > 1 and len(fus[0]) < 3:
        fus[1] = fus[0] + fus[1]
        fus.pop(0)
    out = []
    for k, g in enumerate(fus):
        if k == 0:
            debut = max(0.0, ms[g[0]]["s"] - MARGE_BORD)
        else:
            p = fus[k - 1][-1]
            debut = (ms[p]["e"] + ms[g[0]]["s"]) / 2
        if k == len(fus) - 1:
            fin = ms[g[-1]]["e"] + MARGE_BORD
        else:
            n = fus[k + 1][0]
            fin = (ms[g[-1]]["e"] + ms[n]["s"]) / 2
        out.append({"rush": stem, "debut": round(debut, 3), "fin": round(fin, 3)})
    return out


def _mots_entre(ms, debut, fin):
    """Mots dont le milieu est dans [debut, fin)."""
    return [m for m in ms if debut <= (m["s"] + m["e"]) / 2 < fin]


def _recouvre(m, plages):
    d = max(m["e"] - m["s"], 1e-9)
    tot = sum(max(0.0, min(m["e"], b) - max(m["s"], a)) for a, b in plages)
    return tot / d


def mots_du_bloc(root, bloc):
    ms = _mots_entre(mots(root, bloc["rush"]), bloc["debut"], bloc["fin"])
    kp = garde(root, bloc["rush"])
    return [
        {
            "w": m["w"],
            "s": m["s"],
            "e": m["e"],
            "garde": True if kp is None else _recouvre(m, kp) >= 0.5,
        }
        for m in ms
    ]


def plages(root, bloc):
    kp = garde(root, bloc["rush"])
    d, f = bloc["debut"], bloc["fin"]
    if kp is None:
        return [(d, f)]
    out = []
    for a, b in kp:
        s, e = max(a, d), min(b, f)
        if e - s > 1e-6:
            out.append((s, e))
    return out


def couper(root, seq, i, t):
    if not 0 <= i < len(seq):
        raise ErreurProjet("coupe hors du bloc")
    b = seq[i]
    ms = mots(root, b["rush"])
    t = caler(float(t), ms)
    g = _mots_entre(ms, b["debut"], t)
    d = _mots_entre(ms, t, b["fin"])
    if not g or not d or not b["debut"] < t < b["fin"]:
        raise ErreurProjet("coupe hors du bloc")
    a = {"rush": b["rush"], "debut": b["debut"], "fin": t}
    c = {"rush": b["rush"], "debut": t, "fin": b["fin"]}
    return list(seq[:i]) + [a, c] + list(seq[i + 1 :])


def inserer(seq, apres, bloc):
    return list(seq[: apres + 1]) + [bloc] + list(seq[apres + 1 :])


def valider(root, p, sequence):
    """Renvoie la séquence aux bornes calées, ou lève ErreurProjet."""
    if not isinstance(sequence, list):
        raise ErreurProjet("séquence invalide")
    out = []
    for b in sequence:
        try:
            r, d, f = b["rush"], float(b["debut"]), float(b["fin"])
        except (KeyError, TypeError, ValueError):
            raise ErreurProjet("bloc invalide dans la séquence") from None
        if r not in p.get("rushs", []):
            raise ErreurProjet(f"rush inconnu : {r}")
        ms = mots(root, r)
        d, f = caler(d, ms), caler(f, ms)
        if not d < f:
            raise ErreurProjet(
                f"bloc invalide : début {d:.2f} s après la fin {f:.2f} s"
            )
        out.append({"rush": r, "debut": d, "fin": f})
    return out


def libres(root, p):
    """Par rush : ses blocs moins le temps déjà dans la séquence, morceaux d'au moins 1 mot."""
    res = {}
    for stem in p.get("rushs", []):
        ms = mots(root, stem)
        pris = sorted(
            (b["debut"], b["fin"]) for b in p.get("sequence", []) if b["rush"] == stem
        )
        morceaux = []
        for b in blocs(root, stem):
            cur = b["debut"]
            for a, z in pris:
                if z <= cur or a >= b["fin"]:
                    continue
                if a > cur:
                    morceaux.append((cur, a))
                cur = max(cur, z)
            if cur < b["fin"]:
                morceaux.append((cur, b["fin"]))
        res[stem] = [
            {"rush": stem, "debut": round(a, 3), "fin": round(z, 3)}
            for a, z in morceaux
            if _mots_entre(ms, a, z)
        ]
    return res


# ---------------------------------------------------------------- création


def _refuser_melange(stem, kind, kind_projet):
    if kind != kind_projet:
        qui = "un audio" if kind == "audio" else "une vidéo"
        quoi = "en audio" if kind_projet == "audio" else "en vidéo"
        raise ErreurProjet(
            f"un projet ne mélange pas audio seul et vidéo : {stem} est {qui}, le projet est {quoi}"
        )


def nouveau(root, nom, stems):
    d = dossier(root, nom)
    if os.path.isfile(os.path.join(d, "projet.json")):
        raise ErreurProjet(f"le projet {nom} existe déjà")
    uniques = []
    for s in stems:
        if s not in uniques:
            uniques.append(s)
    kind0 = None
    for s in uniques:
        rush(root, s)
        k = _kind(root, s)
        if kind0 is None:
            kind0 = k
        _refuser_melange(s, k, kind0)
    p = {
        "nom": nom,
        "rushs": uniques,
        "sequence": blocs(root, uniques[0]) if uniques else [],
        "propositions": [],
    }
    ecrire(root, nom, p)
    return p


def ajouter(root, nom, stem):
    p = charger(root, nom)
    if stem in p["rushs"]:
        return p
    rush(root, stem)
    if p["rushs"]:
        _refuser_melange(stem, _kind(root, stem), _kind(root, p["rushs"][0]))
    p["rushs"].append(stem)
    if len(p["rushs"]) == 1 and not p["sequence"]:
        p["sequence"] = blocs(root, stem)
    ecrire(root, nom, p)
    return p


def genre(root, p):
    return _kind(root, p["rushs"][0]) if p.get("rushs") else "video"


# ---------------------------------------------------------------- CLI


def _texte(root, bloc):
    return " ".join(m["w"] for m in mots_du_bloc(root, bloc))


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    cmd, root, nom = argv[0], argv[1], argv[2]
    rest = argv[3:]
    try:
        if cmd == "new":
            nouveau(root, nom, rest)
        elif cmd == "add":
            ajouter(root, nom, rest[0])
        elif cmd == "kind":
            print(genre(root, charger(root, nom)))
        elif cmd == "montrer":
            for b in charger(root, nom)["sequence"]:
                print(f"{b['rush']}\t{b['debut']}\t{b['fin']}\t{_texte(root, b)}")
        else:
            sys.exit(__doc__)
    except ErreurProjet as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
