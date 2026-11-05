"""Modèle des projets : blocs, plages, coupe, insertion, création (sans média réel)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
DERUSH = os.path.join(os.path.dirname(HERE), "derush")
sys.path.insert(0, DERUSH)

import llm  # noqa: E402
import projet  # noqa: E402
from projet import ErreurProjet  # noqa: E402


def ecrire_rush(root, stem, mots, keep=None, silences=None, kind="video"):
    """mots = [(texte, début, fin)] ; une seule 'segment' suffit au modèle."""
    w = os.path.join(root, stem, "_work")
    os.makedirs(w, exist_ok=True)
    src = os.path.join(root, stem, stem + ".mov")
    open(src, "w").close()
    open(os.path.join(w, "source.txt"), "w").write(src + "\n")
    open(os.path.join(w, "kind"), "w").write(kind + "\n")
    words = [{"word": t, "start": s, "end": e} for t, s, e in mots]
    json.dump(
        {"segments": [{"text": " ".join(t for t, _, _ in mots), "words": words}]},
        open(os.path.join(w, "aligned.json"), "w"),
    )
    json.dump(
        {
            "filler_cuts": [
                {"start": a, "end": b, "kind": "silence"} for a, b in (silences or [])
            ]
        },
        open(os.path.join(w, "silence_cuts.json"), "w"),
    )
    if keep is not None:
        json.dump(
            [{"start": a, "end": b} for a, b in keep],
            open(os.path.join(root, stem, "keep.json"), "w"),
        )


def suite(t0, textes, pas=0.3, dur=0.25):
    """Construit des mots en chaîne : textes = [(mot, trou_avant)]."""
    out, t = [], t0
    for mot, trou in textes:
        t += trou
        out.append((mot, round(t, 3), round(t + dur, 3)))
        t += dur
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        # prise un : 3 paragraphes. Trous : 0.7 après « tous. », 1.3 après « début », 0.1 ailleurs
        m = suite(
            1.0,
            [
                ("Bonjour", 0),
                ("à", 0.1),
                ("tous.", 0.1),
                ("on", 0.7),
                ("commence", 0.1),
                ("par", 0.1),
                ("le", 0.1),
                ("début", 0.1),
                ("sans", 1.3),
                ("point", 0.1),
                ("ici", 0.1),
                ("puis", 0.1),
                ("fin.", 0.1),
            ],
        )
        self.m1 = m
        ecrire_rush(self.root, "prise un", m, keep=[(0.0, 100.0)])
        m2 = suite(
            2.0,
            [
                ("Les", 0),
                ("girafes", 0.1),
                ("dorment", 0.1),
                ("debout.", 0.1),
                ("Ensuite", 1.5),
                ("on", 0.1),
                ("coupe", 0.1),
                ("tout.", 0.1),
            ],
        )
        self.m2 = m2
        ecrire_rush(self.root, "P2", m2, keep=[(0.0, 100.0)])
        ecrire_rush(
            self.root,
            "memo",
            suite(1.0, [("a", 0), ("b", 0.1), ("c", 0.1)]),
            kind="audio",
        )

    def tearDown(self):
        self.tmp.cleanup()


class TestBlocs(Base):
    def test_blocs_ponctuation_et_silence(self):
        b = projet.blocs(self.root, "prise un")
        self.assertEqual(len(b), 3)
        # fin du 2e bloc = milieu du trou de 1.3 s (après « début »)
        fin_debut = self.m1[7][2]
        debut_sans = self.m1[8][1]
        self.assertAlmostEqual(b[1]["fin"], (fin_debut + debut_sans) / 2, places=3)
        self.assertAlmostEqual(b[2]["debut"], b[1]["fin"], places=3)

    def test_blocs_point_sans_silence_ne_coupe_pas(self):
        ecrire_rush(
            self.root,
            "Z",
            suite(
                1.0,
                [
                    ("Un", 0),
                    ("deux", 0.1),
                    ("trois.", 0.1),
                    ("quatre", 0.3),
                    ("cinq", 0.1),
                    ("six", 0.1),
                ],
            ),
        )
        self.assertEqual(len(projet.blocs(self.root, "Z")), 1)

    def test_bloc_trop_court_fusionne(self):
        ecrire_rush(
            self.root,
            "Y",
            suite(
                1.0,
                [
                    ("Un", 0),
                    ("deux", 0.1),
                    ("trois", 0.1),
                    ("quatre.", 0.1),
                    ("Oui", 1.0),
                    ("non.", 0.1),
                ],
            ),
        )
        b = projet.blocs(self.root, "Y")
        self.assertEqual(len(b), 1)
        self.assertEqual(len(projet.mots_du_bloc(self.root, b[0])), 6)

    def test_bornes_premier_dernier(self):
        b = projet.blocs(self.root, "prise un")
        self.assertAlmostEqual(b[0]["debut"], max(0, self.m1[0][1] - 0.25), places=3)
        self.assertAlmostEqual(b[-1]["fin"], self.m1[-1][2] + 0.25, places=3)

    def test_caler(self):
        ms = projet.mots(self.root, "prise un")
        m = ms[0]
        self.assertEqual(projet.caler(m["s"] + 0.01, ms), m["s"])
        self.assertEqual(projet.caler(m["e"] - 0.01, ms), m["e"])
        gap = (ms[0]["e"] + ms[1]["s"]) / 2
        self.assertEqual(projet.caler(gap, ms), gap)

    def test_plages_intersection(self):
        ecrire_rush(self.root, "K", self.m1, keep=[(0, 2), (3, 5)])
        self.assertEqual(
            projet.plages(self.root, {"rush": "K", "debut": 1.5, "fin": 4}),
            [(1.5, 2), (3, 4)],
        )
        ecrire_rush(self.root, "N", self.m1)  # pas de keep.json
        self.assertEqual(
            projet.plages(self.root, {"rush": "N", "debut": 1.5, "fin": 4}), [(1.5, 4)]
        )

    def test_mots_barres(self):
        m = suite(1.0, [("un", 0), ("deux", 0.2), ("trois", 0.2)])
        # « deux » : 1.45-1.70 ; keep s'arrête à 1.55 → moins de la moitié dedans
        ecrire_rush(self.root, "B", m, keep=[(0.0, 1.55)])
        mb = projet.mots_du_bloc(self.root, {"rush": "B", "debut": 0, "fin": 10})
        self.assertEqual([x["garde"] for x in mb], [True, False, False])

    def test_mots_gardes_sans_keep(self):
        ecrire_rush(self.root, "N", self.m1)
        mb = projet.mots_du_bloc(self.root, {"rush": "N", "debut": 0, "fin": 100})
        self.assertTrue(all(x["garde"] for x in mb))


class TestSequence(Base):
    def test_couper_inserer(self):
        a = projet.blocs(self.root, "prise un")
        b = projet.blocs(self.root, "P2")[0]
        ms = projet.mots(self.root, "prise un")
        # milieu du trou entre « on commence » (mots 3,4)
        t = (ms[4]["e"] + ms[5]["s"]) / 2
        seq = projet.couper(self.root, a, 1, t)
        self.assertEqual(len(seq), 4)
        seq = projet.inserer(seq, 1, b)
        self.assertEqual(
            [x["rush"] for x in seq],
            ["prise un", "prise un", "P2", "prise un", "prise un"],
        )
        self.assertAlmostEqual(seq[1]["fin"], t, places=3)
        self.assertAlmostEqual(seq[3]["debut"], t, places=3)
        # une coupe dans un mot tombe sur son bord
        t2 = ms[5]["s"] + 0.01
        seq2 = projet.couper(self.root, a, 1, t2)
        self.assertEqual(seq2[1]["fin"], ms[5]["s"])
        # avant le premier mot du bloc : refusé
        with self.assertRaises(ErreurProjet) as c:
            projet.couper(self.root, a, 1, a[1]["debut"] + 0.001)
        self.assertIn("coupe hors du bloc", str(c.exception))

    def test_inserer_debut(self):
        a = projet.blocs(self.root, "prise un")
        b = projet.blocs(self.root, "P2")[0]
        self.assertEqual(projet.inserer(a, -1, b)[0], b)

    def test_valider_refuse_rush_inconnu(self):
        p = {"rushs": ["prise un"]}
        with self.assertRaises(ErreurProjet):
            projet.valider(self.root, p, [{"rush": "zzz", "debut": 0, "fin": 1}])

    def test_valider_cale_les_bornes(self):
        p = {"rushs": ["prise un"]}
        ms = projet.mots(self.root, "prise un")
        out = projet.valider(
            self.root, p, [{"rush": "prise un", "debut": ms[0]["s"] + 0.01, "fin": 5}]
        )
        self.assertEqual(out[0]["debut"], ms[0]["s"])

    def test_libres(self):
        p = projet.nouveau(self.root, "demo", ["prise un", "P2"])
        # P2 : 2 blocs ; on insère la moitié du premier
        b2 = projet.blocs(self.root, "P2")
        ms = projet.mots(self.root, "P2")
        t = (ms[1]["e"] + ms[2]["s"]) / 2
        moitie = projet.couper(self.root, [b2[0]], 0, t)
        p["sequence"] = projet.inserer(p["sequence"], 0, moitie[0])
        lib = projet.libres(self.root, p)
        self.assertEqual(lib["prise un"], [])
        self.assertEqual(len(lib["P2"]), 2)
        self.assertAlmostEqual(lib["P2"][0]["debut"], t, places=3)
        self.assertEqual(lib["P2"][1], b2[1])


class TestProjet(Base):
    def test_nouveau_et_existant(self):
        p = projet.nouveau(self.root, "demo", ["prise un", "P2"])
        self.assertEqual(p["rushs"], ["prise un", "P2"])
        self.assertEqual(p["sequence"], projet.blocs(self.root, "prise un"))
        f = os.path.join(self.root, "_projets", "demo", "projet.json")
        avant = open(f).read()
        with self.assertRaises(ErreurProjet) as c:
            projet.nouveau(self.root, "demo", ["P2"])
        self.assertIn("existe déjà", str(c.exception))
        self.assertEqual(open(f).read(), avant)
        self.assertEqual(projet.charger(self.root, "demo"), p)

    def test_ajouter(self):
        projet.nouveau(self.root, "demo", ["prise un"])
        p = projet.ajouter(self.root, "demo", "P2")
        self.assertEqual(p["rushs"], ["prise un", "P2"])
        self.assertEqual(
            projet.ajouter(self.root, "demo", "P2")["rushs"], ["prise un", "P2"]
        )
        with self.assertRaises(ErreurProjet):
            projet.ajouter(self.root, "demo", "memo")
        with self.assertRaises(ErreurProjet) as c:
            projet.ajouter(self.root, "demo", "_projets")
        self.assertIn("rush inconnu", str(c.exception))

    def test_nom_invalide(self):
        for nom in ("a b", "../x", ""):
            with self.assertRaises(ErreurProjet) as c:
                projet.nouveau(self.root, nom, [])
            self.assertIn("nom de projet invalide", str(c.exception))

    def test_melange_refuse(self):
        with self.assertRaises(ErreurProjet) as c:
            projet.nouveau(self.root, "m", ["prise un", "memo"])
        self.assertIn("ne mélange pas audio seul et vidéo", str(c.exception))
        self.assertIn("memo est un audio, le projet est en vidéo", str(c.exception))

    def test_aucune_copie_media(self):
        projet.nouveau(self.root, "demo", ["prise un", "P2"])
        self.assertEqual(
            os.listdir(os.path.join(self.root, "_projets", "demo")), ["projet.json"]
        )

    def test_rush_introuvable(self):
        os.remove(os.path.join(self.root, "P2", "P2.mov"))
        with self.assertRaises(ErreurProjet) as c:
            projet.rush(self.root, "P2")
        self.assertIn("rush introuvable : P2", str(c.exception))

    def test_cli_erreur_sans_traceback(self):
        r = subprocess.run(
            [
                sys.executable,
                "-I",
                os.path.join(DERUSH, "projet.py"),
                "new",
                self.root,
                "a b",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("nom de projet invalide", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_montrer(self):
        py = [sys.executable, "-I", os.path.join(DERUSH, "projet.py")]
        subprocess.run(py + ["new", self.root, "demo", "prise un"], check=True)
        out = subprocess.run(
            py + ["montrer", self.root, "demo"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(len(out.strip().splitlines()), 3)
        self.assertTrue(out.splitlines()[0].startswith("prise un\t"))
        k = subprocess.run(
            py + ["kind", self.root, "demo"], capture_output=True, text=True, check=True
        ).stdout
        self.assertEqual(k.strip(), "video")


if __name__ == "__main__":
    unittest.main()
