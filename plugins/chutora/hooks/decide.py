#!/usr/bin/env python3
"""決策引擎：有限選項的信心分數、校準、自動化門檻、復原點與回饋。只用標準函式庫。

信心分數（不呼叫模型）：
  p_i = w·(n_i+α)/(N+kα) + (1−w)·c_i，w = N/(N+m)
  n_i 相似紀錄裡選過 i 的次數（每筆乘上相似度與權重），N 總和，k 選項數，α=1、m=5；
  c_i 主對話給的估計（--claude），沒有就平均分配；使用者明確說過「這類以後自動／先問我」時，
  以最近一次相似（≥0.8）的明確偏好當 c（0.9 給該選項），因為使用者的話比 Claude 的猜測準。
相似度：規則式加權比對情境特徵（類型必須相同；category、action、path、branch、tracked、regen、project），
  只採相似度 ≥ 0.6 的紀錄。
校準：每次知道結果就記一筆、算 Brier 分數；同類型的預測依 0.1 分桶，樣本 ≥5 的桶依實際命中率往回修。
門檻：可復原且無影響 0.70、可復原但有影響 0.85、不可復原（或不確定）永不自動；
  省錢 −0.05、品質 +0.05；沒有相似歷史時 +0.10；24 小時內復原過的相似情境不自動。
沒空選（--unattended）：不可復原且有影響 → 不做、記成待辦；最高 <0.5 且不可復原 → 待辦；否則選最高者並記理由。

紀錄：claude-memory/decisions.jsonl（沒有 claude-memory/ 時與 changes.jsonl 同在 auto memory 目錄）。
  {"id","ts","type","options","features","raw","probs","best","threshold","recoverable","impact","basis",
   "auto","change_id","outcome":null,...}；結果以 {"id","update":{"outcome","weight","feedback","brier","resolved_ts"}} 追加。

命令列（主對話用 Bash 呼叫）：
  decide.py score --type T --options a,b [--claude a=0.7,b=0.3] [--feature k=v]… [--path P]…
                  [--recoverable yes|no] [--impact yes|no] [--remote] [--unattended] [--no-record]
  decide.py record <決策 id> <結果>
  decide.py snapshot [--config] [--git] [--summary 說明] <路徑>…   → 建復原點並記進 changes.jsonl
  decide.py undo <變更 id>
  decide.py pending | changes [N] | ok <id|all> [auto|ask] | stats
hook（說明按需帶入，平常不加 token）：
  decide.py notify   UserPromptSubmit：有待確認動作 → 請 Claude 回覆結尾附一行；使用者把決定交給 Claude
                     （「你決定」「都可以」「up to you」…）→ 帶精簡用法
  decide.py ask      PreToolUse(AskUserQuestion)：有相關的過去答案才帶一行建議，並在建議選項的說明後面附註
  （記下 AskUserQuestion 的答案由 observe.py 在 PostToolUse 呼叫 ask_learn()）
開關：CHUTORA_DECIDE=0，或 ~/.claude/chutora/decide 寫 off（只停掉 hook 的自動判斷；命令列照常可用）。
"""
import argparse
import glob as globmod
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changes  # noqa: E402

try:
    from compact import lang
except Exception:  # pragma: no cover
    lang = lambda: "en"  # noqa: E731

ALPHA, M = 1.0, 5.0
SIM_MIN = 0.6
PREF_SIM, PREF_PRIOR, SIMPLE_SIM = 0.8, 0.9, 0.95
COLD_BONUS = 0.10
BASE_THRESHOLD = {False: 0.70, True: 0.85}  # key：有沒有影響
MODE_SHIFT = {"economy": -0.05, "balanced": 0.0, "quality": 0.05}
UNDO_WEIGHT, UNDO_COOLDOWN = 3.0, 24 * 3600
CAL_MIN, CAL_K = 5, 10
AUTO_TYPE = "auto_run"
LEARNABLE = {"rm-in-project", "git-reset-hard", "git-clean"}
PENDING_ACTIONS = {"auto_allow", "unattended_run", "approved_run", "auto_cli"}
W = {"category": 0.3, "action": 0.15, "path": 0.25, "branch": 0.1, "tracked": 0.1, "regen": 0.1, "project": 0.1}
REGEN_DIRS = {"build", "dist", "out", "target", "node_modules", "__pycache__", ".cache", ".pytest_cache",
              ".mypy_cache", ".ruff_cache", ".next", ".nuxt", ".parcel-cache", "coverage", "htmlcov", ".tox",
              ".gradle", ".turbo", ".svelte-kit", ".eggs", ".nyc_output", ".angular", ".expo", "DerivedData"}
REGEN_SUFFIX = (".pyc", ".pyo", ".o", ".class", ".egg-info")


def T(zh, en):
    return en if lang() == "en" else zh


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_id():
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


# ------------------------------------------------------------------ 設定與路徑
def conf_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "chutora")


def engine_enabled():
    if os.environ.get("CHUTORA_DECIDE", "").strip() == "0":
        return False
    try:
        with open(os.path.join(conf_dir(), "decide")) as f:
            return f.read().strip().lower() != "off"
    except OSError:
        return True


def mode():
    m = (os.environ.get("CHUTORA_MODE") or "").strip().lower()
    if not m:
        try:
            with open(os.path.join(conf_dir(), "mode")) as f:
                m = re.sub(r"[^a-z]", "", f.read().lower())
        except OSError:
            m = ""
    return m if m in MODE_SHIFT else "balanced"


def project_dir(data=None):
    return os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or (data or {}).get("cwd") or os.getcwd())


def decisions_path(pd=None, transcript=None):
    return os.path.join(os.path.dirname(changes.changes_path(pd, transcript)), "decisions.jsonl")


def load_decisions(pd=None, transcript=None, path=None):
    return changes.read(path=path or decisions_path(pd, transcript))


# ------------------------------------------------------------------ 相似度、機率、校準
def _match(k, x, y):
    if x == y:
        return 1.0
    if k == "path" and isinstance(x, str) and isinstance(y, str):
        xs = {p.split("/")[0] for p in x.split(",")}
        ys = {p.split("/")[0] for p in y.split(",")}
        if xs & ys:
            return 0.6 * len(xs & ys) / len(xs | ys)
    return 0.0


def similarity(a, b):
    """0～1。類型（type）不同一律 0；只有一邊有的特徵算不相符。"""
    a, b = a or {}, b or {}
    if a.get("type") != b.get("type"):
        return 0.0
    keys = (set(a) | set(b)) - {"type"}
    if not keys:
        return 1.0
    tot = got = 0.0
    for k in keys:
        w = W.get(k, 0.1)
        tot += w
        if k in a and k in b:
            got += w * _match(k, a[k], b[k])
    return got / tot if tot else 1.0


def norm_prior(options, prior=None):
    if prior:
        vals = {o: max(0.0, float(prior.get(o, 0) or 0)) for o in options}
        s = sum(vals.values())
        if s > 0:
            return {o: v / s for o, v in vals.items()}
    return {o: 1.0 / len(options) for o in options}


def mix(options, counts, prior=None, alpha=ALPHA, m=M):
    """p_i = w·(n_i+α)/(N+kα) + (1−w)·c_i；回傳 (機率, N, w)。"""
    k = len(options)
    n = sum(max(0.0, counts.get(o, 0.0)) for o in options)
    w = n / (n + m) if n + m > 0 else 0.0
    c = norm_prior(options, prior)
    return {o: w * (max(0.0, counts.get(o, 0.0)) + alpha) / (n + k * alpha) + (1 - w) * c[o] for o in options}, n, w


