#!/usr/bin/env python3
"""Projets derush : plusieurs rushs déjà dérushés, UN montage, assemblé par blocs de texte.

Un projet vit dans $DERUSH_OUT_ROOT/_projets/<nom>/projet.json et ne référence que des
plages de temps dans la source de chaque rush : aucun média n'est recopié. Ce module porte le
modèle (blocs, plages, coupe, insertion), le placement d'une reprise, le plan de rendu et le
rendu. `bin/derush projet …`, le studio et les tests passent tous par lui.

Usage (root = $DERUSH_OUT_ROOT) :
  projet.py new <root> <nom> [STEM…]     crée un projet (séquence = un clip par prise, dans l'ordre)
  projet.py add <root> <nom> <STEM>      ajoute un rush (son clip arrive en fin de piste)
  projet.py op <root> <nom> '<json>'     une opération de piste : {"op":"couper","i","t"}, {"op":"deplacer","i","j"},
                                         {"op":"retirer","i"}, {"op":"trimmer","i","cote":"debut|fin","t"}
  projet.py kind <root> <nom>            audio ou video
  projet.py resume <root> <nom>          durées et nombre de fondus (JSON)
  projet.py render <root> <nom>          monte le projet (mp4|m4a, fcpxml, cuts.md)
  projet.py a-rendre <root> <nom>        les rushs sans keep.json, un par ligne
  projet.py montrer <root> <nom>         une ligne par bloc : rush, début, fin, texte
  projet.py placer <root> <nom> <STEM> <début> <fin>   propose où va ce bloc (JSON), le range
  projet.py accepter|refuser <root> <nom> <k>          applique ou efface la proposition k
Les erreurs sortent en français sur stderr, code 1, sans traceback.
"""

import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FONDU = 0.2
NOM_RE = re.compile(r"^[\w-]+\Z")  # \Z et non $ : « demo\n » ne passe pas
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


@contextlib.contextmanager
def verrou(root, nom):
    """Verrou de fichier (flock) : tout load-modify-write de projet.json le prend, CLI et studio compris.
    Le fichier vit à côté du dossier du projet (`_projets/.<nom>.lock`), pas dedans."""
    dossier(root, nom)
    base = os.path.join(root, "_projets")
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, f".{nom}.lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


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


def duree_source(root, stem):
    """Durée de la source du rush en secondes, ou None si elle ne se sonde pas."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
             rush(root, stem)["source"]],
            capture_output=True, text=True, check=True,
        )
        d = float(r.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None
    return d if d > 0 else None


def clip_rush(root, stem):
    """Le clip de départ d'une prise : toute la prise gardée, du premier au dernier mot gardé."""
    kp, ms, D = garde(root, stem), mots(root, stem), duree_source(root, stem)
    if kp:
        debut, fin = min(a for a, _ in kp), max(b for _, b in kp)
    elif ms:
        debut, fin = max(0.0, ms[0]["s"] - MARGE_BORD), ms[-1]["e"] + MARGE_BORD
        if D is not None:
            fin = min(fin, D)
    elif D is not None:
        debut, fin = 0.0, D
    else:
        raise ErreurProjet(f"rush sans mots ni durée lisible : {stem}")
    return {"rush": stem, "debut": round(debut, 3), "fin": round(fin, 3)}


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
    kp = garde(root, stem)
    if kp is not None:  # un trou coupé par le montage du rush : les deux blocs prennent chacun son bord gardé
        for k in range(len(out) - 1):
            m = out[k]["fin"]
            if any(a - 1e-9 <= m <= z + 1e-9 for a, z in kp):
                continue
            avant = [z for a, z in kp if z <= m]
            apres = [a for a, z in kp if a >= m]
            if avant and apres:
                out[k]["fin"] = round(max(avant), 3)
                out[k + 1]["debut"] = round(min(apres), 3)
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
    """Ce que le clip joue. La première plage commence EXACTEMENT à `debut` et la dernière finit exactement
    à `fin` : un trim vers l'extérieur rend le temps que le montage du rush avait coupé (c'est sa main).
    À l'intérieur du clip, les coupes du montage du rush s'appliquent."""
    kp = garde(root, bloc["rush"])
    d, f = bloc["debut"], bloc["fin"]
    if kp is None:
        return [(d, f)]
    out = []
    for a, b in kp:
        s, e = max(a, d), min(b, f)
        if e - s > 1e-6:
            out.append((s, e))
    if not out:
        return [(d, f)]
    out[0] = (d, out[0][1])
    out[-1] = (out[-1][0], f)
    return out


