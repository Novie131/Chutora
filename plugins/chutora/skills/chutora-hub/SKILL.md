---
name: chutora
description: Chutora 入口:/chutora、狀態、doctor、模式、語言、各項開關、ask
---
# /chutora

執行 `python3 "${CLAUDE_SKILL_DIR}/chutora.py"`，把使用者在 `/chutora` 後面打的參數原樣帶上：

- 沒有參數 → 狀態總覽與功能選單
- `doctor`（或「健檢」）→ 唯讀安裝健檢
- `mode [economy|balanced|quality]`（或「模式 省錢／平衡／品質」）→ 查看或切換模式
- `trim [on|off]`（或「瘦身」）→ 查看或切換噪音輸出瘦身
- `dedup [on|off]`（或「去重」）→ 查看或切換讀檔去重
- `mcp-trim [on|off]` → 查看或切換 MCP 輸出瘦身；`mcp-trim exclude|include <server>` 讓某個 server 完全不瘦身／恢復；`mcp-trim text on|off` 純文字也瘦身（預設不瘦）
- `guard [on|off|rules]`（或「守門」）→ 危險守門（實驗中）：查看、開關、列出規則
- `observe [on|off]`（或「觀察」）→ 觀察紀錄（實驗中）：查看或開關；`observe privacy [strict|normal]` 查看或切換隱私（strict 時你的糾正與選擇只記長度）
- `ask`（或「先問我」）→ 印出反問步驟，接著**照步驟用 AskUserQuestion 反問使用者**；`ask on|off` 開關自動反問提醒
- `changes` → 決策引擎（實驗中）自動做了、還沒確認的動作；`ok <id|all> [auto|ask]` 回饋（auto：這類以後可自動；ask：下次先問我；不加：只標成已讀）；`undo <id>` 用復原點還原；`decide [on|off|stats]` 開關自動執行、看校準統計
- `lang [zh|en|auto]` → 查看或切換提醒訊息語言
- `ledger [天數] [all] [json]`（或「損益表」）→ 損益表（唯讀）：過去 N 天（預設 7）各功能省了多少、固定開銷多少、真失誤與守門攔截分開算、各子 agent 成功率；`all` 看全部專案，`json` 給程式用

## 怎麼回報

- 狀態總覽：把腳本輸出原樣給使用者（它已經依語言輸出），不要另外改寫或刪減選單。使用者接著回覆編號或名稱時，就執行對應的 skill 或指令；使用者問被瘦身的輸出少了什麼時，用 Read 讀瘦身說明裡給的原文路徑（`~/.claude/chutora/raw/<id>.log`）。
- ledger：把腳本輸出原樣給使用者，不要改寫數字；它是估算（收入偏低、支出偏高），被問到就照表尾的說明解釋。
- doctor：先講結果那一行，再列出「要修」的項目與修法；「選用」項目簡短帶過。不要自動執行修法，問使用者要不要做。
- mode：切換後，這個對話剩下的部分也照新模式做（新模式的規則在 `../../hooks/modes/` 或 `~/.claude/hooks/chutora/modes/` 的對應檔案，讀一次即可）；新對話開始時 hook 會自動帶入。
- ask：腳本只印步驟；你接著真的去問（用 AskUserQuestion，題數照腳本寫的上限），問完把答案寫成任務說明，再繼續原本的工作。只有主對話能反問，子 agent 不行。
- ok／undo：上方若已有「Chutora 已依使用者這則訊息處理」的提示，代表 hook 已經處理好，直接轉告結果，不要再執行腳本。`ok … auto` 只能由使用者本人回覆，你自己跑會被守門攔下（正常，不要繞過）。
- guard／observe／decide off：危險守門會把「關掉守門或觀察」當成要問的動作，跳出確認是正常的，由使用者決定；不要換別的方法繞過。
- 腳本只讀紀錄、只寫 `~/.claude/chutora/` 底下自己的設定檔（`mode`、`lang`、`trim`、`dedup`、`mcp-trim`、`mcp-trim-exclude`、`mcp-trim-text`、`ask`、`guard`、`observe`、`observe-privacy`、`decide`），不碰 settings.json；`ok`／`undo` 會寫決策與變更紀錄、`undo` 會還原檔案。
