#!/usr/bin/env python3
"""SessionStart 用：每個 ISO 週第一次對話輸出一行「上週派工省下多少」的估算；其他時候什麼都不印。

估算方法（只算模型價差）：過去 7 天子 agent 的每次 API 呼叫，假設改由主對話最常用的模型處理，
依 usage_stats.py 的 API 牌價表算出的金額，減去實際金額。不含 context 隔離省下的重讀成本，
也不代表訂閱方案的實際花費（訂閱不按 token 計費）。
CHUTORA_WEEKLY=0 可關閉。任何錯誤都安靜結束。
"""
import datetime
import glob
import importlib.util
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/hooks")
STATE = os.path.join(STATE_DIR, ".weekly-shown")
DAYS = 7


def load_usage_stats():
    for cand in (os.path.join(HERE, "..", "skills", "usage-stats", "usage_stats.py"),
                 os.path.expanduser("~/.claude/skills/usage-stats/usage_stats.py")):
        if os.path.isfile(cand):
            spec = importlib.util.spec_from_file_location("chutora_usage_stats", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def lang():
    v = os.environ.get("CHUTORA_RESOLVED_LANG")
    if v in ("zh", "en"):
        return v
    sys.path.insert(0, HERE)
    try:
        from compact import lang as _lang
        return _lang()
    except Exception:
        return "en"


def estimate(us, root, today):
    since = (today - datetime.timedelta(days=DAYS)).isoformat()
    until = today.isoformat()
    cutoff = datetime.datetime.combine(today - datetime.timedelta(days=DAYS + 1), datetime.time()).timestamp()
    main_models, subs, seen = Counter(), [], set()
    for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(f) < cutoff:
                continue
            in_sub = "subagents" in os.path.relpath(f, root).split(os.sep)[:-1]
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    m = d.get("message")
                    if d.get("type") != "assistant" or not isinstance(m, dict):
                        continue
                    u, ts = m.get("usage"), d.get("timestamp")
                    if not isinstance(u, dict) or not u or not isinstance(ts, str):
                        continue
                    if not (since <= us.local_date(ts) < until):
                        continue
                    key = (m.get("id"), d.get("requestId"))
                    if key in seen:
                        continue
                    seen.add(key)
                    model = str(m.get("model", "?"))
                    if d.get("isSidechain") or in_sub:
                        subs.append((model, u))
                    else:
                        main_models[model] += 1
        except OSError:
            continue
    if not subs or not main_models:
        return None
    main = main_models.most_common(1)[0][0]
    saved, tokens = 0.0, 0
    for model, u in subs:
        actual, counter = us.call_cost(model, u), us.call_cost(main, u)
        if actual is None or counter is None:
            continue
        saved += counter - actual
        tokens += sum(us.num(u, k) for k in ("input_tokens", "cache_read_input_tokens",
                                             "cache_creation_input_tokens", "output_tokens"))
    if saved <= 0 or tokens <= 0:
        return None
    return main, tokens, saved


def main():
    if os.environ.get("CHUTORA_WEEKLY", "1").strip() == "0":
        return
    today = datetime.date.today()
    week = "%d-W%02d" % today.isocalendar()[:2]
    try:
        with open(STATE) as f:
            if f.read().strip() == week:
                return
    except OSError:
        pass
    # 先記下這週已處理，避免掃描失敗時每次開對話都重掃
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(STATE, "w") as f:
            f.write(week + "\n")
    except OSError:
        return
    us = load_usage_stats()
    if us is None:
        return
    root = os.path.expanduser(os.environ.get("CHUTORA_PROJECTS_ROOT") or "~/.claude/projects")
    r = estimate(us, root, today)
    if not r:
        return
    main_model, tokens, saved = r
    short = main_model.replace("claude-", "")
    if lang() == "en":
        print(f"Chutora weekly (estimate): over the past {DAYS} days subagents handled about "
              f"{tokens / 1e6:.1f}M tokens, roughly ${saved:,.2f} less at API list prices than running them on "
              f"{short}. Model price difference only; context isolation savings not included, and subscriptions "
              f"aren't billed per token. Turn off with CHUTORA_WEEKLY=0.")
    else:
        print(f"Chutora 每週回顧（估算）：過去 {DAYS} 天子 agent 處理了約 {tokens / 1e4:,.0f} 萬 token，"
              f"比全部交給 {short} 處理，依 API 牌價約省 ${saved:,.2f}。只算模型價差，不含 context 隔離省下的部分；"
              f"訂閱方案不按 token 計費。設 CHUTORA_WEEKLY=0 可關閉。")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
