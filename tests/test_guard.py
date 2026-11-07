"""危險守門 hook（plugins/chutora/hooks/guard.py）的測試。一律用暫存 HOME 與暫存專案。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "plugins" / "chutora" / "hooks" / "guard.py"

# 一般指令：一律不能攔
SAFE = [
    "git push origin feat/x",
    "git push -u origin feat/new-thing",
    "git push origin feat/main-menu",
    "git status && git diff",
    "rm -rf node_modules",
    "rm -rf build/",
    "rm -rf node_modules dist .cache && npm install",
    "rm -f src/old.py",
    "find . -name '*.pyc' -delete",
    "rm -rf /tmp/chutora-guard-test-scratch",
    "tmp=$(mktemp -d); cd $tmp && rm -rf \"$tmp\"",
    "npm install && npm test",
    "python3 -m unittest discover -s tests",
    "cat .env.example",
    "cp .env.example .env.sample",
    "git commit -m 'docs: mention git reset --hard, rm -rf / and DROP TABLE'",
    "echo \"git push --force origin main\"",
    "grep -rn \"DROP TABLE\" migrations/",
    "git log --grep='reset --hard'",
    "terraform plan",
    "kubectl get pods",
    "git reset --soft HEAD~1",
    "git reset HEAD file.py",
    "git clean -n",
    "cat ~/.claude/settings.json",
    "cp ~/.claude/settings.json ./settings-backup.json",
    "jq .hooks ~/.claude/settings.json",
    "python3 skills/chutora-hub/chutora.py mode economy",
    "python3 skills/route-setup/apply_settings.py --status",
    "ls -la ~/.ssh/id_rsa.pub",
    "cat <<'EOF' > notes.md\nrm -rf / and git push --force and DROP TABLE x\nEOF",
    "truncate -s 0 app.log",
    "docker compose up -d",
]

# (指令, 預期決定, 預期規則)
DANGER = [
    ("git push --force origin feat/x", "ask", "force-push"),
    ("git push -f", "ask", "force-push"),
    ("git push --force-with-lease origin feat/x", "ask", "force-push"),
    ("git push origin +feat/x", "ask", "force-push"),
    ("git push origin main", "ask", "push-main"),
    ("git push origin HEAD:master", "ask", "push-main"),
    ("git push --signed origin main", "ask", "push-main"),
    ("git -C sub push origin main", "ask", "push-main"),
    ("rm -rf ~", "deny", "rm-catastrophe"),
    ("rm -rf ~/", "deny", "rm-catastrophe"),
    ("rm -rf ~/*", "deny", "rm-catastrophe"),
    ("rm -rf /", "deny", "rm-catastrophe"),
    ("rm -rf /*", "deny", "rm-catastrophe"),
    ("rm -rf $HOME", "deny", "rm-catastrophe"),
    ("sudo rm -rf /usr", "deny", "rm-catastrophe"),
    ("bash -c \"rm -rf ~\"", "deny", "rm-catastrophe"),
    ("cd / && rm -rf *", "deny", "rm-catastrophe"),
    ("dd if=/dev/zero of=/dev/disk2", "deny", "disk-wipe"),
    ("rm -rf ~/chutora-guard-test-missing", "ask", "rm-home"),
    ("rm -rf ../other-project", "ask", "rm-home"),
    ("rm /etc/hosts", "ask", "rm-outside"),
    ("rm -rf .", "ask", "rm-project-root"),
    ("rm -rf .git", "ask", "rm-project-root"),
    ("rm -rf \"$CHUTORA_TEST_UNSET_VAR/\"", "ask", "rm-unresolved"),
    ("cat .env", "ask", "secret-file"),
    ("echo TOKEN=1 >> .env", "ask", "secret-file"),
    ("source .env.local", "ask", "secret-file"),
    ("cat ~/.ssh/id_ed25519", "ask", "secret-file"),
    ("docker run --env-file=.env app", "ask", "secret-file"),
    ("psql -c \"DROP TABLE users\"", "ask", "sql-drop"),
    ("echo 'drop database prod' | mysql", "ask", "sql-drop"),
    ("sqlite3 app.db 'TRUNCATE TABLE logs'", "ask", "sql-drop"),
    ("psql mydb <<SQL\nDROP TABLE users;\nSQL", "ask", "sql-drop"),
    ("terraform destroy -auto-approve", "ask", "terraform-destroy"),
    ("terraform apply -destroy", "ask", "terraform-destroy"),
    ("kubectl delete pod web-1", "ask", "kubectl-delete"),
    ("git reset --hard HEAD~1", "ask", "git-reset-hard"),
    ("git clean -fd", "ask", "git-clean"),
    ("git clean -xdf", "ask", "git-clean"),
    ("echo '{}' > ~/.claude/settings.json", "ask", "claude-settings"),
    ("sed -i 's/a/b/' ~/.claude/settings.json", "ask", "claude-settings"),
    ("cp new.json ~/.claude/settings.json", "ask", "claude-settings"),
    ("echo off > ~/.claude/chutora/guard", "ask", "claude-settings"),
    ("python3 skills/chutora-hub/chutora.py guard off", "ask", "claude-settings"),
    ("python3 skills/route-setup/apply_settings.py --set-autocompact 153000", "ask", "claude-settings"),
]


class GuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.proj = self.home / "work" / "proj"
        (self.proj / ".git").mkdir(parents=True)
        (self.proj / ".git" / "HEAD").write_text("ref: refs/heads/feat/x\n")
        (self.proj / "claude-memory").mkdir()
        self.conf = self.home / ".claude" / "chutora"

    def run_hook(self, tool, inp, env=None, mode="default", tool_use_id="toolu_g1"):
        data = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool, "tool_input": inp,
                "tool_use_id": tool_use_id, "cwd": str(self.proj), "permission_mode": mode}
        e = dict(os.environ, HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG="zh")
        for k in ("CHUTORA_GUARD", "CHUTORA_TEST_UNSET_VAR"):
            e.pop(k, None)
        e.update(env or {})
        r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(data), capture_output=True, text=True,
                           env=e, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def bash(self, cmd, **kw):
        return self.run_hook("Bash", {"command": cmd}, **kw)

    def test_safe_commands_pass(self):
        for cmd in SAFE:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.bash(cmd))

    def test_dangerous_commands(self):
        for cmd, decision, rule in DANGER:
            with self.subTest(cmd=cmd):
                out = self.bash(cmd)
                self.assertIsNotNone(out, cmd)
                self.assertEqual(out["hookEventName"], "PreToolUse")
                self.assertEqual(out["permissionDecision"], decision)
                self.assertIn(f"[{rule}]", out["permissionDecisionReason"])

    def test_push_without_refspec_uses_current_branch(self):
        self.assertIsNone(self.bash("git push"))
        (self.proj / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        self.assertEqual(self.bash("git push")["permissionDecision"], "ask")
        self.assertEqual(self.bash("git push -u origin HEAD")["permissionDecision"], "ask")

    def test_file_tools(self):
        self.assertEqual(self.run_hook("Write", {"file_path": str(self.proj / ".env"), "content": "X=1"})["permissionDecision"], "ask")
        self.assertEqual(self.run_hook("Edit", {"file_path": str(self.home / ".claude" / "settings.json")})["permissionDecision"], "ask")
        self.assertEqual(self.run_hook("Write", {"file_path": str(self.conf / "always-ask")})["permissionDecision"], "ask")
        self.assertEqual(self.run_hook("Edit", {"file_path": str(self.proj / ".claude" / "settings.json")})["permissionDecision"], "ask")
        self.assertEqual(self.run_hook("Read", {"file_path": str(self.home / ".ssh" / "id_rsa")})["permissionDecision"], "ask")
        self.assertIsNone(self.run_hook("Read", {"file_path": str(self.home / ".claude" / "settings.json")}))
        self.assertIsNone(self.run_hook("Write", {"file_path": str(self.proj / "src" / "app.py")}))
        self.assertIsNone(self.run_hook("Edit", {"file_path": str(self.proj / ".env.example")}))
        self.assertIsNone(self.run_hook("Grep", {"pattern": "x"}))

    def test_switches(self):
        self.assertIsNone(self.bash("rm -rf ~", env={"CHUTORA_GUARD": "0"}))
        self.conf.mkdir(parents=True)
        (self.conf / "guard").write_text("off\n")
        self.assertIsNone(self.bash("git reset --hard"))

    def test_user_rules(self):
        self.conf.mkdir(parents=True)
        (self.conf / "always-ask").write_text(
            "# 我的規則\n!git-reset-hard\n\\bnpm publish\\b\ndeny: \\bheroku apps:destroy\\b\n([unclosed\n")
        self.assertIsNone(self.bash("git reset --hard"))
        self.assertEqual(self.bash("npm publish")["permissionDecision"], "ask")
        self.assertIn("npm publish", self.bash("npm publish")["permissionDecisionReason"])
        self.assertEqual(self.bash("heroku apps:destroy x")["permissionDecision"], "deny")
        self.assertIsNone(self.bash("npm test"))  # 壞掉的 regex 被略過，不影響其他規則
        self.assertEqual(self.bash("git push --force")["permissionDecision"], "ask")

    def test_reason_bilingual_and_bypass_note(self):
        zh = self.bash("git reset --hard", mode="bypassPermissions")["permissionDecisionReason"]
        self.assertIn("Chutora 守門", zh)
        self.assertIn("權限模式不會跳出確認", zh)
        en = self.bash("git reset --hard", env={"CHUTORA_LANG": "en"})["permissionDecisionReason"]
        self.assertIn("Chutora guard", en)
        self.assertNotIn("skips prompts", en)
        deny = self.bash("rm -rf ~", env={"CHUTORA_LANG": "en"})["permissionDecisionReason"]
        self.assertIn("blocked", deny)

    def test_change_log_written(self):
        self.bash("git reset --hard", tool_use_id="toolu_x1")
        self.bash("rm -rf ~", tool_use_id="toolu_x2")
        lines = [json.loads(x) for x in (self.proj / "claude-memory" / "changes.jsonl").read_text().splitlines()]
        self.assertEqual([x["action"] for x in lines], ["guard_ask", "guard_deny"])
        self.assertEqual(lines[0]["rules"], ["git-reset-hard"])
        self.assertTrue(lines[0]["notified"])
        self.assertIsNone(lines[0]["user_response"])
        self.assertEqual(lines[0]["tool_use_id"], "toolu_x1")
        pend = list((self.home / ".claude" / "chutora" / "projects").glob("*/guard-pending.json"))
        self.assertEqual(len(pend), 1)
        self.assertIn("toolu_x1", json.loads(pend[0].read_text()))

    def test_change_log_masks_secrets(self):
        self.bash("psql postgres://admin:hunter2pass@db/x -c 'DROP TABLE t'")
        text = (self.proj / "claude-memory" / "changes.jsonl").read_text()
        self.assertNotIn("hunter2pass", text)

    def test_bad_input_quiet(self):
        e = dict(os.environ, HOME=str(self.home))
        for raw in ("", "not json", "[]", json.dumps({"tool_name": "Bash", "tool_input": "x"})):
            r = subprocess.run([sys.executable, str(GUARD)], input=raw, capture_output=True, text=True, env=e, timeout=30)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "")

    def test_unterminated_quote_falls_back(self):
        self.assertEqual(self.bash("rm -rf / 'oops")["permissionDecision"], "deny")
        self.assertIsNone(self.bash("echo 'oops"))

    # ---------------------------------------------------------------- 略過權限模式：備份不了的改成直接擋
    def test_bypass_mode_denies_unrecoverable(self):
        cases = [
            ("git push --force origin feat/x", "force-push"),
            ("git push -f nowhere-remote-xyz feat/x", "force-push"),
            ("rm /etc/hosts", "rm-outside"),
            ("rm -rf ~/chutora-guard-test-missing", "rm-home"),
            ("psql -c \"DROP TABLE users\"", "sql-drop"),
            ("terraform destroy -auto-approve", "terraform-destroy"),
            ("kubectl delete pod web-1", "kubectl-delete"),
        ]
        for cmd, rule in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd)["permissionDecision"], "ask")  # 一般模式：照舊問
                out = self.bash(cmd, mode="bypassPermissions")
                self.assertEqual(out["permissionDecision"], "deny")
                self.assertIn(f"[{rule}]", out["permissionDecisionReason"])
                self.assertIn("略過權限模式", out["permissionDecisionReason"])
                self.assertIn("終端機", out["permissionDecisionReason"])
        en = self.bash("git push --force origin feat/x", mode="bypassPermissions", env={"CHUTORA_LANG": "en"})
        self.assertEqual(en["permissionDecision"], "deny")
        for s in ("bypass-permissions mode", "confirmation prompt may be skipped", "terminal", "turn off bypass"):
            self.assertIn(s, en["permissionDecisionReason"])

    def test_bypass_mode_leaves_other_rules_and_modes_alone(self):
        # 其他規則在略過權限模式仍是 ask
        for cmd in ("git reset --hard HEAD~1", "git clean -fd", "cat .env", "rm -rf .git", "git push origin main",
                    "rm -rf \"$CHUTORA_TEST_UNSET_VAR/\"", "echo '{}' > ~/.claude/settings.json"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd, mode="bypassPermissions")["permissionDecision"], "ask")
        # 其他模式不變
        for mode in ("default", "plan", "acceptEdits", "auto", "dontAsk"):
            with self.subTest(mode=mode):
                self.assertEqual(self.bash("git push --force origin feat/x", mode=mode)["permissionDecision"], "ask")
        # 本來就 deny 的照舊 deny；一般指令照舊不攔
        self.assertEqual(self.bash("rm -rf ~", mode="bypassPermissions")["permissionDecision"], "deny")
        self.assertIsNone(self.bash("git push origin feat/x", mode="bypassPermissions"))
        out = self.bash("rm -rf node_modules", mode="bypassPermissions")  # 不攔；決策引擎只先建復原點、補一行通知
        self.assertTrue(out is None or "permissionDecision" not in out)

    def test_bypass_deny_logged(self):
        self.bash("git push --force origin feat/x", mode="bypassPermissions", tool_use_id="toolu_b1")
        lines = [json.loads(x) for x in (self.proj / "claude-memory" / "changes.jsonl").read_text().splitlines()]
        self.assertEqual(lines[-1]["action"], "guard_deny")
        self.assertEqual(lines[-1]["permission_mode"], "bypassPermissions")
        obs = [json.loads(x) for f in (self.home / ".claude" / "chutora" / "projects").glob("*/observations.jsonl")
               for x in f.read_text().splitlines()]
        self.assertTrue(obs[-1].get("bypass_deny"))
        self.assertFalse(list((self.home / ".claude" / "chutora" / "projects").glob("*/guard-pending.json")))

    # ---------------------------------------------------------------- route-setup 只問一次
    OWN = ROOT / "plugins" / "chutora" / "skills" / "route-setup" / "apply_settings.py"

    def test_route_setup_own_script_not_asked_again(self):
        own = str(self.OWN)
        for cmd in (f'python3 "{own}" --set-autocompact 153000',
                    f'python3 "{own}" --set-statusline "python3 ~/.claude/chutora/statusline/statusline.py"',
                    f'python3 "{own}" --status',
                    f'cd /tmp && python3 {own} --set-autocompact 153000'):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.bash(cmd))
                self.assertIsNone(self.bash(cmd, mode="bypassPermissions"))

    def test_route_setup_lookalikes_still_ask(self):
        own = str(self.OWN)
        fake = self.home / "evil" / "skills" / "route-setup" / "apply_settings.py"
        fake.parent.mkdir(parents=True)
        fake.write_text(self.OWN.read_text())
        (self.proj / "apply_settings.py").write_text("print(1)\n")
        for cmd in (f'python3 "{fake}" --set-autocompact 153000',             # 同名、不在 plugin 目錄
                    "python3 apply_settings.py --set-statusline x",            # 專案裡的同名腳本
                    "python3 skills/route-setup/apply_settings.py --set-autocompact 1",
                    f'python3 "{own}" --set-autocompact 1 > ~/.claude/settings.json',  # 同一行另外改設定
                    f'python3 "{own}" --set-autocompact 1 && cp x.json ~/.claude/settings.json',
                    "python3 -c \"open('$HOME/.claude/settings.json','w').write('{}')\"",
                    "sed -i 's/a/b/' ~/.claude/settings.json",
                    f'cp /tmp/x.py "{own}"'):                                  # 改寫 plugin 自己的腳本
            with self.subTest(cmd=cmd):
                out = self.bash(cmd)
                self.assertIsNotNone(out, cmd)
                self.assertEqual(out["permissionDecision"], "ask")
                self.assertIn("[claude-settings]", out["permissionDecisionReason"])
        for tool in ("Write", "Edit"):
            self.assertEqual(self.run_hook(tool, {"file_path": str(self.home / ".claude" / "settings.json")})["permissionDecision"], "ask")
            self.assertEqual(self.run_hook(tool, {"file_path": own})["permissionDecision"], "ask")


if __name__ == "__main__":
    unittest.main()
