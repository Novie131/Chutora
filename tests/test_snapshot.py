"""自動交接快照（snapshot.py）與 SessionStart 的一行指標。一律用暫存 HOME 與暫存 git repo。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
SNAP = HOOKS / "snapshot.py"


def jl(p, rows):
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def tool(name, **inp):
    return {"type": "assistant", "message": {"id": "m" + name, "content": [{"type": "tool_use", "name": name, "input": inp}]}}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.proj = self.tmp / "proj"
        self.proj.mkdir()

    def env(self, **kw):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("CHUTORA_", "LC_", "LANG", "CLAUDE_"))}
        e.update(HOME=str(self.home), CHUTORA_LANG="zh", CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_WEEKLY="0")
        e.update(kw)
        return e

    def git(self, *a):
        subprocess.run(["git", "-C", str(self.proj), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                       check=True, capture_output=True)

    def transcript(self, rows=None):
        tp = self.tmp / "t.jsonl"
        jl(tp, rows if rows is not None else [
            {"type": "user", "message": {"content": "請幫我改 login 的錯誤處理"}},
            tool("Edit", file_path="/p/a.py"), tool("Write", file_path="/p/b.py"), tool("Edit", file_path="/p/a.py"),
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            tool("TodoWrite", todos=[{"content": "舊的", "status": "pending"}]),
            tool("TodoWrite", todos=[{"content": "寫測試", "status": "completed"}, {"content": "跑 lint", "status": "in_progress"},
                                     {"content": "發 PR", "status": "pending"}]),
        ])
        return tp

    def run_snap(self, payload=None, args=(), **kw):
        raw = payload if isinstance(payload, str) else json.dumps(payload if payload is not None else {})
        return subprocess.run([sys.executable, str(SNAP), *args], input=raw, capture_output=True, text=True,
                              env=self.env(**kw), cwd=str(self.proj), timeout=30)


class SnapshotTest(Base):
    def test_writes_to_claude_memory_without_output(self):
        (self.proj / "claude-memory").mkdir()
        (self.proj / "claude-memory" / "handoff.md").write_text("原本的交接\n")
        self.git("init", "-q", "-b", "feat/x")
        (self.proj / "f").write_text("1")
        self.git("add", "f")
        for i in range(4):
            self.git("commit", "-q", "--allow-empty", "-m", f"第 {i} 個 commit")
        r = self.run_snap({"transcript_path": str(self.transcript()), "cwd": str(self.proj), "hook_event_name": "PreCompact"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        t = (self.proj / "claude-memory" / "handoff-auto.md").read_text()
        self.assertRegex(t.splitlines()[0], r"^<!-- time: \d{4}-\d\d-\d\d \d\d:\d\d -->$")
        self.assertIn("feat/x", t)
        self.assertIn("第 3 個 commit", t)
        self.assertIn("第 1 個 commit", t)
        self.assertNotIn("第 0 個 commit", t)  # 只留最近 3 個
        self.assertIn("請幫我改 login 的錯誤處理", t)
        self.assertEqual(t.count("/p/a.py"), 1)
        self.assertIn("- /p/b.py", t)
        self.assertIn("- [x] 寫測試", t)
        self.assertIn("- [~] 跑 lint", t)
        self.assertNotIn("舊的", t)
        self.assertEqual((self.proj / "claude-memory" / "handoff.md").read_text(), "原本的交接\n")  # 不動 handoff.md

    def test_prompts_limited_truncated_and_redacted(self):
        rows = [{"type": "user", "message": {"content": f"問題{i} " + "字" * 300}} for i in range(7)]
        rows.append({"type": "user", "message": {"content": "token=sk-ant-abcdefghijklmnopqrstuvwxyz0123 請用這個"}})
        rows.append({"type": "user", "message": {"content": "<command-name>/x</command-name>"}})
        self.run_snap({"transcript_path": str(self.transcript(rows))})
        d = self.home / ".claude" / "chutora" / "handoff"
        files = list(d.glob("*.md"))
        self.assertEqual(len(files), 1)  # 沒有 claude-memory/：放到使用者層級
        t = files[0].read_text()
        self.assertNotIn("問題0", t)
        self.assertNotIn("問題2 ", t)
        self.assertIn("問題3 ", t)
        self.assertNotIn("字" * 201, t)
        self.assertNotIn("abcdefghijklmnop", t)
        self.assertIn("[REDACTED]", t)
        self.assertNotIn("command-name", t)
        self.assertEqual(sum(1 for ln in t.splitlines() if ln.startswith("- 問題") or ln.startswith("- [REDACTED]") or "REDACTED" in ln), 5)

    def test_empty_conversation_does_not_overwrite(self):
        (self.proj / "claude-memory").mkdir()
        keep = self.proj / "claude-memory" / "handoff-auto.md"
        keep.write_text("<!-- time: 2026-01-01 00:00 -->\n舊快照\n")
        self.run_snap({"transcript_path": str(self.transcript([tool("Edit", file_path="/x")]))})
        self.assertIn("舊快照", keep.read_text())

    def test_always_exit_0_and_silent(self):
        for raw in ("not json", "", "[]", "null", json.dumps({"transcript_path": "/nonexistent"}),
                    json.dumps({"transcript_path": 5})):
            r = self.run_snap(raw)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), raw)
        # 目的地無法寫入
        (self.proj / "claude-memory").mkdir()
        os.chmod(self.proj / "claude-memory", 0o500)
        self.addCleanup(os.chmod, self.proj / "claude-memory", 0o700)
        r = self.run_snap({"transcript_path": str(self.transcript())})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_english_labels(self):
        self.run_snap({"transcript_path": str(self.transcript())}, CHUTORA_LANG="en")
        t = next((self.home / ".claude" / "chutora" / "handoff").glob("*.md")).read_text()
        self.assertIn("## Recent user prompts", t)

    def test_hooks_registered(self):
        d = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
        for ev in ("PreCompact", "SessionEnd"):
            self.assertIn("snapshot.py", d[ev][0]["hooks"][0]["command"])


class PointerTest(Base):
    def start(self, **kw):
        r = subprocess.run(["sh", str(HOOKS / "session-start.sh")], input=json.dumps({"session_id": "s1"}),
                           capture_output=True, text=True, env=self.env(**kw), cwd=str(self.proj), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.lstrip().startswith("{") else r.stdout

    def test_no_snapshot_no_line(self):
        self.assertNotIn("自動交接快照", self.start())

    def test_pointer_is_one_line_with_path_and_time(self):
        (self.proj / "claude-memory").mkdir()
        snap = self.proj / "claude-memory" / "handoff-auto.md"
        snap.write_text("<!-- time: 2026-11-09 14:03 -->\n# 自動交接快照\n" + "很長的內容\n" * 50)
        out = self.start()
        lines = [ln for ln in out.splitlines() if "自動交接快照" in ln]
        self.assertEqual(lines, [f"自動交接快照：{snap}（2026-11-09 14:03）"])
        self.assertNotIn("很長的內容", out)
        self.assertIn("Auto handoff snapshot: %s (2026-11-09 14:03)" % snap, self.start(CHUTORA_LANG="en"))

    def test_pointer_without_claude_memory_uses_user_level_file(self):
        self.run_snap({"transcript_path": str(self.transcript())})
        f = next((self.home / ".claude" / "chutora" / "handoff").glob("*.md"))
        out = self.start()
        self.assertIn(f"自動交接快照：{f}（", out)


if __name__ == "__main__":
    unittest.main()
