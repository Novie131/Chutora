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
    a = ap.parse_args(argv)
    fn = {"score": cli_score, "record": cli_record, "stats": cli_stats, "snapshot": cli_snapshot, "undo": cli_undo}.get(a.cmd)
    if not fn:
        ap.print_help()
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
