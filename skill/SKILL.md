---
name: derush
description: "Dérusher une vidéo parlée (face caméra, vocal, screen rec) : couper les silences, les euh/hum/mmh, les bégaiements, les faux départs et les phrases reprises. Sortie = un MP4 monté propre, un export prêt à poster et le rapport des coupes, dans $DERUSH_OUT_ROOT/<IMG>/. FR/EN. Triggers: derush, dérushe, coupe les silences, enlève les euh, jump cut, nettoie ma vidéo, monte ma vidéo."
---

# derush

Montage « jump cut » automatique d'une prise parlée. Ne fait QUE la coupe et l'export : pas de
sous-titres. Cette skill embarque la rubrique de rétraction ci-dessous ; les scripts (fillers, prune, cut) sont dans le dépôt.

Les vidéos vivent dans `$DERUSH_OUT_ROOT/<STEM>/` (défaut `~/Movies/Derush`, voir `derush config show`).

Un audio seul (m4a, mp3, wav, aiff, caf) passe la même chaîne : le montage sort en `<STEM>.derush.m4a`, l'export en `<STEM>.export.m4a` (-14 LUFS) ; fcpxml, logos et look n'existent pas pour lui.

## Les trois commandes

```bash
derush prep "<video>"          # range la source dans $DERUSH_OUT_ROOT/<STEM>/, audio, silences, transcription (qwen),
                               # alignement, euh, trous, contrôle des trous. ~1.5x la durée
derush words <STEM>            # transcript mot à mot avec bornes : l'étape 6 se lit là-dessus
derush studio                  # TOUT dans le navigateur : déposer une vidéo brute, derush, montage par le
                               # texte, montage serré proposé, rendu. Parole dans un trou = gardée, barrable
derush edit <STEM>             # montage par le texte : page locale, barrer des mots (Suppr), rattraper un
                               # euh/silence (Entrée), Valider → retraction_cuts.json + restore.json
                               # « Proposer un montage serré » : Claude propose des coupes (redites,
                               # digressions, reprises), en orange, rien n'est coupé sans son OK
derush render <STEM>           # fusion + garde + coupe + retranscription de la sortie + cuts.md
derush logos <STEM>            # optionnel : logos.json → <STEM>.logos.mp4, export le prend s'il existe
derush fcpxml <STEM>           # <STEM>.fcpxml, écrit aussi par render : timeline Resolve, clips sur la
                               # source entière, un bord tiré rend ce qui a été coupé
derush export <STEM>           # <STEM>.reel.mp4 : 1080x1920, 30 fps, -14 LUFS, prêt à poster
```

