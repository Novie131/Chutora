import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "plugins" / "chutora" / "skills" / "route-setup"
APPLY = SKILL / "apply_settings.py"


class ApplySettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.path = self.tmp / "settings.json"
        self.cmd = "python3 ~/x/statusline.py"

    def run_apply(self, *args, settings=True):
        a = ["--settings", str(self.path)] if settings else []
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        return subprocess.run([sys.executable, str(APPLY), *a, *args], capture_output=True,
                              text=True, env=env, timeout=30, stdin=subprocess.DEVNULL)

    def baks(self):
        return sorted(self.tmp.glob("settings.json.bak-*"))

    def test_frontmatter(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        self.assertIn("name: route-setup", head)
        self.assertIn("disable-model-invocation: true", head)
        self.assertIn("description:", head)

    def test_creates_missing_file(self):
        r = self.run_apply("--set-statusline", self.cmd, "--set-autocompact", "153000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.path.read_text()),
                         {"statusLine": {"type": "command", "command": self.cmd},
                          "autoCompactWindow": 153000})
        self.assertEqual(self.baks(), [])

    def test_creates_parent_directory(self):
        self.path = self.tmp / "sub" / "dir" / "settings.json"
        r = self.run_apply("--set-autocompact", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.path.read_text()), {"autoCompactWindow": 1})

    def test_adds_only_missing_keys_and_preserves_others(self):
        orig = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"Stop": []},
                "model": "opus", "note": "中文", "autoCompactWindow": 100000}
        text = json.dumps(orig, ensure_ascii=False)
        self.path.write_text(text, encoding="utf-8")
        r = self.run_apply("--set-statusline", self.cmd, "--set-autocompact", "153000")
        self.assertEqual(r.returncode, 3)  # autoCompactWindow 已存在
        data = json.loads(self.path.read_text())
        self.assertEqual(data.pop("statusLine"), {"type": "command", "command": self.cmd})
        self.assertEqual(data, orig)  # 其他鍵原樣，autoCompactWindow 沒被覆蓋
        self.assertIn("中文", self.path.read_text())
        self.assertIn("100000", r.stdout)
        baks = self.baks()
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(), text)

    def test_existing_value_returns_3_and_unchanged(self):
        text = '{"statusLine": {"type": "command", "command": "mine"}}'
        self.path.write_text(text)
        r = self.run_apply("--set-statusline", self.cmd)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.path.read_text(), text)
        self.assertEqual(self.baks(), [])
        self.assertIn("mine", r.stdout)

    def test_bad_json_returns_2_no_write_no_backup(self):
        for bad in ("{not json", "[1, 2]", '"str"', ""):
            with self.subTest(bad=bad):
                self.path.write_text(bad)
                r = self.run_apply("--set-statusline", self.cmd)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(self.path.read_text(), bad)
                self.assertEqual(self.baks(), [])

    # --add-plugin-dir / --remove-plugin-dir
    VAR = "CLAUDE_CODE_PLUGIN_DIRS"

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_add_plugin_dir_no_env(self):
        orig = {"permissions": {"allow": ["Bash(ls)"]}, "model": "opus"}
        text = json.dumps(orig)
        self.path.write_text(text)
        r = self.run_apply("--add-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), {**orig, "env": {self.VAR: "/a/board"}})
        baks = self.baks()
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(), text)

    def test_add_plugin_dir_creates_missing_file(self):
        r = self.run_apply("--add-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), {"env": {self.VAR: "/a/board"}})
        self.assertEqual(self.baks(), [])

    def test_add_plugin_dir_keeps_other_env(self):
        self.path.write_text(json.dumps({"env": {"FOO": "1"}, "x": 2}))
        r = self.run_apply("--add-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), {"env": {"FOO": "1", self.VAR: "/a/board"}, "x": 2})

    def test_add_plugin_dir_appends_to_existing(self):
        self.path.write_text(json.dumps({"env": {self.VAR: "/x/one:/x/two", "FOO": "1"}}))
        r = self.run_apply("--add-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), {"env": {self.VAR: "/x/one:/x/two:/a/board", "FOO": "1"}})

    def test_add_plugin_dir_duplicate_not_added(self):
        text = json.dumps({"env": {self.VAR: "/x/one:/a/board"}})
        self.path.write_text(text)
        r = self.run_apply("--add-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 3)
        self.assertIn("已存在", r.stdout)
        self.assertEqual(self.path.read_text(), text)
        self.assertEqual(self.baks(), [])

    def test_remove_plugin_dir_only_one(self):
        self.path.write_text(json.dumps({"env": {self.VAR: "/a/board"}, "x": 1}))
        r = self.run_apply("--remove-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), {"x": 1})  # 變數空了刪變數，env 空了刪 env
        self.assertEqual(len(self.baks()), 1)

    def test_remove_plugin_dir_keeps_other_env_var(self):
        self.path.write_text(json.dumps({"env": {self.VAR: "/a/board", "FOO": "1"}}))
        self.run_apply("--remove-plugin-dir", "/a/board")
        self.assertEqual(self.read(), {"env": {"FOO": "1"}})

    def test_remove_plugin_dir_keeps_other_paths(self):
        self.path.write_text(json.dumps({"env": {self.VAR: "/x/one:/a/board:/x/two"}}))
        r = self.run_apply("--remove-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), {"env": {self.VAR: "/x/one:/x/two"}})

    def test_remove_plugin_dir_absent_noop(self):
        for text in ('{"x": 1}', json.dumps({"env": {self.VAR: "/x/one"}})):
            with self.subTest(text=text):
                self.path.write_text(text)
                r = self.run_apply("--remove-plugin-dir", "/a/board")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.path.read_text(), text)
                self.assertEqual(self.baks(), [])
        self.path.unlink()
        r = self.run_apply("--remove-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self.path.exists())

    def test_plugin_dir_bad_json_untouched(self):
        for flag in ("--add-plugin-dir", "--remove-plugin-dir"):
            for bad in ("{not json", "[1]"):
                with self.subTest(flag=flag, bad=bad):
                    self.path.write_text(bad)
                    r = self.run_apply(flag, "/a/board")
                    self.assertEqual(r.returncode, 2)
                    self.assertEqual(self.path.read_text(), bad)
                    self.assertEqual(self.baks(), [])

    def test_plugin_dir_bad_env_type_untouched(self):
        text = json.dumps({"env": ["x"]})
        self.path.write_text(text)
        r = self.run_apply("--add-plugin-dir", "/a/board")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.path.read_text(), text)
        self.assertEqual(self.baks(), [])

    def test_dry_run_writes_nothing(self):
        r = self.run_apply("--set-autocompact", "153000", "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self.path.exists())
        text = '{"a": 1}'
        self.path.write_text(text)
        r = self.run_apply("--set-autocompact", "153000", "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.path.read_text(), text)
        self.assertEqual(self.baks(), [])
        self.assertIn("dry-run", r.stdout)

    def test_status_output(self):
        self.path.write_text(json.dumps({
            "model": "opus", "autoCompactWindow": 150000,
            "modelSettings": {"opus": {"autoCompactWindow": 100000}},
            "statusLine": {"type": "command", "command": "x"}}))
        before = self.path.read_text()
        r = self.run_apply("--status")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["model"], "opus")
        self.assertEqual(d["autoCompactWindow"], 150000)
        self.assertEqual(d["statusLine"]["command"], "x")
        self.assertTrue(d["modelSettingsOverridesAutoCompact"])
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(self.baks(), [])

    def test_status_without_overrides_or_file(self):
        r = self.run_apply("--status")
        d = json.loads(r.stdout)
        self.assertFalse(d["modelSettingsOverridesAutoCompact"])
        self.assertIsNone(d["statusLine"])
        self.assertFalse(self.path.exists())

    def test_default_settings_path_is_home(self):
        (self.home / ".claude").mkdir()
        r = self.run_apply("--set-autocompact", "5", settings=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.home / ".claude" / "settings.json").read_text()),
                         {"autoCompactWindow": 5})

    def test_no_action_is_usage_error(self):
        r = self.run_apply()
        self.assertEqual(r.returncode, 2)
        self.assertFalse(self.path.exists())

    def test_output_format(self):
        self.path.write_text('{"a": {"b": "中"}}')
        self.run_apply("--set-autocompact", "7")
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('\n  "a": {', text)  # 縮排 2
        self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
