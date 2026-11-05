"""駕駛艙的共用小模組：白話翻譯、目前動作（activity）與本次 token 統計。

statusline.py、activity.py 與 trim 系列 hook 共用；agent-board 面板的 deck-logic.js 移植同一份翻譯規則。
只用標準函式庫；任何讀寫失敗都安靜略過，不能影響 Claude Code 本身。

activity 檔：~/.claude/chutora/activity/<session_id>.json
  running：{tool_use_id: {agent, model, tool, summary, start}}  目前在跑的動作
  last：最近一個完成的動作（多了 end、ok）
  agents：{agent_id: {type, model, start, end}}
  saved：{bash, dedup, mcp}  這個 session 擋在 context 外的字元數（估算 token 用 ÷4）
"""
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STALE_SEC = 30 * 60   # running 超過 30 分鐘沒收到結束事件就當作遺失
KEEP_FILES = 40        # activity 目錄最多保留幾個 session


def conf_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "chutora")


def act_dir():
    return os.path.join(conf_dir(), "activity")


def safe_sid(sid):
    s = re.sub(r"[^A-Za-z0-9_.-]", "", str(sid or ""))[:80]
    return s or None


# ---------------------------------------------------------------- 白話翻譯
def _base(p):
    p = str(p or "").rstrip("/")
    return os.path.basename(p) or p


def _short(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _strip_prefix(cmd):
    """去掉開頭的 cd xxx &&、環境變數設定、sudo、time，只看真正的指令。"""
    c = str(cmd or "").strip()
    for _ in range(6):
        m = re.match(r"^(cd\s+\S+\s*(&&|;)\s*)", c)
        if m:
            c = c[m.end():].strip(); continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*=\S*\s+)", c)
        if m:
            c = c[m.end():].strip(); continue
        m = re.match(r"^(sudo|time|exec|command|nohup)\s+", c)
        if m:
            c = c[m.end():].strip(); continue
        break
    return c