def couper(root, seq, i, t):
    """Coupe le clip i en deux à t (ramené hors d'un mot). Sans perte : si t tombe dans un trou coupé par
    le montage du rush, A1 finit où finit la plage gardée d'avant et A2 commence où commence celle d'après."""
    if not 0 <= i < len(seq):
        raise ErreurProjet("coupe hors du bloc")
    b = seq[i]
    ms = mots(root, b["rush"])
    t = caler(float(t), ms)
    g = _mots_entre(ms, b["debut"], t)
    d = _mots_entre(ms, t, b["fin"])
    if not b["debut"] < t < b["fin"] or (ms and (not g or not d)):
        raise ErreurProjet("coupe hors du bloc")
    fin_a, debut_c = t, t
    kp = garde(root, b["rush"])
    if kp is not None and not any(a - 1e-9 <= t <= z + 1e-9 for a, z in kp):
        avant = [z for a, z in kp if z <= t and z > b["debut"]]
        apres = [a for a, z in kp if a >= t and a < b["fin"]]
        if not avant or not apres:
            raise ErreurProjet("coupe hors du bloc")
        fin_a, debut_c = max(avant), min(apres)
    a = {"rush": b["rush"], "debut": b["debut"], "fin": fin_a}
    c = {"rush": b["rush"], "debut": debut_c, "fin": b["fin"]}
    return list(seq[:i]) + [a, c] + list(seq[i + 1 :])


def _indice(seq, i, msg):
    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(seq):
        raise ErreurProjet(msg)
    return i


def deplacer(seq, i, j):
    """Le clip i passe à la position j (indice final)."""
    _indice(seq, i, "déplacement hors de la piste")
    _indice(seq, j, "déplacement hors de la piste")
    out = list(seq)
    out.insert(j, out.pop(i))
    return out


def retirer(seq, i):
    _indice(seq, i, "retrait hors de la piste")
    return list(seq[:i]) + list(seq[i + 1 :])


def pas_image(root, stem):
    """Durée d'une image de la source du rush (0,01 s pour un audio, 1/30 si la sonde échoue)."""
    try:
        info = rush(root, stem)
        if info["kind"] == "audio":
            return 0.01
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
             "-of", "default=nw=1:nk=1", info["source"]],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        n, _, d = r.partition("/")
        fps = float(n) / float(d or 1)
        return 1 / fps if fps > 0 else 1 / 30
    except (subprocess.CalledProcessError, ValueError, ZeroDivisionError, OSError, ErreurProjet):
        return 1 / 30


def trimmer(root, seq, i, cote, t):
    """Déplace un bord du clip i à t : posé tel quel (jamais ramené hors d'un mot), arrondi à l'image,
    borné à la source du rush, un clip garde au moins une image."""
    if cote not in ("debut", "fin"):
        raise ErreurProjet("trim : côté inconnu")
    _indice(seq, i, "trim hors de la piste")
    try:
        t = float(t)
    except (TypeError, ValueError):
        raise ErreurProjet("trim : temps invalide") from None
    if t != t or t in (float("inf"), float("-inf")):
        raise ErreurProjet("trim : temps invalide")
    b = seq[i]
    pas = pas_image(root, b["rush"])
    D = duree_source(root, b["rush"])
    t = round(round(t / pas) * pas, 4)
    if cote == "debut":
        t = max(0.0, min(t, b["fin"] - pas))
    else:
        t = max(b["debut"] + pas, t if D is None else min(t, D))
    out = list(seq)
    out[i] = dict(b, **{cote: round(t, 6)})
    return out


def operer(root, nom, op):
    """Une opération de piste sous verrou : couper, deplacer, retirer, trimmer. Renvoie le projet."""
    if not isinstance(op, dict):
        raise ErreurProjet("opération invalide")
    with verrou(root, nom):
        p = charger(root, nom)
        seq, nom_op = p["sequence"], op.get("op")
        if nom_op == "couper":
            nouveau_seq = couper(root, seq, op.get("i"), op.get("t"))
        elif nom_op == "deplacer":
            nouveau_seq = deplacer(seq, op.get("i"), op.get("j"))
        elif nom_op == "retirer":
            nouveau_seq = retirer(seq, op.get("i"))
        elif nom_op == "trimmer":
            nouveau_seq = trimmer(root, seq, op.get("i"), op.get("cote"), op.get("t"))
        else:
            raise ErreurProjet(f"opération inconnue : {nom_op}")
        p["sequence"] = valider(root, p, nouveau_seq)
        ecrire(root, nom, p)
        return p


def inserer(seq, apres, bloc):
    return list(seq[: apres + 1]) + [bloc] + list(seq[apres + 1 :])


