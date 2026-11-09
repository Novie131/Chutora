"""用量儀表的共用模組（statusline.py、snapshot.py 共用）。只用標準函式庫，任何函式都不丟例外給呼叫端以外的人。

- usage.json（~/.claude/chutora/usage.json）：額度（limits）與本機 Claude 的即時用量（claude）。
  {"v":1,"limits":{"source","updated_at","five_hour":{"pct","resets_at"},"seven_day":{...}},
   "claude":{"updated_at","session_id","surface","last_turn":{...},"ctx","saved","overhead","net"}}
  原子寫入（tmp＋os.replace）；壞檔當空；limits 只在新值的 updated_at 不比舊的早時才覆蓋（多個 session 同時跑）。
- last_turn_tokens：最後一則真正的使用者提示之後，主對話 assistant 的 usage 加總。
- est_tokens：token 估算＝ASCII 字元÷4＋非 ASCII 字元×1.0（CJK 約 1 字 1 token；偏保守，寧可高估開銷）。
- overhead_tokens：外掛的固定開銷估算（SessionStart 實際注入文字＋skills／agents 描述文字）以 est_tokens 估。
- fmt_reset：額度重置時間的短字串。
"""
import json, os, re, time

VERSION = 1
CHARS_PER_TOKEN = 4  # ASCII 每 token 約 4 字元
NONASCII_TOKENS = 1.0  # 非 ASCII（主要是 CJK）每字約 1 token
WEEKDAY = {"zh": "一二三四五六日", "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}


def conf_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "chutora")


def path():
    return os.path.join(conf_dir(), "usage.json")


# ---------------------------------------------------------------- usage.json
def load():
    """讀 usage.json；沒有、壞檔、不是物件都當空。"""
    try:
        with open(path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(doc):
    """原子寫入；失敗回傳 False（不丟例外）。"""
    p = path()
    tmp = "%s.%d.tmp" % (p, os.getpid())
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, p)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def _ts(d):
    v = d.get("updated_at") if isinstance(d, dict) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _strip_ts(x):
    if isinstance(x, dict):
        return {k: _strip_ts(v) for k, v in x.items() if k != "updated_at"}
    return x


def update(limits=None, claude=None, now=None, min_interval=5):
    """把 limits／claude 合進 usage.json。回傳 True 表示有寫入。

    - limits 只在它的 updated_at 不比檔案裡的早時才覆蓋；claude 直接覆蓋。
    - 內容（不含 updated_at）沒變、且檔案裡的時間戳距今不到 min_interval 秒就不重寫。
    """
    if not limits and not claude:
        return False
    now = time.time() if now is None else now
    old = load()
    doc = {"v": VERSION}
    for k in ("limits", "claude"):
        if isinstance(old.get(k), dict):
            doc[k] = old[k]
    if isinstance(limits, dict) and limits:
        if _ts(limits) >= _ts(doc.get("limits")):
            doc["limits"] = limits
    if isinstance(claude, dict) and claude:
        doc["claude"] = claude
    if _strip_ts(doc) == _strip_ts(old):
        newest = max(_ts(old.get("limits")), _ts(old.get("claude")))
        if 0 <= now - newest < min_interval:
            return False
    return save(doc)


def limits_from_stdin(rate_limits, now=None, source="claude-cli"):
    """把 statusline stdin 的 rate_limits 轉成 usage.json 的 limits；沒有可用讀數回傳 None。"""
    if not isinstance(rate_limits, dict):
        return None
    now = int(time.time() if now is None else now)
    out = {"source": source, "updated_at": now}
    for src, dst in (("five_hour", "five_hour"), ("seven_day", "seven_day")):
        w = rate_limits.get(src)
        if not isinstance(w, dict):
            continue
        pct, rs = w.get("used_percentage"), w.get("resets_at")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            continue
        ent = {"pct": round(pct, 1) if pct != int(pct) else int(pct)}
        if isinstance(rs, (int, float)) and not isinstance(rs, bool):
            ent["resets_at"] = int(rs)
        out[dst] = ent
    return out if len(out) > 2 else None


