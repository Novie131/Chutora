# chutora 架構 spec

> 英文文件（README.en.md、plugins/chutora/INSTALL.en.md）是繁中版的翻譯；改 README.md 或 INSTALL.md 時要同步更新這兩份英文版。

## 目標

主對話用 Opus 思考與判斷,執行工作派給較便宜的模型;主對話保持短,要留下的寫進記憶,對話可以隨時清空;知識跨對話累積。

## 架構

```
你 ──► 主對話(Opus)          ← 大門。理解、判斷、決定派給誰
          │
          ├──► worker(Sonnet)     ← 方向已定、動手做的事
          │      └► worker-hard    ← worker 失敗後的升級
          ├──► bulk(Haiku)        ← 大量讀取只要結論
          ├──► librarian(Haiku)   ← 查知識庫。唯讀
          ├──► Explore(Haiku)     ← 搜程式碼。使用者層級,需另裝
          └──► harvester(Sonnet)  ← 挖歷史對話進知識庫。手動觸發

hook :SessionStart 帶入分工慣例、記憶索引、交接筆記;UserPromptSubmit 在 context 過長時提醒
skill:handoff 寫交接筆記;research 查外部資料、附來源、存筆記;usage-stats 量測 context 與子 agent 用量
```

**路由發生在 Opus 之後,不是之前。** 判斷意圖就得先讀懂訊息,而讀懂即規劃。所以 Opus 永遠是入口,由它派工。

成本上仍划算:規劃是一則訊息,執行迴圈常是數十次工具呼叫,省後者即省大部分。

## 元件

| 元件 | 模型 | 工具 | 職責 |
|---|---|---|---|
| 主對話 | Opus | 全部 | 規劃、判斷、派工 |
| `worker` | Sonnet medium | 讀寫檔案、Bash、網頁 | 執行明確任務,必須驗證,收工寫記憶 |
| `worker-hard` | Sonnet high | 同 worker | worker 失敗後接手,先分析前次失敗原因 |
| `bulk` | Haiku medium | 讀寫檔案、Bash、網頁 | 看圖、讀長 log、抓網頁、規則明確的批次修改;只回結論 |
| `librarian` | Haiku low | **唯讀**(Read/Glob/Grep) | 在知識庫檢索,回傳原文片段 |
| `harvester` | Sonnet | 繼承 | 讀過往 session,萃取成筆記 |
| `Explore`(範本) | Haiku | 唯讀 | 搜程式碼。須放 `~/.claude/agents/` 才能覆蓋內建版 |
| `handoff` skill | — | — | 寫 `handoff.md`(四段、只記現況、≤60 行) |
| `research` skill | — | — | 查外部資料、附來源、存 `web/` 筆記 |
| `usage-stats` skill | — | — | 統計主對話 context 與子 agent 用量(含各類子 agent 跑在哪個模型) |

worker 從 0.6 的 `low` 改為 `medium`:執行層做錯由主對話收拾的成本,高於推理省下的 token;升級鏈只在失敗時才付 `high`。

## 記憶

```
<你的資料夾>/claude-memory/
├── MEMORY.md    ← 常駐索引,session 開始時由 hook 帶入主對話,預算 40 行
├── handoff.md   ← 交接筆記,只記現況;下個 session 自動帶入
├── topics/      ← agent 累積的知識(可隨時砍掉重來)
├── kb/          ← 你自己的筆記(agent 不該改)
└── web/         ← 外部資料筆記,附來源與 fetched 日期,依 volatility 過期
```

**MEMORY.md 只放觸發條件,知識本體放主題檔。**

這讓成本跟「這次用得到多少」成正比,而非「總共記得多少」——知識可無限成長,固定成本不變。hook 只帶入前 120 行(略過 HTML 註解與空行),膨脹即截斷。

**帶入靠 SessionStart hook,不靠 CLAUDE.md。** plugin 改不了使用者的 CLAUDE.md,plugin 根目錄的 CLAUDE.md 也不會載入;SessionStart 的純文字 stdout 會成為 context(官方 hooks 文件)。hook 讀的是 `$CLAUDE_PROJECT_DIR/claude-memory/`。

