#!/usr/bin/env python3
"""損益表（/chutora ledger）：把觀察紀錄接成一張帳——每個功能花多少、省多少、攔下多少、出錯多少。

唯讀：只讀 ~/.claude/chutora/projects/<專案 id>/observations.jsonl（含 archive/）、overhead/ 與對話紀錄，
不寫任何檔、不注入任何文字；只輸出數字，不輸出使用者打的字或工具輸出內容。只用標準函式庫。

- 單位是「每則使用者提示」（user_prompt／user_correction／不是工具回來的 user_choice），不是每場對話：
  一場做的事變多會讓每場變貴，但不代表設定變肥。
- 收入（省下）：trimmed／reread 的 saved_chars，÷4 換成 token（CJK 會被低估，寧可少算收入）。
- 支出（固定開銷）：每個對話一次 usage.overhead_tokens（已含 ×1.5 校正，寧可多算支出）。
- 品質：真失誤（tool_fail／repeat_error，不含使用者中斷）與守門攔截（guard_ask／guard_deny）分開列——
  被攔下是刻意設計的，不算失誤。
- 派工：delegation_result 摘要開頭的「狀態：完成｜失敗｜需要決策」「驗證：通過｜未驗證｜失敗」；沒照格式的記成未標示。
- 實際用量：這些對話在 ~/.claude/projects 的對話紀錄裡 assistant 的 usage 加總（找不到就略過這一段）。

collect() 回傳的 dict 就是 `ledger json` 的輸出，也給之後的消融比對與跨平台彙總用。
"""
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VERSION = 1
DAYS = 7
CHARS_PER_TOKEN = 4
PROMPTS = ("user_prompt", "user_correction", "user_choice")
FAILS = ("tool_fail", "repeat_error")
STATUS_RE = re.compile(r"(?:狀態|Status)\s*[:：]\s*(完成|失敗|需要決策|done|failed|needs[ -]decision)", re.I)
VERIFY_RE = re.compile(r"(?:驗證|Verif\w*)\s*[:：]\s*(通過|未驗證|失敗|passed|unverified|failed)", re.I)
STATUS_KEY = {"完成": "done", "done": "done", "失敗": "failed", "failed": "failed"}
TOKEN_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")


def parse_ts(s):
    """觀察紀錄與對話紀錄的時間 → 有時區的 datetime；看不懂回傳 None。"""
    if not isinstance(s, str) or not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    m = re.match(r"^(.*[+-]\d{2})(\d{2})$", s)  # +0800 → +08:00（Python 3.10 以前的 fromisoformat 不吃）
    if m:
        s = m.group(1) + ":" + m.group(2)
    s = re.sub(r"\.(\d{1,6})\d*", lambda x: "." + x.group(1).ljust(6, "0"), s)
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def records(ddir):
    """一個專案資料夾裡的所有觀察紀錄（含輪替到 archive/ 的），壞行跳過。"""
    paths = sorted(glob.glob(os.path.join(ddir, "archive", "observations-*.jsonl")))
    paths.append(os.path.join(ddir, "observations.jsonl"))
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict):
                        yield d
        except OSError:
            continue


def _int(x):
    try:
        return max(0, int(x))
    except (TypeError, ValueError):
        return 0


def _usage_mod():
    try:
        import usage
        return usage
    except Exception:
        return None


def _price_mod():
    try:
        import importlib.util
        for cand in (os.path.join(HERE, "..", "skills", "usage-stats", "usage_stats.py"),
                     os.path.expanduser("~/.claude/skills/usage-stats/usage_stats.py")):
            if os.path.isfile(cand):
                spec = importlib.util.spec_from_file_location("chutora_usage_stats", cand)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
    except Exception:
        pass
    return None


