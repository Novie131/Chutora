"""噪音輸出瘦身 hook（plugins/chutora/hooks/trim.py）的測試。一律用暫存 HOME。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIM = ROOT / "plugins" / "chutora" / "hooks" / "trim.py"


def npm_install_log(n=400):
    lines = ["npm warn deprecated inflight@1.0.6: This module is not supported"]
    for i in range(n):
        lines.append(f"\x1b[32mreify\x1b[0m:pkg-{i} \x1b[90mtiming\x1b[0m reifyNode:node_modules/pkg-{i} Completed in {i}ms")
    lines += ["", "added 412 packages, and audited 413 packages in 9s", "", "found 0 vulnerabilities"]
    return "\n".join(lines)


def pytest_log(n=300):
    lines = ["============================= test session starts ==============================",
             "platform darwin -- Python 3.12.1, pytest-8.3.2", "collected 300 items", ""]
    lines += [f"tests/test_mod.py::test_case_{i} PASSED                                   [{i * 100 // n:3d}%]" for i in range(n)]
    lines += ["tests/test_mod.py::test_checkout FAILED", "",
              "    def test_checkout():", ">       assert cart.total == 30",
              "E       AssertionError: assert 25 == 30", "",
              "=========================== short test summary info ============================",
              "FAILED tests/test_mod.py::test_checkout - AssertionError: assert 25 == 30",
              "======================== 1 failed, 299 passed in 3.21s ========================="]
    return "\n".join(lines)


def jest_log(n=250):
    lines = [f" PASS  src/components/C{i}.test.tsx ({i % 7 + 1}.{i % 10}s)" for i in range(n)]
    lines += ["", "Test Suites: 250 passed, 250 total", "Tests:       1210 passed, 1210 total",
              "Snapshots:   0 total", "Time:        48.3 s"]
    return "\n".join(lines)


def cargo_log(n=300):
    lines = [f"   Compiling crate{i} v0.{i}.0" for i in range(n)]
    lines += ["warning: unused variable: `x`", "  --> src/main.rs:10:9", "   |",
              "    Finished `dev` profile [unoptimized + debuginfo] target(s) in 41.20s"]
    return "\n".join(lines)


class TrimTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.conf = self.home / ".claude" / "chutora"

    def run_hook(self, command, stdout, stderr="", env=None, tool_use_id="toolu_1", **resp_extra):
        data = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": tool_use_id,
                "tool_input": {"command": command},
                "tool_response": dict({"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False}, **resp_extra)}
        e = dict(os.environ, HOME=str(self.home), CHUTORA_LANG="zh")
        e.pop("CHUTORA_TRIM", None)
        e.pop("CHUTORA_MODE", None)
        e.update(env or {})
        r = subprocess.run([sys.executable, str(TRIM)], input=json.dumps(data), capture_output=True,
                           text=True, env=e, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def new_output(self, out):
        self.assertIsNotNone(out)
        h = out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "PostToolUse")
        return h["updatedToolOutput"]

    # ---- 會瘦身的情況
    def test_npm_install_trimmed_keeps_summary_and_warnings(self):
        log = npm_install_log()
        new = self.new_output(self.run_hook("npm install", log))
        self.assertLess(len(new["stdout"]), len(log) // 2)
        self.assertIn("added 412 packages", new["stdout"])
        self.assertIn("found 0 vulnerabilities", new["stdout"])
        self.assertIn("npm warn deprecated inflight", new["stdout"])
        self.assertNotIn("\x1b[", new["stdout"])
        self.assertIn("Chutora 瘦身", new["stdout"])
        self.assertFalse(new["interrupted"])  # 其他欄位照抄

    def test_chained_command_uses_noisy_segment(self):
        # 實測發現：rm -rf node_modules && npm install 原本只看第一段（rm），被當成不認得的指令而沒有瘦身
        log = npm_install_log(200)
        new = self.new_output(self.run_hook("rm -rf node_modules package-lock.json && npm install --loglevel=http", log))
        self.assertIn("Chutora 瘦身", new["stdout"])
        self.assertIn("added 412 packages", new["stdout"])
        # 讀檔類放在前面仍然維持原本規則（第一段是 cat 且沒有噪音指令 → 不動）
        self.assertIsNone(self.run_hook("cd app && cat big.log", log))

    def test_pytest_failure_lines_kept(self):
        log = pytest_log()
        new = self.new_output(self.run_hook("cd app && python -m pytest -q", log))
        s = new["stdout"]
        for must in ("FAILED tests/test_mod.py::test_checkout", "AssertionError: assert 25 == 30",
                     "assert cart.total == 30", "1 failed, 299 passed"):
            self.assertIn(must, s)
        self.assertLess(len(s), len(log) // 2)

    def test_jest_and_cargo(self):
        new = self.new_output(self.run_hook("npx jest", jest_log()))
        self.assertIn("Tests:       1210 passed", new["stdout"])
        new = self.new_output(self.run_hook("cargo build", "", cargo_log()))
        self.assertIn("warning: unused variable", new["stderr"])
        self.assertIn("--> src/main.rs:10:9", new["stderr"])
        self.assertIn("Finished `dev` profile", new["stderr"])

    def test_unknown_long_output_is_conservative(self):
        lines = [f"processing item {i} of 3000 ok-ish" for i in range(3000)]
        log = "\n".join(lines)
        new = self.new_output(self.run_hook("./scripts/migrate.sh", log))
        s = new["stdout"]
        self.assertIn("processing item 0 of 3000", s)
        self.assertIn("processing item 2999 of 3000", s)
        # other 類保留開頭 80 行
        self.assertIn("processing item 79 of 3000", s)

    def test_progress_lines_collapsed(self):
        lines = [f"Downloading pkg.tar.gz {i}% |{'#' * (i // 5)}|" for i in range(400)]
        log = "\r".join(lines[:200]) + "\n" + "\n".join(lines[200:]) + "\nSuccessfully installed pkg-1.0"
        new = self.new_output(self.run_hook("pip install pkg", log))
        self.assertIn("Successfully installed pkg-1.0", new["stdout"])

    # ---- 不動的情況
    def test_short_output_untouched(self):
        self.assertIsNone(self.run_hook("npm install", "added 1 package in 1s"))

    def test_read_like_commands_untouched(self):
        big = "\n".join(f"line {i}" for i in range(5000))
        for cmd in ("cat big.log", "head -n 4000 a.txt", "sed -n 1,4000p a.txt", "git diff", "git show HEAD",
                    "grep -rn foo .", "npm test | tail -50", "ls -la", "python3 -c 'print(1)'"):
            self.assertIsNone(self.run_hook(cmd, big), cmd)

    def test_json_and_special_responses_untouched(self):
        big_json = json.dumps([{"i": i, "name": f"pkg-{i}"} for i in range(2000)])
        self.assertIsNone(self.run_hook("npm ls --json", big_json))
        log = npm_install_log()
        self.assertIsNone(self.run_hook("npm install", log, persistedOutputPath="/tmp/x"))
        self.assertIsNone(self.run_hook("npm install", log, backgroundTaskId="b1"))

    def test_other_tools_untouched(self):
        data = {"tool_name": "Read", "tool_input": {}, "tool_response": {"stdout": npm_install_log()}}
        e = dict(os.environ, HOME=str(self.home))
        r = subprocess.run([sys.executable, str(TRIM)], input=json.dumps(data), capture_output=True, text=True, env=e)
        self.assertEqual(r.stdout.strip(), "")

    def test_bad_input_is_silent(self):
        e = dict(os.environ, HOME=str(self.home))
        r = subprocess.run([sys.executable, str(TRIM)], input="not json", capture_output=True, text=True, env=e)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    # ---- 開關、模式、原文、統計
    def test_switch_off(self):
        log = npm_install_log()
        self.assertIsNone(self.run_hook("npm install", log, env={"CHUTORA_TRIM": "0"}))
        self.conf.mkdir(parents=True)
        (self.conf / "trim").write_text("off\n")
        self.assertIsNone(self.run_hook("npm install", log))

    def test_mode_thresholds(self):
        log = "\n".join(f"   Compiling crate{i:03d} v0.1.0-dev" for i in range(110))  # 110 行、約 3.4k 字元
        self.assertIsNone(self.run_hook("cargo build", log))  # balanced：未達 120 行／4000 字
        self.assertIsNotNone(self.run_hook("cargo build", log, env={"CHUTORA_MODE": "economy"}))
        log2 = "\n".join(f"   Compiling crate{i} v0.1.0" for i in range(200))
        self.assertIsNotNone(self.run_hook("cargo build", log2))
        self.assertIsNone(self.run_hook("cargo build", log2, env={"CHUTORA_MODE": "quality"}))

    def test_raw_saved_and_rotated(self):
        log = npm_install_log()
        new = self.new_output(self.run_hook("npm install", log, tool_use_id="toolu_abc"))
        raw = self.conf / "raw" / "toolu_abc.log"
        self.assertTrue(raw.is_file())
        self.assertIn(str(raw), new["stdout"])
        self.assertIn("reify:pkg-200", raw.read_text().replace("\x1b[32m", "").replace("\x1b[0m", ""))
        for i in range(55):
            self.run_hook("npm install", log, tool_use_id=f"toolu_{i:03d}")
        self.assertEqual(len(list((self.conf / "raw").glob("*.log"))), 50)

    def test_stats_accumulate(self):
        log = npm_install_log()
        self.run_hook("npm install", log, tool_use_id="a")
        self.run_hook("npm install", log, tool_use_id="b")
        st = json.loads((self.conf / "trim-stats.json").read_text())
        self.assertEqual(st["count"], 2)
        self.assertGreater(st["total_chars"], len(log))
        self.assertEqual(sum(st["days"].values()), st["total_chars"])

    def test_english_note(self):
        new = self.new_output(self.run_hook("npm install", npm_install_log(), env={"CHUTORA_LANG": "en"}))
        self.assertIn("Chutora trim", new["stdout"])


if __name__ == "__main__":
    unittest.main()