索引寫成條件,不是主題:

- ✗ `setup.md — 環境設定相關`
- ✓ `setup.md — 要改路徑或指令跑不起來時先讀`

記憶內容記「下次怎麼做」,不是「這次做了什麼」。流水帳不會讓下一次變快。

## 檢索

這是 RAG,只是檢索靠關鍵詞搜尋與條件判斷,不是向量相似度。

個人規模(數十到數百篇)不建議上向量:要多一套基礎設施、檢索失敗難除錯、切塊破壞 Markdown 結構、embedding 本身也花錢。且 agentic search 會換同義詞、換語言、改搜檔名重試,固定向量查詢做不到。

上千篇或大量 PDF、長逐字稿才值得考慮。屆時 `kb/` 的 markdown 直接當語料,不用重來。

## 省 token 的四個槓桿

0. **對話長度**(實測最大)。21 個 session、約 2,000 次呼叫的實測:主對話每次呼叫的 context 中位數約 24 萬 token,快取讀取約 4.9 億 vs 輸出 240 萬——錢花在每輪重讀舊對話。→ hook 在 10 萬 token 時提醒、之後每 4 萬再提醒;handoff skill 寫下現況;建議另設 `autoCompactWindow: 153000`(約 12 萬自動壓縮),壓縮後自動帶回 handoff(見 0.8 全自動 context 管理)。
1. **Context 隔離**(複利)。對話中每則訊息在後續每一輪都會重送。30 次工具呼叫留在主對話 = 被反覆計費到對話結束;派給 subagent 則主對話只收摘要。→ **整包派工,不要一件一件派**,每次啟動 subagent 都要重付系統提示與記憶注入。
2. **模型分層**。線性效果,省的比例約等於價差比例。
3. **`effort`**。librarian `low`、worker `medium`、worker-hard `high`。依失敗代價配置,不是一律壓低。

## 關鍵設計決策

**沒有 planner subagent** — 主對話本身就是 planner,多一層只是多一次轉手。

**失敗升級有上限** — 補背景重派 → bulk 改 worker → worker 改 worker-hard(附失敗報告)→ 停下重新規劃或問使用者。不設上限的升級會在規劃錯誤時一路燒錢。

**Explore 不放進 plugin** — 官方文件:只有使用者或專案層級名為 `Explore` 的 agent 能覆蓋內建版;plugin agent 優先順序最低。主對話是 Opus 時內建 Explore 也跑 Opus,所以以範本 + `install.sh --with-explore` 提供。

**context 提醒用 python、安靜失敗** — 要解析 transcript 的 usage,純 sh 不可靠。`run-python.sh` 找不到可用的 python3 就跳過(macOS 未裝 Command Line Tools 時 `/usr/bin/python3` 會跳安裝視窗,先用 `xcode-select -p` 判斷);腳本任何錯誤都不擋使用者訊息。

**Haiku 層預設只開檢索** — Haiku 的風險是「安靜地做錯」。檢索是例外:唯讀改不壞東西、成功標準明確、省得最多。其他 Haiku 用途需綁定具體任務後才啟用(見 plugin 內 `skills/route-setup/templates/runner.md.example`)。

**記憶優先放連接資料夾** — `memory:` 欄位路徑寫死,而 Cowork 沙盒家目錄每 session 重建。放自己指定的資料夾才能跨對話、跨環境存活,順便就是 Obsidian vault。

**升級成 skill 是手動的** — 自動偵測「這件事重複了」易誤判。`MEMORY.md` 的重複次數紀錄累積到 3–5 次,由你決定是否固化。

---

# 實作附錄

> 依此附錄可重建 worker、librarian、harvester 與記憶範本。0.7 新增的元件(worker-hard、bulk、skills、hooks)規格見「0.7 新增元件」一節,細節以檔案為準。

## 目錄結構

