"""derush studio : déposer une vidéo brute, le derush tourne, montage par le texte, rendu. Tout dans le navigateur.

Usage : "$DERUSH_PY" -I edit_server.py <dossier des vidéos> <chemin de derush.sh> [--port 8790]
Pages : /  (accueil : déposer une vidéo, liste)   /edit?v=<STEM>  (montage par le texte)
Les tâches longues (prep, proxy, render) tournent en fond, une par vidéo, journal dans _work/job.log.
"""

import json, os, re, shutil, subprocess, sys, datetime, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

RUSHS = os.path.abspath(sys.argv[1])
DERUSH = os.path.abspath(sys.argv[2])
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8790
HERE = os.path.dirname(os.path.abspath(__file__))
TAG = "barré dans l'éditeur"
JOBS = {}  # stem -> {"proc", "kind", "log"}
STEPS = {
    "prep": "derush : silences, euh, transcription, alignement",
    "proxy": "version légère pour la page",
    "render": "montage final + vérification",
}


def load(p, default):
    try:
        return json.load(open(p))
    except FileNotFoundError:
        return default


def safe_stem(s):
    s = os.path.basename(s or "")
    if not s or s.startswith(".") or not os.path.isdir(os.path.join(RUSHS, s)):
        raise ValueError(f"vidéo inconnue : {s}")
    return s


def paths(stem):
    out = os.path.join(RUSHS, stem)
    return out, os.path.join(out, "_work")