def valider(root, p, sequence):
    """Renvoie la séquence aux bornes calées, ou lève ErreurProjet."""
    if not isinstance(sequence, list):
        raise ErreurProjet("séquence invalide")
    out, sources = [], {}
    for b in sequence:
        try:
            r, d, f = b["rush"], float(b["debut"]), float(b["fin"])
        except (KeyError, TypeError, ValueError):
            raise ErreurProjet("bloc invalide dans la séquence") from None
        if r not in p.get("rushs", []):
            raise ErreurProjet(f"rush absent du projet : {r}")
        # une borne posée à la main reste telle quelle (révision piste) : seulement bornée à la source
        if r not in sources:
            sources[r] = duree_source(root, r)
        d = max(0.0, d)
        if sources[r] is not None:
            f = min(f, sources[r])
        d, f = round(d, 4), round(f, 4)
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
    with verrou(root, nom):
        return _nouveau(root, nom, stems)


def _nouveau(root, nom, stems):
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
        "sequence": [clip_rush(root, r) for r in uniques],
        "propositions": [],
    }
    ecrire(root, nom, p)
    return p


def ajouter(root, nom, stem):
    with verrou(root, nom):
        return _ajouter(root, nom, stem)


def _ajouter(root, nom, stem):
    p = charger(root, nom)
    if stem in p["rushs"]:
        return p
    rush(root, stem)
    if p["rushs"]:
        _refuser_melange(stem, _kind(root, stem), _kind(root, p["rushs"][0]))
    p["rushs"].append(stem)
    p["sequence"] = list(p["sequence"]) + [clip_rush(root, stem)]
    ecrire(root, nom, p)
    return p


def enregistrer_sequence(root, nom, sequence):
    """Valide puis range la séquence, sous verrou."""
    with verrou(root, nom):
        p = charger(root, nom)
        p["sequence"] = valider(root, p, sequence)
        ecrire(root, nom, p)
        return p


def genre(root, p):
    return _kind(root, p["rushs"][0]) if p.get("rushs") else "video"


# ---------------------------------------------------------------- placement


def normaliser(w):
    """Minuscules, accents gardés, tout sauf lettres, chiffres et apostrophe retiré."""
    return "".join(c for c in w.lower() if c.isalnum() or c in "'’").replace("’", "'")


def _vue(b):
    return {"rush": b["rush"], "debut": b["debut"], "fin": b["fin"]}


def _avec_hote(seq, prop):
    """Une seule place pose `hote` : le bloc d'accueil au moment de la proposition."""
    a = prop["apres"]
    if a >= 0:
        prop["hote"] = _vue(seq[a])
    else:
        prop["hote"] = _vue(seq[0]) if seq else None
    return prop


def _milieu_trou(ms, i):
    """Milieu du trou entre le mot i-1 et le mot i."""
    return (ms[i - 1]["e"] + ms[i]["s"]) / 2


def reprise(root, seq, bloc):
    """Cas A : le bloc répète au moins 4 mots d'un bloc de la séquence, dans ses 8 premiers mots.
    La comparaison porte sur les mots GARDÉS (un « euh » barré par le montage du rush n'est pas dit
    dans le rendu) ; les index d'origine servent à placer les coupes."""
    nm = mots_du_bloc(root, bloc)
    ni = [i for i, m in enumerate(nm) if m["garde"]]
    nn = [normaliser(nm[i]["w"]) for i in ni]
    n = len(nn)
    hotes = [mots_du_bloc(root, b) for b in seq]
    hi = [[i for i, m in enumerate(h) if m["garde"]] for h in hotes]
    hn = [[normaliser(h[i]["w"]) for i in idx] for h, idx in zip(hotes, hi)]
    best = None  # (longueur, j, m, -k)
    for k in range(0, min(8, n) - 3):
        for j, h in enumerate(hn):
            for m in range(len(h)):
                L = 0
                while (
                    k + L < n
                    and m + L < len(h)
                    and nn[k + L]
                    and nn[k + L] == h[m + L]
                ):
                    L += 1
                if L >= 4 and (best is None or (L, j, m, -k) > best[0]):
                    best = ((L, j, m, -k), L, j, m, k)
    if best is None:
        return None
    _, L, j, m, k = best
    passage = " ".join(nm[i]["w"] for i in ni[k : k + L])
    if k + L >= n:
        raise ErreurProjet(f"rien de neuf dans ce bloc : il répète « {passage} »")
    dup_fin = ni[k + L - 1]  # dernier mot répété, index d'origine
    h = hotes[j]
    he = hi[j][m + L - 1]
    couper_a = None if he + 1 >= len(h) else _milieu_trou(h, he + 1)
    prop = {
        "bloc": {
            "rush": bloc["rush"],
            "debut": round(_milieu_trou(nm, dup_fin + 1), 3),
            "fin": bloc["fin"],
        },
        "apres": j,
        "couper_a": None if couper_a is None else round(couper_a, 3),
        "raison": f"reprend « {passage} » : placé juste après, doublon retiré",
        "cas": "A",
    }
    return _avec_hote(seq, prop)


