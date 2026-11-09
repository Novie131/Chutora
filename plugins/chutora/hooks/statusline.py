#!/usr/bin/env python3
"""statusLine 指令：駕駛艙穩定版。只用官方 statusline 與標準 hooks，不依賴 mod API。

工作中：▶ worker·Sonnet 跑測試 npm test · 12s │ 5h 42%(2h13m) │ 週 18%(週四14:00) │ ctx 95k/120k │ 上輪 12.3k │ 淨省≈+3k │ 本次 42k tok
閒置時：Opus │ 5h 42%(2h13m) │ 週 18%(週四14:00) │ ctx 95k │ 上輪 12.3k │ 淨省≈+3k │ 本次 42k tok │ 提醒 100k │ 壓縮 120k

- 目前動作來自 activity.py 寫的 ~/.claude/chutora/activity/<session_id>.json；沒有就只顯示閒置版。
- 本次 token：transcript 的 usage 精確加總（input＋cache 寫入＋output，不含 cache 讀取），主對話＋子 agent。
- 待確認：決策引擎自動做了、使用者還沒回應的動作數（/chutora changes）。
- 額度：stdin 的 rate_limits（5 小時、每週；只在有讀數時出現，沒有就略過該欄）；超過 80% 黃、超過 95% 紅。
- 上輪：最後一則真正提示之後的 token（input＋cache 寫入＋output，不含 cache 讀取）。
- 淨省：瘦身省下的字元數 ÷4，扣掉外掛固定開銷（SessionStart 注入＋skills／agents 描述）÷4，標「≈」；負值照實顯示（淡色）。
- 提醒 100k 只在 context 提醒開啟時顯示（CHUTORA_CONTEXT_REMIND=1 或 ~/.claude/chutora/remind 為 on）。
- 每次執行把額度與 claude 區塊寫入 ~/.claude/chutora/usage.json（同內容 5 秒內不重寫）。
- 重要性（寬度不夠時後面的先丟）：額度 > ctx > 上輪 > 淨省 > 其他。
- ctx 用 total_input_tokens（缺時加總 current_usage），不用 used_percentage；8 萬以下綠、提醒門檻以下黃、以上紅。
- 寬度：CHUTORA_STATUS_WIDTH 或 COLUMNS（預設 120）；放不下時依重要性丟掉後面的欄位，再截短動作描述。
壞輸入安靜結束。
"""
import json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact import compact_point, remind_tokens
try:
    from compact import remind_enabled
except ImportError:  # 舊版 compact.py
    remind_enabled = lambda: False  # noqa: E731
try:
    from compact import lang
except ImportError:  # 舊版 compact.py
    lang = lambda: "en"  # noqa: E731
try:
    import deck
except Exception:  # 狀態列資料夾裡沒有 deck.py（舊版同步）時，只顯示閒置版
    deck = None

try:
    import usage
except Exception:  # 狀態列資料夾裡沒有 usage.py（舊版同步）時，不顯示額度／上輪／淨省
    usage = None

REMIND = remind_tokens()
GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"
ORANGE, DIM = "\033[38;5;208m", "\033[2m"
MODEL_COLOR = {"Opus": "\033[38;5;208m", "Sonnet": "\033[38;5;141m", "Haiku": "\033[38;5;80m"}
ANSI = re.compile(r"\033\[[0-9;]*m")
STALE = 30 * 60


def width(s):
    w = 0
    for ch in ANSI.sub("", s):
        c = ord(ch)
        w += 2 if (0x1100 <= c <= 0x115F or 0x2E80 <= c <= 0xA4CF or 0xAC00 <= c <= 0xD7A3 or
                   0xF900 <= c <= 0xFAFF or 0xFE30 <= c <= 0xFE6F or 0xFF00 <= c <= 0xFF60 or 0xFFE0 <= c <= 0xFFE6) else 1
    return w


def cut(s, n):
    out, w = "", 0
    for ch in s:
        cw = width(ch)
        if w + cw > n - 1:
            return out + "…"
        out += ch
        w += cw
    return out


