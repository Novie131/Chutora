#!/usr/bin/env python3
"""statusLine 指令：駕駛艙穩定版。只用官方 statusline 與標準 hooks，不依賴 mod API。

工作中：▶ worker·Sonnet 跑測試 npm test · 12s │ 本次 42k tok │ 瘦身省≈8k │ ctx 95k/120k
閒置時：Opus │ ctx 95k │ 提醒 100k │ 壓縮 120k │ 本次 42k tok │ 瘦身省≈8k

- 目前動作來自 activity.py 寫的 ~/.claude/chutora/activity/<session_id>.json；沒有就只顯示閒置版。
- 本次 token：transcript 的 usage 精確加總（input＋cache 寫入＋output，不含 cache 讀取），主對話＋子 agent。
- 瘦身省：噪音瘦身、讀檔去重、MCP 瘦身擋在 context 外的字元數 ÷4，標「≈」表示估算。
- ctx 用 total_input_tokens（缺時加總 current_usage），不用 used_percentage；8 萬以下綠、提醒門檻以下黃、以上紅。
- 寬度：CHUTORA_STATUS_WIDTH 或 COLUMNS（預設 120）；放不下時依重要性丟掉後面的欄位，再截短動作描述。
壞輸入安靜結束。
"""
import json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact import compact_point, remind_tokens
try:
    from compact import lang
except ImportError:  # 舊版 compact.py
    lang = lambda: "zh"  # noqa: E731
try:
    import deck
except Exception:  # 狀態列資料夾裡沒有 deck.py（舊版同步）時，只顯示閒置版
    deck = None

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

    extra = []  # (priority, text)
    running = []
    try:
        sid = data.get("session_id")
        if deck and sid:
            st = deck.load(sid)
            now = time.time()
            running = sorted((v for v in (st.get("running") or {}).values()
                              if isinstance(v, dict) and now - v.get("start", 0) < STALE),
                             key=lambda v: v.get("start", 0))
            tok = deck.session_tokens(data.get("transcript_path"), sid)
            if tok and tok["total"] > 0:
                extra.append((3, f"{'本次' if zh else 'session'} {ktok(tok['total'])} tok"))
            saved = deck.saved_chars(st) // 4
            if saved >= 100:
                extra.append((4, f"{'瘦身省' if zh else 'trimmed'}≈{ktok(saved)}"))
    except Exception:
        extra, running = [], []

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
            parts = [(0, act)] + extra + [(1, f"{color}ctx {n // 1000}k{RESET}/{den // 1000}k")]
            print(fit(parts, True, limit()))
            return
        parts = [(2, model), (0, f"{color}ctx {n // 1000}k{RESET}"), (5, f"{'提醒' if zh else 'remind'} {REMIND // 1000}k")]
        if compact is not None:
            parts.append((5, f"{'壓縮' if zh else 'compact'} {compact // 1000}k"))
        parts += extra
        if not extra:
            print(" │ ".join(t for _, t in parts))
        else:
            print(fit(parts, False, limit()))
    except Exception:
        return


if __name__ == "__main__":
    main()
