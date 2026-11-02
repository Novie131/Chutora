# Smart Agent Route

<p align="center"><b>繁體中文</b> · <a href="README.en.md"><b>English</b></a></p>

**讓 Claude Code 像一個小團隊一樣分工：Opus 當主管負責想，Sonnet 和 Haiku 負責動手；對話變長時先寫交接筆記，清空後照筆記接著做。**

> A Claude Code plugin for tiered model delegation — Opus plans, Sonnet executes, Haiku retrieves and digests bulk output — plus context-length reminders with handoff notes so the main conversation stays short, and persistent, source-cited memory that accumulates across conversations. English documentation: [README.en.md](README.en.md).

**目的**：用同樣的預算做更多事，而且長時間工作也不會因為對話越拉越長而變貴、變亂。

**為什麼用它**

- **貴的模型只用在刀口上**：Opus 只負責想與判斷，寫程式交給 Sonnet，讀 log、看截圖、查資料交給 Haiku。
- **長對話不再失控**：context 超過 10 萬 token 就提醒，先寫交接筆記；壓縮、`/clear` 或隔天開新對話，進度都會自動接回來。
- **裝完就能用**：兩行指令，不用改你的 CLAUDE.md。進階設定一次只問一項，改設定前先備份。
- **做完會驗證，岔路會停下來問**：子 agent 回報完成前必須驗證；遇到需要決策的地方，列出選項讓你選，不會自作主張。失敗有固定的升級順序，不會無限重試。
- **記憶跨對話累積**：記憶就是一般的 Markdown 檔，可以進 git、用 Obsidian 開；查外部資料時附上來源。
- **效果量得到**：`usage-stats` 可以量出主對話 context 長度、每個 agent 用了多少 token、依 API 牌價估算的金額，也能輸出一份有每日圖表的 HTML 報表。
- **看得到子 agent 在做什麼**（選裝）：`agent-board` 看板常駐在輸入框上方，即時列出每個子 agent 的類型、模型、狀態、經過時間、token 與估計金額。
- **回覆一眼看懂**（選裝）：`reply-detail` 讓回覆預設只講現況、你要做的、需要你決定的事；要細節時用看板的「⇄ 回覆：精簡／詳細」切換鍵，切到詳細後每則都寫詳細版。

---

## 這解決什麼問題

用 Claude Code 一陣子，常會遇到兩件事：

- **貴**：所有事都由主對話的 Opus 親自做，包括讀長 log、看一堆截圖、改幾十個檔案。這些工作大多用便宜的模型就夠了。
- **對話越聊越長**：每一則訊息、每一次讀檔的結果，之後每一輪都會重新送給模型一次。對話拖到後面，大部分花費都在重讀舊內容。實測一位重度使用者的 21 個 session，主對話每次呼叫的 context 中位數約 24 萬 token。

這個 plugin 的做法像一位主管帶團隊：主管（Opus）聽你說、想清楚、決定派給誰；動手的工作交給組員（Sonnet、Haiku）在各自的桌上做完，只把結論交回來，主管的桌面因此保持乾淨。桌面快滿時，主管先寫好交接筆記，清掉桌面後照筆記繼續做。

**適合**：已經在用 Claude Code、常做多步驟工作（改程式、讀 log、查資料），想省錢或不想讓長對話失控的人。只偶爾問一兩句話的話，分工的好處不明顯。

---

## 快速開始

在 Claude Code 裡輸入：

```
/plugin install smart-agent-route --marketplace Novie131/smart-agent-route
/reload-plugins
```

（Claude Code 2.1.275 以前：先 `/plugin marketplace add Novie131/smart-agent-route`，再 `/plugin install smart-agent-route@smart-agent-route`。）

裝完就能用。接著建議做兩件事：

1. **主對話設成 Opus**：`/model opus`。plugin 不會自動改。
2. **開啟完整功能**：執行 `/smart-agent-route:route-setup`，可以設定 context 狀態列、自動壓縮門檻、Haiku 版 Explore、`claude-memory/` 記憶庫。它一次只問一項，每項都說明做什麼、影響、怎麼還原，可以隨時略過；寫 `settings.json` 前會備份，已有的值不覆蓋。沒做的話，session 開始時會提醒你（最多 3 次）。