def _prompt_llm(root, seq, bloc):
    def lignes(b):
        return " ".join(f"{i}:{m['w']}" for i, m in enumerate(mots_du_bloc(root, b)))

    blocs_txt = "\n".join(f"[{k}] {lignes(b)}" for k, b in enumerate(seq))
    return (
        "Tu aides à monter une vidéo parlée en français. La séquence actuelle est une liste "
        "de blocs numérotés ; dans chaque bloc les mots sont numérotés (n:mot).\n\n"
        f"SÉQUENCE :\n{blocs_txt}\n\n"
        f"BLOC À PLACER (une prise refaite) :\n{lignes(bloc)}\n\n"
        "Où ce bloc va-t-il, dans le fil du discours ? Réponds par UN SEUL objet JSON, rien "
        'd\'autre : {"apres": <numéro du bloc de la séquence après lequel il va, -1 pour tout au '
        'début>, "couper_a_mot": <numéro d\'un mot DU BLOC « apres » : ce bloc est coupé juste '
        "avant ce mot et le nouveau bloc passe entre les deux moitiés ; null pour ne rien couper>, "
        '"raison": "<une phrase>"}'
    )


def placer_llm(root, seq, bloc):
    """Cas B : le LLM dit où va le bloc. Rien n'est appliqué ici."""
    import llm

    if not seq:
        return _avec_hote(
            seq,
            {"bloc": _vue(bloc), "apres": -1, "couper_a": None,
             "raison": "la séquence est vide", "cas": "B"},
        )
    try:
        brut, _ = llm.complete(_prompt_llm(root, seq, bloc))
    except (llm.NoLLM, RuntimeError) as e:
        raise ErreurProjet(str(e)) from None
    m = re.search(r"\{.*\}", brut, re.S)
    try:
        r = json.loads(m.group(0)) if m else None
        apres = r["apres"]
        mot = r.get("couper_a_mot")
    except (ValueError, KeyError, AttributeError, TypeError):
        raise ErreurProjet(f"réponse LLM illisible : {brut.strip()[:200]}") from None
    if isinstance(apres, bool) or not isinstance(apres, int) or not -1 <= apres < len(seq):
        raise ErreurProjet(f"réponse LLM hors séquence : apres={apres}")
    couper_a = None
    if mot is not None:
        hm = mots_du_bloc(root, seq[apres]) if apres >= 0 else []
        if isinstance(mot, bool) or not isinstance(mot, int) or not 1 <= mot <= len(hm) - 1:
            raise ErreurProjet(f"réponse LLM hors séquence : couper_a_mot={mot}")
        couper_a = round(_milieu_trou(hm, mot), 3)
    prop = {
        "bloc": _vue(bloc),
        "apres": apres,
        "couper_a": couper_a,
        "raison": str(r.get("raison") or "").strip() or "proposé par le LLM",
        "cas": "B",
    }
    return _avec_hote(seq, prop)


def calculer_proposition(root, p, bloc):
    """A d'abord, sinon B. Ne touche à aucun fichier."""
    seq = p.get("sequence", [])
    prop = reprise(root, seq, bloc)
    return prop if prop is not None else placer_llm(root, seq, bloc)


def ajouter_proposition(root, nom, prop):
    with verrou(root, nom):
        p = charger(root, nom)
        p.setdefault("propositions", []).append(prop)
        ecrire(root, nom, p)
        return p


def _proposition(p, k):
    props = p.get("propositions", [])
    if not isinstance(k, int) or not 0 <= k < len(props):
        raise ErreurProjet(f"proposition inconnue : {k}")
    return props[k]


def _meme(a, b):
    return (
        a is not None
        and b is not None
        and a["rush"] == b["rush"]
        and abs(a["debut"] - b["debut"]) < 1e-3
        and abs(a["fin"] - b["fin"]) < 1e-3
    )


def accepter(root, nom, k):
    with verrou(root, nom):
        p = charger(root, nom)
        prop = _proposition(p, k)
        seq, apres, hote = p["sequence"], prop["apres"], prop.get("hote")
        if apres >= 0:
            ok = apres < len(seq) and _meme(seq[apres], hote)
        else:
            ok = (not seq and hote is None) or (bool(seq) and _meme(seq[0], hote))
        if not ok:
            raise ErreurProjet("proposition périmée : la séquence a changé, relance Placer")
        b = prop["bloc"]
        if any(x["rush"] == b["rush"] and min(x["fin"], b["fin"]) - max(x["debut"], b["debut"]) > 1e-3 for x in seq):
            raise ErreurProjet(
                "ce passage est déjà dans la séquence : retire-le d'abord, ou refuse la proposition"
            )
        if prop["couper_a"] is not None:
            seq = couper(root, seq, apres, prop["couper_a"])
        p["sequence"] = valider(root, p, inserer(seq, apres, b))
        p["propositions"] = [x for i, x in enumerate(p["propositions"]) if i != k]
        ecrire(root, nom, p)
        return p


