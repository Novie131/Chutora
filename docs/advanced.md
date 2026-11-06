# Chutora 進階說明

<p><a href="../README.md">← 回到 README</a> · <a href="advanced.en.md">English</a></p>

README 只留三分鐘上手；這份是完整說明。

<a name="problem"></a>

## <img src="../assets/icons/puzzle.svg" width="26" height="26" alt=""> 這解決什麼問題

用 Claude Code 一陣子，常會遇到兩件事：

- **貴**：所有事都由主對話的 Opus 親自做，包括讀長 log、看一堆截圖、改幾十個檔案。這些工作大多用便宜的模型就夠了。
- **對話越聊越長**：每一則訊息、每一次讀檔的結果，之後每一輪都會重新送給模型一次。對話拖到後面，大部分花費都在重讀舊內容。實測一位重度使用者的 21 個 session，主對話每次呼叫的 context 中位數約 24 萬 token。

這個 plugin 的做法像一位主管帶團隊：主管（Opus）聽你說、想清楚、決定派給誰；動手的工作交給組員（Sonnet、Haiku）在各自的桌上做完，只把結論交回來，主管的桌面因此保持乾淨。桌面快滿時，主管先寫好交接筆記，清掉桌面後照筆記繼續做。

**適合**：已經在用 Claude Code、常做多步驟工作（改程式、讀 log、查資料），想省錢或不想讓長對話失控的人。只偶爾問一兩句話的話，分工的好處不明顯。

---

<a name="usage"></a>

## <img src="../assets/icons/bubble.svg" width="26" height="26" alt=""> 裝完之後怎麼用

照平常講話就好，主對話會自己判斷要不要派工：

| 你說 | 誰處理 |
|---|---|
| 「幫我想清楚這該怎麼做」 | 主對話（Opus）自己想 |
| 「照剛才講的做」 | worker（Sonnet）動手，做完先驗證再回報 |
| 「看一下這 18 張截圖有沒有跑版」「這份 log 為什麼失敗」 | bulk（Haiku）讀完只回結論 |
| 「我之前有記過 X 嗎」 | librarian（Haiku）查記憶，附出處 |
| 「這個 API 新版怎麼設定」 | research skill 查外部資料，回答附來源，官方資料存進 `claude-memory/web/` |
| 「交接一下」 | handoff skill 寫 `handoff.md`，之後可以 `/clear` |

想強制指定某個 agent，用 `@agent-chutora:worker`。

對話變長時（預設超過 10 萬 token）你會看到提醒，Claude 會先把目前進度寫進 `handoff.md`。之後不管是自動壓縮、`/clear` 還是隔天開新對話，交接筆記都會自動帶回來，不用重新解釋一次。

### 名詞小抄

- **context**：模型這一輪看得到的全部內容，包括系統提示、對話紀錄、工具結果。以 token 計算，越長越貴。
- **子 agent（subagent）**：主對話派出去的助手，在自己獨立的 context 裡工作，只把結論交回來。
- **skill**：可以呼叫的固定作業流程，例如寫交接筆記的 `handoff`。
- **hook**：Claude Code 在特定時機自動執行的腳本，例如 session 開始時、你送出訊息時。
- **effort**：模型思考的力道。越高想得越久，也越貴。
- **自動壓縮（autocompact）**：context 快滿時，Claude Code 把舊對話壓成摘要。
- **Cowork**：Claude 桌面版的代理工作模式。

---

<a name="modes"></a>

## <img src="../assets/icons/sliders.svg" width="26" height="26" alt=""> 三種模式、語言與每週回顧

### 三種模式

模式改的是 session 開始時帶進主對話的派工慣例，加上噪音輸出瘦身與 MCP 瘦身的門檻、反問一次最多幾題（省錢 3、平衡 4、品質 5）。各 agent 用的模型和 effort 寫在 agent 檔案裡，plugin 沒辦法依模式改，所以切換模式不會讓 worker 換成別的模型。實際效果取決於 Claude 照慣例做的程度。

| 模式 | 實際改變 |
|---|---|
| 省錢 `economy` | 更積極派工：讀超過 3 個檔、看圖、讀長 log、指令輸出很長都交給 bulk 或 Explore；小修改也整包交給 worker；worker 失敗先補背景重派一次再升級；驗證只跑相關的測試 |
| 平衡 `balanced`（預設） | 照分工慣例做，不額外調整 |
| 品質 `quality` | worker 失敗一次就直接升級 worker-hard；主對話親自看過關鍵 diff 才採用；驗證跑完整測試套件；牽涉設計取捨先問你 |

切換：`/chutora mode economy`（或 `balanced`、`quality`，也可以打「省錢」「平衡」「品質」）。設定存在 `~/.claude/chutora/mode`，新對話開始時生效，切換的那個對話也會照新模式做。刪掉這個檔就回到預設。

