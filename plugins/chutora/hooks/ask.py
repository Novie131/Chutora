#!/usr/bin/env python3
"""UserPromptSubmit hook：反問提醒。

使用者明確要求先問（「先問我」「ask me first」），或表達不清楚、不確定（「我不太清楚」「不確定」
「你覺得呢」「not sure」「what do you think」…）時，在提示旁帶入一句提醒：先用 AskUserQuestion
把會改變結果的地方問清楚（題數依模式），再動手。只提醒主對話；子 agent 不會收到使用者提示，本來就不會觸發。

不擋提示、不改提示。開關：CHUTORA_ASK=0 關閉；/chutora ask off|on 寫入 ~/.claude/chutora/ask。
任何例外都安靜放行。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from trim import cfg_file, mode  # noqa: E402

try:
    from compact import lang
except Exception:  # pragma: no cover
    lang = lambda: "en"  # noqa: E731

MAX_Q = {"economy": 3, "balanced": 4, "quality": 5}

EXPLICIT = re.compile(
    r"(先問我|先反問|問我一下|先跟我確認|先確認一下需求|有問題先問|/chutora\s+ask\b|"
    r"\bask me (?:first|before)\b|\bclarify (?:with me )?first\b|\bask (?:me )?(?:some )?(?:clarifying )?questions? first\b)",
    re.I)
UNSURE = re.compile(
    r"(我?不太清楚|不太確定|不確定(?:要|該|怎|是否|哪)|還沒想好|沒什麼想法|不知道(?:要|該|怎麼|哪)|你覺得呢|你覺得怎麼樣|"
    r"你建議|幫我想想|有什麼建議|\bnot sure\b|\bunsure\b|\bi(?:'m| am) not certain\b|\bdon'?t know (?:what|which|how|if|whether)\b|"
    r"\bwhat do you (?:think|suggest|recommend)\b|\bany suggestions\b|\bhaven'?t decided\b)",
    re.I)


def enabled():
    if os.environ.get("CHUTORA_ASK", "").strip() == "0":
        return False
    return cfg_file("ask") != "off"


def message(kind, n):
    if lang() == "en":
        why = "asked to be asked first" if kind == "explicit" else "said they are not sure"
        return (f"Chutora clarify: the user {why}. Before planning or delegating, use the AskUserQuestion tool to ask "
                f"at most {n} questions, only about what would change the result: scope (in / out), what counts as done, "
                f"constraints (what must not change), edge cases, and trade-offs (fast vs complete). Put the recommended "
                f"option first in each question and offer \"use the defaults, stop asking\". If the request is only to "
                f"investigate or explain, answer directly instead. Write the answers into a short task brief "
                f"(claude-memory/briefs/<date>-<slug>.md, or briefs/ in the auto memory folder) with \"what counts as done\" "
                f"marked as acceptance criteria, and attach it when delegating.")
    why = "要求先問清楚" if kind == "explicit" else "表示不太確定"
    return (f"Chutora 反問：使用者{why}。規劃或派工之前，先用 AskUserQuestion 問最多 {n} 題，只問會改變結果的地方："
            f"範圍（做／不做）、怎樣算完成、限制（不能動什麼）、邊界情況、取捨（快還是完整）。每題第一個選項放建議選項，"
            f"並提供「照預設、別問了」。如果使用者只是要你查證或解釋，就直接做，不必反問。答案寫成精簡任務說明"
            f"（claude-memory/briefs/<日期>-<slug>.md，沒有 claude-memory 時放 auto memory 目錄的 briefs/），"
            f"「怎樣算完成」標成驗收標準，派工時附給 worker。")


def process(data):
    if not enabled():
        return None
    text = data.get("prompt") or ""
    if not isinstance(text, str) or not text.strip():
        return None
    if EXPLICIT.search(text):
        kind = "explicit"
    elif UNSURE.search(text):
        kind = "unsure"
    else:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": message(kind, MAX_Q.get(mode(), 4))}}


def main():
    try:
        out = process(json.load(sys.stdin))
    except Exception:
        return
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
