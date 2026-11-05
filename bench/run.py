#!/usr/bin/env python3
"""Chutora token benchmark：同一組固定任務，分別在「有 Chutora」和「沒有 Chutora」下用
`claude -p --output-format json` 各跑 N 次，記錄 token、花費、輪數與是否通過驗收，取中位數。

用法（會實際呼叫模型、產生費用）：
    ANTHROPIC_API_KEY=... python3 bench/run.py --runs 3
先看會跑什麼（不呼叫模型）：
    python3 bench/run.py --dry-run

隔離：每次執行都用全新的暫存工作目錄（從 bench/fixtures 複製）、暫存的 HOME 與
CLAUDE_CONFIG_DIR，不會讀你的 ~/.claude 設定、其他 plugin 或記憶，所以需要 ANTHROPIC_API_KEY。
「有 Chutora」用 --plugin-dir 載入 repo 裡的 plugins/chutora；「沒有」則不載入任何 plugin。
只用 Python 標準函式庫。
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLUGIN = os.path.join(REPO, "plugins", "chutora")
ARMS = ("without", "with")
TOOLS = "Bash,Read,Edit,Write,Glob,Grep"


def load_tasks(path=None):
    with open(path or os.path.join(HERE, "tasks.json")) as f:
        return json.load(f)


def build_cmd(task, arm, model=None, budget=None, plugin=PLUGIN):
    cmd = ["claude", "-p", task["prompt"], "--output-format", "json",
           "--permission-mode", "acceptEdits", "--allowedTools", TOOLS]
    if model:
        cmd += ["--model", model]
    if budget:
        cmd += ["--max-budget-usd", str(budget)]
    if arm == "with":
        cmd += ["--plugin-dir", plugin]
    return cmd


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_result(text):
    """解析 `claude -p --output-format json` 的輸出。找不到結果時回傳 None。

    優先用頂層 usage；沒有時加總 modelUsage（各模型的 inputTokens 等）。
    """
    data = None
    text = (text or "").strip()
    try:
        data = json.loads(text)
    except ValueError:
        for line in reversed(text.splitlines()):  # 有些版本會在前面多印東西
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except ValueError:
                    continue
    if isinstance(data, list):  # stream 形式：取最後一個 result
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None)
    if not isinstance(data, dict):
        return None
    u = data.get("usage") or {}
    rec = {
        "input_tokens": _num(u.get("input_tokens")),
        "output_tokens": _num(u.get("output_tokens")),
        "cache_creation_tokens": _num(u.get("cache_creation_input_tokens")),
        "cache_read_tokens": _num(u.get("cache_read_input_tokens")),
    }
    mu = data.get("modelUsage") or {}
    if not any(rec.values()) and isinstance(mu, dict):
        for m in mu.values():
            if isinstance(m, dict):
                rec["input_tokens"] += _num(m.get("inputTokens"))
                rec["output_tokens"] += _num(m.get("outputTokens"))
                rec["cache_creation_tokens"] += _num(m.get("cacheCreationInputTokens"))
                rec["cache_read_tokens"] += _num(m.get("cacheReadInputTokens"))
    cost = data.get("total_cost_usd")
    if cost is None and isinstance(mu, dict):
        cost = sum(_num(m.get("costUSD")) for m in mu.values() if isinstance(m, dict))
    rec.update(
        cost_usd=_num(cost),
        num_turns=int(_num(data.get("num_turns"))),
        duration_ms=_num(data.get("duration_ms")),
        is_error=bool(data.get("is_error")) or str(data.get("subtype", "success")) != "success",
        models=sorted(mu) if isinstance(mu, dict) else [],
    )
    rec["total_tokens"] = rec["input_tokens"] + rec["output_tokens"] + rec["cache_creation_tokens"] + rec["cache_read_tokens"]
    return rec


def aggregate(records):
    """records: [{task, arm, ok, ...parse_result 欄位}] → {(task, arm): 摘要}，數值取中位數。"""
    groups = {}
    for r in records:
        groups.setdefault((r["task"], r["arm"]), []).append(r)
    out = {}
    for key, rs in sorted(groups.items()):
        parsed = [r for r in rs if r.get("total_tokens") is not None]
        med = lambda f: statistics.median([r[f] for r in parsed]) if parsed else None  # noqa: E731
        out[key] = {
            "runs": len(rs),
            "success": sum(1 for r in rs if r.get("ok")),
            "total_tokens": med("total_tokens"),
            "input_tokens": med("input_tokens"),
            "output_tokens": med("output_tokens"),
            "cache_read_tokens": med("cache_read_tokens"),
            "cost_usd": med("cost_usd"),
            "num_turns": med("num_turns"),
        }
    return out


def _fmt(v, kind="int"):
    if v is None:
        return "—"
    if kind == "usd":
        return f"${v:.4f}"
    return f"{v:,.0f}"


def _delta(a, b):
    if not a or b is None:
        return "—"
    return f"{(b - a) / a * 100:+.0f}%"


def markdown(agg):
    lines = ["| Task | Arm | Success | Total tokens (median) | Δ vs without | Cost (median) | Δ cost | Turns |",
             "|---|---|---|---|---|---|---|---|"]
    tasks = sorted({t for t, _ in agg})
    for t in tasks:
        base = agg.get((t, "without"), {})
        for arm in ARMS:
            s = agg.get((t, arm))
            if not s:
                continue
            d_tok = _delta(base.get("total_tokens"), s["total_tokens"]) if arm == "with" else ""
            d_cost = _delta(base.get("cost_usd"), s["cost_usd"]) if arm == "with" else ""
            lines.append(f"| {t} | {arm} | {s['success']}/{s['runs']} | {_fmt(s['total_tokens'])} | {d_tok} | "
                         f"{_fmt(s['cost_usd'], 'usd')} | {d_cost} | {_fmt(s['num_turns'])} |")
    return "\n".join(lines)


def run_once(task, arm, args):
    work = tempfile.mkdtemp(prefix=f"chutora-bench-{task['id']}-{arm}-")
    home = tempfile.mkdtemp(prefix="chutora-bench-home-")
    try:
        shutil.copytree(os.path.join(HERE, "fixtures", task["fixture"]), work, dirs_exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CHUTORA"))}
        env.update(HOME=home, CLAUDE_CONFIG_DIR=os.path.join(home, ".claude"))
        cmd = build_cmd(task, arm, args.model, args.max_budget_usd)
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=args.timeout)
            out, code = p.stdout, p.returncode
        except subprocess.TimeoutExpired as e:
            out, code = (e.stdout or "") if isinstance(e.stdout, str) else "", -1
        rec = parse_result(out) or {}
        chk = subprocess.run(task["check"], cwd=work, capture_output=True, text=True, timeout=120)
        rec.update(task=task["id"], arm=arm, exit_code=code, ok=chk.returncode == 0,
                   wall_s=round(time.time() - t0, 1))
        return rec
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=int, default=3, help="每個任務、每組各跑幾次（預設 3）")
    ap.add_argument("--tasks", default="", help="只跑這些任務 id，逗號分隔")
    ap.add_argument("--model", default=None, help="傳給 claude --model，例如 opus")
    ap.add_argument("--max-budget-usd", type=float, default=1.0, help="每次執行的花費上限（傳給 --max-budget-usd）")
    ap.add_argument("--timeout", type=int, default=900, help="每次執行的秒數上限")
    ap.add_argument("--out", default=os.path.join(HERE, "results"), help="結果輸出資料夾")
    ap.add_argument("--dry-run", action="store_true", help="只列出會執行的指令，不呼叫模型")
    args = ap.parse_args(argv)

    tasks = load_tasks()
    if args.tasks:
        want = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in want]
    plan = [(t, arm, i) for t in tasks for arm in ARMS for i in range(args.runs)]
    if args.dry_run:
        print(f"Would run {len(plan)} claude -p calls ({len(tasks)} tasks × {len(ARMS)} arms × {args.runs} runs):")
        for t, arm, i in plan:
            print(f"- [{t['id']} / {arm} / run {i + 1}] " + " ".join(build_cmd(t, arm, args.model, args.max_budget_usd)))
        print("Each run uses a fresh temp copy of bench/fixtures/<task>, a temp HOME and CLAUDE_CONFIG_DIR, "
              "and needs ANTHROPIC_API_KEY. Nothing was run.")
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is required (runs are isolated from your ~/.claude login). Use --dry-run to preview.",
              file=sys.stderr)
        return 2
    if not shutil.which("claude"):
        print("claude CLI not found on PATH.", file=sys.stderr)
        return 2
    records = []
    for t, arm, i in plan:
        print(f"[{t['id']} / {arm} / run {i + 1}] ...", file=sys.stderr, flush=True)
        records.append(run_once(t, arm, args))
    agg = aggregate(records)
    os.makedirs(args.out, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(args.out, f"bench-{stamp}.json"), "w") as f:
        json.dump({"records": records, "summary": {f"{k[0]}/{k[1]}": v for k, v in agg.items()}}, f, indent=2)
    md = markdown(agg)
    with open(os.path.join(args.out, f"bench-{stamp}.md"), "w") as f:
        f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
