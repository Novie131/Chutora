#!/usr/bin/env python3
"""/chutora 的腳本：狀態總覽、安裝健檢、模式與語言切換。只用標準函式庫。

用法：chutora.py [status] | doctor | mode [economy|balanced|quality] | lang [zh|en|auto]
      | trim|dedup|mcp-trim [on|off] | mcp-trim exclude|include <server> | mcp-trim text on|off
      | ask [on|off] | guard [on|off|rules] | observe [on|off] | observe privacy [strict|normal]
      | changes [N] | ok <id|all> [auto|ask] | undo <id> | decide [on|off|stats]
status 與 doctor 唯讀；其他子指令只寫 ~/.claude/chutora/ 底下自己的設定檔。
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
CONF = os.path.join(CLAUDE, "chutora")
MODES = ("economy", "balanced", "quality")
MODE_NAMES = {"economy": ("省錢", "economy"), "balanced": ("平衡", "balanced"), "quality": ("品質", "quality")}


def hooks_dir():
    for d in (os.path.join(HERE, "..", "..", "hooks"), os.path.join(CLAUDE, "hooks", "chutora")):
        if os.path.isfile(os.path.join(d, "compact.py")):
            return os.path.abspath(d)
    return None


HOOKS = hooks_dir()
if HOOKS:
    sys.path.insert(0, HOOKS)
try:
    from compact import lang as _lang, remind_tokens, compact_point
except Exception:
    _lang = lambda: "en"  # noqa: E731
    remind_tokens = lambda: 100000  # noqa: E731
    compact_point = lambda: None  # noqa: E731

L = _lang()


def T(zh, en):
    return zh if L == "zh" else en


def install_kind():
    """plugin（市集安裝）／install.sh（複製）／install.sh --link（符號連結）／repo（--plugin-dir 載入）"""
    p = os.path.realpath(HERE)
    if p.startswith(os.path.realpath(os.path.join(CLAUDE, "plugins")) + os.sep):
        return "plugin"
    if p.startswith(os.path.realpath(os.path.join(CLAUDE, "skills")) + os.sep):
        return "install.sh"
    link = os.path.join(CLAUDE, "skills", os.path.basename(HERE))
    if os.path.islink(link) and os.path.realpath(link) == p:
        return "install.sh --link"
    return "repo"


def namespaced():
    return install_kind() in ("plugin", "repo")


def version():
    pj = os.path.join(HERE, "..", "..", ".claude-plugin", "plugin.json")
    try:
        with open(pj) as f:
            return json.load(f).get("version") or "?"
    except Exception:
        return "?"


def read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def get_mode():
    m = re.sub(r"[^a-z]", "", read_text(os.path.join(CONF, "mode")))
    return m if m in MODES else "balanced"


def settings():
    try:
        with open(os.path.join(CLAUDE, "settings.json")) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def state_dirs():
    dirs = []
    if os.environ.get("CLAUDE_PLUGIN_DATA"):
        dirs.append(os.environ["CLAUDE_PLUGIN_DATA"])
    dirs += sorted(glob.glob(os.path.join(CLAUDE, "plugins", "data", "*chutora*")))
    dirs.append(os.path.join(CLAUDE, "hooks"))
    return [d for d in dirs if os.path.isdir(d)]


def newest(paths):
    paths = [p for p in paths if os.path.isfile(p)]
    return max(paths, key=os.path.getmtime) if paths else None


def project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def current_transcript():
    root = os.path.join(CLAUDE, "projects")
    enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_dir()))
    t = newest(glob.glob(os.path.join(root, enc, "*.jsonl")))
    return t or newest(glob.glob(os.path.join(root, "*", "*.jsonl")))


def last_context(path):
    last, seen = None, set()
    try:
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
                last = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0))
    except OSError:
        return None
    return last


def loop_status(session_id):
    repeat = int(os.environ.get("LOOP_GUARD_REPEAT") or 3)
    p = newest([os.path.join(d, ".loop-guard-state.json") for d in state_dirs()])
    if not p:
        return None
    try:
        with open(p) as f:
            st = json.load(f)
    except Exception:
        return None
    sess = st.get(session_id) if session_id else None
    if not isinstance(sess, dict):
        return (0, 0)
    counts = [c for c in (sess.get("sigs") or {}).values() if isinstance(c, int) and c >= repeat]
    return (len(counts), max(counts) if counts else 0)


def trim_state():
    """回傳 (是否開啟, 原因, 累計瘦身字元數, 門檻說明)。"""
    on, why = True, ""
    if os.environ.get("CHUTORA_TRIM", "").strip() == "0":
        on, why = False, "CHUTORA_TRIM=0"
    elif read_text(os.path.join(CONF, "trim")).strip().lower() == "off":
        on, why = False, "/chutora trim off"
    chars = 0
    try:
        with open(os.path.join(CONF, "trim-stats.json")) as f:
            chars = int(json.load(f).get("total_chars", 0))
    except (OSError, ValueError, TypeError):
        pass
    th = {"economy": (3000, 80), "balanced": (4000, 120), "quality": (8000, 250)}[get_mode()]
    return on, why, chars, th


TOGGLES = {  # 子指令 → (設定檔名, 環境變數, 中文名, 英文名)
    "trim": ("trim", "CHUTORA_TRIM", "噪音輸出瘦身", "Noisy-output trimming"),
    "dedup": ("dedup", "CHUTORA_DEDUP", "讀檔去重", "Read dedup"),
    "mcp-trim": ("mcp-trim", "CHUTORA_MCP_TRIM", "MCP 輸出瘦身", "MCP output trimming"),
    "ask": ("ask", "CHUTORA_ASK", "反問提醒", "Clarify reminders"),
    "guard": ("guard", "CHUTORA_GUARD", "危險守門", "Danger guard"),
    "observe": ("observe", "CHUTORA_OBSERVE", "觀察紀錄", "Observation log"),
    "decide": ("decide", "CHUTORA_DECIDE", "決策引擎自動執行", "Decision engine auto-run"),
}
ASK_MAX = {"economy": 3, "balanced": 4, "quality": 5}


def toggle_state(name):
    fname, env, _, _ = TOGGLES[name]
    if os.environ.get(env, "").strip() == "0":
        return False, f"{env}=0"
    if read_text(os.path.join(CONF, fname)).strip().lower() == "off":
        return False, f"/chutora {name} off"
    return True, ""


def saved_kinds():
    try:
        with open(os.path.join(CONF, "trim-stats.json")) as f:
            st = json.load(f)
        k = st.get("kinds") or {}
        total = int(st.get("total_chars", 0))
        known = sum(int(v) for v in k.values())
        k = {key: int(v) for key, v in k.items()}
        if total > known:  # 0.13 以前只記合計，都是 Bash 瘦身
            k["bash"] = k.get("bash", 0) + total - known
        return k
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def cmd(name):
    return f"/chutora:{name}" if namespaced() else f"/{name}"


def hook_mod(name):
    """載入 hooks/ 底下的模組（guard、projectid、changes、mcptrim）；載不到回傳 None。"""
    if not HOOKS:
        return None
    try:
        import importlib
        return importlib.import_module(name)
    except Exception:
        return None


def guard_info():
    """回傳 (預設規則數, 停用的預設規則, 使用者規則數, 壞掉的行, 最近 7 天攔下幾次)。"""
    g = hook_mod("guard")
    if not g:
        return None
    off, extra, bad = g.user_rules()
    recent = 0
    ch = hook_mod("changes")
    if ch:
        import time
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
        recent = sum(1 for x in ch.read(project_dir=project_dir()) if str(x.get("action", "")).startswith("guard_")
                     and str(x.get("ts", ""))[:10] >= cutoff)
    return len(g.RULES), sorted(off & set(g.RULES)), len(extra), bad, recent


def observe_info():
    """回傳 (observations.jsonl 路徑, 大小 bytes 或 None)；唯讀，不建立目錄。"""
    pid = hook_mod("projectid")
    if not pid:
        return None
    try:
        d = pid.project_data_dir(project_dir(), create=False)
    except Exception:
        return None
    p = os.path.join(d, "observations.jsonl")
    return p, (os.path.getsize(p) if os.path.isfile(p) else None)


def decide_info():
    """決策引擎：待確認數、決策筆數、平均 Brier、復原點目錄；唯讀，不建立目錄。"""
    d = hook_mod("decide")
    pid = hook_mod("projectid")
    if not d or not pid:
        return None
    try:
        pd = project_dir()
        st = d.stats(d.load_decisions(pd))
        rr = os.path.join(pid.project_data_dir(pd, create=False), "restore")
        return {"pending": len(d.pending(pd)), "decisions": st["decisions"], "resolved": st["resolved"],
                "brier": st["brier"], "restore_dir": rr}
    except Exception:
        return None


def observe_privacy():
    """回傳 ("strict"|"normal", 來源)。和 hooks/observe.py 的 privacy() 同一套規則。"""
    v = os.environ.get("CHUTORA_OBSERVE_PRIVACY", "").strip().lower()
    if v in ("strict", "normal"):
        return v, "CHUTORA_OBSERVE_PRIVACY=" + v
    if read_text(os.path.join(CONF, "observe-privacy")).lower() == "strict":
        return "strict", "/chutora observe privacy strict"
    return "normal", ""


def privacy_label(level):
    return (T("嚴格（糾正與選擇只記長度）", "strict (corrections and choices: length only)") if level == "strict"
            else T("一般（糾正存前 160 字、已遮罩）", "normal (corrections: first 160 chars, masked)"))


def mcp_excludes():
    m = hook_mod("mcptrim")
    try:
        return m.exclude_patterns() if m else []
    except Exception:
        return []


# ------------------------------------------------------------------ status
def status():
    mode = get_mode()
    zh_m, en_m = MODE_NAMES[mode]
    print(T("Chutora 狀態", "Chutora status"))
    print(T(f"- 版本：{version()}（{install_kind()}）", f"- Version: {version()} ({install_kind()})"))
    print(T(f"- 模式：{zh_m}（{mode}）", f"- Mode: {en_m}"))
    print(T("- 語言：中文", "- Language: English"))
    tr = current_transcript()
    ctx = last_context(tr) if tr else None
    remind = remind_tokens()
    cp = compact_point()
    if ctx is None:
        print(T("- 目前對話 context：讀不到紀錄", "- Current context: no transcript found"))
    else:
        extra = T(f"，約 {cp // 1000}k 自動壓縮", f", auto-compact around {cp // 1000}k") if cp else ""
        print(T(f"- 目前對話 context：約 {ctx // 1000}k（{remind // 1000}k 提醒{extra}）",
                f"- Current context: about {ctx // 1000}k (reminder at {remind // 1000}k{extra})"))
    sid = os.path.basename(tr)[:-6] if tr else None
    ls = loop_status(sid)
    if ls is None:
        print(T("- loop guard：還沒有紀錄", "- Loop guard: no record yet"))
    elif ls[0]:
        print(T(f"- loop guard：這個對話有 {ls[0]} 種錯誤重複出現（最多 {ls[1]} 次），可能卡住了",
                f"- Loop guard: {ls[0]} error(s) keep repeating in this conversation (up to {ls[1]} times); you may be stuck"))
    else:
        print(T("- loop guard：這個對話沒有偵測到重複錯誤", "- Loop guard: no repeating errors in this conversation"))
    on, why, chars, th = trim_state()
    saved = T(f"，累計瘦身約 {chars // 4:,} token（估算：字元數÷4）", f"; trimmed about {chars // 4:,} tokens so far (estimate: characters ÷ 4)") if chars else ""
    if on:
        print(T(f"- 噪音輸出瘦身：開啟（超過 {th[0]} 字元或 {th[1]} 行的安裝／建置／測試輸出才處理）{saved}",
                f"- Noisy-output trimming: on (install/build/test output over {th[0]} chars or {th[1]} lines){saved}"))
    else:
        print(T(f"- 噪音輸出瘦身：關閉（{why}）{saved}", f"- Noisy-output trimming: off ({why}){saved}"))
    k = saved_kinds()
    for name, kind in (("dedup", "dedup"), ("mcp-trim", "mcp")):
        on2, why2 = toggle_state(name)
        zh_n, en_n = TOGGLES[name][2], TOGGLES[name][3]
        extra = T(f"，累計約 {k.get(kind, 0) // 4:,} token（估算）", f"; about {k.get(kind, 0) // 4:,} tokens so far (estimate)") if k.get(kind) else ""
        print(T(f"- {zh_n}：{'開啟' if on2 else '關閉（' + why2 + '）'}{extra}", f"- {en_n}: {'on' if on2 else 'off (' + why2 + ')'}{extra}"))
    on3, why3 = toggle_state("ask")
    n = ASK_MAX[mode]
    print(T(f"- 反問：{'開啟' if on3 else '關閉（' + why3 + '）'}（大任務且模糊、或你說不確定時先問，最多 {n} 題；/chutora ask 可強制先問）",
            f"- Clarify: {'on' if on3 else 'off (' + why3 + ')'} (asks first, up to {n} questions, on big vague tasks or when you're unsure; /chutora ask forces it)"))
    ex = mcp_excludes()
    text_on = os.environ.get("CHUTORA_MCP_TRIM_TEXT", "").strip() == "1" or read_text(os.path.join(CONF, "mcp-trim-text")).lower() == "on"
    print(T(f"  MCP 瘦身只處理 JSON 長陣列與重複項；純文字／Markdown {'也會瘦身（mcp-trim text on）' if text_on else '不動'}；"
            f"排除：{', '.join(ex) if ex else '無'}",
            f"  MCP trimming only touches long JSON lists and repeats; plain text / Markdown {'is trimmed too (mcp-trim text on)' if text_on else 'is left alone'}; "
            f"excluded: {', '.join(ex) if ex else 'none'}"))
    on4, why4 = toggle_state("guard")
    gi = guard_info()
    if gi:
        n_rules, off_rules, n_user, bad, recent = gi
        extra = T(f"；預設 {n_rules} 條{'、停用 ' + ','.join(off_rules) if off_rules else ''}、你的規則 {n_user} 條、近 7 天攔下 {recent} 次",
                  f"; {n_rules} default rules{', disabled: ' + ','.join(off_rules) if off_rules else ''}, {n_user} of yours, {recent} stopped in the last 7 days")
    else:
        extra = ""
    print(T(f"- 危險守門（實驗中）：{'開啟' if on4 else '關閉（' + why4 + '）'}（force push、rm -rf 專案外、碰 .env 等先問你；rm -rf ~ 這類直接擋；略過權限模式下備份不了的也直接擋）{extra}",
            f"- Danger guard (experimental): {'on' if on4 else 'off (' + why4 + ')'} (asks before force push, rm -rf outside the project, touching .env…; blocks rm -rf ~ and the like, and in bypass-permissions mode also what a backup can't undo){extra}"))
    on5, why5 = toggle_state("observe")
    oi = observe_info()
    size = T(f"，{oi[1] // 1024:,} KB", f", {oi[1] // 1024:,} KB") if oi and oi[1] else ""
    where = (oi[0].replace(HOME, "~") if oi else "~/.claude/chutora/projects/<id>/observations.jsonl")
    pv, pv_why = observe_privacy()
    pv_txt = privacy_label(pv) + (f" [{pv_why}]" if pv_why else "")
    print(T(f"- 觀察紀錄（實驗中）：{'開啟' if on5 else '關閉（' + why5 + '）'}（不花 token，記在 {where}{size}；隱私：{pv_txt}）",
            f"- Observation log (experimental): {'on' if on5 else 'off (' + why5 + ')'} (costs no tokens; kept in {where}{size}; privacy: {pv_txt})"))
    on6, why6 = toggle_state("decide")
    di = decide_info()
    dx = ""
    if di:
        dx = T(f"；待確認 {di['pending']} 個、決策 {di['decisions']} 筆", f"; {di['pending']} to confirm, {di['decisions']} decisions") + (
            f"、Brier {di['brier']}" if di.get("brier") is not None else "")
    print(T(f"- 決策引擎（實驗中）：{'開啟' if on6 else '關閉（' + why6 + '）'}（你說過「這類以後可以自動」且可復原時，先建復原點再自動做並通知；/chutora changes 查看）{dx}",
            f"- Decision engine (experimental): {'on' if on6 else 'off (' + why6 + ')'} (when you said a kind may be automatic and it is recoverable, it saves a restore point, does it and tells you; see /chutora changes){dx}"))
    print()
    print(T("可以做的事（直接回覆編號或名稱）：", "What you can do (reply with a number or name):"))
    items = [
        ("/chutora ask", "先把需求問清楚再動手（最多 3–5 題選擇題）", "clarify the task first (3–5 multiple-choice questions)"),
        (cmd("handoff"), "寫交接筆記，之後可以放心 /clear", "write a handoff note so you can /clear safely"),
        (cmd("usage-stats"), "看用量與估計金額報表", "usage and estimated cost report"),
        ("/chutora doctor", "安裝健檢，壞了告訴你怎麼修", "install check, with fixes"),
        ("/chutora mode economy|balanced|quality", "切換模式：省錢／平衡／品質", "switch mode: economy / balanced / quality"),
        ("/chutora lang zh|en|auto", "切換提醒訊息語言", "switch the language of messages"),
        (cmd("harness-tune"), "讓某類任務越做越順", "make a recurring kind of task go smoother"),
        (cmd("toolprune"), "找出沒用到的工具來省 token", "find unused tools to save tokens"),
        (cmd("route-setup"), "完整設定：狀態列、自動壓縮、記憶庫", "full setup: status line, auto-compact, memory"),
        ("/chutora trim on|off", "噪音輸出瘦身開關（原文存在 ~/.claude/chutora/raw/）", "turn noisy-output trimming on/off (originals kept in ~/.claude/chutora/raw/)"),
        ("/chutora dedup on|off", "讀檔去重開關（同一段對話重讀沒變的檔案不再重送）", "turn read dedup on/off (unchanged re-reads aren't sent again)"),
        ("/chutora mcp-trim on|off", "MCP 輸出瘦身開關（只瘦 JSON 長陣列與重複項）", "turn MCP output trimming on/off (long JSON lists and repeats only)"),
        ("/chutora mcp-trim exclude|include <server>", "某個 MCP server 完全不瘦身／恢復", "never trim one MCP server / undo"),
        ("/chutora guard on|off|rules", "危險守門開關與規則清單（實驗中）", "danger guard switch and rule list (experimental)"),
        ("/chutora observe on|off", "觀察紀錄開關（實驗中）", "observation log switch (experimental)"),
        ("/chutora observe privacy strict|normal", "觀察紀錄隱私：strict 時你的糾正與選擇只記長度", "observation privacy: strict keeps only the length of your corrections and choices"),
    ]
    for i, (c, zh, en) in enumerate(items, 1):
        print(f"{i}. {c} — {T(zh, en)}")


# ------------------------------------------------------------------ doctor
def doctor():
    rows = []  # (level, item, detail, fix)
    OK, OPT, FIX = "ok", "optional", "fix"

    def add(level, item, detail, fix=""):
        rows.append((level, item, detail, fix))

    v = sys.version_info
    add(OK if v >= (3, 8) else FIX, "python3", f"{v.major}.{v.minor}.{v.micro}",
        T("請升級到 Python 3.8 以上", "Upgrade to Python 3.8 or later") if v < (3, 8) else "")

    s = settings()
    kind = install_kind()
    hooks_json = json.dumps(s.get("hooks") or {})
    if namespaced():
        enabled = s.get("enabledPlugins") or {}
        off = [k for k, val in enabled.items() if k.startswith("chutora@") and val is False]
        if off:
            add(FIX, "hooks", T("plugin 已安裝但被停用", "the plugin is installed but disabled"),
                T("執行 /plugin，把 chutora 重新啟用", "Run /plugin and enable chutora again"))
        else:
            add(OK, "hooks", T("由 plugin 自動註冊", "registered by the plugin") + ("" if kind == "plugin" else T("（--plugin-dir 載入）", " (loaded with --plugin-dir)")))
    else:
        need = {"session-start.sh": "SessionStart", "context-check.py": "UserPromptSubmit", "post-tool.py": "PostToolUse",
                "trim.py": "PostToolUse (Bash: trim)", "dedup.py": "PostToolUse (Read: dedup)",
                "mcptrim.py": "PostToolUse (mcp__: MCP trim)", "ask.py": "UserPromptSubmit (ask)",
                "activity.py": "PreToolUse/PostToolUse (activity)", "guard.py": "PreToolUse (guard)",
                "observe.py": "PostToolUse/PostToolUseFailure/SubagentStop/UserPromptSubmit (observe)"}
        missing = [ev for f, ev in need.items() if f not in hooks_json]
        if missing:
            add(FIX, "hooks", T("settings.json 缺少：", "missing in settings.json: ") + ", ".join(missing),
                T("重跑 bash install.sh，把它印出的 hooks 片段合併進 ~/.claude/settings.json",
                  "Re-run bash install.sh and merge the hooks snippet it prints into ~/.claude/settings.json"))
        else:
            add(OK, "hooks", T("settings.json 已設定", "configured in settings.json"))
    usage = newest([os.path.join(d, ".tool-usage.json") for d in state_dirs()])
    if usage:
        import time
        days = (time.time() - os.path.getmtime(usage)) / 86400
        add(OK if days < 7 else OPT, T("hook 觸發紀錄", "hook activity"),
            T(f"{days:.0f} 天前有紀錄", f"last recorded {days:.0f} day(s) ago"),
            "" if days < 7 else T("最近沒有紀錄；確認 hooks 有啟用", "Nothing recent; check that the hooks are enabled"))
    else:
        add(OPT, T("hook 觸發紀錄", "hook activity"), T("還沒有紀錄", "no record yet"),
            T("用一陣子後再跑一次健檢；一直沒有紀錄代表 hooks 沒在跑", "Check again after some use; no record at all means the hooks aren't running"))

    sl = json.dumps(s.get("statusLine") or "")
    if "statusline.py" in sl:
        add(OK, T("狀態列", "status line"), T("已設定", "configured"))
    else:
        add(OPT, T("狀態列", "status line"), T("未設定（選用）", "not set (optional)"), T(f"執行 {cmd('route-setup')}", f"Run {cmd('route-setup')}"))

    w = s.get("autoCompactWindow")
    if isinstance(w, int) and not isinstance(w, bool):
        add(OK, "autoCompactWindow", str(w))
    else:
        add(OPT, "autoCompactWindow", T("未設定（選用）", "not set (optional)"), T(f"執行 {cmd('route-setup')}", f"Run {cmd('route-setup')}"))

    mem = os.path.join(project_dir(), "claude-memory")
    add(OK if os.path.isdir(mem) else OPT, "claude-memory",
        mem if os.path.isdir(mem) else T("這個專案沒有（選用，會退回 auto memory）", "none in this project (optional; falls back to auto memory)"),
        "" if os.path.isdir(mem) else T(f"執行 {cmd('route-setup')}", f"Run {cmd('route-setup')}"))

    ex = os.path.join(CLAUDE, "agents", "Explore.md")
    ex_text = read_text(ex)
    if re.search(r"^model:\s*haiku", ex_text, re.M):
        add(OK, "Haiku Explore", T("已安裝", "installed"))
    else:
        add(OPT, "Haiku Explore", T("未安裝（選用，內建 Explore 會跟著跑 Opus）", "not installed (optional; the built-in Explore runs on Opus)"),
            T(f"執行 {cmd('route-setup')}", f"Run {cmd('route-setup')}"))

    legacy = [p for p in (os.path.join(CLAUDE, ".smart-agent-route-installed"), os.path.join(CLAUDE, "hooks", "smart-agent-route"),
                          os.path.join(CLAUDE, "smart-agent-route")) if os.path.exists(p)]
    if "smart-agent-route" in hooks_json or "smart-agent-route" in sl:
        legacy.append("settings.json")
    if any(k.startswith("smart-agent-route@") for k in (s.get("enabledPlugins") or {})):
        legacy.append("enabledPlugins: smart-agent-route")
    if legacy:
        add(FIX, T("舊版 smart-agent-route", "old smart-agent-route"), ", ".join(p.replace(HOME, "~") for p in legacy),
            T("照 docs/部署安裝.md「從 smart-agent-route 升級」移除舊版；settings.json 的路徑改成 chutora",
              "Remove the old version as described in docs (upgrading from smart-agent-route); point settings.json paths to chutora"))
    else:
        add(OK, T("舊版 smart-agent-route", "old smart-agent-route"), T("沒有殘留", "nothing left over"))

    gi = guard_info()
    if gi is None:
        add(OPT, T("危險守門", "danger guard"), T("找不到 guard.py", "guard.py not found"))
    else:
        bad = gi[3]
        on_g, why_g = toggle_state("guard")
        if bad:
            add(FIX, T("危險守門", "danger guard"),
                T(f"~/.claude/chutora/always-ask 有 {len(bad)} 行不是有效的 regex（已略過）：", f"{len(bad)} line(s) in ~/.claude/chutora/always-ask are not valid regex (skipped): ")
                + " | ".join(b.strip() for b in bad[:3]),
                T("修正或刪掉那幾行；每行一個 regex，! 開頭表示移除預設規則", "Fix or remove those lines; one regex per line, ! to remove a default rule"))
        else:
            add(OK if on_g else OPT, T("危險守門", "danger guard"),
                (T("開啟", "on") if on_g else T(f"關閉（{why_g}）", f"off ({why_g})")) +
                T(f"，你的規則 {gi[2]} 條", f", {gi[2]} rule(s) of yours"),
                "" if on_g else T("/chutora guard on 重新開啟", "Turn it back on with /chutora guard on"))
    oi = observe_info()
    if oi:
        d = os.path.dirname(oi[0])
        probe = d if os.path.isdir(d) else CONF if os.path.isdir(CONF) else CLAUDE
        writable = os.access(probe, os.W_OK)
        big = oi[1] is not None and oi[1] > 6 * 1024 * 1024
        add(OK if writable and not big else FIX, T("觀察紀錄", "observation log"),
            oi[0].replace(HOME, "~") + (T(f"（{oi[1] // 1024:,} KB）", f" ({oi[1] // 1024:,} KB)") if oi[1] else T("（還沒有紀錄）", " (nothing yet)"))
            + T(f"；隱私：{privacy_label(observe_privacy()[0])}", f"; privacy: {privacy_label(observe_privacy()[0])}"),
            "" if writable and not big else (T(f"{probe} 不能寫入", f"{probe} is not writable") if not writable
                                              else T("超過 5 MB 卻沒有輪替；確認 observe.py 是新版", "Over 5 MB without rotating; check observe.py is up to date")))

    di = decide_info()
    if not di:
        add(FIX, T("決策引擎", "decision engine"), T("找不到 decide.py", "decide.py not found"),
            T("hooks 版本太舊：重新安裝或更新 plugin", "hooks are out of date: reinstall or update the plugin"))
    else:
        rr = di["restore_dir"]
        ok_w = os.access(rr if os.path.isdir(rr) else (os.path.dirname(rr) if os.path.isdir(os.path.dirname(rr)) else CLAUDE), os.W_OK)
        add(OK if ok_w else FIX, T("決策引擎", "decision engine"),
            T(f"待確認 {di['pending']} 個、決策 {di['decisions']} 筆（已知結果 {di['resolved']}）", f"{di['pending']} to confirm, {di['decisions']} decisions ({di['resolved']} resolved)")
            + (f"、Brier {di['brier']}" if di.get("brier") is not None else "") + T(f"；復原點在 {rr.replace(HOME, '~')}", f"; restore points in {rr.replace(HOME, '~')}"),
            "" if ok_w else T(f"{rr} 不能寫入：自動執行會因為建不了復原點而停用", f"{rr} is not writable: auto-run stays off because restore points can't be saved"))

    add(OK, T("版本", "version"), f"{version()} ({kind})")

    mark = {OK: T("正常", "OK"), OPT: T("選用", "optional"), FIX: T("要修", "FIX")}
    print(T("Chutora 健檢（唯讀，不會改任何設定）", "Chutora doctor (read-only, changes nothing)"))
    for level, item, detail, fix in rows:
        line = f"[{mark[level]}] {item}：{detail}" if L == "zh" else f"[{mark[level]}] {item}: {detail}"
        print(line)
        if fix:
            print(("    → " + fix))
    n_fix = sum(1 for r in rows if r[0] == FIX)
    print()
    print(T(f"結果：{n_fix} 項要修。" if n_fix else "結果：沒有要修的項目。",
            f"Result: {n_fix} item(s) to fix." if n_fix else "Result: nothing to fix."))
    return 1 if n_fix else 0


# ------------------------------------------------------------------ mode / lang
def write_conf(name, value):
    os.makedirs(CONF, exist_ok=True)
    p = os.path.join(CONF, name)
    if value is None:
        if os.path.exists(p):
            os.remove(p)
        return
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(value + "\n")
    os.replace(tmp, p)


def mode(arg):
    if not arg:
        m = get_mode()
        print(T(f"目前模式：{MODE_NAMES[m][0]}（{m}）。可選 economy（省錢）、balanced（平衡）、quality（品質）。",
                f"Current mode: {m}. Choices: economy, balanced, quality."))
        return 0
    alias = {"省錢": "economy", "平衡": "balanced", "品質": "quality", "eco": "economy", "save": "economy"}
    m = alias.get(arg, arg.lower())
    if m not in MODES:
        print(T(f"不認得的模式：{arg}。可選 economy、balanced、quality。", f"Unknown mode: {arg}. Choices: economy, balanced, quality."))
        return 2
    write_conf("mode", m)
    print(T(f"已切換到「{MODE_NAMES[m][0]}」模式（寫入 ~/.claude/chutora/mode）。新對話開始時生效；改回預設：/chutora mode balanced。",
            f"Switched to {m} mode (saved to ~/.claude/chutora/mode). Takes effect when a new conversation starts; back to default: /chutora mode balanced."))
    return 0


def set_lang(arg):
    global L
    if not arg:
        print(T("目前語言：中文。可選 zh、en、auto（依系統語言）。", "Current language: English. Choices: zh, en, auto (follow the system locale)."))
        return 0
    a = arg.lower()
    if a not in ("zh", "en", "auto"):
        print(T(f"不認得的語言：{arg}。可選 zh、en、auto。", f"Unknown language: {arg}. Choices: zh, en, auto."))
        return 2
    write_conf("lang", None if a == "auto" else a)
    L = _lang()
    print(T("已設定：提醒訊息用中文（寫入 ~/.claude/chutora/lang）。", "Done: messages will be in English (saved to ~/.claude/chutora/lang).")
          if a != "auto" else T("已改回依系統語言。", "Back to following the system locale."))
    return 0


def trim(arg):
    a = (arg or "").strip().lower()
    if not a:
        on, why, chars, th = trim_state()
        state = T("開啟", "on") if on else T(f"關閉（{why}）", f"off ({why})")
        print(T(f"噪音輸出瘦身：{state}。累計瘦身約 {chars // 4:,} token（估算）。可用 /chutora trim on|off 切換。",
                f"Noisy-output trimming: {state}. About {chars // 4:,} tokens trimmed so far (estimate). Switch with /chutora trim on|off."))
        return 0
    if a in ("on", "開", "開啟"):
        write_conf("trim", None)
        print(T("已開啟噪音輸出瘦身（下一次指令就生效）。", "Noisy-output trimming is on (takes effect on the next command)."))
        if os.environ.get("CHUTORA_TRIM", "").strip() == "0":
            print(T("注意：環境變數 CHUTORA_TRIM=0 仍會讓它保持關閉。", "Note: the CHUTORA_TRIM=0 environment variable still keeps it off."))
        return 0
    if a in ("off", "關", "關閉"):
        write_conf("trim", "off")
        print(T("已關閉噪音輸出瘦身（寫入 ~/.claude/chutora/trim）。之後指令輸出都會完整進到對話；改回：/chutora trim on。",
                "Noisy-output trimming is off (saved to ~/.claude/chutora/trim). Command output now reaches the conversation in full; undo: /chutora trim on."))
        return 0
    print(T(f"不認得的設定：{arg}。可用 on、off。", f"Unknown value: {arg}. Use on or off."))
    return 2


def toggle(name, arg):
    fname, env, zh_n, en_n = TOGGLES[name]
    a = (arg or "").strip().lower()
    if not a:
        on, why = toggle_state(name)
        state = T("開啟", "on") if on else T(f"關閉（{why}）", f"off ({why})")
        print(T(f"{zh_n}：{state}。可用 /chutora {name} on|off 切換。", f"{en_n}: {state}. Switch with /chutora {name} on|off."))
        return 0
    if a in ("on", "開", "開啟"):
        write_conf(fname, None)
        print(T(f"已開啟{zh_n}（馬上生效）。", f"{en_n} is on (takes effect right away)."))
        if os.environ.get(env, "").strip() == "0":
            print(T(f"注意：環境變數 {env}=0 仍會讓它保持關閉。", f"Note: the {env}=0 environment variable still keeps it off."))
        return 0
    if a in ("off", "關", "關閉"):
        write_conf(fname, "off")
        print(T(f"已關閉{zh_n}（寫入 ~/.claude/chutora/{fname}）；改回：/chutora {name} on。",
                f"{en_n} is off (saved to ~/.claude/chutora/{fname}); undo: /chutora {name} on."))
        return 0
    print(T(f"不認得的設定：{arg}。可用 on、off。", f"Unknown value: {arg}. Use on or off."))
    return 2


def ask(arg):
    """沒有參數：印出反問步驟給主對話照做；on|off：開關自動反問提醒。"""
    a = (arg or "").strip().lower()
    if a in ("status", "狀態"):
        return toggle("ask", "")
    if a:
        return toggle("ask", arg)
    n = ASK_MAX[get_mode()]
    print(T("反問（先把需求問清楚再動手）：", "Clarify first:"))
    print(T(f"1. 用 AskUserQuestion 一次問最多 {n} 題，每題第一個選項是建議選項，並提供「照預設、別問了」。",
            f"1. Use AskUserQuestion: at most {n} questions; put the recommended option first and offer \"use the defaults, stop asking\"."))
    print(T("2. 只問會改變結果的：範圍（做／不做）、怎樣算完成、限制（不能動什麼）、邊界情況、取捨（快還是完整）。已經講清楚的不要再問。",
            "2. Only ask what changes the result: scope (in / out), what counts as done, constraints (what must not change), edge cases, trade-offs (fast vs complete). Don't re-ask what is already clear."))
    print(T("3. 答案寫成精簡任務說明 claude-memory/briefs/<日期>-<slug>.md（沒有 claude-memory 時放 auto memory 目錄的 briefs/），欄位：目標、範圍、驗收標準、限制、邊界情況、取捨。",
            "3. Write the answers into a short brief, claude-memory/briefs/<date>-<slug>.md (or briefs/ in the auto memory folder): goal, scope, acceptance criteria, constraints, edge cases, trade-offs."))
    print(T("4. 派工時把這份說明附給 worker；「怎樣算完成」就是驗收標準。", "4. Attach the brief when delegating; \"what counts as done\" is the acceptance criteria."))
    return 0


def mcp_sub(action, arg):
    """mcp-trim exclude|include <server>、mcp-trim text on|off。寫檔前備份成 .bak。"""
    path = os.path.join(CONF, "mcp-trim-exclude")
    if action == "text":
        a = arg.lower()
        if a in ("on", "off"):
            write_conf("mcp-trim-text", "on" if a == "on" else None)
            print(T("純文字／Markdown 的 MCP 輸出也會瘦身（寫入 ~/.claude/chutora/mcp-trim-text）；改回：/chutora mcp-trim text off。"
                    if a == "on" else "純文字／Markdown 的 MCP 輸出不再瘦身（預設）。",
                    "Plain-text / Markdown MCP output will be trimmed too (saved to ~/.claude/chutora/mcp-trim-text); undo: /chutora mcp-trim text off."
                    if a == "on" else "Plain-text / Markdown MCP output is no longer trimmed (the default)."))
            return 0
        print(T("用法：/chutora mcp-trim text on|off", "Usage: /chutora mcp-trim text on|off"))
        return 2
    name = arg.strip()
    if not name or not re.match(r"^[\w.:-]+$", name):
        print(T("用法：/chutora mcp-trim exclude|include <server 名稱或 mcp__ 前綴>", "Usage: /chutora mcp-trim exclude|include <server name or mcp__ prefix>"))
        return 2
    lines = read_text(path).splitlines()
    norm = lambda x: x.strip() if x.strip().startswith("mcp__") else f"mcp__{x.strip()}__"  # noqa: E731
    target = norm(name)
    if action == "exclude":
        if any(norm(x) == target for x in lines if x.strip() and not x.startswith("#")):
            print(T(f"{target} 已在排除清單。", f"{target} is already excluded."))
            return 0
        lines.append(name)
    else:
        new = [x for x in lines if x.startswith("#") or not x.strip() or norm(x) != target]
        if new == lines:
            print(T(f"{target} 不在排除清單。", f"{target} is not in the exclude list."))
            return 0
        lines = new
    os.makedirs(CONF, exist_ok=True)
    if os.path.exists(path):
        import shutil
        shutil.copy2(path, path + ".bak")
    write_conf("mcp-trim-exclude", "\n".join(lines) if lines else None)
    print(T(f"已{'排除' if action == 'exclude' else '恢復'} {target}（寫入 ~/.claude/chutora/mcp-trim-exclude，舊檔備份為 .bak）。",
            f"{'Excluded' if action == 'exclude' else 'Restored'} {target} (saved to ~/.claude/chutora/mcp-trim-exclude; previous file kept as .bak)."))
    return 0


def observe_privacy_cmd(arg):
    a = (arg or "").strip().lower()
    if not a:
        pv, why = observe_privacy()
        print(T(f"觀察紀錄隱私：{privacy_label(pv)}{'（' + why + '）' if why else ''}。可用 /chutora observe privacy strict|normal 切換。",
                f"Observation privacy: {privacy_label(pv)}{' (' + why + ')' if why else ''}. Switch with /chutora observe privacy strict|normal."))
        return 0
    alias = {"嚴格": "strict", "一般": "normal", "on": "strict", "off": "normal"}
    a = alias.get(a, a)
    if a not in ("strict", "normal"):
        print(T(f"不認得的設定：{arg}。可用 strict、normal。", f"Unknown value: {arg}. Use strict or normal."))
        return 2
    write_conf("observe-privacy", "strict" if a == "strict" else None)
    if a == "strict":
        print(T("已切到嚴格隱私（寫入 ~/.claude/chutora/observe-privacy）：之後你的糾正與選擇只記長度，不存你打的字；改回：/chutora observe privacy normal。",
                "Strict privacy is on (saved to ~/.claude/chutora/observe-privacy): from now on only the length of your corrections and choices is kept, none of your words; undo: /chutora observe privacy normal."))
    else:
        print(T("已改回一般隱私：糾正存前 160 字（已遮罩金鑰）。", "Back to normal privacy: corrections keep their first 160 characters (secrets masked)."))
    env = os.environ.get("CHUTORA_OBSERVE_PRIVACY", "").strip().lower()
    if env in ("strict", "normal") and env != a:
        print(T(f"注意：環境變數 CHUTORA_OBSERVE_PRIVACY={env} 優先，目前仍是 {env}。",
                f"Note: the CHUTORA_OBSERVE_PRIVACY={env} environment variable takes precedence, so it is still {env}."))
    return 0


def guard_rules():
    g = hook_mod("guard")
    if not g:
        print(T("找不到 guard.py。", "guard.py not found."))
        return 1
    off, extra, bad = g.user_rules()
    print(T("危險守門規則（ask＝先問你，deny＝直接擋）：", "Danger guard rules (ask = asks you first, deny = blocked):"))
    for rid, (d, zh, en) in g.RULES.items():
        state = T("（已停用）", " (disabled)") if rid in off else ""
        print(f"- {rid} [{d}] {T(zh, en)}{state}")
    for d, _, line in extra:
        print(f"- {T('你的規則', 'yours')} [{d}] {line.strip()}")
    for line in bad:
        print(f"- {T('無效（略過）', 'invalid (skipped)')}: {line.strip()}")
    print(T("調整：編輯 ~/.claude/chutora/always-ask，每行一個 regex；deny: 開頭直接擋；!<規則 id> 移除預設規則。",
            "Adjust: edit ~/.claude/chutora/always-ask, one regex per line; prefix deny: to block; !<rule id> removes a default rule."))
    return 0


def decide_cmd(sub, args):
    """決策引擎：changes（列出待確認）、ok <id|all> [auto|ask]、undo <id>、stats。"""
    d = hook_mod("decide")
    if not d:
        print(T("找不到 decide.py（hooks 版本太舊？先跑 /chutora doctor）。", "decide.py not found (old hooks? run /chutora doctor)."))
        return 1
    if sub == "changes":
        n = int(args[0]) if args and args[0].isdigit() else 10
        print(d.list_changes(n, project_dir()))
        return 0
    if sub == "ok":
        if not args:
            print(T("用法：/chutora ok <id|all> [auto|ask]", "Usage: /chutora ok <id|all> [auto|ask]"))
            return 2
        done, msgs = d.feedback(args[0], args[1] if len(args) > 1 else "", project_dir())
        print("\n".join(msgs))
        return 0 if done else 1
    if sub == "undo":
        if not args:
            print(T("用法：/chutora undo <id>（id 見 /chutora changes）", "Usage: /chutora undo <id> (ids: /chutora changes)"))
            return 2
        ok, msg = d.undo(args[0], project_dir())
        print(msg)
        return 0 if ok else 1
    st = d.stats(d.load_decisions(project_dir()))
    print(json.dumps(st, ensure_ascii=False))
    return 0


def main(argv):
    sub = argv[0].lower() if argv else "status"
    rest = argv[1] if len(argv) > 1 else ""
    if sub in ("status", "狀態", ""):
        status()
        return 0
    if sub in ("doctor", "健檢", "check"):
        return doctor()
    if sub in ("mode", "模式"):
        return mode(rest)
    if sub in ("trim", "瘦身"):
        return trim(rest)
    if sub in ("dedup", "去重"):
        return toggle("dedup", rest)
    if sub in ("mcp-trim", "mcptrim", "mcp"):
        if rest.lower() in ("exclude", "include", "text"):
            return mcp_sub(rest.lower(), argv[2] if len(argv) > 2 else "")
        return toggle("mcp-trim", rest)
    if sub in ("guard", "守門"):
        if rest.lower() in ("rules", "規則", "list"):
            return guard_rules()
        return toggle("guard", rest)
    if sub in ("observe", "觀察"):
        if rest.lower() in ("privacy", "隱私"):
            return observe_privacy_cmd(argv[2] if len(argv) > 2 else "")
        return toggle("observe", rest)
    if sub in ("ask", "反問", "先問我"):
        return ask(rest)
    if sub in ("changes", "變更", "待確認"):
        return decide_cmd("changes", argv[1:])
    if sub in ("ok", "好"):
        return decide_cmd("ok", argv[1:])
    if sub in ("undo", "復原"):
        return decide_cmd("undo", argv[1:])
    if sub in ("decide", "決策"):
        if rest.lower() in ("stats", "統計"):
            return decide_cmd("stats", [])
        return toggle("decide", rest)
    if sub in ("lang", "language", "語言"):
        return set_lang(rest)
    print(T(f"不認得的指令：{sub}。可用：status、doctor、mode、trim、dedup、mcp-trim、ask、guard、observe、changes、ok、undo、decide、lang。",
            f"Unknown command: {sub}. Available: status, doctor, mode, trim, dedup, mcp-trim, ask, guard, observe, changes, ok, undo, decide, lang."))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
