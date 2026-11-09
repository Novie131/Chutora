"""讀檔去重 hook（plugins/chutora/hooks/dedup.py）的測試。一律用暫存 HOME 與假的 transcript。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEDUP = ROOT / "plugins" / "chutora" / "hooks" / "dedup.py"
BIG = "\n".join(f"line {i}: some source code here = {i * 7}" for i in range(200))


class DedupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.proj = self.home / ".claude" / "projects" / "-p"
        self.proj.mkdir(parents=True)
        self.tp = self.proj / "sess1.jsonl"
        self.entries = []
        self.n = 0

    # 假的 transcript：assistant tool_use → user tool_result，一條鏈
    def add_read(self, tool_use_id, parent=None):
        p = parent if parent is not None else (self.entries[-1]["uuid"] if self.entries else None)
        self.n += 1
        a = {"uuid": f"a{self.n}", "parentUuid": p, "type": "assistant",
             "message": {"content": [{"type": "tool_use", "id": tool_use_id, "name": "Read"}]}}
        u = {"uuid": f"u{self.n}", "parentUuid": a["uuid"], "type": "user",
             "message": {"content": [{"type": "tool_result", "tool_use_id": tool_use_id}]}}
        self.entries += [a, u]
        self.flush()
        return u["uuid"]

    def flush(self):
        self.tp.write_text("\n".join(json.dumps(e) for e in self.entries) + "\n")

    def run_hook(self, tool_use_id, content=BIG, agent_id=None, env=None, path="/p/src/app.py", tool_input=None, **resp_extra):
        data = {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_use_id": tool_use_id,
                "session_id": "sess1", "transcript_path": str(self.tp),
                "tool_input": tool_input or {"file_path": path},
                "tool_response": dict({"type": "text", "file": {"filePath": path, "content": content,
                                                                 "numLines": content.count("\n") + 1, "startLine": 1,
                                                                 "totalLines": content.count("\n") + 1}}, **resp_extra)}
        if agent_id:
            data["agent_id"] = agent_id
        e = dict(os.environ, HOME=str(self.home), CHUTORA_LANG="zh")
        e.pop("CHUTORA_DEDUP", None)
        e.update(env or {})
        r = subprocess.run([sys.executable, str(DEDUP)], input=json.dumps(data), capture_output=True, text=True, env=e, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_first_read_untouched(self):
        self.add_read("t1")
        self.assertIsNone(self.run_hook("t1"))

    def test_repeat_unchanged_is_deduped(self):
        self.add_read("t1")
        self.run_hook("t1")
        self.add_read("t2")
        out = self.run_hook("t2")
        self.assertIsNotNone(out)
        new = out["hookSpecificOutput"]["updatedToolOutput"]
        self.assertEqual(new["type"], "text")
        self.assertIn("Chutora 去重", new["file"]["content"])
        self.assertIn("t1", new["file"]["content"])
        self.assertEqual(new["file"]["filePath"], "/p/src/app.py")
        st = json.loads((self.home / ".claude" / "chutora" / "trim-stats.json").read_text())
        self.assertGreater(st["kinds"]["dedup"], 1000)

    def test_changed_content_not_deduped(self):
        self.add_read("t1")
        self.run_hook("t1")
        self.add_read("t2")
        self.assertIsNone(self.run_hook("t2", content=BIG + "\nnew line"))

    def test_different_range_not_deduped(self):
        self.add_read("t1")
        self.run_hook("t1")
        self.add_read("t2")
        self.assertIsNone(self.run_hook("t2", tool_input={"file_path": "/p/src/app.py", "offset": 10, "limit": 50}))

    def test_other_context_not_deduped(self):
        self.add_read("t1")
        self.run_hook("t1")  # 主對話讀過
        self.add_read("t2")
        self.assertIsNone(self.run_hook("t2", agent_id="agent-x"))  # 子 agent 第一次讀：不去重

    def test_not_on_current_chain_after_rewind_or_compact(self):
        root = self.add_read("t1")
        self.run_hook("t1")
        # 模擬 /rewind 或壓縮：新的一支從 None 開始，舊的 t1 不在目前這條鏈上
        self.add_read("t2", parent="")
        self.entries[-2]["parentUuid"] = None
        self.flush()
        self.assertIsNone(self.run_hook("t2"))
        self.assertTrue(root)

    def test_missing_transcript_not_deduped(self):
        self.add_read("t1")
        self.run_hook("t1")
        self.tp.unlink()
        self.assertIsNone(self.run_hook("t2"))

    def test_small_file_and_images_skipped(self):
        self.add_read("t1")
        self.run_hook("t1", content="short")
        self.add_read("t2")
        self.assertIsNone(self.run_hook("t2", content="short"))
        data_img = self.run_hook("t3", type="image")
        self.assertIsNone(data_img)

    def test_switch_off(self):
        self.add_read("t1")
        self.run_hook("t1")
        self.add_read("t2")
        self.assertIsNone(self.run_hook("t2", env={"CHUTORA_DEDUP": "0"}))
        conf = self.home / ".claude" / "chutora"
        (conf / "dedup").write_text("off\n")
        self.add_read("t3")
        self.assertIsNone(self.run_hook("t3"))

    def test_english_stub(self):
        self.add_read("t1")
        self.run_hook("t1")
        self.add_read("t2")
        out = self.run_hook("t2", env={"CHUTORA_LANG": "en"})
        self.assertIn("Chutora dedup", out["hookSpecificOutput"]["updatedToolOutput"]["file"]["content"])

    def test_bad_input_is_silent(self):
        e = dict(os.environ, HOME=str(self.home))
        r = subprocess.run([sys.executable, str(DEDUP)], input="not json", capture_output=True, text=True, env=e, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")


MCPTRIM = ROOT / "plugins" / "chutora" / "hooks" / "mcptrim.py"
DEV = "mcp__remote-devices__device_bash"
DEV_OUT = "\n".join(f"-rw-r--r--  1 user staff {i * 113} Nov  9 10:00 report-{i}.txt" for i in range(30))


class DeviceDedupTest(DedupTest):
    # 繼承 DedupTest 只為了共用 setUp 與假 transcript 的輔助函式；下面把繼承來的 Read 測試關掉

    """Cowork 的 device_bash：同一只讀指令＋完全相同輸出 → 換成說明（經 mcptrim.py，先去重再瘦身）。"""

    for _n in [n for n in dir(DedupTest) if n.startswith("test_")]:
        locals()[_n] = None
    del _n

    def run_dev(self, tool_use_id, cmd="ls -l $HOME/mnt/proj", out=DEV_OUT, script=MCPTRIM, shape="list", env=None):
        resp = [{"type": "text", "text": out}] if shape == "list" else out
        data = {"hook_event_name": "PostToolUse", "tool_name": DEV, "tool_use_id": tool_use_id,
                "session_id": "sess1", "transcript_path": str(self.tp),
                "tool_input": {"command": cmd}, "tool_response": resp}
        e = dict(os.environ, HOME=str(self.home), CHUTORA_LANG="zh")
        for k in ("CHUTORA_DEDUP", "CHUTORA_TRIM", "CHUTORA_MCP_TRIM"):
            e.pop(k, None)
        e.update(env or {})
        r = subprocess.run([sys.executable, str(script)], input=json.dumps(data), capture_output=True, text=True, env=e, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def twice(self, cmd="ls -l $HOME/mnt/proj", out1=DEV_OUT, out2=DEV_OUT, **kw):
        self.add_read("d1")
        self.assertIsNone(self.run_dev("d1", cmd=cmd, out=out1, **kw))
        self.add_read("d2")
        return self.run_dev("d2", cmd=cmd, out=out2, **kw)

    def test_same_output_second_time_is_stub(self):
        out = self.twice()
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertEqual(new[0]["type"], "text")
        self.assertIn("Chutora 去重", new[0]["text"])
        self.assertRegex(new[0]["text"], r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
        self.assertLess(len(new[0]["text"]), len(DEV_OUT) / 2)

    def test_string_response_and_english_and_direct_script(self):
        out = self.twice(shape="str", script=DEDUP, env={"CHUTORA_LANG": "en"})
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertIsInstance(new, str)
        self.assertIn("Chutora dedup", new)

    def test_different_output_not_deduped(self):
        self.assertIsNone(self.twice(out2=DEV_OUT + "\nnew-file.txt"))

    def test_non_read_only_not_deduped(self):
        for cmd in ("sed -i s/a/b/ $HOME/mnt/proj/a.txt; ls -l", "npm install", "ls -l > out.txt", "find . -exec ls -l {} +"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.twice(cmd=cmd))

    def test_read_only_pipeline_is_deduped(self):
        self.assertIsNotNone(self.twice(cmd="cat $HOME/mnt/proj/a.log | grep -v x | head -50"))

    def test_after_compaction_not_deduped(self):
        self.add_read("d1")
        self.assertIsNone(self.run_dev("d1"))
        self.add_read("d2", parent="")
        self.entries[-2]["parentUuid"] = None
        self.flush()
        self.assertIsNone(self.run_dev("d2"))

    def test_too_short_not_deduped(self):
        self.assertIsNone(self.twice(out1="x" * 399, out2="x" * 399))

    def test_switch_off(self):
        self.assertIsNone(self.twice(env={"CHUTORA_DEDUP": "0"}))


if __name__ == "__main__":
    unittest.main()