def gather(decisions, feats, options, now=None):
    """從歷史算 n_i；另外找最近一次相似的明確偏好、24 小時內的復原。"""
    now = now or time.time()
    counts = {o: 0.0 for o in options}
    pref, cooldown, best_sim = None, False, 0.0
    for d in decisions:
        o = d.get("outcome")
        if o not in counts:
            continue
        s = similarity(feats, d.get("features"))
        if s < SIM_MIN:
            continue
        try:
            wt = float(d.get("weight") or 1.0)
        except (TypeError, ValueError):
            wt = 1.0
        counts[o] += s * wt
        t = d.get("resolved_ts") or 0
        if d.get("feedback") in ("auto", "ask", "undo") and s >= PREF_SIM:
            if pref is None or t >= pref[0]:
                pref = (t, o, s)
        if d.get("feedback") == "undo" and now - t < UNDO_COOLDOWN:
            cooldown = True
        best_sim = max(best_sim, s)
    return counts, pref, cooldown, best_sim


def _bucket(p):
    return min(int(p * 10), 9)


def calibrate(probs, dtype, decisions):
    """分桶校準：同類型過去預測 raw p 在同一桶（0.1 寬）、樣本 ≥CAL_MIN 時，往實際命中率修。"""
    pairs = []
    for d in decisions:
        if d.get("type") != dtype or d.get("outcome") is None or not isinstance(d.get("raw"), dict):
            continue
        for o, p in d["raw"].items():
            try:
                pairs.append((float(p), 1.0 if d["outcome"] == o else 0.0))
            except (TypeError, ValueError):
                pass
    out, info = {}, {}
    for o, p in probs.items():
        b = [(q, y) for q, y in pairs if _bucket(q) == _bucket(p)]
        if len(b) >= CAL_MIN:
            mp, obs = sum(q for q, _ in b) / len(b), sum(y for _, y in b) / len(b)
            p2 = p - (mp - obs) * len(b) / (len(b) + CAL_K)
            info[o] = {"bucket": _bucket(p) / 10, "n": len(b), "pred": round(mp, 3), "actual": round(obs, 3)}
        else:
            p2 = p
        out[o] = min(max(p2, 1e-3), 1 - 1e-3)
    s = sum(out.values())
    return {o: v / s for o, v in out.items()}, info


def brier(probs, outcome):
    return sum((float(p) - (1.0 if o == outcome else 0.0)) ** 2 for o, p in (probs or {}).items())


def threshold(recoverable, impact, mode_name=None, cold=False):
    """回傳自動執行門檻；不可復原或不確定 → None（永不自動）。"""
    if recoverable is not True:
        return None
    t = BASE_THRESHOLD[bool(impact)] + MODE_SHIFT.get(mode_name or mode(), 0.0) + (COLD_BONUS if cold else 0.0)
    return round(t, 4)


def score(dtype, options, features=None, claude=None, recoverable=None, impact=True, decisions=(),
          mode_name=None, unattended=False, now=None):
    options = [str(o) for o in options if str(o)]
    if len(options) < 2:
        raise ValueError("need at least two options")
    feats = dict(features or {})
    feats["type"] = dtype
    counts, pref, cooldown, best_sim = gather(decisions, feats, options, now)
    prior, prior_src = claude, ("claude" if claude else "uniform")
    if pref and pref[1] in options:
        rest = (1 - PREF_PRIOR) / (len(options) - 1)
        prior, prior_src = {o: (PREF_PRIOR if o == pref[1] else rest) for o in options}, "user:" + pref[1]
    raw, n, w = mix(options, counts, prior)
    probs, cal = calibrate(raw, dtype, decisions)
    best = max(options, key=lambda o: (probs[o], -options.index(o)))
    cold = n == 0
    thr = threshold(recoverable, impact, mode_name, cold)
    res = {"type": dtype, "options": options, "features": feats, "counts": {o: round(v, 3) for o, v in counts.items()},
           "n": round(n, 3), "w": round(w, 3), "prior": prior_src, "raw": {o: round(v, 4) for o, v in raw.items()},
           "probs": {o: round(v, 4) for o, v in probs.items()}, "calibration": cal, "best": best,
           "p_best": round(probs[best], 4), "threshold": thr, "cold": cold, "cooldown": cooldown,
           "recoverable": recoverable, "impact": bool(impact), "mode": mode_name or mode(),
           "simple": bool(pref and pref[1] == best and pref[2] >= SIMPLE_SIM)}
    if thr is not None and probs[best] >= thr and not cooldown:
        res["action"] = "auto"
        res["reason"] = T(f"「{best}」機率 {probs[best]:.2f} ≥ 門檻 {thr:.2f}，可復原", f"'{best}' at {probs[best]:.2f} ≥ threshold {thr:.2f}, recoverable")
    elif unattended:
        if recoverable is not True and impact:
            res["action"] = "skip-todo"
            res["reason"] = T("不可復原且有影響：沒人確認時不做，記成待辦", "not recoverable and has impact: not done unattended, saved as a to-do")
        elif probs[best] < 0.5 and recoverable is not True:
            res["action"] = "skip-todo"
            res["reason"] = T(f"最高只有 {probs[best]:.2f}（<0.5）且不可復原：記成待辦", f"best is only {probs[best]:.2f} (<0.5) and not recoverable: saved as a to-do")
        else:
            res["action"] = "auto-unattended"
            res["reason"] = T(f"沒人可問：選機率最高的「{best}」（{probs[best]:.2f}）", f"nobody to ask: picked the most likely '{best}' ({probs[best]:.2f})")
    else:
        res["action"] = "ask"
        why = (T("不可復原，永不自動", "not recoverable, never automatic") if thr is None else
               T("最近復原過相似動作", "a similar action was undone recently") if cooldown else
               T(f"「{best}」機率 {probs[best]:.2f} < 門檻 {thr:.2f}", f"'{best}' at {probs[best]:.2f} < threshold {thr:.2f}"))
        res["reason"] = why
    return res


# ------------------------------------------------------------------ 決策紀錄
def record_decision(res, *, path=None, pd=None, transcript=None, **extra):
    """把 score() 的結果記成一筆決策（結果待定），回傳 id；失敗回傳 None。"""
    try:
        did = "d" + new_id()
        obj = {"id": did, "ts": now_iso(), "outcome": None}
        for k in ("type", "options", "features", "raw", "probs", "best", "threshold", "recoverable", "impact",
                  "action", "reason", "prior", "n"):
            if k in res:
                obj[k] = res[k]
        obj["basis"] = res.get("basis")
        obj.update(extra)
        changes._append(path or decisions_path(pd, transcript), obj)
        return did
    except Exception:
        return None


def resolve_decision(did, outcome, *, feedback="record", weight=1.0, path=None, pd=None, transcript=None, decisions=None):
    """記下事後知道的結果與 Brier 分數。回傳 Brier 分數，找不到回傳 None。"""
    p = path or decisions_path(pd, transcript)
    ds = decisions if decisions is not None else changes.read(path=p)
    d = next((x for x in ds if x.get("id") == did), None)
    if not d:
        return None
    b = brier(d.get("probs"), outcome)
    changes.update(did, path=p, outcome=outcome, feedback=feedback, weight=weight, brier=round(b, 4),
                   resolved_ts=time.time())
    return b