# (正規表示式, 中文, 英文)；依序比對指令開頭，第一個命中的就用
BASH_RULES = [
    (r"^(npm|pnpm|yarn|bun)\s+(i|install|ci|add)\b", "安裝套件", "Install packages"),
    (r"^(npm|pnpm|yarn|bun)\s+(run\s+)?test\b", "跑測試", "Run tests"),
    (r"^(npm|pnpm|yarn|bun)\s+(run\s+)?build\b", "建置", "Build"),
    (r"^(npm|pnpm|yarn|bun)\s+(run\s+)?lint\b", "檢查程式碼", "Lint"),
    (r"^(npm|pnpm|yarn|bun)\s+(run\s+)?(dev|start|serve)\b", "啟動開發伺服器", "Start dev server"),
    (r"^(npx\s+)?(pytest|jest|vitest|mocha|ava|rspec|phpunit)\b", "跑測試", "Run tests"),
    (r"^python3?\s+-m\s+(pytest|unittest)\b", "跑測試", "Run tests"),
    (r"^(go|cargo|dotnet|swift|mix|deno)\s+test\b", "跑測試", "Run tests"),
    (r"^(mvn|gradle|\./gradlew)\s+(\S+\s+)*test\b", "跑測試", "Run tests"),
    (r"^make\s+(test|check)\b", "跑測試", "Run tests"),
    (r"^(cargo|go|dotnet|swift)\s+build\b|^(npx\s+)?tsc\b|^make\b|^(mvn|gradle|\./gradlew)\b", "建置", "Build"),
    (r"^(pip3?|uv|poetry|pipx|brew|apt(-get)?|gem|cargo)\s+(install|add|sync)\b", "安裝套件", "Install packages"),
    (r"^(npx\s+)?(eslint|prettier|ruff|black|flake8|mypy|golangci-lint)\b", "檢查程式碼", "Lint"),
    (r"^git\s+status\b", "看 git 狀態", "Check git status"),
    (r"^git\s+diff\b", "看修改差異", "View changes"),
    (r"^git\s+(log|show)\b", "看提交紀錄", "View history"),
    (r"^git\s+add\b", "暫存修改", "Stage changes"),
    (r"^git\s+commit\b", "提交 commit", "Commit"),
    (r"^git\s+push\b", "推上遠端", "Push"),
    (r"^git\s+(pull|fetch)\b", "拉下遠端更新", "Pull updates"),
    (r"^git\s+(checkout|switch)\b", "切換分支", "Switch branch"),
    (r"^git\s+(branch)\b", "看分支", "List branches"),
    (r"^git\s+(merge|rebase)\b", "合併分支", "Merge branches"),
    (r"^git\s+clone\b", "下載 repo", "Clone repo"),
    (r"^git\s+stash\b", "暫存工作區", "Stash work"),
    (r"^docker\s+(build|buildx)\b", "建置容器映像", "Build image"),
    (r"^docker(-compose|\s+compose)?\s+(run|up|start)\b", "啟動容器", "Start containers"),
    (r"^(ls|tree|exa|eza)\b", "看資料夾內容", "List files"),
    (r"^(cat|head|tail|less|more|bat|nl)\b", "看檔案內容", "View a file"),
    (r"^(grep|rg|ag|ack)\b", "搜尋文字", "Search text"),
    (r"^(find|fd)\b", "找檔案", "Find files"),
    (r"^mkdir\b", "建立資料夾", "Create folder"),
    (r"^(rm|rmdir|unlink)\b", "刪除檔案", "Delete files"),
    (r"^mv\b", "移動檔案", "Move files"),
    (r"^cp\b", "複製檔案", "Copy files"),
    (r"^(curl|wget|http)\b", "連網抓資料", "Fetch from network"),
    (r"^sed\s+-i\b", "直接改檔案", "Edit a file in place"),
    (r"^(chmod|chown)\b", "改權限", "Change permissions"),
    (r"^(python3?|node|ruby|php|go\s+run|deno\s+run|bun\s+run|java)\b", "執行程式", "Run a program"),
    (r"^(echo|printf)\b", "輸出文字", "Print text"),
]
_BASH_RULES = [(re.compile(p), zh, en) for p, zh, en in BASH_RULES]

TOOL_PLAIN = {  # tool: (中文, 英文)，{x} 會換成對象
    "Read": ("讀 {x}", "Read {x}"),
    "Edit": ("修改 {x}", "Edit {x}"),
    "MultiEdit": ("修改 {x}", "Edit {x}"),
    "Write": ("寫入 {x}", "Write {x}"),
    "NotebookEdit": ("修改筆記本 {x}", "Edit notebook {x}"),
    "Glob": ("找檔案 {x}", "Find files {x}"),
    "WebFetch": ("讀網頁 {x}", "Read web page {x}"),
    "WebSearch": ("上網搜尋「{x}」", "Search the web for “{x}”"),
    "TodoWrite": ("更新待辦清單", "Update to-do list"),
    "TaskCreate": ("新增待辦", "Add a task"),
    "TaskUpdate": ("更新待辦", "Update a task"),
    "AskUserQuestion": ("問你問題", "Ask you a question"),
    "Skill": ("載入技能 {x}", "Load skill {x}"),
    "ToolSearch": ("載入工具", "Load tools"),
    "ExitPlanMode": ("提出計畫", "Propose a plan"),
    "EnterPlanMode": ("進入規劃模式", "Enter plan mode"),
    "LSP": ("查程式碼定義", "Look up code"),
    "SendUserMessage": ("傳訊息給你", "Message you"),
}