def refuser(root, nom, k):
    with verrou(root, nom):
        p = charger(root, nom)
        _proposition(p, k)
        p["propositions"] = [x for i, x in enumerate(p["propositions"]) if i != k]
        ecrire(root, nom, p)
        return p


# ---------------------------------------------------------------- plan de rendu


def _silences(root, stem):
    f = os.path.join(_dossier_rush(root, stem), "_work", "silence_cuts.json")
    if not os.path.isfile(f):
        return []
    return [
        (float(c["start"]), float(c["end"]))
        for c in json.load(open(f)).get("filler_cuts", [])
    ]


def _marge_fin(ms, sil, E, bfin):
    """Rallonge la fin E vers le silence voisin jusqu'à FONDU après le dernier mot gardé."""
    avant = [m for m in ms if m["s"] < E - 1e-6]
    if not avant or avant[-1]["e"] > E + 1e-6:
        return E  # pas de mot, ou la borne tombe dans un mot : on ne touche à rien
    dernier = avant[-1]
    if E - dernier["e"] >= FONDU - 1e-6:
        return E
    span = next((b for a, b in sil if a <= E + 1e-3 and b > E + 1e-6), None)
    if span is None:
        return E
    suivants = [m["s"] for m in ms if m["s"] >= E - 1e-6]
    borne = min([dernier["e"] + FONDU, bfin, span] + suivants[:1])
    return max(E, borne)


def _marge_debut(ms, sil, S, bdebut):
    """Idem pour le début S : le fondu ne doit pas manger le premier mot gardé."""
    apres = [m for m in ms if m["e"] > S + 1e-6]
    if not apres or apres[0]["s"] < S - 1e-6:
        return S
    premier = apres[0]
    if premier["s"] - S >= FONDU - 1e-6:
        return S
    span = next((a for a, b in sil if a < S - 1e-6 and b >= S - 1e-3), None)
    if span is None:
        return S
    precedents = [m["e"] for m in ms if m["e"] <= S + 1e-6]
    borne = max([premier["s"] - FONDU, bdebut, span] + precedents[-1:])
    return min(S, borne)


def plan_rendu(root, p):
    """(runs, vides) : une suite de blocs d'un même rush = un run, coupé en un seul passage."""
    seq = p.get("sequence", [])
    runs, vides = [], []
    for i, b in enumerate(seq):
        pl = plages(root, b)
        if not pl:
            vides.append(i)
            continue
        if runs and runs[-1]["rush"] == b["rush"]:
            r = runs[-1]
        else:
            info = rush(root, b["rush"])
            r = {"rush": b["rush"], "source": info["source"], "kind": info["kind"],
                 "plages": [], "blocs": []}
            runs.append(r)
        r["blocs"].append(i)
        for a, z in pl:
            if r["plages"] and abs(r["plages"][-1][1] - a) < 1e-3:
                r["plages"][-1][1] = z
            else:
                r["plages"].append([a, z])
    for k, r in enumerate(runs):
        ms, sil = mots(root, r["rush"]), _silences(root, r["rush"])
        if k < len(runs) - 1:
            r["plages"][-1][1] = _marge_fin(ms, sil, r["plages"][-1][1], seq[r["blocs"][-1]]["fin"])
        if k > 0:
            r["plages"][0][0] = _marge_debut(ms, sil, r["plages"][0][0], seq[r["blocs"][0]]["debut"])
    return runs, vides


def hors_montage_voulu(root, bloc):
    """Intervalles entre un bord du clip et le bord gardé le plus proche (tout le clip si aucune plage gardée
    ne le touche) : ce temps hors du montage du rush est là parce qu'elle a tiré le bord, c'est sa main."""
    kp = garde(root, bloc["rush"])
    if kp is None:
        return []
    d, f = bloc["debut"], bloc["fin"]
    inter = [(max(a, d), min(b, f)) for a, b in kp if min(b, f) - max(a, d) > 1e-6]
    if not inter:
        return [(d, f)]
    out = []
    if d < inter[0][0] - 1e-9:
        out.append((d, inter[0][0]))
    if inter[-1][1] < f - 1e-9:
        out.append((inter[-1][1], f))
    return out


def _moins(a, z, coupes):
    """[a, z] privé des intervalles `coupes` : la liste des morceaux restants."""
    out, cur = [], a
    for x, y in sorted(coupes):
        if y <= cur:
            continue
        if x >= z:
            break
        if x > cur:
            out.append((cur, x))
        cur = max(cur, y)
    if cur < z:
        out.append((cur, z))
    return out


