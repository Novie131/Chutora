---
name: chutora
description: Chutora 的單一入口。使用者輸入 /chutora、問「Chutora 有什麼功能」「現在狀態如何」、要健檢安裝（doctor）、切換省錢／平衡／品質模式、開關噪音輸出瘦身／讀檔去重／MCP 瘦身、要求「先問我」（ask）、或切換提醒語言時使用。Single entry point for Chutora: status, what it can do, install check (doctor), mode, output trimming / read dedup / MCP trimming switches, clarify-first (ask) and language switching.
---
# /chutora

執行 `python3 "${CLAUDE_SKILL_DIR}/chutora.py"`，把使用者在 `/chutora` 後面打的參數原樣帶上：

- 沒有參數 → 狀態總覽與功能選單
- `doctor`（或「健檢」）→ 唯讀安裝健檢
- `mode [economy|balanced|quality]`（或「模式 省錢／平衡／品質」）→ 查看或切換模式
- `trim [on|off]`（或「瘦身」）→ 查看或切換噪音輸出瘦身
- `dedup [on|off]`（或「去重」）→ 查看或切換讀檔去重
- `mcp-trim [on|off]` → 查看或切換 MCP 輸出瘦身
- `ask`（或「先問我」）→ 印出反問步驟，接著**照步驟用 AskUserQuestion 反問使用者**；`ask on|off` 開關自動反問提醒
- `lang [zh|en|auto]` → 查看或切換提醒訊息語言

## 怎麼回報

- 狀態總覽：把腳本輸出原樣給使用者（它已經依語言輸出），不要另外改寫或刪減選單。使用者接著回覆編號或名稱時，就執行對應的 skill 或指令；使用者問被瘦身的輸出少了什麼時，用 Read 讀瘦身說明裡給的原文路徑（`~/.claude/chutora/raw/<id>.log`）。
- doctor：先講結果那一行，再列出「要修」的項目與修法；「選用」項目簡短帶過。不要自動執行修法，問使用者要不要做。
- mode：切換後，這個對話剩下的部分也照新模式做（新模式的規則在 `../../hooks/modes/` 或 `~/.claude/hooks/chutora/modes/` 的對應檔案，讀一次即可）；新對話開始時 hook 會自動帶入。
- ask：腳本只印步驟；你接著真的去問（用 AskUserQuestion，題數照腳本寫的上限），問完把答案寫成任務說明，再繼續原本的工作。只有主對話能反問，子 agent 不行。
- 腳本只讀紀錄、只寫 `~/.claude/chutora/` 底下自己的設定檔（`mode`、`lang`、`trim`、`dedup`、`mcp-trim`、`ask`），不碰 settings.json。
