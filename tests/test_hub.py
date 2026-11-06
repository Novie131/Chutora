"""/chutora 入口腳本：狀態、doctor、模式、語言。一律用假 HOME。"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "plugins" / "chutora" / "skills" / "chutora-hub" / "chutora.py"


class HubTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.proj = self.tmp / "proj"
        self.proj.mkdir()
        self.data = self.tmp / "data"
        self.data.mkdir()

    def run_hub(self, *args, lang="zh", **kw):
        env = {k: v for k, v in os.environ.items() if k not in ("LC_ALL", "LC_MESSAGES", "LANG", "LOOP_GUARD_REPEAT")}
        env.update({"HOME": str(self.home), "CLAUDE_PROJECT_DIR": str(self.proj),
                    "CLAUDE_PLUGIN_DATA": str(self.data), "CHUTORA_LANG": lang})
        env.update(kw)
        return subprocess.run([sys.executable, str(HUB), *args], capture_output=True, text=True,
                              env=env, cwd=self.proj, timeout=30)

    def conf(self, name):
        p = self.home / ".claude" / "chutora" / name
        return p.read_text().strip() if p.exists() else None

    def test_status_menu_zh(self):
        out = self.run_hub().stdout
        self.assertIn("Chutora 狀態", out)
        self.assertIn("模式：平衡", out)
        self.assertIn("/chutora doctor", out)
        self.assertIn("/chutora trim on|off", out)
        self.assertIn("噪音輸出瘦身：開啟", out)

    def test_status_menu_en(self):
        out = self.run_hub(lang="en").stdout
        self.assertIn("Chutora status", out)
        self.assertIn("Noisy-output trimming: on", out)

    def test_status_reads_context_and_loop_guard(self):
        enc = re.sub(r"[^A-Za-z0-9]", "-", str(self.proj))
        d = self.home / ".claude" / "projects" / enc
        d.mkdir(parents=True)
        (d / "sess1.jsonl").write_text(json.dumps({"type": "assistant", "message": {
            "id": "m", "usage": {"input_tokens": 42000}}}) + "\n")
        (self.data / ".loop-guard-state.json").write_text(json.dumps(
            {"_order": ["sess1"], "sess1": {"sigs": {"Bash::error x": 4, "Bash::other": 1}, "nudged": {}}}))
        out = self.run_hub().stdout
        self.assertIn("約 42k", out)
        self.assertIn("1 種錯誤重複出現（最多 4 次）", out)

    def test_mode_switch(self):
        r = self.run_hub("mode", "economy")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.conf("mode"), "economy")
        self.assertIn("模式：省錢", self.run_hub().stdout)
        self.assertEqual(self.run_hub("模式", "品質").returncode, 0)
        self.assertEqual(self.conf("mode"), "quality")

    def test_mode_invalid(self):
        r = self.run_hub("mode", "turbo")
        self.assertEqual(r.returncode, 2)
        self.assertIsNone(self.conf("mode"))

    def test_lang_switch_and_auto(self):
        self.assertEqual(self.run_hub("lang", "en").returncode, 0)
        self.assertEqual(self.conf("lang"), "en")
        self.assertEqual(self.run_hub("lang", "auto").returncode, 0)
        self.assertIsNone(self.conf("lang"))

    def test_doctor_clean(self):
        r = self.run_hub("doctor")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("沒有要修的項目", r.stdout)
        self.assertIn("[選用] 狀態列", r.stdout)

    def test_doctor_legacy_and_disabled_plugin(self):
        (self.home / ".claude" / "hooks" / "smart-agent-route").mkdir(parents=True)
        (self.home / ".claude" / "settings.json").write_text(json.dumps(
            {"enabledPlugins": {"chutora@chutora": False}, "autoCompactWindow": 153000}))
        r = self.run_hub("doctor", lang="en")
        self.assertEqual(r.returncode, 1)
        self.assertIn("[FIX] old smart-agent-route", r.stdout)
        self.assertIn("[FIX] hooks: the plugin is installed but disabled", r.stdout)
        self.assertIn("[OK] autoCompactWindow: 153000", r.stdout)

    def test_doctor_is_read_only(self):
        before = sorted(str(p) for p in self.home.rglob("*"))
        self.run_hub("doctor")
        self.assertEqual(before, sorted(str(p) for p in self.home.rglob("*")))

    def test_unknown_command(self):
        self.assertEqual(self.run_hub("fly").returncode, 2)


    def test_trim_switch_and_stats(self):
        r = self.run_hub("trim", "off")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.conf("trim"), "off")
        self.assertIn("噪音輸出瘦身：關閉", self.run_hub().stdout)
        r = self.run_hub("trim", "on")
        self.assertEqual(r.returncode, 0)
        self.assertIsNone(self.conf("trim"))
        (self.home / ".claude" / "chutora" / "trim-stats.json").write_text(json.dumps({"total_chars": 40000}))
        out = self.run_hub("trim").stdout
        self.assertIn("10,000 token", out)
        self.assertIn("關閉", self.run_hub(CHUTORA_TRIM="0").stdout)
        self.assertEqual(self.run_hub("trim", "maybe").returncode, 2)

    def test_mode_changes_trim_threshold(self):
        self.run_hub("mode", "economy")
        self.assertIn("3000 字元", self.run_hub().stdout)

    def test_guard_and_observe_status_and_switches(self):
        out = self.run_hub().stdout
        self.assertIn("危險守門（實驗中）：開啟", out)
        self.assertIn("觀察紀錄（實驗中）：開啟", out)
        self.assertIn("/chutora guard on|off|rules", out)
        self.assertEqual(self.run_hub("guard", "off").returncode, 0)
        self.assertEqual(self.conf("guard"), "off")
        self.assertEqual(self.run_hub("observe", "off").returncode, 0)
        out = self.run_hub().stdout
        self.assertIn("危險守門（實驗中）：關閉（/chutora guard off）", out)
        self.assertIn("觀察紀錄（實驗中）：關閉", out)
        self.run_hub("guard", "on")
        self.assertIsNone(self.conf("guard"))
        self.assertIn("關閉（CHUTORA_OBSERVE=0）", self.run_hub(CHUTORA_OBSERVE="0").stdout)
        r = self.run_hub("guard", "rules", lang="en")
        self.assertIn("rm-catastrophe [deny]", r.stdout)

    def test_mcp_trim_exclude_include_text(self):
        self.assertIn("純文字／Markdown 不動", self.run_hub().stdout)
        self.assertEqual(self.run_hub("mcp-trim", "exclude", "Claude_Docs").returncode, 0)
        self.assertEqual(self.conf("mcp-trim-exclude"), "Claude_Docs")
        self.assertIn("mcp__Claude_Docs__", self.run_hub().stdout)
        self.run_hub("mcp-trim", "exclude", "slack")
        self.assertTrue((self.home / ".claude" / "chutora" / "mcp-trim-exclude.bak").exists())
        self.assertEqual(self.run_hub("mcp-trim", "include", "mcp__Claude_Docs__").returncode, 0)
        self.assertEqual(self.conf("mcp-trim-exclude"), "slack")
        self.assertEqual(self.run_hub("mcp-trim", "exclude", "bad name;rm").returncode, 2)
        self.run_hub("mcp-trim", "text", "on")
        self.assertEqual(self.conf("mcp-trim-text"), "on")
        self.run_hub("mcp-trim", "text", "off")
        self.assertIsNone(self.conf("mcp-trim-text"))

    def test_doctor_flags_bad_guard_rules(self):
        c = self.home / ".claude" / "chutora"
        c.mkdir(parents=True)
        (c / "always-ask").write_text("([broken\n\\bnpm publish\\b\n")
        r = self.run_hub("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("[要修] 危險守門", r.stdout)
        self.assertIn("([broken", r.stdout)


if __name__ == "__main__":
    unittest.main()
