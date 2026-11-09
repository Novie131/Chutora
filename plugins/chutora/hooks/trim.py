#!/usr/bin/env python3
"""PostToolUse（Bash）hook：噪音輸出瘦身。

又長又雜的指令輸出（安裝、建置、測試 log）在進入 context 之前先瘦身：
去色碼、收斂進度列與重複行，保留開頭、結尾、錯誤與摘要行；原文一定另存一份，
需要時 Claude 可以用 Read 讀回來。原則是寧可少砍：讀檔類指令、git diff/show、
已經自己用 head/tail/grep 過濾過的指令、結構化或 JSON 輸出都不動。

透過標準 PostToolUse hook 的 hookSpecificOutput.updatedToolOutput 替換 Claude 看到的
結果（Bash 的結果物件是 {stdout, stderr, interrupted, ...}，只改 stdout／stderr，其餘欄位照抄）。
失敗的指令走 PostToolUseFailure，不經過這裡，所以錯誤輸出一律完整保留。

開關：CHUTORA_TRIM=0 關閉；/chutora trim on|off 寫入 ~/.claude/chutora/trim。
門檻依模式（~/.claude/chutora/mode）：economy 較積極、quality 較保守。
真的瘦身時在觀察紀錄寫一筆 trimmed（工具、原長度、省下多少；見 observe.py）。
任何例外都安靜放行（不輸出），絕不擋住工具結果。
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from compact import lang
except Exception:  # pragma: no cover
    lang = lambda: "en"  # noqa: E731


def conf_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "chutora")


KEEP_RAW = 50

# 各模式的門檻：(字元數, 行數, 保留開頭行, 保留結尾行)
THRESHOLDS = {
    "economy": (3000, 80, 25, 40),
    "balanced": (4000, 120, 40, 60),
    "quality": (8000, 250, 60, 100),
}

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
IMPORTANT = re.compile(
    r"(?i)\b(errors?|fail(?:ed|ure|ures|ing|s)?|exception|traceback|warn(?:ing|ings)?|panic(?:ked)?|fatal|"
    r"assert(?:ion)?(?:error)?|denied|cannot|can't|unable|undefined|not found|missing|segmentation fault|"
    r"deprecat\w*|vulnerabilit\w*)\b|✗|✕|×|✘|FAIL|ERR!|\bE\d{3,}\b|^\s*at \S|^\s*File \"|^\s*-->|^\s*\^"
)
SUMMARY = re.compile(
    r"(?i)\b(passed|failed|skipped|tests?:|test result|test suites?:|summary|total|added \d+ packages?|"
    r"removed \d+ packages?|changed \d+ packages?|up to date|audited|found \d+|successfully installed|"
    r"requirement already satisfied|finished|done in|compiled|built in|build (?:succeeded|failed)|"
    r"coverage|ran \d+ tests?|ok\b|\d+ (?:passing|pending|failing))"
)
PROGRESS = re.compile(r"(?i)(\d{1,3}(?:\.\d+)?\s?%|[█▓▒░■□#=>-]{6,}|\b\d+(?:\.\d+)?\s?[kKmMgG]i?B(?:/s)?\b|eta\s*\d|downloading|fetching|resolving|extracting|⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏)")

# 只算「警告」、不含錯誤字眼的行：同一類（開頭三個詞相同）太多時才摺疊，錯誤行一律保留
WARNISH = re.compile(r"(?i)\b(?:warn(?:ing|ings)?|deprecat\w*)\b")
ERRORISH = re.compile(
    r"(?i)\b(errors?|fail(?:ed|ure|ures|ing|s)?|exception|traceback|panic(?:ked)?|fatal|assert(?:ion)?(?:error)?|"
    r"denied|cannot|can't|unable|undefined|not found|missing|segmentation fault)\b|✗|✕|×|✘|FAIL|ERR!|\bE\d{3,}\b"
)
WARN_GROUP_MIN = 9   # 同一類警告超過 8 行才摺疊
WARN_KEEP_HEAD = 3   # 摺疊時留前 3 行與最後 1 行


def warn_key(line):
    return " ".join(line.lower().split()[:3])


def similar_warnings(lines):
    """回傳要摺疊的警告行號：同一類警告太多時，只留前幾行與最後一行。"""
    groups = {}
    for i, line in enumerate(lines):
        if WARNISH.search(line) and not ERRORISH.search(line):
            groups.setdefault(warn_key(line), []).append(i)
    out = set()
    for idx in groups.values():
        if len(idx) >= WARN_GROUP_MIN:
            out.update(idx[WARN_KEEP_HEAD:-1])
    return out


READ_LIKE = {"cat", "head", "tail", "less", "more", "bat", "nl", "sed", "awk", "jq", "yq", "diff", "cmp",
             "grep", "rg", "ag", "ack", "find", "fd", "ls", "tree", "wc", "file", "stat", "xxd", "hexdump",
             "od", "strings", "echo", "printf", "env", "printenv", "which", "type", "man", "readlink", "realpath"}
READ_LIKE_GIT = {"diff", "show", "log", "blame", "grep", "ls-files", "cat-file", "format-patch", "status"}

NOISY = [
    re.compile(r"^(?:npm|pnpm|yarn|bun)\s+(?:i|install|add|ci|update|upgrade|test|t|run\s+(?:build|test|lint)\S*)\b"),
    re.compile(r"^(?:npx\s+)?(?:jest|vitest|mocha|playwright\s+test|cypress\s+run|tsc|eslint|webpack|vite\s+build|next\s+build)\b"),
    re.compile(r"^(?:python3?\s+-m\s+)?(?:pip3?|uv\s+pip|poetry|pipenv)\s+(?:install|sync|lock|add|update)\b"),
    re.compile(r"^uv\s+(?:sync|add|lock)\b"),
    re.compile(r"^(?:python3?\s+-m\s+)?(?:pytest|unittest|tox|nox)\b"),
    re.compile(r"^cargo\s+(?:build|test|check|clippy|run|install|update)\b"),
    re.compile(r"^go\s+(?:build|test|vet|mod\s+(?:download|tidy)|install|get)\b"),
    re.compile(r"^(?:make|cmake|ninja|gradle|\./gradlew|mvn|\./mvnw|bazel|dotnet\s+(?:build|test|restore)|swift\s+(?:build|test)|xcodebuild)\b"),
    re.compile(r"^(?:brew|apt|apt-get|dnf|yum|apk)\s+(?:install|upgrade|update)\b"),
    re.compile(r"^(?:bundle\s+install|gem\s+install|composer\s+(?:install|update)|mix\s+(?:deps\.get|test|compile)|docker\s+(?:build|pull|compose\s+(?:build|pull|up)))\b"),
]


def cfg_file(name):
    try:
        with open(os.path.join(conf_dir(), name)) as f:
            return f.read().strip().lower()
    except OSError:
        return ""


def enabled():
    if os.environ.get("CHUTORA_TRIM", "").strip() == "0":
        return False
    return cfg_file("trim") != "off"


def mode():
    m = (os.environ.get("CHUTORA_MODE") or cfg_file("mode") or "balanced").strip().lower()
    return m if m in THRESHOLDS else "balanced"


def first_segment(cmd):
    """取第一段指令（去掉 cd X && 、環境變數設定、sudo/time 等前綴）。"""
    segs = re.split(r"\s*(?:&&|;|\|\||\n)\s*", cmd.strip())
    for s in segs:
        s = s.strip()
        if not s or re.match(r"^(?:cd|pushd|export|source|\.)\b", s):
            continue
        s = re.sub(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", s)
        s = re.sub(r"^(?:sudo|time|nice|nohup|command|exec|caffeinate)\s+", "", s)
        return s
    return ""


def classify(cmd):
    """回傳 'skip'（絕不動）、'noisy'（積極）或 'other'（保守）。"""
    if not isinstance(cmd, str) or not cmd.strip():
        return "skip"
    # 已經自己過濾或導向的：交給使用者／Claude 的意圖
    if re.search(r"\|\s*(?:head|tail|grep|rg|sed|awk|jq|less|more|wc|sort|uniq|cut)\b", cmd):
        return "skip"
    seg = first_segment(cmd)
    if not seg:
        return "skip"
    # 串接的指令（例如 rm -rf node_modules && npm install）：只要有一段是會產生大量噪音的指令，
    # 就以它為準；輸出主要來自那一段。
    for part in re.split(r"\s*(?:&&|;|\|\||\n)\s*", cmd.strip()):
        part = re.sub(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", part.strip())
        part = re.sub(r"^(?:sudo|time|nice|nohup|command|exec|caffeinate)\s+", "", part)
        if part and any(rx.search(part) for rx in NOISY):
            return "noisy"
    words = seg.split()
    prog = os.path.basename(words[0])
    if prog in READ_LIKE:
        return "skip"
    if prog == "git" and len(words) > 1 and words[1] in READ_LIKE_GIT:
        return "skip"
    if prog in ("python", "python3", "node", "ruby", "perl") and len(words) > 1 and words[1] == "-c":
        return "skip"
    for rx in NOISY:
        if rx.search(seg):
            return "noisy"
    return "other"


def clean(text):
    text = ANSI.sub("", text)
    out = []
    for line in text.split("\n"):
        if "\r" in line:
            parts = [p for p in line.split("\r") if p.strip()]
            line = parts[-1] if parts else ""
        out.append(line.rstrip())
    return out


def norm(line):
    return re.sub(r"\d+", "#", line.strip())


def trim_lines(lines, head, tail, ctx):
    n = len(lines)
    tail_from = max(0, n - tail)
    folded = similar_warnings(lines)
    keep = (set(range(min(head, n))) | set(range(tail_from, n))) - folded
    for i, line in enumerate(lines):
        if i in folded:
            continue
        if IMPORTANT.search(line):
            keep.update(j for j in range(max(0, i - ctx), min(n, i + ctx + 1)) if j not in folded)
        elif SUMMARY.search(line) and not PROGRESS.search(line):
            keep.add(i)
    out, skipped, stats = [], 0, {"progress": 0, "repeat": 0, "other": 0, "warn": 0}
    prev_norm, run = None, 0
    gap = 0

    def flush_gap():
        nonlocal gap
        if gap:
            out.append(("… 略過 %d 行 …" if lang() != "en" else "… %d lines omitted …") % gap)
            gap = 0

    for i, line in enumerate(lines):
        if i not in keep:
            gap += 1
            skipped += 1
            stats["warn" if i in folded else ("progress" if PROGRESS.search(line) else
                  ("repeat" if norm(line) == prev_norm else "other"))] += 1
            prev_norm = norm(line)
            continue
        nl = norm(line)
        if nl and nl == prev_norm and head <= i < tail_from and not IMPORTANT.search(line):
            run += 1
            if run > 2:  # 中段（開頭、結尾以外）同樣的行最多留 3 行
                gap += 1
                skipped += 1
                stats["repeat"] += 1
                continue
        else:
            run = 0
        flush_gap()
        out.append(line)
        prev_norm = nl
    flush_gap()
    return out, skipped, stats


def shrink(text, kind, md):
    """回傳 (新文字, 統計) 或 None（不處理）。"""
    chars, max_lines, head, tail = THRESHOLDS[md]
    ctx = 2
    if kind == "other":  # 不認得的指令：門檻加倍、保留更多
        chars, max_lines, head, tail, ctx = chars * 2, max_lines * 2, head * 2, tail * 2, 3
    if not text or (len(text) <= chars and text.count("\n") + 1 <= max_lines):
        return None
    lines = clean(text)
    out, skipped, stats = trim_lines(lines, head, tail, ctx)
    new = "\n".join(out)
    saved = len(text) - len(new)
    if skipped == 0 or saved < max(1000, len(text) * 0.2):
        return None
    stats.update(orig_lines=len(lines), orig_chars=len(text), skipped=skipped, saved=saved)
    return new, stats


def save_raw(tool_use_id, cmd, resp):
    d = os.path.join(conf_dir(), "raw")
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tool_use_id or "unknown"))[:80] or "unknown"
    path = os.path.join(d, safe + ".log")
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write("$ " + cmd + "\n\n--- stdout ---\n" + (resp.get("stdout") or "") +
                "\n\n--- stderr ---\n" + (resp.get("stderr") or "") + "\n")
    logs = sorted((os.path.join(d, x) for x in os.listdir(d) if x.endswith(".log")),
                  key=lambda p: os.path.getmtime(p))
    for old in logs[:-KEEP_RAW]:
        try:
            os.remove(old)
        except OSError:
            pass
    return path


def save_raw_text(tool_use_id, header, body):
    """原文另存到 ~/.claude/chutora/raw/<tool_use_id>.log（保留最近 KEEP_RAW 份），回傳路徑。"""
    d = os.path.join(conf_dir(), "raw")
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(tool_use_id or "unknown"))[:80] or "unknown"
    path = os.path.join(d, safe + ".log")
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(header + "\n\n" + body + "\n")
    logs = sorted((os.path.join(d, x) for x in os.listdir(d) if x.endswith(".log")),
                  key=lambda q: os.path.getmtime(q))
    for old in logs[:-KEEP_RAW]:
        try:
            os.remove(old)
        except OSError:
            pass
    return path


def add_stats(saved_chars, kind="bash", session_id=None):
    """累計擋在 context 外的字元數。total_chars 是所有來源的合計；kinds 分開記 bash／dedup／mcp。
    有 session_id 時另記到這個 session 的 activity 檔，給狀態列與駕駛艙顯示「本次瘦身省≈」。"""
    if session_id:
        try:
            import deck
            deck.add_saved(session_id, saved_chars, kind)
        except Exception:
            pass
    p = os.path.join(conf_dir(), "trim-stats.json")
    try:
        with open(p) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    day = datetime.date.today().isoformat()
    days = st.get("days") or {}
    days[day] = int(days.get(day, 0)) + int(saved_chars)
    for k in sorted(days)[:-60]:  # 只留最近 60 天
        del days[k]
    kinds = st.get("kinds") or {}
    kinds[kind] = int(kinds.get(kind, 0)) + int(saved_chars)
    st.update(days=days, kinds=kinds, total_chars=int(st.get("total_chars", 0)) + int(saved_chars),
              count=int(st.get("count", 0)) + 1)
    tmp = p + ".tmp"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, p)


def observe_trimmed(data, orig_chars, saved_chars, kind):
    """觀察紀錄：這次真的瘦身了（只寫檔、不輸出，不增加 token）。"""
    try:
        import observe
        observe.note(data, "trimmed", kind=kind, orig_chars=int(orig_chars), saved_chars=int(saved_chars))
    except Exception:
        pass


def note(stats, path):
    s = stats
    if lang() == "en":
        return (f"[Chutora trim: output was {s['orig_lines']} lines / {s['orig_chars']} chars; omitted "
                f"{s['skipped']} lines (progress {s['progress']}, repeats {s['repeat']}, other {s['other']}"
                f"{', similar warnings %d' % s['warn'] if s.get('warn') else ''}). "
                f"Errors, warnings, summaries, the start and the end are kept. Full original: {path} "
                f"(read it with the Read tool if you need anything omitted). Turn off with CHUTORA_TRIM=0 or /chutora trim off.]")
    return (f"[Chutora 瘦身：原輸出 {s['orig_lines']} 行／{s['orig_chars']} 字元，略過 {s['skipped']} 行"
            f"（進度 {s['progress']}、重複 {s['repeat']}、其他 {s['other']}"
            f"{'、同類警告 %d' % s['warn'] if s.get('warn') else ''}），錯誤、警告、摘要、開頭與結尾都保留。"
            f"完整原文：{path}（需要被略過的內容時用 Read 讀取）。可用 CHUTORA_TRIM=0 或 /chutora trim off 關閉。]")


def process(data):
    """回傳要印出的 hook JSON（dict），或 None 表示不動。"""
    if data.get("tool_name") != "Bash" or not enabled():
        return None
    resp = data.get("tool_response")
    if not isinstance(resp, dict):
        return None
    if resp.get("isImage") or resp.get("backgroundTaskId") or resp.get("structuredContent") \
            or resp.get("persistedOutputPath") or resp.get("stdoutHoldsOutputEnd") or resp.get("interrupted"):
        return None
    cmd = (data.get("tool_input") or {}).get("command", "")
    kind = classify(cmd)
    if kind == "skip":
        return None
    stdout, stderr = resp.get("stdout") or "", resp.get("stderr") or ""
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return None
    if stdout.lstrip()[:1] in ("{", "["):  # 看起來是 JSON 等結構化輸出
        return None
    md = mode()
    r_out, r_err = shrink(stdout, kind, md), shrink(stderr, kind, md)
    if not r_out and not r_err:
        return None
    path = save_raw(data.get("tool_use_id"), cmd, resp)
    new = dict(resp)
    total = {"orig_lines": 0, "orig_chars": 0, "skipped": 0, "saved": 0, "progress": 0, "repeat": 0, "other": 0,
             "warn": 0}
    for key, r in (("stdout", r_out), ("stderr", r_err)):
        if r:
            new[key] = r[0]
            for k in total:
                total[k] += r[1].get(k, 0)
    tag = note(total, path)
    if r_out:
        new["stdout"] = new["stdout"] + "\n" + tag
    else:
        new["stderr"] = new["stderr"] + "\n" + tag
    saved = len(stdout) + len(stderr) - len(new["stdout"]) - len(new["stderr"])
    if saved <= 0:
        return None
    add_stats(saved, session_id=data.get("session_id"))
    observe_trimmed(data, len(stdout) + len(stderr), saved, "bash")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": new}}


def main():
    try:
        data = json.load(sys.stdin)
        out = process(data)
    except Exception:
        return
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
