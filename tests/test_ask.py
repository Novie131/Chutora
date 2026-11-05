"""反問提醒 hook（plugins/chutora/hooks/ask.py）與 /chutora ask 的測試。一律用暫存 HOME。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASK = ROOT / "plugins" / "chutora" / "hooks" / "ask.py"
HUB = ROOT / "plugins" / "chutora" / "skills" / "chutora-hub" / "chutora.py"


class AskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.conf = self.home / ".claude" / "chutora"

    def env(self, extra=None):
        e = dict(os.environ, HOME=str(self.home), CHUTORA_LANG="zh")
        for k in ("CHUTORA_ASK", "CHUTORA_MODE"):
            e.pop(k, None)
        e.update(extra or {})
        return e

    def run_hook(self, prompt, extra=None):
        data = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "session_id": "s"}
        r = subprocess.run([sys.executable, str(ASK)], input=json.dumps(data), capture_output=True, text=True,
                           env=self.env(extra), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else None

    def test_explicit_request(self):
        msg = self.run_hook("先問我再做，幫我重構登入流程")
        self.assertIn("要求先問清楚", msg)
        self.assertIn("最多 4 題", msg)
        self.assertIn("briefs", msg)
        self.assertIn("AskUserQuestion", msg)

    def test_unsure_phrases(self):
        for p in ("我不太清楚要用哪個資料庫", "這樣做好嗎？你覺得呢", "還沒想好要怎麼分頁"):
            self.assertIn("表示不太確定", self.run_hook(p), p)

    def test_english(self):
        msg = self.run_hook("I'm not sure which approach is better", {"CHUTORA_LANG": "en"})
        self.assertIn("said they are not sure", msg)
        self.assertIn("asked to be asked first", self.run_hook("Ask me first, then build it", {"CHUTORA_LANG": "en"}))

    def test_plain_prompt_ignored(self):
        self.assertIsNone(self.run_hook("把 README 的錯字修掉"))
        self.assertIsNone(self.run_hook("Fix the typo in README"))

    def test_mode_limits(self):
        self.assertIn("最多 3 題", self.run_hook("先問我", {"CHUTORA_MODE": "economy"}))
        self.assertIn("最多 5 題", self.run_hook("先問我", {"CHUTORA_MODE": "quality"}))

    def test_switch_off(self):
        self.assertIsNone(self.run_hook("先問我", {"CHUTORA_ASK": "0"}))
        self.conf.mkdir(parents=True, exist_ok=True)
        (self.conf / "ask").write_text("off\n")
        self.assertIsNone(self.run_hook("先問我"))

    def hub(self, *args, extra=None):
        return subprocess.run([sys.executable, str(HUB), *args], capture_output=True, text=True, env=self.env(extra), timeout=30)

    def test_hub_ask_prints_steps(self):
        r = self.hub("ask")
        self.assertEqual(r.returncode, 0)
        self.assertIn("AskUserQuestion", r.stdout)
        self.assertIn("最多 4 題", r.stdout)
        self.assertIn("驗收標準", r.stdout)

    def test_hub_toggles(self):
        for name, fname in (("ask", "ask"), ("dedup", "dedup"), ("mcp-trim", "mcp-trim")):
            self.assertEqual(self.hub(name, "off").returncode, 0)
            self.assertEqual((self.conf / fname).read_text().strip(), "off")
            self.assertIn("關閉", self.hub(name, *(["status"] if name == "ask" else [])).stdout)
            self.assertEqual(self.hub(name, "on").returncode, 0)
            self.assertFalse((self.conf / fname).exists())
        self.assertEqual(self.hub("dedup", "maybe").returncode, 2)

    def test_hub_status_shows_new_switches(self):
        out = self.hub().stdout
        for s in ("讀檔去重", "MCP 輸出瘦身", "反問", "/chutora ask"):
            self.assertIn(s, out)


if __name__ == "__main__":
    unittest.main()
