"""損益表（hooks/ledger.py）與 /chutora ledger。"""
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
HUB = ROOT / "plugins" / "chutora" / "skills" / "chutora-hub" / "chutora.py"
TZ = datetime.timezone(datetime.timedelta(hours=8))
NOW = datetime.datetime(2026, 11, 10, 12, 0, 0, tzinfo=TZ)


def load():
    sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location("chutora_ledger_test", HOOKS / "ledger.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ts(days_ago, now=NOW):
    return (now - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S%z")


def rec(signal, days_ago=1, session="s1", agent="main", **kw):
    return dict({"ts": ts(days_ago), "session": session, "agent": agent, "signal": signal}, **kw)


SAMPLE = [
    rec("user_prompt", chars=10), rec("user_prompt", chars=20), rec("user_correction", chars=5),
    rec("user_choice", chars=1),                                   # 使用者回的選項：算提示
    rec("user_choice", tool="AskUserQuestion"),                    # 工具回來的答案：算動作，不算提示
    rec("tool_ok", tool="Bash"), rec("tool_ok", tool="Read"), rec("tool_ok", tool="Read", session="s2"),
    rec("tool_fail", tool="Bash"), rec("repeat_error", tool="Bash", count=2),
    rec("tool_fail", tool="Bash", interrupted=True),               # 使用者中斷：不算失誤
    rec("guard_ask", tool="Bash"), rec("guard_ask", tool="Bash"), rec("guard_deny", tool="Bash"),
    rec("trimmed", tool="Bash", kind="bash", orig_chars=9000, saved_chars=4000),
    rec("trimmed", tool="mcp__x__y", kind="mcp", orig_chars=20000, saved_chars=12000),
    rec("trimmed", tool="Bash", kind="bash", orig_chars=3000, saved_chars=1000),
    rec("reread", tool="Read", n=2, saved_chars=3001),
    rec("delegation_result", agent="worker", summary="狀態：完成\n驗證：通過\n改了兩個檔"),
    rec("delegation_result", agent="worker", summary="狀態:失敗\n驗證:失敗"),
    rec("delegation_result", agent="worker", summary="狀態：需要決策"),
    rec("delegation_result", agent="worker", summary="Status: done\nVerification: passed"),
    rec("delegation_result", agent="Explore", summary="找到三個檔案"),
    rec("user_prompt", days_ago=30, session="old"), rec("tool_fail", days_ago=30, session="old", tool="Bash"),
    rec("trimmed", days_ago=8, session="old", kind="bash", saved_chars=99999),
]


class LedgerCollectTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.ddir = self.home / ".claude" / "chutora" / "projects" / "abc"
        self.ddir.mkdir(parents=True)
        p = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.led = load()

    def write(self, records, name="observations.jsonl"):
        path = self.ddir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records) + "not json\n", encoding="utf-8")

    def collect(self, **kw):
        return self.led.collect([str(self.ddir)], now=NOW, transcripts=str(self.tmp / "none"), **kw)

    def test_counts(self):
        self.write(SAMPLE)
        d = self.collect()
        self.assertEqual((d["sessions"], d["prompts"], d["actions"], d["corrections"]), (2, 4, 7, 1))
        self.assertEqual(d["per_prompt"]["actions"], 1.75)

    def test_income_is_saved_chars_div_4(self):
        self.write(SAMPLE)
        s = self.collect()["saved"]
        self.assertEqual(s["trim"], {"bash": {"n": 2, "chars": 5000}, "mcp": {"n": 1, "chars": 12000}})
        self.assertEqual(s["reread"], {"n": 1, "chars": 3001})
        self.assertEqual((s["chars"], s["tokens"]), (20001, 5000))

    def test_intercepts_are_not_failures(self):
        self.write(SAMPLE)
        d = self.collect()
        self.assertEqual(d["guard"], {"ask": 2, "deny": 1})
        self.assertEqual(d["fail"], {"tool_fail": 1, "repeat_error": 1, "interrupted": 1})
        self.assertEqual(d["fails"], 2)

    def test_delegation_status(self):
        self.write(SAMPLE)
        a = self.collect()["agents"]
        self.assertEqual(a["worker"], {"n": 4, "done": 2, "failed": 1, "decision": 1, "unmarked": 0, "verified": 2})
        self.assertEqual(a["Explore"], {"n": 1, "done": 0, "failed": 0, "decision": 0, "unmarked": 1, "verified": 0})

    def test_window(self):
        self.write(SAMPLE)
        self.assertEqual(self.collect(days=60)["sessions"], 3)
        d = self.collect(days=9)
        self.assertEqual(d["saved"]["trim"]["bash"]["chars"], 5000 + 99999)
        self.assertEqual(d["prompts"], 4)

    def test_overhead_and_net(self):
        self.write(SAMPLE)
        od = self.home / ".claude" / "chutora" / "overhead"
        od.mkdir(parents=True)
        (od / "s1").write_text("400 100")
        import usage
        d = self.collect()
        want = usage.overhead_tokens("s1") + usage.overhead_tokens("s2")
        self.assertGreater(usage.overhead_tokens("s1"), usage.overhead_tokens("s2"))
        self.assertEqual(d["overhead"], {"tokens": want, "sessions": 2, "measured": 1})
        self.assertEqual(d["net_tokens"], 5000 - want)
        self.assertEqual(d["per_prompt"]["net_tokens"], round((5000 - want) / 4))

    def test_archive_is_read(self):
        self.write(SAMPLE[:3], "archive/observations-20261109-000000-1.jsonl")
        self.write(SAMPLE[3:])
        self.assertEqual(self.collect()["prompts"], 4)

    def test_same_input_same_output(self):
        self.write(SAMPLE)
        a, b = self.collect(), self.collect()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(self.led.render(a, "zh"), self.led.render(b, "zh"))

    def test_actual_usage_from_transcripts(self):
        self.write(SAMPLE)
        root = self.tmp / "projects" / "-x"
        (root / "s1" / "subagents").mkdir(parents=True)

        def line(typ, mid, days_ago, **kw):
            d = {"type": typ, "timestamp": (NOW - datetime.timedelta(days=days_ago)).astimezone(datetime.timezone.utc)
                 .isoformat().replace("+00:00", "Z")}
            if typ == "assistant":
                d["message"] = {"id": mid, "model": "claude-opus-5-5", "usage": dict(kw)}
            else:
                d["message"] = {"role": "user", "content": "hi"}
            return json.dumps(d) + "\n"

        (root / "s1.jsonl").write_text(
            line("user", None, 1) + line("assistant", "m1", 1, input_tokens=100, output_tokens=50, cache_read_input_tokens=1000)
            + line("assistant", "m1", 1, input_tokens=100, output_tokens=50, cache_read_input_tokens=1000)  # 同一則重複
            + line("user", None, 1) + line("assistant", "m2", 1, input_tokens=10, output_tokens=5)
            + line("assistant", "m3", 30, input_tokens=99999, output_tokens=1))                               # 視窗外
        (root / "s1" / "subagents" / "agent-a.jsonl").write_text(line("assistant", "a1", 1, input_tokens=300, output_tokens=30))
        (root / "zzz.jsonl").write_text(line("assistant", "z1", 1, input_tokens=5000, output_tokens=1))       # 別的對話
        a = self.led.collect([str(self.ddir)], now=NOW, transcripts=str(self.tmp / "projects"))["actual"]
        self.assertEqual((a["main_tokens"], a["sub_tokens"], a["prompts"], a["sessions"]), (1165, 330, 2, 1))
        self.assertIsNone(self.collect()["actual"])

    def test_render(self):
        self.write(SAMPLE)
        d = self.collect()
        zh, en = self.led.render(d, "zh"), self.led.render(d, "en")
        for want in ("損益表", "輸出瘦身（bash）：2 次，省 5,000 字元", "合計 ≈ 5,000 token", "真失誤：2 次（佔動作 28.6%",
                     "守門攔截：3 次（先問 2、擋下 1）", "被你糾正：1 次", "你中斷的：1 次",
                     "worker：4 次——完成 2、失敗 1、需要決策 1（成功率 50.0%）", "Explore：1 次，沒有標示狀態"):
            self.assertIn(want, zh)
        for want in ("Chutora ledger", "Real failures: 2", "Guard intercepts: 3", "worker: 4× — done 2"):
            self.assertIn(want, en)
        self.assertNotIn("改了兩個檔", zh)  # 不輸出摘要內容

    def test_empty(self):
        d = self.collect()
        self.assertEqual((d["sessions"], d["net_tokens"], d["actual"]), (0, 0, None))
        self.assertIn("沒有觀察紀錄", self.led.render(d, "zh"))
        self.assertIn("No observations", self.led.render(d, "en"))


class LedgerCommandTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name).resolve() / "home"
        self.proj = self.home / "proj"
        self.proj.mkdir(parents=True)

    def env(self, lang="zh"):
        e = dict(os.environ, HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG=lang)
        e.pop("CHUTORA_OBSERVE", None)
        return e

    def run_hub(self, *args, lang="zh"):
        return subprocess.run([sys.executable, str(HUB), *args], capture_output=True, text=True, env=self.env(lang),
                              cwd=str(self.proj))

    def seed(self):
        r = subprocess.run([sys.executable, "-c", "import projectid; print(projectid.project_data_dir())"],
                           capture_output=True, text=True, env=self.env(), cwd=str(HOOKS))
        ddir = Path(r.stdout.strip())
        now = datetime.datetime.now().astimezone()
        recs = [dict(x, ts=ts(0.01, now)) for x in SAMPLE[:19]]
        (ddir / "observations.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in recs), encoding="utf-8")

    def test_command(self):
        self.seed()
        r = self.run_hub("ledger")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Chutora 損益表（過去 7 天，本專案）", r.stdout)
        self.assertIn("淨省 ≈", r.stdout)
        self.assertIn("Chutora ledger (past 30 days, all projects)", self.run_hub("ledger", "30", "all", lang="en").stdout)
        d = json.loads(self.run_hub("損益表", "json").stdout)
        self.assertEqual((d["v"], d["prompts"], d["saved"]["tokens"]), (1, 4, 5000))

    def test_no_data_and_bad_arg(self):
        r = self.run_hub("ledger")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("沒有觀察紀錄", r.stdout)
        self.assertFalse((self.home / ".claude" / "chutora" / "projects").exists())  # 唯讀：不建資料夾
        r = self.run_hub("ledger", "bogus")
        self.assertEqual(r.returncode, 2)
        self.assertIn("用法", r.stdout)


if __name__ == "__main__":
    unittest.main()
