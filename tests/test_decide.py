"""決策引擎（plugins/chutora/hooks/decide.py）的測試：公式、平滑、冷啟動、相似度、校準、門檻與模式。"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
DECIDE = HOOKS / "decide.py"
sys.path.insert(0, str(HOOKS))
import decide  # noqa: E402


def past(outcome, feats, probs=None, feedback="record", weight=1.0, ts=None, dtype="t"):
    f = dict(feats, type=dtype)
    return {"id": "x", "type": dtype, "features": f, "outcome": outcome, "feedback": feedback, "weight": weight,
            "raw": probs or {}, "probs": probs or {}, "resolved_ts": ts if ts is not None else time.time() - 999999}


class MathTest(unittest.TestCase):
    def test_formula_matches_definition(self):
        p, n, w = decide.mix(["a", "b"], {"a": 3, "b": 1}, {"a": 0.2, "b": 0.8})
        self.assertAlmostEqual(n, 4)
        self.assertAlmostEqual(w, 4 / 9)
        self.assertAlmostEqual(p["a"], (4 / 9) * (4 / 6) + (5 / 9) * 0.2)
        self.assertAlmostEqual(sum(p.values()), 1.0)

    def test_no_history_uses_claude_or_uniform(self):
        p, n, w = decide.mix(["a", "b", "c"], {}, None)
        self.assertEqual(n, 0)
        for v in p.values():
            self.assertAlmostEqual(v, 1 / 3)
        p, _, _ = decide.mix(["a", "b"], {}, {"a": 3, "b": 1})
        self.assertAlmostEqual(p["a"], 0.75)

    def test_smoothing_never_reaches_certainty(self):
        p, _, _ = decide.mix(["a", "b"], {"a": 50}, None)
        self.assertLess(p["a"], 1.0)
        self.assertGreater(p["b"], 0.0)

    def test_similarity_rules(self):
        a = {"type": "t", "category": "rm", "path": "build", "branch": "main"}
        self.assertEqual(decide.similarity(a, dict(a)), 1.0)
        self.assertEqual(decide.similarity(a, dict(a, type="u")), 0.0)
        self.assertLess(decide.similarity(a, dict(a, branch="dev")), 1.0)
        self.assertGreater(decide.similarity(a, dict(a, path="build/*")), decide.similarity(a, dict(a, path="src")))

    def test_only_similar_records_count(self):
        feats = {"category": "rm", "path": "build", "action": "rm"}
        far = past("b", {"category": "other", "path": "src", "action": "mv"})
        near = past("a", feats)
        counts, _, _, _ = decide.gather([far, near], dict(feats, type="t"), ["a", "b"])
        self.assertEqual(counts["b"], 0)
        self.assertAlmostEqual(counts["a"], 1.0)

    def test_brier(self):
        self.assertAlmostEqual(decide.brier({"a": 0.7, "b": 0.3}, "a"), 0.09 + 0.09)
        self.assertAlmostEqual(decide.brier({"a": 1.0, "b": 0.0}, "a"), 0.0)

    def test_calibration_pulls_overconfident_bucket_down(self):
        hist = []
        for i in range(10):  # 預測 0.7 那桶只對六成
            hist.append({"type": "t", "outcome": "a" if i < 6 else "b", "raw": {"a": 0.72, "b": 0.28}})
        p, info = decide.calibrate({"a": 0.72, "b": 0.28}, "t", hist)
        self.assertLess(p["a"], 0.72)
        self.assertIn("a", info)
        p2, info2 = decide.calibrate({"a": 0.72, "b": 0.28}, "t", hist[:3])  # 樣本太少不修
        self.assertAlmostEqual(p2["a"], 0.72)
        self.assertEqual(info2, {})

    def test_thresholds_and_modes(self):
        self.assertEqual(decide.threshold(True, False, "balanced"), 0.70)
        self.assertEqual(decide.threshold(True, True, "balanced"), 0.85)
        self.assertIsNone(decide.threshold(False, True, "balanced"))
        self.assertIsNone(decide.threshold(None, False, "balanced"))
        self.assertAlmostEqual(decide.threshold(True, True, "economy"), 0.80)
        self.assertAlmostEqual(decide.threshold(True, True, "quality"), 0.90)
        self.assertAlmostEqual(decide.threshold(True, False, "balanced", cold=True), 0.80)

    def test_cold_start_never_auto(self):
        r = decide.score("t", ["a", "b"], {}, {"a": 0.79, "b": 0.21}, True, False, [], "balanced")
        self.assertTrue(r["cold"])
        self.assertEqual(r["action"], "ask")
        r = decide.score("t", ["a", "b"], {}, {"a": 0.9, "b": 0.1}, True, False, [], "balanced")
        self.assertEqual(r["action"], "auto")

    def test_irreversible_never_auto_even_if_certain(self):
        hist = [past("a", {"k": "v"}, feedback="auto") for _ in range(30)]
        r = decide.score("t", ["a", "b"], {"k": "v"}, {"a": 1, "b": 0}, False, True, hist, "economy")
        self.assertEqual(r["action"], "ask")
        r = decide.score("t", ["a", "b"], {"k": "v"}, {"a": 1, "b": 0}, False, True, hist, "economy", unattended=True)
        self.assertEqual(r["action"], "skip-todo")

    def test_unattended_picks_best_or_todo(self):
        r = decide.score("t", ["a", "b"], {}, {"a": 0.6, "b": 0.4}, True, True, [], "balanced", unattended=True)
        self.assertEqual((r["action"], r["best"]), ("auto-unattended", "a"))
        r = decide.score("t", ["a", "b", "c"], {}, {"a": 0.4, "b": 0.35, "c": 0.25}, False, False, [], unattended=True)
        self.assertEqual(r["action"], "skip-todo")

    def test_user_preference_and_undo_cooldown(self):
        feats = {"category": "rm-in-project", "path": "build"}
        grant = past("auto", feats, feedback="auto", ts=time.time() - 100, dtype=decide.AUTO_TYPE)
        r = decide.score(decide.AUTO_TYPE, ["auto", "ask"], feats, None, True, False, [grant], "balanced")
        self.assertEqual(r["prior"], "user:auto")
        self.assertEqual(r["action"], "auto")
        self.assertTrue(r["simple"])
        undo = past("ask", feats, feedback="undo", weight=3, ts=time.time() - 10, dtype=decide.AUTO_TYPE)
        r = decide.score(decide.AUTO_TYPE, ["auto", "ask"], feats, None, True, False, [grant, undo], "balanced")
        self.assertTrue(r["cooldown"])
        self.assertEqual(r["best"], "ask")
        self.assertEqual(r["action"], "ask")


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.proj = self.home / "proj"
        (self.proj / "claude-memory").mkdir(parents=True)

    def run_cli(self, *args):
        e = dict(os.environ, HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG="zh")
        e.pop("CHUTORA_MODE", None)
        r = subprocess.run([sys.executable, str(DECIDE)] + list(args), capture_output=True, text=True, env=e,
                           cwd=str(self.proj), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def test_score_record_stats_roundtrip(self):
        out = json.loads(self.run_cli("score", "--type", "pick", "--options", "x,y", "--claude", "x=0.7,y=0.3",
                                      "--feature", "area=docs", "--recoverable", "yes", "--impact", "no"))
        self.assertEqual(out["best"], "x")
        self.assertEqual(out["action"], "ask")  # 冷啟動 0.80
        rec = json.loads(self.run_cli("record", out["id"], "x"))
        self.assertAlmostEqual(rec["brier"], 0.18, places=3)
        lines = (self.proj / "claude-memory" / "decisions.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        st = json.loads(self.run_cli("stats"))
        self.assertEqual(st["resolved"], 1)
        out2 = json.loads(self.run_cli("score", "--type", "pick", "--options", "x,y", "--feature", "area=docs",
                                       "--recoverable", "yes", "--impact", "no", "--no-record"))
        self.assertFalse(out2["cold"])
        self.assertGreater(out2["probs"]["x"], 0.5)

    def test_remote_is_never_auto(self):
        out = json.loads(self.run_cli("score", "--type", "push", "--options", "push,wait", "--claude", "push=1",
                                      "--remote", "--unattended"))
        self.assertEqual(out["action"], "skip-todo")
        self.assertFalse(out["recoverable"])

    def test_path_reversibility(self):
        (self.proj / "build").mkdir()
        (self.proj / "build" / "a.o").write_text("x")
        out = json.loads(self.run_cli("score", "--type", "clean", "--options", "yes,no", "--path", "build",
                                      "--no-record"))
        self.assertEqual(out["basis"], "regenerable")
        self.assertFalse(out["impact"])
        out = json.loads(self.run_cli("score", "--type", "clean", "--options", "yes,no", "--path", "../x",
                                      "--no-record"))
        self.assertFalse(out["recoverable"])


if __name__ == "__main__":
    unittest.main()