```
chutora/
├── .claude-plugin/plugin.json    ← 只有 manifest 放這裡
├── agents/
│   ├── worker.md
│   ├── worker-hard.md
│   ├── bulk.md
│   ├── librarian.md
│   └── harvester.md
├── skills/
│   ├── handoff/SKILL.md
│   ├── research/SKILL.md
│   ├── usage-stats/SKILL.md
│   └── route-setup/
│       ├── SKILL.md
│       ├── apply_settings.py   ← 唯一會寫 settings.json 的程式（只碰 statusLine、autoCompactWindow）
│       └── route-setup/templates/ ← MEMORY.md、KNOWLEDGE-BASE.md、Explore.md、runner.md.example
├── hooks/
│   ├── hooks.json          ← 最外層必須包一層 "hooks" 鍵,否則載入失敗
│   ├── session-start.sh    ← 純 sh + awk
│   ├── guide.md            ← session-start.sh 輸出的分工慣例
│   ├── run-python.sh       ← 找不到可用 python3 就安靜跳過
│   ├── compact.py          ← 壓縮點（autoCompactWindow − buffer），statusline 與 context-check 共用
│   ├── statusline.py       ← 狀態列指令，需使用者在 settings 的 statusLine 指定
│   └── context-check.py
```

`skills/route-setup/templates/Explore.md` 只有放進使用者層級 `~/.claude/agents/` 才生效，不會被 plugin 載入。

`agents/`、`skills/`、`hooks/` 必須在 plugin 根目錄,**不可放進 `.claude-plugin/`**。

plugin 內的元件都帶命名空間:agent 是 `chutora:worker`,skill 是 `/chutora:handoff`。

`plugin.json`:

```json
{
  "name": "chutora",
  "description": "分層委派架構:Opus 規劃、Sonnet 執行、Haiku 檢索與大量讀取,搭配 context 長度提醒與交接筆記…",
  "version": "0.8.0"
}
```

打包成 `.plugin` = 對 plugin 根目錄內容做 zip(不含最外層目錄)。

## Agent frontmatter

```yaml
# worker.md
name: worker
description: 執行已經想清楚的工作。當任務的「做什麼」已經確定、剩下的是動手完成時使用。
             不要用它來決定方向、評估取捨、或回答開放式問題;那些留在主對話。
tools: Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch
model: sonnet
memory: user
effort: medium
maxTurns: 30
color: blue
```

```yaml
# librarian.md
name: librarian
description: 在知識庫與記憶中查找資料。需要知道「之前記過什麼」「筆記裡有沒有提過 X」時使用。
             它只讀不寫,回傳原文片段與出處。查東西優先派給它,不要自己在主對話翻檔案。
tools: Read, Glob, Grep          # 唯讀。不可加入 Write / Edit / Bash
model: haiku
effort: low
color: green
```

```yaml
# harvester.md
name: harvester
description: 把過去的對話紀錄挖成知識庫筆記。只在使用者明確要求時使用。
             這是耗費較大的批次作業,不要主動或順帶執行。
model: sonnet
color: purple
# 刻意不列 tools —— 需要繼承讀取 session 的 MCP 工具,而那些工具依環境而定。
# 明確列出不存在的工具會導致 agent 完全無法啟動。
```

`description` 是委派的唯一依據,寫法直接決定派工準確率。要寫明「什麼時候用」與「什麼時候不要用」。

## worker 的核心指令

**定位** — 方向已定才派給它。若做到一半出現需要重新決策的岔路,**停下來回報**,不要自己選一條路走完。誤把「需要判斷的事」當「執行的事」做掉,是本架構最主要的失敗模式。

**記憶位置(順序不可顛倒)**

1. 已連接資料夾裡的 `claude-memory/` — 優先
2. 找不到才退回自己的 agent 記憶目錄

原因:某些環境(如 Cowork)的 agent 記憶目錄位於每次重建的沙盒中。兩者皆無且使用者已連資料夾時,主動建立並告知;完全沒連資料夾則照常工作,但回報時提醒記憶無法保存。

**開工前** — 先讀 `MEMORY.md`,依觸發索引決定要不要載入主題檔。

**收工後** — 問「下一次做類似的事,我會希望當時的自己留下什麼?」

值得寫:環境與結構的事實、踩過的坑與正確做法、使用者偏好與慣例、非顯然的因果關係。
不值得寫:這次做了什麼的流水帳。**寫的是「下次怎麼做」,不是「這次做了什麼」。**

