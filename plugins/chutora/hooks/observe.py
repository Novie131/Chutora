#!/usr/bin/env python3
"""觀察 hook（學習的地基）：PostToolUse／PostToolUseFailure／SubagentStop／UserPromptSubmit。

把「發生了什麼」記到 ~/.claude/chutora/projects/<專案 id>/observations.jsonl（專案 id 見 projectid.py）。
完全不輸出任何東西，所以不會增加 token；任何錯誤都安靜結束，不擋工具。

每筆紀錄：
  ts        時間（ISO 8601）
  session   session id
  agent     main（主對話）或子 agent 類型（例如 worker、Explore）
  signal    tool_ok、tool_fail、repeat_error、delegation_result、user_correction、user_choice、user_prompt、
            guard_ask／guard_deny（由 guard.py 呼叫 append() 寫入：被守門攔下的呼叫不會有 PostToolUse）
  tool      工具名（沒有就省略）
  summary   精簡摘要：指令、路徑、子 agent 描述等，已遮罩金鑰、截到 160 字元；不存工具輸出內容
  其他      out_chars（輸出大小）、count（重複次數）、match（糾正用語）、chars（提示長度）等數字或短字串
使用者的一般提示只記長度（user_prompt），不記內容；糾正與選擇才記一小段（已遮罩）。

輪替：檔案超過 5 MB（CHUTORA_OBSERVE_MAX_MB 可調）就移到 archive/，最多留 5 份。
開關：CHUTORA_OBSERVE=0，或 /chutora observe off（寫入 ~/.claude/chutora/observe）。
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from redact import short  # noqa: E402

KEEP_ARCHIVES = 5
STATE_SESS_CAP = 20
STATE_SIG_CAP = 60

CORRECTION = re.compile(
    r"(不對|錯了|搞錯|弄錯|我不是要這個|不是我要的|不是這樣|不是這個意思|你誤會|誤會了|別這樣做|不要這樣做|重做一次|"
    r"\bthat'?s (?:wrong|not (?:it|right|what i (?:asked|meant|wanted)))\b|\bthat is (?:wrong|not what)\b|"
    r"\bnot what i (?:asked|meant|wanted)\b|\byou misunderstood\b|\bwrong (?:file|approach|place|one)\b|"
    r"\b(?:undo|revert) (?:that|this|it)\b|\bno,? (?:that'?s|this is) not\b|\bi didn'?t ask (?:for|you to)\b)",
    re.I)
CHOICE = re.compile(
    r"^\s*(?:\d{1,2}|[a-dA-D]|(?:選|就|用)\s*\S{1,8}|第\s*[一二三四五六七八九十\d]+\s*(?:個|項|種|題|案)?|"
    r"(?:option|choice)\s*\w{1,4}|(?:the )?(?:first|second|third|last) one)\s*[。.!！]?\s*$", re.I)
ERROR_HINT = ("error", "exception", "traceback", "failed", "not found", "no such file", "permission denied",
              "fatal:", "refused", "timed out", "錯誤", "失敗", "找不到", "無法")


def enabled():
    if os.environ.get("CHUTORA_OBSERVE", "").strip() == "0":
        return False
    try:
        with open(os.path.join(os.path.expanduser("~"), ".claude", "chutora", "observe")) as f:
            return f.read().strip().lower() != "off"
    except OSError:
        return True


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def agent_of(data):
    t = data.get("agent_type")
    return str(t).split(":")[-1] if t else "main"


def rel(path, root):
    try:
        p = os.path.abspath(str(path))
        if root and (p == root or p.startswith(root.rstrip("/") + "/")):
            return os.path.relpath(p, root)
    except Exception:
        pass
    return str(path)


def tool_summary(tool, inp, root):
    if not isinstance(inp, dict):
        return ""
    if tool == "Bash":
        return short(inp.get("command"), 160)
    if tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        return short(rel(inp.get("file_path") or inp.get("notebook_path") or "", root), 160)
    if tool in ("Grep", "Glob"):
        return short(f"{inp.get('pattern', '')} @ {rel(inp.get('path') or '.', root)}", 160)
    if tool in ("Agent", "Task"):
        return short(f"{inp.get('subagent_type') or 'general-purpose'}: {inp.get('description') or ''}", 160)
    if tool == "WebFetch":
        return short(re.sub(r"[?#].*$", "", str(inp.get("url") or "")), 160)
    if tool == "WebSearch":
        return short(inp.get("query"), 120)
    if tool == "Skill":
        return short(inp.get("skill") or inp.get("command"), 80)
    if tool == "AskUserQuestion":
        qs = inp.get("questions") or []
        return short("; ".join(str(q.get("question", "")) for q in qs if isinstance(q, dict)), 160)
    return short("keys: " + ",".join(sorted(str(k) for k in inp)[:12]), 120) if inp else ""


def size_of(resp):
    try:
        return len(resp) if isinstance(resp, str) else len(json.dumps(resp, ensure_ascii=False))
    except (TypeError, ValueError):
        return 0


def error_text(data):
    e = data.get("error")
    if isinstance(e, str) and e.strip():
        return e
    resp = data.get("tool_response")
    if isinstance(resp, dict):
        for k in ("stderr", "error", "message"):
            v = resp.get(k)
            if isinstance(v, str) and v.strip():
                return v
    if isinstance(resp, str):
        return resp
    return ""


def signature(tool, text):
    line = ""
    for raw in text.splitlines():
        if any(m in raw.lower() for m in ERROR_HINT):
            line = raw.strip()
            break
    if not line:
        line = text.strip().splitlines()[0] if text.strip() else ""
    line = re.sub(r"0x[0-9a-fA-F]+|\d+", "#", line)
    line = re.sub(r"[/\\][^\s]*", "/…", line)
    return (tool or "") + "::" + re.sub(r"\s+", " ", line).strip().lower()[:100]


def bump(state_path, session, sig):
    try:
        with open(state_path) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    order = st.setdefault("_order", [])
    s = session or "_none"
    if s in order:
        order.remove(s)
    order.append(s)
    for old in order[:-STATE_SESS_CAP]:
        st.pop(old, None)
    st["_order"] = order[-STATE_SESS_CAP:]
    sigs = st.setdefault(s, {})
    sigs[sig] = int(sigs.get(sig, 0)) + 1
    if len(sigs) > STATE_SIG_CAP:
        for k in sorted(sigs, key=sigs.get)[: len(sigs) - STATE_SIG_CAP]:
            sigs.pop(k, None)
    tmp = state_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, state_path)
    return sigs[sig]


def rotate(path):
    try:
        limit = float(os.environ.get("CHUTORA_OBSERVE_MAX_MB") or 5) * 1024 * 1024
    except ValueError:
        limit = 5 * 1024 * 1024
    try:
        if os.path.getsize(path) <= limit:
            return
    except OSError:
        return
    arch = os.path.join(os.path.dirname(path), "archive")
    os.makedirs(arch, exist_ok=True)
    dst = os.path.join(arch, "observations-" + time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}.jsonl")
    os.replace(path, dst)
    olds = sorted(os.path.join(arch, x) for x in os.listdir(arch) if x.startswith("observations-"))
    for old in olds[:-KEEP_ARCHIVES]:
        try:
            os.remove(old)
        except OSError:
            pass


def resolve_guard(data, ddir):
    """守門問過的同一個 tool_use_id 真的執行了 → 在變更紀錄標成 approved。"""
    tid = data.get("tool_use_id")
    p = os.path.join(ddir, "guard-pending.json")
    if not tid or not os.path.exists(p):
        return
    try:
        with open(p) as f:
            pend = json.load(f)
        item = pend.pop(tid, None)
        if not item:
            return
        import changes
        changes.update(item["id"], path=item.get("changes"), user_response="approved")
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(pend, f)
        os.replace(tmp, p)
    except Exception:
        pass


def build(data, ddir, root):
    """回傳要寫入的紀錄（dict）或 None。"""
    ev = data.get("hook_event_name") or ""
    tool = data.get("tool_name") or ""
    base = {"ts": now(), "session": data.get("session_id"), "agent": agent_of(data)}
    if ev == "PostToolUse":
        resp = data.get("tool_response")
        rec = dict(base, signal="tool_ok", tool=tool, summary=tool_summary(tool, data.get("tool_input"), root),
                   out_chars=size_of(resp))
        if isinstance(resp, dict) and (resp.get("is_error") or resp.get("isError")):
            ev = "PostToolUseFailure"
        elif tool == "AskUserQuestion":
            ans = resp.get("answers") if isinstance(resp, dict) else None
            if isinstance(ans, dict) and ans:
                rec.update(signal="user_choice", summary=short("; ".join(f"{k} → {v}" for k, v in ans.items()), 200))
            return rec
        else:
            return rec
    if ev == "PostToolUseFailure":
        text = error_text(data)
        n = bump(os.path.join(ddir, "observe-state.json"), data.get("session_id"), signature(tool, text))
        rec = dict(base, signal="repeat_error" if n >= 2 else "tool_fail", tool=tool,
                   summary=tool_summary(tool, data.get("tool_input"), root), error=short(text, 160))
        if n >= 2:
            rec["count"] = n
        if data.get("is_interrupt"):
            rec["interrupted"] = True
        return rec
    if ev == "SubagentStop":
        msg = data.get("last_assistant_message") or ""
        return dict(base, signal="delegation_result", agent=agent_of(data) if data.get("agent_type") else "subagent",
                    summary=short(msg, 200), chars=len(msg) if isinstance(msg, str) else 0)
    if ev == "UserPromptSubmit":
        p = data.get("prompt") or ""
        if not isinstance(p, str):
            return None
        m = CORRECTION.search(p)
        if m:
            return dict(base, signal="user_correction", match=m.group(0), summary=short(p, 160), chars=len(p))
        if CHOICE.match(p):
            return dict(base, signal="user_choice", summary=short(p, 40), chars=len(p))
        return dict(base, signal="user_prompt", chars=len(p))
    return None


def append(rec, cwd=None):
    """寫入一筆紀錄（已關閉時不寫）。給 guard.py 這類其他 hook 用。"""
    if not enabled():
        return
    from projectid import project_data_dir
    ddir = project_data_dir(cwd)
    rec = {k: v for k, v in rec.items() if v not in (None, "")}
    path = os.path.join(ddir, "observations.jsonl")
    rotate(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def process(data):
    if not isinstance(data, dict):
        return
    from projectid import project_data_dir, project_info
    ddir = project_data_dir(data.get("cwd"), create=False)
    if data.get("hook_event_name") == "PostToolUse":
        resolve_guard(data, ddir)
    if not enabled():
        return
    ddir = project_data_dir(data.get("cwd"))
    root = project_info(data.get("cwd"))["root"]
    rec = build(data, ddir, root)
    if not rec:
        return
    rec = {k: v for k, v in rec.items() if v not in (None, "")}
    path = os.path.join(ddir, "observations.jsonl")
    rotate(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    try:
        process(json.load(sys.stdin))
    except Exception:
        return


if __name__ == "__main__":
    main()
