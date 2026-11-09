#!/usr/bin/env python3
"""Chutora 自我檢查（唯讀，不呼叫模型，不真的執行任何指令）。

用法：python3 <外掛路徑>/hooks/selfcheck.py
印出執行環境、外掛來源與版本、hook 最近一次觸發時間、守門與瘦身的 dry 結果、偵測到的語言；每項標 ✅／⚠️／❌。
給 VS Code 擴充（以及任何平台）確認「外掛有載入、hook 有觸發」用；步驟見 docs/vscode-check.md。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OK, WARN, BAD = "✅", "⚠️", "❌"

try:
    from compact import lang as _lang
except Exception:  # pragma: no cover
    _lang = lambda: "en"  # noqa: E731


def conf_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "chutora")


def plugin_version():
    try:
        with open(os.path.join(HERE, "..", ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return json.load(f).get("version") or "?"
    except Exception:
        return "?"


def last_activity():
    """~/.claude/chutora/activity 底下最新一次寫入的 epoch 秒數；沒有就是 None。"""
    d = os.path.join(conf_dir(), "activity")
    best = None
    try:
        for n in os.listdir(d):
            if n.endswith(".json"):
                t = os.path.getmtime(os.path.join(d, n))
                best = t if best is None or t > best else best
    except OSError:
        pass
    return best


def guard_decision(cmd):
    """用 guard 的判斷函式 dry 判斷；回傳 (決定或 None, 規則 id 清單)。不執行指令。"""
    import guard
    r = guard.decide({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": os.getcwd()})
    return (r[0], [h[0] for h in r[1]]) if r else (None, [])


def trim_lines(n=150):
    """150 行假 npm warn 輸出餵給 trim.shrink；回傳 (前行數, 後行數)。"""
    import trim
    text = "\n".join(f"npm warn deprecated pkg-{i}@1.0.{i}: this package is no longer supported" for i in range(n))
    r = trim.shrink(text, trim.classify("npm install"), trim.mode())
    return n, (len((r[0]).splitlines()) if r else n)


def run():
    lng = _lang()
    T = (lambda zh, en: zh if lng == "zh" else en)
    rows = []

    def add(mark, item, detail):
        rows.append((mark, item, detail))

    ep = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
    envs = {k: os.environ[k] for k in ("CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_ENTRY", "CLAUDECODE", "CLAUDE_CODE_REMOTE",
                                       "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "TERM_PROGRAM", "VSCODE_PID")
            if os.environ.get(k)}
    add(OK if ep else WARN, T("執行環境", "environment"),
        (", ".join(f"{k}={v}" for k, v in envs.items()) or T("沒有 Claude Code 相關環境變數（不是從 Claude Code 內執行？）",
                                                          "no Claude Code variables (not run from inside Claude Code?)"))
        + (T("（VS Code 擴充通常是 claude-vscode）", " (VS Code extension is usually claude-vscode)") if ep and "vscode" not in ep else ""))

    root = os.path.normpath(os.path.join(HERE, ".."))
    add(OK if plugin_version() != "?" else WARN, T("外掛來源與版本", "plugin source and version"),
        f"{root} · {plugin_version()}")

    t = last_activity()
    if t is None:
        add(WARN, T("hook 觸發紀錄", "hook activity"),
            T("~/.claude/chutora/activity 沒有紀錄：新對話裡讓 Claude 用一次工具（例如列出檔案）後再跑一次",
              "nothing in ~/.claude/chutora/activity: let Claude use any tool in a new conversation, then run this again"))
    else:
        ago = int(time.time() - t)
        add(OK if ago < 6 * 3600 else WARN, T("hook 觸發紀錄", "hook activity"),
            T(f"最近一次寫入 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))}（{ago} 秒前）",
              f"last write {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))} ({ago}s ago)"))

    for cmd, want in (("git push --force origin main", "force-push"),
                      ("find ~/.claude -name settings.json -exec sed -i s/a/b/ {} ;", "claude-settings")):
        try:
            dec, ids = guard_decision(cmd)
            add(OK if dec and want in ids else BAD, T("守門 dry", "guard dry-run"),
                f"{cmd} → {dec or T('不回應', 'no response')} {ids}")
        except Exception as e:
            add(BAD, T("守門 dry", "guard dry-run"), f"{cmd} → {type(e).__name__}: {e}")
    try:
        before, after = trim_lines()
        add(OK if after < before else BAD, T("瘦身 dry", "trim dry-run"),
            T(f"150 行假 npm warn 輸出：{before} 行 → {after} 行", f"150 fake npm warn lines: {before} → {after} lines"))
    except Exception as e:
        add(BAD, T("瘦身 dry", "trim dry-run"), f"{type(e).__name__}: {e}")

    det = ""
    try:
        with open(os.path.join(conf_dir(), "lang-detected")) as f:
            det = f.read().strip()
    except OSError:
        pass
    add(OK, T("語言", "language"), T(f"目前使用 {lng}；自動偵測檔：{det or '尚無'}", f"using {lng}; detected file: {det or 'none yet'}"))
    return rows


def main():
    rows = run()
    print(T_title(_lang()))
    for mark, item, detail in rows:
        print(f"{mark} {item}: {detail}")
    bad = sum(1 for r in rows if r[0] == BAD)
    warn = sum(1 for r in rows if r[0] == WARN)
    print(f"\n{OK} {len(rows) - bad - warn} / {WARN} {warn} / {BAD} {bad}")
    return 1 if bad else 0


def T_title(lng):
    return "Chutora 自我檢查（唯讀，不呼叫模型）" if lng == "zh" else "Chutora self-check (read-only, no model calls)"


if __name__ == "__main__":
    sys.exit(main())
