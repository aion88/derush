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


LLM_APRES = (
    'cat >/dev/null; echo "{\\"apres\\": %s, \\"couper_a_mot\\": %s, \\"raison\\": \\"suite logique\\"}"'
)


class Placement(Base):
    def setUp(self):
        super().setUp()
        # H : 4 paragraphes (trou 1.5 s entre eux)
        h = suite(
            1.0,
            [("le", 0), ("montage", 0.1), ("prend", 0.1), ("beaucoup", 0.1), ("de", 0.1),
             ("temps", 0.1), ("quand", 0.1), ("on", 0.1), ("filme", 0.1), ("seul.", 0.1),
             ("ensuite", 1.5), ("on", 0.1), ("coupe", 0.1), ("les", 0.1), ("silences.", 0.1),
             ("voilà", 1.5), ("c'est", 0.1), ("tout", 0.1), ("merci.", 0.1),
             ("fin", 1.5), ("de", 0.1), ("la", 0.1), ("prise.", 0.1)],
        )
        ecrire_rush(self.root, "H", h, keep=[(0.0, 100.0)])
        n = suite(
            1.0,
            [("alors", 0), ("le", 0.1), ("montage", 0.1), ("prend", 0.1), ("beaucoup", 0.1),
             ("de", 0.1), ("temps", 0.1), ("et", 0.1), ("il", 0.1), ("faut", 0.1), ("couper.", 0.1),
             ("merci", 1.5), ("à", 0.1), ("tous", 0.1), ("les", 0.1), ("amis.", 0.1)],
        )
        ecrire_rush(self.root, "N", n, keep=[(0.0, 100.0)])
        self.p = projet.nouveau(self.root, "demo", ["H", "N"])
        self.seq = self.p["sequence"]
        self.nb = projet.blocs(self.root, "N")

    def milieu(self, stem, i):
        """Milieu du trou entre le mot i-1 et le mot i du rush."""
        ms = projet.mots(self.root, stem)
        return (ms[i - 1]["e"] + ms[i]["s"]) / 2

    def llm(self, apres, coupe):
        return mock.patch.dict(os.environ, {"DERUSH_LLM": LLM_APRES % (apres, coupe)})

    def proposer(self, apres, coupe, bloc=None):
        with self.llm(apres, coupe):
            pr = projet.calculer_proposition(self.root, projet.charger(self.root, "demo"), bloc or self.nb[1])
        projet.ajouter_proposition(self.root, "demo", pr)
        return pr

    def test_normaliser(self):
        self.assertEqual(projet.normaliser("Montage,"), "montage")
        self.assertEqual(projet.normaliser("L'idée"), "l'idée")

    def test_cas_a_milieu(self):
        pr = projet.reprise(self.root, self.seq, self.nb[0])
        self.assertEqual(pr["cas"], "A")
        self.assertEqual(pr["apres"], 0)
        self.assertAlmostEqual(pr["couper_a"], self.milieu("H", 6), places=3)  # temps|quand
        self.assertAlmostEqual(pr["bloc"]["debut"], self.milieu("N", 7), places=3)  # temps|et
        self.assertAlmostEqual(pr["bloc"]["fin"], self.nb[0]["fin"], places=3)
        self.assertIn("reprend", pr["raison"])
        self.assertEqual(pr["hote"], self.seq[0])

    def test_cas_a_fin_de_bloc(self):
        ecrire_rush(self.root, "F", suite(1.0, [("oui", 0), ("quand", 0.1), ("on", 0.1), ("filme", 0.1), ("seul", 0.1), ("puis", 0.1), ("autre", 0.1), ("chose.", 0.1)]))
        bloc = projet.blocs(self.root, "F")[0]
        pr = projet.reprise(self.root, self.seq, bloc)
        self.assertEqual(pr["apres"], 0)
        self.assertIsNone(pr["couper_a"])

    def test_cas_a_trois_mots_ne_suffit_pas(self):
        ecrire_rush(self.root, "T", suite(1.0, [("alors", 0), ("prend", 0.1), ("beaucoup", 0.1), ("de", 0.1), ("choses", 0.1), ("très", 0.1), ("variées.", 0.1)]))
        self.assertIsNone(projet.reprise(self.root, self.seq, projet.blocs(self.root, "T")[0]))

    def test_cas_a_hors_huit_premiers_mots(self):
        def bloc(prefix):
            mm = [(f"f{i}", 0.1) for i in range(prefix)] + [("montage", 0.1), ("prend", 0.1), ("beaucoup", 0.1), ("de", 0.1), ("zzz", 0.1), ("yyy.", 0.1)]
            ecrire_rush(self.root, f"X{prefix}", suite(1.0, mm))
            return projet.blocs(self.root, f"X{prefix}")[0]
        # doublon aux indices 4..7 : trouvé ; 5..8 : pas dans les 8 premiers mots
        self.assertIsNotNone(projet.reprise(self.root, self.seq, bloc(4)))
        self.assertIsNone(projet.reprise(self.root, self.seq, bloc(5)))

    def test_cas_a_casse_ponctuation(self):
        ecrire_rush(self.root, "C", suite(1.0, [("Alors,", 0), ("Le", 0.1), ("montage,", 0.1), ("prend", 0.1), ("beaucoup;", 0.1), ("DE", 0.1), ("temps", 0.1), ("et", 0.1), ("voilà.", 0.1)]))
        pr = projet.reprise(self.root, self.seq, projet.blocs(self.root, "C")[0])
        self.assertEqual(pr["cas"], "A")

    def test_cas_a_rien_de_neuf(self):
        ecrire_rush(self.root, "R", suite(1.0, [("le", 0), ("montage", 0.1), ("prend", 0.1), ("beaucoup", 0.1), ("de", 0.1), ("temps.", 0.1)]))
        with self.assertRaises(ErreurProjet) as c:
            projet.reprise(self.root, self.seq, projet.blocs(self.root, "R")[0])
        self.assertIn("rien de neuf", str(c.exception))

    def test_cas_a_derniere_occurrence(self):
        # le passage existe dans 2 blocs de la séquence : on choisit le dernier
        seq = self.seq + [self.seq[0]]
        pr = projet.reprise(self.root, seq, self.nb[0])
        self.assertEqual(pr["apres"], len(seq) - 1)

    def test_cas_b_llm_simule(self):
        with self.llm(0, 2):
            pr = projet.calculer_proposition(self.root, self.p, self.nb[1])
        self.assertEqual(pr["cas"], "B")
        self.assertEqual(pr["apres"], 0)
        self.assertAlmostEqual(pr["couper_a"], self.milieu("H", 2), places=3)
        self.assertEqual(pr["hote"], self.seq[0])
        p = projet.ajouter_proposition(self.root, "demo", pr)
        self.assertEqual(p["sequence"], self.seq)
        self.assertEqual(len(projet.charger(self.root, "demo")["propositions"]), 1)

    def test_cas_b_reponse_hors_sequence(self):
        for apres, coupe in ((99, "null"), (0, 99), (0, 0), (-1, 3)):
            with self.llm(apres, coupe):
                with self.assertRaises(ErreurProjet) as c:
                    projet.calculer_proposition(self.root, self.p, self.nb[1])
            self.assertIn("réponse LLM hors séquence", str(c.exception))
        self.assertEqual(projet.charger(self.root, "demo")["propositions"], [])

    def test_cas_b_reponse_illisible(self):
        with mock.patch.dict(os.environ, {"DERUSH_LLM": "cat >/dev/null; echo pas du json"}):
            with self.assertRaises(ErreurProjet):
                projet.calculer_proposition(self.root, self.p, self.nb[1])

    def test_cas_b_sans_llm(self):
        env = {k: v for k, v in os.environ.items() if k != "DERUSH_LLM"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("llm.pick", return_value=("none", None)):
            with self.assertRaises(ErreurProjet) as c:
                projet.calculer_proposition(self.root, self.p, self.nb[1])
        self.assertEqual(str(c.exception), llm.NO_LLM_MSG)

    def test_accepter_coupe_et_insere(self):
        self.proposer(0, 2)
        avant = len(self.seq)
        p = projet.accepter(self.root, "demo", 0)
        self.assertEqual(len(p["sequence"]), avant + 2)
        self.assertEqual([b["rush"] for b in p["sequence"][:3]], ["H", "N", "H"])
        self.assertEqual(p["sequence"][1], self.nb[1])
        self.assertEqual(p["propositions"], [])
        self.assertEqual(projet.charger(self.root, "demo"), p)

    def test_accepter_cas_a_retire_le_doublon(self):
        with mock.patch.dict(os.environ, {}):
            pr = projet.calculer_proposition(self.root, self.p, self.nb[0])
        projet.ajouter_proposition(self.root, "demo", pr)
        p = projet.accepter(self.root, "demo", 0)
        texte = projet._texte(self.root, p["sequence"][1])
        self.assertTrue(texte.startswith("et il faut"), texte)

    def test_refuser(self):
        self.proposer(0, 2)
        p = projet.refuser(self.root, "demo", 0)
        self.assertEqual(p["propositions"], [])
        self.assertEqual(p["sequence"], self.seq)

    def test_accepter_inconnue(self):
        with self.assertRaises(ErreurProjet):
            projet.accepter(self.root, "demo", 3)

    def perimee(self, k=0):
        avant = projet.charger(self.root, "demo")
        with self.assertRaises(ErreurProjet) as c:
            projet.accepter(self.root, "demo", k)
        self.assertIn("proposition périmée", str(c.exception))
        self.assertEqual(projet.charger(self.root, "demo"), avant)

    def test_accepter_perimee(self):
        self.proposer(0, 2)
        p = projet.charger(self.root, "demo")
        p["sequence"] = p["sequence"][1:]
        projet.ecrire(self.root, "demo", p)
        self.perimee()

    def test_perimee_sans_coupe_reordonne(self):
        self.proposer(1, "null")
        p = projet.charger(self.root, "demo")
        s = p["sequence"]
        p["sequence"] = [s[0], s[2], s[1]] + s[3:]
        projet.ecrire(self.root, "demo", p)
        self.perimee()

    def test_perimee_bloc_precedent_retire(self):
        self.proposer(2, "null")
        p = projet.charger(self.root, "demo")
        p["sequence"] = p["sequence"][1:]
        projet.ecrire(self.root, "demo", p)
        self.perimee()

    def test_perimee_debut(self):
        self.proposer(-1, "null")
        self.assertEqual(projet.charger(self.root, "demo")["propositions"][0]["hote"], self.seq[0])
        p = projet.charger(self.root, "demo")
        s = p["sequence"]
        p["sequence"] = [s[3]] + s[:3]
        projet.ecrire(self.root, "demo", p)
        self.perimee()
        p["sequence"] = s
        projet.ecrire(self.root, "demo", p)
        r = projet.accepter(self.root, "demo", 0)
        self.assertEqual(r["sequence"][0], self.nb[1])

    def test_valider_reordonne_et_raccourci(self):
        p = projet.charger(self.root, "demo")
        s = p["sequence"]
        neuf = projet.valider(self.root, p, [s[2], s[0], s[3]])
        p["sequence"] = neuf
        projet.ecrire(self.root, "demo", p)
        self.assertEqual(projet.charger(self.root, "demo")["sequence"], neuf)

    def test_cli_placer_accepter_refuser(self):
        py = [sys.executable, "-I", os.path.join(DERUSH, "projet.py")]
        nb = self.nb[0]
        out = subprocess.run(py + ["placer", self.root, "demo", "N", str(nb["debut"]), str(nb["fin"])], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out)["cas"], "A")
        self.assertEqual(len(projet.charger(self.root, "demo")["propositions"]), 1)
        self.assertEqual(len(projet.charger(self.root, "demo")["sequence"]), 4)
        subprocess.run(py + ["accepter", self.root, "demo", "0"], check=True)
        self.assertEqual(len(projet.charger(self.root, "demo")["sequence"]), 6)
        r = subprocess.run(py + ["refuser", self.root, "demo", "0"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)


class Rendu(Base):
    """Plan de rendu, garde, marge de fondu."""

    def setUp(self):
        super().setUp()
        # M : « un deux trois » finit à L_E ; un mot « quatre » 0.15 s après (même paragraphe)
        self.m = suite(1.0, [("un", 0), ("deux", 0.1), ("trois", 0.1), ("quatre", 0.15), ("cinq", 0.1), ("six.", 0.1),
                              ("sept", 1.5), ("huit", 0.1), ("neuf.", 0.1)])
        self.le = self.m[2][2]  # fin de « trois »

    def seq(self, *blocs):
        return {"nom": "d", "rushs": ["prise un", "P2", "M"], "sequence": list(blocs), "propositions": []}

    def test_plan_runs(self):
        a = projet.blocs(self.root, "prise un")
        b = projet.blocs(self.root, "P2")
        p = self.seq(a[0], a[1], b[0], a[2])
        runs, vides = projet.plan_rendu(self.root, p)
        self.assertEqual([r["rush"] for r in runs], ["prise un", "P2", "prise un"])
        self.assertEqual(runs[0]["blocs"], [0, 1])
        self.assertEqual(vides, [])
        self.assertEqual(runs[0]["kind"], "video")
        self.assertTrue(runs[0]["source"].endswith("prise un.mov"))
        projet.ecrire(self.root, "d", p)
        r = projet.resume(self.root, "d")
        self.assertEqual((r["fondus"], r["blocs"], r["vides"]), (2, 4, 0))

    def test_plan_fusion_contigue(self):
        a = projet.blocs(self.root, "prise un")
        ms = projet.mots(self.root, "prise un")
        moitie = projet.couper(self.root, [a[1]], 0, (ms[5]["e"] + ms[6]["s"]) / 2)
        runs, _ = projet.plan_rendu(self.root, self.seq(*moitie))
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0]["plages"]), 1)

    def test_plan_bloc_vide(self):
        b = projet.blocs(self.root, "prise un")
        ecrire_rush(self.root, "Q", self.m1, keep=[(0, b[0]["fin"]), (b[1]["fin"], 100)])
        qb = projet.blocs(self.root, "Q")
        p = {"nom": "d", "rushs": ["Q"], "sequence": qb, "propositions": []}
        runs, vides = projet.plan_rendu(self.root, p)
        self.assertEqual(vides, [1])
        self.assertEqual(runs[0]["blocs"], [0, 2])
        self.assertEqual(len(runs[0]["plages"]), 2)

    def fond(self, keep, silences):
        ecrire_rush(self.root, "M", self.m, keep=keep, silences=silences)
        mb = projet.blocs(self.root, "M")
        pb = projet.blocs(self.root, "P2")
        p = self.seq(mb[0], pb[0])
        return p, projet.plan_rendu(self.root, p)[0]

    def test_marge_fondu_par_le_silence(self):
        # ici « quatre » est à 0.5 s de « trois » : le silence voisin laisse la place
        self.m = suite(1.0, [("un", 0), ("deux", 0.1), ("trois", 0.1), ("quatre", 0.5), ("cinq", 0.1), ("six.", 0.1),
                              ("sept", 1.5), ("huit", 0.1), ("neuf.", 0.1)])
        self.le = self.m[2][2]
        E = self.le + 0.05
        p, runs = self.fond([(0, E)], [(E, E + 1.0)])
        self.assertAlmostEqual(runs[0]["plages"][-1][1], self.le + 0.2, places=3)
        self.assertEqual(projet.mots_dans_fondu(self.root, runs), [])
        self.assertEqual(projet.garde_projet(self.root, p, runs), [])

    def test_marge_fondu_pas_sur_un_mot(self):
        E = self.le + 0.05
        quatre = self.m[3][1]
        p, runs = self.fond([(0, E)], [(E, E + 0.1)])
        self.assertLessEqual(runs[0]["plages"][-1][1], quatre + 1e-6)
        self.assertAlmostEqual(runs[0]["plages"][-1][1], quatre, places=3)
        self.assertTrue(any("trois" in x for x in projet.mots_dans_fondu(self.root, runs)))
        self.assertEqual(projet.garde_projet(self.root, p, runs), [])

    def test_marge_pas_hors_silence(self):
        E = self.le + 0.05
        _, runs = self.fond([(0, E)], [])
        self.assertAlmostEqual(runs[0]["plages"][-1][1], E, places=3)

    def test_marge_au_debut_du_run_suivant(self):
        # raccord M -> P2 -> M : le début de la 2e prise M est déjà dans un silence trop court
        ms = projet.mots(self.root, "prise un")
        S = ms[3]["s"] - 0.05  # « on » de la 2e phrase, 0.05 s après le bord du keep
        ecrire_rush(self.root, "prise un", self.m1, keep=[(S, 100)], silences=[(S - 1.0, S)])
        a = projet.blocs(self.root, "prise un")
        pb = projet.blocs(self.root, "P2")
        p = self.seq(pb[0], {"rush": "prise un", "debut": S - 0.5, "fin": a[1]["fin"]})
        runs, _ = projet.plan_rendu(self.root, p)
        self.assertAlmostEqual(runs[1]["plages"][0][0], ms[3]["s"] - 0.2, places=3)
        self.assertEqual(projet.garde_projet(self.root, p, runs), [])

    def test_garde_rouge_borne_dans_un_mot(self):
        ms = projet.mots(self.root, "prise un")
        milieu = (ms[1]["s"] + ms[1]["e"]) / 2
        p = self.seq({"rush": "prise un", "debut": milieu, "fin": ms[2]["e"] + 0.05})
        runs, _ = projet.plan_rendu(self.root, p)
        err = projet.garde_projet(self.root, p, runs)
        self.assertEqual(len(err), 1)
        self.assertIn("dans un mot", err[0])

    def mot_etire(self, silences):
        """Un mot étiré sur une pause (1.0-3.0 s) ; keep.json le coupe à 2.0 s (comme le rush rendu)."""
        ecrire_rush(self.root, "S", [("Il", 1.0, 3.0), ("faut", 3.1, 3.4), ("dire.", 3.5, 3.9)],
                    keep=[(0.0, 2.0), (3.0, 4.2)], silences=silences)
        p = {"nom": "d", "rushs": ["S"], "sequence": [{"rush": "S", "debut": 0.0, "fin": 4.2}], "propositions": []}
        runs, _ = projet.plan_rendu(self.root, p)
        return p, runs

    def test_garde_borne_dans_mot_etire_couvert_par_silence(self):
        # la partie coupée du mot (2.0-3.0) est du silence détecté : même règle que check_clips
        p, runs = self.mot_etire([(2.0, 3.0)])
        self.assertEqual(projet.garde_projet(self.root, p, runs), [])

    def test_garde_borne_dans_mot_sans_silence_reste_rouge(self):
        p, runs = self.mot_etire([])
        err = projet.garde_projet(self.root, p, runs)
        self.assertTrue(any("dans un mot" in e for e in err), err)

    def test_garde_rouge_plage_hors_keep(self):
        # une plage forcée hors de keep.json et hors silence : refusée
        ecrire_rush(self.root, "K", self.m1, keep=[(0, 2.0)])
        runs = [{"rush": "K", "source": "x", "kind": "video", "plages": [[1.0, 2.5]], "blocs": [0]}]
        p = {"nom": "d", "rushs": ["K"], "sequence": [{"rush": "K", "debut": 1.0, "fin": 2.5}], "propositions": []}
        err = projet.garde_projet(self.root, p, runs)
        self.assertTrue(any("hors du montage" in e for e in err), err)

    def test_run_trop_court(self):
        a = projet.blocs(self.root, "prise un")
        court = {"rush": "P2", "debut": 2.0, "fin": 2.3}
        p = self.seq(a[0], court, a[1])
        runs, _ = projet.plan_rendu(self.root, p)
        err = projet.garde_projet(self.root, p, runs)
        self.assertEqual(len(err), 1)
        self.assertIn("bloc trop court pour un fondu", err[0])
        self.assertIn("retire-le ou rallonge-le", err[0])

    def test_resume(self):
        a = projet.blocs(self.root, "prise un")
        b = projet.blocs(self.root, "P2")
        p = self.seq(a[0], b[0])
        projet.ecrire(self.root, "d", p)
        r = projet.resume(self.root, "d")
        attendu = sum(e - s for bl in (a[0], b[0]) for s, e in projet.plages(self.root, bl))
        self.assertAlmostEqual(r["total"], attendu, places=2)
        self.assertEqual((r["fondus"], r["blocs"], r["vides"]), (1, 2, 0))

    def test_rush_introuvable_au_plan(self):
        a = projet.blocs(self.root, "P2")
        os.remove(os.path.join(self.root, "P2", "P2.mov"))
        with self.assertRaises(ErreurProjet) as c:
            projet.plan_rendu(self.root, self.seq(a[0]))
        self.assertIn("rush introuvable : P2", str(c.exception))


