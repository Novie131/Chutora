"""自動壓縮點的共用小模組（statusline.py 與 context-check.py 共用）。

Claude Code 的 settings.json 鍵 autoCompactWindow 是「壓縮視窗」，
實際壓縮點約為 autoCompactWindow 扣掉 /context 顯示的 Autocompact buffer。
buffer 預設 33000（本機實測值，用 /context 確認），可用環境變數 CONTEXT_AUTOCOMPACT_BUFFER 覆寫。
"""
import json, os, re

DEFAULT_BUFFER = 33000
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".claude", "chutora")  # 使用者層級設定（語言、模式）
DEFAULT_REMIND = 100000  # 提醒門檻預設值的唯一來源（usage_stats.py 在別的目錄，另寫一份 100000）


def remind_tokens():
    """提醒門檻（tokens）：環境變數 CONTEXT_REMIND_TOKENS，沒設或不是整數就用 DEFAULT_REMIND。"""
    try:
        return int(os.environ.get("CONTEXT_REMIND_TOKENS", DEFAULT_REMIND))
    except ValueError:
        return DEFAULT_REMIND


def remind_enabled():
    """context 提醒是否開啟（預設關）：CHUTORA_CONTEXT_REMIND=1／on 開、0／off 關；
    沒設環境變數就看 ~/.claude/chutora/remind 的內容是不是 on。"""
    v = (os.environ.get("CHUTORA_CONTEXT_REMIND") or "").strip().lower()
    if v:
        return v in ("1", "on", "true", "yes")
    try:
        with open(os.path.join(CONFIG_DIR, "remind")) as f:
            return f.read(16).strip().lower() in ("on", "1", "true", "yes")
    except OSError:
        return False


def compact_point():
    """回傳預估的自動壓縮點（tokens）；沒設定、讀不到、JSON 壞掉都回傳 None，不丟例外。"""
    try:
        with open(os.path.expanduser("~/.claude/settings.json")) as f:
            window = json.load(f).get("autoCompactWindow")
        if isinstance(window, bool) or not isinstance(window, int):
            return None
        buffer = int(os.environ.get("CONTEXT_AUTOCOMPACT_BUFFER", DEFAULT_BUFFER))
        return window - buffer
    except Exception:
        return None


DETECT_MIN_CJK = 4      # 中文至少要有這麼多個漢字才採信（太短不更新）
DETECT_MIN_LATIN = 20   # 英文至少要有這麼多個拉丁字母才採信
DETECT_ZH_RATIO = 0.3   # 漢字占「字母類字元」的比例達到這個值記為 zh
_URL = re.compile(r"https?://\S+|www\.\S+")
_CODE = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*`", re.S)


def detect_lang(text):
    """從一段提示文字猜語言：回傳 "zh"、"en" 或 None（資訊不足）。純本地、不輸出。
    先去掉網址與程式碼區塊；漢字占字母類字元 >= 30%（且至少 4 字）→ zh；
    否則拉丁字母 >= 20 個 → en；其餘不判斷。"""
    if not isinstance(text, str):
        return None
    t = _CODE.sub(" ", _URL.sub(" ", text))
    cjk = latin = other = 0
    for ch in t:
        if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
            cjk += 1
        elif ch.isalpha():
            if ch.isascii() or "\u00c0" <= ch <= "\u024f":
                latin += 1
            else:
                other += 1
    total = cjk + latin + other
    if cjk >= DETECT_MIN_CJK and cjk / total >= DETECT_ZH_RATIO:
        return "zh"
    if latin >= DETECT_MIN_LATIN:
        return "en"
    return None


def detected_path():
    return os.path.join(os.path.expanduser("~"), ".claude", "chutora", "lang-detected")


def note_prompt_lang(text):
    """UserPromptSubmit 時呼叫：偵測得出來就寫進 ~/.claude/chutora/lang-detected（zh／en）；沒變就不寫。
    不輸出任何東西，任何錯誤都安靜結束。"""
    try:
        got = detect_lang(text)
        if not got:
            return None
        p = detected_path()
        try:
            with open(p) as f:
                if f.read().strip() == got:
                    return got
        except OSError:
            pass
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w") as f:
            f.write(got + "\n")
        os.replace(p + ".tmp", p)
        return got
    except Exception:
        return None


def lang():
    """訊息語言：zh 或 en。

    依序：環境變數 CHUTORA_LANG → ~/.claude/chutora/lang（/chutora lang 寫入）→
    ~/.claude/chutora/lang-detected（UserPromptSubmit 時依使用者提示自動偵測）→
    LC_ALL / LC_MESSAGES / LANG 第一個有值的（zh 開頭為中文）→ 英文。
    """
    def pick(v):
        v = (v or "").strip().lower()
        return "zh" if v.startswith("zh") else "en" if v.startswith("en") else None
    got = pick(os.environ.get("CHUTORA_LANG"))
    if got:
        return got
    try:
        with open(os.path.join(os.path.expanduser("~"), ".claude", "chutora", "lang")) as f:
            got = pick(f.read())
        if got:
            return got
    except OSError:
        pass
    try:
        with open(detected_path()) as f:
            got = pick(f.read())
        if got:
            return got
    except OSError:
        pass
    for k in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(k)
        if v:
            return "zh" if v.strip().lower().startswith("zh") else "en"
    return "en"
