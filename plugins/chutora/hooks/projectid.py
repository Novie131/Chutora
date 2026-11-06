"""專案 id 與每個專案的資料目錄（observe.py、changes.py 共用）。只用標準函式庫、不跑 git 指令。

專案 id 依序：
1. 起點目錄：CLAUDE_PROJECT_DIR → hook 輸入的 cwd → 目前目錄；
2. 往上找 git repo 根目錄（.git 是資料夾，或 worktree 的 .git 檔），讀它的 config：
   有 remote "origin"（沒有就取第一個 remote）→ 正規化後的 remote URL 取 sha256 前 12 字元；
3. 沒有 remote → repo 根目錄路徑的 sha256 前 12 字元；
4. 不在 git repo 裡 → 起點目錄路徑的 sha256 前 12 字元。
同一個 repo 在不同機器、不同 clone 位置會得到同一個 id（只要 remote 相同）。
"""
import hashlib
import os
import re


def conf_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "chutora")


def start_dir(cwd=None):
    d = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()
    return os.path.abspath(os.path.expanduser(d))


def git_root(start):
    """回傳 (repo 根目錄, git 共用目錄) 或 (None, None)。"""
    d = os.path.abspath(start)
    for _ in range(64):
        g = os.path.join(d, ".git")
        if os.path.isdir(g):
            return d, g
        if os.path.isfile(g):  # worktree／submodule：.git 是一行 "gitdir: <path>"
            try:
                with open(g, encoding="utf-8", errors="replace") as f:
                    m = re.match(r"\s*gitdir:\s*(.+?)\s*$", f.read())
            except OSError:
                m = None
            if m:
                gd = m.group(1)
                gd = gd if os.path.isabs(gd) else os.path.normpath(os.path.join(d, gd))
                common = gd
                try:
                    with open(os.path.join(gd, "commondir"), encoding="utf-8") as f:
                        c = f.read().strip()
                    common = c if os.path.isabs(c) else os.path.normpath(os.path.join(gd, c))
                except OSError:
                    pass
                return d, common
            return d, None
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None, None


def remote_url(gitdir):
    """從 git config 讀 remote URL：優先 origin，沒有就第一個 remote。"""
    if not gitdir:
        return None
    try:
        with open(os.path.join(gitdir, "config"), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    remotes, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'^\[\s*remote\s+"([^"]+)"\s*\]$', s)
        if m:
            cur = m.group(1)
            continue
        if s.startswith("["):
            cur = None
            continue
        if cur:
            m = re.match(r"^url\s*=\s*(.+)$", s)
            if m and cur not in remotes:
                remotes[cur] = m.group(1).strip()
    if "origin" in remotes:
        return remotes["origin"]
    return next(iter(remotes.values()), None)


def normalize_url(url):
    """git@github.com:A/b.git、https://user:tok@github.com/A/b → github.com/a/b（拿掉帳密與 .git）。"""
    u = url.strip()
    m = re.match(r"^[\w.-]+@([\w.-]+):(.+)$", u)  # scp 形式
    if m:
        host, path = m.group(1), m.group(2)
    else:
        u = re.sub(r"^[a-zA-Z][\w+.-]*://", "", u)
        u = re.sub(r"^[^@/]*@", "", u)  # 帳密
        host, _, path = u.partition("/")
        host = re.sub(r":\d+$", "", host)
    path = re.sub(r"\.git/?$", "", path.strip("/"))
    return (host.lower() + "/" + path).lower()


def _h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def project_info(cwd=None):
    """回傳 {"id", "root", "remote"}；remote 已正規化（不含帳密），沒有就是 None。"""
    start = start_dir(cwd)
    root, gitdir = git_root(start)
    if root:
        url = remote_url(gitdir)
        if url:
            n = normalize_url(url)
            return {"id": _h(n), "root": root, "remote": n}
        return {"id": _h(root), "root": root, "remote": None}
    return {"id": _h(start), "root": start, "remote": None}


def project_id(cwd=None):
    return project_info(cwd)["id"]


def project_data_dir(cwd=None, create=True):
    """~/.claude/chutora/projects/<id>/；第一次建立時寫一份 meta.json 說明這是哪個專案。"""
    info = project_info(cwd)
    d = os.path.join(conf_dir(), "projects", info["id"])
    if create:
        os.makedirs(d, exist_ok=True)
        meta = os.path.join(d, "meta.json")
        if not os.path.exists(meta):
            try:
                import json
                with open(meta, "w", encoding="utf-8") as f:
                    json.dump({"root": info["root"], "remote": info["remote"]}, f, ensure_ascii=False)
            except OSError:
                pass
    return d
