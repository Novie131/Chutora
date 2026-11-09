"""bench/run.py 的測試：只測解析、彙總與 dry-run，不呼叫模型。"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "bench" / "run.py"
spec = importlib.util.spec_from_file_location("bench_run", RUN)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

FAKE = {
    "type": "result", "subtype": "success", "is_error": False, "duration_ms": 12000, "num_turns": 7,
    "result": "done", "session_id": "s1", "total_cost_usd": 0.0421,
    "usage": {"input_tokens": 120, "output_tokens": 900, "cache_creation_input_tokens": 15000,
              "cache_read_input_tokens": 60000},
    "modelUsage": {"claude-opus-5-5": {"inputTokens": 100, "outputTokens": 800, "cacheReadInputTokens": 50000,
                                       "cacheCreationInputTokens": 12000, "costUSD": 0.04},
                   "claude-haiku-5-5": {"inputTokens": 20, "outputTokens": 100, "cacheReadInputTokens": 10000,
                                        "cacheCreationInputTokens": 3000, "costUSD": 0.0021}},
}


class BenchTest(unittest.TestCase):
    def test_parse_usage(self):
        r = bench.parse_result(json.dumps(FAKE))
        self.assertEqual(r["total_tokens"], 120 + 900 + 15000 + 60000)
        self.assertAlmostEqual(r["cost_usd"], 0.0421)
        self.assertEqual(r["num_turns"], 7)
        self.assertFalse(r["is_error"])
        self.assertEqual(r["models"], ["claude-haiku-5-5", "claude-opus-5-5"])

    def test_parse_model_usage_fallback_and_noise(self):
        d = dict(FAKE)
        d.pop("usage")
        d.pop("total_cost_usd")
        r = bench.parse_result("some warning line\n" + json.dumps(d))
        self.assertEqual(r["input_tokens"], 120)
        self.assertEqual(r["cache_read_tokens"], 60000)
        self.assertAlmostEqual(r["cost_usd"], 0.0421)

    def test_parse_error_and_garbage(self):
        d = dict(FAKE, subtype="error_max_turns", is_error=True)
        self.assertTrue(bench.parse_result(json.dumps(d))["is_error"])
        self.assertIsNone(bench.parse_result("not json at all"))
        self.assertIsNone(bench.parse_result(""))

    def test_aggregate_medians_and_markdown(self):
        recs = []
        for arm, toks, ok in (("without", [100, 300, 200], [True, True, False]), ("with", [50, 70, 60], [True] * 3)):
            for t, o in zip(toks, ok):
                recs.append({"task": "fix-bug", "arm": arm, "ok": o, "total_tokens": t, "input_tokens": t,
                             "output_tokens": 0, "cache_read_tokens": 0, "cost_usd": t / 1000, "num_turns": 3})
        agg = bench.aggregate(recs)
        self.assertEqual(agg[("fix-bug", "without")]["total_tokens"], 200)
        self.assertEqual(agg[("fix-bug", "with")]["total_tokens"], 60)
        self.assertEqual(agg[("fix-bug", "without")]["success"], 2)
        md = bench.markdown(agg)
        self.assertIn("| fix-bug | with | 3/3 | 60 | -70% |", md)

    def test_build_cmd(self):
        t = {"id": "x", "prompt": "do it"}
        self.assertNotIn("--plugin-dir", bench.build_cmd(t, "without"))
        c = bench.build_cmd(t, "with", model="opus", budget=0.5)
        self.assertIn("--plugin-dir", c)
        self.assertEqual(c[c.index("--model") + 1], "opus")
        self.assertEqual(c[c.index("--output-format") + 1], "json")

    def test_dry_run_calls_nothing(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        env = dict(os.environ, PATH=empty)  # 沒有 claude 可呼叫
        env.pop("ANTHROPIC_API_KEY", None)
        r = subprocess.run([sys.executable, str(RUN), "--dry-run", "--runs", "2"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Would run 12 claude -p calls", r.stdout)
        self.assertIn("Nothing was run", r.stdout)

    def test_no_key_refuses(self):
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_BASE_URL", None)
        r = subprocess.run([sys.executable, str(RUN), "--runs", "1"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2)

    def test_fixtures_fail_before_and_pass_after_fix(self):
        for task in bench.load_tasks():
            work = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, work)
            shutil.copytree(ROOT / "bench" / "fixtures" / task["fixture"], work, dirs_exist_ok=True)
            r = subprocess.run(task["check"], cwd=work, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, task["id"] + " should fail before the fix")
            if task["id"] == "fix-bug":
                p = Path(work, "cart.py")
                p.write_text(p.read_text().replace("return subtotal - pct  # bug：把百分比當成金額扣",
                                                   "return max(0, subtotal * (100 - pct) // 100)"))
            elif task["id"] == "noisy-build":
                Path(work, "build.json").write_text('{"target": "release", "jobs": 4}\n')
            elif task["id"] == "explore":
                Path(work, "ANSWER.txt").write_text("app/shipping/mod3.py:shipping_fee\n")
            r = subprocess.run(task["check"], cwd=work, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, task["id"] + " should pass after the fix: " + r.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
