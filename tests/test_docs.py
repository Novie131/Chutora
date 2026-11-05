"""README 與 docs/ 的相對連結、圖示與 <a name> 錨點都要存在；中英兩版的固定錨點要一致。"""
import re
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [ROOT / "README.md", ROOT / "README.en.md"] + sorted((ROOT / "docs").glob("*.md"))


def anchors(p):
    t = p.read_text(encoding="utf-8")
    a = set(re.findall(r'<a name="([^"]+)">', t))
    for h in re.findall(r"(?m)^#+ (.+)$", t):
        h = re.sub(r"<[^>]+>", "", h).strip().lower()
        a.add(re.sub(r"\s", "-", re.sub(r"[^\w\- ]", "", h)))
    return a


class DocsTest(unittest.TestCase):
    def test_relative_links_resolve(self):
        bad = []
        for f in FILES:
            t = f.read_text(encoding="utf-8")
            for u in re.findall(r"\]\(([^)\s]+)\)", t) + re.findall(r'(?:src|href)="([^"]+)"', t):
                if re.match(r"(https?:|mailto:)", u):
                    continue
                path, _, frag = u.partition("#")
                tgt = (f.parent / urllib.parse.unquote(path)) if path else f
                if not tgt.exists():
                    bad.append(f"{f.name}: {u}")
                elif frag and tgt.suffix == ".md" and frag not in anchors(tgt):
                    bad.append(f"{f.name}: #{frag}")
        self.assertEqual(bad, [])

    def test_zh_en_share_anchors(self):
        for zh, en in (("README.md", "README.en.md"), ("docs/advanced.md", "docs/advanced.en.md")):
            a = re.findall(r'<a name="([^"]+)">', (ROOT / zh).read_text(encoding="utf-8"))
            b = re.findall(r'<a name="([^"]+)">', (ROOT / en).read_text(encoding="utf-8"))
            self.assertEqual(a, b, zh)

    def test_no_emoji_icons_in_headings(self):
        for f in FILES:
            for h in re.findall(r"(?m)^#+ (.+)$", f.read_text(encoding="utf-8")):
                self.assertIsNone(re.search(r"[\U0001F300-\U0001FAFF]", h), f"{f.name}: {h}")


if __name__ == "__main__":
    unittest.main()
