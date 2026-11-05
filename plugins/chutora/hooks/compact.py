"""自動壓縮點的共用小模組（statusline.py 與 context-check.py 共用）。

Claude Code 的 settings.json 鍵 autoCompactWindow 是「壓縮視窗」，
實際壓縮點約為 autoCompactWindow 扣掉 /context 顯示的 Autocompact buffer。
buffer 預設 33000（本機實測值，用 /context 確認），可用環境變數 CONTEXT_AUTOCOMPACT_BUFFER 覆寫。
"""
import json, os

DEFAULT_BUFFER = 33000
DEFAULT_REMIND = 100000  # 提醒門檻預設值的唯一來源（usage_stats.py 在別的目錄，另寫一份 100000）


def remind_tokens():
    """提醒門檻（tokens）：環境變數 CONTEXT_REMIND_TOKENS，沒設或不是整數就用 DEFAULT_REMIND。"""
    try:
        return int(os.environ.get("CONTEXT_REMIND_TOKENS", DEFAULT_REMIND))
    except ValueError:
        return DEFAULT_REMIND


def compact_point():
    """回傳預估的自動壓縮點（tokens）；沒設定、讀不到、JSON 壞掉都回傳 None，不丟例外。"""
    try:
        with open(os.path.expanduser("~/.claude/settings.json")) as f:
            window = json.load(f).get("autoCompactWindow")
        if isinstance(window, bool) or not isinstance(window, int):
            return None
        buffer = int(os.environ.get("CONTEXT_AUTOCOMPACT_BUFFER", DEFAULT_BUFFER))
        return window - buffer
    except Exception:
        return None
