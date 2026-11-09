import importlib.util
import json
import time
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "menubar", "chutora-usage.1m.py")
spec = importlib.util.spec_from_file_location("chutora_usage", SCRIPT)
mb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mb)

NOW = 1_800_000_000  # 固定時間
FRESH = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 60))  # Codex 事件時間戳：比 NOW 早 1 分鐘（不算舊資料）


def claude_json(home, **over):
    d = {
        "v": 1,
        "limits": {"source": "statusline", "updated_at": NOW - 120,
                   "five_hour": {"pct": 42, "resets_at": NOW + 2 * 3600 + 13 * 60},
                   "seven_day": {"pct": 18, "resets_at": NOW + 3 * 86400}},
        "claude": {"updated_at": NOW - 120, "last_turn": {"input": 1200, "cache_write": 300, "cache_read": 50000, "output": 800, "total": 2300},
                   "net": 4200},
    }
    d.update(over)
    p = os.path.join(home, ".claude", "chutora")
    os.makedirs(p, exist_ok=True)
    with open(os.path.join(p, "usage.json"), "w", encoding="utf-8") as f:
        json.dump(d, f)


def tc(ts, primary=(10, 300), secondary=(3, 10080), last=(900, 400, 50), resets=NOW + 3600):
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {
        "type": "token_count",
        "info": {"total_token_usage": {}, "last_token_usage": {"input_tokens": last[0], "cached_input_tokens": last[1], "output_tokens": last[2]}},
        "rate_limits": {"primary": {"used_percent": primary[0], "window_minutes": primary[1], "resets_at": resets},
                        "secondary": {"used_percent": secondary[0], "window_minutes": secondary[1], "resets_at": resets + 86400}}}})


def rollout(codex, lines, name="rollout-2026-11-09T10-00-00-abc.jsonl", day="2026/11/09", mtime=None):
    d = os.path.join(codex, "sessions", day)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


class MenubarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.codex = os.path.join(self.tmp.name, "codex")
        os.makedirs(self.home)
        os.makedirs(self.codex)
        self.addCleanup(self.tmp.cleanup)

    def build(self):
        return mb.build(self.home, self.codex, NOW)

    def title(self):
        return self.build().split("\n")[0]

    def test_only_claude(self):
        claude_json(self.home)
        out = self.build()
        lines = out.split("\n")
        self.assertEqual(lines[0].split(" | ")[0], "C 5h42% 週18%")
        self.assertEqual(lines[1], "---")
        self.assertIn("5 小時：42%　重置 2h13m 後", out)
        self.assertRegex(out, r"每週：18%　重置 週[一二三四五六日] \d\d:\d\d")
        self.assertIn("上一輪 token：input 1.2k／cache 寫 300 讀 50k／output 800", out)
        self.assertIn("淨省≈ 4.2k tokens", out)
        self.assertIn("2 分鐘前更新", out)
        self.assertNotIn("舊資料", out)
        self.assertNotIn("Codex", out)
        self.assertIn("Opus／Sonnet 分項：外掛拿不到", out)
        self.assertEqual(lines[-1], "重新整理 | refresh=true")

    def test_only_codex(self):
        rollout(self.codex, [tc(FRESH)])
        out = self.build()
        self.assertEqual(out.split("\n")[0].split(" | ")[0], "X 5h10% 週3%")
        self.assertIn("5 小時：10%　重置 1h00m 後", out)
        self.assertIn("上一輪 token：input 900／cache 400／output 50", out)
        self.assertNotIn("Claude Code", out)
        self.assertNotIn("淨省", out)

    def test_both(self):
        claude_json(self.home)
        rollout(self.codex, [tc(FRESH)])
        out = self.build()
        self.assertEqual(out.split("\n")[0].split(" | ")[0], "C 5h42% 週18% · X 5h10% 週3%")
        self.assertIn("Claude Code | size=13", out)
        self.assertIn("Codex | size=13", out)

    def test_neither(self):
        out = self.build()
        self.assertEqual(out.split("\n")[0], "Chutora —")
        self.assertIn("重新整理 | refresh=true", out)

    def test_bad_json_and_non_dict(self):
        p = os.path.join(self.home, ".claude", "chutora")
        os.makedirs(p)
        for bad in ("{壞掉", "[1,2]", "", '{"limits": "x", "claude": 5}'):
            with open(os.path.join(p, "usage.json"), "w", encoding="utf-8") as f:
                f.write(bad)
            self.assertEqual(self.title(), "Chutora —", bad)

    def test_bad_json_codex_line_skipped(self):
        rollout(self.codex, [tc(FRESH, primary=(55, 300)), '{"payload": {"type": "token_count" 壞', "not json"])
        self.assertEqual(self.title().split(" | ")[0], "X 5h55% 週3%")

    def test_stale(self):
        claude_json(self.home)
        out = mb.build(self.home, self.codex, NOW + 7 * 3600)
        self.assertIn("7 小時前更新（舊資料）", out)

    def test_stale_marked_in_title_and_not_colored(self):
        # Claude 舊（7 小時前）、Codex 新：標題 C 加(舊)；Claude 的高用量不讓標題變色
        claude_json(self.home, limits={"updated_at": NOW - 7 * 3600, "five_hour": {"pct": 96, "resets_at": NOW + 600},
                                       "seven_day": {"pct": 18, "resets_at": NOW + 3 * 86400}},
                    claude={"updated_at": NOW - 7 * 3600, "net": 1})
        rollout(self.codex, [tc(FRESH)])
        head = mb.build(self.home, self.codex, NOW).split("\n")[0]
        self.assertTrue(head.startswith("C 5h96% 週18%(舊) · X 5h10% 週3% | size=12"), head)
        self.assertNotIn("color=", head)

    def test_all_stale_title_gray(self):
        claude_json(self.home)
        head = mb.build(self.home, self.codex, NOW + 7 * 3600).split("\n")[0]
        self.assertEqual(head, "C 週18%(舊) | size=12 color=#8E8E93")

    def test_reset_passed_shows_dash(self):
        claude_json(self.home)
        out = mb.build(self.home, self.codex, NOW + 3 * 3600)
        self.assertIn("5 小時：—　重置 已重置", out)
        self.assertEqual(out.split("\n")[0].split(" | ")[0], "C 週18%")

    def test_colors(self):
        claude_json(self.home, limits={"updated_at": NOW, "five_hour": {"pct": 81, "resets_at": NOW + 600}, "seven_day": {"pct": 10, "resets_at": NOW + 99999}})
        self.assertIn("color=#D9A100", self.title())
        claude_json(self.home, limits={"updated_at": NOW, "five_hour": {"pct": 96, "resets_at": NOW + 600}})
        self.assertIn("color=#E5484D", self.title())
        claude_json(self.home)
        self.assertNotIn("color=", self.title())

    def test_negative_net(self):
        claude_json(self.home, claude={"updated_at": NOW, "net": -1500})
        self.assertIn("淨省≈ -1.5k tokens", self.build())

    def test_large_rollout_reads_only_tail(self):
        junk = json.dumps({"type": "response_item", "payload": {"type": "message", "text": "x" * 2000}})
        old = tc(FRESH, primary=(99, 300))
        # 最舊的 token_count（99%）被 ~1MB 垃圾蓋過去；尾端只有新的 token_count
        lines = [old] + [junk] * 500 + [tc(FRESH, primary=(21, 300))] + [junk] * 10
        path = rollout(self.codex, lines)
        self.assertGreater(os.path.getsize(path), 900 * 1024)
        self.assertEqual(self.title().split(" | ")[0], "X 5h21% 週3%")
        # 只有最舊那筆在 256KB 之外 → 讀不到，不會為了找它掃整個檔
        rollout(self.codex, [old] + [junk] * 500)
        self.assertEqual(self.title(), "Chutora —")

    def test_picks_newest_file_and_classifies_by_window_minutes(self):
        rollout(self.codex, [tc(FRESH, primary=(77, 300))], name="rollout-old.jsonl", day="2026/11/08", mtime=NOW - 9999)
        # 方案只有週窗：primary 就是 10080，不能當成 5 小時
        rollout(self.codex, [tc(FRESH, primary=(30, 10080), secondary=(5, 43200))], name="rollout-new.jsonl", mtime=NOW)
        self.assertEqual(self.title().split(" | ")[0], "X 週30%")

    def test_codex_home_env_and_script_never_errors(self):
        env = dict(os.environ, HOME=self.home, CODEX_HOME=self.codex)
        rollout(self.codex, [tc(FRESH)])
        r = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("X 5h10% 週3%"))
        env = dict(os.environ, HOME=os.path.join(self.tmp.name, "nope"), CODEX_HOME=os.path.join(self.tmp.name, "nope2"))
        r = subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("Chutora —"))

    def test_internal_error_still_gives_title(self):
        orig = mb.build
        mb.build = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mb.main()
            self.assertTrue(buf.getvalue().startswith("Chutora —"))
            self.assertIn("boom", buf.getvalue())
        finally:
            mb.build = orig

    def test_tok_format(self):
        self.assertEqual([mb.tok(x) for x in (0, 999, 1000, 1234, -1500, 1_200_000, None)], ["0", "999", "1k", "1.2k", "-1.5k", "1.2M", "—"])


