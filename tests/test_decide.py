"""決策引擎（plugins/chutora/hooks/decide.py）的測試：公式、平滑、冷啟動、相似度、校準、門檻與模式。"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
DECIDE = HOOKS / "decide.py"
sys.path.insert(0, str(HOOKS))
import decide  # noqa: E402


def past(outcome, feats, probs=None, feedback="record", weight=1.0, ts=None, dtype="t"):
    f = dict(feats, type=dtype)
    return {"id": "x", "type": dtype, "features": f, "outcome": outcome, "feedback": feedback, "weight": weight,
            "raw": probs or {}, "probs": probs or {}, "resolved_ts": ts if ts is not None else time.time() - 999999}


class MathTest(unittest.TestCase):
    def test_formula_matches_definition(self):
        p, n, w = decide.mix(["a", "b"], {"a": 3, "b": 1}, {"a": 0.2, "b": 0.8})
        self.assertAlmostEqual(n, 4)
        self.assertAlmostEqual(w, 4 / 9)
        self.assertAlmostEqual(p["a"], (4 / 9) * (4 / 6) + (5 / 9) * 0.2)
        self.assertAlmostEqual(sum(p.values()), 1.0)

    def test_no_history_uses_claude_or_uniform(self):
        p, n, w = decide.mix(["a", "b", "c"], {}, None)
        self.assertEqual(n, 0)
        for v in p.values():
            self.assertAlmostEqual(v, 1 / 3)
        p, _, _ = decide.mix(["a", "b"], {}, {"a": 3, "b": 1})
        self.assertAlmostEqual(p["a"], 0.75)

    def test_smoothing_never_reaches_certainty(self):
        p, _, _ = decide.mix(["a", "b"], {"a": 50}, None)
        self.assertLess(p["a"], 1.0)
        self.assertGreater(p["b"], 0.0)

    def test_similarity_rules(self):
        a = {"type": "t", "category": "rm", "path": "build", "branch": "main"}
        self.assertEqual(decide.similarity(a, dict(a)), 1.0)
        self.assertEqual(decide.similarity(a, dict(a, type="u")), 0.0)
        self.assertLess(decide.similarity(a, dict(a, branch="dev")), 1.0)
        self.assertGreater(decide.similarity(a, dict(a, path="build/*")), decide.similarity(a, dict(a, path="src")))

    def test_only_similar_records_count(self):
        feats = {"category": "rm", "path": "build", "action": "rm"}
        far = past("b", {"category": "other", "path": "src", "action": "mv"})
        near = past("a", feats)
        counts, _, _, _ = decide.gather([far, near], dict(feats, type="t"), ["a", "b"])
        self.assertEqual(counts["b"], 0)
        self.assertAlmostEqual(counts["a"], 1.0)

    def test_brier(self):
        self.assertAlmostEqual(decide.brier({"a": 0.7, "b": 0.3}, "a"), 0.09 + 0.09)
        self.assertAlmostEqual(decide.brier({"a": 1.0, "b": 0.0}, "a"), 0.0)

    def test_calibration_pulls_overconfident_bucket_down(self):
        hist = []
        for i in range(10):  # 預測 0.7 那桶只對六成
            hist.append({"type": "t", "outcome": "a" if i < 6 else "b", "raw": {"a": 0.72, "b": 0.28}})
        p, info = decide.calibrate({"a": 0.72, "b": 0.28}, "t", hist)
        self.assertLess(p["a"], 0.72)
        self.assertIn("a", info)
        p2, info2 = decide.calibrate({"a": 0.72, "b": 0.28}, "t", hist[:3])  # 樣本太少不修
        self.assertAlmostEqual(p2["a"], 0.72)
        self.assertEqual(info2, {})

    def test_thresholds_and_modes(self):
        self.assertEqual(decide.threshold(True, False, "balanced"), 0.70)
        self.assertEqual(decide.threshold(True, True, "balanced"), 0.85)
        self.assertIsNone(decide.threshold(False, True, "balanced"))
        self.assertIsNone(decide.threshold(None, False, "balanced"))
        self.assertAlmostEqual(decide.threshold(True, True, "economy"), 0.80)
        self.assertAlmostEqual(decide.threshold(True, True, "quality"), 0.90)
        self.assertAlmostEqual(decide.threshold(True, False, "balanced", cold=True), 0.80)

    def test_cold_start_never_auto(self):
        r = decide.score("t", ["a", "b"], {}, {"a": 0.79, "b": 0.21}, True, False, [], "balanced")
        self.assertTrue(r["cold"])
        self.assertEqual(r["action"], "ask")
        r = decide.score("t", ["a", "b"], {}, {"a": 0.9, "b": 0.1}, True, False, [], "balanced")
        self.assertEqual(r["action"], "auto")

    def test_irreversible_never_auto_even_if_certain(self):
        hist = [past("a", {"k": "v"}, feedback="auto") for _ in range(30)]
        r = decide.score("t", ["a", "b"], {"k": "v"}, {"a": 1, "b": 0}, False, True, hist, "economy")
        self.assertEqual(r["action"], "ask")
        r = decide.score("t", ["a", "b"], {"k": "v"}, {"a": 1, "b": 0}, False, True, hist, "economy", unattended=True)
        self.assertEqual(r["action"], "skip-todo")

    def test_unattended_picks_best_or_todo(self):
        r = decide.score("t", ["a", "b"], {}, {"a": 0.6, "b": 0.4}, True, True, [], "balanced", unattended=True)
        self.assertEqual((r["action"], r["best"]), ("auto-unattended", "a"))
        r = decide.score("t", ["a", "b", "c"], {}, {"a": 0.4, "b": 0.35, "c": 0.25}, False, False, [], unattended=True)
        self.assertEqual(r["action"], "skip-todo")

    def test_user_preference_and_undo_cooldown(self):
        feats = {"category": "rm-in-project", "path": "build"}
        grant = past("auto", feats, feedback="auto", ts=time.time() - 100, dtype=decide.AUTO_TYPE)
        r = decide.score(decide.AUTO_TYPE, ["auto", "ask"], feats, None, True, False, [grant], "balanced")
        self.assertEqual(r["prior"], "user:auto")
        self.assertEqual(r["action"], "auto")
        self.assertTrue(r["simple"])
        undo = past("ask", feats, feedback="undo", weight=3, ts=time.time() - 10, dtype=decide.AUTO_TYPE)
        r = decide.score(decide.AUTO_TYPE, ["auto", "ask"], feats, None, True, False, [grant, undo], "balanced")
        self.assertTrue(r["cooldown"])
        self.assertEqual(r["best"], "ask")
        self.assertEqual(r["action"], "ask")


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.proj = self.home / "proj"
        (self.proj / "claude-memory").mkdir(parents=True)

    def run_cli(self, *args):
        e = dict(os.environ, HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG="zh")
        e.pop("CHUTORA_MODE", None)
        r = subprocess.run([sys.executable, str(DECIDE)] + list(args), capture_output=True, text=True, env=e,
                           cwd=str(self.proj), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def test_score_record_stats_roundtrip(self):
        out = json.loads(self.run_cli("score", "--type", "pick", "--options", "x,y", "--claude", "x=0.7,y=0.3",
                                      "--feature", "area=docs", "--recoverable", "yes", "--impact", "no"))
        self.assertEqual(out["best"], "x")
        self.assertEqual(out["action"], "ask")  # 冷啟動 0.80
        rec = json.loads(self.run_cli("record", out["id"], "x"))
        self.assertAlmostEqual(rec["brier"], 0.18, places=3)
        lines = (self.proj / "claude-memory" / "decisions.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        st = json.loads(self.run_cli("stats"))
        self.assertEqual(st["resolved"], 1)
        out2 = json.loads(self.run_cli("score", "--type", "pick", "--options", "x,y", "--feature", "area=docs",
                                       "--recoverable", "yes", "--impact", "no", "--no-record"))
        self.assertFalse(out2["cold"])
        self.assertGreater(out2["probs"]["x"], 0.5)

    def test_remote_is_never_auto(self):
        out = json.loads(self.run_cli("score", "--type", "push", "--options", "push,wait", "--claude", "push=1",
                                      "--remote", "--unattended"))
        self.assertEqual(out["action"], "skip-todo")
        self.assertFalse(out["recoverable"])

    def test_path_reversibility(self):
        (self.proj / "build").mkdir()
        (self.proj / "build" / "a.o").write_text("x")
        out = json.loads(self.run_cli("score", "--type", "clean", "--options", "yes,no", "--path", "build",
                                      "--no-record"))
        self.assertEqual(out["basis"], "regenerable")
        self.assertFalse(out["impact"])
        out = json.loads(self.run_cli("score", "--type", "clean", "--options", "yes,no", "--path", "../x",
                                      "--no-record"))
        self.assertFalse(out["recoverable"])


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.proj = self.home / "proj"
        (self.proj / "claude-memory").mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG="zh",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")

    def sh(self, *cmd):
        r = subprocess.run(list(cmd), capture_output=True, text=True, env=self.env, cwd=str(self.proj), timeout=30)
        return r

    def cli(self, *args):
        return self.sh(sys.executable, str(DECIDE), *args)

    def test_snapshot_and_undo_directory(self):
        (self.proj / "build" / "sub").mkdir(parents=True)
        (self.proj / "build" / "sub" / "a.txt").write_text("hello")
        r = self.cli("snapshot", "--summary", "rm -rf build", "build")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        cid = json.loads(r.stdout)["change_id"]
        import shutil
        shutil.rmtree(self.proj / "build")
        r = self.cli("undo", cid)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.proj / "build" / "sub" / "a.txt").read_text(), "hello")
        r = self.cli("undo", cid)  # 第二次不能再復原
        self.assertEqual(r.returncode, 1)
        ch = [json.loads(x) for x in (self.proj / "claude-memory" / "changes.jsonl").read_text().splitlines()]
        self.assertTrue(any(x.get("update", {}).get("user_response") == "undone" for x in ch))

    def test_undo_moves_current_aside(self):
        (self.proj / "conf.toml").write_text("old")
        r = self.cli("snapshot", "--config", "conf.toml")
        cid = json.loads(r.stdout)["change_id"]
        rp = Path(json.loads(r.stdout)["restore_point"])
        self.assertTrue(any(".2" in p.name for p in (rp / "files").iterdir()))  # 時間戳複本
        (self.proj / "conf.toml").write_text("new")
        self.assertEqual(self.cli("undo", cid).returncode, 0)
        self.assertEqual((self.proj / "conf.toml").read_text(), "old")
        self.assertTrue(list(rp.glob("replaced-*/*conf.toml")))

    def test_too_big_fails(self):
        (self.proj / "big").write_bytes(b"x" * 300000)
        self.env["CHUTORA_BACKUP_MAX_MB"] = "0.1"
        r = self.cli("snapshot", "big")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.proj / "claude-memory" / "changes.jsonl").exists())

    def test_git_reset_hard_restore(self):
        self.sh("git", "init", "-q")
        (self.proj / "f.txt").write_text("v1")
        self.sh("git", "add", "f.txt")
        self.sh("git", "commit", "-qm", "one")
        (self.proj / "f.txt").write_text("v2")
        self.sh("git", "commit", "-qam", "two")
        (self.proj / "f.txt").write_text("v3 uncommitted")
        sys.path.insert(0, str(HOOKS))
        old = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            man = decide.snapshot([], str(self.proj), git=True, kind="git-reset-hard")
        finally:
            os.environ["HOME"] = old
        self.assertIsNotNone(man)
        self.assertTrue(man["git"]["stash"])
        self.assertEqual((self.proj / "f.txt").read_text(), "v3 uncommitted")  # stash create 不動工作區
        self.sh("git", "reset", "--hard", "HEAD~1")
        self.assertEqual((self.proj / "f.txt").read_text(), "v1")
        ok, msgs = decide.restore(man)
        self.assertTrue(ok, msgs)
        self.assertEqual((self.proj / "f.txt").read_text(), "v3 uncommitted")
        self.assertIn("two", self.sh("git", "log", "-1", "--format=%s").stdout)


class NotifyFeedbackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.proj = self.home / "proj"
        (self.proj / "claude-memory").mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG="zh")
        self.old = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_PROJECT_DIR", "CHUTORA_LANG")}
        os.environ.update(HOME=str(self.home), CLAUDE_PROJECT_DIR=str(self.proj), CHUTORA_LANG="zh")
        self.addCleanup(self.restore_env)

    def restore_env(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_py(self, script, *args, stdin=""):
        r = subprocess.run([sys.executable, str(script)] + list(args), input=stdin, capture_output=True, text=True,
                           env=self.env, cwd=str(self.proj), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def auto_action(self, category="rm-in-project"):
        import changes
        feats = {"category": category, "path": "build", "action": "rm -r"}
        res = decide.score(decide.AUTO_TYPE, ["auto", "ask"], feats, None, True, False, [], "balanced")
        (self.proj / "build").mkdir(exist_ok=True)
        man = decide.snapshot(["build"], str(self.proj))
        cid = changes.record("auto_allow", "Bash: rm -rf build", project_dir=str(self.proj),
                             restore_point=os.path.join(man["dir"], "manifest.json"), category=category)
        decide.record_decision(res, pd=str(self.proj), change_id=cid, auto=True)
        return cid

    def prompt(self, text):
        out = self.run_py(DECIDE, "notify", stdin=json.dumps({"prompt": text, "cwd": str(self.proj)}))
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""

    def test_notify_until_response(self):
        self.assertEqual(self.prompt("hello"), "")  # 沒有待確認：不輸出、不加 token
        cid = self.auto_action()
        ctx = self.prompt("hello")
        self.assertIn(cid, ctx)
        self.assertIn("一行", ctx)
        self.assertIn(cid, self.prompt("next"))  # 沒回應就持續提醒
        ctx = self.prompt(f"/chutora ok {cid} auto")  # 使用者本人回覆：由 hook 直接處理
        self.assertIn("已依使用者這則訊息處理", ctx)
        self.assertEqual(self.prompt("after"), "")
        ds = decide.load_decisions(str(self.proj))
        d = [x for x in ds if x.get("change_id") == cid][0]
        self.assertEqual((d["outcome"], d["feedback"]), ("auto", "auto"))
        self.assertIsNotNone(d.get("brier"))

    def test_ok_ask_and_all(self):
        a, b = self.auto_action(), self.auto_action()
        done, msgs = decide.feedback("all", "ask", str(self.proj))
        self.assertEqual(done, 2)
        self.assertEqual(decide.pending(str(self.proj)), [])
        ds = decide.load_decisions(str(self.proj))
        self.assertEqual({x["outcome"] for x in ds if x.get("change_id") in (a, b)}, {"ask"})

    def test_hard_category_cannot_be_learned(self):
        cid = self.auto_action(category="force-push")
        done, msgs = decide.feedback(cid, "auto", str(self.proj))
        self.assertIn("不能學成自動", msgs[0])
        ds = decide.load_decisions(str(self.proj))
        self.assertIsNone([x for x in ds if x.get("change_id") == cid][0].get("outcome"))

    def test_undo_via_prompt_and_hub(self):
        cid = self.auto_action()
        (self.proj / "build" / "x").write_text("1")
        cid2 = self.auto_action()  # 這次的復原點含 x
        import shutil
        shutil.rmtree(self.proj / "build")
        ctx = self.prompt(f"/chutora undo {cid2}")
        self.assertIn("已復原", ctx)
        self.assertTrue((self.proj / "build" / "x").exists())
        hub = ROOT / "plugins" / "chutora" / "skills" / "chutora-hub" / "chutora.py"
        out = self.run_py(hub, "changes")
        self.assertIn("待確認 1", out)
        self.assertIn(cid, out)
        out = self.run_py(hub, "ok", cid)
        self.assertIn("已讀", out)
        self.assertIn("待確認 0", self.run_py(hub, "changes"))

    def test_record_refuses_auto_decisions(self):
        cid = self.auto_action()
        d = [x for x in decide.load_decisions(str(self.proj)) if x.get("change_id") == cid][0]
        r = subprocess.run([sys.executable, str(DECIDE), "record", d["id"], "auto"], capture_output=True, text=True,
                           env=self.env, cwd=str(self.proj), timeout=30)
        self.assertEqual(r.returncode, 1)

    def test_statusline_count(self):
        self.auto_action()
        data = {"session_id": "s", "model": {"display_name": "Opus"}, "cwd": str(self.proj),
                "workspace": {"project_dir": str(self.proj)}, "context_window": {"total_input_tokens": 1000}}
        out = self.run_py(HOOKS / "statusline.py", stdin=json.dumps(data))
        self.assertIn("待確認 1", out)

    def test_guard_blocks_self_grant(self):
        import guard
        for cmd in ("python3 skills/chutora-hub/chutora.py ok all auto", "python3 hooks/decide.py ok x auto",
                    "echo '{}' >> claude-memory/decisions.jsonl"):
            r = guard.explain(cmd, str(self.proj))
            self.assertTrue(r and any(h[0] == "self-grant" for h in r[1]), cmd)
        for cmd in ("python3 hooks/decide.py ok x ask", "python3 hooks/decide.py undo x", "cat claude-memory/decisions.jsonl"):
            self.assertIsNone(guard.explain(cmd, str(self.proj)), cmd)
        self.assertIn("self-grant", guard.BYPASS_DENY)


if __name__ == "__main__":
    unittest.main()
