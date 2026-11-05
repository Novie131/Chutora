"""每週「省下多少」估算（hooks/weekly.py）與 SessionStart 的整合。"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
WEEKLY = HOOKS / "weekly.py"


def ts(days_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return t.replace(hour=12, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


class WeeklyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.data = self.tmp / "data"
        self.proj = self.home / ".claude" / "projects" / "-Users-x-proj"
        (self.proj / "s1" / "subagents").mkdir(parents=True)

    def line(self, model, mid, days_ago, tokens, side=False):
        return json.dumps({"type": "assistant", "timestamp": ts(days_ago), "isSidechain": side,
                           "message": {"id": mid, "model": model,
                                       "usage": {"input_tokens": tokens, "output_tokens": 1000}}}) + "\n"

    def seed(self, with_sub=True):
        (self.proj / "s1.jsonl").write_text(self.line("claude-opus-5-5", "m1", 2, 20000))
        if with_sub:
            (self.proj / "s1" / "subagents" / "agent-a.jsonl").write_text(
                self.line("claude-haiku-5-5", "a1", 2, 2_000_000) + self.line("claude-sonnet-5-5", "a2", 3, 1_000_000))

    def run_weekly(self, **kw):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["CLAUDE_PLUGIN_DATA"] = str(self.data)
        env.pop("CHUTORA_WEEKLY", None)
        env.update(kw)
        return subprocess.run([sys.executable, str(WEEKLY)], capture_output=True, text=True, env=env, timeout=60)

    def test_prints_estimate_once_per_week(self):
        self.seed()
        out = self.run_weekly(CHUTORA_LANG="zh").stdout
        self.assertIn("估算", out)
        self.assertIn("opus-5-5", out)
        self.assertIn("只算模型價差", out)
        self.assertEqual(self.run_weekly(CHUTORA_LANG="zh").stdout, "")

    def test_english(self):
        self.seed()
        out = self.run_weekly(CHUTORA_LANG="en").stdout
        self.assertIn("estimate", out)
        self.assertIn("Model price difference only", out)

    def test_disabled(self):
        self.seed()
        self.assertEqual(self.run_weekly(CHUTORA_WEEKLY="0").stdout, "")
        self.assertFalse((self.data / ".weekly-shown").exists())

    def seed_trim(self, days_ago=1, chars=80000):
        import datetime
        d = self.home / ".claude" / "chutora"
        d.mkdir(parents=True, exist_ok=True)
        day = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
        (d / "trim-stats.json").write_text(json.dumps({"days": {day: chars}, "total_chars": chars, "count": 3}))

    def test_trim_only_line(self):
        self.seed(with_sub=False)
        self.seed_trim()
        out = self.run_weekly(CHUTORA_LANG="zh").stdout
        self.assertIn("輸出瘦身與讀檔去重讓約 20,000 token", out)
        self.assertIn("估算", out)

    def test_trim_appended_to_estimate(self):
        self.seed()
        self.seed_trim()
        out = self.run_weekly(CHUTORA_LANG="en").stdout
        self.assertIn("Model price difference only", out)
        self.assertIn("about 20,000 tokens out of the context", out)

    def test_old_trim_ignored(self):
        self.seed(with_sub=False)
        self.seed_trim(days_ago=30)
        self.assertEqual(self.run_weekly().stdout, "")

    def test_no_subagents_silent(self):
        self.seed(with_sub=False)
        self.assertEqual(self.run_weekly().stdout, "")

    def test_old_data_ignored(self):
        (self.proj / "s1.jsonl").write_text(self.line("claude-opus-5-5", "m1", 20, 20000))
        (self.proj / "s1" / "subagents" / "agent-a.jsonl").write_text(self.line("claude-haiku-5-5", "a1", 20, 2_000_000))
        self.assertEqual(self.run_weekly().stdout, "")

    def test_session_start_shows_weekly_in_system_message(self):
        self.seed()
        self.data.mkdir()
        (self.data / ".route-setup-done").touch()
        proj = self.tmp / "work"
        proj.mkdir()
        env = os.environ.copy()
        env.update({"HOME": str(self.home), "CLAUDE_PLUGIN_DATA": str(self.data), "CLAUDE_PROJECT_DIR": str(proj),
                    "CHUTORA_LANG": "en"})
        env.pop("CHUTORA_WEEKLY", None)
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        r = subprocess.run(["sh", str(HOOKS / "session-start.sh")], capture_output=True, text=True, env=env,
                           cwd=proj, stdin=subprocess.DEVNULL, timeout=60)
        d = json.loads(r.stdout)
        self.assertIn("Chutora weekly (estimate)", d["systemMessage"])
        self.assertIn("delegation conventions", d["hookSpecificOutput"]["additionalContext"])
        # 同一週第二次：回到純文字
        r2 = subprocess.run(["sh", str(HOOKS / "session-start.sh")], capture_output=True, text=True, env=env,
                            cwd=proj, stdin=subprocess.DEVNULL, timeout=60)
        self.assertFalse(r2.stdout.startswith("{"))


if __name__ == "__main__":
    unittest.main()
