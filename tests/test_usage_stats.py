import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "plugins", "chutora", "skills", "usage-stats", "usage_stats.py")


def rec(mid, rid, ctx, model="claude-opus-5-5", ts="2026-10-10T01:00:00Z", side=False, out=10):
    return json.dumps({
        "type": "assistant", "timestamp": ts, "requestId": rid, "isSidechain": side,
        "message": {"id": mid, "model": model,
                    "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": ctx, "output_tokens": out}},
    })


def write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


class UsageStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        p = os.path.join(self.root, "-proj-alpha")
        write(os.path.join(p, "s1.jsonl"), [
            rec("m1", "r1", 100000),
            rec("m1", "r1", 100000),  # 重複
            "{壞行",
            json.dumps({"type": "assistant", "message": {"id": "x"}}),  # 缺欄位
            rec("m2", "r2", 200000),
            rec("m3", "r3", 50000, ts="2026-09-01T00:00:00Z"),
        ])
        write(os.path.join(p, "s1", "subagents", "agent-x.jsonl"),
              [rec("s1", "q1", 1000, model="claude-opus-5-5", side=True),
               rec("s2", "q2", 1000, model="claude-haiku-5-5", side=True)])
        with open(os.path.join(p, "s1", "subagents", "agent-x.meta.json"), "w") as f:
            json.dump({"agentType": "chutora:worker"}, f)
        write(os.path.join(p, "s1", "subagents", "agent-y.jsonl"),
              [rec("s3", "q3", 1000, model="claude-haiku-5-5", side=True)])
        write(os.path.join(p, "s2.jsonl"), [rec("m4", "r4", 300000)])
        write(os.path.join(self.root, "-proj-beta", "s3.jsonl"), [rec("m5", "r5", 10000)])

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, root=None):
        r = subprocess.run([sys.executable, SCRIPT, "--root", root or self.root, *args],
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60, env=self.clean_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    @staticmethod
    def clean_env():
        env = os.environ.copy()
        env.pop("CONTEXT_REMIND_TOKENS", None)
        return env

    def test_dedup_median_threshold(self):
        out = self.run_script("--project", "alpha", "--since", "2026-10-01")
        # main: 100000、200000、300000（m1 去重、m3 被 since 排除）
        self.assertIn("（3 次）", out)
        self.assertIn("中位數 200,000", out)
        self.assertIn("（2/3）", out)

    def test_default_threshold_100k(self):
        out = self.run_script("--project", "alpha", "--since", "2026-10-01")
        self.assertIn("超過門檻 100,000 的呼叫比例", out)

    def test_threshold_option(self):
        out = self.run_script("--project", "alpha", "--since", "2026-10-01", "--threshold", "250000")
        self.assertIn("（1/3）", out)

    def test_agent_type_split(self):
        out = self.run_script("--project", "alpha")
        lines = out.splitlines()
        self.assertTrue(any("chutora:worker" in l and "claude-opus-5-5" in l for l in lines))
        self.assertTrue(any("chutora:worker" in l and "claude-haiku-5-5" in l for l in lines))
        self.assertTrue(any("(未知)" in l and "claude-haiku-5-5" in l for l in lines))
        self.assertIn("子 agent 呼叫比例：3/7", out)
        self.assertIn("1/2", out)  # 有派子 agent 的 session：s1 / (s1, s2)

    def test_since_until_filter(self):
        out = self.run_script("--project", "alpha", "--since", "2026-10-01")
        self.assertNotIn("50,000", out)
        out2 = self.run_script("--project", "alpha", "--until", "2026-09-30")
        self.assertIn("（1 次）", out2)

    def test_project_filter(self):
        out = self.run_script("--project", "beta")
        self.assertIn("（1 次）", out)
        self.assertNotIn("agent 類型", out)

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as empty:
            out = self.run_script(root=empty)
            self.assertIn("沒有符合條件", out)

    # ---- 以下為金額、時區、派工模型、HTML 相關測試 ----
    @staticmethod
    def urec(mid, model, usage, ts="2026-10-10T01:00:00Z", side=False, content=None):
        m = {"id": mid, "model": model, "usage": usage}
        if content is not None:
            m["content"] = content
        return json.dumps({"type": "assistant", "timestamp": ts, "requestId": "r" + mid,
                           "isSidechain": side, "message": m})

    def fresh_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def test_timezone_local_date(self):
        root = self.fresh_root()
        write(os.path.join(root, "-p", "s.jsonl"), [rec("a", "ra", 5000, ts="2026-10-17T21:00:00Z")])
        env = self.clean_env()
        env["TZ"] = "Asia/Taipei"  # UTC+8：UTC 10/17 21:00 = 當地 10/18 05:00
        r = subprocess.run([sys.executable, SCRIPT, "--root", root, "--since", "2026-10-18"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("（1 次）", r.stdout)
        env["TZ"] = "UTC"
        r = subprocess.run([sys.executable, SCRIPT, "--root", root, "--since", "2026-10-18"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, env=env)
        self.assertIn("沒有符合條件", r.stdout)

    def test_cost_opus_1h_and_5m(self):
        root = self.fresh_root()
        u = {"input_tokens": 1000000, "output_tokens": 1000000, "cache_read_input_tokens": 1000000,
             "cache_creation_input_tokens": 2000000,
             "cache_creation": {"ephemeral_1h_input_tokens": 1000000, "ephemeral_5m_input_tokens": 1000000}}
        write(os.path.join(root, "-p", "s.jsonl"), [self.urec("a", "claude-opus-5-5-20261001", u)])
        out = self.run_script(root=root)
        # 4 + 20 + 0.20 + 5（5m）+ 8（1h）= 37.20
        self.assertIn("$37.20", out)

    def test_cost_no_breakdown_counts_as_5m(self):
        root = self.fresh_root()
        u = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 1000000}
        write(os.path.join(root, "-p", "s.jsonl"), [self.urec("a", "claude-sonnet-5-5", u)])
        self.assertIn("$2.50", self.run_script(root=root))

    def test_cost_haiku_two_tiers(self):
        root = self.fresh_root()
        low = {"input_tokens": 100000, "output_tokens": 100000, "cache_read_input_tokens": 0,
               "cache_creation_input_tokens": 0}   # prompt=100k（含邊界）→ 低價：0.01+0.05
        high = {"input_tokens": 100001, "output_tokens": 100000, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}  # >100k → 高價：0.0500005+0.25
        write(os.path.join(root, "-p", "a.jsonl"), [self.urec("a", "claude-haiku-5-5", low)])
        out = self.run_script(root=root)
        self.assertIn("$0.06", out)
        root2 = self.fresh_root()
        write(os.path.join(root2, "-p", "a.jsonl"), [self.urec("a", "claude-haiku-5-5", high)])
        self.assertIn("$0.30", self.run_script(root=root2))

    def test_unknown_model_not_priced(self):
        root = self.fresh_root()
        u = {"input_tokens": 1000000, "output_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0}
        write(os.path.join(root, "-p", "s.jsonl"), [self.urec("a", "<synthetic>", u),
                                                    self.urec("b", "claude-opus-5-5", u)])
        out = self.run_script(root=root)
        self.assertIn("有 1 次呼叫因模型不在價格表而未計價", out)
        self.assertIn("合計 $4.00", out)
        self.assertTrue(any(l.startswith("<synthetic>") and l.rstrip().endswith("-") for l in out.splitlines()))

    def test_dispatch_model_link(self):
        root = self.fresh_root()
        p = os.path.join(root, "-p")
        u = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        tools = [{"type": "tool_use", "id": "toolu_A", "name": "Task", "input": {"model": "sonnet", "subagent_type": "bulk"}},
                 {"type": "tool_use", "id": "toolu_B", "name": "Task", "input": {"subagent_type": "bulk"}}]
        write(os.path.join(p, "s.jsonl"), [self.urec("m", "claude-opus-5-5", u, content=tools)])
        for name, tid in (("agent-1", "toolu_A"), ("agent-2", "toolu_A"), ("agent-3", "toolu_B")):
            write(os.path.join(p, "s", "subagents", name + ".jsonl"),
                  [self.urec(name, "claude-haiku-5-5", u, side=True)])
            with open(os.path.join(p, "s", "subagents", name + ".meta.json"), "w") as f:
                json.dump({"agentType": "bulk", "toolUseId": tid}, f)
        out = self.run_script(root=root)
        line = next(l for l in out.splitlines() if l.startswith("bulk"))
        self.assertIn("sonnet×2", line)
        self.assertIn("未指定×1", line)
        self.assertRegex(line, r"\s3\s")  # 派工次數 3

    def html_fixture(self):
        root = self.fresh_root()
        p = os.path.join(root, "-p")
        u = {"input_tokens": 10, "output_tokens": 10, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0}
        write(os.path.join(p, "s.jsonl"), [self.urec("m", "claude-opus-5-5", u)])
        write(os.path.join(p, "s", "subagents", "agent-1.jsonl"),
              [self.urec("a1", "claude-haiku-5-5", u, side=True)])
        with open(os.path.join(p, "s", "subagents", "agent-1.meta.json"), "w") as f:
            json.dump({"agentType": "<script>alert(1)</script>", "toolUseId": "t"}, f)
        return root

    def test_html_output_escaped_and_self_contained(self):
        root = self.html_fixture()
        out_dir = self.fresh_root()
        target = os.path.join(out_dir, "r.html")
        out = self.run_script("--html", target, root=root)
        self.assertIn(target, out)
        with open(target, encoding="utf-8") as f:
            doc = f.read()
        self.assertNotIn("<script>alert(1)</script>", doc)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", doc)
        self.assertNotIn("http://", doc)
        self.assertNotIn("https://", doc)
        self.assertIn("prefers-color-scheme", doc)
        self.assertIn("主對話", doc)

    def test_no_html_writes_nothing(self):
        root = self.html_fixture()
        before = sorted(os.listdir(root))
        cwd = self.fresh_root()
        r = subprocess.run([sys.executable, SCRIPT, "--root", root], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60, env=self.clean_env(), cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(cwd), [])
        self.assertEqual(sorted(os.listdir(root)), before)
        self.assertNotIn("HTML 報表", r.stdout)


if __name__ == "__main__":
    unittest.main()
