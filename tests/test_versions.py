import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "chutora" / ".claude-plugin" / "plugin.json"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class VersionTest(unittest.TestCase):
    def test_json_parse(self):
        self.assertIsInstance(load(MARKETPLACE), dict)
        self.assertIsInstance(load(PLUGIN), dict)

    def test_versions_match(self):
        market = load(MARKETPLACE)["plugins"][0]["version"]
        plugin = load(PLUGIN)["version"]
        self.assertEqual(market, plugin)


if __name__ == "__main__":
    unittest.main()