def _fr(x):
    return f"{x:.2f}".replace(".", ",")


def garde_projet(root, p, runs):
    """Erreurs (liste vide = vert) : plage hors du montage du rush, borne dans un mot, run trop court."""
    err = []
    for k, r in enumerate(runs):
        ms, sil, kp = mots(root, r["rush"]), _silences(root, r["rush"]), garde(root, r["rush"])
        voulu = [iv for i in r.get("blocs", []) for iv in hors_montage_voulu(root, p["sequence"][i])]
        for a, z in r["plages"]:
            if kp is not None:
                morceaux = [m for x, y in _moins(a, z, kp) for m in _moins(x, y, voulu)]
                for x, y in morceaux:
                    if y - x < 1e-3:
                        continue
                    dans_silence = any(sa - 1e-3 <= x and y <= sb + 1e-3 for sa, sb in sil)
                    sur_mot = any(m["s"] < y - 1e-3 and m["e"] > x + 1e-3 for m in ms)
                    if not dans_silence or sur_mot:
                        err.append(
                            f"plage {_fr(x)}-{_fr(y)} s de {r['rush']} hors du montage du rush"
                        )
            for t, debut_plage in ((a, True), (z, False)):
                for m in ms:
                    if m["s"] + 0.03 < t < m["e"] - 0.03:
                        # Même règle que check_clips : la partie du mot du côté coupé peut être du
                        # silence détecté (mot étiré sur une pause) ; seul le reste est une perte.
                        x, y = (m["s"], t) if debut_plage else (t, m["e"])
                        couvert = sum(max(0.0, min(y, sb) - max(x, sa)) for sa, sb in sil)
                        if (y - x) - couvert > 0.03:
                            err.append(
                                f"borne {_fr(t)} s de {r['rush']} dans un mot : « {m['w']} »"
                            )
        if len(runs) > 1:
            duree = sum(z - a for a, z in r["plages"])
            if duree < 2 * FONDU + 0.1 - 1e-6:
                debut = " ".join(
                    m["w"] for m in mots_du_bloc(root, p["sequence"][r["blocs"][0]])[:5]
                )
                err.append(
                    f"bloc trop court pour un fondu ({_fr(duree)} s gardées) : « {debut} », "
                    "retire-le ou rallonge-le"
                )
    return err


def mots_dans_fondu(root, runs):
    """Mots gardés qui passent sous un fondu de 0,2 s : à écouter."""
    out = []
    for k, r in enumerate(runs):
        ms = mots(root, r["rush"])
        zones = []
        if k < len(runs) - 1:
            e = r["plages"][-1][1]
            zones.append((e - FONDU, e))
        if k > 0:
            s = r["plages"][0][0]
            zones.append((s, s + FONDU))
        for zs, ze in zones:
            for m in ms:
                milieu = (m["s"] + m["e"]) / 2
                dedans = any(a <= milieu <= z for a, z in r["plages"])
                if m["e"] > zs + 1e-6 and m["s"] < ze - 1e-6 and dedans:
                    out.append(f"« {m['w']} » ({r['rush']}, {_fr(m['s'])} s)")
    return out


def resume(root, nom):
    p = charger(root, nom)
    runs, vides = plan_rendu(root, p)
    return _resume(p, runs, vides)


def _resume(p, runs, vides):
    return {
        "total": round(sum(z - a for r in runs for a, z in r["plages"]), 3),
        "fondus": max(0, len(runs) - 1),
        "blocs": len(p.get("sequence", [])),
        "vides": len(vides),
    }


# ---------------------------------------------------------------- rendu


def a_rendre(root, nom):
    """Les rushs du projet qui n'ont pas encore de keep.json (derush render d'abord)."""
    p = charger(root, nom)
    return [s for s in p.get("rushs", []) if garde(root, s) is None]


def _sonde(chemin):
    d = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", chemin],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    v = next((x for x in d["streams"] if x["codec_type"] == "video"), None)
    a = next((x for x in d["streams"] if x["codec_type"] == "audio"), None)
    return {
        "w": int(v["width"]) if v else 0,
        "h": int(v["height"]) if v else 0,
        "fps": v["r_frame_rate"] if v else "",
        "rate": int(a["sample_rate"]) if a else 48000,
        "layout": (a.get("channel_layout") or ("mono" if int(a.get("channels", 2)) == 1 else "stereo")) if a else "stereo",
        "duree": float(d["format"]["duration"]),
        "vduree": float(v.get("duration") or d["format"]["duration"]) if v else 0.0,
    }


def _fps_txt(fps):
    try:
        n, d = fps.split("/")
        x = float(n) / float(d)
        return str(int(x)) if abs(x - round(x)) < 1e-3 else f"{x:.3f}"
    except (ValueError, ZeroDivisionError):
        return fps


