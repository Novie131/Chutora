"""固定開銷預算：guide、modes、skills／agents description 不准再長回去（用 usage.est_tokens 量）。"""
import glob
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "plugins" / "chutora"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))
import usage  # noqa: E402

GUIDE_MAX = 350
MODE_MAX = 120
DESCRIPTORS_MAX = 450


class OverheadBudgetTest(unittest.TestCase):
    def test_guides_within_budget(self):
        for name in ("guide.md", "guide.en.md"):
            n = usage.est_tokens((HOOKS / name).read_text(encoding="utf-8"))
            self.assertLessEqual(n, GUIDE_MAX, "%s 估算 %d tokens，上限 %d" % (name, n, GUIDE_MAX))

    def test_modes_within_budget(self):
        files = sorted((HOOKS / "modes").glob("*.md"))
        self.assertEqual(len(files), 6)
        for p in files:
            n = usage.est_tokens(p.read_text(encoding="utf-8"))
            self.assertLessEqual(n, MODE_MAX, "%s 估算 %d tokens，上限 %d" % (p.name, n, MODE_MAX))

    def test_descriptors_within_budget(self):
        text = "".join(usage._frontmatter_text(p) for p in
                       glob.glob(str(ROOT / "skills" / "*" / "SKILL.md")) + glob.glob(str(ROOT / "agents" / "*.md")))
        n = usage.est_tokens(text)
        self.assertGreater(n, 100)  # 確認真的有量到
        self.assertLessEqual(n, DESCRIPTORS_MAX, "skills＋agents description 估算 %d tokens，上限 %d" % (n, DESCRIPTORS_MAX))

    def test_trigger_keywords_kept(self):
        def desc(rel):
            return usage._frontmatter_text(str(ROOT / rel))
        hub = desc("skills/chutora-hub/SKILL.md")
        for k in ("/chutora", "狀態", "doctor", "模式", "語言"):
            self.assertIn(k, hub)
        self.assertIn("明確要求", desc("agents/harvester.md"))
        self.assertIn("worker 失敗後", desc("agents/worker-hard.md"))

    def test_guide_keeps_core_rules(self):
        for name, keys in (("guide.md", ("worker", "bulk", "librarian", "狀態：", "驗證：", "worker-hard", "AskUserQuestion", "briefs/", "看不到對話", "隔離")),
                           ("guide.en.md", ("worker", "bulk", "librarian", "狀態：", "驗證：", "worker-hard", "AskUserQuestion", "briefs/", "can't see", "isolated"))):
            t = (HOOKS / name).read_text(encoding="utf-8")
            for k in keys:
                self.assertIn(k, t, (name, k))


if __name__ == "__main__":
    unittest.main()
