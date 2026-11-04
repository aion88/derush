import io, json, os, subprocess, sys, tempfile, unittest, urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "derush"))
import llm  # noqa: E402

MSG = "aucun LLM : installe Claude Code (claude) ou ajoute une clé OpenAI (derush config openai-key)"
# fake key built at runtime so secret scanners do not flag the test file
FAKE = "sk-" + "proj-" + "SECRETKEY" + "-abcd1234"
claude = lambda n: "/x/claude" if n == "claude" else None
nothing = lambda n: None


class Pick(unittest.TestCase):
    def test_custom_wins(self):
        env = {"DERUSH_LLM": "cat", "OPENAI_API_KEY": "k"}
        self.assertEqual(llm.pick(env, claude, lambda: "kc"), ("custom", "cat"))

    def test_empty_custom_is_unset(self):
        self.assertEqual(llm.pick({"DERUSH_LLM": ""}, claude, lambda: None), ("claude", None))

    def test_claude_before_openai(self):
        self.assertEqual(llm.pick({"OPENAI_API_KEY": "k"}, claude, lambda: "kc"), ("claude", None))

    def test_openai_from_env(self):
        self.assertEqual(llm.pick({"OPENAI_API_KEY": "k"}, nothing, lambda: "kc"), ("openai", "k"))

    def test_openai_from_keychain(self):
        self.assertEqual(llm.pick({}, nothing, lambda: "kc"), ("openai", "kc"))

    def test_none_message(self):
        self.assertEqual(llm.pick({}, nothing, lambda: None), ("none", None))
        with mock.patch.object(llm, "pick", return_value=("none", None)):
            with self.assertRaises(llm.NoLLM) as c:
                llm.complete("x")
        self.assertEqual(str(c.exception), MSG)

    def _err(self, code, body, key=FAKE):
        err = urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body.encode()))
        with mock.patch.object(llm, "pick", return_value=("openai", key)), \
             mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(Exception) as c:
                llm.complete("hi")
        return str(c.exception)

    def test_key_never_in_error(self):
        key = FAKE
        redacted = "sk-proj-****" + key[-4:]
        for code in (401, 403, 400, 429):
            msg = self._err(code, f'{{"error":"Incorrect API key {key}; you sent {redacted}"}}')
            self.assertIn(str(code), msg)
            self.assertNotIn(key, msg)
            self.assertNotIn(key[-4:], msg)
            self.assertNotIn("SECRETKEY", msg)

    def test_auth_error_has_no_body(self):
        msg = self._err(401, "some body text")
        self.assertIn("clé OpenAI refusée", msg)
        self.assertNotIn("some body text", msg)

    def test_urlerror_becomes_runtimeerror(self):
        with mock.patch.object(llm, "pick", return_value=("openai", "k")), \
             mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("pas de réseau")):
            with self.assertRaises(RuntimeError) as c:
                llm.complete("hi")
        self.assertIn("LLM injoignable", str(c.exception))

    def test_timeout_becomes_runtimeerror(self):
        with mock.patch.object(llm, "pick", return_value=("custom", "sleep 5")), \
             mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sh", 240)):
            with self.assertRaises(RuntimeError) as c:
                llm.complete("hi")
        self.assertIn("LLM injoignable", str(c.exception))


class Isolated(unittest.TestCase):
    def test_runs_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "_work"))
            words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("bonjour a tous".split())]
            with open(os.path.join(d, "_work", "aligned.json"), "w") as f:
                json.dump({"segments": [{"words": words}]}, f)
            env = dict(os.environ, DERUSH_LLM='cat >/dev/null; echo {\\"proposals\\":[]}')
            py = os.environ.get("DERUSH_PY") or os.path.expanduser("~/.local/share/derush/venv/bin/python")
            r = subprocess.run([py, "-I", os.path.join(ROOT, "derush", "propose_cuts.py"), d],
                               input=json.dumps({"keep_idx": [0, 1, 2]}), capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["engine"], "custom")
            self.assertEqual(out["proposals"], [])


if __name__ == "__main__":
    unittest.main()