def stats(decisions):
    done = [d for d in decisions if d.get("outcome") is not None and d.get("brier") is not None]
    out = {"decisions": len(decisions), "resolved": len(done),
           "brier": round(sum(d["brier"] for d in done) / len(done), 4) if done else None,
           "auto": sum(1 for d in decisions if d.get("auto")), "buckets": []}
    pairs = []
    for d in done:
        for o, p in (d.get("raw") or {}).items():
            pairs.append((float(p), 1.0 if d["outcome"] == o else 0.0))
    for b in range(10):
        g = [(q, y) for q, y in pairs if _bucket(q) == b]
        if g:
            out["buckets"].append({"bucket": b / 10, "n": len(g), "pred": round(sum(q for q, _ in g) / len(g), 3),
                                   "actual": round(sum(y for _, y in g) / len(g), 3)})
    return out


# ------------------------------------------------------------------ 可復原判斷（客觀檢查）
def _git(root, *args, timeout=10):
    try:
        r = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def git_root_of(path):
    try:
        from projectid import git_root
        return git_root(path if os.path.isdir(path) else os.path.dirname(path))[0]
    except Exception:
        return None


def under(path, root):
    path, root = os.path.normpath(path), os.path.normpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def is_regen(rel):
    parts = [p for p in rel.replace(os.sep, "/").split("/") if p and p != "."]
    return bool(parts) and (any(p in REGEN_DIRS for p in parts) or parts[-1].endswith(REGEN_SUFFIX))


def path_pattern(rels):
    pats = set()
    for r in rels:
        parts = [p for p in r.replace(os.sep, "/").split("/") if p and p != "."]
        if parts:
            pats.add(parts[0] + ("/*" if len(parts) > 1 else ""))
    return ",".join(sorted(pats))


def reversibility(paths, root):
    """回傳 {"recoverable": True|None|False, "impact": bool, "basis": 說明, "pattern", "tracked", "regen"}。
    recoverable None 表示「要靠備份」：自動執行前備份成功才算可復原。"""
    root = os.path.realpath(root)
    full = [os.path.realpath(os.path.join(root, os.path.expanduser(p))) for p in paths]
    rels = [os.path.relpath(f, root) for f in full]
    base = {"pattern": path_pattern(rels), "tracked": "nogit", "regen": False}
    if not full or any(not under(f, root) or f == root for f in full):
        return dict(base, recoverable=False, impact=True, basis="outside project")
    regen = all(is_regen(r) for r in rels)
    base["regen"] = regen
    groot = git_root_of(root)
    if groot:
        code, out = _git(groot, "ls-files", "--", *full)
        tracked = code == 0 and bool(out.strip())
        base["tracked"] = "yes" if tracked else "no"
        if tracked and not regen:
            code2, dirty = _git(groot, "status", "--porcelain", "--", *full)
            code3, untracked = _git(groot, "ls-files", "--others", "--", *full)
            if code2 == 0 and not dirty.strip() and code3 == 0 and not untracked.strip():
                return dict(base, recoverable=True, impact=True, basis="git committed")
    if regen:
        return dict(base, recoverable=True, impact=False, basis="regenerable")
    return dict(base, recoverable=None, impact=True, basis="needs backup")


# ------------------------------------------------------------------ 復原點
def max_bytes():
    try:
        return int(float(os.environ.get("CHUTORA_BACKUP_MAX_MB", "200")) * 1024 * 1024)
    except ValueError:
        return 200 * 1024 * 1024


MAX_FILES = 20000


def restore_root(pd=None):
    from projectid import project_data_dir
    return os.path.join(project_data_dir(pd), "restore")


def _fits(paths):
    total, files, limit = 0, 0, max_bytes()
    for p in paths:
        if os.path.islink(p) or os.path.isfile(p):
            total += os.lstat(p).st_size
            files += 1
        elif os.path.isdir(p):
            for r, ds, fs in os.walk(p):
                files += len(fs) + len(ds)
                for f in fs:
                    try:
                        total += os.lstat(os.path.join(r, f)).st_size
                    except OSError:
                        pass
                if files > MAX_FILES or total > limit:
                    return False
        if files > MAX_FILES or total > limit:
            return False
    return True


def git_point(groot, rid, kind=None):
    """git stash create（不動工作區）存下目前未提交的修改，掛在 refs/chutora/restore/<rid> 免得被回收。"""
    code, head = _git(groot, "rev-parse", "--verify", "HEAD")
    if code != 0 or not head.strip():
        return None
    code, sha = _git(groot, "stash", "create")
    if code != 0:
        return None
    sha = sha.strip() or None
    ref = None
    if sha:
        ref = f"refs/chutora/restore/{rid}"
        if _git(groot, "update-ref", ref, sha)[0] != 0:
            return None
    return {"root": groot, "head": head.strip(), "stash": sha, "ref": ref, "kind": kind}


def snapshot(paths, pd=None, *, git=False, config=False, kind="files", label=""):
    """建復原點：檔案／資料夾複本（設定檔加時間戳）、可選 git stash create。成功回傳 manifest，失敗回傳 None。"""
    pd = os.path.abspath(pd or project_dir())
    rid = new_id()
    d = None
    try:
        d = os.path.join(restore_root(pd), rid)
        full = [os.path.abspath(os.path.join(pd, os.path.expanduser(p))) for p in paths]
        if not _fits([p for p in full if os.path.lexists(p)]):
            return None
        os.makedirs(os.path.join(d, "files"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        items = []
        for i, p in enumerate(full):
            if not os.path.lexists(p):
                items.append({"src": p, "kind": "missing"})
                continue
            name = f"{i}-{os.path.basename(p.rstrip(os.sep)) or 'root'}" + (f".{stamp}" if config else "")
            dst = os.path.join(d, "files", name)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.copytree(p, dst, symlinks=True)
                items.append({"src": p, "kind": "dir", "copy": name})
            else:
                shutil.copy2(p, dst, follow_symlinks=False)
                items.append({"src": p, "kind": "file", "copy": name})
        g = None
        if git:
            groot = git_root_of(pd)
            g = git_point(groot, rid, kind) if groot else None
            if g is None:
                raise RuntimeError("git restore point failed")
        man = {"id": rid, "ts": now_iso(), "project": pd, "kind": kind, "label": label, "items": items, "git": g,
               "dir": d}
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=1)
        return man
    except Exception:
        if d:
            shutil.rmtree(d, ignore_errors=True)
        return None


def load_manifest(path):
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) and m.get("items") is not None else None
    except (OSError, ValueError, TypeError):
        return None


def restore(man):
    """依復原點還原。現有的同名檔案先移到復原點的 replaced-<時間>/，不直接覆蓋。回傳 (成功, 訊息清單)。"""
    msgs, ok = [], True
    aside = os.path.join(man["dir"], "replaced-" + time.strftime("%Y%m%d-%H%M%S"))
    g = man.get("git")
    if g:
        groot = g.get("root")
        cur = _git(groot, "stash", "create")[1].strip()
        if cur:  # 還原前的狀態也留一份
            _git(groot, "update-ref", f"refs/chutora/restore/{man['id']}-before-undo", cur)
            msgs.append(f"before-undo: {cur[:10]}")
        if g.get("kind") == "git-reset-hard" and g.get("head"):
            code, _ = _git(groot, "reset", "--hard", g["head"])
            ok = ok and code == 0
            msgs.append(f"HEAD → {g['head'][:10]}")
        if g.get("stash"):
            code, _ = _git(groot, "stash", "apply", g["stash"])
            ok = ok and code == 0
            msgs.append(f"stash apply {g['stash'][:10]}" + ("" if code == 0 else " FAILED"))
    for i, it in enumerate(man.get("items") or []):
        if it.get("kind") not in ("dir", "file"):
            continue
        src, cp = it["src"], os.path.join(man["dir"], "files", it["copy"])
        try:
            if os.path.lexists(src):
                os.makedirs(aside, exist_ok=True)
                shutil.move(src, os.path.join(aside, f"{i}-{os.path.basename(src)}"))
            os.makedirs(os.path.dirname(src), exist_ok=True)
            if it["kind"] == "dir":
                shutil.copytree(cp, src, symlinks=True)
            else:
                shutil.copy2(cp, src, follow_symlinks=False)
            msgs.append(src)
        except Exception as e:  # noqa: BLE001
            ok = False
            msgs.append(f"{src}: {e}")
    return ok, msgs


