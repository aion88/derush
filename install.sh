#!/usr/bin/env bash
# install.sh : un seul installateur, idempotent.
#   ./install.sh               installe ce qui manque
#   ./install.sh --check       ne change rien, rapporte (exit 1 s'il manque quelque chose)
#   ./install.sh --models      télécharge aussi Qwen3-ASR-1.7B (4,4 Go) et whisper large-v3-turbo
#   ./install.sh --at-login    LaunchAgent : le studio démarre à l'ouverture de session (sans navigateur)
# Chaque ligne : OK <quoi> | INSTALLÉ <quoi> | MANQUE <quoi> → <commande>
# Variables de test : DERUSH_APP_DIR (dossier de Derush.app), DERUSH_NO_LAUNCHCTL=1 (écrit le plist, ne le charge pas).
set -uo pipefail
ROOT="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
CHECK=0 MODELS=0 ATLOGIN=0
for a in "$@"; do case "$a" in
  --check) CHECK=1;; --models) MODELS=1;; --at-login) ATLOGIN=1;;
  -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "option inconnue : $a" >&2; exit 2;; esac; done

MISSING=0
ok()  { echo "OK $*"; }
did() { echo "INSTALLÉ $*"; }
miss() { echo "MANQUE $1 → $2"; MISSING=1; }
ORIGINAL_PATH="$PATH"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

DERUSH_VENV="${DERUSH_VENV:-$HOME/.local/share/derush/venv}"
DERUSH_PY="$DERUSH_VENV/bin/python"
PKGS="torch torchaudio numpy soundfile qwen-asr openai-whisper"
BREW_ONELINER='/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'

# 1. macOS, Apple Silicon
if [ "$(uname -s)" != Darwin ]; then miss "macOS" "derush ne tourne que sur macOS"; exit 1; fi
if [ "$(uname -m)" = arm64 ]; then ok "macOS Apple Silicon"
else echo "ATTENTION Mac Intel : Qwen tournera sur CPU, plus lent. On continue."; fi

# 2. ffmpeg
if command -v ffmpeg >/dev/null 2>&1; then ok "ffmpeg"
elif command -v brew >/dev/null 2>&1; then
  if [ $CHECK = 1 ]; then miss "ffmpeg" "brew install ffmpeg"
  elif brew install ffmpeg >&2; then did "ffmpeg (brew)"; else miss "ffmpeg" "brew install ffmpeg"; fi
else miss "ffmpeg (et Homebrew)" "$BREW_ONELINER  puis  brew install ffmpeg"; fi

# 3. uv
if command -v uv >/dev/null 2>&1; then ok "uv"
elif [ $CHECK = 1 ]; then miss "uv" "curl -LsSf https://astral.sh/uv/install.sh | sh"
elif curl -LsSf https://astral.sh/uv/install.sh | sh >&2 && command -v uv >/dev/null 2>&1; then did "uv"
else miss "uv" "curl -LsSf https://astral.sh/uv/install.sh | sh"; fi