def actual_usage(sessions, since, until, root=None):
    """這些對話在對話紀錄裡的實際用量；找不到任何紀錄回傳 None。"""
    root = root or os.path.join(os.path.expanduser("~"), ".claude", "projects")
    us, um = _price_mod(), _usage_mod()
    out = {"main_tokens": 0, "sub_tokens": 0, "prompts": 0, "cost": 0.0, "unpriced": 0, "sessions": 0}
    seen, found = set(), set()
    for dirpath, _dirs, files in os.walk(root):
        parts = os.path.relpath(dirpath, root).split(os.sep)
        for name in sorted(files):
            if not name.endswith(".jsonl"):
                continue
            sid = name[:-6]
            in_sub = "subagents" in parts
            owner = sid if sid in sessions else next((p for p in parts if p in sessions), None)
            if not owner:
                continue
            try:
                fh = open(os.path.join(dirpath, name), encoding="utf-8", errors="ignore")
            except OSError:
                continue
            with fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(d, dict):
                        continue
                    t = parse_ts(d.get("timestamp"))
                    if t is None or not (since <= t < until):
                        continue
                    if d.get("type") == "user":
                        if not in_sub and um and um.is_real_prompt(d):
                            out["prompts"] += 1
                        continue
                    m = d.get("message")
                    if d.get("type") != "assistant" or not isinstance(m, dict):
                        continue
                    u = m.get("usage")
                    if not isinstance(u, dict) or not u:
                        continue
                    key = (m.get("id"), d.get("requestId"))
                    if key in seen:
                        continue
                    seen.add(key)
                    found.add(owner)
                    n = sum(_int(u.get(k)) for k in TOKEN_KEYS)
                    out["sub_tokens" if (in_sub or d.get("isSidechain")) else "main_tokens"] += n
                    c = None
                    if us:
                        try:
                            c = us.call_cost(str(m.get("model", "?")), u)
                        except Exception:
                            c = None
                    if c is None:
                        out["unpriced"] += 1
                    else:
                        out["cost"] += c
    if not found:
        return None
    out["sessions"] = len(found)
    out["cost"] = round(out["cost"], 4)
    return out


def collect(ddirs, days=DAYS, now=None, transcripts=None):
    """讀一或多個專案資料夾，回傳損益表（dict）。now 是有時區的 datetime（測試用）。"""
    now = now or datetime.datetime.now().astimezone()
    since = now - datetime.timedelta(days=days)
    sessions, prompts, actions, corrections = set(), 0, 0, 0
    trims, reread = {}, {"n": 0, "chars": 0}
    guard = {"ask": 0, "deny": 0}
    fail = {"tool_fail": 0, "repeat_error": 0, "interrupted": 0}
    agents = {}
    for ddir in ddirs:
        for r in records(ddir):
            t = parse_ts(r.get("ts"))
            if t is None or not (since <= t < now):
                continue
            sig = r.get("signal")
            if r.get("session"):
                sessions.add(str(r["session"]))
            if sig in PROMPTS and not r.get("tool"):  # 有 tool 的 user_choice 是 AskUserQuestion 的答案，不是新提示
                prompts += 1
                if sig == "user_correction":
                    corrections += 1
            elif sig == "tool_ok" or (sig == "user_choice" and r.get("tool")):
                actions += 1
            elif sig in FAILS:
                actions += 1
                if r.get("interrupted"):
                    fail["interrupted"] += 1
                else:
                    fail[sig] += 1
            elif sig == "guard_ask":
                guard["ask"] += 1
            elif sig == "guard_deny":
                guard["deny"] += 1
            elif sig == "trimmed":
                k = trims.setdefault(str(r.get("kind") or r.get("tool") or "?"), {"n": 0, "chars": 0})
                k["n"] += 1
                k["chars"] += _int(r.get("saved_chars"))
            elif sig == "reread":
                reread["n"] += 1
                reread["chars"] += _int(r.get("saved_chars"))
            elif sig == "delegation_result":
                a = agents.setdefault(str(r.get("agent") or "subagent"),
                                      {"n": 0, "done": 0, "failed": 0, "decision": 0, "unmarked": 0, "verified": 0})
                a["n"] += 1
                s = r.get("summary") if isinstance(r.get("summary"), str) else ""
                m = STATUS_RE.search(s)
                a[STATUS_KEY.get(m.group(1).lower(), "decision") if m else "unmarked"] += 1
                v = VERIFY_RE.search(s)
                if v and v.group(1).lower() in ("通過", "passed"):
                    a["verified"] += 1
    saved_chars = reread["chars"] + sum(k["chars"] for k in trims.values())
    saved_tokens = saved_chars // CHARS_PER_TOKEN
    um = _usage_mod()
    over = {"tokens": 0, "sessions": len(sessions), "measured": 0}
    for sid in sorted(sessions):
        if not um:
            break
        try:
            if any(um.injected_counts(sid)):
                over["measured"] += 1
            over["tokens"] += _int(um.overhead_tokens(sid))
        except Exception:
            continue
    fails = fail["tool_fail"] + fail["repeat_error"]
    net = saved_tokens - over["tokens"]
    return {
        "v": VERSION, "days": days, "since": since.isoformat(timespec="seconds"),
        "until": now.isoformat(timespec="seconds"), "projects": len(ddirs),
        "sessions": len(sessions), "prompts": prompts, "actions": actions,
        "saved": {"trim": {k: trims[k] for k in sorted(trims)}, "reread": reread,
                  "chars": saved_chars, "tokens": saved_tokens},
        "overhead": over, "net_tokens": net,
        "guard": guard, "fail": fail, "fails": fails, "corrections": corrections,
        "agents": {k: agents[k] for k in sorted(agents)},
        "per_prompt": {"actions": round(actions / prompts, 2) if prompts else None,
                       "net_tokens": round(net / prompts) if prompts else None},
        "actual": actual_usage(sessions, since, now, transcripts) if sessions else None,
    }


