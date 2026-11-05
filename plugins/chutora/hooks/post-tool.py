#!/usr/bin/env python3
"""PostToolUse hook：做兩件事，任何錯誤都安靜結束，絕不中斷工作。

1) failure-loop intervention（loop guard）：同一個錯誤在這個 session 重複出現到門檻，
   就在 context 注入一句導正，提醒換個方向——只提醒，永遠不中斷、不幫使用者停。
2) 工具用量記錄：記下每個工具被用過（給 toolprune 判斷哪些工具長期沒用到）。

設計取自 microsoft/TokenEconomizer：只透過 agent 本來就會讀的 context 作用、
保護任務成功（只在真的卡住才介入）、每個動作可逆（純提醒）。
"""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from compact import lang
except Exception:
    lang = lambda: "zh"  # noqa: E731

THRESHOLD = int(os.environ.get("LOOP_GUARD_REPEAT") or 3)   # 同一錯誤重複幾次才提醒
SESS_CAP = 200          # 用量記錄最多留幾個 session id
LG_SESS_CAP = 40        # loop guard 狀態最多留幾個 session
SIG_CAP = 60            # 每個 session 最多追蹤幾種錯誤簽章

STATE_DIR = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/hooks")
USAGE_PATH = os.path.join(STATE_DIR, ".tool-usage.json")
LOOP_PATH = os.path.join(STATE_DIR, ".loop-guard-state.json")

ERROR_MARKERS = (
    "error", "exception", "traceback", "failed", "failure", "cannot",
    "not found", "no such file", "permission denied", "command not found",
    "fatal:", "refused", "timed out", "timeout", "undefined", "unresolved",
    "錯誤", "失敗", "找不到", "無法",
)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def response_text(resp):
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        parts = []
        for k in ("stderr", "error", "message", "content", "returnDisplay", "stdout"):
            v = resp.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        if parts:
            return "\n".join(parts)
    try:
        return json.dumps(resp, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(resp)


def looks_like_error(resp, text):
    if isinstance(resp, dict):
        if resp.get("is_error") or resp.get("isError") or resp.get("error"):
            return True
        code = resp.get("exit_code", resp.get("returncode"))
        if isinstance(code, int) and code != 0:
            return True
    low = text.lower()
    return any(m in low for m in ERROR_MARKERS)


def signature(tool_name, text):
    """取第一行含錯誤關鍵字的內容，正規化成穩定簽章（去數字、路徑、空白）。"""
    line = ""
    for raw in text.splitlines():
        low = raw.lower()
        if any(m in low for m in ERROR_MARKERS):
            line = raw.strip()
            break
    if not line:
        line = text.strip().splitlines()[0] if text.strip() else ""
    line = re.sub(r"0x[0-9a-fA-F]+|\d+", "#", line)      # 數字、位址 → #
    line = re.sub(r"[/\\][^\s]*", "/…", line)            # 路徑 → /…
    line = re.sub(r"\s+", " ", line).strip().lower()[:100]
    return (tool_name or "") + "::" + line


def record_usage(tool_name, session_id):
    st = load(USAGE_PATH)
    tools = st.setdefault("tools", {})
    sessions = st.setdefault("sessions", [])
    today = date.today().isoformat()
    if session_id and session_id not in sessions:
        sessions.append(session_id)
        del sessions[:-SESS_CAP]
    t = tools.setdefault(tool_name, {"count": 0, "sessions": 0, "last": today})
    t["count"] = t.get("count", 0) + 1
    t["last"] = today
    t["last_session"] = session_id
    # 以不同 session 數粗估「用過幾次 session」
    seen = t.setdefault("seen_sessions", [])
    if session_id and session_id not in seen:
        seen.append(session_id)
        del seen[:-20]
    t["sessions"] = len(seen)
    save(USAGE_PATH, st)


def check_loop(tool_name, resp, text, session_id):
    if not looks_like_error(resp, text):
        return None
    sig = signature(tool_name, text)
    st = load(LOOP_PATH)
    order = st.setdefault("_order", [])
    sess = st.setdefault(session_id or "_none", {"sigs": {}, "nudged": {}})
    if session_id and session_id in order:
        order.remove(session_id)
    order.append(session_id or "_none")
    for old in order[:-LG_SESS_CAP]:
        st.pop(old, None)
    st["_order"] = order[-LG_SESS_CAP:]

    sigs = sess.setdefault("sigs", {})
    nudged = sess.setdefault("nudged", {})
    sigs[sig] = sigs.get(sig, 0) + 1
    if len(sigs) > SIG_CAP:
        # 丟掉次數最少的，保留反覆出現的
        for k in sorted(sigs, key=sigs.get)[: len(sigs) - SIG_CAP]:
            sigs.pop(k, None)
            nudged.pop(k, None)
    count = sigs[sig]
    level = nudged.get(sig, 0)
    msg = None
    en = lang() == "en"
    if count >= THRESHOLD * 2 and level < 2:
        nudged[sig] = 2
        msg = (
            f"The same error has now appeared {count} times and the earlier nudge didn't break the loop. "
            "Strongly consider stopping the retries: step back and re-understand the problem, switch to a "
            "completely different approach, or report the situation and what has been tried to the user and "
            "let them decide. Don't retry in a similar way again."
        ) if en else (
            f"同一個錯誤已經出現 {count} 次，之前的提醒後仍在原地打轉。"
            "強烈建議停止重試：退回去重新理解問題、換一條完全不同的路，"
            "或把目前情況、已試過的做法回報給使用者讓他決定。不要再用類似方式重試。"
        )
    elif count >= THRESHOLD and level < 1:
        nudged[sig] = 1
        snippet = sig.split("::", 1)[-1][:80]
        msg = (
            f"The same error has repeated {count} times ({snippet}). This usually means being stuck on one path. "
            "Change direction: step back and re-understand the problem, try a different approach, or report "
            "to the user, instead of retrying the same way."
        ) if en else (
            f"偵測到同一個錯誤重複出現 {count} 次（{snippet}）。"
            "這通常代表卡在同一條路上。建議換個方向：退一步重新理解問題、"
            "換一種做法，或把情況回報給使用者，而不是再用同樣方式重試。"
        )
    save(LOOP_PATH, st)
    return msg


def main():
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    tool_name = data.get("tool_name") or data.get("toolName") or ""
    session_id = data.get("session_id") or data.get("sessionId") or ""
    resp = data.get("tool_response", data.get("toolResponse"))
    if not tool_name:
        return
    text = response_text(resp)

    try:
        record_usage(tool_name, session_id)
    except Exception:
        pass

    try:
        msg = check_loop(tool_name, resp, text, session_id)
    except Exception:
        msg = None

    if msg:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }}, ensure_ascii=False))


if __name__ == "__main__":
    main()