def find_change(cid, pd=None, transcript=None):
    return next((c for c in changes.read(project_dir=pd, transcript_path=transcript) if c.get("id") == cid), None)


def undo(cid, pd=None, transcript=None):
    """用變更紀錄的復原點還原，並當成強烈負面回饋。回傳 (成功, 訊息)。"""
    pd = pd or project_dir()
    ch = find_change(cid, pd, transcript)
    if not ch:
        return False, T(f"找不到變更 {cid}", f"change {cid} not found")
    if ch.get("user_response") == "undone":
        return False, T(f"{cid} 已經復原過了", f"{cid} was already undone")
    man = load_manifest(ch.get("restore_point") or "")
    if not man:
        return False, T(f"{cid} 沒有可用的復原點", f"{cid} has no usable restore point")
    ok, msgs = restore(man)
    cp = changes.changes_path(pd, transcript)
    changes.update(cid, path=cp, user_response="undone" if ok else "undo_failed", notified=True)
    dp = decisions_path(pd, transcript)
    ds = changes.read(path=dp)
    for d in ds:
        if d.get("change_id") == cid and d.get("type") == AUTO_TYPE:
            resolve_decision(d["id"], "ask", feedback="undo", weight=UNDO_WEIGHT, path=dp, decisions=ds)
    head = T("已復原", "Restored") if ok else T("部分復原失敗", "Restore partly failed")
    return ok, f"{head} {cid}: " + "; ".join(msgs[:8])


# ------------------------------------------------------------------ 通知與回饋
def pending(pd=None, transcript=None):
    """待確認：Chutora 自動做（或代你在略過權限模式下做）、還沒回應的動作。"""
    return [c for c in changes.read(project_dir=pd, transcript_path=transcript)
            if c.get("action") in PENDING_ACTIONS and not c.get("user_response") and not c.get("quiet")
            and c.get("ran") is not False]  # ran=False：hook 放行了但沒真的執行（例如被 settings 的 deny 規則擋下）


def _summ(c, n=60):
    from redact import short
    return short(re.sub(r"^Bash:\s*", "", str(c.get("summary") or "")), n)


# 使用者把決定交給 Claude（只看這則訊息；誤判的代價只是多帶一段短說明）
DELEGATE = re.compile(
    r"(你(?:來|幫我|替我)?(?:決定|選|挑|判斷)(?:一個|一下)?(?:吧|就好|就行|就可以|好了)?(?=$|[\s，,。！!？?～~；;])|你看著辦|交給你(?:決定|選)?|照你的(?:判斷|意思|建議)|"
    r"(?:^|[\s，,。！!；;])(?:都可以|都行|都好|隨便|哪個都(?:可以|行|好))(?=$|[\s，,。！!～~；;啦喔吧])|"
    r"\byou (?:decide|choose|pick)\b|\b(?:it'?s |that'?s )?up to you\b|\byour call\b|"
    r"\b(?:either|any|both) (?:one |option |way )?(?:is|are|works?|would be) (?:fine|ok(?:ay)?|good)\b|"
    r"\bwhatever you (?:think|prefer|want|decide)\b|\bi don'?t (?:mind|care) (?:which|either)\b|\bdealer'?s choice\b)",
    re.I)


def delegate_text():
    cmd = f'python3 "{HERE}/decide.py"'
    return T(f"Chutora 決策引擎：使用者把決定交給你。在有限選項中選擇前先跑 `{cmd} score --type <題型> --options a,b "
             f"[--claude a=0.7,b=0.3] [--path <路徑>] [--remote]`：`action` 是 auto 就照 `best` 做（動到檔案先 "
             f"`decide.py snapshot --summary \"<做什麼>\" <路徑>`，失敗就不做）；是 ask 時，可復原的選 `best` 並在回覆說明理由，"
             f"不可復原的（--remote、刪除、對外）先確認再做。事後知道答案：`decide.py record <id> <答案>`。",
             f"Chutora decision engine: the user left the decision to you. Before choosing among bounded options, run `{cmd} score "
             f"--type <kind> --options a,b [--claude a=0.7,b=0.3] [--path <paths>] [--remote]`: if `action` is auto, do `best` "
             f"(when it touches files, first `decide.py snapshot --summary \"<what>\" <paths>`; if that fails, don't); if it is ask, "
             f"pick `best` when it is recoverable and say why in your reply, and confirm first when it is not (--remote, deleting, "
             f"outside effects). Once the answer is known: `decide.py record <id> <answer>`.")


def notify_text(items):
    n = len(items)
    lst = "；".join(f"{c['id']} {_summ(c)}" for c in items[:3]) + ("…" if n > 3 else "")
    lst_en = "; ".join(f"{c['id']} {_summ(c)}" for c in items[:3]) + ("…" if n > 3 else "")
    ids = items[0]["id"] if n == 1 else "<id>"
    who = "ok " + (ids if n == 1 else "all")
    return T(f"Chutora：有 {n} 個動作還沒確認（自動執行、或你剛允許的；{lst}）。請在這次回覆的最後附上剛好一行（多個合併成一行）："
             f"「Chutora 自動做了 {n} 件：<簡述>。回 /chutora {who} auto（這類以後可自動）、/chutora {who} ask（下次先問我）"
             f"或 /chutora undo {ids}（復原）」。使用者回應前，每次都會再提醒；ok … auto 只能由使用者本人回覆。",
             f"Chutora: {n} action(s) not confirmed yet (run automatically or just allowed by you; {lst_en}). End this reply with exactly one line "
             f"(merge them into one): \"Chutora did {n} thing(s) automatically: <summary>. Reply /chutora {who} auto "
             f"(this kind may be automatic), /chutora {who} ask (ask me next time) or /chutora undo {ids} (restore).\" "
             f"This reminder repeats until the user responds; only the user may answer ok … auto.")


def notify(data):
    """UserPromptSubmit：有待確認的自動動作時，請 Claude 在回覆結尾附一行；使用者把決定交給 Claude 時帶精簡用法。
    兩者都沒有就不輸出（不加 token）。"""
    if not isinstance(data, dict):
        return None
    prompt = str(data.get("prompt") or "")
    m = re.match(r"\s*/(?:chutora:)?chutora\s+(ok|undo|好|復原)\s+(\S+)(?:\s+(\S+))?\s*$", prompt)
    if m:  # 使用者本人打的回饋：在這裡直接處理（Claude 自己跑 ok … auto 會被守門攔下）
        pd = project_dir(data)
        if m.group(1) in ("ok", "好"):
            _, msgs = feedback(m.group(2), m.group(3) or "", pd, data.get("transcript_path"))
            text = "\n".join(msgs)
        else:
            _, text = undo(m.group(2), pd, data.get("transcript_path"))
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": T(
            f"Chutora 已依使用者這則訊息處理完畢（不要再執行 chutora.py ok／undo，直接把結果告訴使用者）：\n{text}",
            f"Chutora already handled this message from the user (do not run chutora.py ok/undo again; just tell the user the result):\n{text}")}}
    if re.match(r"\s*/(?:chutora:)?chutora\b", prompt):
        return None  # 使用者正在查看，不必再提醒
    parts = []
    items = pending(project_dir(data), data.get("transcript_path"))
    if items:
        parts.append(notify_text(items))
    if engine_enabled() and DELEGATE.search(prompt):
        parts.append(delegate_text())
    if not parts:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(parts)}}