# ---------------------------------------------------------------- 顯示
def _n(x):
    return f"{x:,}"


def _tok(x):
    return f"{x / 1e6:.2f}M" if x >= 1e6 else (f"{x / 1e3:.1f}k" if x >= 1e4 else _n(x))


def _pct(a, b):
    return f"{a / b * 100:.1f}%" if b else "—"


def render(d, lng="zh", scope_all=False):
    en = lng == "en"
    T = (lambda zh, e: e) if en else (lambda zh, e: zh)
    scope = T("全部專案", "all projects") if scope_all else T("本專案", "this project")
    out = [T(f"Chutora 損益表（過去 {d['days']} 天，{scope}）", f"Chutora ledger (past {d['days']} days, {scope})")]
    if not d["sessions"]:
        out.append(T("這段期間沒有觀察紀錄。觀察開著嗎？用 /chutora observe 查看。",
                     "No observations in this period. Is observe on? Check with /chutora observe."))
        return "\n".join(out)
    pp = d["per_prompt"]
    out.append(T(f"規模：{_n(d['sessions'])} 個對話、{_n(d['prompts'])} 則提示、{_n(d['actions'])} 個動作",
                 f"Scale: {_n(d['sessions'])} sessions, {_n(d['prompts'])} prompts, {_n(d['actions'])} actions")
               + (T(f"（每則提示 {pp['actions']} 個）", f" ({pp['actions']} per prompt)") if d["prompts"] else ""))
    s = d["saved"]
    out += ["", T("收入（省下，估算）", "Income (saved, estimated)")]
    rows = [(T(f"輸出瘦身（{k}）", f"output trim ({k})"), v) for k, v in s["trim"].items()]
    rows.append((T("讀檔去重", "reread dedup"), s["reread"]))
    for name, v in rows:
        out.append(T(f"  {name}：{_n(v['n'])} 次，省 {_n(v['chars'])} 字元",
                     f"  {name}: {_n(v['n'])}×, saved {_n(v['chars'])} chars"))
    out.append(T(f"  合計 ≈ {_n(s['tokens'])} token", f"  Total ≈ {_n(s['tokens'])} tokens"))
    o = d["overhead"]
    out += ["", T("支出（固定開銷，估算）", "Cost (fixed overhead, estimated)"),
            T(f"  {_n(o['sessions'])} 個對話 ≈ {_n(o['tokens'])} token", f"  {_n(o['sessions'])} sessions ≈ {_n(o['tokens'])} tokens")
            + (T(f"（其中 {_n(o['sessions'] - o['measured'])} 個沒有開場注入紀錄，只算描述文字）",
                 f" ({_n(o['sessions'] - o['measured'])} without an injection record: descriptions only)")
               if o["measured"] < o["sessions"] else "")]
    sign = "+" if d["net_tokens"] >= 0 else "−"
    out += ["", T(f"淨省 ≈ {sign}{_n(abs(d['net_tokens']))} token", f"Net ≈ {sign}{_n(abs(d['net_tokens']))} tokens")
            + (T(f"（每則提示 {'+' if pp['net_tokens'] >= 0 else '−'}{_n(abs(pp['net_tokens']))}）",
                 f" ({'+' if pp['net_tokens'] >= 0 else '−'}{_n(abs(pp['net_tokens']))} per prompt)") if d["prompts"] else "")]
    f, g = d["fail"], d["guard"]
    out += ["", T("品質", "Quality"),
            T(f"  真失誤：{_n(d['fails'])} 次（佔動作 {_pct(d['fails'], d['actions'])}；其中重複犯錯 {_n(f['repeat_error'])} 次）",
              f"  Real failures: {_n(d['fails'])} ({_pct(d['fails'], d['actions'])} of actions; {_n(f['repeat_error'])} repeated)"),
            T(f"  守門攔截：{_n(g['ask'] + g['deny'])} 次（先問 {_n(g['ask'])}、擋下 {_n(g['deny'])}）——刻意設計，不算失誤",
              f"  Guard intercepts: {_n(g['ask'] + g['deny'])} (asked {_n(g['ask'])}, denied {_n(g['deny'])}) — by design, not failures"),
            T(f"  被你糾正：{_n(d['corrections'])} 次（佔提示 {_pct(d['corrections'], d['prompts'])}）",
              f"  Corrected by you: {_n(d['corrections'])} ({_pct(d['corrections'], d['prompts'])} of prompts)")]
    if f["interrupted"]:
        out.append(T(f"  你中斷的：{_n(f['interrupted'])} 次（不算失誤）", f"  Interrupted by you: {_n(f['interrupted'])} (not counted)"))
    if d["agents"]:
        out += ["", T("派工", "Delegation")]
        for name, a in d["agents"].items():
            marked = a["n"] - a["unmarked"]
            if not marked:
                out.append(T(f"  {name}：{_n(a['n'])} 次，沒有標示狀態", f"  {name}: {_n(a['n'])}×, no status reported"))
                continue
            out.append(T(f"  {name}：{_n(a['n'])} 次——完成 {a['done']}、失敗 {a['failed']}、需要決策 {a['decision']}"
                         f"{f'、未標示 {a_un}' if (a_un := a['unmarked']) else ''}（成功率 {_pct(a['done'], marked)}）",
                         f"  {name}: {_n(a['n'])}× — done {a['done']}, failed {a['failed']}, needs decision {a['decision']}"
                         f"{f', unmarked {a_un}' if (a_un := a['unmarked']) else ''} (success {_pct(a['done'], marked)})"))
    a = d.get("actual")
    if a:
        total = a["main_tokens"] + a["sub_tokens"]
        line = T(f"  主對話 {_tok(a['main_tokens'])}、子 agent {_tok(a['sub_tokens'])} token",
                 f"  main {_tok(a['main_tokens'])}, subagents {_tok(a['sub_tokens'])} tokens")
        if a["prompts"]:
            line += T(f"；每則提示約 {_tok(round(total / a['prompts']))}", f"; about {_tok(round(total / a['prompts']))} per prompt")
        if a["cost"] > 0:
            line += T(f"；API 牌價約 ${a['cost']:,.2f}", f"; about ${a['cost']:,.2f} at API list price")
        out += ["", T(f"實際用量（{_n(a['sessions'])} 個對話的對話紀錄）", f"Actual usage (transcripts of {_n(a['sessions'])} sessions)"), line]
    out += ["", T("說明：收入以省下字元 ÷4 估（偏低），支出含 ×1.5 校正（偏高）；token 含快取讀取，訂閱方案不按牌價計費。",
                  "Notes: income is saved chars ÷4 (low side), cost includes a ×1.5 calibration (high side); "
                  "tokens include cache reads, and subscriptions are not billed at list price.")]
    return "\n".join(out)


def project_dirs(scope_all=False, cwd=None):
    from projectid import conf_dir, project_data_dir
    if scope_all:
        return sorted(p for p in glob.glob(os.path.join(conf_dir(), "projects", "*")) if os.path.isdir(p))
    return [project_data_dir(cwd, create=False)]


def main(argv, lng="zh"):
    days, scope_all, as_json = DAYS, False, False
    for a in argv:
        s = str(a).lower().lstrip("-")
        if s in ("all", "全部"):
            scope_all = True
        elif s == "json":
            as_json = True
        elif s.isdigit() and 1 <= int(s) <= 3650:
            days = int(s)
        else:
            print(("Usage: ledger [days] [all] [json]" if lng == "en" else "用法：ledger [天數] [all] [json]"))
            return 2
    try:
        d = collect(project_dirs(scope_all), days)
    except Exception as e:  # 報表壞了也不該丟一串 traceback 給使用者
        print(("Ledger failed: " if lng == "en" else "損益表算不出來：") + type(e).__name__)
        return 1
    print(json.dumps(d, ensure_ascii=False, sort_keys=True) if as_json else render(d, lng, scope_all))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], "en" if (os.environ.get("CHUTORA_LANG") or "").lower().startswith("en") else "zh"))
