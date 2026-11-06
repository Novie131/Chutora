"""記憶身分資料工具（plugins/chutora/hooks/memmeta.py）的測試。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugins" / "chutora" / "hooks"
sys.path.insert(0, str(HOOKS))

import memmeta  # noqa: E402

AUTO_MEMORY = """---
name: user-prefers-pnpm
description: "The user wants pnpm, not npm: confirmed twice"
type: feedback
---

Use pnpm for installs.
"""


class MemMetaTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print(1)\n")

    def test_round_trip_all_fields(self):
        m = memmeta.new_meta(source="observed", bound_files=["src/app.py"], root=str(self.root), confidence=0.55)
        for k in memmeta.KEYS:
            self.assertIn(k, m)
        self.assertEqual(m["status"], "active")
        self.assertEqual(m["version"], 1)
        self.assertIsNone(m["supersedes"])
        self.assertEqual(m["bound_files"][0]["path"], "src/app.py")
        self.assertEqual(len(m["bound_files"][0]["sha"]), 12)
        text = memmeta.dump(m, "\nBody line: with colon\n")
        back, body = memmeta.parse(text)
        self.assertEqual(back, m)
        self.assertEqual(body, "\nBody line: with colon\n")

    def test_existing_front_matter_preserved(self):
        meta, body = memmeta.parse(AUTO_MEMORY)
        self.assertEqual(meta["name"], "user-prefers-pnpm")
        self.assertEqual(meta["description"], "The user wants pnpm, not npm: confirmed twice")
        self.assertFalse(memmeta.has_identity(meta))
        meta2, body2 = memmeta.parse(memmeta.dump(meta, body))
        self.assertEqual((meta2, body2), (meta, body))

    def test_unknown_nested_kept_verbatim(self):
        text = "---\nid: mem-1\nweird:\n  nested:\n    deep: 1\nversion: 2\n---\nbody\n"
        meta, body = memmeta.parse(text)
        self.assertEqual(meta["id"], "mem-1")
        self.assertIn("weird", meta["_raw"])
        self.assertIn("    deep: 1", memmeta.dump(meta, body))

    def test_no_front_matter(self):
        meta, body = memmeta.parse("just text\n")
        self.assertEqual((meta, body), ({}, "just text\n"))

    def test_check_bound_files(self):
        m = memmeta.new_meta(bound_files=["src/app.py", "missing.txt"], root=str(self.root))
        self.assertEqual([c[0] for c in memmeta.check(m, str(self.root))], [])  # missing.txt 指紋本來就是 None
        (self.root / "src" / "app.py").write_text("print(2)\n")
        self.assertEqual([c[0] for c in memmeta.check(m, str(self.root))], ["src/app.py"])

    def test_superseding_and_touched(self):
        old = memmeta.new_meta(source="user", confidence=0.9)
        new = memmeta.superseding(old)
        self.assertEqual(new["supersedes"], old["id"])
        self.assertEqual(new["version"], 2)
        self.assertEqual(new["confidence"], 0.9)
        t = memmeta.touched(old)
        self.assertIn("last_used", t)
        self.assertEqual(t["id"], old["id"])

    def test_validation(self):
        with self.assertRaises(ValueError):
            memmeta.new_meta(source="random")
        with self.assertRaises(ValueError):
            memmeta.new_meta(confidence=2)

    def test_write_new_never_overwrites(self):
        p = self.root / "claude-memory" / "pref.md"
        memmeta.write_new(str(p), "Use pnpm.\n", memmeta.new_meta())
        before = p.read_text()
        with self.assertRaises(FileExistsError):
            memmeta.write_new(str(p), "other", memmeta.new_meta())
        self.assertEqual(p.read_text(), before)
        meta, body = memmeta.read_file(str(p))
        self.assertTrue(memmeta.has_identity(meta))
        self.assertEqual(body.strip(), "Use pnpm.")

    def test_cli(self):
        p = self.root / "m.md"
        cli = [sys.executable, str(HOOKS / "memmeta.py")]
        r = subprocess.run(cli + ["new", str(p), "--source", "research", "--bind", "src/app.py", "--root", str(self.root)],
                           input="Body\n", capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("mem-"))
        r = subprocess.run(cli + ["new", str(p)], input="x", capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        r = subprocess.run(cli + ["show", str(p)], capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(r.stdout)["source"], "research")
        r = subprocess.run(cli + ["check", str(p), "--root", str(self.root)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
