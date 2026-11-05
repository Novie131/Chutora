"""中英雙語：語言判斷優先順序，以及各 hook 的英文／中文訊息。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"


class LangBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.data = self.tmp / "data"

    def env(self, **kw):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CHUTORA_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "CLAUDE_PLUGIN_ROOT")}
        env["HOME"] = str(self.home)
        env["CLAUDE_PLUGIN_DATA"] = str(self.data)
        env["CHUTORA_WEEKLY"] = "0"
        env.update(kw)
        return env

    def lang(self, **kw):
        code = f"import sys; sys.path.insert(0, {str(HOOKS)!r}); from compact import lang; print(lang())"
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env=self.env(**kw), timeout=30).stdout.strip()


class LangPickTest(LangBase):
    def test_default_is_english(self):
        self.assertEqual(self.lang(), "en")

    def test_locale_zh(self):
        self.assertEqual(self.lang(LANG="zh_TW.UTF-8"), "zh")

    def test_lc_all_wins_over_lang(self):
        self.assertEqual(self.lang(LANG="zh_TW.UTF-8", LC_ALL="en_US.UTF-8"), "en")

    def test_file_wins_over_locale(self):
        (self.home / ".claude" / "chutora").mkdir()
        (self.home / ".claude" / "chutora" / "lang").write_text("zh\n")
        self.assertEqual(self.lang(LANG="en_US.UTF-8"), "zh")

    def test_env_wins_over_file(self):
        (self.home / ".claude" / "chutora").mkdir()
        (self.home / ".claude" / "chutora" / "lang").write_text("zh\n")
        self.assertEqual(self.lang(CHUTORA_LANG="en"), "en")


class HookMessagesTest(LangBase):
    def transcript(self, n):
        p = self.tmp / "t.jsonl"
        p.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": n}}}) + "\n")
        return p

    def context_check(self, **kw):
        r = subprocess.run([sys.executable, str(HOOKS / "context-check.py")],
                           input=json.dumps({"transcript_path": str(self.transcript(5000))}),
                           capture_output=True, text=True, env=self.env(CONTEXT_REMIND_TOKENS="1000", **kw), timeout=30)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_context_check_en(self):
        self.assertIn("past the 1k reminder threshold", self.context_check(CHUTORA_LANG="en"))

    def test_context_check_zh(self):
        self.assertIn("已超過 1k 的提醒門檻", self.context_check(CHUTORA_LANG="zh"))

    def loop(self, **kw):
        out = ""
        for i in range(3):
            r = subprocess.run([sys.executable, str(HOOKS / "post-tool.py")],
                               input=json.dumps({"session_id": "s", "tool_name": "Bash",
                                                 "tool_response": {"is_error": True, "stderr": f"Error: boom {i}"}}),
                               capture_output=True, text=True, env=self.env(**kw), timeout=30)
            out = r.stdout
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def test_loop_guard_en(self):
        self.assertIn("The same error has repeated 3 times", self.loop(CHUTORA_LANG="en"))

    def test_loop_guard_zh(self):
        self.assertIn("偵測到同一個錯誤重複出現 3 次", self.loop(CHUTORA_LANG="zh"))

    def statusline(self, **kw):
        r = subprocess.run([sys.executable, str(HOOKS / "statusline.py")],
                           input=json.dumps({"model": {"display_name": "Opus"}, "context_window": {"total_input_tokens": 5000}}),
                           capture_output=True, text=True, env=self.env(**kw), timeout=30)
        return r.stdout

    def test_statusline_en(self):
        self.assertIn("remind 100k", self.statusline(CHUTORA_LANG="en"))

    def test_statusline_zh(self):
        self.assertIn("提醒 100k", self.statusline(CHUTORA_LANG="zh"))


class SessionStartLangTest(LangBase):
    def run_hook(self, **kw):
        proj = self.tmp / "proj"
        proj.mkdir(exist_ok=True)
        return subprocess.run(["sh", str(HOOKS / "session-start.sh")], capture_output=True, text=True,
                              env=self.env(CLAUDE_PROJECT_DIR=str(proj), **kw), cwd=proj,
                              stdin=subprocess.DEVNULL, timeout=30)

    def mark_done(self):
        self.data.mkdir(exist_ok=True)
        (self.data / ".route-setup-done").touch()

    def test_english_guide_and_prompt(self):
        d = json.loads(self.run_hook(CHUTORA_LANG="en").stdout)
        self.assertIn("chutora is ready to use", d["systemMessage"])
        self.assertIn("/chutora", d["systemMessage"])
        ctx = d["hookSpecificOutput"]["additionalContext"]
        self.assertIn("delegation conventions for this session", ctx)
        self.assertIn("Current mode: balanced", ctx)

    def test_chinese_guide(self):
        self.mark_done()
        out = self.run_hook(CHUTORA_LANG="zh").stdout
        self.assertIn("本 session 的分工慣例", out)
        self.assertIn("目前模式：平衡", out)

    def test_mode_file(self):
        self.mark_done()
        (self.home / ".claude" / "chutora").mkdir()
        (self.home / ".claude" / "chutora" / "mode").write_text("economy\n")
        out = self.run_hook(CHUTORA_LANG="en").stdout
        self.assertIn("Current mode: economy", out)
        self.assertNotIn("Current mode: balanced", out)

    def test_bad_mode_falls_back(self):
        self.mark_done()
        (self.home / ".claude" / "chutora").mkdir()
        (self.home / ".claude" / "chutora" / "mode").write_text("../../etc\n")
        self.assertIn("目前模式：平衡", self.run_hook(CHUTORA_LANG="zh").stdout)

    def test_lang_file_used(self):
        self.mark_done()
        (self.home / ".claude" / "chutora").mkdir()
        (self.home / ".claude" / "chutora" / "lang").write_text("zh\n")
        self.assertIn("本 session 的分工慣例", self.run_hook(LANG="en_US.UTF-8").stdout)

    def test_every_mode_file_exists(self):
        for m in ("economy", "balanced", "quality"):
            for l in ("zh", "en"):
                self.assertTrue((HOOKS / "modes" / f"{m}.{l}.md").is_file(), (m, l))


if __name__ == "__main__":
    unittest.main()
