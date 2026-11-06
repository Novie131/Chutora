#!/usr/bin/env python3
"""記憶檔的身分資料（YAML 開頭區塊）讀寫工具。只用標準函式庫，只支援下面用到的 YAML 子集。

格式（放在記憶檔最上面，兩行 --- 之間）：

    ---
    id: mem-20261107-a1b2c3          # 唯一 id
    created: 2026-11-07T10:00:00+0800
    last_used: 2026-11-07T10:00:00+0800
    confidence: 0.7                  # 0～1：使用者親口說的 0.9 以上，推測的 0.5 左右
    source: user                     # user／observed／handoff／research／inferred／imported
    bound_files:                     # 這條記憶依據的檔案與指紋（內容 sha256 前 12 字元）
      - path: src/app.py
        sha: 3f2a9c0d11ee
    version: 1
    supersedes: null                 # 取代的舊記憶 id
    status: active                   # active／stale／superseded／archived
    ---

既有檔案的其他欄位（例如 auto memory 的 name、description、type）讀取時保留、寫回時照原樣放在後面。
規則：既有記憶檔不改寫；write_new() 只建立新檔，檔案已存在就拒絕。
命令列：memmeta.py new <path> --source S [--bind 檔案 ...] [--confidence 0.7] [--supersedes ID] < 內文
        memmeta.py show <path>　　memmeta.py check <path> [--root 專案根目錄]
"""
import hashlib
import json
import os
import re
import sys
import time
import uuid

KEYS = ("id", "created", "last_used", "confidence", "source", "bound_files", "version", "supersedes", "status")
SOURCES = ("user", "observed", "handoff", "research", "inferred", "imported")
STATUSES = ("active", "stale", "superseded", "archived")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_id():
    return "mem-" + time.strftime("%Y%m%d-") + uuid.uuid4().hex[:6]


# ------------------------------------------------------------------ YAML 子集
def _scalar(s):
    s = s.strip()
    if s in ("", "~", "null", "Null", "NULL"):
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d*", s):
        return float(s)
    if s.startswith('"'):
        try:
            return json.loads(s)
        except ValueError:
            return s
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    return s


def _strip_comment(s):
    # 引號外的「 #」之後是註解
    q = None
    for i, c in enumerate(s):
        if q:
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s