**常駐 vs 下放的判準** — 只有**同時**滿足「幾乎每次都用得到」與「一兩行講得完」才進 `MEMORY.md` 本體。注意是「頻繁」不是「重要」。

**寫入時機** — 收工時一次寫完,不要邊做邊改。分散寫入會反覆變動 context 前段,拿不到快取效益。

**重複訊號** — 發現這次做的事與記憶中某件事幾乎相同且判斷成分低,回報時明講「適合固化成 skill」。指認但不決定。

## librarian 的核心指令

**存在理由** — 呼叫者不想把二十個檔案讀進 context。價值在**壓縮比**:讀得廣,回得精。

**搜尋範圍**(依序):`claude-memory/` 的 `MEMORY.md` → `topics/` → `kb/` → 擴大到連接資料夾其他位置。

**搜尋策略** — 第一個關鍵詞沒中不代表資料不存在。依序試:原詞 → 同義詞與上位詞 → **中英文都試一遍**(技術筆記常中英夾雜,只搜一種會漏一半)→ 檔名(Glob)與內容(Grep)兩邊都搜。

先 Grep 定位,再 Read 真正相關的幾個。**不要把搜到的檔案全部讀完**,那會失去存在意義。

**回報格式**

```
## 找到的內容
### <檔案路徑>
> <原文片段>
（一句話說明為何相關）

## 沒找到的部分
<明確列出問到但查不到的東西>

## 我搜過的關鍵詞
<列出來>
```

**回傳原文,不要改寫。** 擅自濃縮會弄丟細節。

最後兩區不可省略:「沒找到」讓呼叫者知道這件事沒記錄過;「搜過的詞」讓對方看出是否找錯方向。

**界線** — 不下判斷、不建議、不延伸推論。內容矛盾時兩邊都報並指出矛盾。過期內容照報但標註。

## harvester 的核心指令

**在獨立 context 執行** — 逐字稿很長,存在意義就是讓原始內容留在它這裡。**絕不把逐字稿大段複製進回報。**

**流程** — 列出可讀 session → **先回報清單、確認範圍再讀**(逐字稿成本不低)→ 逐一讀取、邊讀邊萃取(不要全讀完才整理,context 會先爆)→ 寫進 `kb/` → 更新 `MEMORY.md` 觸發索引。

**值得留** — 做過的決定**及當初理由**(理由比結論更難重建)、查證過的事實與來源、使用者偏好、**試過但行不通的方法及原因**、領域知識與術語。

**不要留** — 對話來回過程、一次性且不會再現的問答、已過期資訊、**不確定是否正確的東西**(寧可漏掉不要污染)。

**按主題歸檔,不按時間** — 最容易做錯的地方。一個 session 一個檔只是把逐字稿換地方放。三次對話談同一件事要合併成一個主題檔。已存在的主題檔要合併進去,不要另開。

**誠實標註** — 不確定處明講、矛盾兩邊都寫、每則註明來源 session。

**回報** — 挖了哪些、產出哪些檔案(列路徑)、哪些判斷不值得留及原因(讓使用者有機會推翻)。不重述筆記內容。

## MEMORY.md 範本結構

六個區塊,依序:

| 區塊 | 內容 | 預算 |
|---|---|---|
| 說明 | 這是觸發器不是知識庫;常駐預算 40 行 | — |
| 常駐事實 | 每次都用得到的短事實 | 10 行 |
| 觸發索引 | 表格:`檔案` / `什麼時候讀` | 主體 |
| 使用者偏好 | 慣例與判斷傾向 | 少量 |
| 已知的坑 | 一行一個:什麼會失敗 + 正確做法 | 少量 |
| 重複次數紀錄 | 表格:`事情` / `次數` / `備註` | 少量 |

觸發索引的「什麼時候讀」要寫成**條件**而非主題。代價不對稱:沒被讀到的索引幾乎不花錢,「該讀而沒讀」則是整趟重新摸索 —— 所以觸發條件寧可寫寬。

## 知識庫結構

```
claude-memory/
├── MEMORY.md   ← 常駐索引
├── topics/     ← agent 寫的。會過期、可能有誤,隨時可整個刪掉重來
└── kb/         ← 你寫的。agent 不該改
```

