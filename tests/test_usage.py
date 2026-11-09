"""用量儀表：usage.py、狀態列的額度／上輪／淨省、usage.json、SessionStart 記錄固定開銷。一律用暫存 HOME。"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
sys.path.insert(0, str(HOOKS))
ANSI = re.compile(r"\033\[[0-9;]*m")
YELLOW, RED = "\033[33m", "\033[31m"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        (self.home / ".claude" / "chutora").mkdir(parents=True)
        self.plug = self.tmp / "plug"
        self.plug.mkdir()
        self._old = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_PLUGIN_ROOT")}
        os.environ["HOME"] = str(self.home)
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(self.plug)
        self.addCleanup(self._restore)
        import usage
        self.usage = usage

    def _restore(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @property
    def upath(self):
        return self.home / ".claude" / "chutora" / "usage.json"

    def env(self, **kw):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("CHUTORA_", "LC_", "LANG", "COLUMNS"))}
        e.update(HOME=str(self.home), CHUTORA_LANG="zh", CLAUDE_PLUGIN_ROOT=str(self.plug))
        e.update(kw)
        return e


def line(**kw):
    d = {"type": "assistant", "message": {"id": kw.pop("mid"), "usage": kw.pop("u")}}
    d.update(kw)
    return d


def user(text="hi", **kw):
    d = {"type": "user", "message": {"role": "user", "content": text}}
    d.update(kw)
    return d


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}


def write_jsonl(p, rows):
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class LastTurnTest(Base):
    def test_sums_after_last_real_prompt_dedup_and_sidechain(self):
        tp = self.tmp / "t.jsonl"
        write_jsonl(tp, [
            user("first"), line(mid="old", u={"input_tokens": 9999, "output_tokens": 9999}),
            user("second"),
            line(mid="a", u={"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 5000, "output_tokens": 5}),
            line(mid="a", u={"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 5000, "output_tokens": 5}),
            tool_result(),  # 不是真正的提示：不切斷這一輪
            line(mid="b", u={"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 5100, "output_tokens": 40}),
            line(mid="side", u={"input_tokens": 7777, "output_tokens": 7777}, isSidechain=True),
            user("meta", isMeta=True),
        ])
        got = self.usage.last_turn_tokens(str(tp))
        self.assertEqual(got, {"input": 11, "cache_write": 100, "cache_read": 10100, "output": 45, "total": 156})

    def test_missing_empty_and_bad(self):
        self.assertIsNone(self.usage.last_turn_tokens(str(self.tmp / "none.jsonl")))
        self.assertIsNone(self.usage.last_turn_tokens(None))
        tp = self.tmp / "e.jsonl"
        tp.write_text("not json\n\n[]\n")
        self.assertIsNone(self.usage.last_turn_tokens(str(tp)))
        write_jsonl(tp, [user("only a prompt")])
        self.assertIsNone(self.usage.last_turn_tokens(str(tp)))

    def test_reads_back_from_big_tail(self):
        """提示在很前面（超過第一次讀的尾巴大小）也要找得到。"""
        tp = self.tmp / "big.jsonl"
        rows = [user("start"), line(mid="x", u={"input_tokens": 3, "output_tokens": 4})]
        rows += [tool_result() for _ in range(6000)]  # 每行約 150 bytes，總量超過 256KB
        write_jsonl(tp, rows)
        self.assertGreater(tp.stat().st_size, 256 << 10)
        self.assertEqual(self.usage.last_turn_tokens(str(tp))["total"], 7)


class UsageFileTest(Base):
    def lim(self, ts, pct=10):
        return {"source": "claude-cli", "updated_at": ts, "five_hour": {"pct": pct, "resets_at": 2000000000}}

    def test_atomic_roundtrip_and_bad_file_is_empty(self):
        self.assertEqual(self.usage.load(), {})
        self.upath.write_text("{broken")
        self.assertEqual(self.usage.load(), {})
        self.upath.write_text("[1]")
        self.assertEqual(self.usage.load(), {})
        self.assertTrue(self.usage.update(limits=self.lim(100), claude={"updated_at": 100, "ctx": 1}, now=100))
        d = json.loads(self.upath.read_text())
        self.assertEqual((d["v"], d["limits"]["five_hour"]["pct"], d["claude"]["ctx"]), (1, 10, 1))
        self.assertEqual([p.name for p in self.upath.parent.iterdir() if p.name.endswith(".tmp")], [])

    def test_limits_only_overwritten_when_newer(self):
        self.usage.update(limits=self.lim(200, 50), now=200)
        self.usage.update(limits=self.lim(100, 10), now=300)  # 較舊的 session：不覆蓋
        self.assertEqual(self.usage.load()["limits"]["five_hour"]["pct"], 50)
        self.usage.update(limits=self.lim(300, 60), now=300)
        self.assertEqual(self.usage.load()["limits"]["five_hour"]["pct"], 60)
        self.usage.update(claude={"updated_at": 301, "ctx": 5}, now=301)  # 只更新 claude 不動 limits
        self.assertEqual(self.usage.load()["limits"]["five_hour"]["pct"], 60)

    def test_same_content_within_5s_not_rewritten(self):
        c = lambda t: {"updated_at": t, "ctx": 5}  # noqa: E731
        self.assertTrue(self.usage.update(limits=self.lim(100), claude=c(100), now=100))
        mt = self.upath.stat().st_mtime_ns
        self.assertFalse(self.usage.update(limits=self.lim(103), claude=c(103), now=103))
        self.assertEqual(self.upath.stat().st_mtime_ns, mt)
        self.assertTrue(self.usage.update(limits=self.lim(106), claude=c(106), now=106))  # 過了 5 秒
        self.assertTrue(self.usage.update(limits=self.lim(107, 11), claude=c(107), now=107))  # 內容變了

    def test_nothing_to_write(self):
        self.assertFalse(self.usage.update())
        self.assertFalse(self.upath.exists())

    def test_limits_from_stdin(self):
        got = self.usage.limits_from_stdin({"five_hour": {"used_percentage": 42.5, "resets_at": 1900000000},
                                            "seven_day": {"used_percentage": "x"}}, now=5)
        self.assertEqual(got, {"source": "claude-cli", "updated_at": 5,
                               "five_hour": {"pct": 42.5, "resets_at": 1900000000}})
        self.assertIsNone(self.usage.limits_from_stdin({}))
        self.assertIsNone(self.usage.limits_from_stdin(None))


class OverheadTest(Base):
    def test_est_tokens(self):
        e = self.usage.est_tokens
        self.assertEqual(e(""), 0)
        self.assertEqual(e("abcd" * 10), 10)  # ASCII 每 4 字元 1 token
        self.assertEqual(e("一二三四"), 4)  # 非 ASCII 每字 1 token
        self.assertEqual(e("abcd一二"), 3)

    def test_overhead_counts_injected_and_descriptors(self):
        (self.plug / "skills" / "a").mkdir(parents=True)
        (self.plug / "skills" / "a" / "SKILL.md").write_text("---\nname: abc\ndescription: 一二三四五六七八\nx: y\n---\nbody body body\n")
        (self.plug / "agents").mkdir()
        (self.plug / "agents" / "w.md").write_text("---\nname: w\ndescription: >\n  one two\n  three\nmodel: haiku\n---\nbody\n")
        od = self.home / ".claude" / "chutora" / "overhead"
        od.mkdir()
        (od / "s1").write_text("1000 100\n")  # ASCII 1000、非 ASCII 100
        (od / "old").write_text("400\n")  # 舊格式：只有一個數字，當全是 ASCII
        # 描述：ASCII abc(3)+w(1)+"one two"(7)+"three"(5)=16、非 ASCII 8
        self.assertEqual(self.usage.descriptor_counts(), (16, 8))
        self.assertEqual(self.usage.overhead_tokens("s1"), self.cal((1000 + 16) // 4 + 108))
        self.assertEqual(self.usage.overhead_tokens("old"), self.cal((400 + 16) // 4 + 8))
        self.assertEqual(self.usage.overhead_tokens("nope"), self.cal(16 // 4 + 8))  # 只有描述
        self.assertEqual(self.usage.overhead_tokens("../x"), self.cal(16 // 4 + 8))

    def cal(self, n):
        return int(round(n * self.usage.OVERHEAD_CALIBRATION))

    def test_descriptor_cache_used_when_plugin_dir_missing(self):
        """狀態列副本（~/.claude/chutora/statusline/）旁邊沒有 skills／agents：讀 SessionStart 時算好的快取。"""
        od = self.home / ".claude" / "chutora" / "overhead"
        od.mkdir()
        (od / ".descriptors").write_text("400 0\n")
        (od / "s1").write_text("0 0\n")
        copy = self.tmp / "sl"
        copy.mkdir()
        (copy / "usage.py").write_text((HOOKS / "usage.py").read_text())
        env = self.env()
        env.pop("CLAUDE_PLUGIN_ROOT")
        r = subprocess.run([sys.executable, "-c", "import usage; print(usage.overhead_tokens('s1'))"],
                           cwd=str(copy), env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout.strip(), "150", r.stderr)  # 400÷4＝100，×1.5 校正

    def test_real_plugin_descriptors_are_counted(self):
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(HOOKS.parent)
        self.assertGreater(sum(self.usage.descriptor_counts()), 500)
        self.assertTrue((self.home / ".claude" / "chutora" / "overhead" / ".descriptors").exists())


class FmtResetTest(Base):
    def test_short_and_far(self):
        f = self.usage.fmt_reset
        self.assertEqual(f(1000 + 2 * 3600 + 13 * 60, 1000), "2h13m")
        self.assertEqual(f(1000 + 45 * 60, 1000), "45m")
        self.assertEqual(f(900, 1000), "0m")
        self.assertEqual(f("x", 1000), "")
        # 本機時區：用 localtime 組出同一個週四 14:00
        t = time.mktime((2026, 11, 12, 14, 0, 0, 0, 0, -1))
        self.assertEqual(f(t, t - 3 * 86400), "週四 14:00")
        self.assertEqual(f(t, t - 3 * 86400, "en"), "Thu 14:00")


class StatuslineUsageTest(Base):
    def sl(self, payload, raw=False, **kw):
        r = subprocess.run([sys.executable, str(HOOKS / "statusline.py")],
                           input=payload if isinstance(payload, str) else json.dumps(payload),
                           capture_output=True, text=True, env=self.env(**kw), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.rstrip("\n") if raw else ANSI.sub("", r.stdout).rstrip("\n")

    def payload(self, five=42, week=18, **kw):
        now = time.time()
        wk = time.mktime((2026, 11, 12, 14, 0, 0, 0, 0, -1))
        d = {"model": {"display_name": "Opus"}, "session_id": "s1", "context_window": {"total_input_tokens": 50000},
             "rate_limits": {"five_hour": {"used_percentage": five, "resets_at": now + 2 * 3600 + 13 * 60 + 30},
                             "seven_day": {"used_percentage": week, "resets_at": wk if wk > now + 86400 * 2 else now + 3 * 86400}}}
        d.update(kw)
        return d

    def test_limits_shown_and_colored(self):
        out = self.sl(self.payload())
        self.assertRegex(out, r"^Opus │ 5h 42%\(2h13m\) │ 週 18%\(週.\d\d:\d\d\) │ ctx 50k$")
        out_en = self.sl(self.payload(), CHUTORA_LANG="en")
        self.assertRegex(out_en, r"5h 42%\(2h13m\) │ wk 18%\([A-Z][a-z]{2} \d\d:\d\d\)")
        for pct, color, shown in ((80, "", True), (81, YELLOW, True), (95, YELLOW, True), (96, RED, True)):
            raw = self.sl(self.payload(five=pct), raw=True)
            seg = re.search(r"(\033\[[0-9;]*m)?5h %d%%" % pct, raw)
            self.assertTrue(seg, raw)
            self.assertEqual(seg.group(1) or "", color, pct)

    def test_no_rate_limits_is_quiet(self):
        p = self.payload()
        del p["rate_limits"]
        self.assertEqual(self.sl(p), "Opus │ ctx 50k")

    def test_last_turn_and_net(self):
        tp = self.tmp / "t.jsonl"
        write_jsonl(tp, [user("q"), line(mid="a", u={"input_tokens": 300, "cache_creation_input_tokens": 12000,
                                                      "cache_read_input_tokens": 90000, "output_tokens": 0})])
        od = self.home / ".claude" / "chutora" / "overhead"
        od.mkdir()
        (od / "s1").write_text("12000\n")  # 3k tokens，×1.5 校正＝4.5k
        act = self.home / ".claude" / "chutora" / "activity"
        act.mkdir()
        (act / "s1.json").write_text(json.dumps({"saved": {"bash": 24000}}))  # 6k tokens
        out = self.sl(self.payload(transcript_path=str(tp), rate_limits=None))
        self.assertIn("│ 上輪 12.3k │ 淨省≈+1.5k", out)
        (act / "s1.json").write_text(json.dumps({"saved": {"bash": 4000}}))  # 1k − 3k×1.5 = −3.5k
        raw = self.sl(self.payload(transcript_path=str(tp), rate_limits=None), raw=True)
        self.assertIn("\033[2m淨≈-3.5k\033[0m", raw)  # 1k − 3k×1.5
        self.assertNotIn(RED, raw)
        en = self.sl(self.payload(transcript_path=str(tp), rate_limits=None), CHUTORA_LANG="en")
        self.assertIn("last 12.3k │ net≈-3.5k", en)

    def test_priority_when_narrow(self):
        tp = self.tmp / "t.jsonl"
        write_jsonl(tp, [user("q"), line(mid="a", u={"input_tokens": 12300, "output_tokens": 0})])
        out = self.sl(self.payload(transcript_path=str(tp)), CHUTORA_STATUS_WIDTH="46")
        self.assertIn("5h 42%", out)
        self.assertIn("ctx 50k", out)
        self.assertNotIn("上輪", out)
        self.assertLessEqual(len(out), 46)

    def test_writes_usage_json_and_debounces(self):
        tp = self.tmp / "t.jsonl"
        write_jsonl(tp, [user("q"), line(mid="a", u={"input_tokens": 1000, "output_tokens": 0})])
        p = self.payload(transcript_path=str(tp))
        self.sl(p)
        d = json.loads(self.upath.read_text())
        self.assertEqual(d["limits"]["source"], "claude-cli")
        self.assertEqual(d["limits"]["five_hour"]["pct"], 42)
        self.assertEqual(d["claude"]["session_id"], "s1")
        self.assertEqual(d["claude"]["last_turn"]["total"], 1000)
        self.assertEqual(d["claude"]["ctx"], 50000)
        for k in ("updated_at", "surface", "saved", "overhead", "net"):
            self.assertIn(k, d["claude"])
        mt = self.upath.stat().st_mtime_ns
        self.sl(p)
        self.assertEqual(self.upath.stat().st_mtime_ns, mt)

    def test_bad_input_is_quiet_and_writes_nothing(self):
        for raw in ("not json", "", "[]", "null"):
            self.assertEqual(self.sl(raw), "")
        self.assertFalse(self.upath.exists())


class SessionStartOverheadTest(Base):
    def run_hook(self, sid="sess-1", **kw):
        proj = self.tmp / "proj"
        proj.mkdir(exist_ok=True)
        env = self.env(CHUTORA_WEEKLY="0", CLAUDE_PROJECT_DIR=str(proj), **kw)
        return subprocess.run(["sh", str(HOOKS / "session-start.sh")], input=json.dumps({"session_id": sid}),
                              capture_output=True, text=True, env=env, cwd=str(proj), timeout=30)

    def test_records_injected_chars(self):
        (self.home / ".claude" / "hooks").mkdir(parents=True)
        (self.home / ".claude" / "hooks" / ".route-setup-done").write_text("")  # 純文字模式
        r = self.run_hook(CLAUDE_PLUGIN_DATA=str(self.home / ".claude" / "hooks"))
        self.assertEqual(r.returncode, 0)
        rec = self.home / ".claude" / "chutora" / "overhead" / "sess-1"
        a, na = (int(x) for x in rec.read_text().split())  # ASCII、非 ASCII 字元數
        self.assertAlmostEqual(a + na, len(r.stdout.strip()), delta=3)  # 字元數（不是 byte）
        self.assertTrue(a > 0 and na > 0)
        self.assertLess(a + na, len(r.stdout.encode()))
        self.assertAlmostEqual(na, sum(1 for c in r.stdout if ord(c) > 127), delta=3)

    def test_records_in_json_mode_without_counting_system_message(self):
        r = self.run_hook(sid="sess-2")  # 沒有 route-setup 標記：JSON 模式
        d = json.loads(r.stdout)
        ctx = d["hookSpecificOutput"]["additionalContext"]
        a, na = (int(x) for x in (self.home / ".claude" / "chutora" / "overhead" / "sess-2").read_text().split())
        self.assertAlmostEqual(a + na, len(ctx.strip()), delta=3)

    def test_no_session_id_no_record_and_unsafe_id(self):
        proj = self.tmp / "proj"
        proj.mkdir()
        subprocess.run(["sh", str(HOOKS / "session-start.sh")], input="{}", capture_output=True, text=True,
                       env=self.env(CHUTORA_WEEKLY="0"), cwd=str(proj), timeout=30)
        self.assertFalse((self.home / ".claude" / "chutora" / "overhead").exists())
        self.run_hook(sid="../../evil")
        self.assertFalse((self.home / ".claude" / "evil").exists())

    def test_no_context_reminder_text_in_guides(self):
        for name in ("guide.md", "guide.en.md"):
            t = (HOOKS / name).read_text()
            self.assertNotIn("UserPromptSubmit hook", t)
            self.assertNotIn("context reminder", t)
        for p in (HOOKS / "modes").glob("*.md"):
            self.assertNotIn("context 提醒", p.read_text())


if __name__ == "__main__":
    unittest.main()


class CompactSummaryTest(unittest.TestCase):
    """/compact 之後的壓縮摘要不算使用者提示（快照與「上輪」都不該把它當提示）。"""

    def test_compact_summary_not_prompt(self):
        sys.path.insert(0, str(HOOKS))
        import usage
        base = {"type": "user", "message": {"role": "user", "content": "This session is being continued from a previous conversation that ran out of context."}}
        self.assertFalse(usage.is_real_prompt(base))
        self.assertFalse(usage.is_real_prompt({**base, "isCompactSummary": True, "message": {"role": "user", "content": "摘要"}}))
        self.assertTrue(usage.is_real_prompt({"type": "user", "message": {"role": "user", "content": "跑測試"}}))
