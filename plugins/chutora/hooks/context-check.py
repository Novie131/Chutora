#!/usr/bin/env python3
"""UserPromptSubmit hook：對話 context 超過門檻時，讓 Claude 提醒使用者清空或壓縮對話。

只在跨過門檻、或之後每多 STEP 個 token 時提醒一次，避免每輪都提醒。
門檻可用環境變數 CONTEXT_REMIND_TOKENS 覆寫（測試時可設低一點）。

「上次檢查時在哪一格」記在狀態檔，而不是拿最後兩次 API 呼叫比較：
一個回合內常有多次工具呼叫，跨門檻多半發生在回合中間，
等到下一則訊息時最後兩次都已超過門檻，就永遠不會提醒。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from compact import compact_point, remind_tokens
    THRESHOLD = remind_tokens()
except Exception:  # compact.py 缺檔也不擋提醒
    compact_point = lambda: None  # noqa: E731
try:
    from compact import lang
except Exception:
    lang = lambda: "en"  # noqa: E731
    THRESHOLD = int(os.environ.get("CONTEXT_REMIND_TOKENS") or 100000)
STEP = 40000
KEEP = 50  # 狀態檔只留最近這麼多個對話
STATE_PATH = os.path.join(
    # 不用 plugin 安裝時（symlink）沒有 CLAUDE_PLUGIN_DATA；不能放腳本旁邊，那會寫進 repo
    os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/hooks"),
    ".context-check-state.json",
)


def context_sizes(path):
    """依序回傳主對話中每次 API 呼叫的 context 大小（同一則訊息只算一次）。"""
    sizes, seen = [], set()
    with open(path, errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message")
            if d.get("type") != "assistant" or d.get("isSidechain") or not isinstance(m, dict):
                continue
            u = m.get("usage")
            if not u or m.get("id") in seen:
                continue
            seen.add(m.get("id"))
            sizes.append(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                         + u.get("cache_read_input_tokens", 0))
    return sizes


def bucket(n):
    return -1 if n < THRESHOLD else (n - THRESHOLD) // STEP


def remember(path, now_bucket):
    """記下這個對話目前在哪一格，回傳上次記的那一格（沒記過當作 -1）。"""
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    prev = state.pop(path, -1)
    state[path] = now_bucket  # 重新放到最後，越後面越新
    for old in list(state)[:-KEEP]:
        del state[old]
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)
    return prev


def reminder(now):
    try:
        point = compact_point()
    except Exception:
        point = None
    if lang() == "en":
        head = (f"The conversation context is now about {now // 1000}k tokens, past the "
                f"{THRESHOLD // 1000}k reminder threshold. ")
        if point is not None:
            return (
                head + "Use chutora's handoff skill to update the handoff note first, then end your reply "
                f"with one sentence to the user: \"Handoff note updated; auto-compact kicks in around {point // 1000}k "
                "and the note is restored automatically afterwards, so nothing to do by hand. If this task is "
                "wrapped up, a new conversation or /clear is cheaper.\" No need to suggest /compact or /rewind."
            )
        return (
            head + "This is when chutora's handoff skill applies: update the handoff note first (whether or not "
            "the user will /clear), then end your reply with one copy-paste command that fits the situation: "
            "task wrapped up → /clear; halfway through → /compact keep <write the decisions and progress to keep>; "
            "the latter half is mostly debugging or exploration noise → /rewind and pick <the message to start "
            "from>, then Summarize from here. Also mention that otherwise auto-compact will kick in near the "
            "context limit, at a time and with a focus nobody chose."
        )
    head = f"目前對話的 context 約為 {now // 1000}k tokens，已超過 {THRESHOLD // 1000}k 的提醒門檻。"
    if point is not None:
        return (
            head + "請依 chutora 的 handoff skill 先更新交接筆記，"
            f"然後在回答結尾用一句話告訴使用者：「交接筆記已更新；約 {point // 1000}k 會自動壓縮，"
            "壓縮後會自動帶回交接筆記，不需要手動處理。這件事若已告一段落，換新對話或 /clear 更省」。"
            "不需要再給 /compact 或 /rewind 指令。"
        )
    return (
        head + "chutora 的 handoff skill 用於此時：先更新交接筆記"
        "（不論使用者是否 /clear），再依當下情況，在回答結尾給使用者一句可直接複製的指令："
        "事情已告一段落 → /clear；做到一半 → /compact 保留<替使用者寫好要保留的決定與進度>；"
        "後半段多是除錯或探索雜訊 → /rewind 選<指出從哪一則訊息開始>，再按 Summarize from here。"
        "並說明不處理的話，接近 context 上限時會自動壓縮，時機和重點都不是自己選的。"
    )


def main():
    try:
        data = json.load(sys.stdin)
        try:  # 順便偵測使用者的語言（純本地、不輸出）
            from compact import note_prompt_lang
            note_prompt_lang(data.get("prompt"))
        except Exception:
            pass
        path = data.get("transcript_path")
        sizes = context_sizes(path) if path else []
        if not sizes:
            return
        now = sizes[-1]
        # 壓縮後 context 變小，格子跟著往回記，之後再跨過門檻會再提醒
        prev = remember(path, bucket(now))
    except Exception:
        return  # 任何錯誤都不擋使用者的訊息
    if bucket(now) < 0 or bucket(now) <= prev:
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": reminder(now),
    }}, ensure_ascii=False))


if __name__ == "__main__":
    main()