def feedback(target, verdict="ack", pd=None, transcript=None):
    """回饋：auto（這類以後可以自動）、ask（下次先問我）、ack（只是知道了，不計入學習）。回傳 (成功數, 訊息清單)。"""
    pd = pd or project_dir()
    verdict = {"": "ack", "ok": "ack", "auto": "auto", "ask": "ask", "自動": "auto", "問": "ask", "先問": "ask"}.get(
        (verdict or "").strip().lower(), None)
    if verdict is None:
        return 0, [T("回饋只能是 auto、ask，或不加（只標成已讀）", "Feedback must be auto, ask, or nothing (just mark as seen)")]
    items = pending(pd, transcript) if target == "all" else [find_change(target, pd, transcript)]
    if target == "all" and not items:
        return 0, [T("沒有待確認的自動動作", "Nothing waiting for confirmation")]
    dp = decisions_path(pd, transcript)
    ds = changes.read(path=dp)
    cp = changes.changes_path(pd, transcript)
    done, msgs = 0, []
    for ch in items:
        if not ch:
            msgs.append(T(f"找不到變更 {target}", f"change {target} not found"))
            continue
        want = {"auto": "ok_auto", "ask": "ok_ask", "ack": "ack"}[verdict]
        if ch.get("user_response") == want:
            msgs.append(T(f"{ch['id']}：先前已記錄過", f"{ch['id']}: already recorded"))
            done += 1
            continue
        linked = [d for d in ds if d.get("change_id") == ch["id"] and d.get("outcome") is None]
        learn = [d for d in linked if d.get("type") != AUTO_TYPE or (d.get("features") or {}).get("category") in LEARNABLE]
        if verdict in ("auto", "ask") and not learn:
            msgs.append(T(f"{ch['id']}：這類在永遠要問清單上或不可復原，不能學成自動；只標成已讀",
                          f"{ch['id']}: this kind is on the always-ask list or not recoverable, so it can't be learned; marked as seen"))
            changes.update(ch["id"], path=cp, user_response="ack", notified=True)
            done += 1
            continue
        if verdict in ("auto", "ask"):
            for d in learn:
                if d.get("type") == AUTO_TYPE:
                    resolve_decision(d["id"], verdict, feedback=verdict, path=dp, decisions=ds)
                elif verdict == "auto" and d.get("best"):
                    resolve_decision(d["id"], d["best"], feedback="auto", path=dp, decisions=ds)
        changes.update(ch["id"], path=cp, user_response={"auto": "ok_auto", "ask": "ok_ask", "ack": "ack"}[verdict],
                       notified=True)
        done += 1
        msgs.append(f"{ch['id']}: " + {"auto": T("記下了，這類以後可以自動", "noted: this kind may run automatically"),
                                        "ask": T("記下了，下次先問你", "noted: will ask you first next time"),
                                        "ack": T("已讀（不計入學習）", "seen (not used for learning)")}[verdict])
    return done, msgs


def list_changes(n=10, pd=None, transcript=None):
    pd = pd or project_dir()
    pend = pending(pd, transcript)
    out = [T(f"待確認 {len(pend)} 個", f"{len(pend)} waiting for confirmation") + (T("：", ":") if pend else T("。", "."))]
    for c in pend:
        rp = T("有復原點", "restore point") if c.get("restore_point") else T("無復原點", "no restore point")
        out.append(f"- {c['id']}  {c.get('ts', '')[:16]}  {c.get('action')}  {_summ(c, 100)}  [{rp}]")
    recent = [c for c in changes.read(project_dir=pd, transcript_path=transcript)
              if c.get("action") in PENDING_ACTIONS and c not in pend][-n:]
    if recent:
        out.append(T("最近已處理：", "Recently handled:"))
        for c in recent:
            out.append(f"- {c['id']}  {c.get('action')}  {_summ(c, 80)}  → {c.get('user_response') or ('quiet' if c.get('quiet') else '')}")
    out.append(T("回應：/chutora ok <id|all> auto（這類以後可自動）｜ask（下次先問我）；/chutora undo <id> 復原",
                 "Respond: /chutora ok <id|all> auto (may be automatic) | ask (ask me next time); /chutora undo <id> to restore"))
    return "\n".join(out)


# ------------------------------------------------------------------ PreToolUse 整合（由 guard.py 呼叫）
def _real(p):
    try:
        return os.path.realpath(p)
    except OSError:
        return p


def _features(category, action, rels, root, cwd, tracked):
    try:
        import guard as g
        branch = g.current_branch(cwd)
    except Exception:
        branch = None
    try:
        from projectid import project_id
        proj = project_id(root)
    except Exception:
        proj = None
    return {"category": category, "action": action, "path": path_pattern(rels) if rels else "*", "branch": branch,
            "tracked": tracked, "regen": bool(rels) and all(is_regen(r) for r in rels), "project": proj}


def _clean_list(cwd, args):
    """git clean 會刪掉哪些檔案：用同樣的選項跑 git clean -n。"""
    flags = []
    for x in args:
        if x in ("-f", "--force", "-i", "--interactive", "-q", "--quiet"):
            continue
        if re.match(r"^-[a-zA-Z]+$", x):
            x = "-" + x[1:].replace("f", "").replace("i", "").replace("q", "")
            if x == "-":
                continue
        flags.append(x)
    code, out = _git(cwd, "clean", "-n", *flags)
    if code != 0:
        return None
    return [os.path.normpath(os.path.join(cwd, m.group(1))) for m in
            (re.match(r"^Would remove (.+?)/?$", ln) for ln in out.splitlines()) if m]