context 長度提醒需要 `python3`，沒有的話會安靜停用。不想用 marketplace，見[其他安裝方式](#其他安裝方式)。

---

## 裝完之後怎麼用

照平常講話就好，主對話會自己判斷要不要派工：

| 你說 | 誰處理 |
|---|---|
| 「幫我想清楚這該怎麼做」 | 主對話（Opus）自己想 |
| 「照剛才講的做」 | worker（Sonnet）動手，做完先驗證再回報 |
| 「看一下這 18 張截圖有沒有跑版」「這份 log 為什麼失敗」 | bulk（Haiku）讀完只回結論 |
| 「我之前有記過 X 嗎」 | librarian（Haiku）查記憶，附出處 |
| 「這個 API 新版怎麼設定」 | research skill 查外部資料，回答附來源，官方資料存進 `claude-memory/web/` |
| 「交接一下」 | handoff skill 寫 `handoff.md`，之後可以 `/clear` |

想強制指定某個 agent，用 `@agent-smart-agent-route:worker`。

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

## 運作方式

```
你 ──► 主對話(Opus)          ← 大門。理解、判斷、決定派給誰
          │
          ├──► worker(Sonnet)       ← 方向已定、動手做的事
          │      └► worker-hard      ← worker 失敗後的升級
          ├──► bulk(Haiku)          ← 大量讀取只要結論:圖片、長 log、網頁
          ├──► librarian(Haiku)     ← 查知識庫。唯讀
          ├──► harvester(Sonnet)    ← 挖歷史對話進知識庫。手動觸發
          ├──► security-review(Sonnet) ← 靜態安全審查你自己的碼。唯讀
          └──► security-test(Sonnet)   ← 授權動態測試你自己的 dev 環境

skill:handoff(交接筆記)、research(查外部資料並附來源)、usage-stats(量測 context 與子 agent 用量)、route-setup(一次性完整設定)、evidence-analysis(證據導向分析)
hook :session 開始帶入分工慣例與記憶;context 過長時提醒
```

| 元件 | 模型 | 做什麼 |
|---|---|---|
| worker | Sonnet，effort medium | 方向已定的實作：寫程式、修 bug、補測試。回報完成前必須先驗證 |
| worker-hard | Sonnet，effort high | 只在 worker 失敗後使用，派工時必須附上前次失敗報告 |
| bulk | Haiku | 大量讀取、只回結論：大量圖片、長 log、網頁、輸出很多的指令，以及機械式的批次修改 |
| librarian | Haiku，effort low | 查知識庫與記憶。只有 `Read`、`Glob`、`Grep`，什麼都改不了；回傳原文片段與來源，並說明搜過哪些詞、什麼沒找到 |
| harvester | Sonnet | 把歷史對話逐字稿挖進知識庫筆記。只在你明確要求時才跑，成本不低 |
| security-review | Sonnet，effort medium | 對你自己的程式碼做靜態安全審查（OWASP 類別、附證據與修補、嚴重度分級）。只讀不改，只用於你擁有或授權的碼 |
| security-test | Sonnet，effort medium | 對你自己、已授權且隔離的 dev 環境做動態安全測試，驗證漏洞是否可利用。開工先確認授權範圍，不碰 production、不外送資料 |
| Explore（選裝） | Haiku | 內建 Explore 在主對話是 Opus 時也跑 Opus。plugin 蓋不掉它（只有使用者或專案層級、名為 `Explore` 的 agent 能覆蓋），所以用 route-setup 或 `bash install.sh --with-explore` 把 Haiku 版裝進 `~/.claude/agents/` |

- **Skills**：`handoff` 寫 `handoff.md`；`research` 查外部資料並附來源；`usage-stats` 量測主對話 context 長度、各 agent 的派工次數、token 用量與估計金額（唯讀；加 `--html` 可輸出圖表報表）；`route-setup` 是一次性完整設定。
- **Hooks**：SessionStart 帶入分工慣例、記憶索引與交接筆記；UserPromptSubmit 在 context 過長時提醒。
- **新增能力**：`evidence-analysis`（證據導向分析：結論分 觀察／推論／未知 並附出處）；`security-review`／`security-test`（防禦性安全：靜態審查＋授權動態測試）。安全能力只用於你自己或明確授權的程式碼與環境，動態測試只在隔離環境、不碰 production、不外送資料。

主對話怎麼分工，不靠你的 CLAUDE.md：SessionStart hook 會在每個 session 開始時把分工表帶進去（內容見 `hooks/guide.md`）。設計理由與取捨見 [docs/spec.md](docs/spec.md)。

### 為什麼這樣省

**路由發生在 Opus 之後，不是之前。** 判斷意圖就得先讀懂訊息，而讀懂就等於規劃了，所以沒辦法在前面放一個便宜的路由器。Opus 永遠是入口，由它派工。

省下的錢來自四個地方，照影響大小排序：

1. **Context 隔離**（最大的一筆，而且是複利）。在主對話裡跑 30 次工具呼叫，那 30 份結果會被反覆計費到對話結束；派給子 agent 的話，主對話只收到一份摘要。派工要整包派，不要一件一件派，因為每次啟動子 agent 都要重付一次系統提示與記憶注入。
2. **模型分層。** 有用，但是線性的：省的比例大致等於價差。
3. **`effort` 等級。** worker 用 `medium`，失敗才升級到 worker-hard（`high`）；librarian 用 `low`。
4. **主對話別開太久。** 隔離只管得到工具呼叫，管不到對話本身變長，所以 plugin 另外盯著長度，超過門檻就提醒寫交接筆記（見[進階設定](#進階設定)）。話題告一段落時，換新對話或 `/clear` 仍然最省。

### 失敗怎麼辦

子 agent 收工時用固定的回報格式，主對話只看前兩行就能決定下一步：狀態行（完成、失敗、需要決策）與驗證行（通過、未驗證、失敗）。「完成」只能搭配「驗證通過」。遇到需要決策的岔路時，子 agent 會停下來回報有哪些選項與各自的影響，不會自己選一條路走完。

失敗升級依序：補背景後同一個 agent 重派 → bulk 失敗改 worker → worker 失敗改 worker-hard（附前次失敗報告）→ 仍失敗就停下來重新規劃或問你。不會無限升級。

---

## 進階設定

### context 提醒與自動壓縮

- UserPromptSubmit hook 在 context 超過 10 萬 token 時提醒一次，之後每多 4 萬再提醒。門檻可用環境變數 `CONTEXT_REMIND_TOKENS` 調整。
- 提醒時 Claude 用 handoff skill 把現況寫進 `handoff.md`（目前任務 / 已完成 / 下一步 / 未決問題）。
- 有設 `autoCompactWindow` 時，提醒只會告訴你約多少 k 會自動壓縮、壓縮後會帶回交接筆記；沒設才給可複製的指令：告一段落用 `/clear`、做到一半用 `/compact` 並指定重點、後半段是除錯雜訊就用 `/rewind` 局部摘要。
- 每次壓縮、`/clear`、新 session 開始時，SessionStart hook 自動帶入 `handoff.md`：專案有 `claude-memory/` 就用它，否則用 transcript 旁 auto memory 目錄的 `handoff.md`（Claude Code 只會自動帶入 auto memory 的 MEMORY.md 索引，不會帶 handoff.md）。

建議在 `~/.claude/settings.json` 把自動壓縮當保險（plugin 不能代設，`/smart-agent-route:route-setup` 會幫你安全地寫入）：

```
"autoCompactWindow": 153000
```

扣掉約 33k 的 buffer 後，約在 12 萬自動壓縮，在 10 萬提醒之後留 2 萬緩衝寫 handoff。33k 是作者機器的實測值（不確定是否固定）；寫入後請用 `/context` 確認 Autocompact buffer 約 33k、壓縮點約 120k（有 `modelSettings` 逐模型覆蓋時要一併看）。

### 狀態列（選用）

顯示 `模型 │ ctx 95k │ 提醒 100k │ 壓縮 120k`，壓縮點讀自 `autoCompactWindow`（沒設就不顯示）。plugin 不能設定主狀態列：plugin 安裝的使用者請用 `/smart-agent-route:route-setup`，它會把檔案放到固定位置；install.sh 安裝的用 `bash install.sh --with-statusline`，或手動貼進 settings.json：

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/smart-agent-route/statusline.py" }
```

### 子 agent 看板與回覆模式切換鍵（選用）

兩個選裝的 mod（Claude Code 的介面擴充，需要 2.1.299 以上；作者在 VS Code 擴充 2.1.301 實測）：

| mod | 做什麼 |
|---|---|
| `agent-board` | 常駐面板列出每個子 agent 的類型、模型、狀態、經過時間、token 與估計金額（API 牌價），上方顯示合計。可以縮小成一行摘要，用 `/agent-board` 開關；底部有「⇄ 回覆：精簡／詳細」切換鍵 |
| `reply-detail` | 在 system prompt 注入回覆格式：預設精簡三段（現況／你要做的／需要你決定或提供），只對主對話生效。看板的切換鍵切到「詳細」後，之後每則回覆都是詳細版，直到切回精簡；只要單次詳細版時，直接輸入「詳細說明」就會把上一則改寫成詳細版 |

安裝：用 plugin 市集的話是 `/plugin install agent-board@smart-agent-route`、`/plugin install reply-detail@smart-agent-route`；用 install.sh 的話加 `--with-agent-board`、`--with-reply-detail`（VS Code 不能帶 `--plugin-dir`，腳本會把目錄加進 `settings.json` 的 `env.CLAUDE_CODE_PLUGIN_DIRS`）。裝完在 VS Code 執行 Developer: Reload Window。

agent-board 的設定（plugin 的 userConfig，預設都開）：`autoOpen` 子 agent 啟動時自動開面板、`persistent` 對話一開始就開且不自動收起、`detailButton` 看板底部的回覆模式切換鍵（名稱沿用舊版）。切換鍵切到詳細時，看板會在你送出的每則訊息附上「這一輪寫詳細版」的要求；reload 後回到精簡。

限制：mod 不能在 VS Code 輸入框的工具列（模型選單那一排）加按鈕，所以切換鍵放在看板裡。回覆訊息底下和輸入框上方的橫條也能放，但 VS Code 會替 mod 畫的這些區塊加上外框和「From the … plugin」標籤（mod 關不掉），所以不採用。另外，Claude Code 對不是使用者自己打開的面板有寬度門檻（沒手動開過要 144 欄），VS Code 聊天面板常常不夠寬，面板會停在看不見的「未放置」狀態；常駐模式會在畫面重連、寬度改變、回合開始與結束時檢查並補開。

### 看固定成本

想知道每一輪固定要付多少（系統提示、工具定義、MCP、skills、記憶檔），在對話裡輸入 `/context`，或在 terminal 跑 `claude -p "/context"`（不用開互動對話，在本機計算、不呼叫模型）。作者機器上新對話的固定成本約 29k token，其中約 18k 是 Claude Code 內建的系統提示與工具定義；標為 deferred 的工具用到才載入，不計入。固定內容每輪都會命中快取，通常不是大頭，先處理對話長度與輸出，再考慮拔掉不用的 MCP 或 plugin。

---

## 記憶

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

### 知識庫與 harvester

餵知識庫有兩種方式：自己把 `.md` 放進 `kb/`（不用任何前處理，librarian 立刻找得到），或叫 `harvester` 去挖歷史對話（它會先列出可讀的 session 讓你選範圍）。先講清楚四個限制：

- 只看得到本機的 session；網頁版或手機上的對話不在範圍內。
- 成本不低，所以是偶爾跑一次的批次作業，不是常駐功能。
- 萃取一定會失真：產出值得抽查，尤其是頭幾次。
- 它會寫進 `kb/`，而那原本是你自己的東西。如果你在意這條界線，先叫它寫到 `kb/harvested/`。

第一次安裝後跑一次，把已經累積的東西撈起來當起點；之後 worker 收工時會即時寫記憶，就很少需要再跑。

---

## 設計取捨

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

## 其他安裝方式

不想用 marketplace 的話，repo 內附 `install.sh`，或直接 `claude --plugin-dir ./plugins/smart-agent-route`。

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

- 這種模式下名稱沒有命名空間：agent 是 `worker`，skill 是 `/handoff`（plugin 安裝則是 `smart-agent-route:worker`）。
- 裝了哪些東西記在 `~/.claude/.smart-agent-route-installed`。內容完全相同的既有檔案會併入清單；內容不同的（你自己的）不會覆蓋，並給警告。
- `--with-statusline` 可與預設的複製模式或 `--link` 併用，不能與 `--agents-only`、`--uninstall` 併用。它只動 `settings.json` 的 `statusLine` 這個 key：檔案不存在就建立，已有 `statusLine` 絕不覆蓋（只印出建議片段），其餘情況寫入前先備份成 `settings.json.bak-<timestamp>`。JSON 壞掉或沒有 python3 時什麼都不做。
- `--with-agent-board`、`--with-reply-detail` 的限制同 `--with-statusline`，兩者可以同時使用。它們只動 `env.CLAUDE_CODE_PLUGIN_DIRS`：已有的路徑保留，寫入前先備份；`--uninstall` 只移除自己加的路徑。
- install.sh 不會改你 `settings.json` 裡的 hooks，結尾會印出一段片段，由你自己併進 `"hooks"`。之後執行 `/route-setup` 取得完整功能。

更多說明見 [docs/部署安裝.md](docs/部署安裝.md)與 [plugins/smart-agent-route/INSTALL.md](plugins/smart-agent-route/INSTALL.md)（英文版：[INSTALL.en.md](plugins/smart-agent-route/INSTALL.en.md)）。

---

## 目錄

```
smart-agent-route/
├── .claude-plugin/marketplace.json   ← 市集目錄
├── plugins/smart-agent-route/            ← plugin 本體
│   ├── .claude-plugin/plugin.json
│   ├── agents/                       ← worker / worker-hard / bulk / librarian / harvester / security-review / security-test
│   ├── skills/                       ← handoff / research / usage-stats / route-setup
│   ├── hooks/                        ← SessionStart 帶入、context 長度提醒
│   （範本在 skills/route-setup/templates/：MEMORY.md、知識庫說明、Explore、Haiku 層範本）
├── plugins/agent-board/              ← 子 agent 看板 mod（選裝）
├── plugins/reply-detail/             ← 回覆格式 mod（選裝）
├── docs/
│   ├── spec.md                       ← 架構設計與實作附錄
│   ├── 部署安裝.md
│   └── 發佈到-GitHub.md
├── claude-memory/                    ← 記憶庫(不進版控)
└── install.sh                        ← 不用 marketplace 的安裝方式
```

---

## 狀態

**v0.8.0 — 早期版本。** 0.7.0 以前叫 tiered-agents，升級請先移除舊版（見 [docs/部署安裝.md](docs/部署安裝.md#從-tiered-agents070-以前升級)）。 context 提醒 hook、handoff、bulk、Explore 覆蓋版移植自作者的個人設定：hook 已在真實對話中觸發、Explore 與 bulk 已確認跑在 Haiku，但都還在驗證期。worker-hard 升級鏈、research skill 與 plugin 形式的 hook 尚未實際使用。agent-board 與 reply-detail 已在 VS Code 擴充 2.1.301 實測過看板；常駐模式、看板裡的按鈕與回覆格式注入還在驗證。

已知會需要調整的地方：

- 委派靠 `description` 匹配，不是保證。要確定就 `@agent-smart-agent-route:worker`
- hook 在 Cowork 的行為未驗證
- `MEMORY.md` 會腐化，需要你定期整理（超過 150 行即是訊號）
- Haiku 執行層預設留空，見 `plugins/smart-agent-route/skills/route-setup/templates/runner.md.example` 的啟用條件
- `harvester` 只讀得到本機 session
- mod 的 API 標示為搶先體驗（early access），Claude Code 改版時可能要跟著調整

歡迎開 issue。

---

## 授權

MIT
