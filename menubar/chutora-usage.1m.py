#!/usr/bin/env python3
# <xbar.title>Chutora 用量儀表</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.desc>在 Mac 選單列顯示 Claude Code 與 Codex 的 5 小時／每週額度與上一輪 token。</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
"""Chutora 用量儀表：SwiftBar／xbar 選單列外掛（只用 python3 標準函式庫）。

資料來源：
  Claude：~/.claude/chutora/usage.json（chutora 狀態列與 agent-board 面板寫入）
  Codex ：$CODEX_HOME 或 ~/.codex 下最新 rollout 檔的最後一個 token_count 事件
任何錯誤都會輸出可用的標題，不讓 SwiftBar 顯示錯誤。
"""
import glob
import json
import math
import os
import sys
import time
from datetime import datetime

TAIL_BYTES = 256 * 1024
STALE_SECONDS = 6 * 3600
YELLOW, RED = 80, 95
C_YELLOW, C_RED, C_GRAY = "#D9A100", "#E5484D", "#8E8E93"
WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _pct(v):
    v = _num(v)
    return None if v is None else int(math.floor(v + 0.5))


def tok(n):
    n = _num(n)
    if n is None:
        return "—"
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a < 1000:
        return sign + str(int(round(a)))
    if a < 999950:
        return sign + ("%.1f" % (a / 1000)).rstrip("0").rstrip(".") + "k"
    return sign + ("%.1f" % (a / 1e6)).rstrip("0").rstrip(".") + "M"


def _window(d):
    """{'pct':…, 'resets_at':…} → (pct 或 None, resets_at 或 None)；不是 dict 就都是 None。"""
    if not isinstance(d, dict):
        return None, None
    return _num(d.get("pct")), _num(d.get("resets_at"))


