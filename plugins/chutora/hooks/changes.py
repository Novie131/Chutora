#!/usr/bin/env python3
"""變更紀錄：claude-memory/changes.jsonl（沒有 claude-memory/ 時退回 auto memory 目錄的 changes.jsonl）。

每一行是一筆 JSON，只會追加、不改寫舊行：
- 新紀錄：{"id", "ts", "action", "summary", "restore_point", "notified", "user_response", "source", "session", ...}
  action         動作代號，例如 guard_ask、guard_deny（第 1 批只有危險守門會寫）
  summary        一句話說明（已遮罩金鑰、截短）
  restore_point  復原點位置（備份檔路徑、git stash／commit 等）；沒有就是 null
  notified       是否已告知使用者（true／false）
  user_response  使用者回應：null（還不知道）、approved、rejected、undone 或自由文字
- 更新：{"id": <原紀錄 id>, "ts", "update": {欄位: 新值}}；讀取時依序合併到原紀錄上。

API：changes_path()、record()、update()、read()。命令列：changes.py list [N]（唯讀）。
任何寫入失敗都安靜回傳 None，不擋工作。
"""
import json
import os
import re
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from redact import short  # noqa: E402

FIELDS = ("id", "ts", "action", "summary", "restore_point", "notified", "user_response", "source", "session")


def auto_memory_dir(project_dir, transcript_path=None):
    """auto memory 目錄：transcript 同層的 memory/，否則 ~/.claude/projects/<編碼後的路徑>/memory。"""
    if transcript_path:
        return os.path.join(os.path.dirname(transcript_path), "memory")
    enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_dir))
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", enc, "memory")


def changes_path(project_dir=None, transcript_path=None):
    pd = os.path.abspath(project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    mem = os.path.join(pd, "claude-memory")
    if os.path.isdir(mem):
        return os.path.join(mem, "changes.jsonl")
    return os.path.join(auto_memory_dir(pd, transcript_path), "changes.jsonl")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _append(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def record(action, summary, *, restore_point=None, notified=False, user_response=None, source="chutora",
           session=None, project_dir=None, transcript_path=None, path=None, **extra):
    """追加一筆紀錄，回傳它的 id；失敗回傳 None。"""
    try:
        rid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        obj = {"id": rid, "ts": _now(), "action": str(action), "summary": short(summary, 240),
               "restore_point": restore_point, "notified": bool(notified), "user_response": user_response,
               "source": source, "session": session}
        for k, v in extra.items():
            if k not in obj:
                obj[k] = short(v, 240) if isinstance(v, str) else v
        _append(path or changes_path(project_dir, transcript_path), obj)
        return rid
    except Exception:
        return None


def update(rid, *, project_dir=None, transcript_path=None, path=None, **fields):
    """對既有紀錄追加一筆更新（例如使用者回應、已通知）。失敗回傳 False。"""
    try:
        upd = {k: (short(v, 240) if isinstance(v, str) else v) for k, v in fields.items() if k not in ("id", "ts")}
        _append(path or changes_path(project_dir, transcript_path), {"id": rid, "ts": _now(), "update": upd})
        return True
    except Exception:
        return False


def read(*, project_dir=None, transcript_path=None, path=None, limit=None, action=None):
    """讀回所有紀錄（更新已合併），舊到新；壞掉的行略過。limit 取最後幾筆。"""
    p = path or changes_path(project_dir, transcript_path)
    items, order = {}, []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or not d.get("id"):
                    continue
                if "update" in d:
                    if d["id"] in items and isinstance(d["update"], dict):
                        items[d["id"]].update(d["update"])
                        items[d["id"]]["updated"] = d.get("ts")
                    continue
                if d["id"] not in items:
                    order.append(d["id"])
                items[d["id"]] = d
    except OSError:
        return []
    out = [items[i] for i in order]
    if action:
        out = [x for x in out if x.get("action") == action]
    return out[-limit:] if limit else out


def main(argv):
    if argv[:1] == ["list"]:
        n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 20
        print(changes_path())
        for x in read(limit=n):
            print(json.dumps(x, ensure_ascii=False))
        return 0
    print("usage: changes.py list [N]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