class Revue(Base):
    """Corrections de la revue finale."""

    def test_nom_avec_saut_de_ligne_refuse(self):
        with self.assertRaises(ErreurProjet):
            projet.dossier(self.root, "demo\n")

    def hote_et_neuf(self):
        h = suite(1.0, [("le", 0), ("montage", 0.1), ("euh", 0.1), ("prend", 0.1), ("beaucoup", 0.1),
                         ("de", 0.1), ("temps", 0.1), ("quand", 0.1), ("on", 0.1), ("filme.", 0.1)])
        euh = h[2]
        ecrire_rush(self.root, "HS", h, keep=[(0.0, euh[1]), (euh[2], 100.0)])
        n = suite(1.0, [("alors", 0), ("le", 0.1), ("montage", 0.1), ("prend", 0.1), ("beaucoup", 0.1),
                         ("zzz", 0.1), ("yyy", 0.1), ("xxx", 0.1), ("voilà.", 0.1)])
        ecrire_rush(self.root, "NS", n, keep=[(0.0, 100.0)])
        return h, projet.blocs(self.root, "HS"), projet.blocs(self.root, "NS")[0]

    def test_cas_a_ignore_les_mots_barres_de_l_hote(self):
        h, seq, bloc = self.hote_et_neuf()
        pr = projet.reprise(self.root, seq, bloc)
        self.assertIsNotNone(pr)
        self.assertEqual(pr["cas"], "A")
        ms = projet.mots(self.root, "HS")
        # coupe juste après « beaucoup » (index 4 dans le texte brut, « euh » barré en 2) : trou beaucoup|de
        self.assertAlmostEqual(pr["couper_a"], (ms[4]["e"] + ms[5]["s"]) / 2, places=3)

    def test_accepter_refuse_un_passage_deja_dans_la_sequence(self):
        projet.nouveau(self.root, "demo", ["prise un", "P2"])
        p = projet.charger(self.root, "demo")
        b = projet.blocs(self.root, "P2")[1]
        prop = {"bloc": b, "apres": 0, "couper_a": None, "raison": "t", "cas": "B"}
        projet._avec_hote(p["sequence"], prop)
        projet.ajouter_proposition(self.root, "demo", prop)
        p = projet.charger(self.root, "demo")
        p["sequence"] = p["sequence"] + [b]  # glissé à la main après Placer
        projet.ecrire(self.root, "demo", p)
        avant = projet.charger(self.root, "demo")
        with self.assertRaises(ErreurProjet) as c:
            projet.accepter(self.root, "demo", 0)
        self.assertIn("déjà dans la séquence", str(c.exception))
        self.assertEqual(projet.charger(self.root, "demo"), avant)

    def test_verrou_serialise_les_ecritures(self):
        import threading, time as _t

        projet.nouveau(self.root, "demo", ["prise un"])
        fini = threading.Event()
        def ajoute():
            projet.ajouter(self.root, "demo", "P2"); fini.set()
        with projet.verrou(self.root, "demo"):
            th = threading.Thread(target=ajoute); th.start()
            _t.sleep(0.4)
            self.assertFalse(fini.is_set(), "ajouter ne doit pas passer pendant qu'on tient le verrou")
        th.join(5)
        self.assertTrue(fini.is_set())
        self.assertEqual(projet.charger(self.root, "demo")["rushs"], ["prise un", "P2"])

    def test_enregistrer_sequence(self):
        projet.nouveau(self.root, "demo", ["prise un"])
        seq = projet.blocs(self.root, "prise un")[:1]
        p = projet.enregistrer_sequence(self.root, "demo", seq)
        self.assertEqual(p["sequence"], projet.charger(self.root, "demo")["sequence"])
        with self.assertRaises(ErreurProjet):
            projet.enregistrer_sequence(self.root, "demo", [{"rush": "zzz", "debut": 0, "fin": 1}])