# ---------------------------------------------------------------- transcript
def is_real_prompt(d):
    """使用者真正打的提示：不是 tool_result、不是 meta、不是子 agent（isSidechain）。"""
    if not isinstance(d, dict) or d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
        return False
    m = d.get("message")
    if not isinstance(m, dict):
        return False
    c = m.get("content")
    if isinstance(c, str):
        return bool(c.strip())
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return False
        return any(isinstance(b, dict) and b.get("type") in ("text", "image") for b in c)
    return False


def prompt_text(d):
    """真正提示的文字（只取 text 區塊）。"""
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return ""


def _num(u, k):
    v = u.get(k, 0)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _tail_lines(p, want_prompt, cap=32 << 20):
    """從檔尾往前讀，直到讀到的內容裡有真正的提示（或讀完／到上限）。回傳 JSON 行（完整行）。"""
    size = os.path.getsize(p)
    n = 256 << 10
    with open(p, "rb") as f:
        while True:
            n = min(n, size)
            f.seek(size - n)
            chunk = f.read(n)
            lines = chunk.split(b"\n")
            if n < size:
                lines = lines[1:]  # 第一行可能被切一半
            if n >= size or n >= cap or want_prompt(lines):
                return lines
            n *= 4


def _has_prompt(lines):
    for ln in lines:
        if b'"user"' not in ln:
            continue
        try:
            if is_real_prompt(json.loads(ln)):
                return True
        except ValueError:
            continue
    return False


def last_turn_tokens(transcript_path):
    """最後一則真正使用者提示之後，主對話（排除 isSidechain）assistant 訊息的 usage 加總。

    同一個 message id 只算一次（取最後出現的那份）。
    回傳 {"input","cache_write","cache_read","output","total"}；total＝input＋cache_write＋output，
    cache 讀取另列、不算進 total（與「本次」一致）。讀不到、沒有任何 assistant 訊息回傳 None。
    """
    try:
        if not transcript_path or not os.path.isfile(transcript_path):
            return None
        lines = _tail_lines(transcript_path, _has_prompt)
    except OSError:
        return None
    msgs, last = {}, 0
    rows = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        rows.append(d)
        if is_real_prompt(d):
            last = len(rows)
    for d in rows[last:]:
        m = d.get("message")
        if d.get("type") != "assistant" or d.get("isSidechain") or not isinstance(m, dict):
            continue
        u = m.get("usage")
        if not isinstance(u, dict):
            continue
        msgs[m.get("id") or "#%d" % len(msgs)] = u
    if not msgs:
        return None
    t = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    for u in msgs.values():
        t["input"] += _num(u, "input_tokens")
        t["cache_write"] += _num(u, "cache_creation_input_tokens")
        t["cache_read"] += _num(u, "cache_read_input_tokens")
        t["output"] += _num(u, "output_tokens")
    t["total"] = t["input"] + t["cache_write"] + t["output"]
    return {k: int(v) for k, v in t.items()}


# ---------------------------------------------------------------- 固定開銷
def est_from_counts(ascii_n, nonascii_n):
    """由 ASCII／非 ASCII 字元數估 tokens。"""
    return int(max(0, ascii_n) / CHARS_PER_TOKEN + max(0, nonascii_n) * NONASCII_TOKENS)


def count_chars(text):
    """(ASCII 字元數, 非 ASCII 字元數)。"""
    a = sum(1 for c in text if ord(c) < 128)
    return a, len(text) - a


def est_tokens(text):
    """文字的 token 估算＝ASCII 字元÷4＋非 ASCII 字元×1.0。

    固定開銷（注入文字、skills／agents 描述）含大量中文，字元數÷4 會嚴重低估，所以改用這個。
    """
    return est_from_counts(*count_chars(text or ""))


def overhead_dir():
    return os.path.join(conf_dir(), "overhead")


