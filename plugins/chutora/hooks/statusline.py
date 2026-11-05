#!/usr/bin/env python3
"""statusLine 指令：顯示 context 大小、提醒門檻與自動壓縮點。

輸出：{model} │ ctx 95k │ 提醒 100k │ 壓縮 120k（8 萬以下綠、門檻以下黃、以上紅）。
用 total_input_tokens（缺時加總 current_usage），不用 used_percentage：
它以完整視窗計算，1M 模型在 10 萬 token 只會顯示 12%。
壓縮點來自 settings.json 的 autoCompactWindow（見 compact.py）；沒設定就不顯示「壓縮」。
提醒門檻讀環境變數 CONTEXT_REMIND_TOKENS（預設見 compact.py 的 DEFAULT_REMIND，與 context-check.py 一致）。
壞輸入安靜結束。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact import compact_point, remind_tokens

REMIND = remind_tokens()
GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"


def main():
    try:
        data = json.load(sys.stdin)
        cw = data.get("context_window") or {}
        n = cw.get("total_input_tokens")
        if n is None:
            u = cw.get("current_usage") or {}
            n = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        color = GREEN if n < 80000 else YELLOW if n < REMIND else RED
        model = (data.get("model") or {}).get("display_name", "")
        parts = [model, f"{color}ctx {n // 1000}k{RESET}", f"提醒 {REMIND // 1000}k"]
        compact = compact_point()
        if compact is not None:
            parts.append(f"壓縮 {compact // 1000}k")
    except Exception:
        return
    print(" │ ".join(parts))


if __name__ == "__main__":
    main()
