#!/usr/bin/env python3
"""統計 Claude Code 對話紀錄的 context 用量與子 agent 使用比例，用於優化前後比較。

用法：python3 usage_stats.py [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                             [--project 子字串] [--root 路徑] [--threshold N]
                             [--html 輸出路徑]
預設唯讀；只有給 --html 才會寫一份自足的靜態 HTML 報表。
"""
import argparse
import datetime
import glob
import html
import json
import os
from collections import Counter, defaultdict

# 價格表：每百萬 token 美元，2026-10-18 依 Anthropic API 牌價。
# 欄位順序：(input, output, cache read, 5 分鐘寫入, 1 小時寫入)；模型名用前綴比對
PRICES = {
    "claude-opus-5-5": (4, 20, 0.20, 5, 8),
    "claude-sonnet-5-5": (2, 10, 0.20, 2.50, 4),
}
# Haiku 依該次呼叫的 prompt（input+cache_read+cache_write）分兩段價
HAIKU_PREFIX = "claude-haiku-5-5"
HAIKU_LOW = (0.10, 0.50, 0.01, 0.125, 0.20)
HAIKU_HIGH = (0.50, 2.50, 0.05, 0.625, 1.00)
HAIKU_LIMIT = 100000
MAIN_LABEL = "主對話"


def env_threshold():
    try:
        return int(os.environ.get("CONTEXT_REMIND_TOKENS", ""))
    except ValueError:
        return 100000  # 與 hooks/compact.py 的 DEFAULT_REMIND 同值（此檔在別的目錄，不 import）


def num(u, key):
    v = u.get(key, 0)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def agent_type(path):
    meta = path[:-len(".jsonl")] + ".meta.json"
    try:
        with open(meta, encoding="utf-8", errors="ignore") as fh:
            t = json.load(fh).get("agentType")
        return t if isinstance(t, str) and t else "(未知)"
    except Exception:
        return "(未知)"


def pct(x):
    return f"{x:.0%}"


def money(x):
    return f"${x:,.2f}"


def call_cost(model, u):
    """單次呼叫的估計金額（美元）；模型不在價格表回傳 None。"""
    inp, cr = num(u, "input_tokens"), num(u, "cache_read_input_tokens")
    cw, out = num(u, "cache_creation_input_tokens"), num(u, "output_tokens")
    cc = u.get("cache_creation")
    if isinstance(cc, dict):
        w1, w5 = num(cc, "ephemeral_1h_input_tokens"), num(cc, "ephemeral_5m_input_tokens")
    else:
        w1, w5 = 0, cw  # 沒有細項時全部當 5 分鐘寫入
    price = None
    if model.startswith(HAIKU_PREFIX):
        price = HAIKU_LOW if inp + cr + cw <= HAIKU_LIMIT else HAIKU_HIGH
    else:
        for prefix, p in PRICES.items():
            if model.startswith(prefix):
                price = p
                break
    if price is None:
        return None
    pi, po, pr, p5, p1 = price
    return (inp * pi + out * po + cr * pr + w5 * p5 + w1 * p1) / 1_000_000


def local_date(ts):
    """UTC 時間戳轉成本機時區的日期字串（YYYY-MM-DD）；解析失敗退回前 10 字元。"""
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d")
    except Exception:
        return ts[:10]


def agent_meta(path):
    """回傳 (agentType, toolUseId)；讀不到的欄位為 (未知) / None。"""
    meta = path[:-len(".jsonl")] + ".meta.json"
    try:
        with open(meta, encoding="utf-8", errors="ignore") as fh:
            d = json.load(fh)
        t = d.get("agentType")
        tid = d.get("toolUseId")
        return (t if isinstance(t, str) and t else "(未知)",
                tid if isinstance(tid, str) and tid else None)
    except Exception:
        return "(未知)", None


def new_bucket():
    return {"calls": 0, "inp": 0, "cache_r": 0, "cache_w": 0, "out": 0,
            "cost": 0.0, "unpriced": 0}


def add(b, inp, cr, cw, out, cost):
    b["calls"] += 1
    b["inp"] += inp
    b["cache_r"] += cr
    b["cache_w"] += cw
    b["out"] += out
    if cost is None:
        b["unpriced"] += 1
    else:
        b["cost"] += cost


