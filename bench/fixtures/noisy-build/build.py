"""假的建置腳本：會印出大量進度與日誌，最後因設定錯誤失敗。"""
import json
import sys

for i in range(1, 1201):
    print(f"[build] compiling module_{i:04d}.c ... ok ({i % 97} ms)")
    if i % 100 == 0:
        print(f"[build] progress {i // 12}% |{'#' * (i // 60)}{'.' * (20 - i // 60)}|")

with open("build.json") as f:
    cfg = json.load(f)

if cfg.get("target") not in ("debug", "release"):
    print(f"error: unknown build target {cfg.get('target')!r} in build.json (expected 'debug' or 'release')",
          file=sys.stderr)
    sys.exit(1)
print("[build] done: 1200 modules, target=" + cfg["target"])