### 語言

提醒訊息、交接提示、狀態列和 `/chutora` 會依序看：

1. 環境變數 `CHUTORA_LANG`（`zh` 或 `en`）
2. `~/.claude/chutora/lang`（用 `/chutora lang zh`、`/chutora lang en` 寫入；`/chutora lang auto` 刪除）
3. 系統語言 `LC_ALL`、`LC_MESSAGES`、`LANG` 第一個有值的，`zh` 開頭就用中文
4. 都沒有就用英文

macOS 從 Dock 或 VS Code 啟動時，常常沒有設定 `LANG`。看到英文提醒的話，執行一次 `/chutora lang zh` 就會固定成中文。

### 每週回顧

每個 ISO 週的第一個對話開始時，畫面上會出現一行估算：過去 7 天子 agent 處理的 token，如果改由主對話最常用的模型處理，依 API 牌價要多花多少。

- 只算模型價差，不含 context 隔離省下的重讀成本，所以是保守的估計。
- 訂閱方案不是按 token 計費，這個數字只用來比較相對大小。
- 價格表與 `usage-stats` 共用；要看完整報表用 `/chutora:usage-stats`。
- 不想看：在 `~/.claude/settings.json` 的 `"env"` 加 `"CHUTORA_WEEKLY": "0"`。
- 有開噪音輸出瘦身時，同一行會附上「瘦身讓多少 token 沒進到 context」的估算。

### 噪音輸出瘦身

`npm install`、`pytest`、`cargo build` 這類指令常常印出幾百行進度和日誌，真正有用的只有錯誤和最後的摘要，但整段都會進到 context、之後每一輪重送。Chutora 用標準的 PostToolUse hook（`hooks/trim.py`）在結果進到 context 前先瘦身：

- **何時處理**：只處理成功的 Bash 指令，而且輸出超過門檻才動。門檻依模式：省錢 3000 字元或 80 行、平衡 4000 字元或 120 行、品質 8000 字元或 250 行。不認得的指令門檻加倍、保留更多。
- **怎麼瘦**：去掉色碼與 `\r` 進度覆寫，收斂進度列與重複行，保留開頭與結尾各數十行；含 error、fail、exception、traceback、warning、assert 等關鍵字的行一定保留，連同前後 2 行；測試結果、安裝摘要這類摘要行也保留。瘦身省不到兩成就不動。
- **絕不動**：讀檔類指令（`cat`、`head`、`tail`、`sed`、`grep`、`ls`…）、`git diff`／`show`／`log`／`status`、已經自己接了 `| head`、`| grep` 的指令、`python -c`、JSON 輸出、背景指令、Claude Code 自己已經另存的超大輸出。失敗的指令走 PostToolUseFailure，那裡不能改寫輸出，所以錯誤輸出一律完整保留。
- **原文一定留著**：存到 `~/.claude/chutora/raw/<tool_use_id>.log`（保留最近 50 份），瘦身後的輸出最後一行會寫明路徑，Claude 需要被略過的內容時會用 Read 讀回來。
- **開關**：`/chutora trim off`（寫入 `~/.claude/chutora/trim`）或環境變數 `CHUTORA_TRIM=0`；`/chutora trim on` 改回。
- **省了多少**：累計瘦身掉的字元數記在 `~/.claude/chutora/trim-stats.json`，`/chutora` 與每週回顧會換算成 token 顯示。換算用「字元數÷4」，是估算。


### 讀檔去重

Claude 常在同一段對話裡反覆讀同一個沒改過的檔案，每讀一次就再付一次 token。`hooks/dedup.py`（PostToolUse，Read）在下面這些條件**全部**成立時，把結果換成一行「跟第 N 次讀的一樣、檔案沒變，請參考那次的結果」：

- 同一個 context：主對話與每個子 agent（hook 輸入的 `agent_id`）分開記，絕不跨 context。
- 同一個檔案、同一個範圍（offset／limit、起始行、行數），而且內容雜湊完全相同。
- 先前那次讀取的結果還在**目前這條對話鏈**上：hook 會讀 transcript，從最新一筆沿著 `parentUuid` 往回找那次的 `tool_use_id`。壓縮、`/clear`、`/rewind` 之後舊結果不在鏈上，就照常重讀；transcript 讀不到也一律不去重。
- 不是圖片、PDF、notebook，也不是被截斷的讀取；檔案至少 1500 字元。