def _emit(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{},&*!|>'\"%@`]|^\s|\s$|^[-?]", s) or _scalar(s) != s:
        return json.dumps(s, ensure_ascii=False)
    return s


def split(text):
    """回傳 (開頭區塊文字或 None, 內文)。"""
    if not text.startswith("---"):
        return None, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return None, text


def parse_front(front):
    """回傳 [(key, value, raw_lines)]；看不懂的值 value 為 _RAW，寫回時用 raw_lines。"""
    out, cur = [], None
    for line in front.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            if cur:
                cur[2].append(line)
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            cur = [m.group(1), None, [line], _strip_comment(m.group(2)).strip()]
            out.append(cur)
            continue
        if cur:
            cur[2].append(line)
    result = []
    for key, _, raw, first in out:
        body = [ln for ln in raw[1:] if ln.strip() and not ln.lstrip().startswith("#")]
        if first or not body:
            result.append((key, _scalar(first) if not body else _RAW, raw))
            continue
        # 區塊清單：- scalar 或 - k: v（後面縮排的 k: v 屬於同一項）
        items, ok = [], True
        for ln in body:
            s = _strip_comment(ln).strip()
            if s.startswith("- "):
                s = s[2:].strip()
                m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", s)
                items.append({m.group(1): _scalar(m.group(2))} if m else _scalar(s))
            elif s == "-":
                items.append(None)
            else:
                m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", s)
                if m and items and isinstance(items[-1], dict):
                    items[-1][m.group(1)] = _scalar(m.group(2))
                else:
                    ok = False
                    break
        result.append((key, items if ok else _RAW, raw))
    return result


class _Raw:
    pass


_RAW = _Raw()


def parse(text):
    """回傳 (meta dict, 內文)。看不懂的欄位放在 meta["_raw"][key]（原始行），寫回時照抄。"""
    front, body = split(text)
    meta = {}
    if front is None:
        return meta, body
    for key, value, raw in parse_front(front):
        if value is _RAW:
            meta.setdefault("_raw", {})[key] = raw
        else:
            meta[key] = value
    return meta, body


def dump(meta, body=""):
    raw = meta.get("_raw") or {}
    lines = ["---"]
    keys = [k for k in KEYS if k in meta] + [k for k in meta if k not in KEYS and k != "_raw"]
    for k in keys:
        v = meta[k]
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
                continue
            lines.append(f"{k}:")
            for it in v:
                if isinstance(it, dict):
                    first = True
                    for ik, iv in it.items():
                        lines.append(("  - " if first else "    ") + f"{ik}: {_emit(iv)}")
                        first = False
                else:
                    lines.append(f"  - {_emit(it)}")
        else:
            lines.append(f"{k}: {_emit(v)}")
    for k, rl in raw.items():
        if k not in meta:
            lines.extend(rl)
    lines.append("---")
    return "\n".join(lines) + "\n" + (body or "")


# ------------------------------------------------------------------ 身分資料
def fingerprint(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:12]
    except OSError:
        return None


def new_meta(source="user", bound_files=(), root=None, confidence=0.7, supersedes=None, version=None, extra=None):
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    c = float(confidence)
    if not 0 <= c <= 1:
        raise ValueError("confidence must be between 0 and 1")
    root = os.path.abspath(root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    bf = []
    for p in bound_files or ():
        full = p if os.path.isabs(p) else os.path.join(root, p)
        rel = os.path.relpath(full, root) if os.path.abspath(full).startswith(root + os.sep) else full
        bf.append({"path": rel, "sha": fingerprint(full)})
    t = now()
    m = {"id": new_id(), "created": t, "last_used": t, "confidence": round(c, 2), "source": source,
         "bound_files": bf, "version": int(version or 1), "supersedes": supersedes, "status": "active"}
    if extra:
        for k, v in extra.items():
            m.setdefault(k, v)
    return m


def superseding(old_meta, **kw):
    """取代舊記憶的新身分資料：version＋1、supersedes 指向舊 id。舊檔不動（呼叫者自行決定要不要標 superseded）。"""
    kw.setdefault("source", old_meta.get("source") or "user")
    kw.setdefault("confidence", old_meta.get("confidence") or 0.7)
    return new_meta(supersedes=old_meta.get("id"), version=int(old_meta.get("version") or 1) + 1, **kw)


def touched(meta):
    """回傳 last_used 更新為現在的新 dict（不寫檔）。"""
    m = dict(meta)
    m["last_used"] = now()
    return m


def has_identity(meta):
    return bool(meta.get("id")) and "version" in meta


def check(meta, root=None):
    """比對 bound_files 指紋，回傳變動或不見的檔案清單 [(path, 舊指紋, 新指紋)]。"""
    root = os.path.abspath(root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    changed = []
    for it in meta.get("bound_files") or []:
        if not isinstance(it, dict) or not it.get("path"):
            continue
        p = it["path"]
        cur = fingerprint(p if os.path.isabs(p) else os.path.join(root, p))
        if cur != it.get("sha"):
            changed.append((p, it.get("sha"), cur))
    return changed


def write_new(path, body, meta):
    """只建立新檔；檔案已存在就丟 FileExistsError（不改寫既有記憶檔）。"""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        f.write(dump(meta, body if body.startswith("\n") else "\n" + body))
    return path


def read_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse(f.read())


# ------------------------------------------------------------------ CLI
def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]

    def opt(name, many=False, default=None):
        vals, i = [], 0
        while i < len(args):
            if args[i] == name and i + 1 < len(args):
                vals.append(args[i + 1])
                i += 2
                continue
            i += 1
        return vals if many else (vals[-1] if vals else default)

    pos = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))]
    if not pos:
        print("missing <path>")
        return 2
    path = pos[0]
    if cmd == "new":
        meta = new_meta(source=opt("--source", default="user"), bound_files=opt("--bind", many=True),
                        root=opt("--root"), confidence=opt("--confidence", default=0.7), supersedes=opt("--supersedes"))
        try:
            write_new(path, sys.stdin.read() if not sys.stdin.isatty() else "", meta)
        except FileExistsError:
            print(f"refused: {path} already exists (existing memory files are never rewritten)")
            return 1
        print(meta["id"])
        return 0
    if cmd == "show":
        meta, _ = read_file(path)
        meta.pop("_raw", None)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0
    if cmd == "check":
        meta, _ = read_file(path)
        ch = check(meta, opt("--root"))
        for p, old, new in ch:
            print(f"changed: {p} {old} -> {new}")
        print("ok" if not ch else f"{len(ch)} bound file(s) changed")
        return 0 if not ch else 1
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
