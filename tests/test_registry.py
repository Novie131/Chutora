"""hooks.json（plugin 安裝）與 install.sh 印出的 hooks 片段（複製安裝）要登記同一組 hook。"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_JSON = ROOT / "plugins" / "chutora" / "hooks" / "hooks.json"
INSTALL = ROOT / "install.sh"


def plugin_pairs():
    d = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    out = set()
    for ev, groups in d.items():
        for g in groups:
            for h in g["hooks"]:
                m = re.findall(r"hooks/([\w.-]+\.(?:py|sh))", h["command"])
                out.add((ev, g.get("matcher", ""), m[-1]))
    return out


def snippet_pairs():
    text = INSTALL.read_text(encoding="utf-8")
    body = text[text.index("print_hook_snippet() {"):]
    body = body[body.index("<<'MSG'"):body.index("\nMSG\n")]
    j = "{" + body[body.index('"SessionStart"'):] + "}"
    d = json.loads(j)
    out = set()
    for ev, groups in d.items():
        for g in groups:
            for h in g["hooks"]:
                m = re.findall(r"chutora/([\w.-]+\.(?:py|sh))", h["command"])
                out.add((ev, g.get("matcher", ""), m[-1]))
    return out


class RegistryTest(unittest.TestCase):
    def test_install_snippet_matches_hooks_json(self):
        self.assertEqual(snippet_pairs(), plugin_pairs())

    def test_new_hooks_registered(self):
        pairs = plugin_pairs()
        self.assertIn(("PreToolUse", "Bash|Write|Edit|MultiEdit|NotebookEdit|Read", "guard.py"), pairs)
        for ev in ("PostToolUse", "PostToolUseFailure", "SubagentStop", "UserPromptSubmit"):
            self.assertIn((ev, "", "observe.py"), pairs)


if __name__ == "__main__":
    unittest.main()