def plain(tool, inp, lng="zh"):
    """回傳 (白話, 原始摘要)。原始摘要給小字顯示；認不得的工具就用工具名稱。"""
    inp = inp if isinstance(inp, dict) else {}
    zh = lng != "en"
    tool = str(tool or "")
    try:
        if tool == "Bash":
            cmd = _strip_prefix(inp.get("command"))
            raw = _short(cmd, 60)
            for rx, z, e in _BASH_RULES:
                if rx.search(cmd):
                    return (z if zh else e), raw
            desc = inp.get("description")
            if isinstance(desc, str) and desc.strip() and not zh:
                return _short(desc, 40), raw
            return ("執行指令" if zh else "Run a command"), raw
        if tool == "Grep":
            pat, where = _short(inp.get("pattern"), 30), inp.get("path") or inp.get("glob")
            if where:
                where = _short(_base(where) if inp.get("path") else where, 24)
                return (f"在 {where} 裡找「{pat}」" if zh else f"Search {where} for “{pat}”"), f'Grep "{pat}" {where}'
            return (f"找「{pat}」" if zh else f"Search for “{pat}”"), f'Grep "{pat}"'
        if tool in ("Agent", "Task"):
            who = inp.get("subagent_type") or "general-purpose"
            who = str(who).split(":")[-1]
            desc = _short(inp.get("description"), 32)
            if zh:
                return (f"派工給 {who}：{desc}" if desc else f"派工給 {who}"), f"Agent {who}"
            return (f"Delegate to {who}: {desc}" if desc else f"Delegate to {who}"), f"Agent {who}"
        if tool.startswith("mcp__"):
            parts = tool.split("__")
            server = parts[1] if len(parts) > 1 else "MCP"
            name = parts[-1] if len(parts) > 2 else tool
            return (f"用 {server} 的 {name}" if zh else f"Use {server}: {name}"), tool
        if tool in TOOL_PLAIN:
            z, e = TOOL_PLAIN[tool]
            x = ""
            if tool in ("Read", "Edit", "MultiEdit", "Write"):
                x = _base(inp.get("file_path"))
                raw = f"{tool} {_short(inp.get('file_path'), 60)}"
            elif tool == "NotebookEdit":
                x = _base(inp.get("notebook_path"))
                raw = f"{tool} {_short(inp.get('notebook_path'), 60)}"
            elif tool == "Glob":
                x = _short(inp.get("pattern"), 30); raw = f"Glob {x}"
            elif tool == "WebFetch":
                m = re.match(r"^\w+://([^/]+)", str(inp.get("url") or ""))
                x = m.group(1) if m else _short(inp.get("url"), 30); raw = _short(inp.get("url"), 60)
            elif tool == "WebSearch":
                x = _short(inp.get("query"), 30); raw = f"WebSearch {x}"
            elif tool == "Skill":
                x = _short(inp.get("skill"), 30); raw = f"Skill {x}"
            else:
                raw = tool
            text = (z if zh else e).replace("{x}", x).replace("  ", " ").strip()
            if tool == "TodoWrite":
                todos = inp.get("todos") if isinstance(inp.get("todos"), list) else []
                done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
                if todos:
                    text += f"（{done}/{len(todos)}）" if zh else f" ({done}/{len(todos)})"
            return text, raw
    except Exception:
        pass
    return tool or "?", tool


# ---------------------------------------------------------------- agent 名稱與模型
MODEL_NAMES = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku", "fable": "Fable"}


def model_name(m):
    m = str(m or "").lower()
    for k, v in MODEL_NAMES.items():
        if k in m:
            return v
    return ""


def agent_model(agent_type):
    """從本 plugin 的 agents/<name>.md frontmatter 讀 model；讀不到回傳空字串（沿用主對話）。"""
    name = str(agent_type or "").split(":")[-1]
    if not re.match(r"^[A-Za-z0-9_-]+$", name):
        return ""
    for d in (os.path.join(HERE, "..", "agents"), os.path.join(os.path.expanduser("~"), ".claude", "agents")):
        p = os.path.join(d, name + ".md")
        try:
            with open(p, encoding="utf-8") as f:
                head = f.read(2000)
        except OSError:
            continue
        m = re.search(r"^model:\s*(\S+)", head, re.M)
        if m:
            return model_name(m.group(1))
    return ""


