# chutora

分層委派:**主對話用 Opus 思考,執行派給 Sonnet,檢索與大量讀取交給 Haiku**;再加上 context 長度提醒與交接筆記,讓主對話可以放心保持短。

---

## 這套東西的形狀

先講一個容易搞反的地方。

直覺上會想做「前置路由器」——讀你的訊息、判斷是規劃還是執行、再決定用哪個模型。**這做不到**,因為要判斷意圖就得先讀懂訊息,而讀懂就是規劃本身。用便宜模型當路由器會誤判,用貴模型當路由器則你已經付了錢。

所以正確的形狀是反過來的:

```
你 ──► 主對話(Opus)  ← 永遠是大門,負責理解與判斷
            │
            ├──► worker(Sonnet medium)  ← 方向已定、動手做的事
            │      └► worker-hard(Sonnet high) ← worker 失敗後的升級
            ├──► bulk(Haiku)              ← 大量讀取只要結論:圖片、長 log、網頁
            ├──► librarian(Haiku)         ← 查知識庫。唯讀,讀得廣回得精
            ├──► Explore(Haiku,選裝)      ← 搜程式碼。需另裝到 ~/.claude/agents/
            ├──► harvester(Sonnet)        ← 把歷史對話挖進知識庫(手動觸發)
            └──► 你自訂的 Haiku agent       ← 已驗證的固定流程(預設留空)

  skill:handoff(寫交接筆記)、research(查外部資料並附來源)、usage-stats(量測 context 與子 agent 用量)
  hook :SessionStart(帶入分工慣例、記憶索引、交接筆記)、UserPromptSubmit(context 過長時提醒)
```

**判斷該找誰的人,是那個已經理解任務的人。**

成本上這反而是划算的:規劃只有一則訊息,執行迴圈常常是三十次工具呼叫。省下後者就等於省下大部分。

---

## 安裝與設定

**裝完即可用。** 想要完整功能（狀態列、自動壓縮門檻、Haiku Explore、claude-memory）執行 `/chutora:route-setup`（install.sh 安裝則是 `/route-setup`）；下面各步驟是它在做的事，也可以手動做。


### 1. 安裝 plugin

```
/plugin install chutora --marketplace Novie131/chutora
```

(Claude Code 2.1.275 以前的版本先 `/plugin marketplace add Novie131/chutora`,再 `/plugin install chutora@chutora`。)

context 長度提醒需要 `python3`;沒有的話這個 hook 會安靜停用,其餘功能照常。

### 1.5(建議)搜程式碼也改用 Haiku

主對話是 Opus 時,內建的 Explore 也跑 Opus。**plugin 裡的 agent 蓋不掉內建 Explore**——官方文件寫明只有使用者或專案層級、名為 `Explore` 的 agent 才能覆蓋。所以這一步要手動:

```bash
cp skills/route-setup/templates/Explore.md ~/.claude/agents/Explore.md   # 或 bash install.sh --with-explore，或 /route-setup
```

已經有自己的 `Explore.md` 就不用做。

### 2. 把主對話設成 Opus

```
/model opus
```

或寫進 settings.json:

```json
{ "model": "opus" }
```

**替代選項:`opusplan`。** 規劃模式用 Opus、離開後自動切 Sonnet。省錢,但代價是只有在你手動進入規劃模式(Shift+Tab)時才會用到 Opus——一般對話就吃不到 Opus 的判斷力,委派品質會下降。

建議:先用 `opus` 跑一陣子,覺得成本有感再換 `opusplan`。

### 3. 初始化記憶

**這步決定了記憶能不能跨對話活下來,不要跳過。**

plugin 本身裝一次就到處都在(它在使用者層級,不綁對話)。但**記憶不一定跟著走**,而且兩種環境的行為不同:

| 環境 | 記憶位置 | 跨對話存活 |
|---|---|---|
| Claude Code(終端機) | `~/.claude/agent-memory/worker/` | ✅ 會 |
| Cowork(桌面版) | 沙盒家目錄,每個 session 重建 | ❌ **不會** |

所以 worker 被設定成**優先使用「已連接資料夾裡的 `claude-memory/`」**,找不到才退回 agent 記憶目錄。這個位置在兩種環境下都活得下來。

**做法:選一個你自己的資料夾當記憶庫**(建議直接開一個新的、專用的),在裡面建 `claude-memory/`:

```bash
mkdir -p <你的資料夾>/claude-memory/{topics,kb,web}
cp skills/route-setup/templates/MEMORY.md <你的資料夾>/claude-memory/MEMORY.md   # 或 /route-setup
```

`topics/` 給 agent 累積,`kb/` 放你自己的筆記——詳見 `skills/route-setup/templates/KNOWLEDGE-BASE.md`。

然後:

- **Cowork**:每次開新對話時把這個資料夾連接進來。這是唯一需要重複做的動作。
- **Claude Code**:在這個資料夾底下開 session,或直接把它當專案根目錄。

> 退回路徑依賴 auto memory。如果你關過 `autoMemoryEnabled` 或設了 `CLAUDE_CODE_DISABLE_AUTO_MEMORY`,`memory` 欄位不會生效——這種情況下連接資料夾就不是建議,是必要。

### 4. (選用)接上 Obsidian

用 Obsidian 開你剛才那個資料夾當 vault,`claude-memory/` 就是裡面的一個目錄。

沒有 MCP、沒有 symlink、沒有同步腳本——vault 本來就只是一個裝 `.md` 的資料夾,跟 agent 記憶是同一種東西。

這樣一來記憶庫同時是:agent 讀寫的地方、你用 Obsidian 檢視整理的地方、以及每次連接給 Cowork 的那個資料夾。三件事一個位置。

**Obsidian 在這裡的作用是給人看的,不是給 agent 用的。** Claude 讀那些檔案靠 Grep 和 Read,有沒有 Obsidian 都一樣。它真正解決的是:記憶需要定期整理,而整理很苦、苦就不會做、不做這套架構就慢慢廢掉。Obsidian 讓整理變得不痛苦——買的是可維護性,不是能力。

三個注意事項:

- **開新的專用 vault,別指向你現有的個人筆記庫。** agent 有寫入權,而且你的個人筆記會變成雜訊。
- **`[[wikilink]]` 對 Claude 來說只是文字**,它不會自動跟著跳。所以 `MEMORY.md` 的索引要寫明「什麼時候該去讀哪個檔」,不能只丟連結。
- Obsidian 會建 `.obsidian/` 設定目錄,無害,但之後若改用 project scope 進了 git 記得 gitignore。

---

## 怎麼用

正常講話就好。主對話會自己判斷該不該派工:

- 「幫我想清楚 X 該怎麼做」→ 留在 Opus
- 「照剛才講的做」→ 派給 worker
- 「我之前有記過 X 嗎」「筆記裡有沒有提過 Y」→ 派給 librarian
- 「看一下這 18 張截圖有沒有跑版」「這份 log 為什麼失敗」→ 派給 bulk
- 「這個 API 新版怎麼設定」→ research skill,回答附來源,官方資料存進 `claude-memory/web/`
- 「交接一下」或 hook 提醒 context 過長 → handoff skill 寫 `handoff.md`,之後可以 `/clear`
- 「@agent-chutora:worker 做 X」→ 強制指定

主對話怎麼分工,不靠你的 CLAUDE.md:plugin 的 SessionStart hook 會在每個 session 開始時把分工表帶進去(內容見 `hooks/guide.md`)。

**失敗升級**依序:補背景後同一個 agent 重派 → bulk 失敗改 worker → worker 失敗改 worker-hard(附前次失敗報告)→ 仍失敗就停下來重新規劃或問你。不會無限升級。

---

## 擴充:什麼時候加 Haiku 層

`skills/route-setup/templates/runner.md.example` 是預留的位置,**目前不會被載入**,這是刻意的。

Haiku 層是唯一真正省錢、也唯一真正有風險的一層——它不會停下來問你,它會照著它以為的意思安靜做完。所以每個 Haiku agent 都必須綁死在一件具體任務上,不能寫成通用 runner。

三個條件同時成立才啟用:

1. 這件事你已經做過三到五次,流程幾乎一樣
2. 成功的樣子明確到你一眼能判斷
3. 做錯可承受且可回復(不刪東西、不送出去、不覆蓋無備份的檔案)

任何一項不成立,就繼續留在 worker。

追蹤方式在 `MEMORY.md` 的「重複次數紀錄」——worker 每次指認就記一筆。這是刻意保留的手動關卡:自動偵測「這件事重複了」很容易誤判,而真正知道「這件事我閉著眼睛都能做」的人是你。

---

## 知識庫與 RAG

**這套架構本身就是 RAG,只是檢索方式不同。** `MEMORY.md` 的觸發索引是 retrieval,主題檔是語料,需要時才讀進來就是 augmentation。差別在於檢索靠的是條件判斷和關鍵詞搜尋,不是向量相似度。

`librarian` 就是這層的執行者:它用 Haiku 跑,在知識庫裡反覆搜尋,只把相關的原文片段帶回來。

**為什麼檢索是 Haiku 層最好的用途。** 我原本說 Haiku 層有「安靜地做錯」的風險,所以留空。檢索是這個風險的例外:

- **唯讀。** 它只有 `Read` / `Glob` / `Grep`,沒有寫入工具,做錯了也改不壞東西。
- **成功標準明確。** 找到就是找到,而且它必須回報「搜過哪些詞」「什麼沒找到」,你一眼就能驗證。
- **省得最多。** 它讀二十個檔案、回傳一段話。翻找的成本留在它自己的 context 裡,不進你的對話。

所以這是唯一我願意預設就開的 Haiku agent。

知識庫的目錄結構與組織原則見 `skills/route-setup/templates/KNOWLEDGE-BASE.md`,包含什麼時候才該考慮上向量檢索(簡短答案:個人規模通常不需要,而且常常更差)。

### 兩種餵資料的方式

**你自己丟的**——`.md` 直接放進 `kb/`,不用任何前處理,librarian 立刻找得到。

**從歷史對話挖的**——`harvester` 負責。它讀過去 session 的逐字稿,萃取出還會用到的知識,按主題寫進 `kb/`,並更新 `MEMORY.md` 的索引。

跟你說一聲:

```
把之前的對話整理進知識庫
```

它會先列出可讀的 session 讓你選範圍,不會悶著頭全部讀完。

**四個限制先講清楚:**

- **只看得到本機的 session。** 網頁版或手機上的對話紀錄不在範圍內。
- **成本不低。** 逐字稿很長,所以這是偶爾跑一次的批次作業,不是常駐功能。它在自己的 context 裡讀,主對話只收到成果——但那個 context 一樣要付錢。
- **萃取一定會失真。** harvester 被要求標註不確定處、保留矛盾、註明來源 session,但**產出值得你抽查**,尤其是頭幾次。
- **它會寫進 `kb/`。** 而 `kb/` 原本的定位是「你自己的東西,agent 不該改」。如果你在意這條界線,先叫它寫到 `kb/harvested/` 底下,確認品質再決定要不要併進去。

### 什麼時候跑

**第一次安裝後跑一次**,把已經累積的東西撈起來當起點——這是它最有價值的時刻,因為過去的對話是現成的、免費的語料。

之後就不太需要了:worker 每次收工都會寫記憶,新知識是即時累積的。只有在你**換了工具、或有一陣子沒用 plugin** 的情況下,才值得再跑一次補齊。

---

## 省 token:四個槓桿,照順序做

**1. Context 隔離(最大的一筆,而且是複利)**

對話裡的每一則訊息、每一次工具回傳,在**後續每一輪都會被重新送一次**。一個跑 30 次工具呼叫的任務,如果全在主對話裡做,那 30 份結果會被反覆計費到對話結束。

派給 worker 就不一樣:它在自己的 context 裡跑完,主對話只收到一份摘要。

省下的不是 30 次呼叫,是「30 次 × 剩下的輪數」。這個量級遠大於換模型。

> **操作守則:整包派工,不要一件一件派。**
> 每次啟動 subagent 都要重付一次系統提示 + 記憶注入。派 5 次小任務比派 1 次大任務貴。
> 派工的單位應該是「一段完整的工作」,不是「一個步驟」。

**2. 模型分層**

有用,但它是線性的——省的比例大致等於價差比例。真正的重頭戲在上面那一項。

**3. `effort` 等級**

worker 用 `effort: medium`,搭配「完成後必須驗證」與失敗升級到 worker-hard(`high`)。librarian 用 `low`(純檢索)。

> 0.6 版 worker 是 `low`。改成 `medium` 的理由:執行層做錯的代價是主對話要收拾,而升級鏈只在失敗時才付 `high` 的錢。想更省可以改回 `low`,但先觀察 worker 有沒有開始毛躁、漏步驟。

**4. 主對話別開太久(plugin 會幫你盯)**

Opus 掛著一段長對話是最安靜的漏斗——整段歷史每輪重送一次。實測一個重度使用者 21 個 session:主對話每次呼叫的 context 中位數約 24 萬 token,其中絕大部分是在重讀舊對話。

所以這一項不只靠自覺:

- **UserPromptSubmit hook** 在 context 超過 10 萬 token 時提醒一次,之後每多 4 萬再提醒(門檻可用環境變數 `CONTEXT_REMIND_TOKENS` 調整)
- 提醒時 Claude 會用 **handoff skill** 把現況寫進 `handoff.md`(目前任務 / 已完成 / 下一步 / 未決問題)。有設 `autoCompactWindow`(見下)時只會告訴你「約 N k 會自動壓縮、壓縮後自動帶回交接筆記,不需手動處理」;沒設才給可複製的指令(告一段落 `/clear`、做到一半 `/compact 保留…`、後半段是除錯雜訊就 `/rewind` 局部摘要)
- 每次壓縮、`/clear`、新 session 開始時 **SessionStart hook** 自動帶入 handoff.md:專案有 `claude-memory/` 就用它,否則用 transcript 旁 auto memory 目錄的 `handoff.md`(Claude Code 只會自動帶入 auto memory 的 MEMORY.md 索引,不會帶 handoff.md)。話題告一段落時,換新對話或 `/clear` 仍然更省