分開的理由:寫入者不同,信任程度不同。檢索結果矛盾時能一眼判斷該信哪邊,整理 `topics/` 時也能放心砍。

`kb/` 放置習慣:檔名寫人話(librarian 會搜檔名)、每檔開頭兩三行「這篇在講什麼」、一檔一主題(三千行萬用筆記會塞爆呼叫者 context)、中英術語都寫進標題或開頭。

## runner.md.example(Haiku 層範本,預設停用)

刻意用 `.example` 副檔名使其不被載入。內容為填空範本 + 啟用條件:

1. 這件事已做過 3–5 次,流程幾乎一樣
2. 成功的樣子明確到一眼可判斷
3. 做錯可承受且可回復(不刪東西、不送出、不覆蓋無備份檔案)

任一不成立就留在 worker。**一個任務一個檔案,不要寫通用 runner**,名字要具體(`weekly-report` 而非 `runner`)。工具權限從最少開始加。範本內須含:前置條件檢查、明確步驟、可檢查的完成標準、以及「遇到預期外狀況就停下回報,不要推測意圖或盡量做完」。

---

## 0.7 新增元件

**worker-hard**(Sonnet、`effort: high`、`maxTurns: 40`)— 只在 worker 失敗後派,委派時附前次失敗報告。先分析失敗原因(方法錯/資訊不足/規劃有問題),不重複已失敗的方法;判斷是規劃問題就停下回報。收工把「前次為什麼失敗」寫進記憶的已知的坑。

**worker 的新增指令** — 完成後必須驗證;同一問題 3 次失敗即停;回報格式:做了什麼 / 驗證方式與結果 / 未解決與已嘗試的方法。

**bulk**(Haiku、`effort: medium`、`maxTurns: 20`、`omitClaudeMd: true`)— 嚴格照委派執行、不擴大範圍、不寫記憶;大檔先 grep/head/tail;只回結論並附證據(網址、路徑與行號、關鍵原文),推測要標明。`omitClaudeMd` 需 Claude Code 2.1.271 以上。

**handoff skill** — 位置依序:`claude-memory/handoff.md` → auto memory 目錄(並在其 `MEMORY.md` 留指向)→ 都沒有就告知使用者。四段固定格式:目前任務 / 已完成與已修改的檔案 / 下一步 / 未決問題與使用者做過的決定。只記現況、改寫不追加、≤60 行。

**research skill** — 先查 `web/INDEX.md`;官方來源優先;文件站先試 `llms.txt`;抓網頁派給 bulk 只回「結論 + 網址 + 章節 + 短引文」;結尾附參考來源。存檔分級:官方 + stable/product 直接存並告知;非官方或矛盾先問;live 資訊不存。過期:stable 180 天、product 30 天,過期則更新原筆記。

**SessionStart hook**(matcher `startup|clear|compact`)— 輸出 `guide.md`,再附 `claude-memory/MEMORY.md`(≤120 行)與 `handoff.md`(≤80 行),兩者都略過 HTML 註解與空行。`resume` 不觸發,因為恢復的對話已含先前帶入的內容。

**UserPromptSubmit hook** — 從 `transcript_path` 讀主對話(排除 sidechain)最後一次呼叫的 input + cache 讀寫 token;以 10 萬為門檻(預設值集中在 `compact.py` 的 `DEFAULT_REMIND`)、每 4 萬一格,「上次在哪一格」記在 `${CLAUDE_PLUGIN_DATA}/.context-check-state.json`(只比最後兩次呼叫會漏掉回合中途跨門檻的情況)。跨進新的一格才以 `additionalContext` 提醒一次,文字用陳述語氣。

## 0.8 回報選擇題

借用決策模型(如 Jev)的概念:**判斷做成固定選項,下一步照規則走,只有拿不準才交給模型。** 不接外部服務——分派本來就在 Opus 的同一輪回覆裡完成,沒有額外呼叫可省。

worker、worker-hard、bulk 的回報前兩行固定:

```
狀態:完成 | 失敗 | 需要決策
驗證:通過 | 未驗證 | 失敗
```