# ---------------------------------------------------------------- 讀資料
def load_claude(home):
    """讀 usage.json，回傳 {'five_hour','seven_day','updated_at','last_turn','net'}；沒有或壞掉回傳 None。"""
    try:
        with open(os.path.join(home, ".claude", "chutora", "usage.json"), encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(j, dict):
        return None
    lim = j.get("limits") if isinstance(j.get("limits"), dict) else {}
    cl = j.get("claude") if isinstance(j.get("claude"), dict) else {}
    stamps = [t for t in (_num(lim.get("updated_at")), _num(cl.get("updated_at"))) if t is not None]
    out = {
        "five_hour": _window(lim.get("five_hour")),
        "seven_day": _window(lim.get("seven_day")),
        "updated_at": max(stamps) if stamps else None,
        "last_turn": None,
        "net": _num(cl.get("net")),
    }
    lt = cl.get("last_turn")
    if isinstance(lt, dict):
        out["last_turn"] = {
            "input": _num(lt.get("input")),
            "cache": (_num(lt.get("cache_write")) or 0) + (_num(lt.get("cache_read")) or 0)
            if _num(lt.get("cache_write")) is not None or _num(lt.get("cache_read")) is not None else None,
            "cache_write": _num(lt.get("cache_write")),
            "cache_read": _num(lt.get("cache_read")),
            "output": _num(lt.get("output")),
        }
    if out["five_hour"] == (None, None) and out["seven_day"] == (None, None) and not out["last_turn"] and out["net"] is None:
        return None
    return out


def _tail_lines(path):
    """最後約 256KB 的行（由新到舊）；從中間開始讀時丟掉第一行（可能被截斷）。"""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        start = max(0, size - TAIL_BYTES)
        f.seek(start)
        data = f.read()
    lines = data.split(b"\n")
    if start > 0 and lines:
        lines = lines[1:]
    return reversed(lines)


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _scan_rollout(path):
    info = limits = ts = None
    for raw in _tail_lines(path):
        raw = raw.strip()
        if not raw or b"token_count" not in raw:
            continue
        try:
            ev = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        p = ev.get("payload") if isinstance(ev, dict) else None
        if not isinstance(p, dict) or p.get("type") != "token_count":
            continue
        if ts is None:
            ts = _parse_ts(ev.get("timestamp"))
        if info is None and isinstance(p.get("info"), dict):
            info = p["info"]
        if limits is None and isinstance(p.get("rate_limits"), dict):
            limits = p["rate_limits"]
        if info is not None and limits is not None:
            break
    if info is None and limits is None:
        return None
    return info, limits, ts


def load_codex(codex_home):
    """讀最新 rollout 檔尾端的 token_count；回傳與 load_claude 同形狀，沒有回傳 None。"""
    try:
        files = glob.glob(os.path.join(codex_home, "sessions", "*", "*", "*", "rollout-*.jsonl"))
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except OSError:
        return None
    for path in files[:3]:
        try:
            found = _scan_rollout(path)
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if not found:
            continue
        info, limits, ts = found
        out = {"five_hour": (None, None), "seven_day": (None, None), "updated_at": ts or mtime, "last_turn": None, "net": None}
        for key in ("primary", "secondary"):
            w = (limits or {}).get(key)
            if not isinstance(w, dict):
                continue
            wm = _num(w.get("window_minutes"))
            if wm is None:
                continue  # 依 window_minutes 分類，不依位置
            slot = "five_hour" if abs(wm - 300) <= 60 else "seven_day" if abs(wm - 10080) <= 1440 else None
            if slot:
                out[slot] = (_num(w.get("used_percent")), _num(w.get("resets_at")))
        lt = (info or {}).get("last_token_usage")
        if isinstance(lt, dict):
            out["last_turn"] = {
                "input": _num(lt.get("input_tokens")), "cache": _num(lt.get("cached_input_tokens")),
                "cache_write": None, "cache_read": None, "output": _num(lt.get("output_tokens")),
            }
        return out
    return None


# ---------------------------------------------------------------- 顯示
def reset_text(resets_at, now):
    if resets_at is None:
        return ""
    diff = resets_at - now
    if diff <= 0:
        return "已重置"
    if diff < 24 * 3600:
        mins = int(math.ceil(diff / 60))
        return ("%dh%02dm 後" % (mins // 60, mins % 60)) if mins >= 60 else "%dm 後" % mins
    d = datetime.fromtimestamp(resets_at)  # 本機時間
    return "%s %02d:%02d" % (WEEKDAYS[d.weekday()], d.hour, d.minute)


def ago_text(updated_at, now):
    if updated_at is None:
        return "更新時間未知"
    s = max(0, now - updated_at)
    if s < 60:
        return "剛剛更新"
    if s < 3600:
        return "%d 分鐘前更新" % (s // 60)
    if s < 48 * 3600:
        return "%d 小時前更新" % (s // 3600)
    return "%d 天前更新" % (s // 86400)


def _live_pct(window, now):
    """已過重置時間的讀數不再可信（重置後用量歸零），當作沒有。"""
    pct, resets_at = window
    if pct is None or (resets_at is not None and resets_at <= now):
        return None
    return pct


def title_part(letter, src, now):
    parts = []
    for label, key in (("5h", "five_hour"), ("週", "seven_day")):
        pct = _live_pct(src[key], now)
        if pct is not None:
            parts.append("%s%d%%" % (label, _pct(pct)))
    return letter + " " + (" ".join(parts) if parts else "—")


def section(name, src, now, claude=False):
    lines = ["%s | size=13" % name]
    for label, key in (("5 小時", "five_hour"), ("每週", "seven_day")):
        pct, resets_at = src[key]
        if pct is None and resets_at is None:
            continue
        live = _live_pct(src[key], now)
        txt = "%s：%s" % (label, ("%d%%" % _pct(live)) if live is not None else "—")
        r = reset_text(resets_at, now)
        if r:
            txt += "　重置 " + r
        lines.append(txt + " | font=Menlo size=12" + _color(live))
    lt = src.get("last_turn")
    if lt:
        cache = tok(lt["cache"]) if lt["cache"] is not None else "—"
        if lt.get("cache_write") is not None or lt.get("cache_read") is not None:
            cache = "寫 %s 讀 %s" % (tok(lt.get("cache_write")), tok(lt.get("cache_read")))
        lines.append("上一輪 token：input %s／cache %s／output %s | size=12" % (tok(lt["input"]), cache, tok(lt["output"])))
    if claude and src.get("net") is not None:
        lines.append("淨省≈ %s tokens | size=12" % tok(src["net"]))
    stale = src["updated_at"] is not None and now - src["updated_at"] > STALE_SECONDS
    lines.append(ago_text(src["updated_at"], now) + ("（舊資料）" if stale else "") + " | size=11 color=" + C_GRAY)
    return lines


def _color(pct):
    if pct is None:
        return ""
    return " color=" + C_RED if pct >= RED else " color=" + C_YELLOW if pct >= YELLOW else ""


def build(home, codex_home, now):
    """回傳整份輸出（第一行標題、---、下拉選單）。"""
    sources = []
    for letter, name, loader, is_claude in (
        ("C", "Claude Code", lambda: load_claude(home), True),
        ("X", "Codex", lambda: load_codex(codex_home), False),
    ):
        try:
            src = loader()
        except Exception:
            src = None
        if src:
            sources.append((letter, name, src, is_claude))
    if not sources:
        return "\n".join([
            "Chutora —",
            "---",
            "還沒有用量資料 | size=12",
            "Claude：裝好 chutora 狀態列後會寫入 ~/.claude/chutora/usage.json | size=11 color=" + C_GRAY,
            "Codex：用過 Codex CLI 就會有 | size=11 color=" + C_GRAY,
            "---",
            "重新整理 | refresh=true",
        ])
    pcts = [p for _, _, s, _ in sources for k in ("five_hour", "seven_day") for p in [_live_pct(s[k], now)] if p is not None]
    worst = max(pcts) if pcts else None
    out = [" · ".join(title_part(l, s, now) for l, _, s, _ in sources) + (" | size=12" + _color(worst)), "---"]
    for i, (_, name, src, is_claude) in enumerate(sources):
        if i:
            out.append("---")
        out.extend(section(name, src, now, is_claude))
    out += ["---", "Opus／Sonnet 分項：外掛拿不到 | size=11 color=" + C_GRAY, "---", "重新整理 | refresh=true"]
    return "\n".join(out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        home = os.path.expanduser("~")
        codex_home = os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
        text = build(home, codex_home, time.time())
    except Exception as e:  # 不能讓 SwiftBar 顯示錯誤
        text = "Chutora —\n---\n讀取失敗：%s | size=11 color=%s\n---\n重新整理 | refresh=true" % (str(e)[:80].replace("\n", " "), C_GRAY)
    print(text)


if __name__ == "__main__":
    main()