def _ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise ErreurProjet(f"ffmpeg en échec : {r.stderr.strip()[-400:]}")


def _chaine(runs, fichiers, infos, audio, t0):
    """Graphe ffmpeg : chaque run normalisé au format du premier, puis xfade / acrossfade de 0,2 s."""
    lignes = []
    n = len(runs)
    for i in range(n):
        if not audio:
            lignes.append(
                f"[{i}:v]scale={t0['w']}:{t0['h']}:force_original_aspect_ratio=decrease,"
                f"pad={t0['w']}:{t0['h']}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={t0['fps']},"
                f"format=yuv420p,settb=AVTB[v{i}]"
            )
        lignes.append(
            f"[{i}:a]aresample={t0['rate']},aformat=sample_fmts=fltp:channel_layouts={t0['layout']}[a{i}]"
        )
    if not audio:
        cumul, prec = 0.0, "v0"
        for k in range(1, n):
            cumul += infos[k - 1]["vduree"]
            off = cumul - k * FONDU
            sortie = f"x{k}"
            lignes.append(
                f"[{prec}][v{k}]xfade=transition=fade:duration={FONDU}:offset={off:.6f}[{sortie}]"
            )
            prec = sortie
    prec = "a0"
    for k in range(1, n):
        sortie = f"y{k}"
        lignes.append(f"[{prec}][a{k}]acrossfade=d={FONDU}[{sortie}]")
        prec = sortie
    return ";\n".join(lignes), (None if audio else f"x{n - 1}"), prec


def duree_attendue(infos, audio):
    """Durée du montage d'après les runs RÉELLEMENT coupés (cut.sh cale chaque plage sur la grille d'images
    de sa source : la somme des plages brutes dérive de plus de 0,25 s sur un vrai rush à 100 coupes)."""
    return sum(i["duree"] if audio else i["vduree"] for i in infos) - FONDU * (len(infos) - 1)