`完成` 只能搭配 `驗證:通過`;整份回報 30 行內。主對話(`guide.md`)照這兩行處理:完成+通過 → 抽查後採用;完成但未通過、或格式不合 → 當失敗;失敗 → 升級鏈;需要決策 → 不升級,主對話判斷或問使用者。librarian(回原文片段)與 harvester(與使用者互動)不套用。

**未做:用 hook 強制格式。** 文件確認可行(`SubagentStop` 有 `last_assistant_message`、可 block,`stop_hook_active` 防迴圈),但 auto mode 下子 agent 改用 `SubagentHandback` 交報告,`last_assistant_message` 不是報告本身,要另外用 `PreToolUse`(matcher `SubagentHandback`)檢查 `tool_input.message`;且 hook 腳本壞掉時 exit 2 會讓子 agent 一直跑。等用量數據顯示子 agent 常不照格式再做。

## 0.8 context 可見性

- `compact.py` 的 `compact_point()`:讀 `~/.claude/settings.json` 的 `autoCompactWindow`,減 buffer(預設 33000,作者機器實測 183000 時 `/context` 顯示 33k(是否固定值未知);建議值 153000 約 120k 壓縮,寫入後請用 `/context` 確認;環境變數 `CONTEXT_AUTOCOMPACT_BUFFER` 可覆寫)。沒設定、讀不到、JSON 壞掉回 None。
- `statusline.py`:`模型 │ ctx Nk │ 提醒 100k │ 壓縮 120k`。用 `context_window.total_input_tokens`(缺時加總 `current_usage`),不用 `used_percentage`(以完整視窗算,1M 模型 10 萬只顯示 10%)。plugin 不能設主狀態列;`install.sh --with-statusline` 只在使用者沒有 `statusLine` 時寫入(先備份),絕不碰其他鍵,也不寫 `autoCompactWindow`。
- context-check 的提醒文字在壓縮點已知時帶入「約 Nk 會自動壓縮」,import 失敗退回原句。
- guide.md 加兩條:持續萃取 handoff、實作派 worker 不派 general-purpose(實測曾有 408 次實作跑在 Opus)。

## 0.8 全自動 context 管理

目標:使用者不需要手動 `/clear`。流程:

1. context 到 10 萬(`DEFAULT_REMIND`,可用 `CONTEXT_REMIND_TOKENS` 覆寫):UserPromptSubmit hook 提醒;有設 `autoCompactWindow` 時,Claude 先依 handoff skill 更新 `handoff.md`,再用一句話告知「約 N k 會自動壓縮、壓縮後自動帶回交接筆記」,不再給 /compact、/rewind 指令選單;沒設才維持三選一可複製指令。
2. 約 12 萬(`autoCompactWindow` 153000 扣 buffer 約 33k;buffer 是作者機器實測、未確認固定,寫入後用 `/context` 確認):Claude Code 自動壓縮。10 萬提醒到 12 萬壓縮之間留 2 萬緩衝寫 handoff。
3. 壓縮後 SessionStart(matcher `startup|clear|compact`)hook 自動帶回 handoff 全文:專案有 `claude-memory/` 就用它;沒有時從 stdin JSON 的 `transcript_path` 取上層目錄的 `memory/handoff.md`(去掉 HTML 註解與空行,上限 80 行,標題寫明路徑)。仍刻意不帶 auto memory 的 `MEMORY.md`(Claude Code 本來就會帶,重複只會多付費)。

為何 auto memory 使用者以前會漏讀 handoff:Claude Code 只自動帶入 auto memory 的 `MEMORY.md` 索引,索引裡指向 handoff.md 的那一行得靠模型自己想到去讀,壓縮或 /clear 後常常沒讀;只有 `claude-memory/` 的使用者有 hook 帶入全文。

取捨:每次壓縮多一次摘要輸出、會停頓一下;換來不用手動,且 context 上限壓在約 12 萬(原本建議值 183000 約 15 萬壓縮)。換主題時仍建議開新對話或 `/clear`:新對話不帶舊歷史,比壓縮後的摘要更便宜。

## 0.8 安裝後零手動

