---
name: usage-stats
description: 量測主對話 context 長度與子 agent 使用比例,做優化前後比較時使用。
---
# Usage stats

執行 `python3 "${CLAUDE_SKILL_DIR}/usage_stats.py"`,使用者給的參數原樣帶上:`--since YYYY-MM-DD`、`--until YYYY-MM-DD`、`--project 子字串`(只算目錄名含該字串的專案)、`--threshold N`(預設讀環境變數 `CONTEXT_REMIND_TOKENS`,再預設 100000)。預設只讀 `~/.claude/projects` 的紀錄,不寫任何東西。日期以本機時區計算。

## 怎麼回報

把結果直接摘要給使用者,依序講:

1. 主對話 context 中位數是否低於 10 萬(提醒門檻)
2. 有沒有呼叫超過 12 萬(自動壓縮點;看最大值與超過門檻的比例)
3. 子 agent 呼叫比例,以及有派過子 agent 的 session 比例
4. 哪一類子 agent 跑在 Opus 上(看「agent 類型」表,實際模型欄含 opus 的列);類型顯示「(未知)」代表找不到對應的 meta 檔
5. 哪個 agent 估計金額最高(agent 類型表已依金額由高到低排序,第一列即是);順帶講主對話與子 agent 的金額與占比

## 新欄位怎麼讀

- **派工次數**:不同的子 agent 檔案數,一次派工一個檔案。**calls** 是 API 呼叫數,一次派工通常有多次呼叫,兩者不要混為一談。
- **指定模型分布**:派工時 Task 參數指定的 model(例如「sonnet×5、未指定×1」)。「未指定」代表派工沒帶 model 鍵;「查無派工紀錄」代表找不到對應的 tool_use。把它跟「實際模型」並排看,就能知道派工參數是否覆蓋了 agent 檔案裡寫的 model。
- **估計金額**:依腳本內價格表(API 牌價,表上註明日期)算,input、output、cache 讀寫(5 分鐘與 1 小時分開)都計入,Haiku 依單次 prompt 是否超過 10 萬分兩段價。不在價格表的模型(含 `<synthetic>`)顯示「-」,不計入總額,輸出會註記未計價的呼叫數。
- 金額限制:訂閱方案不是按 token 計費,金額只用來比較相對大小;子 agent 的 output 偏低,所以子 agent 金額是下限。

## 圖表(`--html`)

使用者想看圖表時,加上 `--html "${TMPDIR:-/tmp}/chutora-usage.html"` 一起執行,並告訴使用者檔案路徑。報表是自足的靜態 HTML(無外部資源、支援深色模式),內容有摘要卡片、每日(本機日期)各 agent 類型的估計金額堆疊圖、agent 類型表。使用者要求才用 `open` 打開。這是唯一會寫檔的情況。

子 agent 的 output 欄位會嚴重低估(紀錄檔只記到串流開頭的值),所以不要拿子 agent 的 output 比較,金額也只當下限。

不要貼整張表,除非使用者要。要比較優化前後,請使用者給兩段日期各跑一次。