# 4. venv + paquets (~2 à 3 Go avec torch)
pkgs_ok() { [ -x "$DERUSH_PY" ] && "$DERUSH_PY" -I -c '
from importlib.metadata import version
import sys
for p in sys.argv[1:]: version(p)' $PKGS >/dev/null 2>&1; }
if pkgs_ok; then ok "venv $DERUSH_VENV ($PKGS)"
elif [ $CHECK = 1 ]; then miss "venv et paquets Python" "./install.sh"
elif ! command -v uv >/dev/null 2>&1; then miss "venv et paquets Python" "installer uv d'abord"
else
  if { [ -x "$DERUSH_PY" ] || uv venv --python 3.12 "$DERUSH_VENV" >&2; } \
     && uv pip install --python "$DERUSH_PY" $PKGS >&2 && pkgs_ok; then did "venv $DERUSH_VENV"
  else miss "venv et paquets Python" "uv venv --python 3.12 \"$DERUSH_VENV\" && uv pip install --python \"$DERUSH_PY\" $PKGS"; fi
fi

# 5. liens : derush dans ~/.local/bin, la skill dans ~/.claude/skills
link() { # target linkpath what
  local t="$1" l="$2" w="$3"
  if [ -L "$l" ] && [ "$(readlink "$l")" = "$t" ]; then ok "$w"
  elif [ -e "$l" ] || [ -L "$l" ]; then miss "$w : $l existe déjà, pas touché" "rm -rf \"$l\" && ./install.sh"
  elif [ $CHECK = 1 ]; then miss "$w" "./install.sh"
  elif mkdir -p "$(dirname "$l")" && ln -s "$t" "$l"; then did "$w"
  else miss "$w" "ln -s \"$t\" \"$l\""; fi
}
link "$ROOT/bin/derush" "$HOME/.local/bin/derush" "lien ~/.local/bin/derush"
if ! printf '%s' "$ORIGINAL_PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
  echo "ATTENTION ~/.local/bin n'est pas dans ton PATH : ajoute  export PATH=\"\$HOME/.local/bin:\$PATH\"  à ~/.zshrc"
fi
if [ -d "$HOME/.claude" ]; then link "$ROOT/skill" "$HOME/.claude/skills/derush" "skill ~/.claude/skills/derush"
else ok "skill Claude Code (pas de ~/.claude, ignorée)"; fi

# 6. configuration par défaut, jamais écrasée
CFG="$HOME/.config/derush/config"
if [ -f "$CFG" ]; then ok "config $CFG"
elif [ $CHECK = 1 ]; then miss "config $CFG" "./install.sh"
else
  mkdir -p "$(dirname "$CFG")" && cat > "$CFG" <<'CFGEOF'
# derush : KEY=value (shell). Une variable d'environnement l'emporte sur ce fichier.
# La clé OpenAI n'est jamais ici : `derush config openai-key` (trousseau) ou OPENAI_API_KEY.
#DERUSH_OUT_ROOT=~/Movies/Derush
#DERUSH_LOOK=
#DERUSH_LLM=
#DERUSH_OPENAI_MODEL=gpt-4o-mini
#DERUSH_ASR=qwen
#DERUSH_EDIT_PORT=8790
CFGEOF
  [ -f "$CFG" ] && did "config $CFG" || miss "config $CFG" "mkdir -p ~/.config/derush"
fi

# 7. Derush.app, construite ici (pas téléchargée : pas de quarantaine Gatekeeper)
if [ -n "${DERUSH_APP_DIR:-}" ]; then APPDIRS=("$DERUSH_APP_DIR")
else APPDIRS=(/Applications "$HOME/Applications"); fi
APP_FOUND=""
for d in "${APPDIRS[@]}"; do
  if [ -x "$d/Derush.app/Contents/MacOS/Derush" ] && grep -qF "$(printf '%q' "$ROOT")" "$d/Derush.app/Contents/MacOS/Derush"; then APP_FOUND="$d"; break; fi
done
if [ -n "$APP_FOUND" ]; then ok "Derush.app ($APP_FOUND)"
elif [ $CHECK = 1 ]; then miss "Derush.app" "./install.sh"
else
  built=""
  for d in "${APPDIRS[@]}"; do
    mkdir -p "$d" 2>/dev/null
    if [ -w "$d" ] && bash "$ROOT/app/build-app.sh" "$d" >/dev/null 2>&1; then built="$d"; break; fi
  done
  [ -n "$built" ] && did "Derush.app ($built)" || miss "Derush.app" "bash \"$ROOT/app/build-app.sh\" ~/Applications"
fi

# 8. modèles : à la première utilisation, sauf --models
if [ $MODELS = 1 ] && [ $CHECK = 0 ]; then
  if [ -x "$DERUSH_PY" ]; then
    if HF_HUB_DISABLE_IMPLICIT_TOKEN=1 "$DERUSH_PY" -c '
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-ASR-1.7B")
import whisper
whisper.load_model("large-v3-turbo")' >&2; then did "modèles Qwen3-ASR-1.7B et whisper large-v3-turbo"
    else miss "modèles" "./install.sh --models"; fi
  else miss "modèles" "installer le venv d'abord"; fi
else
  ok "modèles : téléchargés à la première utilisation (./install.sh --models pour les prendre maintenant)"
fi

# --at-login : LaunchAgent, le studio démarre à l'ouverture de session, sans ouvrir le navigateur
if [ $ATLOGIN = 1 ] && [ $CHECK = 0 ]; then
  PL="$HOME/Library/LaunchAgents/com.derush.studio.plist"
  mkdir -p "$(dirname "$PL")" "$HOME/Library/Logs/derush"
  cat > "$PL" <<PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.derush.studio</string>
<key>ProgramArguments</key><array><string>$ROOT/bin/derush</string><string>studio</string><string>--no-open</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><false/>
</dict></plist>
PLEOF
  if plutil -lint "$PL" >/dev/null 2>&1; then
    if [ "${DERUSH_NO_LAUNCHCTL:-}" = 1 ]; then did "LaunchAgent $PL (non chargé : DERUSH_NO_LAUNCHCTL=1)"
    else
      launchctl bootout "gui/$(id -u)/com.derush.studio" >/dev/null 2>&1
      launchctl bootstrap "gui/$(id -u)" "$PL" >/dev/null 2>&1 && did "LaunchAgent $PL" || miss "LaunchAgent" "launchctl bootstrap gui/$(id -u) \"$PL\""
    fi
  else miss "LaunchAgent (plist invalide)" "relancer ./install.sh --at-login"; fi
fi

exit $MISSING
