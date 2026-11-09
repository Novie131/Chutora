#!/usr/bin/env python3
"""PreToolUse hook：危險守門（Bash 為主；Write／Edit／MultiEdit／NotebookEdit 檢查路徑，Read 只檢查金鑰檔）。

命中「永遠要問清單」時回傳標準 PreToolUse 決定：
  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"|"deny",
                          "permissionDecisionReason": "<雙語原因>"}}
- ask：交給 Claude Code 跳出確認（使用者看得到原因）；非互動（-p）沒有人能確認時，Claude Code 會當成拒絕。
- deny：非常明確的災難（rm -rf ~、rm -rf /、清掉整顆磁碟），任何權限模式都擋，原因回給 Claude。
  略過權限模式（permission_mode 為 bypassPermissions）下，確認視窗可能被跳過，所以備份不了的幾類
  （BYPASS_DENY：force push、刪專案外／家目錄的東西、DROP／TRUNCATE、terraform destroy、kubectl delete）也改成 deny。
沒命中就什麼都不輸出，照原本的權限流程走（守門只會收緊、不會放寬）。
唯一的例外是決策引擎（decide.py）：只在「守門沒命中」或「只命中可學的 git-reset-hard／git-clean」、
使用者明確說過這類以後可以自動、可復原且復原點建立成功時，才回 allow；其他規則、使用者規則與
略過權限模式的 deny 一律照守門，引擎碰不到。

指令解析：自己寫的小型 shell 斷詞（引號、跳脫、heredoc、$(...)、sh -c、sudo/env 等前綴），
所以 commit 訊息或 echo 裡「提到」危險指令不會被攔；解析不了時退回保守的整段比對。

使用者規則：~/.claude/chutora/always-ask，一行一條：
  <regex>          額外要問的規則（比對 Bash 指令全文，或檔案工具的路徑）
  deny: <regex>    額外直接擋下的規則
  !<規則 id>       移除一條預設規則（id 見 /chutora guard rules）
  # 開頭是註解
開關：CHUTORA_GUARD=0，或 /chutora guard off（寫入 ~/.claude/chutora/guard）。
被攔下的紀錄寫進 claude-memory/changes.jsonl（見 changes.py）。任何例外都安靜放行，不擋工具。
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from compact import lang
except Exception:  # pragma: no cover
    lang = lambda: "en"  # noqa: E731

HOME = os.path.expanduser("~")
# Cowork：使用者電腦上的 shell（mcp__remote-devices__device_bash）。它跑在使用者的 VM，不是這台機器，
# 所以用一個虛擬的家目錄判斷路徑：連接資料夾在 $HOME/mnt/<名稱>，預設 cwd 是 $HOME/mnt/outputs。
DEVICE_SHELL = re.compile(r"^mcp__.+__device_bash$")
DEVICE_HOME = "/__device__/home"
DEVICE_MNT = DEVICE_HOME + "/mnt"


def is_device_shell(tool):
    return bool(DEVICE_SHELL.match(tool or ""))

# 規則 id → (決定, 中文說明, 英文說明)
RULES = {
    "rm-catastrophe": ("deny", "刪除根目錄、家目錄或系統目錄（rm -rf / 或 ~ 這一類）", "deleting the root, home or a system directory (rm -rf / or ~ and the like)"),
    "disk-wipe": ("deny", "格式化或覆寫整顆磁碟（mkfs、dd of=/dev/…）", "formatting or overwriting a whole disk (mkfs, dd of=/dev/…)"),
    "force-push": ("ask", "強制推送（git push --force），會覆蓋遠端歷史", "force push (git push --force) rewrites remote history"),
    "push-main": ("ask", "直接推到 main／master", "pushing straight to main/master"),
    "rm-outside": ("ask", "刪除專案外的檔案或目錄", "deleting files or folders outside the project"),
    "rm-home": ("ask", "刪除家目錄底下、專案外的東西", "deleting something in your home folder, outside the project"),
    "rm-project-root": ("ask", "刪除整個專案目錄或 .git", "deleting the whole project folder or .git"),
    "rm-unresolved": ("ask", "刪除的路徑含有無法確認的變數（變數是空的就可能刪錯地方）", "the path to delete contains a variable that can't be checked (if it's empty the wrong thing gets deleted)"),
    "secret-file": ("ask", "讀寫 .env 或金鑰檔", "touching a .env or key file"),
    "sql-drop": ("ask", "DROP TABLE／DROP DATABASE／TRUNCATE", "DROP TABLE / DROP DATABASE / TRUNCATE"),
    "terraform-destroy": ("ask", "terraform destroy（刪掉雲端資源）", "terraform destroy (deletes cloud resources)"),
    "kubectl-delete": ("ask", "kubectl delete（刪掉叢集資源）", "kubectl delete (deletes cluster resources)"),
    "claude-settings": ("ask", "修改 Claude Code 設定（settings.json）或 Chutora 設定", "changing Claude Code settings (settings.json) or Chutora settings"),
    "git-reset-hard": ("ask", "git reset --hard（未提交的修改會消失）", "git reset --hard (uncommitted changes are lost)"),
    "self-grant": ("ask", "替自己開自動權限：/chutora ok … auto 或改寫 decisions.jsonl（要由使用者本人回覆）", "granting itself automatic permission: /chutora ok … auto or editing decisions.jsonl (the user must answer this personally)"),
    "git-clean": ("ask", "git clean -f（刪掉未追蹤的檔案）", "git clean -f (deletes untracked files)"),
}

# 略過權限模式（permission_mode == "bypassPermissions"，即 --dangerously-skip-permissions）下，
# 確認視窗可能被跳過；這幾類做了就沒有備份可以救回，所以由 ask 改成 deny。其他規則、其他模式不變。
BYPASS_DENY = {"force-push", "rm-outside", "rm-home", "sql-drop", "terraform-destroy", "kubectl-delete", "self-grant"}

WRAPPERS = {"sudo", "doas", "env", "time", "nohup", "nice", "ionice", "command", "builtin", "exec", "timeout",
            "stdbuf", "caffeinate", "xargs", "chronic", "unbuffer"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
SEARCHERS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "echo", "printf"}
READERS = {"cat", "less", "more", "head", "tail", "grep", "egrep", "rg", "ag", "wc", "ls", "stat", "file", "diff",
           "cmp", "jq", "bat", "nl", "md5", "md5sum", "shasum", "sha256sum", "test", "[", "realpath", "readlink"}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "deno", "bun"}
# find 只有帶這些動作時才會改東西或另外寫檔；沒有的話視為只讀（實測：只讀的 find ~/.claude/chutora 被誤判成改設定）
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}


EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}


def read_only_find(a):
    return bool(a) and base(a[0]) == "find" and not any(x in FIND_ACTIONS for x in a[1:])


def find_exec_commands(a):
    """find 的 -exec／-execdir／-ok／-okdir 子指令。回傳 [argv, …]；{} 代換成 find 的起點路徑，
    若有不含萬用字元的 -name／-iname 就代換成 起點/該名稱。子指令以 ; 或 + 或指令結尾為止。"""
    args = a[1:]
    starts = []
    for x in args:
        if x.startswith("-") or x in ("(", "!", ")"):
            break
        starts.append(x)
    starts = starts or ["."]
    names = [args[k + 1] for k, x in enumerate(args[:-1])
             if x in ("-name", "-iname") and not re.search(r"[*?\[]", args[k + 1]) and "/" not in args[k + 1]]
    targets = [st.rstrip("/") + "/" + n if st != "/" else "/" + n for st in starts for n in names] if names else starts
    out, k = [], 0
    while k < len(args):
        if args[k] in EXEC_FLAGS:
            j = k + 1
            while j < len(args) and args[j] not in (";", "+"):
                j += 1
            sub = args[k + 1:j]
            if sub:
                for t in targets:
                    out.append([w.replace("{}", t) for w in sub])
            k = j
        k += 1
    return out
WRITERS = {"cp", "mv", "rm", "tee", "truncate", "ln", "install", "rsync", "dd", "chmod", "chown", "unlink", "touch",
           "vi", "vim", "nano", "emacs", "code", "open", "ed", "ex"}
CATASTROPHIC_DIRS = {"/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/opt", "/proc", "/root", "/sbin", "/sys",
                     "/usr", "/var", "/home", "/Users", "/System", "/Library", "/Applications", "/Volumes",
                     "/private", "/private/var", "/private/etc", "/cores", "/nix", "/snap", "/srv", "/mnt"}
DISK = re.compile(r"\bof=/dev/(?:sd|hd|nvme|disk|rdisk|mmcblk|vd|xvd)\w*")


# ------------------------------------------------------------------ 開關與使用者規則
def conf_dir():
    return os.path.join(HOME, ".claude", "chutora")


def enabled():
    if os.environ.get("CHUTORA_GUARD", "").strip() == "0":
        return False
    try:
        with open(os.path.join(conf_dir(), "guard")) as f:
            return f.read().strip().lower() != "off"
    except OSError:
        return True


def user_rules():
    """回傳 (停用的預設規則 id 集合, [(決定, regex, 原始行)], [壞掉的行])。"""
    off, extra, bad = set(), [], []
    try:
        with open(os.path.join(conf_dir(), "always-ask"), encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return off, extra, bad
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("!"):
            off.add(s[1:].strip())
            continue
        decision = "ask"
        m = re.match(r"^(deny|ask)\s*:\s*(.+)$", s)
        if m:
            decision, s = m.group(1), m.group(2).strip()
        try:
            extra.append((decision, re.compile(s), ln))
        except re.error:
            bad.append(ln)
    return off, extra, bad


# ------------------------------------------------------------------ shell 斷詞
class Seg:
    __slots__ = ("argv", "redirs")

    def __init__(self):
        self.argv, self.redirs = [], []


def _match_paren(s, i):
    """s[i] 是 '(' 之後的位置；回傳對應 ')' 的位置（粗略處理引號），找不到回傳 -1。"""
    depth, q = 1, None
    while i < len(s):
        c = s[i]
        if q:
            if c == "\\" and q == '"':
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "\\":
            i += 2
            continue
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def tokenize(cmd, depth=0):
    """把指令切成 Seg 清單。不展開變數；$(...) 與反引號裡的指令另外當成獨立片段。"""
    segs, seg = [], Seg()
    word, started = [], False
    pending_redir = None
    heredocs = []
    i, n = 0, len(cmd)

    def end_word():
        nonlocal word, started, pending_redir
        if started:
            w = "".join(word)
            if pending_redir is not None:
                if pending_redir in ("<<", "<<-"):
                    heredocs.append((w, pending_redir == "<<-"))
                elif pending_redir in (">", ">>", ">|", "&>", "&>>"):
                    seg.redirs.append((pending_redir, w))
                elif pending_redir == "<in":
                    seg.redirs.append(("<", w))
                pending_redir = None
            else:
                seg.argv.append(w)
        word, started = [], False

    def end_seg():
        nonlocal seg
        end_word()
        if seg.argv or seg.redirs:
            segs.append(seg)
        seg = Seg()

    while i < n:
        c = cmd[i]
        if c in " \t":
            end_word()
            i += 1
            continue
        if c == "\n":
            end_seg()
            i += 1
            while heredocs:  # 跳過 heredoc 內文
                delim, strip_tabs = heredocs.pop(0)
                while i < n:
                    j = cmd.find("\n", i)
                    line = cmd[i:] if j < 0 else cmd[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delim:
                        break
            continue
        if c == "#" and not started:
            j = cmd.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                raise ValueError("unterminated quote")
            word.append(cmd[i + 1:j])
            started = True
            i = j + 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and cmd[j] != '"':
                if cmd[j] == "\\" and j + 1 < n and cmd[j + 1] in '"\\$`\n':
                    buf.append(cmd[j + 1])
                    j += 2
                    continue
                if cmd[j] == "$" and j + 1 < n and cmd[j + 1] == "(" and depth < 4:
                    k = _match_paren(cmd, j + 2)
                    if k > 0:
                        segs.extend(tokenize(cmd[j + 2:k], depth + 1))
                        buf.append("$(" + cmd[j + 2:k] + ")")
                        j = k + 1
                        continue
                buf.append(cmd[j])
                j += 1
            if j >= n:
                raise ValueError("unterminated quote")
            word.append("".join(buf))
            started = True
            i = j + 1
            continue
        if c == "\\":
            if i + 1 < n and cmd[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < n:
                word.append(cmd[i + 1])
                started = True
            i += 2
            continue
        if c == "$" and i + 1 < n and cmd[i + 1] == "(" and depth < 4:
            k = _match_paren(cmd, i + 2)
            if k > 0:
                inner = cmd[i + 2:k]
                if not inner.startswith("("):  # $(( 算術 )) 不是指令
                    segs.extend(tokenize(inner, depth + 1))
                word.append("$(" + inner + ")")
                started = True
                i = k + 1
                continue
        if c == "`" and depth < 4:
            j = cmd.find("`", i + 1)
            if j > 0:
                segs.extend(tokenize(cmd[i + 1:j], depth + 1))
                word.append("$(" + cmd[i + 1:j] + ")")
                started = True
                i = j + 1
                continue
        if c in ";&|()":
            two = cmd[i:i + 2]
            if c == "&" and two in ("&>",):
                end_word()
                three = cmd[i:i + 3]
                pending_redir = "&>>" if three == "&>>" else "&>"
                i += len(pending_redir)
                continue
            end_seg()
            i += 2 if two in ("&&", "||", ";;", "|&") else 1
            continue
        if c in "<>":
            fd_only = started and "".join(word).isdigit()
            if fd_only:
                word, started = [], False
            else:
                end_word()
            three, two = cmd[i:i + 3], cmd[i:i + 2]
            if three == "<<<":
                op = "<<<"
            elif three == "<<-":
                op = "<<-"
            elif two in ("<<", ">>", ">|", ">&", "<&", "<>"):
                op = two
            else:
                op = c
            i += len(op)
            if op in (">&", "<&"):
                m = re.match(r"\s*(\d+|-)", cmd[i:])
                if m:  # 2>&1 這類複製檔案描述子
                    i += m.end()
                    continue
                op = "&>"
            pending_redir = op if op not in ("<", "<>", "<<<") else "<in"
            continue
        word.append(c)
        started = True
        i += 1
    end_seg()
    return segs


def base(p):
    return os.path.basename(p.rstrip("/")) if p else p


def unwrap(argv):
    """去掉 VAR=1、sudo、env、timeout 30 這類前綴，回傳真正的指令 argv。"""
    a = list(argv)
    if a and all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", x) for x in a):
        return a  # 只有變數設定：留給 check_bash 記下來
    for _ in range(8):
        while a and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a[0]):
            a = a[1:]
        if not a:
            return a
        p = base(a[0])
        if p not in WRAPPERS:
            return a
        a = a[1:]
        if p in ("sudo", "doas"):
            while a and a[0].startswith("-"):
                takes = a[0] in ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U")
                a = a[2:] if takes else a[1:]
        elif p == "env":
            while a and (a[0].startswith("-") or "=" in a[0]):
                a = a[2:] if a[0] in ("-u", "-C", "-S") else a[1:]
        elif p == "nice":
            if a and a[0] == "-n":
                a = a[2:]
            elif a and re.match(r"^-\d+$", a[0]):
                a = a[1:]
        elif p == "timeout":
            while a and a[0].startswith("-"):
                a = a[2:] if a[0] in ("-s", "-k", "--signal", "--kill-after") else a[1:]
            a = a[1:]  # 時間長度
        elif p == "xargs":
            while a and a[0].startswith("-"):
                a = a[2:] if a[0] in ("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a") else a[1:]
        else:
            while a and a[0].startswith("-"):
                a = a[1:]
    return a


def expand_segments(cmd, depth=0):
    """斷詞並展開 sh -c "…"、eval "…"；回傳 Seg 清單。"""
    out = []
    for s in tokenize(cmd):
        a = unwrap(s.argv)
        s.argv = a
        out.append(s)
        if not a or depth > 3:
            continue
        p = base(a[0])
        if p in SHELLS:
            for k, arg in enumerate(a[1:], 1):
                if arg == "-c" or (arg.startswith("-") and not arg.startswith("--") and "c" in arg):
                    if k + 1 < len(a):
                        out.extend(expand_segments(a[k + 1], depth + 1))
                    break
        elif p == "eval" and len(a) > 1:
            out.extend(expand_segments(" ".join(a[1:]), depth + 1))
    return out


# ------------------------------------------------------------------ 路徑判斷
def temp_dirs(data):
    ds = {"/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp", "/var/folders", "/private/var/folders",
          tempfile.gettempdir()}
    for v in (os.environ.get("TMPDIR"), (data or {}).get("scratchpad_dir")):
        if v:
            ds.add(v)
    out = set()
    for d in ds:
        out.add(os.path.normpath(d))
        try:
            out.add(os.path.realpath(d))
        except OSError:
            pass
    return out


def under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def resolve(raw, cwd, local_vars=None):
    """回傳 (正規化後的絕對路徑, 是否含無法確認的變數, 是否有 glob)。glob 只取前面的固定部分。
    local_vars：同一串指令裡前面設定過的變數（例如 tmp=$(mktemp -d)）。"""
    p = raw
    for k, v in (local_vars or {}).items():
        p = re.sub(r"\$\{?" + re.escape(k) + r"\}?(?![A-Za-z0-9_])", lambda _m, v=v: v, p)
    if p.startswith("~"):
        p = HOME + p[1:] if p == "~" or p.startswith("~/") else p
    p = re.sub(r"\$\{?HOME\}?", HOME, p)
    p = re.sub(r"\$\{?(?:CLAUDE_PROJECT_DIR|PWD)\}?", cwd, p)
    unresolved = False
    if "$" in p:
        p2 = os.path.expandvars(p)
        if "$(" in p2 or re.search(r"\$\{?\w", p2):
            unresolved = True
        p = p2
    m = re.search(r"[*?\[]", p)
    globbed = bool(m)
    if m:
        p = p[:m.start()]
        p = p if p.endswith("/") or not p else os.path.dirname(p)
        p = p or "."
    full = os.path.normpath(os.path.join(cwd, p))
    return full, unresolved, globbed


def real(p):
    try:
        return os.path.realpath(p)
    except OSError:
        return p


def rm_targets(a):
    """回傳 (recursive, targets) 或 None（不是刪除指令）。"""
    p = base(a[0])
    if p in ("rm", "unlink", "rmdir", "shred", "srm"):
        rec, force, targets, opts = p == "rmdir", False, [], True
        for x in a[1:]:
            if opts and x == "--":
                opts = False
                continue
            if opts and x.startswith("--"):
                rec = rec or x in ("--recursive", "--dir")
                force = force or x == "--force"
                continue
            if opts and x.startswith("-") and len(x) > 1:
                rec = rec or "r" in x or "R" in x
                force = force or "f" in x
                continue
            targets.append(x)
        return rec, targets
    if p == "find":
        args = a[1:]
        starts = []
        for x in args:
            if x.startswith("-") or x in ("(", "!", ")"):
                break
            starts.append(x)
        deleting = "-delete" in args
        for k, x in enumerate(args):
            if x in ("-exec", "-execdir", "-ok", "-okdir") and k + 1 < len(args) and base(args[k + 1]) in ("rm", "shred", "unlink"):
                deleting = True
        if deleting:
            return True, starts or ["."]
    return None


def check_rm(a, cwd, root, data, hits, local_vars=None):
    r = rm_targets(a)
    if not r:
        return
    rec, targets = r
    tmp = temp_dirs(data)
    home_n, root_n0 = os.path.normpath(HOME), os.path.normpath(root)
    device = bool((data or {}).get("_device"))
    for t in targets:
        if not t:
            continue
        full, unresolved, globbed = resolve(t, cwd, local_vars)
        root_n = root_n0
        if device and under(full, DEVICE_MNT) and full != DEVICE_MNT:  # 每個連接資料夾各自算一個專案
            root_n = os.path.join(DEVICE_MNT, full[len(DEVICE_MNT) + 1:].split("/")[0])
        rp = real(full)
        cands = {full, rp}
        if any(c in CATASTROPHIC_DIRS or c in (home_n, real(home_n)) or c == os.path.dirname(home_n) for c in cands):
            if (rec or globbed) and base(a[0]) != "find":  # find -delete 只刪符合條件的，交給下面的「問」
                hits.append(("rm-catastrophe", t))
                continue
        if unresolved:
            hits.append(("rm-unresolved", t))
            continue
        in_home = any(under(c, home_n) for c in cands)
        if not in_home and any(under(c, d) and c != d for c in cands for d in tmp):  # 暫存目錄底下（本身不算）
            continue
        is_find = base(a[0]) == "find"
        if (full == os.path.join(root_n, ".git") or any(under(root_n, c) for c in cands)) and not (
                is_find and full in (root_n, real(root_n))):  # 專案本身、它的上層或 .git（find . -delete 只刪符合條件的）
            hits.append(("rm-project-root", t))
            continue
        if any(under(c, root_n) or under(c, real(root_n)) for c in cands):
            continue
        if any(under(c, home_n) for c in cands):
            hits.append(("rm-home", t))
        else:
            hits.append(("rm-outside", t))


GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}


def git_parts(a):
    """git [全域選項] 子指令 參數…；回傳 (子指令, 參數, -C 指定的目錄或 None)。"""
    i, cdir = 1, None
    while i < len(a):
        x = a[i]
        if x in GIT_OPTS_WITH_VALUE:
            if x == "-C" and i + 1 < len(a):
                cdir = a[i + 1]
            i += 2
            continue
        if x.startswith("-"):
            i += 1
            continue
        return x, a[i + 1:], cdir
    return None, [], cdir


def current_branch(cwd):
    sys.path.insert(0, HERE)
    try:
        from projectid import git_root
    except Exception:
        return None
    r, _ = git_root(cwd)
    if not r:
        return None
    g = os.path.join(r, ".git")
    try:
        if os.path.isfile(g):
            with open(g) as f:
                m = re.match(r"\s*gitdir:\s*(.+?)\s*$", f.read())
            g = m.group(1) if m else g
            g = g if os.path.isabs(g) else os.path.join(r, g)
        with open(os.path.join(g, "HEAD")) as f:
            head = f.read().strip()
    except OSError:
        return None
    m = re.match(r"^ref:\s*refs/heads/(.+)$", head)
    return m.group(1) if m else None


PUSH_OPTS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def check_git(a, cwd, hits):
    sub, args, cdir = git_parts(a)
    if not sub:
        return
    if sub == "push":
        pos, i, force, every = [], 0, False, False
        while i < len(args):
            x = args[i]
            if x in PUSH_OPTS_WITH_VALUE:
                i += 2
                continue
            if x.startswith("--"):
                if x in ("--force", "--mirror") or x.startswith("--force-with-lease") or x == "--force-if-includes":
                    force = force or x != "--force-if-includes"
                if x in ("--all", "--mirror", "--branches"):
                    every = True
            elif x.startswith("-") and len(x) > 1:
                if "f" in x[1:]:
                    force = True
            else:
                pos.append(x)
            i += 1
        refspecs = pos[1:]
        if any(r.startswith("+") for r in refspecs):
            force = True
        if force:
            hits.append(("force-push", " ".join(a[:8])))
        dsts = []
        for r in refspecs:
            r = r.lstrip("+")
            dst = r.split(":", 1)[1] if ":" in r else r
            dsts.append(re.sub(r"^refs/heads/", "", dst))
        if every or any(d in ("main", "master") for d in dsts):
            hits.append(("push-main", " ".join(a[:8])))
        elif not refspecs or any(d == "HEAD" for d in dsts):
            wd = os.path.normpath(os.path.join(cwd, os.path.expanduser(cdir))) if cdir else cwd
            if current_branch(wd) in ("main", "master"):
                hits.append(("push-main", " ".join(a[:8])))
    elif sub == "reset":
        if "--hard" in args:
            hits.append(("git-reset-hard", " ".join(a[:6])))
    elif sub == "clean":
        for x in args:
            if x == "--force" or (x.startswith("-") and not x.startswith("--") and "f" in x):
                hits.append(("git-clean", " ".join(a[:6])))
                break


SECRET_NAME = re.compile(
    r"(?i)^(?:\.env(?:\.(?!example$|sample$|template$|dist$|defaults?$)[\w.-]+)?|[\w.-]+\.env|"
    r"id_(?:rsa|dsa|ecdsa|ed25519)(?:_sk)?|[\w.-]+\.(?:pem|key|p12|pfx|jks|keystore|ppk|kdbx)|"
    r"\.netrc|\.pgpass|\.git-credentials|\.npmrc|\.pypirc|credentials(?:\.json)?)$")


def is_secret(path):
    if not path:
        return False
    b = os.path.basename(str(path).rstrip("/"))
    if b.lower() in ("credentials", "credentials.json"):
        return "/.aws/" in str(path) or "/.config/gcloud/" in str(path) or b.lower() == "credentials.json"
    return bool(SECRET_NAME.match(b))


def settings_target(path, root):
    """這個路徑是 Claude Code 或 Chutora 的設定嗎？"""
    if not path:
        return False
    p = os.path.normpath(os.path.expanduser(str(path)))
    if base(p) == "apply_settings.py" and real(p) in own_apply_settings():
        return True  # 守門不再問「跑這支腳本」，所以改寫這支腳本本身要問
    claude = os.path.join(HOME, ".claude")
    if p in (os.path.join(claude, "settings.json"), os.path.join(claude, "settings.local.json")):
        return True
    chut = os.path.join(claude, "chutora")
    if under(p, chut):
        rel = os.path.relpath(p, chut).split(os.sep)[0]
        return rel not in ("raw", "projects", "activity", "statusline")  # 這些是資料，不是設定
    if root:
        pc = os.path.join(os.path.normpath(root), ".claude")
        if p in (os.path.join(pc, "settings.json"), os.path.join(pc, "settings.local.json")):
            return True
    return False


def own_apply_settings():
    """route-setup 自己的設定腳本（只認 Chutora 自己目錄裡的那一份）的實際路徑集合。
    plugin／--plugin-dir／install.sh --link：<plugin 根目錄>/skills/route-setup/apply_settings.py；
    install.sh 複製安裝（hooks 在 ~/.claude/hooks/chutora）：~/.claude/skills/route-setup/apply_settings.py。"""
    here = real(HERE)
    out = {real(os.path.join(os.path.dirname(here), "skills", "route-setup", "apply_settings.py"))}
    if here == real(os.path.join(HOME, ".claude", "hooks", "chutora")):
        out.add(real(os.path.join(HOME, ".claude", "skills", "route-setup", "apply_settings.py")))
    return {p for p in out if os.path.isfile(p)}


def is_own_apply(a, cwd):
    """python3 <Chutora 自己的 apply_settings.py> …（同名、但不在 Chutora 目錄裡的腳本不算）。"""
    if len(a) < 2 or base(a[0]) not in INTERPRETERS or base(a[1]) != "apply_settings.py":
        return False
    full, unresolved, globbed = resolve(a[1], cwd)
    return not unresolved and not globbed and real(full) in own_apply_settings()


def check_words(s, cwd, root, hits):
    a = s.argv
    words = [w for w in a[1:]] + [t for _, t in s.redirs]
    prog = base(a[0]) if a else ""
    # 金鑰檔：參數、--x=值、重導向目標
    for w in words:
        for v in [w] + ([w.split("=", 1)[1]] if "=" in w else []):
            if is_secret(v):
                hits.append(("secret-file", v))
                break
        else:
            continue
        break
    # 決策引擎的回饋要由使用者本人給：Claude 自己跑 ok … auto 或改寫 decisions.jsonl 都要問
    if any(base(t) == "decisions.jsonl" for _, t in s.redirs if _ != "<") or (
            prog not in READERS and prog not in ("git",) and any(base(w) == "decisions.jsonl" for w in a[1:])) or (
            prog in INTERPRETERS and any("decisions.jsonl" in w for w in a[1:])):
        hits.append(("self-grant", "decisions.jsonl"))
    for script in ("chutora.py", "decide.py"):
        if prog == script or (a and len(a) > 1 and base(a[1]) == script):
            args = [x.lower() for x in (a[2:] if prog != script else a[1:])]
            if args[:1] == ["ok"] and any(x in ("auto", "自動") for x in args[2:]):
                hits.append(("self-grant", " ".join(a[:5])))
    # 設定檔：寫入類動作才問
    if prog == "chutora.py" or (a and len(a) > 1 and base(a[1]) == "chutora.py"):
        args = a[2:] if base(a[0]) != "chutora.py" else a[1:]
        if args and args[0].lower() in ("guard", "observe", "decide") and any(x.lower() in ("off", "關", "關閉") for x in args[1:]):
            hits.append(("claude-settings", " ".join(a[:4])))
        return
    targets = [t for op, t in s.redirs if op != "<" and settings_target(resolve(t, cwd)[0], root)]
    own = is_own_apply(a, cwd) if a else False
    if own or (a and len(a) > 1 and base(a[1]) == "apply_settings.py" and any(x.startswith("--set") for x in a[2:])):
        # route-setup 已經逐項問過使用者，而且只會跑 Chutora 自己目錄裡的這支腳本：不再問第二次。
        # 同名但在別處的腳本、或同一行另外重導向到設定檔，照樣要問。
        if targets or not own:
            hits.append(("claude-settings", " ".join(a[:4])))
        return
    pos = [w for w in a[1:] if not w.startswith("-")]
    if prog in ("cp", "rsync", "install", "ln", "scp"):  # 只有最後一個參數（目的地）會被改
        pos = pos[-1:]
    mentioned = [w for w in pos if settings_target(resolve(w, cwd)[0], root)]
    if targets:
        hits.append(("claude-settings", targets[0]))
    elif mentioned and prog not in READERS and prog not in ("awk", "git") and not read_only_find(a) and not (
            prog == "find" and not any(x in FIND_ACTIONS - EXEC_FLAGS for x in a[1:])):  # 只有 -exec 的 find：由子指令判斷
        if prog != "sed" or any(x.startswith("-i") or x == "--in-place" for x in a[1:]):
            hits.append(("claude-settings", mentioned[0]))
    elif prog in INTERPRETERS and any(re.search(r"\.claude/(?:settings(?:\.local)?\.json|chutora/)", w) for w in a[1:]):
        hits.append(("claude-settings", prog))


SQL_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "duckdb", "clickhouse-client", "cockroach", "pgcli",
               "mycli", "litecli"}
SQL_DROP = re.compile(r"(?i)\b(?:drop\s+(?:table|database|schema)|truncate\s+(?:table\s+)?[\w`\"'])")


def check_segment(s, cwd, root, data, hits, local_vars=None):
    a = s.argv
    if a:
        p = base(a[0])
        if p == "git":
            check_git(a, cwd, hits)
        check_rm(a, cwd, root, data, hits, local_vars)
        if p in ("terraform", "tofu", "terragrunt") and ("destroy" in a[1:] or ("apply" in a[1:] and any(x in ("-destroy", "--destroy") for x in a))):
            hits.append(("terraform-destroy", " ".join(a[:4])))
        if p == "kubectl" and "delete" in a[1:]:
            hits.append(("kubectl-delete", " ".join(a[:6])))
        if re.match(r"^mkfs(\.\w+)?$", p) or p in ("diskutil",) and any(x in ("eraseDisk", "eraseVolume", "zeroDisk") for x in a[1:]):
            hits.append(("disk-wipe", " ".join(a[:4])))
        if p == "dd" and any(DISK.search(x) for x in a[1:]):
            hits.append(("disk-wipe", " ".join(a[:4])))
        if p not in SEARCHERS and not (p == "git" and git_parts(a)[0] in ("grep", "log", "commit", "show", "tag", "notes")):
            if any(SQL_DROP.search(w) for w in a[1:]):
                hits.append(("sql-drop", " ".join(a[:3])))
    check_words(s, cwd, root, hits)
    if a and base(a[0]) == "find" and any(x in EXEC_FLAGS for x in a[1:]):
        for sub in find_exec_commands(a):  # -exec 後面的子指令照一般指令檢查（{} 已代換成起點路徑）
            sub = unwrap(sub)
            if not sub:
                continue
            ss = Seg()
            ss.argv = sub
            check_segment(ss, cwd, root, data, hits, local_vars)
            if base(sub[0]) in SHELLS:
                for k, arg in enumerate(sub[1:], 1):
                    if arg == "-c" or (arg.startswith("-") and not arg.startswith("--") and "c" in arg):
                        if k + 1 < len(sub):
                            for inner in expand_segments(sub[k + 1]):
                                check_segment(inner, cwd, root, data, hits, local_vars)
                        break


def is_read_only_command(cmd):
    """這條 shell 指令只讀嗎？每個指令段的程式都屬 READERS（或 cd）或沒有 -exec／-delete 的 find，
    且沒有寫檔的重導向（/dev/null 除外）。單一指令段、管線、&& 串接都可以。解析不了就當作不是只讀。"""
    try:
        segs = expand_segments(cmd)
    except Exception:
        return False
    if not segs:
        return False
    for s in segs:
        if any(op != "<" and t != "/dev/null" for op, t in s.redirs):
            return False
        a = s.argv
        if not a:
            continue
        if all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", x) for x in a):
            return False
        p = base(a[0])
        if p == "cd" or p in READERS or read_only_find(a):
            continue
        return False
    return any(s.argv for s in segs)


def check_bash(cmd, data, root=None, cwd=None):
    root = os.path.normpath(root or os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    cwd = os.path.normpath(cwd or data.get("cwd") or root)
    hits = []
    try:
        segs = expand_segments(cmd)
    except Exception:
        segs = None
    if segs is None:  # 解析不了（例如引號沒關）：退回保守的整段比對
        fallback = [
            ("force-push", r"\bgit\b[^\n;&|]*\bpush\b[^\n;&|]*(?:\s--force\b|\s-[a-zA-Z]*f\b)"),
            ("git-reset-hard", r"\bgit\b[^\n;&|]*\breset\b[^\n;&|]*--hard\b"),
            ("rm-catastrophe", r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+(?:/|~/?|\$HOME/?)(?:\s|$|\*)"),
            ("sql-drop", r"(?i)\bdrop\s+(?:table|database)\b"),
        ]
        for rid, rx in fallback:
            if re.search(rx, cmd):
                hits.append((rid, cmd[:80]))
        return hits
    local_vars = {}
    # SQL 用戶端：指令經由管線或 heredoc 送進去，所以看整段原文
    if any(s.argv and base(s.argv[0]) in SQL_CLIENTS for s in segs) and SQL_DROP.search(cmd):
        hits.append(("sql-drop", cmd[:60]))
    for s in segs:
        a = s.argv
        if not a and s.redirs:
            check_words(s, cwd, root, hits)
            continue
        if a and all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", x) for x in a):  # 只有變數設定的片段
            for x in a:
                k, v = x.split("=", 1)
                if re.match(r"^\$\(\s*mktemp\b", v):
                    local_vars[k] = os.path.join(tempfile.gettempdir(), "chutora-mktemp")
                elif "$" not in v:
                    local_vars[k] = v
            continue
        if a and base(a[0]) in ("cd", "pushd") and len(a) <= 2:
            tgt = a[1] if len(a) > 1 else "~"
            if tgt != "-":
                full, unresolved, _ = resolve(tgt, cwd, local_vars)
                if not unresolved:
                    cwd = full
            continue
        check_segment(s, cwd, root, data, hits, local_vars)
    return hits


def check_device_bash(cmd, data):
    """Cowork 的 device_bash：同一套規則，但路徑以使用者電腦（虛擬家目錄）判斷。"""
    global HOME
    saved = HOME
    HOME = DEVICE_HOME
    try:
        d = dict(data, _device=True, cwd=DEVICE_MNT + "/outputs", scratchpad_dir=None)
        return check_bash(cmd, d, root=DEVICE_MNT, cwd=DEVICE_MNT + "/outputs")
    finally:
        HOME = saved


def check_path_tool(tool, inp, data):
    root = os.path.normpath(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    hits = []
    if not path:
        return hits
    if is_secret(path):
        hits.append(("secret-file", path))
    if tool != "Read" and settings_target(path, root):
        hits.append(("claude-settings", path))
    if tool != "Read" and base(str(path)) == "decisions.jsonl":
        hits.append(("self-grant", path))
    return hits


# ------------------------------------------------------------------ 決定與輸出
def decide(data):
    """回傳 (決定, [(規則 id, 命中內容)], 使用者規則行) 或 None。"""
    tool = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}
    if not isinstance(inp, dict):
        return None
    if tool == "Bash" or is_device_shell(tool):
        subject = inp.get("command") or ""
        if not isinstance(subject, str) or not subject.strip():
            return None
        hits = check_device_bash(subject, data) if is_device_shell(tool) else check_bash(subject, data)
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Read"):
        subject = inp.get("file_path") or inp.get("notebook_path") or ""
        hits = check_path_tool(tool, inp, data)
    else:
        return None
    off, extra, _ = user_rules()
    hits = [h for h in hits if h[0] not in off]
    user_hit = []
    for decision, rx, line in extra:
        if isinstance(subject, str) and rx.search(subject):
            user_hit.append((decision, line.strip()))
    if not hits and not user_hit:
        return None
    seen, uniq = set(), []
    for h in hits:
        if h[0] not in seen:
            seen.add(h[0])
            uniq.append(h)
    deny = any(RULES[h[0]][0] == "deny" for h in uniq) or any(d == "deny" for d, _ in user_hit)
    return ("deny" if deny else "ask"), uniq, user_hit


def bypass_upgrade(decision, hits, mode):
    """略過權限模式下，BYPASS_DENY 裡的規則由 ask 改成 deny。回傳 (決定, 是否因此改成 deny)。"""
    if decision == "ask" and mode == "bypassPermissions" and any(h[0] in BYPASS_DENY for h in hits):
        return "deny", True
    return decision, False


def reason(decision, hits, user_hit, mode, bypass=False):
    en = lang() == "en"
    if bypass:  # 把被升級成 deny 的規則排在前面
        hits = [h for h in hits if h[0] in BYPASS_DENY] + [h for h in hits if h[0] not in BYPASS_DENY]
    labels = [RULES[h[0]][2 if en else 1] + f" [{h[0]}]" for h in hits[:3]]
    labels += [("your rule: " if en else "你的規則：") + line for _, line in user_hit[:2]]
    what = "; ".join(labels) if en else "；".join(labels)
    unattended = mode in ("bypassPermissions", "dontAsk")
    if bypass:
        if en:
            msg = (f"Chutora guard blocked this: {what}. The session is in bypass-permissions mode "
                   "(--dangerously-skip-permissions), so a confirmation prompt may be skipped, and this kind of "
                   "operation can't be undone from a backup, so it is blocked outright instead of asked. If it is "
                   "really needed, tell the user exactly what you wanted to run and why: they can run it themselves "
                   "in a terminal, or turn off bypass-permissions mode and try again. Don't look for a way around it.")
            return msg + " Adjust the list in ~/.claude/chutora/always-ask; turn off with CHUTORA_GUARD=0."
        msg = (f"Chutora 守門已擋下：{what}。因為目前是略過權限模式（--dangerously-skip-permissions），"
               "確認視窗可能被跳過，而這類操作做了沒有備份可以救回，所以直接擋下、不再只是詢問。"
               "真的要做的話，把你想執行的指令和原因告訴使用者：請使用者自己在終端機執行，"
               "或關掉略過權限模式後再試一次。不要另找方法繞過。")
        return msg + "調整清單：~/.claude/chutora/always-ask；關閉：CHUTORA_GUARD=0。"
    if en:
        if decision == "deny":
            msg = (f"Chutora guard blocked this: {what}. This is never run automatically. If it is really needed, "
                   "tell the user exactly what you wanted to run and why, and let them run it themselves.")
        else:
            msg = (f"Chutora guard: this is on the always-ask list: {what}. Allow it only if this is what you want.")
            if unattended:
                msg += (" (The current permission mode skips prompts, so this was not run. Explain to the user what "
                        "you wanted to do and let them decide; don't look for a way around it.)")
        return msg + " Adjust the list in ~/.claude/chutora/always-ask; turn off with CHUTORA_GUARD=0."
    if decision == "deny":
        msg = (f"Chutora 守門已擋下：{what}。這類操作不會自動執行；真的需要的話，"
               "把你想執行的指令和原因告訴使用者，由使用者自己執行。")
    else:
        msg = f"Chutora 守門：這在「永遠要問」清單上：{what}。確認是你要的再允許。"
        if unattended:
            msg += "（目前的權限模式不會跳出確認，所以這次沒有執行。請向使用者說明你想做什麼，由使用者決定；不要另找方法繞過。）"
    return msg + "調整清單：~/.claude/chutora/always-ask；關閉：CHUTORA_GUARD=0。"


def log_change(data, decision, hits, user_hit, bypass=False):
    try:
        import changes
        from projectid import project_data_dir
        tool = data.get("tool_name")
        inp = data.get("tool_input") or {}
        subj = inp.get("command") if (tool == "Bash" or is_device_shell(tool)) else (inp.get("file_path") or inp.get("notebook_path"))
        rules = [h[0] for h in hits] + ["user:" + line for _, line in user_hit]
        try:
            import observe
            observe.append({"ts": observe.now(), "session": data.get("session_id"), "agent": observe.agent_of(data),
                            "signal": "guard_" + decision, "tool": tool, "summary": observe.short(subj, 160),
                            "rules": rules, "bypass_deny": True if bypass else None}, data.get("cwd"))
        except Exception:
            pass
        rid = changes.record("guard_" + decision, f"{tool}: {subj}", notified=True, source="guard",
                             session=data.get("session_id"), project_dir=os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd"),
                             transcript_path=data.get("transcript_path"), tool=tool, rules=rules,
                             permission_mode=data.get("permission_mode"), tool_use_id=data.get("tool_use_id"))
        if rid and decision == "ask" and data.get("tool_use_id"):
            # 之後同一個 tool_use_id 真的執行了（PostToolUse），observe.py 會把它標成 approved
            d = project_data_dir(data.get("cwd"))
            p = os.path.join(d, "guard-pending.json")
            try:
                with open(p) as f:
                    pend = json.load(f)
            except (OSError, ValueError):
                pend = {}
            pend[data["tool_use_id"]] = {"id": rid, "changes": changes.changes_path(
                os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd"), data.get("transcript_path"))}
            for k in list(pend)[:-50]:
                pend.pop(k, None)
            tmp = p + ".tmp"
            with open(tmp, "w") as f:
                json.dump(pend, f)
            os.replace(tmp, p)
        return rid
    except Exception:
        return None


# 決策引擎可以學的規則（可復原：git stash create／快照）。其他規則、使用者規則、略過權限模式的 deny 永遠照守門。
LEARNABLE_RULES = {"git-reset-hard", "git-clean"}


def engine():
    try:
        import decide as d
        return d
    except Exception:
        return None


def process(data):
    if not enabled() or not isinstance(data, dict):
        return None
    r = decide(data)
    mode = data.get("permission_mode")
    if not r:
        if is_device_shell(data.get("tool_name")):  # 復原點只能建在這台機器，使用者電腦上的指令不交給決策引擎
            return None
        eng = engine()  # 守門沒命中：決策引擎看是不是已學會可自動的類型（例如專案內刪除）
        try:
            return eng.pretool(data, None) if eng else None
        except Exception:
            return None
    decision, hits, user_hit = r
    decision, bypass = bypass_upgrade(decision, hits, mode)
    device = is_device_shell(data.get("tool_name"))
    learnable = not device and decision == "ask" and not bypass and not user_hit and hits and all(h[0] in LEARNABLE_RULES for h in hits)
    eng = engine() if learnable else None
    if eng:
        try:
            out = eng.pretool(data, hits)
            if out:
                return out
        except Exception:
            pass
    rid = log_change(data, decision, hits, user_hit, bypass)
    why = reason(decision, hits, user_hit, mode, bypass)
    if eng and rid:
        why += eng.note_ask(data, hits, rid)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": why}}


def main():
    try:
        out = process(json.load(sys.stdin))
    except Exception:
        return
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))


def explain(cmd, cwd=None):
    """除錯用：python3 guard.py --explain '<指令>'"""
    data = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd or os.getcwd()}
    return decide(data)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--explain":
        print(explain(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--rules":
        off, extra, bad = user_rules()
        for rid, (d, zh, en) in RULES.items():
            print(f"{rid}\t{d}\t{'off' if rid in off else 'on'}\t{en if lang() == 'en' else zh}")
        for d, _, line in extra:
            print(f"user\t{d}\ton\t{line.strip()}")
        for line in bad:
            print(f"invalid\t-\t-\t{line.strip()}")
    else:
        main()
