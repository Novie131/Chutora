"""駕駛艙穩定版：deck.py 白話翻譯、activity.py 紀錄、statusline.py 工作中／閒置顯示、本次 token 統計。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
sys.path.insert(0, str(HOOKS))
import deck  # noqa: E402

ANSI = __import__("re").compile(r"\033\[[0-9;]*m")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self._old = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old

    def env(self, **kw):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("CHUTORA_", "LC_", "LANG", "COLUMNS"))}
        e.update(HOME=str(self.home), CHUTORA_LANG="zh")
        e.update(kw)
        return e

    def hook(self, payload, **kw):
        return subprocess.run([sys.executable, str(HOOKS / "activity.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env(**kw), timeout=30)

    def sl(self, payload, **kw):
        r = subprocess.run([sys.executable, str(HOOKS / "statusline.py")], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env(**kw), timeout=30)
        return ANSI.sub("", r.stdout).rstrip("\n")


class PlainTest(unittest.TestCase):
    def test_bash_rules(self):
        cases = {"npm test -- checkout": "跑測試", "cd app && pnpm install": "安裝套件", "python3 -m pytest -q": "跑測試",
                 "git status": "看 git 狀態", "cargo build --release": "建置", "FOO=1 go test ./...": "跑測試",
                 "rm -rf build": "刪除檔案", "some-unknown-tool --x": "執行指令"}
        for cmd, want in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(deck.plain("Bash", {"command": cmd}, "zh")[0], want)
        self.assertEqual(deck.plain("Bash", {"command": "npm test"}, "en")[0], "Run tests")
        self.assertEqual(deck.plain("Bash", {"command": "frob", "description": "Frob the widgets"}, "en")[0], "Frob the widgets")

    def test_tools(self):
        self.assertEqual(deck.plain("Read", {"file_path": "/a/src/checkout.ts"}, "zh"), ("讀 checkout.ts", "Read /a/src/checkout.ts"))
        self.assertEqual(deck.plain("Grep", {"pattern": "TypeError", "path": "/a/src"}, "zh")[0], "在 src 裡找「TypeError」")
        self.assertEqual(deck.plain("Agent", {"subagent_type": "chutora:worker", "description": "修 checkout"}, "zh")[0], "派工給 worker：修 checkout")
        self.assertEqual(deck.plain("WebFetch", {"url": "https://docs.example.com/x"}, "en")[0], "Read web page docs.example.com")
        self.assertEqual(deck.plain("mcp__slack__send_message", {}, "zh")[0], "用 slack 的 send_message")
        todos = {"todos": [{"status": "completed"}, {"status": "in_progress"}, {"status": "pending"}]}
        self.assertEqual(deck.plain("TodoWrite", todos, "zh")[0], "更新待辦清單（1/3）")
        self.assertEqual(deck.plain("Frobnicate", {}, "zh")[0], "Frobnicate")

    def test_never_raises(self):
        for inp in (None, [], "x", {"command": None}):
            deck.plain("Bash", inp, "zh")
            deck.plain("Grep", inp, "en")


class ActivityTest(Base):
    def payload(self, ev, **kw):
        d = {"hook_event_name": ev, "session_id": "s1", "transcript_path": "", "cwd": "/w",
             "tool_name": "Bash", "tool_input": {"command": "npm test"}, "tool_use_id": "t1"}
        d.update(kw)
        return d

    def test_lifecycle_and_quiet(self):
        r = self.hook(self.payload("PreToolUse"))
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        st = deck.load("s1")
        self.assertEqual(st["running"]["t1"]["agent"], "main")
        self.assertEqual(st["running"]["t1"]["summary"]["command"], "npm test")
        self.hook(self.payload("PostToolUse", tool_response={"stdout": "ok"}))
        st = deck.load("s1")
        self.assertEqual(st["running"], {})
        self.assertTrue(st["last"]["ok"])
        self.hook(self.payload("PreToolUse", tool_use_id="t2"))
        self.hook(self.payload("PostToolUseFailure", tool_use_id="t2", error="boom"))
        self.assertFalse(deck.load("s1")["last"]["ok"])

    def test_subagent_label_and_model(self):
        self.hook({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "chutora:worker"})
        self.hook(self.payload("PreToolUse", agent_id="a1", agent_type="chutora:worker"))
        item = deck.load("s1")["running"]["t1"]
        self.assertEqual((item["agent"], item["model"]), ("worker", "Sonnet"))
        self.hook({"hook_event_name": "SubagentStop", "session_id": "s1", "agent_id": "a1", "agent_type": "chutora:worker",
                   "stop_hook_active": False, "agent_transcript_path": ""})
        st = deck.load("s1")
        self.assertEqual(st["running"], {})
        self.assertIn("end", st["agents"]["a1"])

    def test_off_switch_and_bad_input(self):
        self.hook(self.payload("PreToolUse"), CHUTORA_ACTIVITY="0")
        self.assertEqual(deck.load("s1"), {})
        for raw in ("not json", "[]", "null"):
            r = subprocess.run([sys.executable, str(HOOKS / "activity.py")], input=raw, capture_output=True, text=True,
                               env=self.env(), timeout=30)
            self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_unsafe_session_id_ignored(self):
        self.hook(self.payload("PreToolUse", session_id="../../etc"))
        self.assertFalse((self.home / "etc").exists())

    def test_saved_per_session(self):
        deck.add_saved("s1", 4000, "bash")
        deck.add_saved("s1", 800, "dedup")
        self.assertEqual(deck.saved_chars(deck.load("s1")), 4800)


class TokensTest(Base):
    def write(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def row(self, mid, model, inp=100, cw=0, out=10, cr=5000):
        return {"type": "assistant", "requestId": "r" + mid,
                "message": {"id": mid, "model": model, "usage": {"input_tokens": inp, "cache_creation_input_tokens": cw,
                                                                  "output_tokens": out, "cache_read_input_tokens": cr}}}

    def test_dedupe_subagents_incremental(self):
        tp = self.home / "proj" / "s1.jsonl"
        self.write(tp, [self.row("m1", "claude-opus-5-5", 100, 2000, 50), self.row("m1", "claude-opus-5-5", 100, 2000, 50)])
        self.write(self.home / "proj" / "s1" / "subagents" / "agent-a1.jsonl", [self.row("m2", "claude-sonnet-5-5", 10, 500, 5)])
        got = deck.session_tokens(str(tp), "s1")
        self.assertEqual(got["by_model"], {"Opus": 2150, "Sonnet": 515})
        self.assertEqual(got["total"], 2665)
        self.write(tp, [self.row("m3", "claude-opus-5-5", 0, 0, 100)])
        self.assertEqual(deck.session_tokens(str(tp), "s1")["by_model"]["Opus"], 2250)
        self.assertIsNone(deck.session_tokens(str(self.home / "missing.jsonl"), "s1"))


class StatuslineDeckTest(Base):
    def payload(self, n=95000, **kw):
        d = {"model": {"display_name": "Opus"}, "context_window": {"total_input_tokens": n}, "session_id": "s1",
             "transcript_path": ""}
        d.update(kw)
        return d

    def test_idle_without_activity_keeps_old_format(self):
        self.assertEqual(self.sl(self.payload(50000)), "Opus │ ctx 50k │ 提醒 100k")

    def test_running_subagent(self):
        self.hook({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "worker"})
        self.hook({"hook_event_name": "PreToolUse", "session_id": "s1", "agent_id": "a1", "agent_type": "worker",
                   "tool_name": "Bash", "tool_input": {"command": "npm test"}, "tool_use_id": "t1"})
        deck.add_saved("s1", 32000, "bash")
        out = self.sl(self.payload())
        self.assertTrue(out.startswith("▶ worker·Sonnet 跑測試 npm test · "), out)
        self.assertIn("瘦身省≈8k", out)
        self.assertTrue(out.endswith("ctx 95k/100k"), out)

    def test_running_main_english_and_narrow(self):
        self.hook({"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Read",
                   "tool_input": {"file_path": "/x/README.md"}, "tool_use_id": "t1"})
        deck.add_saved("s1", 32000, "bash")
        out = self.sl(self.payload(), CHUTORA_LANG="en")
        self.assertTrue(out.startswith("▶ Opus Read README.md · "), out)
        narrow = self.sl(self.payload(), CHUTORA_LANG="en", CHUTORA_STATUS_WIDTH="40")
        self.assertNotIn("trimmed", narrow)
        self.assertLessEqual(len(narrow), 40)

    def test_idle_with_tokens(self):
        tp = self.home / "proj" / "s1.jsonl"
        tp.parent.mkdir(parents=True)
        tp.write_text(json.dumps({"type": "assistant", "requestId": "r", "message": {
            "id": "m", "model": "claude-opus-5-5", "usage": {"input_tokens": 42000, "output_tokens": 0}}}) + "\n")
        out = self.sl(self.payload(50000, transcript_path=str(tp)))
        self.assertEqual(out, "Opus │ ctx 50k │ 提醒 100k │ 本次 42k tok")


if __name__ == "__main__":
    unittest.main()