def cost_text(b):
    return "-" if b["calls"] and b["unpriced"] == b["calls"] else money(b["cost"])


def dispatch_label(tid, tool_uses):
    """依 meta 的 toolUseId 找主對話 tool_use 的 input.model。"""
    if tid is None or tid not in tool_uses:
        return "查無派工紀錄"
    return tool_uses[tid] or "未指定"


def render_html(path, args, summary, daily, rows, models_note):
    e = html.escape
    cats = [MAIN_LABEL] + sorted({c for d in daily.values() for c in d if c != MAIN_LABEL})
    days = sorted(daily)
    maxv = max([sum(daily[d].values()) for d in days] + [0.0])
    colw, h, top, bot, left = 44, 260, 12, 40, 56
    w = left + colw * max(len(days), 1) + 10
    svg = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="每日估計金額">']
    plot = h - top - bot
    for i in range(5):
        y = top + plot * i / 4
        val = maxv * (4 - i) / 4
        svg.append(f'<line x1="{left}" x2="{w - 10}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        svg.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" class="axis">{e(money(val))}</text>')
    for i, d in enumerate(days):
        x = left + i * colw + 6
        y = top + plot
        for c in cats:
            v = daily[d].get(c, 0.0)
            if v <= 0 or maxv <= 0:
                continue
            bh = plot * v / maxv
            y -= bh
            svg.append(f'<rect x="{x}" y="{y:.1f}" width="{colw - 12}" height="{bh:.1f}" '
                       f'class="c{cats.index(c) % 8}"><title>{e(d)} {e(c)} {e(money(v))}</title></rect>')
        svg.append(f'<text x="{x + (colw - 12) / 2:.1f}" y="{h - bot + 14}" text-anchor="middle" class="axis">{e(d[5:])}</text>')
    svg.append("</svg>")
    legend = "".join(f'<span class="lg"><i class="sw c{i % 8}"></i>{e(c)}</span>' for i, c in enumerate(cats))
    cards = "".join(f'<div class="card"><div class="k">{e(k)}</div><div class="v">{e(v)}</div></div>'
                    for k, v in summary)
    trs = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    heads = ["agent 類型", "實際模型", "派工次數", "指定模型分布", "calls", "input",
             "cache_read", "cache_write", "估計金額"]
    ths = "".join(f"<th>{e(x)}</th>" for x in heads)
    css = """
:root{--bg:#fff;--fg:#1f2328;--mute:#656d76;--card:#f6f8fa;--line:#d0d7de;
--c0:#0969da;--c1:#bf8700;--c2:#1a7f37;--c3:#cf222e;--c4:#8250df;--c5:#bc4c00;--c6:#0a7d8c;--c7:#6e7781}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mute:#8b949e;--card:#161b22;--line:#30363d;
--c0:#58a6ff;--c1:#d29922;--c2:#3fb950;--c3:#f85149;--c4:#bc8cff;--c5:#f0883e;--c6:#39c5cf;--c7:#8b949e}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Helvetica Neue",sans-serif;margin:24px auto;max-width:1100px;padding:0 16px}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}
.cards{display:flex;flex-wrap:wrap;gap:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:150px}
.k{color:var(--mute);font-size:12px}.v{font-size:18px;font-weight:600}
.chart{overflow-x:auto}.grid{stroke:var(--line);stroke-width:1}.axis{fill:var(--mute);font-size:10px}
""" + "".join(f".c{i}{{fill:var(--c{i});background:var(--c{i})}}" for i in range(8)) + """
.lg{margin-right:14px;font-size:12px}.sw{display:inline-block;width:10px;height:10px;margin-right:4px;border-radius:2px}
table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left}
td:nth-child(n+5),th:nth-child(n+5){text-align:right}.note{color:var(--mute);font-size:12px}
"""
    period = f"{args.since} ~ {args.until}" + (f"　專案：{args.project}" if args.project else "")
    doc = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chutora 用量報表</title><style>{css}</style></head><body>