def ktok(n):
    if n < 1000:
        return str(int(n))
    return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k" if n < 10000 else f"{n // 1000}k"


def ktok1(n):
    """一位小數的 k（12300 → 12.3k；整數就不帶小數；100k 以上取整）。"""
    if n < 1000:
        return str(int(n))
    return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k" if n < 100000 else f"{n // 1000}k"


def elapsed(sec):
    s = max(0, int(sec))
    return f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s" if s < 3600 else f"{s // 3600}h{s % 3600 // 60:02d}m"


def limit():
    for k in ("CHUTORA_STATUS_WIDTH", "COLUMNS"):
        try:
            v = int(os.environ.get(k, ""))
            if v > 20:
                return v
        except ValueError:
            pass
    return 120


def fit(parts, keep_first, max_w):
    """parts: [(priority, text)]，priority 越大越先丟。保留第一段，必要時截短。"""
    parts = list(parts)
    join = lambda ps: " │ ".join(t for _, t in ps)  # noqa: E731
    while width(join(parts)) > max_w and len(parts) > 1:
        drop = max(range(1 if keep_first else 0, len(parts)), key=lambda i: (parts[i][0], i))
        if parts[drop][0] <= 0:
            break
        parts.pop(drop)
    line = join(parts)
    if width(line) > max_w:
        line = cut(ANSI.sub("", line), max_w)
    return line


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
        lng = lang()
        zh = lng == "zh"
        compact = compact_point()
    except Exception:
        return

    # 優先序（數字越大越先丟）：額度 0／1 > ctx 2 > 待確認 3 > 上輪 4 > 淨省 5 > model 6 > 本次 7 > 提醒／壓縮 8
    extra = []  # (priority, text)
    limit_parts = []
    running = []
    sid = data.get("session_id")
    try:
        if usage:
            lim = usage.limits_from_stdin(data.get("rate_limits"))
            for i, (key, zh_l, en_l) in enumerate((("five_hour", "5h", "5h"), ("seven_day", "週", "wk"))):
                w = (lim or {}).get(key)
                if not w:
                    continue
                pct = round(w["pct"])
                c = RED if w["pct"] > 95 else YELLOW if w["pct"] > 80 else ""
                rs = usage.fmt_reset(w.get("resets_at"), None, lng)
                if zh and key == "seven_day":
                    rs = rs.replace(" ", "")
                text = f"{zh_l if zh else en_l} {pct}%" + (f"({rs})" if rs else "")
                limit_parts.append((i, f"{c}{text}{RESET}" if c else text))
    except Exception:
        lim, limit_parts = None, []
    last = None
    try:
        if usage:
            last = usage.last_turn_tokens(data.get("transcript_path"))
            if last and last["total"] > 0:
                extra.append((4, f"{'上輪' if zh else 'last'} {ktok1(last['total'])}"))
    except Exception:
        last = None
    saved = net = ovh = 0
    sess = None
    try:
        now = time.time()
        if deck and sid:
            st = deck.load(sid)
            running = sorted((v for v in (st.get("running") or {}).values()
                              if isinstance(v, dict) and now - v.get("start", 0) < STALE),
                             key=lambda v: v.get("start", 0))
            tok = deck.session_tokens(data.get("transcript_path"), sid)
            if tok and tok["total"] > 0:
                sess = (7, f"{'本次' if zh else 'session'} {ktok(tok['total'])} tok")
            saved = deck.saved_chars(st) // 4
        if usage and sid:
            ovh = usage.overhead_tokens(sid)
        net = saved - ovh
        if abs(net) >= 100 and (saved or ovh):
            if net > 0:
                extra.append((5, f"{'淨省' if zh else 'net saved'}≈+{ktok(net)}"))
            else:
                extra.append((5, f"{DIM}{'淨' if zh else 'net'}≈-{ktok(-net)}{RESET}"))
        if sess:
            extra.append(sess)
    except Exception:
        running = []
        extra = [e for e in extra if e[0] == 4]

    try:  # 把額度與本機 Claude 用量寫進 usage.json（供選單列、面板讀）；失敗不影響顯示
        if usage and (lim or sid):
            claude = {"updated_at": int(time.time()), "session_id": sid, "surface": "cli", "ctx": int(n),
                      "saved": int(saved), "overhead": int(ovh), "net": int(net)}
            if last:
                claude["last_turn"] = last
            usage.update(limits=lim, claude=claude if sid else None)
    except Exception:
        pass

    try:  # 決策引擎：自動做了、還沒確認的動作數（狀態列資料夾沒有 decide.py 時略過）
        import decide
        pd = (data.get("workspace") or {}).get("project_dir") or data.get("cwd")
        k = len(decide.pending(pd, data.get("transcript_path"))) if pd else 0
        if k:
            extra.insert(0, (3, f"{ORANGE}{'待確認' if zh else 'to confirm'} {k}{RESET}"))
    except Exception:
        pass

    try:
        if running:
            cur = running[-1]
            who = cur.get("agent") or "main"
            mdl = cur.get("model") or ""
            if who == "main":
                label = model or "main"
                mc = MODEL_COLOR.get(deck.model_name(model), ORANGE)
            else:
                label = who + ("·" + mdl if mdl else "")
                mc = MODEL_COLOR.get(mdl, "\033[38;5;141m")
            text, raw = deck.plain(cur.get("tool"), cur.get("summary") or {}, lng)
            show_raw = cur.get("tool") == "Bash" and raw and raw not in text
            act = f"{ORANGE}▶{RESET} {mc}{label}{RESET} {text}"
            if show_raw:
                act += f" {DIM}{cut(raw, 28)}{RESET}"
            act += f" · {elapsed(time.time() - cur.get('start', time.time()))}"
            if len(running) > 1:
                act += f" (+{len(running) - 1})"
            den = compact or REMIND
            ctx = f"{color}ctx {n // 1000}k{RESET}/{den // 1000}k" if (compact or remind_enabled()) else f"{color}ctx {n // 1000}k{RESET}"
            parts = [(0, act)] + limit_parts + [(2, ctx)] + extra
            print(fit(parts, True, limit()))
            return
        parts = [(6, model)] + limit_parts + [(2, f"{color}ctx {n // 1000}k{RESET}")] + extra
        if remind_enabled():
            parts.append((8, f"{'提醒' if zh else 'remind'} {REMIND // 1000}k"))
        if compact is not None:
            parts.append((8, f"{'壓縮' if zh else 'compact'} {compact // 1000}k"))
        print(fit(parts, False, limit()))
    except Exception:
        return


if __name__ == "__main__":
    main()
