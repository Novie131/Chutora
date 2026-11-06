"""遮罩常見金鑰與密碼格式（observe.py、changes.py、guard.py 共用）。寧可多遮，不存原值。"""
import re

MASK = "[REDACTED]"

PATTERNS = [
    # 私鑰區塊
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    # 各家 token 前綴
    re.compile(r"\bsk-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\b(?:rk|pk|sk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    # Authorization: Bearer xxx
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    # URL 裡的帳密 https://user:pass@host
    re.compile(r"(?<=://)[^\s/:@]+:[^\s/@]+(?=@)"),
]
# key=value／key: value 形式：保留鍵名，值遮掉
KV = re.compile(
    r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|"
    r"client[_-]?secret|auth(?:orization)?|credential|session[_-]?key)[\"']?\s*[=:]\s*[\"']?)"
    r"([^\s\"',;&|]{4,})")


def redact(text):
    if not isinstance(text, str) or not text:
        return text
    for p in PATTERNS:
        text = p.sub(MASK, text)
    return KV.sub(lambda m: m.group(1) + MASK, text)


def short(text, limit=160):
    """單行化、遮罩、截到 limit 字元。"""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    # 先取一段比上限寬得多的視窗再遮罩（避免大段輸出拖慢），最後才截到上限：
    # 被視窗切斷的半截金鑰一定落在上限之外，不會留下來。
    t = redact(re.sub(r"\s+", " ", text[: limit * 4 + 400]).strip())
    return t if len(t) <= limit else t[: limit - 1] + "…"