def rendre(root, nom):
    """Monte le projet : <nom>.derush.mp4|m4a, <nom>.fcpxml (vidéo), cuts.md. Renvoie le chemin.
    Rien n'est écrit dans les sorties tant que la garde de durée n'a pas passé : un rendu refusé laisse
    le résultat précédent intact."""
    p = charger(root, nom)
    runs, vides = plan_rendu(root, p)
    if not runs:
        raise ErreurProjet("rien à monter : la séquence est vide ou entièrement coupée")
    err = garde_projet(root, p, runs)
    if err:
        raise ErreurProjet("GARDE ROUGE : " + " ; ".join(err))
    audio = genre(root, p) == "audio"
    for r in runs:
        if (r["kind"] == "audio") != audio:
            raise ErreurProjet(f"{r['rush']} n'est pas du même genre que le projet")
    res = _resume(p, runs, vides)  # depuis le plan en main : projet.json peut changer pendant le montage
    d = dossier(root, nom)
    work = os.path.join(d, "_work")
    os.makedirs(work, exist_ok=True)
    ext = "m4a" if audio else "mp4"
    sortie = os.path.join(d, f"{nom}.derush.{ext}")
    tmp = os.path.join(work, f"{nom}.tmp.{ext}")
    cut = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "cut.sh")
    env = dict(os.environ, AUDIO_ONLY="1" if audio else "0")
    fichiers = []
    try:
        for k, r in enumerate(runs):
            rj = os.path.join(work, f"run-{k}.json")
            json.dump([{"start": a, "end": z} for a, z in r["plages"]], open(rj, "w"))
            fo = os.path.join(work, f"run-{k}.{ext}")
            fichiers.append(fo)
            c = subprocess.run(["bash", cut, r["source"], rj, fo], capture_output=True, text=True, env=env)
            if c.returncode != 0 or not os.path.isfile(fo):
                raise ErreurProjet(f"{r['rush']} ne se coupe pas : {(c.stderr or c.stdout).strip()[-300:]}")
        infos = [_sonde(f) for f in fichiers]
        # le format de sortie est celui du PREMIER RUSH du projet (spec), pas du premier bloc de la séquence
        premier = p["rushs"][0] if p.get("rushs") else None
        t0 = infos[next((k for k, r in enumerate(runs) if r["rush"] == premier), 0)]
        if len(runs) == 1:
            os.replace(fichiers[0], tmp)
        else:
            graphe, vlab, alab = _chaine(runs, fichiers, infos, audio, t0)
            gp = os.path.join(work, "graph.txt")
            open(gp, "w").write(graphe)
            args = []
            for f in fichiers:
                args += ["-i", f]
            args += ["-/filter_complex", gp]
            if audio:
                args += ["-map", f"[{alab}]", "-c:a", "aac", "-b:a", "192k"]
            else:
                args += ["-map", f"[{vlab}]", "-map", f"[{alab}]", "-c:v", "libx264", "-preset", "fast",
                         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
            _ffmpeg(args + ["-movflags", "+faststart", tmp])
        attendu = duree_attendue(infos, audio)
        reel = _sonde(tmp)["duree"]
        if abs(reel - attendu) > 0.25:
            raise ErreurProjet(f"GARDE : durée {reel:.2f} s, attendu {attendu:.2f} s (±0,25)")
        if not audio:
            import fcpxml

            fcpxml.build(
                [(r["source"], a, z) for r in runs for a, z in r["plages"]],
                os.path.join(d, f"{nom}.fcpxml"),
                nom,
            )
        _cuts_md(root, nom, p, runs, vides, infos, audio, res, t0)
        os.replace(tmp, sortie)
    finally:
        for f in fichiers + [tmp] + [os.path.join(work, f"run-{k}.json") for k in range(len(runs))]:
            if os.path.exists(f):
                os.remove(f)
    return sortie


def _cuts_md(root, nom, p, runs, vides, infos, audio, res, t0):
    seq = p["sequence"]
    L = [f"# {nom} : projet", "", f"Monté le {time.strftime('%Y-%m-%d %H:%M')}.", "", "## Blocs", ""]
    for i, b in enumerate(seq):
        if i in vides:
            L.append(
                f"{i + 1}. bloc vide : {b['rush']} {_fr(b['debut'])}-{_fr(b['fin'])} s, "
                "tout est coupé par le montage du rush, ignoré"
            )
            continue
        gardees = sum(z - a for a, z in plages(root, b))
        texte = " ".join(m["w"] for m in mots_du_bloc(root, b) if m["garde"])
        L.append(
            f"{i + 1}. {b['rush']} {_fr(b['debut'])}-{_fr(b['fin'])} s, {_fr(gardees)} s gardées : {' '.join(texte.split()[:8])}"
        )
    L += ["", "## Passages (un passage = des blocs de suite d'un même rush)", ""]
    for k, r in enumerate(runs):
        L.append(
            f"{k + 1}. {r['rush']} : blocs {', '.join(str(i + 1) for i in r['blocs'])}, "
            f"{_fr(sum(z - a for a, z in r['plages']))} s"
        )
    nb = sum(1 for i in range(len(seq)) if i not in vides)
    L += ["", f"{max(0, nb - 1)} raccords, {res['fondus']} fondus de 0,2 s (vidéo et son) entre rushs différents ;",
          "même rush : coupe franche.", ""]
    if vides:
        L += [f"{len(vides)} bloc(s) vide(s) ignoré(s) (voir la liste des blocs).", ""]
    if not audio:
        for r, inf in zip(runs, infos):
            if (inf["w"], inf["h"], inf["fps"]) != (t0["w"], t0["h"], t0["fps"]) or inf["rate"] != t0["rate"]:
                L.append(
                    f"- {r['rush']} : {inf['w']}x{inf['h']} {_fps_txt(inf['fps'])} i/s mis à l'échelle en "
                    f"{t0['w']}x{t0['h']} {_fps_txt(t0['fps'])} i/s (son {inf['rate']} Hz vers {t0['rate']} Hz)"
                )
        L.append("")
    L += ["## Mots dans un fondu, à écouter", ""]
    mf = mots_dans_fondu(root, runs)
    L += [f"- {x}" for x in mf] if mf else ["aucun"]
    if not audio:
        L += ["", "Timeline : coupes franches, les fondus ne sont que dans le .mp4"]
    L.append("")
    open(os.path.join(dossier(root, nom), "cuts.md"), "w").write("\n".join(L))


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
        elif cmd == "placer":
            stem, debut, fin = rest[0], float(rest[1]), float(rest[2])
            p = charger(root, nom)
            if stem not in p["rushs"]:
                raise ErreurProjet(f"rush inconnu : {stem}")
            ms = mots(root, stem)
            bloc = {"rush": stem, "debut": caler(debut, ms), "fin": caler(fin, ms)}
            prop = calculer_proposition(root, p, bloc)
            ajouter_proposition(root, nom, prop)
            print(json.dumps(prop, ensure_ascii=False))
        elif cmd == "accepter":
            accepter(root, nom, int(rest[0]))
        elif cmd == "refuser":
            refuser(root, nom, int(rest[0]))
        elif cmd == "render":
            print(rendre(root, nom))
        elif cmd == "a-rendre":
            for x in a_rendre(root, nom):
                print(x)
        elif cmd == "resume":
            print(json.dumps(resume(root, nom)))
        elif cmd == "op":
            try:
                op = json.loads(rest[0])
            except (IndexError, ValueError):
                raise ErreurProjet("op : un objet JSON est attendu") from None
            print(json.dumps(operer(root, nom, op)["sequence"]))
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