建議另外在 `~/.claude/settings.json` 把自動壓縮當保險(plugin 不能代設，`/chutora:route-setup` 會幫你安全地寫入):`"autoCompactWindow": 153000`:扣掉約 33k 的 buffer 後約在 12 萬自動壓縮,在 10 萬提醒之後留 2 萬緩衝寫 handoff(33k 是作者機器的實測值,寫入後請用 `/context` 確認壓縮點約 120k;有 `modelSettings` 逐模型覆蓋時要一併看)。

**狀態列**(選用):顯示 `模型 │ ctx 95k │ 提醒 100k │ 壓縮 120k`,壓縮點讀自 `autoCompactWindow`(沒設就不顯示)。plugin 不能設定主狀態列,用 `bash install.sh --with-statusline`,或手動貼進 settings.json(路徑只適用 install.sh 安裝;plugin 安裝的使用者請用 `/chutora:route-setup`，它會把檔案放到固定位置):

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/chutora/statusline.py" }
```

提醒文字也會帶入預估的壓縮點。

---

## 記憶與省 token 的關係

這兩件事看起來衝突,其實可以同時成立,關鍵是**改變成本的計價方式**。

如果常駐記憶裡塞的是知識本身,成本就跟「你總共記得多少」成正比——這條路一定撞牆,記越多越貴,最後你會為了省錢不敢記。

所以 `MEMORY.md` 的常駐區只放**觸發條件**,知識本體全放主題檔,需要才讀。成本改成跟「這次用得到多少」成正比。**總知識量可以無限成長,每次啟動的固定成本不動。**

這代表「保持 MEMORY.md 薄」有兩個理由,而且方向一致:

- 超過上限會被截斷(hook 帶入 120 行、auto memory 200 行),你就不知道自己知道什麼
- 常駐內容是每個 session 都付的固定成本

範本裡的 40 行預算就是照這個訂的。維護它不是潔癖,是這套架構的運轉條件。

---

## 設計取捨

**為什麼沒有 planner subagent。** 主對話本身就是 planner,再加一個是多餘的中間層,只會多一次轉手和一份 context 損耗。

**為什麼記憶優先放連接資料夾,而不是靠 `memory:` 欄位。** `memory:` 欄位的三個位置(`user` / `project` / `local`)路徑是寫死的,不能指定。而 Cowork 的沙盒家目錄每個 session 重建,寫進去等於丟掉。改成優先用你自己指定的資料夾,就同時解決了跨對話持久化、跨環境一致、以及 Obsidian 檢視這三件事。`memory: user` 保留當退路,在終端機的 Claude Code 裡仍然有效。

**為什麼 MEMORY.md 是索引不是筆記本。** 它每個 session 都被帶入(hook 最多 120 行,HTML 註解與空行不算),膨脹就截斷。保持它薄是它能運作的前提。

**為什麼用 SessionStart hook 帶入記憶,而不是請你改 CLAUDE.md。** plugin 改不了使用者的 CLAUDE.md,而放在 plugin 根目錄的 CLAUDE.md 不會被載入。hook 的純文字輸出會成為 context,這是 plugin 唯一能影響主對話行為的穩定管道。

**為什麼 Explore 要另外裝。** 官方文件:只有使用者或專案層級名為 `Explore` 的 agent 能覆蓋內建版;plugin 的 agent 優先順序最低。

**為什麼記憶要記「下次怎麼做」而不是「這次做了什麼」。** 流水帳不會讓下一次變快。記憶的價值在於免掉重新判斷,不在於留下痕跡。

---

## 已知限制

- **plugin 到處都在,記憶跟著資料夾走。** plugin 裝一次所有對話都能用。但記憶存在你指定的資料夾裡,不在 plugin 裡——在 Cowork 每次開新對話得把那個資料夾連進來,忘了連就等於失憶。這是這套架構目前最容易踩到的坑。
- **委派靠 description 匹配,不是保證。** 主對話有時會自己動手而不派工。想確定就 `@agent-chutora:worker`。
- **hook 在 Cowork 的行為未驗證。** agent 與 skill 是標準 plugin 元件;hook 是否在 Cowork 執行、`CLAUDE_PROJECT_DIR` 是否指向連接資料夾,尚未實測。
- **如果你已經在 `~/.claude/` 自己設過同樣的東西**(context 提醒 hook、bulk agent、CLAUDE.md 裡的分工規則),裝了會重複提醒、重複規則,先移除其中一邊。
- **`MEMORY.md` 會腐化。** 這不是 bug,是需要你定期花五分鐘的維護項目。腐化的訊號是超過 150 行、或出現已經不成立的敘述。