<h1>Chutora 用量報表</h1><div class="note">期間：{e(period)}</div>
<h2>摘要</h2><div class="cards">{cards}</div>
<h2>每日估計金額（本機日期，依 agent 類型堆疊）</h2><div class="legend">{legend}</div><div class="chart">{"".join(svg)}</div>
<h2>agent 類型</h2><table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>
<p class="note">{e(models_note)}</p>
</body></html>
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="0000-00-00")
    ap.add_argument("--until", default="9999-99-99")
    ap.add_argument("--project", default="")
    ap.add_argument("--root", default="~/.claude/projects")
    ap.add_argument("--threshold", type=int, default=None)
    ap.add_argument("--html", default=None, help="寫出自足的靜態 HTML 報表到此路徑")
    args = ap.parse_args()
    threshold = args.threshold if args.threshold is not None else env_threshold()
    root = os.path.abspath(os.path.expanduser(args.root))

    seen, ctx = set(), []
    by = defaultdict(new_bucket)
    by_type = defaultdict(new_bucket)        # (agent 類型, 模型) -> 統計
    type_files = defaultdict(set)            # (agent 類型, 模型) -> 子 agent 檔案
    file_tid = {}                            # 子 agent 檔案 -> meta 的 toolUseId
    tool_uses = {}                           # tool_use id -> input.model（None = 未指定）
    daily = defaultdict(lambda: defaultdict(float))  # 本機日期 -> 類別 -> 金額
    main_sessions, sessions_with_sub = set(), set()
    main_calls = sub_calls = 0
    main_cost = sub_cost = 0.0
    unpriced = 0

    for f in sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)):
        rel = os.path.relpath(f, root).split(os.sep)
        if args.project and args.project not in rel[0]:
            continue
        in_sub_dir = "subagents" in rel[:-1]
        atype = None
        try:
            fh = open(f, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            try:
                lines = list(fh)
            except Exception:
                continue
        for line in lines:
            try:
                d = json.loads(line)
                m = d.get("message")
                if d.get("type") != "assistant" or not isinstance(m, dict):
                    continue
                if not in_sub_dir and isinstance(m.get("content"), list):
                    # 蒐集派工參數（不受日期篩選影響，派工可能發生在期間之前）
                    for blk in m["content"]:
                        if isinstance(blk, dict) and blk.get("type") == "tool_use" and isinstance(blk.get("id"), str):
                            inp_ = blk.get("input")
                            mdl_ = inp_.get("model") if isinstance(inp_, dict) else None
                            tool_uses[blk["id"]] = mdl_ if isinstance(mdl_, str) and mdl_ else None
                u = m.get("usage")
                if not isinstance(u, dict) or not u:
                    continue
                ts = d.get("timestamp")
                if not isinstance(ts, str):
                    continue
                day = local_date(ts)
                if not (args.since <= day <= args.until):
                    continue
                key = (m.get("id"), d.get("requestId"))
                if key in seen:
                    continue
                seen.add(key)
                is_sub = bool(d.get("isSidechain")) or in_sub_dir
                model = str(m.get("model", "?"))
                inp = num(u, "input_tokens")
                cr, cw = num(u, "cache_read_input_tokens"), num(u, "cache_creation_input_tokens")
                out = num(u, "output_tokens")
                cost = call_cost(model, u)
                if cost is None:
                    unpriced += 1
                add(by[f"{model} | {'sub' if is_sub else 'main'}"], inp, cr, cw, out, cost)
                if is_sub:
                    sub_calls += 1
                    sub_cost += cost or 0.0
                    if atype is None:
                        atype, tid = agent_meta(f) if f.endswith(".jsonl") else ("(未知)", None)
                        file_tid[f] = tid
                    add(by_type[(atype, model)], inp, cr, cw, out, cost)
                    type_files[(atype, model)].add(f)
                    daily[day][atype] += cost or 0.0
                    if in_sub_dir:
                        sess = rel[rel.index("subagents") - 1]
                    else:
                        sess = d.get("sessionId") or os.path.basename(f)[:-6]
                    sessions_with_sub.add((rel[0], sess))
                else:
                    main_calls += 1
                    main_cost += cost or 0.0
                    daily[day][MAIN_LABEL] += cost or 0.0
                    ctx.append(inp + cw + cr)
                    main_sessions.add((rel[0], os.path.basename(f)[:-6]))
            except Exception:
                continue

    print(f"期間：{args.since} ~ {args.until}" + (f"　專案：{args.project}" if args.project else ""))
    if not by:
        print("沒有符合條件的用量紀錄。")
        return
    print(f"\n{'模型 | main/sub':40} {'calls':>6} {'input':>11} {'cache_read':>13} {'cache_write':>12} {'output':>10} {'估計金額':>11}")
    for k, v in sorted(by.items(), key=lambda kv: -kv[1]["calls"]):
        print(f"{k:40} {v['calls']:>6} {v['inp']:>11,} {v['cache_r']:>13,} {v['cache_w']:>12,} {v['out']:>10,} {cost_text(v):>11}")

    total_cost = main_cost + sub_cost
    share = sub_cost / total_cost if total_cost else 0.0
    print(f"\n估計金額：主對話 {money(main_cost)}　子 agent {money(sub_cost)}　合計 {money(total_cost)}　子 agent 占比 {pct(share)}")
    note_unpriced = ""
    if unpriced:
        note_unpriced = f"有 {unpriced} 次呼叫因模型不在價格表而未計價（金額顯示 -，不計入總額）。"
        print(note_unpriced)

    med = p90 = mx = 0
    if ctx:
        ctx.sort()
        n = len(ctx)
        over = sum(x > threshold for x in ctx)
        med = ctx[n // 2] if n % 2 else (ctx[n // 2 - 1] + ctx[n // 2]) // 2
        p90 = ctx[min(int(n * .9), n - 1)]
        mx = ctx[-1]
        print(f"\n主對話每次呼叫的 context（{n} 次）：中位數 {med:,}　p90 {p90:,}　最大 {mx:,}")
        print(f"超過門檻 {threshold:,} 的呼叫比例：{pct(over / n)}（{over}/{n}）")
    else:
        print("\n沒有主對話呼叫紀錄。")

    total = main_calls + sub_calls
    print(f"\n子 agent 呼叫比例：{sub_calls}/{total}（{pct(sub_calls / total)}）")
    ms = {s for s in main_sessions}
    used = len(sessions_with_sub & (ms | sessions_with_sub))
    denom = len(ms | sessions_with_sub)
    if denom:
        print(f"有派過子 agent 的主對話 session：{used}/{denom}（{pct(used / denom)}）")

    rows = []
    if by_type:
        for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1]["cost"], kv[0])):
            a, mdl = k
            dist = Counter(dispatch_label(file_tid.get(f), tool_uses) for f in type_files[k])
            dist_s = "、".join(f"{lbl}×{c}" for lbl, c in sorted(dist.items(), key=lambda x: (-x[1], x[0])))
            rows.append((a, mdl, len(type_files[k]), dist_s, v["calls"], f"{v['inp']:,}",
                         f"{v['cache_r']:,}", f"{v['cache_w']:,}", cost_text(v)))
        print(f"\n{'agent 類型':32} {'實際模型':22} {'派工次數':>8} {'指定模型分布':26} {'calls':>6} {'input':>9} {'cache_read':>12} {'cache_write':>12} {'估計金額':>10}")
        for r in rows:
            print(f"{r[0]:32} {r[1]:22} {r[2]:>8} {r[3]:26} {r[4]:>6} {r[5]:>9} {r[6]:>12} {r[7]:>12} {r[8]:>10}")
        print("派工次數 = 不同的子 agent 檔案數；calls = API 呼叫數（一次派工通常有多次呼叫）。")
        # 2026-10-16 實測：子 agent 紀錄的 usage 是串流開頭的值（每次只有個位數到幾十），主對話紀錄則是最終值
    tail = "註：金額依 API 牌價估算，訂閱方案不是按 token 計費，只用來比較相對大小；子 agent 的 output 偏低，所以子 agent 金額是下限。"
    print(tail)

    if args.html:
        summary = [("總估計金額", money(total_cost)),
                   ("主對話", f"{money(main_cost)}（{pct(1 - share) if total_cost else '-'}）"),
                   ("子 agent", f"{money(sub_cost)}（{pct(share) if total_cost else '-'}）"),
                   ("context 中位數", f"{med:,}"), ("context p90", f"{p90:,}"), ("context 最大", f"{mx:,}")]
        render_html(args.html, args, summary, daily, rows, (note_unpriced + " " + tail).strip())
        print(f"\nHTML 報表：{os.path.abspath(args.html)}")


if __name__ == "__main__":
    main()