目標：裝完即可用；完整功能由一個互動 skill 帶使用者做，而不是要求讀文件手動改設定。

- **記憶退回 auto memory。** 沒有 `claude-memory/` 時：librarian 在 `claude-memory/` 之後搜 auto memory 目錄（`~/.claude/projects/<專案路徑把 / 換成 ->/memory/`）；harvester 寫入退回該目錄（筆記放 `kb/`，索引行寫進它的 `MEMORY.md`，保持精簡）；research 存到其 `web/`，`MEMORY.md` 只加一行指向 `web/INDEX.md`（取代原本的「不存檔」）。session-start.sh 沒有 `claude-memory/` 時**不**帶入 auto memory 的 `MEMORY.md`，因為 Claude Code 本來就會自己帶。
- **`route-setup` skill**（`disable-model-invocation: true`，只能由使用者呼叫）。逐項說明「做什麼 → 影響 → 怎麼還原」，一次問一項、可略過：記憶、Haiku Explore、`autoCompactWindow` 153000、狀態列、模型（只回報不強改）。結束寫完成標記（全部略過也寫）。
- **`apply_settings.py`**（標準函式庫）是唯一寫 `settings.json` 的路徑：只碰 `statusLine` 與 `autoCompactWindow`；已有值不覆蓋（結束碼 3）；JSON 壞掉或最外層不是物件不寫（結束碼 2）；寫前備份 `settings.json.bak-<時間>`；暫存檔＋`os.replace` 整份寫回；檔案不存在就建立。`install.sh --with-statusline` 也呼叫它。工具呼叫被權限擋下時，skill 不重試不繞路，把完整指令交給使用者以 `! <指令>` 自己執行。
- **狀態列檔案放固定位置。** user settings 不會展開 `${CLAUDE_PLUGIN_ROOT}`，而快取目錄含版本號、升級即失效，所以 plugin 安裝時把 `statusline.py`、`compact.py` 複製到 `~/.claude/chutora/statusline/`；session-start.sh 之後在該目錄存在時自動同步（內容不同才複製，目的地是符號連結不動）。
- **session-start.sh 的提示。** 標記檔 `${CLAUDE_PLUGIN_DATA:-$HOME/.claude/hooks}/.route-setup-done` 不存在且 `.route-setup-shown` 計數 < 3 時，輸出 JSON：`systemMessage` 一句話提示 route-setup，原本的全部文字放 `hookSpecificOutput.additionalContext`，並計數加 1；其他情況照舊輸出純文字。只用 sh 與 awk，JSON 跳脫 `\`、`"`、換行、tab 與其他控制字元，任何錯誤安靜結束。`hooks.json` 不新增 hook。
- **不採用 plugin settings 的 `agent` 鍵。** 它會把使用者所有對話的主 agent 換成 plugin 指定的那個，副作用遠大於「少打一個指令」的好處。
- **不自動寫 `settings.json`。** plugin 無法安全地代使用者改全域設定；一律經使用者同意，且 33k buffer 只是作者機器的實測值，需使用者用 `/context` 確認。

## 支援平台（目標：四個平台都有效）

Chutora 要在 **Cowork（Claude Desktop）、Claude Code CLI、VS Code 擴充、Codex** 都能用。功能分兩層：

- **通用層**（換平台照樣能用）：交接筆記與記憶放在連接資料夾、規劃／執行／大量讀取的分工、反問與回覆語言規則。本質是說明文字加資料夾裡的檔案；Codex 用 `AGENTS.md` 讀同樣的內容。
- **平台層**（每個平台各接一次）：hook（瘦身、去重、守門、決策引擎、狀態列）。

| 平台 | 狀態（2026-11-09） | 備註 |
|---|---|---|
| Claude Code CLI | 可用 | hook 實測正常 |
| VS Code 擴充 | 待使用者實跑自我檢查 | 底層同為 Claude Code，預期與 CLI 相同。`hooks/selfcheck.py` 已寫好（唯讀，印出環境、hook 觸發、守門與瘦身 dry 結果、語言），步驟見 [vscode-check.md](vscode-check.md)，結果尚未回報 |
| Cowork | 開發中（feat/v2-cowork） | 底層是 Claude Code 2.1.319，會跑 hook；外掛須上傳到 claude.ai 才會同步進 session。存取使用者資料夾走 `mcp__remote-devices__device_bash`：守門（含 `find -exec` 子指令）、瘦身與只讀指令的輸出去重已涵蓋；決策引擎復原點尚未涵蓋（復原點建不到使用者電腦） |
| Codex | 已研究，待實作轉接層 | 通用層可轉；守門只能 deny；瘦身／去重無法改寫輸出。見下方「Codex 轉接方案」 |

