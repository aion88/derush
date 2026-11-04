"""Montage serré proposé : un LLM lit le transcript gardé et propose des coupes (jamais appliquées seul).

Usage : python3 -I propose_cuts.py <dossier videos/STEM>   (lit stdin : {"keep_idx":[indices de mots gardés]})
Sortie stdout : {"proposals":[{"from":i,"to":j,"reason":"...","text":"..."}]}, indices = mots de aligned.json.
LLM : $DERUSH_LLM (commande, prompt sur stdin) sinon ~/bin/llm-fallback sinon `claude -p`.
"""

import json, os, re, shutil, subprocess, sys

OUT = os.path.abspath(sys.argv[1])
W = os.path.join(OUT, "_work")

RUBRIC = """Tu es monteur de vidéos face caméra pour Instagram et TikTok. Voici le transcript d'une prise,
mot par mot, chaque mot précédé de son numéro. Propose les coupes qui rendent la vidéo plus serrée
et plus claire, SANS changer l'ordre ni réécrire : on ne peut que retirer des mots.

Coupe :
- les redites : une idée déjà dite, garder la formulation la plus nette (souvent la dernière) ;
- les phrases commencées puis reprises, les reformulations qui remplacent ;
- les digressions et apartés qui font décrocher le spectateur ;
- les amorces et liants vides (« donc voilà », « en fait », « du coup », « ok alors ») quand ils ralentissent ;
- les longueurs : une explication qui peut perdre une proposition sans perdre son sens.
- une idée répétée à plusieurs endroits de la vidéo (pas seulement côte à côte) : garder la meilleure occurrence ;
- une réaction isolée qui ne porte rien (« oui », « ouais je sais », un mot lancé hors du fil) ;
- une anecdote ou un détail qui traîne après que son point est fait (« ça a commencé à midi ») ;
- une fin qui continue après la punchline : finir sur la phrase la plus forte ;
- les consignes de régie dites à la caméra (« on reprend », « enlève ça », « test, test ») ;
- les [blancs] : le derush y entend peut-être de la parole que la transcription n'a pas écrite.
  La plupart du temps c'est une hésitation, un souffle, ou un mot déjà transcrit juste avant ou après.
  Propose de les couper, sauf si ce qu'on y entend est une idée NEUVE qui manque au texte autour.

Ne coupe jamais :
- l'accroche du début, un fait, un chiffre, un argument ou un exemple qui n'existe qu'une fois ;
- l'humour, une punchline, une répétition d'insistance voulue ;
- un bout qui laisserait une phrase bancale : ce qui reste doit se lire d'une traite, avec une
  suite logique d'une phrase à l'autre.

Dans le doute, garde. Réponds UNIQUEMENT en JSON, sans texte autour :
{"proposals":[{"from":<numéro du premier mot coupé>,"to":<numéro du dernier mot coupé>,"reason":"<raison courte, en français>"}]}

Transcript :
"""


def llm(prompt):
    cmd = os.environ.get("DERUSH_LLM")
    if cmd:
        argv = ["sh", "-c", cmd]
    elif os.access(os.path.expanduser("~/bin/llm-fallback"), os.X_OK):
        argv = [
            os.path.expanduser("~/bin/llm-fallback"),
            "Suis les instructions du texte fourni.",
        ]
    elif shutil.which("claude"):
        argv = ["claude", "-p", "--output-format", "text"]
    else:
        sys.exit("aucun LLM : installe Claude Code (claude) ou définis DERUSH_LLM")
    r = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        sys.exit(f"LLM en échec : {r.stderr.strip()[-400:]}")
    return r.stdout


def main():
    a = json.load(open(os.path.join(W, "aligned.json")))
    ws = [w for s in a["segments"] for w in s.get("words", [])]
    words = [w["word"].strip() for w in ws]
    n = len(words)
    body = json.load(sys.stdin)
    gaps = [g for g in json.load(open(os.path.join(W, "gap_speech.json")))] if os.path.exists(os.path.join(W, "gap_speech.json")) else []
    # éléments gardés dans l'ordre du temps : mots (id = index aligné) + blancs à parole douteuse (id = n + k)
    items = [(ws[i]["start"], i, words[i]) for i in set(body["keep_idx"])]
    items += [(g["start"], n + k, f"[blanc, on y entend peut-être : « {g['heard']} »]")
              for k, g in enumerate(gaps) if n + k in set(body.get("gap_idx", []))]
    items.sort()
    order = {it[1]: pos for pos, it in enumerate(items)}
    lines, line = [], []
    for _, i, txt in items:
        line.append(f"{i}:{txt}")
        if re.search(r"[.!?»\]]$", txt) or len(line) >= 40:
            lines.append(" ".join(line))
            line = []
    if line:
        lines.append(" ".join(line))
    raw = llm(RUBRIC + "\n".join(lines))
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        sys.exit(f"réponse LLM illisible : {raw[:300]}")
    props = []
    for p in json.loads(m.group(0)).get("proposals", []):
        f, t = int(p["from"]), int(p["to"])
        if f not in order or t not in order or order[f] > order[t]:
            continue
        span = items[order[f]: order[t] + 1]
        props.append({"from": f, "to": t, "reason": str(p.get("reason", "")),
                      "text": " ".join(x[2] for x in span), "_a": order[f], "_b": order[t]})
    props.sort(key=lambda p: p["_a"])
    clean = []
    for p in props:  # pas de chevauchement
        if clean and p["_a"] <= clean[-1]["_b"]:
            continue
        clean.append(p)
    for p in clean:
        del p["_a"], p["_b"]
    res = {"proposals": clean}
    json.dump(res, open(os.path.join(W, "propositions.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