Logos (`derush logos`) : `$DERUSH_OUT_ROOT/<STEM>/logos.json` = `{"cues":[{"logo":"canva","t":14.27}]}`, `t` lu
dans `derush words` (instant SOURCE, converti par `keep.json`). Fichiers dans `$DERUSH_OUT_ROOT/_logos/src/<logo>.svg|png`
(détourés, fond transparent ; sans fichier, carte texte). Carte blanche arrondie 30 % de largeur, en haut à
GAUCHE par défaut (face caméra : le visage occupe le tiers haut centré), 2 s, fondu 0,2 s ; une liste dite
vite range les cartes côte à côte. Contrôle : extraire une image par cue et la REGARDER. IMG_4596 (2026-10-11) :
Canva ×2, Microsoft 365, Gamma, Higgsfield (« Xfield » dans le transcript : lui demander les noms, whisper
n'en connaît pas la moitié).

`derush` = `bin/derush` du dépôt. Options de `prep` : `--lang en`,
`--noise -40` (voix faible), `--min 0.3 --pad 0.08` (plus serré), `--min 0.8 --pad 0.2` (plus posé).
Deux vidéos : lancer les `prep` à la suite en arrière-plan, lire les `words` pendant ce temps.

## Projets : plusieurs prises, un seul montage

Quand la vidéo tient en plusieurs prises (ou qu'un passage oublié est refait à part), chaque prise passe d'abord
`derush prep`, puis un projet les assemble : `derush projet new <nom> [STEM…]`, `derush projet add <nom> <STEM>`,
`derush projet render <nom>`, `derush projet export <nom>`. Sorties dans `$DERUSH_OUT_ROOT/_projets/<nom>/` :
`<nom>.derush.mp4`, `<nom>.reel.mp4`, `<nom>.fcpxml`, `cuts.md`. L'ordre et le placement d'une reprise se font dans
le studio (page projet, « Placer »), jamais appliqués sans clic. Fondu de 0,2 s entre deux prises.

## Ce qui est coupé, et qui décide

| Couche | Signal | Qui décide |
|---|---|---|
| Silences | waveform, `silencedetect` (pas les trous whisper, trop grossiers) | script |
| (prérequis) vraies bornes de mots | alignement forcé CTC sur le son (`align_words.py`) | script |
| euh / hum / hein écrits par whisper, bégaiements « je je », « et et » | timestamps mot (`detect_fillers.py`) | script |
| euh / mmh NON écrits (la majorité) | trou non silencieux entre 2 mots (`gap_fillers.py`) | script |
| faux départs, phrase reprise, « non attends », mot abandonné, consignes dites à la caméra | lecture du transcript | TOI, étape 6 |

Prime directive de la skill : **une coupe fausse de vrai contenu est la pire
faute.** Dans le doute, on garde, et on le dit dans `cuts.md` (« gardé exprès »).

## Étape 6, la seule à la main : les faux départs

Lis `derush words <STEM>` (mot@début-fin, `?` = borne interpolée, pas alignée) et écris
`$DERUSH_OUT_ROOT/<STEM>/retraction_cuts.json` = `{"retraction_cuts":[{start,end,cue_text,rationale}]}`.
Rubrique : « THE RETRACTION-DETECTION RUBRIC » plus bas dans ce fichier, avec ces cas du parlé spontané :

- **Faux départ** « je vais... on va voir » : couper « je vais » jusqu'au début de la reprise.
- **Mot reformulé** « c'est un truc, un outil qui » : couper le premier seulement si le second
  le REMPLACE (pas s'il précise).
- **Phrase reprise de zéro**, y compris après un aparté : couper la première tentative entière.
- **Consignes de régie dites à la caméra** (« on enlève ça », « pas dans mon micro, non »,
  « on garde ») : ce sont des instructions, pas du contenu. Les appliquer, puis les couper.
  IMG_4566 : les 40 dernières secondes étaient 3 faux départs et 2 consignes.
- **Ne pas couper** : répétition d'insistance (« toujours, toujours »), liste, « en fait » qui
  ajoute, pause expressive, autocorrection comique (« XXIe et XXIIe siècles. Non, du XXIe »).
- Bornes, lues dans `words` : `start` = milieu entre la fin du dernier mot gardé et le début du
  premier mot abandonné ; `end` = début du premier mot gardé − 0.04 s. Pour couper jusqu'à la
  fin : `end` = durée de la vidéo.

Pour un transcript long (> 1000 mots), déléguer la lecture à un sous-agent qui rend le JSON,
puis relire ses bornes contre `words`.

## Vérifier avant de rendre (re-dériver, pas reconnaître)

`render` fait les contrôles mécaniques et écrit `cuts.md`. Ce que TU relis :

- **La section diff de `cuts.md`** (transcript source → sortie). Chaque `delete` doit être
  une coupe voulue. Un `replace`/`insert` bizarre (« c'est c'est c'est ») est souvent une boucle
  de whisper : retranscrire la région seule avant d'accuser la coupe.
- **Un trou marqué PAROLE DANS LE TROU** par `gap_check` (fin de `prep`) : écouter la fenêtre.
  Si c'est un faux départ, la coupe est bonne. Si c'est du contenu, retirer ce trou de
  `_work/gap_cuts.json` avant `render`.
- **Un euh, un mmh CITÉ est du contenu.** « les silences, les mmh », « surtout sur les euh » :
  le mot est l'objet de la phrase, il reste. Après « les », « des », « un », « sur les » devant un
  euh/mmh/hum, écouter et retirer le trou qui le couvre. Ne jamais traiter « sur les » comme un
  faux départ : la phrase finit sur le euh. (2026-10-27, A001_10272011_C008.)
- **Transcription : Qwen3-ASR par défaut depuis le 2026-11-04** (`transcribe_qwen.py`, `DERUSH_ASR=whisper`
  pour revenir ; qwen absent ou en panne → whisper, dit dans le log). Qwen écrit les bégaiements et faux
  départs que whisper fond (C010 : « des des trucs », « j'aurais pas mes, j'aurais pas mes, tous mes »),
  donc ils apparaissent dans `derush words` et dans `derush edit`. Il n'écrit pas plus les euh :
  `gap_fillers.py` reste. Plus faible sur les noms propres (« claudito » → « claudio »).
- **Faux départ fondu par whisper** : whisper peut n'écrire qu'une fois une phrase dite deux
  fois. IMG_4543 : « je t'en mets… je vais mettre » transcrit « je vais mettre ». Une phrase qui
  sonne bancale à un raccord dans la sortie = retranscrire la source mot par mot à cet endroit.
- **Sigles, noms de domaine, chiffres** : CTC aligne mal les lettres épelées. IMG_4549 : le trou
  avant « SI » (SpaceX SI) portait le « ès ». Tout trou qui touche un sigle ou un `.com` :
  retranscrire la fenêtre, et ne pas le couper au moindre doute. Les tokens à chiffre (« 5h »,
  « J3 ») sont interpolés, jamais alignés.
- **Sync** : `cuts.md` donne l'écart A/V. Au-delà de 40 ms, regarder.
- Remplir la ligne `Sujet` de `cuts.md`.

## THE RETRACTION-DETECTION RUBRIC

You (the invoking agent) read `derush words <STEM>` and write this JSON to
`$DERUSH_OUT_ROOT/<STEM>/retraction_cuts.json`, the file `derush render` reads:

### Detector output contract

```json
{
  "retraction_cuts": [
    {
      "start": 6.4,
      "end": 9.8,
      "cue_text": "Scratch that",
      "rationale": "Reparandum 'runs every time the user opens a file' + cue 'Scratch that'; repair 'it actually runs on session start' is kept."
    }
  ]
}
```

- `start` = where the **abandoned thought (reparandum)** begins. SEMANTIC
  judgment; **it may fall mid-sentence**. Read the exact time off the word
  timestamps of `derush words` (see "Boundary anchoring" below). Times are in seconds
  of the SOURCE video.
- `end` = end of the **retraction cue (interregnum)**. The reparandum + cue are
  BOTH removed; the **repair that FOLLOWS is KEPT**. In practice `end` lands at
  the boundary where the corrected utterance begins.
- **Empty list `{"retraction_cuts": []}` when no genuine retraction.** Decoys
  and topic-shifts produce NO cut.

### The self-repair model (Levelt / Clark & Wasow)

```
[REPARANDUM] [INTERREGNUM/CUE] [REPAIR]
 abandoned        the cue        replacement
   CUT              CUT             KEEP
```

The cut = reparandum + cue. The repair is preserved.

### Positive test (cut) : ALL must hold

1. The speaker is **invalidating** prior content (negating, deleting, or judging
   it wrong/incoherent), AND
2. They **replace it or drop it** : a corrected version follows, or the thought
   is abandoned, AND
3. There is an actual **reparandum present in the transcript** to remove (a cue
   with no preceding speech to retract → NO cut; see edge case below).

### Negative tests (do NOT cut) : any one rejects the candidate

These superficially resemble cues but are not
retractions:

- **Time-qualified topic-shift** : "forget the budget _for a second/for now_",
  "oublie le budget _deux secondes_". The "for a second/for now" qualifier
  (often plus a later deferral like "we'll cover it next week") means the prior
  content is still VALID, just deferred. NO cut.
- **Additive escalation** : "en fait c'est encore mieux", "non mais attends,
  c'est encore plus puissant que ça". "en fait"/"non mais" here UPGRADE the
  prior claim; it still stands. NO cut.
- **Affirmation** : "non mais c'est exactement ça", "actually, that's a good
  point". The "non"/"actually" intensifies agreement, not correction. NO cut.
- **Procedural pause** : "attends, je te montre" / "wait, let me show you".
  Speech pauses for a demo; nothing is retracted. NO cut.
- **Nuance/scope refinement** : "c'est plus subtil que ça", "enfin, c'est un peu
  plus compliqué". The prior claim is qualified/extended, not discarded. NO cut.
- **Topic-closer** : "bref, c'est compliqué", "de toute façon". Closes a chain
  without invalidating it. NO cut. (`bref` is ambiguous : only a cut when it is
  followed by an actual abandonment like "bref, peu importe les critères".)

### How far back does the reparandum start?

The start boundary is a semantic judgment:

- **Ask what the speaker is replacing.** The reparandum begins where the
  abandoned idea first diverged from the correct replacement.
- **Restart markers** ("je reprends", "let me start over", "non attends je
  recommence") → **wider** reparandum: back to the start of the redone stretch.
- **Correction pivots** ("non en fait", "actually no", "wait no") → **narrow**
  reparandum: just the immediately preceding predicate/clause.
- **Natural topic boundary rule** : never cut past a different subject. A valid
  shared topic-introduction that both the wrong and correct versions build on is
  KEPT (e.g. a "for the sound installation project…" intro stays; only the wrong
  technical claim after it is cut).
- **SETUP vs ELABORATION test (keep the last still-true claim).** When a
  setup/intro CLAIM remains true and only a following ELABORATION, ENUMERATION,
  LIST, or DETAIL is abandoned, the reparandum starts at the **elaboration**, not
  the setup. The decisive question is: **"is the speaker negating THIS clause, or
  only what came after it?"** If the clause is still true after the repair, KEEP
  it; begin the cut at the first clause the repair invalidates.
  - "It uses four criteria: A, B, C, D. Anyway, never mind the criteria : what
    matters is X." → the setup "it uses four criteria" is still TRUE (it does use
    criteria); only the enumeration "A, B, C, D" is dropped. Cut starts at the
    enumeration, NOT at "it uses four criteria". Keeping the setup is mandatory :
    cutting it is a false cut of real content.
  - Contrast: if the speaker negates the setup itself ("it uses four criteria…
    actually no, it uses none, it's a flat rule"), then the setup IS the
    reparandum and the cut starts there. Read what the repair replaces.
- **Minimum-cut / conservatism** : when unsure how far back, prefer the
  NARROWER cut. Leaving a slightly imprecise prior clause is far better than
  cutting a correct sentence.
- **Multi-sentence reparanda**: when the abandoned thought spans several sentences or
  lines of `derush words`, the cut covers all of them.
- **Boundary anchoring: use the word timestamps, never arithmetic.** `derush words <STEM>`
  prints every word as `word@start-end` (`?` after a word = the bound is interpolated, not
  aligned on the sound; treat it as less exact). Anchor on those:
  1. **`start`** = the middle of the gap between the END of the last word you keep and the
     START of the first abandoned word.
  2. **`end`** = the START of the first word you keep (the repair head) minus 0.04 s. The
     reparandum and the cue are cut, the repair head is never touched. To cut up to the end
     of the video, `end` = the duration of the video.
  3. **Cue and repair head in the same sentence** (split by "mais", "c'est", "it's", a
     comma, a dash): end the cut at the last word of the cue, not later. Use the FIRST
     punctuation that follows the cue, never a later comma inside the repair clause. When
     the cue carries a trailing comma ("non attends,", "scratch that,"), the words after
     it are repair and are KEPT.
  4. **Reparandum at the tail of one line and the cue at the head of the next**: end the
     cut at the end of the reparandum rather than reaching forward to also grab the cue.
     A brief leftover cue ("non attends") is harmless; eating the repair head is the
     cardinal sin.
  5. **Interpolated bounds (`?`)**: round INWARD (see below). Start a touch LATER, end a
     touch EARLIER (about 0.1 to 0.3 s). Bias toward keeping content; cut less.

### Nested / double retraction : the emission rule

When a repair is **itself** retracted, emit **one cut per cue** (not one
widened cut). If a later retraction's reparandum overlaps a cut you already
emitted, **start the later cut at the previous cut's `end`**, not at its own
(already-removed) reparandum. `derush render` then merges the adjacent cuts for the
actual edit, but you emit them separately so each maps cleanly to its cue.

### Conservatism principle (the prime directive)

**FALSE CUTS OF REAL CONTENT ARE THE WORST FAILURE.** When you are genuinely
unsure whether something is a retraction, **DO NOT CUT.** A missed retraction
leaves a slightly messy clip; a false cut destroys correct content the speaker
meant to keep.

**CONSERVATIVE INTERPOLATION (corollary for boundaries).** The same bias governs
boundary placement under timestamp uncertainty: **round INWARD** :
start a touch LATER, end a touch EARLIER (about 0.1 to 0.3 s). Leaving a sliver of
cue/reparandum tail is harmless;
overshooting eats the repair head or pre-reparandum content = the cardinal sin.
When in doubt at a boundary, cut LESS.

The cost is asymmetric: a missed retraction costs a messy second, a false cut costs real
content. `derush render` checks that no kept word is clipped, but it cannot tell a retraction
from a real sentence: that call is yours.

## Ce que les scripts font, et pourquoi (mesuré)

- **Ne JAMAIS couper sur les timestamps bruts de whisper.** Ils dérivent de 0.1 à 0.4 s, fin de
  mot souvent trop tôt. IMG_4542 (2026-10-07) : « TikTok », « Instagram », « design system »
  rognés. Toute coupe se calcule sur `aligned.json` (torchaudio MMS_FA, modèle 1.2 Go en cache).
- **Le `initial_prompt` plein de « euh » est obligatoire** : sans lui whisper nettoie les
  hésitations et `detect_fillers` ne voit rien. Même avec, il en avale la majorité : elles ne
  restent que comme un TROU non silencieux entre deux mots, d'où `gap_fillers`.
- **`gap_check`** retranscrit chaque trou > 1 s que `silencedetect` ne couvre pas, et dit si le
  trou porte de la parole. Whisper hallucine des phrases entières sur 1 s de souffle : un débit
  > 4.5 mots/s ou un seul mot neuf = pas de la parole.
- **`check_clips`**, bloquante : aucun mot gardé ne doit être rogné, sauf par un silence
  acoustique (CTC étire parfois un mot court sur la pause voisine : « il » sur 3.7 s dans
  IMG_4566), une rétraction, ou une coupe de filler voulue. Exit 1 = rien n'est rendu.
- **Le seuil de silence (`--noise`, défaut -35 dB) est un PLAFOND, pas une valeur.** Après
  l'alignement, `word_peaks.py` mesure le pic de chaque mot et le plancher de la pièce ; si un mot
  pique sous le seuil, les silences sont recalculés à `min(pic) - 3 dB` (jamais sous plancher
  + 10). IMG_4594 (2026-10-11) : 110 mots sur 806 sous -35 dB, les apartés murmurés à 20-30 dB
  sous la voix (« courage avec ça », « c'est cool ça », « je prends mon compte de geek ») coupés
  ENTIERS, et `check_clips` vert parce que son exception « rogné par un silence » ne distinguait
  pas un mot étiré d'un mot avalé. Depuis : un mot dont RIEN ne survit dans `keep.json` est un
  mot avalé, garde rouge. IMG_4582 et IMG_4566, déjà montées, avaient 22 et 25 mots sous -35 dB.
- **`prune --min-keep 0.1`, pas plus** : un « ou » ou un « un » isolé dure 0.06 à 0.12 s.
- **La sortie est retranscrite** avec la même commande et diffée contre la source.
- **Un mot CTC long** (> 1.5 s) couvre une pause : la pause est quand même coupée par
  `silence_cuts`, et la retranscription de la sortie dit si le mot a survécu.
- whisper large-v3-turbo sur CPU : 6:47 d'audio en 1:46 le 2026-10-08. MPS crashe.
- Qwen3-ASR-1.7B sur MPS : 8:38 d'audio en 33 s (chargement compris), prep complet de C010 (1:11) en 29 s contre 40 s avec whisper, le 2026-11-04.
