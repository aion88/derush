"""Un seul endroit choisit le moteur LLM : commande perso, Claude Code, ou OpenAI."""

import json, os, shutil, subprocess, urllib.error, urllib.request


class NoLLM(Exception):
    pass


NO_LLM_MSG = "aucun LLM : installe Claude Code (claude) ou ajoute une clé OpenAI (derush config openai-key)"


def keychain():
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", "derush-openai",
                            "-a", os.environ.get("USER", ""), "-w"],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    k = r.stdout.strip()
    return k if r.returncode == 0 and k else None


def pick(env, which, keychain):
    if env.get("DERUSH_LLM"):
        return ("custom", env["DERUSH_LLM"])
    if which("claude"):
        return ("claude", None)
    key = env.get("OPENAI_API_KEY") or keychain()
    if key:
        return ("openai", key)
    return ("none", None)


def _openai(prompt, key):
    model = os.environ.get("DERUSH_OPENAI_MODEL") or "gpt-4o-mini"
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].replace(key, "***")
        raise RuntimeError(f"OpenAI HTTP {e.code} : {body}") from None


def complete(prompt):
    """Renvoie (texte, nom du moteur)."""
    engine, arg = pick(os.environ, shutil.which, keychain)
    if engine == "none":
        raise NoLLM(NO_LLM_MSG)
    if engine == "openai":
        return _openai(prompt, arg), "openai"
    argv = ["sh", "-c", arg] if engine == "custom" else ["claude", "-p", "--output-format", "text"]
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        raise RuntimeError(f"LLM en échec : {r.stderr.strip()[-400:]}")
    return r.stdout, engine