### Codex 轉接方案（2026-11-09 研究）

依據：openai/codex 原始碼（`codex-rs/hooks`，main 2026-11-09）的 hook schema 與測試為「官方」；標「二手」者來自第三方文章，實作前要再核對。

| Chutora 元件 | Codex 對應 | 可行性 |
|---|---|---|
| 分工說明、交接、記憶（通用層） | `AGENTS.md`；SessionStart／UserPromptSubmit hook 的 `additionalContext` | 可直接轉（官方：兩個事件都有 additionalContext） |
| 危險守門 | PreToolUse hook | **只能 deny**：`permissionDecision: allow／ask` 與 `decision: approve` 都被當成不支援而放行（fail open，官方測試 `unsupported_permission_decision_fails_open`）。「先問」改成：deny 並在原因寫明請使用者自行執行，或交給 Codex 自己的 approval policy |
| 核准時代答（決策引擎） | PermissionRequest hook，`behavior: allow／deny` | 可轉（官方）：只在 Codex 本來就要問使用者時觸發 |
| 噪音瘦身、讀檔去重 | PostToolUse hook | **不能改寫輸出**：只有 block 與 additionalContext，`updatedMCPToolOutput` 明確不支援（官方）。替代做法待實測：PreToolUse 的 `updatedInput`（官方支援）把指令改寫成 `set -o pipefail; <原指令> 2>&1 \| chutora-trim`，風險是改變結束碼與互動行為；Codex 自己也會把過大的輸出存成檔（`output_spill`） |
| 壓縮前後 | PreCompact／PostCompact hook | 可轉（官方） |
| 子 agent 分工 | `~/.codex/agents/*.toml`（name、description、developer_instructions、model…） | 要改寫成 TOML（二手） |
| skills | plugin 內的 `skills/` | 可轉（二手） |
| 外掛打包 | `.codex-plugin/plugin.json`，可帶 `hooks/hooks.json`（官方：`plugin_hook_declarations`） | 要另做一份 manifest |
| 狀態列 | 只有內建 `/statusline` 項目 | 做不到（二手） |

注意：管理員可在 `requirements.toml` 設 `allow_managed_hooks_only = true`，此時使用者與外掛的 hook 全部不生效（官方 docs/config.md）。

建議順序：(1) 通用層 + `AGENTS.md` 產生器；(2) 守門 deny 版 + PermissionRequest；(3) 實測 `updatedInput` 包裝瘦身，確認結束碼與 TTY 不受影響後才開放；(4) agents TOML 與 plugin manifest。

訊息語言（0.16.0-beta.4 起）：明確設定 > 依使用者提示自動偵測（`lang-detected`，純本地）> 系統語言 > 英文，四個平台共用同一函式。

新功能設計時要寫明在四個平台各自怎麼運作，或為什麼不支援。

## 已知限制

- plugin 跨對話,記憶跟著資料夾走。Cowork 忘了連接資料夾等於失憶。
- 委派靠 description 匹配,非保證。要確定用 `@agent-chutora:worker`。
- Cowork 會執行 hook（2026-11-09 驗證），但 `CLAUDE_PROJECT_DIR` 指向雲端工作目錄，不是連接資料夾。
- 使用者若已在 `~/.claude/` 自設同類 hook 或 CLAUDE.md 分工規則,會重複提醒。
- `MEMORY.md` 會腐化,需定期整理。超過 150 行或出現已不成立的敘述即是訊號。
- `harvester` 只看得到本機 session,網頁與手機的對話不在範圍內。
- 記憶注入本身是固定成本,與省 token 有張力。靠「常駐區保持薄」化解。
