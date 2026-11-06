#!/usr/bin/env python3
"""PostToolUse（Read）hook：讀檔去重。

同一個 context 裡再次讀到「同一檔案、同一範圍、內容完全相同」時，把 Claude 收到的結果換成一行說明，
請它參考先前那次讀取，不再把整份內容重送一次。

Claude Code 自 2.1.86 起內建類似機制（重複讀取未變更的檔案時回傳 file_unchanged），但它由遠端旗標控制，
社群回報 2.1.286 之後很多 session 不再觸發（anthropics/claude-code#100265）。所以這個 hook 只在內建機制
沒有出手、而 Claude 又收到完整內容時才動作；內建回 file_unchanged 時什麼都不做。

安全規則（寧可不去重）：
- context 分開算：主對話與每個子 agent（hook 輸入的 agent_id）各自一份紀錄，絕不跨 context。
- 先前那次讀取的結果必須還在「目前這條對話鏈」上：讀 transcript，從最新一筆沿 parentUuid 往回走，
  找得到那次的 tool_use_id 才去重。壓縮、/clear、/rewind 之後舊結果不在鏈上，自然不會去重。
  transcript 讀不到、格式看不懂，一律不去重。
- 內容雜湊必須相同；範圍（offset/limit、起始行、行數）必須相同；圖片、PDF、notebook、被截斷的讀取不處理；
  小檔（不到 MIN_CHARS 字元）不處理。

判定重讀時在觀察紀錄寫一筆 reread（專案內的相對路徑或專案外路徑的雜湊、第幾次；見 observe.py）。
開關：CHUTORA_DEDUP=0 關閉；/chutora dedup on|off 寫入 ~/.claude/chutora/dedup。任何例外都安靜放行。
"""
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from trim import add_stats, cfg_file, conf_dir  # noqa: E402

try:
    import observe
except Exception:  # pragma: no cover
    observe = None

try:
    from compact import lang
except Exception:  # pragma: no cover
    lang = lambda: "en"  # noqa: E731

MIN_CHARS = 1500
KEEP_SESSIONS = 20


def enabled():
    if os.environ.get("CHUTORA_DEDUP", "").strip() == "0":
        return False
    return cfg_file("dedup") != "off"


def state_path():
    return os.path.join(conf_dir(), "dedup-state.json")


def load_state():
    try:
        with open(state_path()) as f:
            st = json.load(f)
            return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(st):
    sessions = st.get("sessions") or {}
    for sid in sorted(sessions, key=lambda s: sessions[s].get("_t", 0))[:-KEEP_SESSIONS]:
        del sessions[sid]
    st["sessions"] = sessions
    os.makedirs(conf_dir(), exist_ok=True)
    tmp = state_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, state_path())


def transcript_for(data):
    """主對話用 transcript_path；子 agent 優先用它自己的 transcript（<session>/subagents/agent-<id>.jsonl）。"""
    tp = data.get("transcript_path") or ""
    aid = data.get("agent_id")
    if aid and tp:
        sid = data.get("session_id") or os.path.basename(tp)[:-6]
        cand = os.path.join(os.path.dirname(tp), sid, "subagents", f"agent-{aid}.jsonl")
        if os.path.isfile(cand):
            return cand
    return tp


def chain_tool_ids(path):
    """回傳目前對話鏈上出現過的 tool_use id 集合；讀不到或看不懂就回傳 None。"""
    try:
        nodes, last = {}, None
        with open(path, errors="ignore") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                u = d.get("uuid")
                if not u:
                    continue
                ids = set()
                m = d.get("message")
                if isinstance(m, dict) and isinstance(m.get("content"), list):
                    for b in m["content"]:
                        if isinstance(b, dict):
                            if b.get("type") == "tool_use" and b.get("id"):
                                ids.add(b["id"])
                            elif b.get("type") == "tool_result" and b.get("tool_use_id"):
                                ids.add(b["tool_use_id"])
                nodes[u] = (d.get("parentUuid"), ids)
                last = u
    except OSError:
        return None
    if last is None:
        return None
    seen, out, cur = set(), set(), last
    while cur and cur in nodes and cur not in seen:
        seen.add(cur)
        parent, ids = nodes[cur]
        out |= ids
        cur = parent
    return out


def stub(path, n, first_id):
    if lang() == "en":
        return (f"[Chutora dedup: {path} is unchanged and this is the same range you already read earlier in this "
                f"conversation (read #{n}; first result: tool_use {first_id}). Refer to that earlier result instead of "
                f"re-reading. If you no longer have it, read a different range or turn this off with CHUTORA_DEDUP=0 "
                f"or /chutora dedup off.]")
    return (f"[Chutora 去重：{path} 沒有變更，而且跟這段對話先前讀過的範圍相同（第 {n} 次讀取；第一次的結果在 "
            f"tool_use {first_id}）。請直接參考那次的內容，不必重讀。如果那次的內容已經不在了，改讀不同範圍，"
            f"或用 CHUTORA_DEDUP=0、/chutora dedup off 關閉。]")


def process(data):
    if data.get("tool_name") != "Read" or not enabled():
        return None
    resp = data.get("tool_response")
    if not isinstance(resp, dict) or resp.get("type") != "text":
        return None
    f = resp.get("file")
    if not isinstance(f, dict) or not isinstance(f.get("content"), str) or f.get("truncatedByTokenCap"):
        return None
    content = f["content"]
    if len(content) < MIN_CHARS:
        return None
    sid = data.get("session_id") or ""
    ctx = data.get("agent_id") or "main"
    ti = data.get("tool_input") or {}
    key = "|".join(str(x) for x in (f.get("filePath") or ti.get("file_path"), ti.get("offset"), ti.get("limit"),
                                    f.get("startLine"), f.get("numLines"), f.get("totalLines")))
    h = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
    tuid = data.get("tool_use_id") or ""
    st = load_state()
    sess = st.setdefault("sessions", {}).setdefault(sid, {})
    sess["_t"] = time.time()
    seen = sess.setdefault(ctx, {})
    prev = seen.get(key)
    out = None
    if prev and prev.get("hash") == h and prev.get("id"):
        ids = chain_tool_ids(transcript_for(data))
        if ids is not None and prev["id"] in ids:
            prev["n"] = int(prev.get("n", 1)) + 1
            text = stub(f.get("filePath") or ti.get("file_path"), prev["n"], prev["id"])
            new_file = dict(f, content=text, numLines=1)
            out = {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                          "updatedToolOutput": dict(resp, file=new_file)}}
            add_stats(len(content) - len(text), "dedup", session_id=data.get("session_id"))
            if observe:  # 觀察紀錄：重讀（專案內記相對路徑，專案外只記路徑雜湊）
                try:
                    observe.note(data, "reread", n=prev["n"], saved_chars=len(content) - len(text),
                                 **observe.where(f.get("filePath") or ti.get("file_path"), data.get("cwd")))
                except Exception:
                    pass
    if out is None:
        seen[key] = {"hash": h, "id": tuid, "n": 1}
    save_state(st)
    return out


def main():
    try:
        out = process(json.load(sys.stdin))
    except Exception:
        return
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