def classify(data, hits=None):
    """這個 Bash 呼叫是不是可以學的類型？回傳候選 dict 或 None。
    只接受「整段指令就只有這件事」：rm／rmdir／unlink 專案內的路徑（可加 cd），或單獨一個 git reset --hard／git clean；
    有管線、重導向、$(...)、反引號、變數、其他指令或 sudo 之類前綴，一律不算（避免連帶放行別的東西）。"""
    import guard as g
    cmd = (data.get("tool_input") or {}).get("command")
    if not isinstance(cmd, str) or not cmd.strip() or "`" in cmd or "$" in cmd or "\n" in cmd.strip():
        return None
    rules = {h[0] for h in hits} if hits else set()
    if hits and not rules <= {"git-reset-hard", "git-clean"}:
        return None
    root = os.path.normpath(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    rroot = _real(root)
    cwd = os.path.normpath(data.get("cwd") or root)
    try:
        segs = g.tokenize(cmd)
    except Exception:
        return None
    work = []
    for s in segs or []:
        a = s.argv
        if s.redirs or not a:
            return None
        if a[0] == "cd" and len(a) == 2:
            full, unres, globbed = g.resolve(a[1], cwd)
            if unres or globbed or not under(_real(full), rroot):
                return None
            cwd = full
            continue
        work.append(a)
    if not work:
        return None
    if hits:
        a = work[0]
        if len(work) != 1 or a[0] != "git" or len(a) < 2:
            return None
        sub, args, cdir = g.git_parts(a)
        if cdir or a[1] != sub:
            return None
        if sub == "reset" and "--hard" in args and "git-reset-hard" in rules:
            return {"category": "git-reset-hard", "paths": [], "git": True, "impact": True, "basis": "git stash create",
                    "summary": cmd, "features": _features("git-reset-hard", "git reset --hard", [], root, cwd, "yes")}
        if sub == "clean" and "git-clean" in rules:
            paths = _clean_list(cwd, args)
            if paths is None or any(not under(_real(p), rroot) or _real(p) == rroot for p in paths):
                return None
            rels = [os.path.relpath(_real(p), rroot) for p in paths]
            return {"category": "git-clean", "paths": paths, "git": False,
                    "impact": not (rels and all(is_regen(r) for r in rels)), "basis": "snapshot untracked",
                    "summary": cmd, "features": _features("git-clean", "git clean", rels, root, cwd, "no")}
        return None
    targets, rec = [], False
    for a in work:
        if a[0] not in ("rm", "rmdir", "unlink"):
            return None
        r = g.rm_targets(a)
        if not r or not r[1]:
            return None
        rec = rec or r[0]
        for t in r[1]:
            if t.startswith("~"):
                return None
            p = os.path.join(cwd, t)
            targets += globmod.glob(p) if re.search(r"[*?\[]", t) else [os.path.normpath(p)]
    rels = []
    for f in targets:
        for c in (os.path.normpath(f), _real(f)):
            if not (under(c, root) or under(c, rroot)) or c in (root, rroot):
                return None
        rel = os.path.relpath(_real(f), rroot)
        if rel.split(os.sep)[0] == ".git" or g.is_secret(f):
            return None
        rels.append(rel)
    rv = reversibility(rels, rroot) if rels else {"recoverable": True, "impact": False, "basis": "nothing to delete",
                                                  "tracked": "no"}
    if rv["recoverable"] is False:
        return None
    return {"category": "rm-in-project", "paths": targets, "git": False, "impact": rv["impact"], "basis": rv["basis"],
            "summary": cmd, "features": _features("rm-in-project", "rm -r" if rec else "rm", rels, root, cwd,
                                                  rv.get("tracked", "nogit"))}


def _hook(decision=None, reason=None, ctx=None):
    o = {"hookEventName": "PreToolUse"}
    if decision:
        o["permissionDecision"] = decision
        o["permissionDecisionReason"] = reason
    if ctx:
        o["additionalContext"] = ctx
    return {"hookSpecificOutput": o}


def _pending_file(cwd):
    from projectid import project_data_dir
    return os.path.join(project_data_dir(cwd), "decide-pending.json")


def _remember(data, item):
    """記下這個 tool_use_id，PostToolUse 時用來確認真的執行了，或問要不要以後自動。"""
    if not data.get("tool_use_id"):
        return
    try:
        p = _pending_file(data.get("cwd"))
        try:
            with open(p) as f:
                pend = json.load(f)
        except (OSError, ValueError):
            pend = {}
        pend[data["tool_use_id"]] = dict(item, ts=time.time())
        for k in list(pend)[:-20]:
            pend.pop(k, None)
        with open(p + ".tmp", "w") as f:
            json.dump(pend, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
    except Exception:
        pass


def _score_cand(cand, decisions):
    return score(AUTO_TYPE, ["auto", "ask"], cand["features"], None, True, cand["impact"], decisions)


def pretool(data, hits=None):
    """guard.py 在「沒命中」或「只命中可學的 ask 規則」時呼叫。回傳 hook 輸出，或 None（照原本流程）。
    永遠要問清單的其他規則、使用者規則、略過權限模式的 deny 都不會走到這裡，所以不會被放寬。"""
    if not engine_enabled() or data.get("tool_name") != "Bash":
        return None
    cand = classify(data, hits)
    if not cand:
        return None
    pd, tp = project_dir(data), data.get("transcript_path")
    dpath = decisions_path(pd, tp)
    ds = changes.read(path=dpath)
    res = _score_cand(cand, ds)
    res["basis"] = cand["basis"]
    pmode = data.get("permission_mode")
    summary = "Bash: " + cand["summary"]
    cat = cand["category"]

    def restore_point():
        man = snapshot(cand["paths"], pd, git=cand["git"], kind=cat, label=cand["summary"][:120])
        return os.path.join(man["dir"], "manifest.json") if man else None

    if res["action"] == "auto" and res["best"] == "auto":
        rp = restore_point()
        if rp:  # 備份成功才自動
            cid = changes.record("auto_allow", summary, restore_point=rp, notified=True, source="decide",
                                 session=data.get("session_id"), project_dir=pd, transcript_path=tp, category=cat,
                                 quiet=bool(res["simple"]) or None, p_auto=res["probs"]["auto"],
                                 tool_use_id=data.get("tool_use_id"), ran=False)
            record_decision(res, path=dpath, change_id=cid, auto=True, category=cat)
            _remember(data, {"confirm": cid, "pd": pd, "tp": tp})
            short_cmd = cand["summary"][:80]
            reason = T(f"Chutora 決策引擎自動允許（你先前同意這類可自動；已建復原點，/chutora undo {cid} 可還原）：{short_cmd}",
                       f"Chutora decision engine auto-approved this (you said this kind may be automatic; restore point saved, /chutora undo {cid} restores it): {short_cmd}")
            if res["simple"]:
                ctx = T(f"Chutora 自動允許了 `{short_cmd}`（已建復原點）。在這次回覆最後附一行即可：「Chutora 自動：{short_cmd}（/chutora undo {cid} 可復原）」，之後不再提醒。",
                        f"Chutora auto-approved `{short_cmd}` (restore point saved). Just end this reply with one line: \"Chutora auto: {short_cmd} (/chutora undo {cid} restores)\"; no further reminders.")
            else:
                ctx = T(f"Chutora 自動允許了 `{short_cmd}`（已建復原點，變更 {cid}）。在這次回覆最後附一行：「Chutora 自動做了：{short_cmd} — /chutora ok {cid} auto｜ask，或 /chutora undo {cid}」。",
                        f"Chutora auto-approved `{short_cmd}` (restore point saved, change {cid}). End this reply with one line: \"Chutora did automatically: {short_cmd} — /chutora ok {cid} auto|ask, or /chutora undo {cid}\".")
            return _hook("allow", reason, ctx)
    if hits:
        return None  # 守門照樣問；guard.py 之後呼叫 note_ask() 把這次記下來
    if res["n"] > 0 and res["best"] == "ask" and (str(res.get("prior")) == "user:ask" or res["cooldown"]):
        return _hook("ask", T(f"Chutora：你先前要求這類動作先問你（或最近復原過）：{cand['summary'][:80]}。確認是你要的再允許。",
                              f"Chutora: you asked to be asked first for this kind of action (or undid one recently): {cand['summary'][:80]}. Allow it only if this is what you want."))
    if pmode == "bypassPermissions":
        rp = restore_point()  # 沒人確認、會直接執行：先留復原點、事後通知
        if rp:
            cid = changes.record("unattended_run", summary, restore_point=rp, notified=False, source="decide",
                                 session=data.get("session_id"), project_dir=pd, transcript_path=tp, category=cat,
                                 tool_use_id=data.get("tool_use_id"), ran=False)
            record_decision(res, path=dpath, change_id=cid, auto=True, by="bypassPermissions", category=cat)
            _remember(data, {"confirm": cid, "pd": pd, "tp": tp})
            return _hook(ctx=T(f"Chutora：略過權限模式下會直接執行 `{cand['summary'][:80]}`，已先建復原點（變更 {cid}）。在這次回覆最後附一行：「Chutora 已建復原點：{cand['summary'][:60]} — /chutora ok {cid} auto｜ask，或 /chutora undo {cid}」。",
                               f"Chutora: in bypass-permissions mode `{cand['summary'][:80]}` runs without a prompt, so a restore point was saved first (change {cid}). End this reply with one line: \"Chutora saved a restore point: {cand['summary'][:60]} — /chutora ok {cid} auto|ask, or /chutora undo {cid}\"."))
        return None
    if res["cold"]:  # 第一次遇到：使用者允許執行後，問要不要以後自動
        _remember(data, {"summary": summary, "category": cat, "res": res, "session": data.get("session_id"),
                         "pd": pd, "tp": tp})
    return None


def note_ask(data, hits, change_id):
    """守門判 ask、而且只命中可學的規則時：記一筆待定決策，回傳附在原因後面的提示（不是可學的就回傳空字串）。"""
    try:
        if not engine_enabled() or not change_id or data.get("tool_name") != "Bash":
            return ""
        cand = classify(data, hits)
        if not cand:
            return ""
        pd, tp = project_dir(data), data.get("transcript_path")
        dpath = decisions_path(pd, tp)
        res = _score_cand(cand, changes.read(path=dpath))
        res["basis"] = cand["basis"]
        record_decision(res, path=dpath, change_id=change_id, auto=False, category=cand["category"])
        return T(f"（Chutora 決策引擎：這類可以學。允許後若希望以後自動〔先建復原點〕，請回 /chutora ok {change_id} auto。）",
                 f" (Chutora decision engine: this kind can be learned. If it should be automatic from now on [with a restore point first], reply /chutora ok {change_id} auto.)")
    except Exception:
        return ""


def resolve_pending(data, ddir=None):
    """PostToolUse／PostToolUseFailure：自動放行的那次標成 ran；第一次遇到、使用者自己允許後真的執行了
    → 記一筆 approved_run，問要不要以後自動。"""
    tid = data.get("tool_use_id")
    if not tid:
        return
    try:
        p = os.path.join(ddir, "decide-pending.json") if ddir else _pending_file(data.get("cwd"))
        if not os.path.exists(p):
            return
        with open(p) as f:
            pend = json.load(f)
        item = pend.pop(tid, None)
        with open(p + ".tmp", "w") as f:
            json.dump(pend, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
        if not item or time.time() - item.get("ts", 0) > 3600:
            return
        pd, tp = item.get("pd"), item.get("tp")
        if item.get("confirm"):  # 自動放行的那次真的執行了
            changes.update(item["confirm"], path=changes.changes_path(pd, tp), ran=True)
            return
        if any(c.get("category") == item["category"] and c.get("action") == "approved_run"
               for c in pending(pd, tp)):
            return  # 同類已經在問了
        cid = changes.record("approved_run", item["summary"], restore_point=None, notified=False, source="decide",
                             session=item.get("session"), project_dir=pd, transcript_path=tp, category=item["category"])
        record_decision(item["res"], path=decisions_path(pd, tp), change_id=cid, auto=False, by="user",
                        category=item["category"])
    except Exception:
        pass


# ------------------------------------------------------------------ AskUserQuestion：依過去答案建議、記下答案
# 實測 Claude Code 2.1.319：PreToolUse 會在問題顯示前觸發，但 additionalContext 要等使用者回答後才隨工具結果送到 Claude；
# 所以另外用 updatedInput（不帶 permissionDecision，問題照常顯示）在建議選項的說明後面附註，使用者選的當下就看得到。
# PostToolUse 的 tool_response 有 answers（{問題文字: 選項 label}），由 observe.py 呼叫 ask_learn() 記下。
ASK_PREFIX = "ask:"
_RECOMMENDED = re.compile(r"\s*[（(]\s*(?:recommended|suggested|建議|推薦|建議選項)\s*[)）]\s*$", re.I)


def _label(s):
    return _RECOMMENDED.sub("", str(s or "")).strip()


def _strict():
    try:
        from observe import strict
        return strict()
    except Exception:
        return False


def _key(text, limit, strict):
    """存進 decisions.jsonl 的寫法：一般存前 limit 字（遮罩金鑰，和 observe 的「選擇存前 40 字」一致）；
    嚴格隱私（/chutora observe privacy strict）只存 sha256 前 12 字元，照樣比得出同一個選項。"""
    import hashlib
    from redact import short
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return "h:" + hashlib.sha256(t.encode("utf-8")).hexdigest()[:12] if strict else short(t, limit)


def _qtype(q, strict=False):
    """題型：header（沒有就用問題前 60 字），小寫、壓空白。"""
    h = str(q.get("header") or "").strip() or str(q.get("question") or "")[:60]
    return ASK_PREFIX + _key(h.lower(), 60, strict)


def _qopts(q, strict=False):
    """回傳 {存檔用的鍵: 原本的 label}（保持順序、去掉「（建議）」「(Recommended)」字尾）。"""
    out = {}
    for o in q.get("options") or []:
        lab = _label(o.get("label") if isinstance(o, dict) else o)
        if lab:
            out.setdefault(_key(lab, 40, strict), lab)
    return out


def _ask_feats(data):
    try:
        from projectid import project_id
        return {"project": project_id(project_dir(data))}
    except Exception:
        return {}


def _ask_history(data):
    ds = changes.read(path=decisions_path(project_dir(data), data.get("transcript_path")))
    return [d for d in ds if str(d.get("type") or "").startswith(ASK_PREFIX) and d.get("outcome") is not None]


def ask_suggest(data):
    """PreToolUse(AskUserQuestion)：同專案、同題型有過去答案、而且算得出偏好時，帶一行建議；否則回傳 None（不加 token）。"""
    if not engine_enabled() or not isinstance(data, dict) or data.get("tool_name") != "AskUserQuestion":
        return None
    ti = data.get("tool_input")
    qs = ti.get("questions") if isinstance(ti, dict) else None
    if not isinstance(qs, list) or not qs:
        return None
    ds = _ask_history(data)
    if not ds:
        return None
    feats, lines, new, st = _ask_feats(data), [], json.loads(json.dumps(ti)), _strict()
    for i, q in enumerate(qs):
        if not isinstance(q, dict) or q.get("multiSelect"):
            continue
        opts = _qopts(q, st)
        if len(opts) < 2:
            continue
        res = score(_qtype(q, st), list(opts), feats, None, None, True, ds)
        ps = sorted(res["probs"].values(), reverse=True)
        if res["n"] <= 0 or ps[0] - ps[1] < 0.01:
            continue  # 沒有相關紀錄，或分不出高下
        best, p = opts[res["best"]], res["probs"][res["best"]]
        head = str(q.get("header") or q.get("question") or "")[:40]
        lines.append(T(f"「{head}」依你過去偏好建議選「{best}」（信心 {p:.2f}，{res['n']:.0f} 筆相似紀錄）",
                       f"'{head}': based on the user's past picks, suggest '{best}' (confidence {p:.2f}, {res['n']:.0f} similar records)"))
        for o in new["questions"][i].get("options") or []:
            if isinstance(o, dict) and _label(o.get("label")) == best:
                o["description"] = (str(o.get("description") or "") + T(f"（Chutora：依你過去的選擇建議，信心 {p:.2f}）",
                                                                         f" (Chutora: suggested from your past picks, {p:.2f})")).strip()
                break
    if not lines:
        return None
    ctx = T("Chutora：" + "；".join(lines) + "。使用者的回答優先。",
            "Chutora: " + "; ".join(lines) + ". The user's answer wins.")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": ctx, "updatedInput": new}}


def ask_learn(data):
    """PostToolUse(AskUserQuestion)：每題記一筆已有結果的決策（自己打字的回答、多選題不記）。回傳記了幾筆。"""
    if not engine_enabled() or not isinstance(data, dict) or data.get("tool_name") != "AskUserQuestion":
        return 0
    ti = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    resp = data.get("tool_response") if isinstance(data.get("tool_response"), dict) else {}
    answers = resp.get("answers") or ti.get("answers")
    qs = resp.get("questions") or ti.get("questions")
    if not isinstance(answers, dict) or not isinstance(qs, list):
        return 0
    p = decisions_path(project_dir(data), data.get("transcript_path"))
    ds = [d for d in changes.read(path=p) if str(d.get("type") or "").startswith(ASK_PREFIX)]
    feats, n, st = _ask_feats(data), 0, _strict()
    for q in qs:
        if not isinstance(q, dict) or q.get("multiSelect"):
            continue
        opts, ans = _qopts(q, st), _label(answers.get(q.get("question")))
        key = next((k for k, lab in opts.items() if lab == ans), None)
        if len(opts) < 2 or key is None:
            continue
        res = score(_qtype(q, st), list(opts), feats, None, None, True, ds)
        if record_decision(res, path=p, outcome=key, feedback="answer", weight=1.0, source="ask",
                           brier=round(brier(res["probs"], key), 4), resolved_ts=time.time(),
                           tool_use_id=data.get("tool_use_id")):
            n += 1
    return n


# ------------------------------------------------------------------ 命令列
def _kv(items):
    out = {}
    for it in items or []:
        for part in str(it).split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def _yn(v):
    if v is None:
        return None
    return str(v).strip().lower() in ("yes", "y", "true", "1", "是")


def cli_score(a):
    pd = project_dir()
    options = [o.strip() for o in a.options.split(",") if o.strip()]
    claude = {k: float(v) for k, v in _kv([a.claude]).items()} if a.claude else None
    feats = _kv(a.feature)
    rec, imp, basis = _yn(a.recoverable), _yn(a.impact), "given"
    if a.remote:
        rec, imp, basis = False, True, "remote/external"
    elif a.path and rec is None:
        rv = reversibility(a.path, pd)
        rec, basis = (True if rv["recoverable"] is None else rv["recoverable"]), rv["basis"]  # 要靠備份：先 snapshot 成功才做
        imp = rv["impact"] if imp is None else imp
        feats.setdefault("path", rv["pattern"])
    imp = True if imp is None else imp
    res = score(a.type, options, feats, claude, rec, imp, load_decisions(pd), unattended=a.unattended)
    res["basis"] = basis
    if not a.no_record:
        res["id"] = record_decision(res, pd=pd, unattended=bool(a.unattended))
        if res["action"] == "skip-todo":
            changes.record("decision_todo", f"{a.type}: {res['best']} ({res['reason']})", project_dir=pd,
                           source="decide", decision_id=res.get("id"))
    print(json.dumps({k: res[k] for k in ("id", "action", "best", "p_best", "probs", "threshold", "recoverable",
                                          "impact", "basis", "reason", "n", "cold", "calibration") if k in res},
                     ensure_ascii=False))
    return 0


def cli_record(a):
    d = next((x for x in load_decisions(project_dir()) if x.get("id") == a.id), None)
    if d and d.get("type") == AUTO_TYPE:  # 「能不能自動」只能由使用者用 /chutora ok／undo 回答
        print(T("這筆是自動執行的決策，要由使用者用 /chutora ok 或 /chutora undo 回應。",
                "This is an auto-run decision; only the user can answer it with /chutora ok or /chutora undo."))
        return 1
    b = resolve_decision(a.id, a.outcome, pd=project_dir())
    if b is None:
        print(T(f"找不到決策 {a.id}", f"decision {a.id} not found"))
        return 1
    print(json.dumps({"id": a.id, "outcome": a.outcome, "brier": round(b, 4)}))
    return 0


def cli_stats(a):
    print(json.dumps(stats(load_decisions(project_dir())), ensure_ascii=False))
    return 0


def cli_snapshot(a):
    pd = project_dir()
    man = snapshot(a.paths, pd, git=a.git, config=a.config, kind="config" if a.config else "files",
                   label=a.summary or "")
    if not man:
        print(T("建立復原點失敗（太大、找不到 git 或寫入失敗）：不要自動執行。",
                "Could not create a restore point (too big, no git, or write failed): do not run it automatically."))
        return 1
    cid = changes.record("auto_cli", a.summary or ("snapshot " + " ".join(a.paths)),
                         restore_point=os.path.join(man["dir"], "manifest.json"), project_dir=pd, source="decide",
                         decision_id=a.decision, category=a.category)
    if a.decision and cid:
        changes.update(a.decision, path=decisions_path(pd), change_id=cid, auto=True)
    print(json.dumps({"change_id": cid, "restore_point": man["dir"]}, ensure_ascii=False))
    return 0


def cli_undo(a):
    ok, msg = undo(a.id)
    print(msg)
    return 0 if ok else 1


def cli_pending(a):
    items = pending()
    print(json.dumps({"count": len(items), "items": [{"id": c["id"], "action": c.get("action"), "summary": _summ(c, 120),
                                                      "restore_point": bool(c.get("restore_point"))} for c in items]},
                     ensure_ascii=False))
    return 0


def cli_changes(a):
    print(list_changes(a.n))
    return 0


def cli_ok(a):
    done, msgs = feedback(a.target, a.verdict or "")
    print("\n".join(msgs))
    return 0 if done else 1


def cli_notify(a):
    try:
        out = notify(json.load(sys.stdin))
    except Exception:
        return 0
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


def cli_ask(a):
    try:
        out = ask_suggest(json.load(sys.stdin))
    except Exception:
        return 0
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(prog="decide.py")
    sp = ap.add_subparsers(dest="cmd")
    s = sp.add_parser("score")
    s.add_argument("--type", required=True)
    s.add_argument("--options", required=True)
    s.add_argument("--claude")
    s.add_argument("--feature", action="append")
    s.add_argument("--path", action="append")
    s.add_argument("--recoverable")
    s.add_argument("--impact")
    s.add_argument("--remote", action="store_true")
    s.add_argument("--unattended", action="store_true")
    s.add_argument("--no-record", action="store_true")
    r = sp.add_parser("record")
    r.add_argument("id")
    r.add_argument("outcome")
    sp.add_parser("stats")
    sn = sp.add_parser("snapshot")
    sn.add_argument("paths", nargs="*")
    sn.add_argument("--git", action="store_true")
    sn.add_argument("--config", action="store_true")
    sn.add_argument("--summary")
    sn.add_argument("--decision")
    sn.add_argument("--category")
    u = sp.add_parser("undo")
    u.add_argument("id")
    sp.add_parser("pending")
    c = sp.add_parser("changes")
    c.add_argument("n", nargs="?", type=int, default=10)
    o = sp.add_parser("ok")
    o.add_argument("target")
    o.add_argument("verdict", nargs="?")
    sp.add_parser("notify")
    sp.add_parser("ask")
    a = ap.parse_args(argv)
    fn = {"score": cli_score, "record": cli_record, "stats": cli_stats, "snapshot": cli_snapshot, "undo": cli_undo,
          "pending": cli_pending, "changes": cli_changes, "ok": cli_ok, "notify": cli_notify,
          "ask": cli_ask}.get(a.cmd)
    if not fn:
        ap.print_help()
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