# ---------------------------------------------------------------- activity 檔
def _path(sid):
    s = safe_sid(sid)
    return os.path.join(act_dir(), s + ".json") if s else None


def load(sid):
    p = _path(sid)
    if not p:
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _locked_update(sid, fn):
    """讀改寫 activity 檔：fcntl 檔案鎖（沒有就直接寫）＋原子取代。"""
    p = _path(sid)
    if not p:
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    lockf = None
    try:
        try:
            import fcntl
            lockf = open(p + ".lock", "w")
            fcntl.flock(lockf, fcntl.LOCK_EX)
        except Exception:
            lockf = None
        st = load(sid)
        fn(st)
        st["updated"] = time.time()
        tmp = p + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, p)
    finally:
        if lockf:
            try:
                lockf.close()
            except Exception:
                pass


def prune_dir():
    try:
        files = [os.path.join(act_dir(), f) for f in os.listdir(act_dir()) if f.endswith(".json")]
        if len(files) <= KEEP_FILES:
            return
        files.sort(key=lambda f: os.path.getmtime(f))
        for f in files[:-KEEP_FILES]:
            for x in (f, f + ".lock", f[:-5] + ".tok.json"):
                try:
                    os.remove(x)
                except OSError:
                    pass
    except OSError:
        pass


def _who(st, data):
    aid = data.get("agent_id")
    if not aid:
        return "main", ""
    a = (st.get("agents") or {}).get(aid) or {}
    t = str(a.get("type") or data.get("agent_type") or "agent").split(":")[-1]
    return t, a.get("model") or agent_model(data.get("agent_type"))


def _summary(tool, inp):
    """存原始參數的精簡版（翻譯在顯示時依語言做）。"""
    inp = inp if isinstance(inp, dict) else {}
    keep = {}
    for k in ("command", "description", "file_path", "notebook_path", "pattern", "path", "glob", "url",
              "query", "subagent_type", "skill"):
        v = inp.get(k)
        if isinstance(v, str):
            keep[k] = v[:200]
    if tool == "TodoWrite" and isinstance(inp.get("todos"), list):
        keep["todos"] = [{"status": t.get("status")} for t in inp["todos"][:50] if isinstance(t, dict)]
    return keep


def on_event(data):
    ev = data.get("hook_event_name")
    sid = data.get("session_id")
    now = time.time()
    if ev == "SubagentStart":
        def f(st):
            ag = st.setdefault("agents", {})
            ag[str(data.get("agent_id"))] = {"type": str(data.get("agent_type") or "").split(":")[-1],
                                            "model": agent_model(data.get("agent_type")), "start": now}
            for k in sorted(ag, key=lambda k: ag[k].get("start", 0))[:-30]:
                del ag[k]
        _locked_update(sid, f)
    elif ev == "SubagentStop":
        def f(st):
            a = (st.get("agents") or {}).get(str(data.get("agent_id")))
            if a is not None:
                a["end"] = now
            run = st.get("running") or {}
            for k in [k for k, v in run.items() if v.get("agent_id") == data.get("agent_id")]:
                del run[k]
        _locked_update(sid, f)
    elif ev == "PreToolUse":
        tid = str(data.get("tool_use_id") or "")
        if not tid:
            return

        def f(st):
            who, model = _who(st, data)
            run = st.setdefault("running", {})
            for k in [k for k, v in run.items() if now - v.get("start", now) > STALE_SEC]:
                del run[k]
            run[tid] = {"agent": who, "model": model, "agent_id": data.get("agent_id"),
                        "tool": data.get("tool_name"), "summary": _summary(data.get("tool_name"), data.get("tool_input")),
                        "start": now}
        _locked_update(sid, f)
        prune_dir()
    elif ev in ("PostToolUse", "PostToolUseFailure"):
        tid = str(data.get("tool_use_id") or "")

        def f(st):
            run = st.setdefault("running", {})
            item = run.pop(tid, None)
            if item is None:
                who, model = _who(st, data)
                item = {"agent": who, "model": model, "tool": data.get("tool_name"),
                        "summary": _summary(data.get("tool_name"), data.get("tool_input")),
                        "start": now - (data.get("duration_ms") or 0) / 1000.0}
            item["end"] = now
            item["ok"] = ev == "PostToolUse"
            st["last"] = item
        _locked_update(sid, f)