Claude Code 自 2.1.86 起內建類似機制（重複讀取未變更的檔案時回傳 `file_unchanged`），但它由遠端旗標控制，社群回報 2.1.286 之後很多 session 不再觸發（[anthropics/claude-code#100265](https://github.com/anthropics/claude-code/issues/100265)）。內建機制有出手時，這個 hook 收到的不是完整內容，就什麼都不做。

開關：`/chutora dedup off`（寫入 `~/.claude/chutora/dedup`）或 `CHUTORA_DEDUP=0`。省下的量記在 `trim-stats.json` 的 `dedup` 欄，換算 token 是估算。

### MCP 輸出瘦身

`hooks/mcptrim.py`（PostToolUse，`mcp__.*`）處理 MCP 工具回傳的大坨資料，用 `updatedMCPToolOutput` 替換：

- **何時處理**：整份輸出超過門檻才動，門檻與保留量依模式：省錢 3000 字元／陣列留 20 筆，平衡 4000／30，品質 8000／60。省不到兩成就不動。
- **JSON**：長陣列保留前 N 筆並註明另有幾筆、連續相同的項目合併成一行、`null`、`""`、`[]`、`{}` 這類空欄位拿掉。字串欄位不截斷。
- **純文字與 Markdown 不動**：使用說明、文件內容這類輸出每一行都可能有用。0.15 曾把 Claude Docs connector 的 `guide` 說明砍掉 204 行，0.16 起預設不處理。真的想瘦身純文字，用 `/chutora mcp-trim text on`（或 `CHUTORA_MCP_TRIM_TEXT=1`）：會沿用噪音輸出瘦身的行規則（保留開頭、結尾、錯誤與摘要行），並截斷 JSON 裡的長字串（省錢 800、平衡 1500、品質 3000 字元）。
- **形狀照抄**：原本是字串就回字串，是 content 陣列就回 content 陣列；圖片等非文字區塊不動。
- **原文**：存到 `~/.claude/chutora/raw/<tool_use_id>.log`，輸出最後一行寫明路徑。
- **排除清單**：`/chutora mcp-trim exclude <server>`（`include` 恢復，改檔前備份成 `.bak`），或直接寫環境變數 `CHUTORA_MCP_TRIM_EXCLUDE`（逗號分隔）、`~/.claude/chutora/mcp-trim-exclude`（一行一個）。可以寫工具全名、前綴（`mcp__github__`），或只寫 server 名稱（`github`，等同 `mcp__github__`）。
- **開關**：`/chutora mcp-trim off` 或 `CHUTORA_MCP_TRIM=0`。

### 反問

參考 [github/spec-kit](https://github.com/github/spec-kit) 的 clarify 步驟（先找出講不清楚的地方問你，再把答案寫回規格），Chutora 做的是不需要寫整份規格的輕量版：

- **什麼時候問**：你說「先問我」或輸入 `/chutora ask`；你說「我不太清楚」「不確定」「你覺得呢」這類話（`hooks/ask.py` 會在提示旁帶入一句提醒）；或大任務需求模糊（會動多個檔案、範圍不明、有多種做法），由分工慣例讓主對話自己判斷。小事、已經講清楚的不問。只有主對話問，子 agent 不問。
- **怎麼問**：用 Claude Code 內建的 AskUserQuestion，一次最多省錢 3 題、平衡 4 題、品質 5 題；每題第一個選項是建議選項，也一定有「照預設、別問了」。只問會改變結果的：範圍（做／不做）、怎樣算完成、限制（不能動什麼）、邊界情況、取捨（快還是完整）。
- **答案去哪**：寫成 `claude-memory/briefs/<日期>-<slug>.md`（沒有 claude-memory 時放 auto memory 目錄的 `briefs/`），欄位是目標、範圍、驗收標準、限制、邊界情況、取捨；派工時附給 worker。「怎樣算完成」就是驗收標準，之後的落地驗收會直接用它。
- **開關**：`/chutora ask off` 或 `CHUTORA_ASK=0` 只關掉「你說不確定時」的提醒；`/chutora ask` 隨時可以強制先問。

### 危險守門（實驗中）

`hooks/guard.py`（PreToolUse，`Bash|Write|Edit|MultiEdit|NotebookEdit|Read`）在工具執行前檢查「永遠要問清單」，命中時回傳標準的 `hookSpecificOutput.permissionDecision` 與雙語的 `permissionDecisionReason`：

- **先問你（ask）**：force push（`--force`、`-f`、`--force-with-lease`、`+分支`）；推到 main／master（含沒寫分支、但目前就在 main）；`rm -rf` 或刪除專案外的檔案（暫存目錄底下除外）；刪掉整個專案或它的 `.git`；刪除路徑含無法確認的變數；讀寫 `.env`（`.env.example` 這類範本除外）與金鑰檔（`id_rsa`、`*.pem`、`*.key`、`.netrc`…）；`DROP TABLE`／`DROP DATABASE`／`TRUNCATE`；`terraform destroy`；`kubectl delete`；修改 `~/.claude/settings.json`、專案的 `.claude/settings.json` 或 Chutora 設定（含 `/chutora guard off`）；`git reset --hard`；`git clean -f`。
- **直接擋（deny）**：非常明確的災難：`rm -rf /`、`rm -rf ~`、刪除系統目錄、`mkfs`、`dd of=/dev/<磁碟>`。原因回給 Claude，請你自己決定要不要在終端機執行。
- **不誤攔**：指令先經過一個小型 shell 斷詞（引號、heredoc、`$(...)`、`sh -c`、`sudo`／`env` 前綴、`cd` 之後的路徑），所以 commit 訊息、`echo`、`grep` 裡「提到」這些字不會被攔；`git push origin feat/x`、`rm -rf node_modules`、`rm -rf build/` 都照常執行。解析不了（例如引號沒關）時退回保守的整段比對。這是盡力而為的檢查，不是沙盒。
- **權限模式**：PreToolUse hook 在任何權限模式下都會先執行。官方文件寫明 `deny` 在 bypassPermissions／`--dangerously-skip-permissions` 下仍然有效；`ask` 在 bypass 下怎麼處理文件沒寫，所以實測了 Claude Code 2.1.319 的 `claude -p`：預設模式、`--allowedTools Bash`（allow 規則）與 `--dangerously-skip-permissions` 下，被要求確認的指令都沒有執行（沒有人可以確認，記在 `permission_denials`），原因回給 Claude。互動模式下的確認畫面，以及互動式 bypass 模式的行為還沒實測。在 bypassPermissions／dontAsk 模式下，原因會另外告訴 Claude「這次沒有執行，請向你說明、不要繞路」。
- **自訂**：`~/.claude/chutora/always-ask` 一行一條：`<regex>` 額外要問（比對 Bash 指令全文，或檔案工具的路徑）、`deny: <regex>` 額外直接擋、`!<規則 id>` 移除一條預設規則（`/chutora guard rules` 列出 id）、`#` 開頭是註解。壞掉的 regex 會被略過，`/chutora doctor` 會列出來。
- **紀錄**：每次攔下都寫一筆到變更紀錄（見[記憶](#memory)）與觀察紀錄；之後同一個呼叫真的執行了（你按了允許），會補記 `user_response: approved`。
- **開關**：`/chutora guard off`（寫入 `~/.claude/chutora/guard`；這個指令本身也會先問你）或 `CHUTORA_GUARD=0`。

### 觀察紀錄（實驗中）

`hooks/observe.py`（PostToolUse、PostToolUseFailure、SubagentStop、UserPromptSubmit）把發生的事記到 `~/.claude/chutora/projects/<專案 id>/observations.jsonl`，是之後「從結果學習」的地基。

- **不花 token**：hook 不輸出任何東西。實測同一個任務各跑兩次，有這些 hook 的輸入 token 是 83,795／83,790，沒有的是 83,788／83,785，差距在每次執行本來就有的幾個 token 之內。
- **專案 id**：從 `CLAUDE_PROJECT_DIR`（沒有就用目前目錄）往上找 git repo，取 remote URL（去掉帳密與 `.git`）的 sha256 前 12 字元；沒有 remote 用 repo 根目錄路徑；不在 repo 裡用目錄路徑。同一個 repo 換位置 clone 也是同一個 id。資料夾裡的 `meta.json` 寫著它是哪個專案。
- **每筆內容**：時間、session、agent（`main` 或子 agent 類型）、訊號（`tool_ok`、`tool_fail`、`repeat_error`、`delegation_result`、`user_correction`、`user_choice`、`user_prompt`、`guard_ask`、`guard_deny`）、工具名、精簡摘要（指令、路徑、子 agent 描述，最多 160 字元）與輸出大小。**不存工具輸出內容**；一般提示只記長度；常見金鑰格式（`sk-…`、`ghp_…`、`AKIA…`、JWT、`Bearer …`、`password=…`、網址裡的帳密、私鑰區塊）一律遮罩。
- **糾正與選擇**：「不對」「錯了」「我不是要這個」「不是這樣」、`that's wrong`、`not what I asked` 這類話記成 `user_correction`；只回一個編號、「選 B」、以及 AskUserQuestion 的答案記成 `user_choice`。
- **輪替**：超過 5 MB 移到同一層的 `archive/`，最多留 5 份（`CHUTORA_OBSERVE_MAX_MB` 可調）。
- **開關**：`/chutora observe off`（寫入 `~/.claude/chutora/observe`）或 `CHUTORA_OBSERVE=0`。

---

<a name="details"></a>

## <img src="../assets/icons/branch.svg" width="26" height="26" alt=""> 運作細節

### 為什麼這樣省

**路由發生在 Opus 之後，不是之前。** 判斷意圖就得先讀懂訊息，而讀懂就等於規劃了，所以沒辦法在前面放一個便宜的路由器。Opus 永遠是入口，由它派工。

省下的錢來自四個地方，照影響大小排序：

1. **Context 隔離**（最大的一筆，而且是複利）。在主對話裡跑 30 次工具呼叫，那 30 份結果會被反覆計費到對話結束；派給子 agent 的話，主對話只收到一份摘要。派工要整包派，不要一件一件派，因為每次啟動子 agent 都要重付一次系統提示與記憶注入。
2. **模型分層。** 有用，但是線性的：省的比例大致等於價差。
3. **`effort` 等級。** worker 用 `medium`，失敗才升級到 worker-hard（`high`）；librarian 用 `low`。
4. **主對話別開太久。** 隔離只管得到工具呼叫，管不到對話本身變長，所以 plugin 另外盯著長度，超過門檻就提醒寫交接筆記（見[進階設定](#advanced)）。話題告一段落時，換新對話或 `/clear` 仍然最省。

### 失敗怎麼辦

子 agent 收工時用固定的回報格式，主對話只看前兩行就能決定下一步：狀態行（完成、失敗、需要決策）與驗證行（通過、未驗證、失敗）。「完成」只能搭配「驗證通過」。遇到需要決策的岔路時，子 agent 會停下來回報有哪些選項與各自的影響，不會自己選一條路走完。

失敗升級依序：補背景後同一個 agent 重派 → bulk 失敗改 worker → worker 失敗改 worker-hard（附前次失敗報告）→ 仍失敗就停下來重新規劃或問你。不會無限升級。

---

<a name="advanced"></a>

## <img src="../assets/icons/wrench.svg" width="26" height="26" alt=""> 進階設定

### context 提醒與自動壓縮

- UserPromptSubmit hook 在 context 超過 10 萬 token 時提醒一次，之後每多 4 萬再提醒。門檻可用環境變數 `CONTEXT_REMIND_TOKENS` 調整。
- 提醒時 Claude 用 handoff skill 把現況寫進 `handoff.md`（目前任務 / 已完成 / 下一步 / 未決問題）。
- 有設 `autoCompactWindow` 時，提醒只會告訴你約多少 k 會自動壓縮、壓縮後會帶回交接筆記；沒設才給可複製的指令：告一段落用 `/clear`、做到一半用 `/compact` 並指定重點、後半段是除錯雜訊就用 `/rewind` 局部摘要。
- 每次壓縮、`/clear`、新 session 開始時，SessionStart hook 自動帶入 `handoff.md`：專案有 `claude-memory/` 就用它，否則用 transcript 旁 auto memory 目錄的 `handoff.md`（Claude Code 只會自動帶入 auto memory 的 MEMORY.md 索引，不會帶 handoff.md）。

建議在 `~/.claude/settings.json` 把自動壓縮當保險（plugin 不能代設，`/chutora:route-setup` 會幫你安全地寫入）：

```
"autoCompactWindow": 153000
```

扣掉約 33k 的 buffer 後，約在 12 萬自動壓縮，在 10 萬提醒之後留 2 萬緩衝寫 handoff。33k 是作者機器的實測值（不確定是否固定）；寫入後請用 `/context` 確認 Autocompact buffer 約 33k、壓縮點約 120k（有 `modelSettings` 逐模型覆蓋時要一併看）。

### 狀態列（選用）

閒置時顯示 `模型 │ ctx 95k │ 提醒 100k │ 壓縮 120k`；Claude 工作時改顯示目前動作（駕駛艙穩定版）：`▶ worker·Sonnet 跑測試 npm test · 12s │ 本次 42k tok │ 瘦身省≈8k │ ctx 95k/120k`。「本次」是這個 session 新處理的 token（input＋cache 寫入＋output，不含 cache 讀取，主對話加子 agent，從 transcript 精確加總）；「瘦身省≈」是瘦身、去重、MCP 瘦身擋下的字元 ÷4，屬於估算。目前動作由 `activity.py` 記在 `~/.claude/chutora/activity/`，`CHUTORA_ACTIVITY=0` 關閉；寬度不夠時依重要性丟掉後面的欄位（`CHUTORA_STATUS_WIDTH` 可指定寬度）。壓縮點讀自 `autoCompactWindow`（沒設就不顯示）。plugin 不能設定主狀態列：plugin 安裝的使用者請用 `/chutora:route-setup`，它會把檔案放到固定位置；install.sh 安裝的用 `bash install.sh --with-statusline`，或手動貼進 settings.json：

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/chutora/statusline.py" }
```

### 子 agent 看板與回覆模式切換鍵（選用）

兩個選裝的 mod（Claude Code 的介面擴充，需要 2.1.299 以上；作者在 VS Code 擴充 2.1.301 實測）：

| mod | 做什麼 |
|---|---|
| `agent-board`（駕駛艙面板） | 「現在」大卡、待辦分格進度、三色工作量長條與三張小卡（交給 Sonnet／Haiku 的比例、瘦身擋下的量、主對話 context）、動作時間線（白話與原始指令可切換、子 agent 縮排、連續相同動作合併、最多 40 筆）、碰過的檔案（改過的附增刪行數，讀過的可展開），以及子 agent 列表（類型、模型、狀態、經過時間、token、估計金額）。桌面版／VS Code／手機用 Svg 畫圖像版，終端機用文字與色塊。可以縮小成一行摘要，用 `/agent-board` 開關；底部有白話／原始指令與「⇄ 回覆：精簡／詳細」切換鍵。工具呼叫只觀察、不改動 |
| `reply-detail` | 在 system prompt 注入回覆格式：預設精簡三段（現況／你要做的／需要你決定或提供），只對主對話生效。看板的切換鍵切到「詳細」後，之後每則回覆都是詳細版，直到切回精簡；只要單次詳細版時，直接輸入「詳細說明」就會把上一則改寫成詳細版 |

安裝：用 plugin 市集的話是 `/plugin install agent-board@chutora`、`/plugin install reply-detail@chutora`；用 install.sh 的話加 `--with-agent-board`、`--with-reply-detail`（VS Code 不能帶 `--plugin-dir`，腳本會把目錄加進 `settings.json` 的 `env.CLAUDE_CODE_PLUGIN_DIRS`）。裝完在 VS Code 執行 Developer: Reload Window。

agent-board 的設定（plugin 的 userConfig，預設都開）：`autoOpen` 子 agent 啟動時自動開面板、`persistent` 對話一開始就開且不自動收起、`detailButton` 看板底部的回覆模式切換鍵（名稱沿用舊版）。切換鍵切到詳細時，看板會在你送出的每則訊息附上「這一輪寫詳細版」的要求；reload 後回到精簡。

限制：mod 不能在 VS Code 輸入框的工具列（模型選單那一排）加按鈕，所以切換鍵放在看板裡。回覆訊息底下和輸入框上方的橫條也能放，但 VS Code 會替 mod 畫的這些區塊加上外框和「From the … plugin」標籤（mod 關不掉），所以不採用。另外，Claude Code 對不是使用者自己打開的面板有寬度門檻（沒手動開過要 144 欄），VS Code 聊天面板常常不夠寬，面板會停在看不見的「未放置」狀態；常駐模式會在畫面重連、寬度改變、回合開始與結束時檢查並補開。

### 看固定成本

想知道每一輪固定要付多少（系統提示、工具定義、MCP、skills、記憶檔），在對話裡輸入 `/context`，或在 terminal 跑 `claude -p "/context"`（不用開互動對話，在本機計算、不呼叫模型）。作者機器上新對話的固定成本約 29k token，其中約 18k 是 Claude Code 內建的系統提示與工具定義；標為 deferred 的工具用到才載入，不計入。固定內容每輪都會命中快取，通常不是大頭，先處理對話長度與輸出，再考慮拔掉不用的 MCP 或 plugin。

---

<a name="memory"></a>

## <img src="../assets/icons/brain.svg" width="26" height="26" alt=""> 記憶

```
<你的資料夾>/claude-memory/
├── MEMORY.md    ← 常駐索引,session 開始時由 hook 帶入,預算 40 行
├── handoff.md   ← 交接筆記,下個 session 自動帶入
├── topics/      ← agent 累積的知識
├── kb/          ← 你自己的筆記
└── web/         ← research 存的外部資料筆記(附來源與過期日)
```

沒有 `claude-memory/` 時，記憶退回 Claude Code 自己的 auto memory，一樣可用；`claude-memory/` 是進階選項，好處是可以進 git、跨環境共用。

`MEMORY.md` **只放觸發條件，知識本體放主題檔**。這讓成本跟「這次用得到多少」成正比，而不是「總共記得多少」：知識可以無限成長，每次啟動的固定成本不變。索引寫成條件，不是主題：

- 不好：`setup.md — 環境設定相關`（這是主題）
- 好：`setup.md — 要改路徑或指令跑不起來時先讀`（這是條件）

記憶放在哪裡：

- agent 優先使用已連接（工作）資料夾裡的 `claude-memory/`，找不到才退回自己的 agent 記憶目錄（`~/.claude/agent-memory/worker/`）。
- Claude Code（終端機）裡退回路徑可以跨對話存活。Cowork 的沙盒家目錄每個 session 重建，只有連接資料夾活得下來：每次開新對話都要重新連接。
- 如果你關過 `autoMemoryEnabled` 或設了 `CLAUDE_CODE_DISABLE_AUTO_MEMORY`，`memory` 欄位不會生效，連接資料夾就從選用變成必要。
- 資料夾直接用 Obsidian 開就是一個 vault，不需要任何整合，vault 本來就只是一堆 `.md`。請開新的專用 vault，不要指向你現有的個人筆記，因為 agent 有寫入權。
- 記憶要記「下次怎麼做」，不是「這次做了什麼」。流水帳不會讓下一次變快。

保持 `MEMORY.md` 薄很重要：超過上限會被截斷（hook 最多帶入 120 行，auto memory 200 行），而且常駐內容是每個 session 都付的固定成本。它會腐化，需要定期整理；超過 150 行就是警訊。

### 變更紀錄與記憶身分資料（實驗中）

**變更紀錄** `claude-memory/changes.jsonl`（沒有 claude-memory 時放 auto memory 目錄）：每行一筆 JSON，只追加、不改寫。欄位：`id`、`ts`、`action`（動作代號，例如 `guard_ask`）、`summary`（已遮罩、截短）、`restore_point`（復原點位置，例如備份檔或 git commit；沒有就是 `null`）、`notified`（是否已告知你）、`user_response`（`null`、`approved`、`rejected`、`undone`…）、`source`、`session`。之後的更新另外追加一行 `{"id": …, "update": {…}}`，讀取時合併。這一批只有危險守門會寫；讀寫模組是 `hooks/changes.py`（`python3 changes.py list` 看最近幾筆），給之後會改設定的功能記「改了什麼、怎麼復原、你怎麼回應」。

**記憶身分資料**：新寫入的記憶檔最上面可以帶一段 YAML（工具模組 `hooks/memmeta.py`）：

```yaml
---
id: mem-20261107-a1b2c3
created: 2026-11-07T10:00:00+0800
last_used: 2026-11-07T10:00:00+0800
confidence: 0.7        # 0～1：你親口說的 0.9 以上，推測的 0.5 左右
source: user           # user／observed／handoff／research／inferred／imported
bound_files:           # 這條記憶依據的檔案與內容指紋（sha256 前 12 字元）
  - path: src/app.py
    sha: 3f2a9c0d11ee
version: 1
supersedes: null       # 取代哪一條舊記憶的 id
status: active         # active／stale／superseded／archived
---
```

- `bound_files` 的指紋讓之後可以發現「這條記憶依據的檔案已經改了」（`memmeta.py check <檔案>`）。
- **既有記憶檔一律不改寫**；`memmeta.py new` 只建立新檔，檔案已存在就拒絕。舊檔開頭的其他欄位（例如 auto memory 的 `name`、`description`、`type`）讀寫時原樣保留。
- 這一批只提供格式與工具，還沒有功能會自動寫記憶。

### 知識庫與 harvester

餵知識庫有兩種方式：自己把 `.md` 放進 `kb/`（不用任何前處理，librarian 立刻找得到），或叫 `harvester` 去挖歷史對話（它會先列出可讀的 session 讓你選範圍）。先講清楚四個限制：

- 只看得到本機的 session；網頁版或手機上的對話不在範圍內。
- 成本不低，所以是偶爾跑一次的批次作業，不是常駐功能。
- 萃取一定會失真：產出值得抽查，尤其是頭幾次。
- 它會寫進 `kb/`，而那原本是你自己的東西。如果你在意這條界線，先叫它寫到 `kb/harvested/`。

第一次安裝後跑一次，把已經累積的東西撈起來當起點；之後 worker 收工時會即時寫記憶，就很少需要再跑。

---

<a name="tradeoffs"></a>

## <img src="../assets/icons/scale.svg" width="26" height="26" alt=""> 設計取捨

### 這是 RAG，只是不用向量

`librarian` 用關鍵詞搜尋與條件判斷做檢索。個人規模（數十到數百篇）這樣通常比向量好：不用多一套基礎設施、檢索失敗看得出原因、不會因為切塊破壞 Markdown 的結構。而且它會換同義詞、換語言、改搜檔名重試，固定的向量查詢做不到。

上千篇或大量 PDF、長逐字稿才值得考慮向量。屆時 `kb/` 的 markdown 直接當語料。

### 什麼時候加 Haiku 執行層

`skills/route-setup/templates/runner.md.example` 是預留的位置，**刻意不載入**。Haiku 層是唯一真正省錢、也唯一真正有風險的一層：它不會停下來問你，會照著它以為的意思安靜做完。所以每個 Haiku agent 都必須綁死在一件具體任務上。

三個條件同時成立才啟用：

- 這件事你已經做過三到五次，流程幾乎一樣。
- 成功的樣子明確到一眼能判斷。
- 做錯可承受且可回復（不刪東西、不送出去、不覆蓋無備份的檔案）。

任何一項不成立，就繼續留在 worker。檢索（librarian）是例外，因為它是唯讀的。

---

<a name="install"></a>

## <img src="../assets/icons/box.svg" width="26" height="26" alt=""> 其他安裝方式

不想用 marketplace 的話，repo 內附 `install.sh`，或直接 `claude --plugin-dir ./plugins/chutora`。

```
bash install.sh                    # 複製安裝(agent、skill、hook 放進 ~/.claude/,沒有命名空間前綴;重跑即更新)
bash install.sh --agents-only      # 只複製 agent(hook 與 skill 不會生效)
bash install.sh --link             # 用符號連結裝 agent、skill、hook(改 repo 立即生效)
bash install.sh --uninstall        # 移除(依安裝清單,不動你自己的檔案)
bash install.sh --with-explore     # 另外安裝 Haiku 版 Explore 到 ~/.claude/agents/
bash install.sh --with-statusline  # 另外在 ~/.claude/settings.json 加 context 狀態列
bash install.sh --with-agent-board   # 另外載入子 agent 看板 mod(寫入 settings.json 的 env.CLAUDE_CODE_PLUGIN_DIRS)
bash install.sh --with-reply-detail  # 另外載入回覆格式 mod(同上)
```

注意事項：

- 這種模式下名稱沒有命名空間：agent 是 `worker`，skill 是 `/handoff`（plugin 安裝則是 `chutora:worker`）。
- 裝了哪些東西記在 `~/.claude/.chutora-installed`。內容完全相同的既有檔案會併入清單；內容不同的（你自己的）不會覆蓋，並給警告。
- `--with-statusline` 可與預設的複製模式或 `--link` 併用，不能與 `--agents-only`、`--uninstall` 併用。它只動 `settings.json` 的 `statusLine` 這個 key：檔案不存在就建立，已有 `statusLine` 絕不覆蓋（只印出建議片段），其餘情況寫入前先備份成 `settings.json.bak-<timestamp>`。JSON 壞掉或沒有 python3 時什麼都不做。
- `--with-agent-board`、`--with-reply-detail` 的限制同 `--with-statusline`，兩者可以同時使用。它們只動 `env.CLAUDE_CODE_PLUGIN_DIRS`：已有的路徑保留，寫入前先備份；`--uninstall` 只移除自己加的路徑。
- install.sh 不會改你 `settings.json` 裡的 hooks，結尾會印出一段片段，由你自己併進 `"hooks"`。之後執行 `/route-setup` 取得完整功能。

更多說明見 [docs/部署安裝.md](部署安裝.md)與 [plugins/chutora/INSTALL.md](../plugins/chutora/INSTALL.md)（英文版：[INSTALL.en.md](../plugins/chutora/INSTALL.en.md)）。

---

<a name="layout"></a>

## <img src="../assets/icons/folder.svg" width="26" height="26" alt=""> 目錄

```
chutora/
├── .claude-plugin/marketplace.json   ← 市集目錄
├── plugins/chutora/            ← plugin 本體
│   ├── .claude-plugin/plugin.json
│   ├── agents/                       ← worker / worker-hard / bulk / librarian / harvester / security-review / security-test
│   ├── skills/                       ← handoff / research / usage-stats / route-setup / evidence-analysis / security-review / security-test / toolprune / harness-tune / chutora-hub
│   ├── hooks/                        ← SessionStart 帶入、context 長度提醒、loop guard、modes/（三種模式）、weekly.py（每週回顧）、trim.py（噪音輸出瘦身）、dedup.py（讀檔去重）、mcptrim.py（MCP 輸出瘦身）、ask.py（反問提醒）、guard.py（危險守門）、observe.py（觀察紀錄）、changes.py（變更紀錄）、memmeta.py（記憶身分資料）、projectid.py、redact.py
│   （範本在 skills/route-setup/templates/：MEMORY.md、知識庫說明、Explore、Haiku 層範本）
├── plugins/agent-board/              ← 子 agent 看板 mod（選裝）
├── plugins/reply-detail/             ← 回覆格式 mod（選裝）
├── bench/                            ← token benchmark：run.py、tasks.json、fixtures/
├── docs/
│   ├── spec.md                       ← 架構設計與實作附錄
│   ├── 部署安裝.md
│   └── 發佈到-GitHub.md
├── claude-memory/                    ← 記憶庫(不進版控)
└── install.sh                        ← 不用 marketplace 的安裝方式
```