def _safe(sid):
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(sid or ""))[:80] or None


def _frontmatter_text(p):
    """frontmatter 裡 name＋description 的文字（description 可跨行縮排續行）。"""
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return ""
    if not lines or lines[0].strip() != "---":
        return ""
    parts, cur = [], None
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        m = re.match(r"^(name|description):\s*(.*)$", ln)
        if m:
            cur = m.group(1)
            v = m.group(2).strip()
            if v not in (">", "|", ">-", "|-"):
                parts.append(v)
        elif cur == "description" and ln[:1] in (" ", "\t"):
            parts.append(ln.strip())
        else:
            cur = None
    return "".join(parts)


def plugin_root():
    r = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if r and os.path.isdir(r):
        return r
    r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return r if os.path.isdir(os.path.join(r, "skills")) or os.path.isdir(os.path.join(r, "agents")) else None


def descriptor_counts():
    """外掛 skills/*/SKILL.md 與 agents/*.md 的 name＋description 的 (ASCII 字元數, 非 ASCII 字元數)。

    找得到外掛目錄就現算並快取到 overhead/.descriptors（"ascii nonascii"）；
    狀態列是被複製到別處執行的（找不到外掛目錄）就讀快取（舊格式只有一個數字，當全是 ASCII）。
    """
    cache = os.path.join(overhead_dir(), ".descriptors")
    root = plugin_root()
    if root:
        import glob
        text = "".join(_frontmatter_text(p) for p in glob.glob(os.path.join(root, "skills", "*", "SKILL.md")))
        text += "".join(_frontmatter_text(p) for p in glob.glob(os.path.join(root, "agents", "*.md")))
        a, n = count_chars(text)
        try:
            os.makedirs(overhead_dir(), exist_ok=True)
            old = None
            try:
                with open(cache) as f:
                    old = f.read().strip()
            except OSError:
                pass
            if old != "%d %d" % (a, n):
                with open(cache + ".tmp", "w") as f:
                    f.write("%d %d\n" % (a, n))
                os.replace(cache + ".tmp", cache)
        except OSError:
            pass
        return a, n
    return _read_counts(cache)


def _read_counts(p):
    try:
        with open(p) as f:
            parts = f.read().split()
        if len(parts) == 1:
            return max(0, int(parts[0])), 0
        return max(0, int(parts[0])), max(0, int(parts[1]))
    except (OSError, ValueError, IndexError):
        return 0, 0


def injected_counts(session_id):
    """session-start.sh 記下的本 session 實際注入文字的 (ASCII 字元數, 非 ASCII 字元數)；沒有記錄回傳 (0, 0)。"""
    s = _safe(session_id)
    if not s:
        return 0, 0
    return _read_counts(os.path.join(overhead_dir(), s))


def overhead_tokens(session_id):
    """外掛固定開銷（tokens，估算）＝est_tokens（SessionStart 注入文字＋skills／agents 描述）。"""
    try:
        a1, n1 = injected_counts(session_id)
        a2, n2 = descriptor_counts()
        return est_from_counts(a1 + a2, n1 + n2)
    except Exception:
        return 0


# ---------------------------------------------------------------- 顯示
def fmt_reset(epoch, now=None, lng="zh"):
    """額度重置時間。24 小時內：「2h13m」「45m」；更久：「週四 14:00」／「Thu 14:00」（本機時區）。壞值回傳 ""。"""
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)):
        return ""
    now = time.time() if now is None else now
    left = int(epoch - now)
    if left < 24 * 3600:
        left = max(0, left)
        h, m = left // 3600, left % 3600 // 60
        return f"{h}h{m:02d}m" if h else f"{m}m"
    t = time.localtime(epoch)
    if lng == "zh":
        return f"週{WEEKDAY['zh'][t.tm_wday]} {t.tm_hour:02d}:{t.tm_min:02d}"
    return f"{WEEKDAY['en'][t.tm_wday]} {t.tm_hour:02d}:{t.tm_min:02d}"
