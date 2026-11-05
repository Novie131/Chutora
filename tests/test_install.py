import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
SRC = ROOT / "plugins" / "chutora"
AGENTS = sorted(p.name for p in (SRC / "agents").glob("*.md"))
SKILLS = sorted(p.name for p in (SRC / "skills").iterdir() if p.is_dir())


class InstallTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.claude = self.home / ".claude"
        self.manifest = self.claude / ".chutora-installed"

    def run_install(self, *args):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        r = subprocess.run(["bash", str(INSTALL), *args], capture_output=True,
                           text=True, env=env, cwd=self.tmp, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def run_install_fail(self, *args):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        r = subprocess.run(["bash", str(INSTALL), *args], capture_output=True,
                           text=True, env=env, cwd=self.tmp, timeout=120)
        self.assertNotEqual(r.returncode, 0)
        return r

    def manifest_lines(self):
        return self.manifest.read_text().splitlines()

    def user_file(self, rel, text="user content\n"):
        p = self.claude / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    # a
    def test_fresh_copy_install(self):
        self.run_install()
        lines = self.manifest_lines()
        for a in AGENTS:
            self.assertTrue((self.claude / "agents" / a).is_file())
            self.assertIn(f"agents/{a}", lines)
        for s in SKILLS:
            self.assertTrue((self.claude / "skills" / s).is_dir())
            self.assertFalse((self.claude / "skills" / s).is_symlink())
            self.assertIn(f"skills/{s}", lines)
        self.assertTrue((self.claude / "hooks" / "chutora" / "context-check.py").is_file())
        self.assertIn("hooks/chutora", lines)

    # b
    def test_rerun_restores(self):
        self.run_install()
        f = self.claude / "agents" / "worker.md"
        f.write_text("tampered\n")
        self.run_install()
        self.assertEqual(f.read_text(), (SRC / "agents" / "worker.md").read_text())

    # c
    def test_user_agent_not_overwritten(self):
        mine = self.user_file("agents/worker.md", "my own worker\n")
        r = self.run_install()
        self.assertEqual(mine.read_text(), "my own worker\n")
        self.assertNotIn("agents/worker.md", self.manifest_lines())
        self.assertIn("不覆蓋", r.stdout)

    # d
    def test_legacy_location_removed(self):
        legacy = self.user_file("skills/chutora/old.md")
        self.run_install()
        self.assertFalse(legacy.parent.exists())

    # e
    def test_legacy_smart_agent_route_warned(self):
        old = self.claude / "hooks" / "smart-agent-route"
        old.mkdir(parents=True)
        r = self.run_install()
        self.assertIn("smart-agent-route", r.stdout + r.stderr)
        self.assertTrue(old.exists())  # 只提醒,不自動刪

    def test_uninstall_only_manifest_items(self):
        self.run_install()
        mine = self.user_file("agents/mine.md")
        skill = self.user_file("skills/myskill/SKILL.md")
        self.run_install("--uninstall")
        for a in AGENTS:
            self.assertFalse((self.claude / "agents" / a).exists())
        for s in SKILLS:
            self.assertFalse((self.claude / "skills" / s).exists())
        self.assertFalse((self.claude / "hooks" / "chutora").exists())
        self.assertTrue(mine.exists())
        self.assertTrue(skill.exists())
        self.assertFalse(self.manifest.exists())

    # f
    def test_uninstall_tampered_manifest(self):
        outside_dir = self.tmp / "outside"
        outside_dir.mkdir()
        outside = outside_dir / "keep.txt"
        outside.write_text("x")
        sentinel_home = self.home / "home_keep.txt"
        sentinel_home.write_text("x")
        settings = self.user_file("settings.json", "{}")
        deep = self.user_file("agents/sub/deep.md")
        mine = self.user_file("agents/mine.md")
        self.manifest.write_text("\n".join([
            "../home_keep.txt",
            "agents/../settings.json",
            "agents/..",
            "..",
            ".",
            "",
            str(outside),
            str(outside_dir),
            "agents/sub/deep.md",
            "skills/../../outside",
        ]) + "\n")
        self.run_install("--uninstall")
        for p in (outside, sentinel_home, settings, deep, mine):
            self.assertTrue(p.exists(), p)
        self.assertTrue(self.claude.is_dir())
        self.assertFalse(self.manifest.exists())

    # g
    def test_link_mode(self):
        mine = self.user_file("agents/worker.md", "mine\n")
        self.run_install("--link")
        for a in AGENTS:
            p = self.claude / "agents" / a
            if a == "worker.md":
                self.assertFalse(p.is_symlink())
                self.assertEqual(p.read_text(), "mine\n")
            else:
                self.assertTrue(p.is_symlink())
                self.assertEqual(os.readlink(p), str(SRC / "agents" / a))
        for s in SKILLS:
            p = self.claude / "skills" / s
            self.assertEqual(os.readlink(p), str(SRC / "skills" / s))
        self.assertEqual(os.readlink(self.claude / "hooks" / "chutora"),
                         str(SRC / "hooks"))
        self.run_install("--link")  # 重跑不出錯
        self.assertEqual(mine.read_text(), "mine\n")

    # h
    def test_link_then_uninstall(self):
        self.run_install("--link")
        other_target = self.tmp / "elsewhere"
        other_target.mkdir()
        other_link = self.claude / "skills" / "foreign"
        other_link.symlink_to(other_target)
        mine = self.user_file("agents/mine.md")
        real = self.user_file("skills/realdir/SKILL.md")
        self.run_install("--uninstall")
        for a in AGENTS:
            self.assertFalse((self.claude / "agents" / a).is_symlink())
        for s in SKILLS:
            self.assertFalse((self.claude / "skills" / s).is_symlink())
        self.assertFalse((self.claude / "hooks" / "chutora").is_symlink())
        self.assertTrue(other_link.is_symlink())
        self.assertTrue(other_target.exists())
        self.assertTrue(mine.exists())
        self.assertTrue(real.exists())

    # i
    def test_agents_only(self):
        self.run_install("--agents-only")
        for a in AGENTS:
            self.assertTrue((self.claude / "agents" / a).is_file())
        self.assertFalse((self.claude / "hooks").exists())
        for s in SKILLS:
            self.assertFalse((self.claude / "skills" / s).exists())
        self.assertTrue(all(l.startswith("agents/") for l in self.manifest_lines()))

    # statusline
    CMD = "python3 ~/.claude/hooks/chutora/statusline.py"

    def baks(self):
        return sorted(self.claude.glob("settings.json.bak-*"))

    def test_statusline_creates_settings(self):
        self.run_install("--with-statusline")
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data, {"statusLine": {"type": "command", "command": self.CMD}})
        self.assertEqual(self.baks(), [])

    def test_statusline_existing_not_overwritten(self):
        text = '{"statusLine": {"type": "command", "command": "mine"}}'
        p = self.user_file("settings.json", text)
        r = self.run_install("--with-statusline")
        self.assertEqual(p.read_text(), text)
        self.assertEqual(self.baks(), [])
        self.assertIn("statusline.py", r.stdout)
        self.assertIn("153000", r.stdout)

    def test_statusline_backup_and_keeps_keys(self):
        orig = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"Stop": []},
                "autoCompactWindow": 153000, "note": "中文"}
        text = json.dumps(orig)
        p = self.user_file("settings.json", text)
        self.run_install("--with-statusline", "--link")
        data = json.loads(p.read_text())
        self.assertEqual(data.pop("statusLine"), {"type": "command", "command": self.CMD})
        self.assertEqual(data, orig)
        self.assertIn("中文", p.read_text())
        baks = self.baks()
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(), text)

    def test_statusline_bad_json_untouched(self):
        p = self.user_file("settings.json", "{not json")
        r = self.run_install("--with-statusline")
        self.assertEqual(p.read_text(), "{not json")
        self.assertEqual(self.baks(), [])
        self.assertIn("statusline.py", r.stdout)

    def test_with_explore_new_path(self):
        self.run_install("--with-explore")
        src = SRC / "skills" / "route-setup" / "templates" / "Explore.md"
        self.assertEqual((self.claude / "agents" / "Explore.md").read_text(), src.read_text())
        mine = (self.claude / "agents" / "Explore.md")
        mine.write_text("mine\n")
        r = self.run_install("--with-explore")
        self.assertEqual(mine.read_text(), "mine\n")
        self.assertIn("不覆蓋", r.stdout)

    def test_route_setup_skill_installed(self):
        self.run_install()
        d = self.claude / "skills" / "route-setup"
        self.assertTrue((d / "apply_settings.py").is_file())
        self.assertTrue((d / "templates" / "MEMORY.md").is_file())

    def test_statusline_conflicts(self):
        for flag in ("--agents-only", "--uninstall"):
            with self.subTest(flag=flag):
                self.run_install_fail("--with-statusline", flag)
        self.assertFalse((self.claude / "settings.json").exists())


    # agent-board
    BOARD_SRC = ROOT / "plugins" / "agent-board"
    VAR = "CLAUDE_CODE_PLUGIN_DIRS"

    def plugin_dirs(self):
        data = json.loads((self.claude / "settings.json").read_text())
        return data.get("env", {}).get(self.VAR)

    def test_agent_board_link(self):
        orig = {"permissions": {"allow": ["Bash(ls)"]}, "env": {"FOO": "1"}}
        self.user_file("settings.json", json.dumps(orig))
        self.run_install("--link", "--with-agent-board")
        self.assertEqual(self.plugin_dirs(), str(self.BOARD_SRC))
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data["env"]["FOO"], "1")
        self.assertEqual(data["permissions"], orig["permissions"])
        self.assertEqual(len(self.baks()), 1)
        self.run_install("--link", "--with-agent-board")  # 重跑不重複
        self.assertEqual(self.plugin_dirs(), str(self.BOARD_SRC))
        self.run_install("--uninstall")
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data, orig)

    def test_agent_board_copy(self):
        self.run_install("--with-agent-board")
        dest = self.claude / "chutora" / "agent-board"
        self.assertTrue(dest.is_dir())
        self.assertFalse(dest.is_symlink())
        self.assertIn("chutora/agent-board", self.manifest_lines())
        self.assertEqual(self.plugin_dirs(), str(dest))
        self.run_install("--with-agent-board")
        self.assertEqual(self.plugin_dirs(), str(dest))
        self.run_install("--uninstall")
        self.assertFalse(dest.exists())
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data, {})

    def test_agent_board_uninstall_keeps_other_paths(self):
        self.run_install("--with-agent-board")
        dest = self.claude / "chutora" / "agent-board"
        p = self.claude / "settings.json"
        data = json.loads(p.read_text())
        data["env"][self.VAR] = f"/x/other:{dest}"
        p.write_text(json.dumps(data))
        self.run_install("--uninstall")
        self.assertEqual(self.plugin_dirs(), "/x/other")

    def test_uninstall_without_board_leaves_settings_alone(self):
        text = '{"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/other"}}'
        p = self.user_file("settings.json", text)
        self.run_install("--uninstall")
        self.assertEqual(p.read_text(), text)
        self.assertEqual(self.baks(), [])

    def test_agent_board_bad_json_untouched(self):
        p = self.user_file("settings.json", "{not json")
        r = self.run_install("--with-agent-board")
        self.assertEqual(p.read_text(), "{not json")
        self.assertEqual(self.baks(), [])
        self.assertIn(self.VAR, r.stdout)

    def test_agent_board_conflicts(self):
        for flag in ("--agents-only", "--uninstall"):
            with self.subTest(flag=flag):
                self.run_install_fail("--with-agent-board", flag)
        self.assertFalse((self.claude / "settings.json").exists())

    # reply-detail
    DETAIL_SRC = ROOT / "plugins" / "reply-detail"

    def test_reply_detail_link(self):
        orig = {"permissions": {"allow": ["Bash(ls)"]}, "env": {"FOO": "1"}}
        self.user_file("settings.json", json.dumps(orig))
        self.run_install("--link", "--with-reply-detail")
        self.assertEqual(self.plugin_dirs(), str(self.DETAIL_SRC))
        self.run_install("--link", "--with-reply-detail")  # 重跑不重複
        self.assertEqual(self.plugin_dirs(), str(self.DETAIL_SRC))
        self.run_install("--uninstall")
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data, orig)

    def test_reply_detail_copy(self):
        self.run_install("--with-reply-detail")
        dest = self.claude / "chutora" / "reply-detail"
        self.assertTrue(dest.is_dir())
        self.assertFalse(dest.is_symlink())
        self.assertIn("chutora/reply-detail", self.manifest_lines())
        self.assertEqual(self.plugin_dirs(), str(dest))
        self.run_install("--uninstall")
        self.assertFalse(dest.exists())
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data, {})

    def test_both_mods_link(self):
        self.run_install("--link", "--with-agent-board", "--with-reply-detail")
        self.assertEqual(self.plugin_dirs(), f"{self.BOARD_SRC}:{self.DETAIL_SRC}")
        self.run_install("--uninstall")
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data, {})

    def test_both_mods_copy(self):
        self.run_install("--with-agent-board", "--with-reply-detail")
        base = self.claude / "chutora"
        self.assertEqual(self.plugin_dirs(), f"{base / 'agent-board'}:{base / 'reply-detail'}")
        self.run_install("--uninstall")
        self.assertFalse((base / "agent-board").exists())
        self.assertFalse((base / "reply-detail").exists())
        data = json.loads((self.claude / "settings.json").read_text())
        self.assertEqual(data, {})

    def test_reply_detail_uninstall_keeps_other_paths(self):
        self.run_install("--with-agent-board", "--with-reply-detail")
        dest = self.claude / "chutora" / "reply-detail"
        board = self.claude / "chutora" / "agent-board"
        p = self.claude / "settings.json"
        data = json.loads(p.read_text())
        data["env"][self.VAR] = f"/x/other:{board}:{dest}"
        p.write_text(json.dumps(data))
        self.run_install("--uninstall")
        self.assertEqual(self.plugin_dirs(), "/x/other")

    def test_reply_detail_conflicts(self):
        for flag in ("--agents-only", "--uninstall"):
            with self.subTest(flag=flag):
                self.run_install_fail("--with-reply-detail", flag)
        self.assertFalse((self.claude / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
