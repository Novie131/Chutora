import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POST_TOOL = ROOT / "plugins" / "smart-agent-route" / "hooks" / "post-tool.py"


class PostToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / "data"
        self.home = self.tmp / "home"
        self.home.mkdir()

    def env(self, repeat="3"):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["CLAUDE_PLUGIN_DATA"] = str(self.data)
        env["LOOP_GUARD_REPEAT"] = repeat
        return env

    def run_hook(self, payload, repeat="3"):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(POST_TOOL)], input=stdin,
                              text=True, capture_output=True, env=self.env(repeat),
                              timeout=30)

    def err(self, session="s", stderr="ModuleNotFoundError: No module named foo", n=0):
        # n 讓每次的數字不同，驗證正規化後仍算同一個錯誤
        return {"session_id": session, "tool_name": "Bash",
                "tool_response": {"is_error": True, "stderr": f"{stderr} at line {n}"}}

    def ok(self, session="s", tool="Read"):
        return {"session_id": session, "tool_name": tool,
                "tool_response": {"content": "fine"}}

    def usage(self):
        p = self.data / ".tool-usage.json"
        return json.loads(p.read_text()) if p.exists() else {}

    # --- loop guard ---

    def test_first_errors_silent_then_nudge_on_threshold(self):
        self.assertEqual(self.run_hook(self.err(n=1)).stdout, "")
        self.assertEqual(self.run_hook(self.err(n=2)).stdout, "")
        out = self.run_hook(self.err(n=3)).stdout
        self.assertNotEqual(out, "")
        d = json.loads(out)
        self.assertEqual(d["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("additionalContext", d["hookSpecificOutput"])

    def test_no_repeat_nudge_at_level_one(self):
        for i in range(3):
            last = self.run_hook(self.err(n=i)).stdout
        self.assertNotEqual(last, "")          # 第 3 次提醒
        self.assertEqual(self.run_hook(self.err(n=9)).stdout, "")   # 第 4 次不再重複

    def test_level_two_nudge_at_double(self):
        outs = [self.run_hook(self.err(n=i)).stdout for i in range(6)]
        self.assertNotEqual(outs[2], "")       # L1 at 3
        self.assertEqual(outs[3], "")
        self.assertEqual(outs[4], "")
        self.assertNotEqual(outs[5], "")       # L2 at 6

    def test_success_never_nudges(self):
        for _ in range(5):
            self.assertEqual(self.run_hook(self.ok()).stdout, "")

    def test_different_errors_do_not_accumulate(self):
        self.run_hook({"session_id": "s", "tool_name": "Bash",
                  "tool_response": {"is_error": True, "stderr": "permission denied"}})
        self.run_hook({"session_id": "s", "tool_name": "Bash",
                  "tool_response": {"is_error": True, "stderr": "connection refused"}})
        out = self.run_hook({"session_id": "s", "tool_name": "Bash",
                        "tool_response": {"is_error": True, "stderr": "no such file"}}).stdout
        self.assertEqual(out, "")              # 三個不同錯誤，不跨門檻

    def test_sessions_isolated(self):
        for i in range(3):
            self.run_hook(self.err(session="a", n=i))
        # 另一個 session 的同樣錯誤從頭算起
        self.assertEqual(self.run_hook(self.err(session="b", n=0)).stdout, "")

    # --- usage logging ---

    def test_usage_is_recorded(self):
        self.run_hook(self.ok(tool="Read"))
        self.run_hook(self.ok(tool="Edit"))
        self.run_hook(self.ok(tool="Read"))
        tools = self.usage().get("tools", {})
        self.assertEqual(tools["Read"]["count"], 2)
        self.assertEqual(tools["Edit"]["count"], 1)

    # --- robustness: 任何情況都不該讓工具中斷 ---

    def test_malformed_stdin_is_silent(self):
        r = self.run_hook("not json at all")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_missing_tool_name_is_silent(self):
        r = self.run_hook({"session_id": "s", "tool_response": {"content": "x"}})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_empty_stdin_is_silent(self):
        r = self.run_hook("")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
