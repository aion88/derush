import io, json, os, subprocess, sys, tempfile, unittest, urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "derush"))
import llm  # noqa: E402

MSG = "aucun LLM : installe Claude Code (claude) ou ajoute une clé OpenAI (derush config openai-key)"
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

    def test_key_never_in_error(self):
        key = "sk-SECRET-123"
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}'))
        with mock.patch.object(llm, "pick", return_value=("openai", key)), \
             mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(Exception) as c:
                llm.complete("hi")
        self.assertIn("401", str(c.exception))
        self.assertNotIn(key, str(c.exception))


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
