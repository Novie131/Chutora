"""MCP 輸出瘦身 hook（plugins/chutora/hooks/mcptrim.py）的測試。一律用暫存 HOME。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "plugins" / "chutora" / "hooks" / "mcptrim.py"


def slack_json(n=200):
    msgs = [{"ts": f"17000000{i}.000", "user": f"U{i % 7}", "text": f"message number {i} about the release plan",
             "reactions": [], "thread_ts": None, "attachments": {}} for i in range(n)]
    return json.dumps({"ok": True, "messages": msgs, "has_more": False})


class McpTrimTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.conf = self.home / ".claude" / "chutora"

    def run_hook(self, resp, tool="mcp__slack__read_channel", env=None, tool_use_id="toolu_m1"):
        data = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_use_id": tool_use_id,
                "tool_input": {"channel": "C1"}, "tool_response": resp}
        e = dict(os.environ, HOME=str(self.home), CHUTORA_LANG="zh")
        for k in ("CHUTORA_MCP_TRIM", "CHUTORA_MCP_TRIM_EXCLUDE", "CHUTORA_MCP_TRIM_TEXT", "CHUTORA_MODE"):
            e.pop(k, None)
        e.update(env or {})
        r = subprocess.run([sys.executable, str(MCP)], input=json.dumps(data), capture_output=True, text=True, env=e, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_content_blocks_json_trimmed(self):
        raw = slack_json()
        out = self.run_hook([{"type": "text", "text": raw}])
        self.assertIsNotNone(out)
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertIsInstance(new, list)
        body = json.loads(new[0]["text"])
        self.assertEqual(len(body["messages"]), 31)  # 平衡：保留 30 筆＋「另有 N 筆」
        self.assertIn("另有 170 筆", body["messages"][-1])
        self.assertNotIn("reactions", body["messages"][0])  # 空欄位拿掉
        self.assertIn("Chutora MCP 瘦身", new[-1]["text"])
        raw_files = list((self.conf / "raw").glob("*.log"))
        self.assertEqual(len(raw_files), 1)
        self.assertIn("message number 199", raw_files[0].read_text())
        st = json.loads((self.conf / "trim-stats.json").read_text())
        self.assertGreater(st["kinds"]["mcp"], 1000)

    def test_long_json_strings_kept_by_default(self):
        big = json.dumps({"page": "x" * 9000})
        self.assertIsNone(self.run_hook(big))

    def test_string_response_and_long_strings_opt_in(self):
        big = json.dumps({"page": "x" * 9000})
        out = self.run_hook(big, env={"CHUTORA_MCP_TRIM_TEXT": "1"})
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertIsInstance(new, str)
        self.assertIn("截斷", new)
        self.assertLess(len(new), len(big))

    def test_dict_with_content(self):
        out = self.run_hook({"content": [{"type": "text", "text": slack_json()}], "isError": False})
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertIn("content", new)
        self.assertFalse(new["isError"])

    def test_plain_text_untouched_by_default(self):
        text = "\n".join(f"row {i}: Downloading chunk {i} 45%" for i in range(600)) + "\nERROR: quota exceeded\nDone."
        self.assertIsNone(self.run_hook([{"type": "text", "text": text}]))
        self.assertIsNone(self.run_hook(text))

    def test_long_guide_text_untouched(self):
        """實際發生過：Claude Docs connector 的 guide 說明被砍掉 204 行。長篇說明文字一律不動。"""
        doc = "# Docs guide\n\n" + "\n".join(
            f"- Step {i}: call `batch` with a pending block, then replace it with the section body ({i})." for i in range(300))
        for resp in ([{"type": "text", "text": doc}], doc, {"content": [{"type": "text", "text": doc}]}):
            self.assertIsNone(self.run_hook(resp, tool="mcp__Claude_Docs__guide"))
        # 包在 JSON 字串裡的長篇 Markdown 也不截斷
        self.assertIsNone(self.run_hook([{"type": "text", "text": json.dumps({"topic": "index", "text": doc})}],
                                        tool="mcp__Claude_Docs__guide"))
        self.assertFalse((self.conf / "raw").exists())

    def test_long_json_array_still_trimmed_next_to_text(self):
        doc = "\n".join(f"line {i} of the manual" for i in range(400))
        out = self.run_hook([{"type": "text", "text": doc}, {"type": "text", "text": slack_json()}])
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertEqual(new[0]["text"], doc)
        self.assertIn("另有 170 筆", json.loads(new[1]["text"])["messages"][-1])

    def test_plain_text_lines_opt_in(self):
        text = "\n".join(f"row {i}: Downloading chunk {i} 45%" for i in range(600)) + "\nERROR: quota exceeded\nDone."
        out = self.run_hook([{"type": "text", "text": text}], env={"CHUTORA_MCP_TRIM_TEXT": "1"})
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertIn("ERROR: quota exceeded", new[0]["text"])
        self.assertIn("略過", new[0]["text"])

    def test_images_kept(self):
        img = {"type": "image", "data": "AAAA", "mimeType": "image/png"}
        out = self.run_hook([img, {"type": "text", "text": slack_json()}])
        new = out["hookSpecificOutput"]["updatedMCPToolOutput"]
        self.assertEqual(new[0], img)

    def test_small_untouched(self):
        self.assertIsNone(self.run_hook([{"type": "text", "text": json.dumps({"ok": True})}]))

    def test_non_mcp_tool_ignored(self):
        self.assertIsNone(self.run_hook([{"type": "text", "text": slack_json()}], tool="Bash"))

    def test_exclude_and_switches(self):
        self.assertIsNone(self.run_hook([{"type": "text", "text": slack_json()}], env={"CHUTORA_MCP_TRIM_EXCLUDE": "mcp__slack__"}))
        self.assertIsNone(self.run_hook([{"type": "text", "text": slack_json()}], env={"CHUTORA_MCP_TRIM": "0"}))
        self.conf.mkdir(parents=True, exist_ok=True)
        (self.conf / "mcp-trim").write_text("off\n")
        self.assertIsNone(self.run_hook([{"type": "text", "text": slack_json()}]))

    def test_exclude_by_server_name(self):
        self.assertIsNone(self.run_hook([{"type": "text", "text": slack_json()}], env={"CHUTORA_MCP_TRIM_EXCLUDE": "slack"}))
        self.assertIsNotNone(self.run_hook([{"type": "text", "text": slack_json()}], env={"CHUTORA_MCP_TRIM_EXCLUDE": "slackbot"}))
        self.conf.mkdir(parents=True, exist_ok=True)
        (self.conf / "mcp-trim-exclude").write_text("slack\n")
        self.assertIsNone(self.run_hook([{"type": "text", "text": slack_json()}]))

    def test_exclude_file(self):
        self.conf.mkdir(parents=True, exist_ok=True)
        (self.conf / "mcp-trim-exclude").write_text("# comment\nmcp__slack__read_channel\n")
        self.assertIsNone(self.run_hook([{"type": "text", "text": slack_json()}]))

    def test_modes_change_limits(self):
        out = self.run_hook([{"type": "text", "text": slack_json()}], env={"CHUTORA_MODE": "quality"})
        body = json.loads(out["hookSpecificOutput"]["updatedMCPToolOutput"][0]["text"])
        self.assertEqual(len(body["messages"]), 61)
        out = self.run_hook([{"type": "text", "text": slack_json()}], env={"CHUTORA_MODE": "economy"})
        body = json.loads(out["hookSpecificOutput"]["updatedMCPToolOutput"][0]["text"])
        self.assertEqual(len(body["messages"]), 21)

    def test_repeated_items_merged(self):
        rows = [{"status": "ok", "region": "us-east-1"}] * 300
        out = self.run_hook([{"type": "text", "text": json.dumps(rows)}])
        body = json.loads(out["hookSpecificOutput"]["updatedMCPToolOutput"][0]["text"])
        self.assertEqual(len(body), 2)
        self.assertIn("×299", body[1])


if __name__ == "__main__":
    unittest.main()
