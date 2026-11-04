# derush

derush cuts the dead weight out of talking-head videos on macOS: silences, "um" and "uh", stutters, false starts and sentences you repeated. You get an edited MP4, a ready-to-post vertical reel and a report of every cut. It works in French and English. You can also edit the cuts by hand in your browser, by striking words from the transcript.

Nothing leaves your machine except the optional "tight edit" suggestions (see below).

## Requirements

- macOS, with [Homebrew](https://brew.sh). Apple Silicon is the main target. Intel works too, but speech recognition runs on the CPU and is slower.
- About 7 GB of disk with the models (Qwen3-ASR is about 4.4 GB, whisper and the alignment model take the rest).

## Install

```bash
git clone https://github.com/aion88/derush && cd derush && ./install.sh
```

The installer is safe to run again. It builds a private Python environment, links `derush` into `~/.local/bin`, links the skill into `~/.claude/skills/derush` and builds `Derush.app`. It tells you what is missing and the exact command to fix it.

| Flag | What it does |
|---|---|
| `--check` | Changes nothing. Reports what is installed and what is missing (the exit code is the number of missing items, 0 when all is installed). |
| `--models` | Downloads the speech models now (otherwise they download on first use). |
| `--at-login` | Installs a LaunchAgent so the studio starts when you log in. |

If `~/.local/bin` is not in your PATH, the installer says so and gives the line to add to `~/.zshrc`.

## The app

Open `Derush.app` (in `/Applications` or `~/Applications`). It starts the studio and opens it in your browser. Drop a raw video in the page and everything follows: transcription, cuts, text editing, render.

Audio works too: give derush a voice memo or podcast take (m4a, mp3, wav, aiff, caf) and it cuts the same way; the output is `<STEM>.derush.m4a`, and export gives `<STEM>.export.m4a` at -14 LUFS (no timeline, logos or look).

Tip: pin the tab. The studio lives at http://127.0.0.1:8790 (the port is `DERUSH_EDIT_PORT`). The server keeps running after you close the browser, until you log out or run `derush stop`. With `./install.sh --at-login` it also comes back after a reboot, so the pinned tab always works.

## Commands

`<STEM>` is the name of the video folder inside `DERUSH_OUT_ROOT`. A path to a video also works everywhere.

| Command | What it does |
|---|---|
| `derush prep <video>` | Moves the source into its folder, then audio, silences, transcription, word alignment, fillers, gaps. Options: `--lang fr\|en`, `--noise -35`, `--min 0.45`, `--pad 0.12`. |
| `derush words <STEM>` | Word-by-word transcript with start and end times (used for false starts). |
| `derush align <audio16k.wav> <asr.json> --out <aligned.json>` | Word alignment on its own, without a STEM. |
| `derush config openai-key` | Stores your OpenAI key in the macOS Keychain (hidden input). |
| `derush config show` | Prints the resolved configuration. The key is never printed. |
| `derush studio [--no-open]` | The whole workflow in the browser. `--no-open` starts the server only. |
| `derush stop` | Stops the studio. |
| `derush edit <STEM>` | Text-based editing: strike words, save. |
| `derush render <STEM>` | Merges all cuts, checks that no kept word is clipped, cuts, writes `<STEM>.derush.mp4` and `cuts.md`. |
| `derush logos <STEM>` | Optional logo cards at the moments listed in `logos.json`. Options: `--x`, `--y`, `--width`. |
| `derush fcpxml <STEM>` | Writes the edit as a timeline for DaVinci Resolve (`render` does it too). |
| `derush export <STEM> [--from <file>]` | `<STEM>.reel.mp4`: 1080x1920, 30 fps, -14 LUFS, ready to post. `--from` takes an edit you retouched elsewhere. |
| `derush all <video>` | `prep`, `render`, `export` in one go, with no false-start pass (fast, less clean). |

## Tight edit (optional)

In the studio, "Proposer un montage serré" asks a language model to suggest more cuts (repeated points, digressions, restarts). Suggestions show in orange. Nothing is cut until you accept it.

derush picks the model in this order:

1. `DERUSH_LLM`, a command of your own, if you set it.
2. The `claude` command (Claude Code), if it is installed.
3. An OpenAI key: the `OPENAI_API_KEY` environment variable, or the key stored by `derush config openai-key`.

If none of the three exists, the studio tells you how to enable one. Without a model, everything else still works.

## Configuration

File: `~/.config/derush/config`, lines like `KEY=value`. Environment variables override the file. The installer never overwrites an existing file. The OpenAI key is never written there (it lives in the Keychain, service `derush-openai`).

| Key | Default | Meaning |
|---|---|---|
| `DERUSH_OUT_ROOT` | `~/Movies/Derush` | Where each video gets its folder. |
| `DERUSH_LOOK` | (none) | A `.cube` color look applied to previews. |
| `DERUSH_LLM` | (none) | Your own command for the tight edit. |
| `DERUSH_OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model for the tight edit. |
| `DERUSH_ASR` | `qwen` | Speech recognition: `qwen` or `whisper`. |
| `DERUSH_EDIT_PORT` | `8790` | Studio port. |
| `DERUSH_VENV` | `~/.local/share/derush/venv` | Where the Python environment lives. |
| `DERUSH_OPEN` | `open` | Command used to open the studio URL. |

Logs: `~/Library/Logs/derush/studio.log`.

## The skill

`skill/SKILL.md` teaches Claude Code the one manual step, finding false starts in the transcript, with a full rubric. The installer links it as `~/.claude/skills/derush`.

## Uninstall

Remove only these exact paths. Your videos in `DERUSH_OUT_ROOT` are not touched.

```bash
derush stop
launchctl bootout "gui/$(id -u)/com.derush.studio" 2>/dev/null   # only if you used --at-login
rm -f ~/Library/LaunchAgents/com.derush.studio.plist              # same
rm -f ~/.local/bin/derush
rm -f ~/.claude/skills/derush
rm -rf ~/.local/share/derush/venv   # or your DERUSH_VENV if you set one
rm -rf /Applications/Derush.app ~/Applications/Derush.app
rm -rf ~/.config/derush ~/Library/Logs/derush
```

Optional: `security delete-generic-password -s derush-openai` removes the stored OpenAI key. The downloaded models stay in the usual Hugging Face and torch caches; delete them there if you want the space back.

## License

MIT, copyright Cynthia Ortu. See `LICENSE`.

## En français

derush enlève le superflu des vidéos face caméra sur macOS : silences, « euh » et « hum », bégaiements, faux départs et phrases reprises. Il rend un MP4 monté, un reel vertical prêt à poster et le rapport de chaque coupe. FR et EN. On peut aussi retoucher les coupes à la main dans le navigateur, en barrant des mots du transcript. Rien ne quitte ta machine, sauf les suggestions optionnelles du « montage serré ».

### Prérequis

- macOS avec [Homebrew](https://brew.sh). Apple Silicon en priorité. Sur Intel ça marche, en plus lent (la reconnaissance vocale tourne sur le CPU).
- Environ 7 Go de disque avec les modèles (Qwen3-ASR pèse environ 4,4 Go).

### Installation

```bash
git clone https://github.com/aion88/derush && cd derush && ./install.sh
```

L'installeur peut être relancé sans risque. Il crée un environnement Python privé, relie `derush` dans `~/.local/bin`, relie la skill dans `~/.claude/skills/derush` et construit `Derush.app`. Il dit ce qui manque et la commande exacte pour le réparer.

- `--check` : ne change rien, rapporte ce qui manque.
- `--models` : télécharge les modèles tout de suite (sinon à la première utilisation).
- `--at-login` : le studio démarre à l'ouverture de session.

### L'app

Ouvre `Derush.app` (dans `/Applications` ou `~/Applications`). Elle lance le studio dans ton navigateur. Dépose une vidéo brute, le reste s'enchaîne : transcription, coupes, montage par le texte, rendu.

L'audio seul marche aussi (mémo vocal, podcast : m4a, mp3, wav, aiff, caf) : même coupe, sortie `<STEM>.derush.m4a`, export `<STEM>.export.m4a` à -14 LUFS (pas de timeline, de logos ni de look).

Astuce : épingle l'onglet. Le studio est sur http://127.0.0.1:8790 (port `DERUSH_EDIT_PORT`). Le serveur continue de tourner quand tu fermes le navigateur, jusqu'à la fermeture de session ou `derush stop`. Avec `./install.sh --at-login`, il revient aussi après un redémarrage.

### Commandes

Mêmes commandes que dans le tableau Commands, plus haut (en anglais). L'essentiel : `derush studio` pour tout faire dans le navigateur, `derush prep <video>` puis `derush render <STEM>` puis `derush export <STEM>` en ligne de commande, `derush stop` pour arrêter le studio. `derush config show` affiche la configuration.

### Montage serré (optionnel)

Dans le studio, « Proposer un montage serré » demande à un modèle de langage des coupes en plus (redites, digressions, reprises). Elles s'affichent en orange et rien n'est coupé sans ton accord. Le modèle est choisi dans cet ordre : ta commande `DERUSH_LLM`, puis la commande `claude` (Claude Code), puis une clé OpenAI (variable `OPENAI_API_KEY` ou `derush config openai-key`). Sans aucun des trois, le studio t'explique comment en activer un.

### Configuration

Fichier `~/.config/derush/config`, lignes `CLE=valeur`. L'environnement l'emporte sur le fichier. Clés : `DERUSH_OUT_ROOT` (défaut `~/Movies/Derush`), `DERUSH_LOOK`, `DERUSH_LLM`, `DERUSH_OPENAI_MODEL` (défaut `gpt-4o-mini`), `DERUSH_ASR` (`qwen` ou `whisper`), `DERUSH_EDIT_PORT` (défaut `8790`), `DERUSH_VENV` (défaut `~/.local/share/derush/venv`), `DERUSH_OPEN` (défaut `open`). La clé OpenAI n'est jamais écrite dans ce fichier : elle vit dans le trousseau.

### Désinstaller

Supprime uniquement ces chemins exacts (tes vidéos dans `DERUSH_OUT_ROOT` ne sont pas touchées) : le lien `~/.local/bin/derush`, le lien `~/.claude/skills/derush`, l'environnement `~/.local/share/derush/venv` (ou ton `DERUSH_VENV`), l'app `/Applications/Derush.app` ou `~/Applications/Derush.app`, la configuration `~/.config/derush`, les logs `~/Library/Logs/derush`, et si tu as utilisé `--at-login` le LaunchAgent `~/Library/LaunchAgents/com.derush.studio.plist` (après `launchctl bootout "gui/$(id -u)/com.derush.studio"`). Les commandes exactes sont dans la section Uninstall en anglais.

### Licence

MIT, copyright Cynthia Ortu.
