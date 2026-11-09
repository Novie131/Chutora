"""VS Code 自我檢查（plugins/chutora/hooks/selfcheck.py）的測試。一律用假 HOME。"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = ROOT / "plugins" / "chutora" / "hooks" / "selfcheck.py"


class SelfcheckTest(unittest.TestCase):
    def run_it(self, home, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("CHUTORA_", "CLAUDE"))}
        e.update(HOME=str(home), **env)
        return subprocess.run([sys.executable, str(SELF)], capture_output=True, text=True, env=e, timeout=60)

    def test_report_has_all_items_in_fake_home(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_it(d, CLAUDE_CODE_ENTRYPOINT="claude-vscode", CHUTORA_LANG="zh")
            self.assertEqual(r.returncode, 0, r.stderr)
            for s in ("執行環境", "claude-vscode", "外掛來源與版本", "hook 觸發紀錄", "守門 dry", "force-push",
                      "claude-settings", "瘦身 dry", "150 行", "語言"):
                self.assertIn(s, r.stdout)
            self.assertIn("⚠️", r.stdout)  # 假 HOME 沒有 activity
            self.assertNotIn("❌ 1", r.stdout)
            self.assertFalse((Path(d) / ".claude").exists())  # 唯讀：沒寫任何東西

    def test_english_and_activity_ok(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / ".claude" / "chutora" / "activity"
            a.mkdir(parents=True)
            (a / "s.json").write_text("{}")
            r = self.run_it(d, CHUTORA_LANG="en")
            self.assertIn("hook activity", r.stdout)
            self.assertIn("✅ hook activity", r.stdout)
            self.assertTrue(r.stdout.strip().endswith("❌ 0"))


if __name__ == "__main__":
    unittest.main()
