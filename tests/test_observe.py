"""觀察 hook（observe.py）、專案 id（projectid.py）、遮罩（redact.py）與變更紀錄（changes.py）的測試。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
OBSERVE = HOOKS / "observe.py"
GUARD = HOOKS / "guard.py"
sys.path.insert(0, str(HOOKS))

import changes  # noqa: E402
import projectid  # noqa: E402
from redact import redact, short  # noqa: E402


class ObserveTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.proj = self.home / "proj"
        self.proj.mkdir(parents=True)

    def env(self, extra=None):
        e = dict(os.environ, HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG="zh")
        for k in ("CHUTORA_OBSERVE", "CHUTORA_OBSERVE_MAX_MB"):
            e.pop(k, None)
        e.update(extra or {})
        return e

    def hook(self, data, script=OBSERVE, env=None):
        base = {"session_id": "s1", "cwd": str(self.proj)}
        base.update(data)
        r = subprocess.run([sys.executable, str(script)], input=json.dumps(base), capture_output=True, text=True,
                           env=self.env(env), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def obs(self):
        files = list((self.home / ".claude" / "chutora" / "projects").glob("*/observations.jsonl"))
        if not files:
            return []
        self.assertEqual(len(files), 1)
        return [json.loads(x) for x in files[0].read_text().splitlines()]

    def test_tool_ok_no_output_and_no_big_text(self):
        big = "x" * 50000
        out = self.hook({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                        "tool_input": {"command": "npm test"}, "tool_response": {"stdout": big, "stderr": ""}})
        self.assertEqual(out, "")  # 不輸出 → 不增加 token
        rec = self.obs()[0]
        self.assertEqual(rec["signal"], "tool_ok")
        self.assertEqual(rec["agent"], "main")
        self.assertEqual(rec["summary"], "npm test")
        self.assertGreater(rec["out_chars"], 50000)
        self.assertLess(len(json.dumps(rec)), 400)

    def test_failures_and_repeat(self):
        for _ in range(3):
            self.hook({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
                      "tool_input": {"command": "pytest"}, "error": "Error: ModuleNotFoundError: No module named foo (line 12)"})
        sig = [r["signal"] for r in self.obs()]
        self.assertEqual(sig, ["tool_fail", "repeat_error", "repeat_error"])
        self.assertEqual(self.obs()[-1]["count"], 3)

    def test_subagent_and_agent_type(self):
        self.hook({"hook_event_name": "SubagentStop", "agent_type": "chutora:worker", "agent_id": "a1",
                  "last_assistant_message": "Done. Changed 3 files. " + "detail " * 500})
        self.hook({"hook_event_name": "PostToolUse", "agent_type": "Explore", "agent_id": "a2", "tool_name": "Read",
                  "tool_input": {"file_path": str(self.proj / "src" / "a.py")}, "tool_response": {"content": "..."}})
        a, b = self.obs()
        self.assertEqual(a["signal"], "delegation_result")
        self.assertEqual(a["agent"], "worker")
        self.assertLessEqual(len(a["summary"]), 200)
        self.assertEqual(b["agent"], "Explore")
        self.assertEqual(b["summary"], os.path.join("src", "a.py"))

    def test_user_signals(self):
        for p in ("不對，我不是要這個", "that's not what I asked for", "2", "幫我把 README 改短一點", "選 B"):
            self.hook({"hook_event_name": "UserPromptSubmit", "prompt": p})
        sig = [(r["signal"], r.get("summary")) for r in self.obs()]
        self.assertEqual(sig[0][0], "user_correction")
        self.assertEqual(sig[1][0], "user_correction")
        self.assertEqual(sig[2], ("user_choice", "2"))
        self.assertEqual(sig[3], ("user_prompt", None))  # 一般提示只記長度
        self.assertEqual(sig[4][0], "user_choice")

    def test_ask_user_question_choice(self):
        self.hook({"hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion",
                  "tool_input": {"questions": [{"question": "範圍？"}]},
                  "tool_response": {"answers": {"範圍？": "只改文件"}}})
        rec = self.obs()[0]
        self.assertEqual(rec["signal"], "user_choice")
        self.assertIn("只改文件", rec["summary"])

    def test_secrets_masked(self):
        self.hook({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                  "tool_input": {"command": "curl -H 'Authorization: Bearer abcdefghijklmnop1234' https://u:pw12345@x.io "
                                            "&& export API_KEY=sk-ant-REALSECRETVALUE123456 password=hunter22"},
                  "tool_response": {"stdout": "ok"}})
        text = json.dumps(self.obs())
        for s in ("abcdefghijklmnop1234", "pw12345", "REALSECRETVALUE", "hunter22"):
            self.assertNotIn(s, text)

    def test_switch_off(self):
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "hi"}, env={"CHUTORA_OBSERVE": "0"})
        self.assertEqual(self.obs(), [])
        self.assertFalse((self.home / ".claude" / "chutora" / "projects").exists())
        cfg = self.home / ".claude" / "chutora"
        cfg.mkdir(parents=True)
        (cfg / "observe").write_text("off\n")
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "hi"})
        self.assertEqual(self.obs(), [])

    def test_rotation(self):
        for i in range(30):
            self.hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": f"echo {i} " + "y" * 120},
                      "tool_response": {"stdout": "ok"}}, env={"CHUTORA_OBSERVE_MAX_MB": "0.001"})
        d = next((self.home / ".claude" / "chutora" / "projects").glob("*"))
        arch = sorted((d / "archive").glob("observations-*.jsonl"))
        self.assertTrue(1 <= len(arch) <= 5)
        self.assertLess((d / "observations.jsonl").stat().st_size, 2048)
        self.assertTrue((d / "meta.json").exists())

    def test_guard_approval_resolved(self):
        (self.proj / "claude-memory").mkdir()
        g = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git reset --hard"},
             "tool_use_id": "toolu_ok1", "permission_mode": "default"}
        self.assertIn("ask", self.hook(g, script=GUARD))
        self.hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "git reset --hard"},
                  "tool_use_id": "toolu_ok1", "tool_response": {"stdout": "HEAD is now at abc"}})
        items = changes.read(path=str(self.proj / "claude-memory" / "changes.jsonl"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["user_response"], "approved")
        sig = [r["signal"] for r in self.obs()]
        self.assertEqual(sig, ["guard_ask", "tool_ok"])
        self.assertEqual(self.obs()[0]["rules"], ["git-reset-hard"])

    def test_bad_input_quiet(self):
        for raw in ("", "x", "[1]"):
            r = subprocess.run([sys.executable, str(OBSERVE)], input=raw, capture_output=True, text=True,
                               env=self.env(), timeout=30)
            self.assertEqual((r.returncode, r.stdout), (0, ""))


class ProjectIdTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._env = os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.addCleanup(lambda: self._env is not None and os.environ.__setitem__("CLAUDE_PROJECT_DIR", self._env))

    def repo(self, name, url=None):
        r = self.root / name
        (r / ".git").mkdir(parents=True)
        cfg = "[core]\n\tbare = false\n"
        if url:
            cfg += f'[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
        (r / ".git" / "config").write_text(cfg)
        (r / "sub").mkdir()
        return r

    def test_remote_hash_same_across_clones(self):
        a = self.repo("a", "git@github.com:Novie131/chutora.git")
        b = self.repo("b", "https://user:tok@github.com/Novie131/Chutora")
        ia, ib = projectid.project_info(str(a / "sub")), projectid.project_info(str(b))
        self.assertEqual(ia["id"], ib["id"])
        self.assertEqual(len(ia["id"]), 12)
        self.assertEqual(ia["remote"], "github.com/novie131/chutora")
        self.assertNotIn("tok", json.dumps(ib))

    def test_no_remote_uses_root_path(self):
        a = self.repo("c")
        self.assertEqual(projectid.project_info(str(a / "sub"))["root"], str(a))
        self.assertNotEqual(projectid.project_id(str(a)), projectid.project_id(str(self.repo("d"))))

    def test_not_a_repo_and_env(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(projectid.project_info(str(plain))["root"], str(plain))
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.repo("e", "https://gitlab.com/x/y.git"))
        try:
            self.assertEqual(projectid.project_info(str(plain))["remote"], "gitlab.com/x/y")
        finally:
            del os.environ["CLAUDE_PROJECT_DIR"]

    def test_worktree_gitfile(self):
        main = self.repo("m", "https://github.com/a/b.git")
        wt_git = main / ".git" / "worktrees" / "w"
        wt_git.mkdir(parents=True)
        (wt_git / "commondir").write_text("../..\n")
        wt = self.root / "w"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {wt_git}\n")
        self.assertEqual(projectid.project_id(str(wt)), projectid.project_id(str(main)))


class RedactTest(unittest.TestCase):
    def test_patterns(self):
        cases = ["sk-ant-api03-ABCDEFGHIJKLMNOPQRST", "ghp_ABCDEFGHIJKLMNOPQRSTUVWX12", "AKIAABCDEFGHIJKLMNOP",
                 "xoxb-1234567890-abcdefghij", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk",
                 "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"]
        for c in cases:
            self.assertNotIn(c[-10:], redact("x " + c + " y"), c)
        self.assertEqual(redact("password=hunter22 user=bob"), "password=[REDACTED] user=bob")
        self.assertIn("[REDACTED]", redact("https://bob:s3cretpw@host/x"))
        self.assertEqual(redact("git push origin main"), "git push origin main")

    def test_short_cuts_after_masking(self):
        s = short("a" * 150 + " sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX", 160)
        self.assertNotIn("ABCDEFGHIJ", s)
        self.assertLessEqual(len(s), 160)


class ChangesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "proj"
        self.proj.mkdir()

    def test_record_update_read(self):
        (self.proj / "claude-memory").mkdir()
        p = changes.changes_path(str(self.proj))
        self.assertEqual(p, str(self.proj / "claude-memory" / "changes.jsonl"))
        rid = changes.record("settings_edit", "changed autoCompactWindow token=abcd1234secret",
                             restore_point="~/.claude/settings.json.bak-1", project_dir=str(self.proj))
        changes.record("guard_ask", "x", project_dir=str(self.proj))
        self.assertTrue(changes.update(rid, project_dir=str(self.proj), user_response="undone", notified=True))
        items = changes.read(project_dir=str(self.proj))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["user_response"], "undone")
        self.assertTrue(items[0]["notified"])
        self.assertEqual(items[0]["restore_point"], "~/.claude/settings.json.bak-1")
        self.assertNotIn("abcd1234secret", json.dumps(items))
        self.assertEqual(len(changes.read(project_dir=str(self.proj), action="guard_ask")), 1)
        self.assertEqual(changes.read(project_dir=str(self.proj), limit=1)[0]["action"], "guard_ask")

    def test_fallback_to_auto_memory(self):
        tp = Path(self._tmp.name) / ".claude" / "projects" / "-x" / "s.jsonl"
        self.assertEqual(changes.changes_path(str(self.proj), str(tp)), str(tp.parent / "memory" / "changes.jsonl"))
        p = changes.changes_path(str(self.proj))
        self.assertTrue(p.endswith(os.path.join("memory", "changes.jsonl")))
        self.assertIn(os.path.join(".claude", "projects"), p)

    def test_broken_lines_skipped(self):
        (self.proj / "claude-memory").mkdir()
        f = self.proj / "claude-memory" / "changes.jsonl"
        f.write_text('not json\n{"id": "a", "action": "x"}\n{"id": "zz", "update": {"user_response": "y"}}\n')
        self.assertEqual([x["id"] for x in changes.read(project_dir=str(self.proj))], ["a"])


if __name__ == "__main__":
    unittest.main()
