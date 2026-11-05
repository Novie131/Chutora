#!/usr/bin/env python3
"""駕駛艙穩定版的資料來源：PreToolUse／PostToolUse／PostToolUseFailure／SubagentStart／SubagentStop hook。

把「誰正在做什麼」寫進 ~/.claude/chutora/activity/<session_id>.json，狀態列（statusline.py）讀它顯示：
▶ worker·Sonnet 跑測試 npm test · 12s │ 本次 42k tok │ 瘦身省≈8k │ ctx 95k/120k
只記錄、不輸出任何東西、不改工具行為；任何錯誤都安靜結束。CHUTORA_ACTIVITY=0 關閉。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if os.environ.get("CHUTORA_ACTIVITY", "").strip() == "0":
        return
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return
        import deck
        deck.on_event(data)
    except Exception:
        return


if __name__ == "__main__":
    main()
