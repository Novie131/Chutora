#!/usr/bin/env python3
"""PostToolUse（mcp__*）hook：MCP 輸出瘦身。

Slack、資料庫、網頁這類 MCP 工具常回傳一大坨資料。超過門檻時，在進入 context 之前：
- JSON：長陣列保留前 N 筆並註明「另有 M 筆」、連續相同的項目合併、空值欄位（null、""、[]、{}）拿掉；
- 純文字、Markdown（例如使用說明、文件內容）預設一律不動：這類輸出通常每一行都有用，
  曾經發生把 connector 的 guide 說明砍掉 204 行的事。JSON 裡的長字串欄位預設也不截斷，理由相同。
  真的想瘦身純文字時，設 CHUTORA_MCP_TRIM_TEXT=1（或 ~/.claude/chutora/mcp-trim-text 寫 on），
  就會沿用 trim.py 的行規則並截斷 JSON 長字串。
原文一定另存到 ~/.claude/chutora/raw/<tool_use_id>.log，並在輸出最後寫明路徑。
回傳形狀照抄原本的（字串、content 陣列、或帶 content 的物件），圖片等非文字區塊不動，
用 PostToolUse 的 hookSpecificOutput.updatedMCPToolOutput 替換。

開關：CHUTORA_MCP_TRIM=0 關閉；/chutora mcp-trim on|off 寫入 ~/.claude/chutora/mcp-trim。
排除清單：CHUTORA_MCP_TRIM_EXCLUDE（逗號分隔）或 ~/.claude/chutora/mcp-trim-exclude（一行一個），
寫工具全名、前綴（例如 mcp__github__ 或 mcp__slack__read_thread），或只寫 server 名稱（例如 slack、
claude_ai_Notion，等同 mcp__<名稱>__）；/chutora mcp-trim exclude <server> 會幫你加。門檻依模式。真的瘦身時在觀察紀錄寫一筆 trimmed。任何例外都安靜放行。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from trim import add_stats, cfg_file, conf_dir, mode, observe_trimmed, save_raw_text, shrink  # noqa: E402

try:
    from compact import lang
except Exception:  # pragma: no cover
    lang = lambda: "en"  # noqa: E731

# 各模式：(超過幾字元才處理, 陣列保留幾筆, 字串欄位最長幾字元)
LIMITS = {
    "economy": (3000, 20, 800),
    "balanced": (4000, 30, 1500),
    "quality": (8000, 60, 3000),
}


def enabled():
    if os.environ.get("CHUTORA_MCP_TRIM", "").strip() == "0":
        return False
    return cfg_file("mcp-trim") != "off"


def text_trim_enabled():
    """純文字／Markdown 與 JSON 長字串要不要瘦身（預設不要）。"""
    if os.environ.get("CHUTORA_MCP_TRIM_TEXT", "").strip() == "1":
        return True
    return cfg_file("mcp-trim-text") == "on"


def exclude_patterns():
    pats = [p.strip() for p in os.environ.get("CHUTORA_MCP_TRIM_EXCLUDE", "").split(",") if p.strip()]
    try:
        with open(os.path.join(conf_dir(), "mcp-trim-exclude")) as f:
            pats += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except OSError:
        pass
    # 只寫 server 名稱（沒有 mcp__ 前綴）→ 視為 mcp__<名稱>__
    return [p if p.startswith("mcp__") else f"mcp__{p}__" for p in pats]


def excluded(tool):
    return any(tool == p or tool.startswith(p) for p in exclude_patterns())


def shrink_json(v, keep, max_str, st):
    """max_str 為 None 時不截斷字串（預設）。"""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if x is None or x == "" or x == [] or x == {}:
                st["dropped"] += 1
                continue
            out[k] = shrink_json(x, keep, max_str, st)
        return out
    if isinstance(v, list):
        items, prev, run = [], object(), 0
        for x in v:
            if x == prev:
                run += 1
                continue
            if run:
                items.append(f"… (same as above ×{run})" if lang() == "en" else f"…（與上一筆相同 ×{run}）")
                st["merged"] += run
                run = 0
            items.append(x)
            prev = x
        if run:
            items.append(f"… (same as above ×{run})" if lang() == "en" else f"…（與上一筆相同 ×{run}）")
            st["merged"] += run
        if len(items) > keep:
            rest = len(items) - keep
            st["items"] += rest
            items = items[:keep] + [f"… {rest} more items omitted" if lang() == "en" else f"…另有 {rest} 筆已略過"]
        return [shrink_json(x, keep, max_str, st) for x in items]
    if max_str is not None and isinstance(v, str) and len(v) > max_str:
        st["strings"] += 1
        cut = len(v) - max_str
        return v[:max_str] + (f"… ({cut} chars cut)" if lang() == "en" else f"…（截斷 {cut} 字元）")
    return v


def shrink_text(text, md):
    """回傳 (新文字, 說明) 或 None。"""
    limit, keep, max_str = LIMITS[md]
    if len(text) <= limit:
        return None
    text_too = text_trim_enabled()
    s = text.strip()
    if s[:1] in ("{", "["):
        try:
            obj = json.loads(s)
        except ValueError:
            obj = None
        if obj is not None:
            st = {"items": 0, "merged": 0, "strings": 0, "dropped": 0}
            new = json.dumps(shrink_json(obj, keep, max_str if text_too else None, st), ensure_ascii=False,
                             separators=(",", ":"))
            if len(new) < len(text):
                return new, st
            return None
    if not text_too:  # 純文字、Markdown：預設不動
        return None
    r = shrink(text, "noisy", md)
    if r:
        return r[0], {"lines": r[1]["skipped"]}
    return None


def note(path, details):
    d = details
    if lang() == "en":
        parts = []
        if d.get("items"): parts.append(f"{d['items']} list items omitted")
        if d.get("merged"): parts.append(f"{d['merged']} repeated items merged")
        if d.get("strings"): parts.append(f"{d['strings']} long strings cut")
        if d.get("dropped"): parts.append(f"{d['dropped']} empty fields dropped")
        if d.get("lines"): parts.append(f"{d['lines']} lines omitted")
        return (f"[Chutora MCP trim: {', '.join(parts) or 'trimmed'}. Full original: {path} (read it with the Read tool "
                f"if you need anything omitted). Turn off with CHUTORA_MCP_TRIM=0 or /chutora mcp-trim off.]")
    parts = []
    if d.get("items"): parts.append(f"略過 {d['items']} 筆陣列項目")
    if d.get("merged"): parts.append(f"合併 {d['merged']} 筆重複項目")
    if d.get("strings"): parts.append(f"截斷 {d['strings']} 個長字串")
    if d.get("dropped"): parts.append(f"拿掉 {d['dropped']} 個空欄位")
    if d.get("lines"): parts.append(f"略過 {d['lines']} 行")
    return (f"[Chutora MCP 瘦身：{'、'.join(parts) or '已瘦身'}。完整原文：{path}（需要被略過的內容時用 Read 讀取）。"
            f"可用 CHUTORA_MCP_TRIM=0 或 /chutora mcp-trim off 關閉。]")


def text_slots(resp):
    """找出可以瘦身的文字位置，回傳 (形狀, 區塊清單)。形狀：'str'、'list'、'dict'。"""
    if isinstance(resp, str):
        return "str", None
    blocks = resp if isinstance(resp, list) else (resp.get("content") if isinstance(resp, dict) else None)
    if isinstance(blocks, list) and all(isinstance(b, dict) for b in blocks):
        return ("list" if isinstance(resp, list) else "dict"), blocks
    return None, None


def process(data):
    tool = data.get("tool_name") or ""
    if not tool.startswith("mcp__") or not enabled() or excluded(tool):
        return None
    resp = data.get("tool_response")
    shape, blocks = text_slots(resp)
    if shape is None:
        return None
    md = mode()
    total_before = len(json.dumps(resp, ensure_ascii=False))
    if total_before <= LIMITS[md][0]:
        return None
    details, changed = {}, False
    if shape == "str":
        r = shrink_text(resp, md)
        if not r:
            return None
        new_resp, details, changed = r[0], r[1], True
    else:
        new_blocks = []
        for b in blocks:
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                r = shrink_text(b["text"], md)
                if r:
                    new_blocks.append(dict(b, text=r[0]))
                    for k, v in r[1].items():
                        details[k] = details.get(k, 0) + v
                    changed = True
                    continue
            new_blocks.append(b)
        if not changed:
            return None
        new_resp = new_blocks if shape == "list" else dict(resp, content=new_blocks)
    if total_before - len(json.dumps(new_resp, ensure_ascii=False)) < max(1000, total_before * 0.2):
        return None
    raw = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False, indent=2)
    path = save_raw_text(data.get("tool_use_id"), f"# {tool}\n# input: {json.dumps(data.get('tool_input'), ensure_ascii=False)}", raw)
    tag = note(path, details)
    if shape == "str":
        new_resp = new_resp + "\n" + tag
    else:
        blocks2 = list(new_resp if shape == "list" else new_resp["content"]) + [{"type": "text", "text": tag}]
        new_resp = blocks2 if shape == "list" else dict(new_resp, content=blocks2)
    saved = total_before - len(json.dumps(new_resp, ensure_ascii=False))
    if saved <= 0:
        return None
    add_stats(saved, "mcp", session_id=data.get("session_id"))
    observe_trimmed(data, total_before, saved, "mcp")
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": new_resp}}


def main():
    try:
        out = process(json.load(sys.stdin))
    except Exception:
        return
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
