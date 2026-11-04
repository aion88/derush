---
name: derush
description: "Dérusher une vidéo parlée (face caméra, vocal, screen rec) : couper les silences, les euh/hum/mmh, les bégaiements, les faux départs et les phrases reprises. Sortie = un MP4 monté propre, un export prêt à poster et le rapport des coupes, dans $DERUSH_OUT_ROOT/<IMG>/. FR/EN. Triggers: derush, dérushe, coupe les silences, enlève les euh, jump cut, nettoie ma vidéo, monte ma vidéo."
---

# derush

Montage « jump cut » automatique d'une prise parlée. Ne fait QUE la coupe et l'export : pas de
sous-titres, pas de note KB, pas de Telegram. Cette skill embarque ses propres scripts (fillers, prune, cut) et la rubrique de rétraction ci-dessous.

Les vidéos vivent dans `$DERUSH_OUT_ROOT/<STEM>/` (défaut `~/Movies/Derush`, voir `derush config show`).

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
                               # source entière, un bord tiré rend ce qui a été coupé (/sm-montage)
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
Rubrique : celle de ce fichier, avec ces cas du parlé spontané :

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
- Remplir la ligne `Sujet` de `cuts.md` et la ligne d'`INDEX.md`.

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