def ffm(args):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y"] + args, check=True)


class RenduReel(Base):
    """Rendu réel (ffmpeg) : garde de durée et sorties."""

    def rush_media(self, stem, size, fps, n, wd, pas, freq=440):
        """n mots de wd secondes tous les `pas` s, keep = un mot par plage. À 30 i/s, pas = 12 images et
        wd = 6,4 images : cut.sh arrondit chaque plage à 6 images, soit 0,4 image perdue à chaque plage."""
        m = [(f"m{i}.", round(0.5 + i * pas, 4), round(0.5 + i * pas + wd, 4)) for i in range(n)]
        dur = m[-1][2] + 0.5
        ecrire_rush(self.root, stem, m, keep=[(a, b) for _, a, b in m],
                    silences=[(m[i][2], m[i + 1][1]) for i in range(n - 1)])
        src = os.path.join(self.root, stem, stem + ".mov")
        ffm(["-f", "lavfi", "-i", f"color=c=blue:s={size}:r={fps}:d={dur}", "-f", "lavfi", "-i",
             f"sine=frequency={freq}:duration={dur}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", src])
        return m

    def projet_xyx(self, n=150):
        self.rush_media("RX", "180x320", 30, n, 0.21333, 0.4)
        self.rush_media("RY", "180x320", 30, 20, 0.21333, 0.4, 330)
        p = projet.nouveau(self.root, "gros", ["RX", "RY"])
        # un seul bloc par rush (pas de coupe de paragraphe) : la séquence est X (moitié), Y, X (reste)
        bx = projet.blocs(self.root, "RX")
        by = projet.blocs(self.root, "RY")
        ms = projet.mots(self.root, "RX")
        milieu = (ms[n // 2]["e"] + ms[n // 2 + 1]["s"]) / 2
        deux = projet.couper(self.root, bx, 0, milieu)
        p["sequence"] = [deux[0], by[0], deux[1]]
        projet.ecrire(self.root, "gros", p)
        return p

    def test_garde_de_duree_sur_beaucoup_de_plages(self):
        self.projet_xyx()
        # le fixture doit exercer le défaut : l'ancienne formule (plages brutes) s'écarte de plus de 0,25 s
        res = projet.resume(self.root, "gros")
        sortie = projet.rendre(self.root, "gros")
        reel = projet._sonde(sortie)["duree"]
        ancien = res["total"] - projet.FONDU * res["fondus"]
        self.assertGreater(abs(reel - ancien), 0.25, "le fixture ne reproduit pas l'arrondi image de cut.sh")

    def test_rendu_refuse_laisse_l_ancien_resultat(self):
        self.projet_xyx(30)
        d = projet.dossier(self.root, "gros")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "gros.derush.mp4")
        for f in ("gros.derush.mp4", "gros.fcpxml", "cuts.md"):
            open(os.path.join(d, f), "w").write("ANCIEN")
        with mock.patch("projet.duree_attendue", return_value=999.0):
            with self.assertRaises(ErreurProjet) as c:
                projet.rendre(self.root, "gros")
        self.assertIn("GARDE", str(c.exception))
        for f in ("gros.derush.mp4", "gros.fcpxml", "cuts.md"):
            self.assertEqual(open(os.path.join(d, f)).read(), "ANCIEN", f)
        self.assertEqual([x for x in os.listdir(os.path.join(d, "_work")) if x.startswith("run-")], [])

    def test_rendu_ne_relit_pas_projet_json(self):
        self.projet_xyx(30)
        with mock.patch("projet.resume", side_effect=AssertionError("relu")):
            projet.rendre(self.root, "gros")

    def test_format_du_premier_rush_pas_du_premier_bloc(self):
        self.rush_media("RX", "180x320", 30, 12, 0.21333, 0.4)
        self.rush_media("RY", "90x160", 25, 12, 0.21333, 0.4, 330)
        p = projet.nouveau(self.root, "fmt", ["RX", "RY"])
        p["sequence"] = [projet.blocs(self.root, "RY")[0], projet.blocs(self.root, "RX")[0]]
        projet.ecrire(self.root, "fmt", p)
        sortie = projet.rendre(self.root, "fmt")
        w = projet._sonde(sortie)
        self.assertEqual((w["w"], w["h"]), (180, 320))


if __name__ == "__main__":
    unittest.main()