def add_saved(sid, chars, kind="bash"):
    if not safe_sid(sid) or not chars:
        return

    def f(st):
        sv = st.setdefault("saved", {})
        sv[kind] = int(sv.get(kind, 0)) + int(chars)
    try:
        _locked_update(sid, f)
    except Exception:
        pass


def saved_chars(st):
    sv = st.get("saved") or {}
    return sum(int(v) for v in sv.values() if isinstance(v, (int, float)))


# ---------------------------------------------------------------- 本次 token（精確，來自 transcript 的 usage）
def _num(u, k):
    v = u.get(k, 0)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def session_tokens(transcript_path, sid):
    """本次 session 新處理的 token（input＋cache 寫入＋output，不含 cache 讀取），主對話＋子 agent。

    回傳 {"total": n, "by_model": {"Opus": n, ...}}；讀不到回傳 None。增量讀取（記住每個檔的位移）。
    同一則 API 回應在 transcript 會拆成多行、帶同一份 usage，以 (message.id, requestId) 去重。
    """
    tp = str(transcript_path or "")
    s = safe_sid(sid)
    if not tp or not s or not os.path.isfile(tp):
        return None
    files = [tp]
    sub = os.path.join(tp[:-6] if tp.endswith(".jsonl") else tp, "subagents")
    try:
        files += sorted(os.path.join(sub, f) for f in os.listdir(sub) if f.endswith(".jsonl"))
    except OSError:
        pass
    cache_p = os.path.join(act_dir(), s + ".tok.json")
    try:
        with open(cache_p, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    if cache.get("transcript") != tp:
        cache = {"transcript": tp, "files": {}}
    changed = False
    for fp in files:
        ent = cache["files"].get(fp) or {"off": 0, "by": {}, "recent": []}
        try:
            size = os.path.getsize(fp)
        except OSError:
            continue
        if size < ent["off"]:
            ent = {"off": 0, "by": {}, "recent": []}
        if size == ent["off"]:
            cache["files"][fp] = ent
            continue
        recent = list(ent.get("recent") or [])
        with open(fp, "rb") as f:
            f.seek(ent["off"])
            chunk = f.read(size - ent["off"])
        last_nl = chunk.rfind(b"\n")
        if last_nl < 0:
            continue
        for line in chunk[: last_nl + 1].splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message") if isinstance(d, dict) else None
            if not isinstance(m, dict) or d.get("type") != "assistant":
                continue
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            key = "%s|%s" % (m.get("id"), d.get("requestId"))
            if key in recent:
                continue
            recent = (recent + [key])[-64:]
            n = _num(u, "input_tokens") + _num(u, "cache_creation_input_tokens") + _num(u, "output_tokens")
            name = model_name(m.get("model")) or "?"
            ent["by"][name] = int(ent["by"].get(name, 0)) + int(n)
        ent["off"] += last_nl + 1
        ent["recent"] = recent
        cache["files"][fp] = ent
        changed = True
    if changed:
        try:
            os.makedirs(act_dir(), exist_ok=True)
            tmp = cache_p + ".%d.tmp" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp, cache_p)
        except OSError:
            pass
    by = {}
    for ent in cache["files"].values():
        for k, v in (ent.get("by") or {}).items():
            by[k] = by.get(k, 0) + v
    return {"total": sum(by.values()), "by_model": by}