class InstallMenubarTest(unittest.TestCase):
    """install.sh --with-menubar:符號連結到 SwiftBar 外掛資料夾。"""
    INSTALL = os.path.join(ROOT, "install.sh")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(os.path.realpath(self.tmp.name), "home")
        os.makedirs(self.home)
        self.default_dir = os.path.join(self.home, "Library", "Application Support", "SwiftBar", "Plugins")

    @staticmethod
    def read(path):
        with open(path) as f:
            return f.read()

    def run_install(self, *args, plugins_dir=None, ok=True):
        env = dict(os.environ, HOME=self.home)
        env.pop("SWIFTBAR_PLUGINS_DIR", None)
        if plugins_dir:
            env["SWIFTBAR_PLUGINS_DIR"] = plugins_dir
        r = subprocess.run(["bash", self.INSTALL, *args], capture_output=True, text=True, env=env, cwd=self.tmp.name, timeout=120)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r

    def test_default_dir_link_and_uninstall(self):
        os.makedirs(self.default_dir)
        self.run_install("--link", "--with-menubar")
        link = os.path.join(self.default_dir, "chutora-usage.1m.py")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), SCRIPT)
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.run_install("--link", "--with-menubar")  # 重跑不出錯
        self.run_install("--uninstall")
        self.assertFalse(os.path.lexists(link))

    def test_custom_dir_created_and_copy_mode(self):
        d = os.path.join(self.tmp.name, "my plugins")
        self.run_install("--with-menubar", plugins_dir=d)
        self.assertEqual(os.readlink(os.path.join(d, "chutora-usage.1m.py")), SCRIPT)
        self.run_install("--uninstall", plugins_dir=d)
        self.assertFalse(os.path.lexists(os.path.join(d, "chutora-usage.1m.py")))

    def test_no_swiftbar_dir_only_prints_help(self):
        r = self.run_install("--link", "--with-menubar")
        self.assertFalse(os.path.exists(self.default_dir))
        self.assertIn("brew install --cask swiftbar", r.stdout)

    def test_existing_file_not_overwritten_and_other_link_kept(self):
        d = os.path.join(self.tmp.name, "p")
        os.makedirs(d)
        mine = os.path.join(d, "chutora-usage.1m.py")
        with open(mine, "w") as f:
            f.write("mine")
        self.run_install("--link", "--with-menubar", plugins_dir=d)
        self.assertEqual(self.read(mine), "mine")
        self.run_install("--uninstall", plugins_dir=d)
        self.assertEqual(self.read(mine), "mine")

    def test_conflicts(self):
        self.run_install("--with-menubar", "--agents-only", ok=False)


if __name__ == "__main__":
    unittest.main()