def start_job(stem, kind, argv_chain):
    """argv_chain : liste de commandes enchaînées (&&). Une seule tâche à la fois par vidéo."""
    j = JOBS.get(stem)
    if j and j["proc"].poll() is None:
        return False
    out, w = paths(stem) if os.path.isdir(os.path.join(RUSHS, stem)) else (None, None)
    log = os.path.join(w, "job.log") if w else os.path.join(RUSHS, "_uploads", f"{stem}.job.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    cmd = " && ".join(" ".join(_q(a) for a in argv) for argv in argv_chain)
    env = dict(os.environ, DERUSH_OUT_ROOT=RUSHS)
    proc = subprocess.Popen(
        ["bash", "-c", cmd], stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env
    )
    JOBS[stem] = {"proc": proc, "kind": kind, "log": log}
    print(f"[derush studio] {stem} : {STEPS.get(kind, kind)}", flush=True)
    return True


def _q(a):
    return "'" + a.replace("'", "'\\''") + "'"


def job_state(stem):
    j = JOBS.get(stem)
    if not j:
        return {"running": False}
    rc = j["proc"].poll()
    try:
        tail = open(j["log"]).read().strip().splitlines()[-6:]
    except FileNotFoundError:
        tail = []
    return {
        "running": rc is None,
        "kind": j["kind"],
        "label": STEPS.get(j["kind"], j["kind"]),
        "ok": rc == 0,
        "error": rc not in (None, 0),
        "tail": tail,
    }


def video_state(stem):
    out, w = paths(stem)
    st = "brut"
    if os.path.exists(os.path.join(w, "aligned.json")):
        st = "prêt"
    if os.path.exists(os.path.join(out, f"{stem}.derush.mp4")):
        st = "monté"
    return {
        "stem": stem,
        "state": st,
        "proxy": os.path.exists(os.path.join(w, "proxy.mp4")),
        "mtime": os.path.getmtime(out),
        "job": job_state(stem),
    }


def videos():
    vs = []
    for d in os.listdir(RUSHS):
        if not d.startswith(("_", ".")) and os.path.exists(
            os.path.join(RUSHS, d, "_work", "source.txt")
        ):
            vs.append(video_state(d))
    for (
        stem
    ) in JOBS:  # upload en cours de prep : le dossier n'a pas encore de source.txt
        if not any(v["stem"] == stem for v in vs):
            vs.append(
                {
                    "stem": stem,
                    "state": "brut",
                    "proxy": False,
                    "mtime": 9e9,
                    "job": job_state(stem),
                }
            )
    return sorted(vs, key=lambda v: -v["mtime"])


def data(stem):
    out, w = paths(stem)
    a = json.load(open(os.path.join(w, "aligned.json")))
    words = [
        {
            "w": x["word"].strip(),
            "s": x["start"],
            "e": x["end"],
            "a": x.get("aligned", True),
            "seg": si,
        }
        for si, s in enumerate(a["segments"])
        for x in s.get("words", [])
    ]
    return {
        "stem": stem,
        "words": words,
        "keep": load(os.path.join(w, "keep.json"), []),
        "gaps": keep_speech_gaps(w),
        "auto": auto_cuts(w),
        "retraction_cuts": load(
            os.path.join(out, "retraction_cuts.json"), {"retraction_cuts": []}
        )["retraction_cuts"],
        "restore": load(os.path.join(out, "restore.json"), {"restore": []})["restore"],
        "rendered": os.path.exists(os.path.join(out, f"{stem}.derush.mp4")),
    }


def keep_speech_gaps(w):
    """Studio : un trou où gap_check entend de la parole n'est PAS coupé d'office (dans le doute, on garde).
    Il sort de gap_cuts.json et devient un bloc du texte (« entendu »), barrable comme un mot. Une fois."""
    done = os.path.join(w, "gap_speech.json")
    if os.path.exists(done):
        return load(done, [])
    speech = []
    try:
        for line in open(os.path.join(w, "gap_check.txt")):
            m = re.match(r"\s*([\d.]+)-\s*([\d.]+).*entendu : « (.*) » → PAROLE DANS LE TROU", line)
            if m:
                speech.append({"start": float(m.group(1)), "end": float(m.group(2)), "heard": m.group(3)})
    except FileNotFoundError:
        pass
    gp = os.path.join(w, "gap_cuts.json")
    if speech and os.path.exists(gp):
        g = json.load(open(gp))
        shutil.copy2(gp, os.path.join(w, "gap_cuts.avant-studio.json"))
        near = lambda c, x: abs(c["start"] - x["start"]) < 0.01 and abs(c["end"] - x["end"]) < 0.01
        g["filler_cuts"] = [c for c in g["filler_cuts"] if not any(near(c, x) for x in speech)]
        json.dump(g, open(gp, "w"), indent=1)
    json.dump(speech, open(done, "w"), ensure_ascii=False, indent=1)
    return speech


def auto_cuts(w):
    """Silences, euh, trous coupés par le derush auto (avant toute coupe de texte)."""
    c = load(os.path.join(w, "silence_cuts.json"), {"filler_cuts": []})["filler_cuts"]
    c += load(os.path.join(w, "gap_cuts.json"), {"filler_cuts": []})["filler_cuts"]
    c += load(os.path.join(w, "filler_cuts.json"), [])
    return sorted(({"start": x["start"], "end": x["end"]} for x in c), key=lambda x: x["start"])


def save(stem, body):
    out, w = paths(stem)
    bk = os.path.join(
        w, "edit-backups", datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    os.makedirs(bk, exist_ok=True)
    for f in ("retraction_cuts.json", "restore.json", "keep.json"):
        if os.path.exists(os.path.join(out, f)):
            shutil.copy2(os.path.join(out, f), bk)
    rc = sorted(
        (
            {
                "start": round(c["start"], 3),
                "end": round(c["end"], 3),
                "cue_text": c.get("cue_text", ""),
                "rationale": c.get("rationale") or TAG,
            }
            for c in body["retraction_cuts"]
            if c["end"] > c["start"]
        ),
        key=lambda c: c["start"],
    )
    json.dump(
        {"retraction_cuts": rc},
        open(os.path.join(out, "retraction_cuts.json"), "w"),
        ensure_ascii=False,
        indent=1,
    )
    json.dump(
        {"restore": body.get("restore", [])},
        open(os.path.join(out, "restore.json"), "w"),
        indent=1,
    )
    return {
        "ok": True,
        "cuts": len(rc),
        "restore": len(body.get("restore", [])),
        "backup": bk,
    }


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, payload):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, obj, code=200):
        self._send(
            code, "application/json", json.dumps(obj, ensure_ascii=False).encode()
        )

    def _route(self):
        u = urllib.parse.urlparse(self.path)
        return u.path, dict(urllib.parse.parse_qsl(u.query))

    def do_GET(self):
        path, q = self._route()
        try:
            if path in ("/", "/index.html"):
                return self._send(
                    200,
                    "text/html; charset=utf-8",
                    open(os.path.join(HERE, "home.html"), "rb").read(),
                )
            if path == "/edit":
                return self._send(
                    200,
                    "text/html; charset=utf-8",
                    open(os.path.join(HERE, "edit.html"), "rb").read(),
                )
            if path == "/videos":
                return self._json(videos())
            if path == "/job":
                return self._json(job_state(q.get("v", "")))
            stem = safe_stem(q.get("v"))
            out, w = paths(stem)
            if path == "/data":
                return self._json(data(stem))
            if path == "/proxy.mp4":
                return self._video(os.path.join(w, "proxy.mp4"))
            if path == "/result.mp4":
                look = os.path.join(out, f"{stem}.apercu-look.mp4")
                return self._video(
                    look
                    if os.path.exists(look)
                    else os.path.join(out, f"{stem}.derush.mp4")
                )
        except (ValueError, FileNotFoundError) as e:
            return self._json({"error": str(e)}, 404)
        self._send(404, "text/plain", b"404")

    def _video(self, p):
        size = os.path.getsize(p)
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        start, end = 0, size - 1
        if m:
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = size - int(m.group(2))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(p, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _upload(self, q):
        name = re.sub(r"[^\w.-]+", "_", os.path.basename(q.get("name", "")))
        if not re.search(r"\.(mov|mp4|m4v|mkv|webm)$", name, re.I):
            return self._json(
                {"error": "format non vidéo (mov, mp4, m4v, mkv, webm)"}, 400
            )
        stem = name.rsplit(".", 1)[0]
        if os.path.exists(os.path.join(RUSHS, stem)):
            return self._json(
                {"error": f"une vidéo {stem} existe déjà, ouvre-la dans la liste"}, 409
            )
        up = os.path.join(RUSHS, "_uploads")
        os.makedirs(up, exist_ok=True)
        dest = os.path.join(up, name)
        left = int(self.headers["Content-Length"])
        with open(dest + ".part", "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            os.remove(dest + ".part")
            return self._json({"error": "envoi interrompu"}, 400)
        os.rename(dest + ".part", dest)
        lang = q.get("lang", "fr") if q.get("lang") in ("fr", "en") else "fr"
        start_job(
            stem,
            "prep",
            [[DERUSH, "prep", dest, "--lang", lang], [DERUSH, "proxy", stem]],
        )
        return self._json({"stem": stem})

    def do_POST(self):
        path, q = self._route()
        try:
            if path == "/upload":
                return self._upload(q)
            stem = safe_stem(q.get("v"))
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if path == "/proxy":
                start_job(stem, "proxy", [[DERUSH, "proxy", stem]])
                return self._json(job_state(stem))
            if path == "/render":
                start_job(stem, "render", [[DERUSH, "render", stem]])
                return self._json(job_state(stem))
            if path == "/propose":
                r = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        os.path.join(HERE, "propose_cuts.py"),
                        paths(stem)[0],
                    ],
                    input=raw.decode(),
                    capture_output=True,
                    text=True,
                )
                if r.returncode != 0:
                    return self._json({"error": r.stderr.strip()[-500:]}, 500)
                return self._send(200, "application/json", r.stdout.encode())
            if path == "/save":
                res = save(stem, json.loads(raw))
                print(
                    f"[derush studio] {stem} : {res['cuts']} coupes de texte, {res['restore']} mots rattrapés",
                    flush=True,
                )
                return self._json(res)
        except ValueError as e:
            return self._json({"error": str(e)}, 404)
        self._send(404, "text/plain", b"404")


if __name__ == "__main__":
    os.makedirs(RUSHS, exist_ok=True)
    print(f"[derush studio] http://127.0.0.1:{PORT}  (Ctrl-C pour fermer)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
