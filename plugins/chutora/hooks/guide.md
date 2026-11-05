# chutora：本 session 的分工慣例（由 hook 在 session 開始時帶入）

主對話負責理解、規劃、判斷與驗收；動手與大量讀取在子 agent 的獨立 context 裡做，主對話只收結論。留在主對話的每次工具輸出，之後每一輪都會被重新計費到對話結束，這是派工的主要理由。

| 工作 | 交給 |
|---|---|
| 方向已定的實作：寫或改程式、修 bug、補測試 | `worker` |
| worker 失敗後的升級（附前次失敗報告） | `worker-hard` |
| 只要結論的大量讀取：多張圖片或影格、長 log、抓網頁、輸出很多的指令 | `bulk` |
| 「之前記過什麼」：claude-memory/ 或 auto memory 裡的記憶、筆記、外部資料筆記 | `librarian` |
| 搜尋程式碼、找檔案或用法 | `Explore` |
| 外部文件、API、版本差異，回答需附來源 | `/research` |
| 把歷史對話整理進知識庫（僅在使用者明確要求時） | `harvester` |
| 分清事實與推測的調查、找根因、審查結論，回答要分 觀察／推論／未知 並附出處 | `/evidence-analysis` |
| 對自己的程式碼做靜態安全審查（OWASP、附證據與修補、嚴重度分級） | `security-review` |
| 對自己、已授權且隔離的 dev 環境做動態安全測試（開工先確認授權範圍） | `security-test` |
| 哪些工具／MCP 長期沒用到、可以關掉省 token | `/toolprune` |
| 讓這套 harness 針對某類任務越調越好（改前確認、可回滾） | `/harness-tune` |
| 使用者想看目前狀態、不知道有哪些功能、要健檢安裝、切換模式或語言 | `/chutora`（`/chutora doctor`、`/chutora mode`、`/chutora lang`） |

以 plugin 安裝時，上表名稱前面會加 `chutora:`（例如 `chutora:worker`、`/chutora:research`）。

- 安全界線：`security-review`／`security-test` 只用於使用者自己或明確授權的程式碼與環境；動態測試只在隔離環境、不碰 production、不外送資料、開工先確認授權範圍。

- 派工以一段完整工作為單位，不是一個步驟；每次啟動子 agent 都要重付系統提示。小而明確的事，主對話直接做比較省。
- 實作工作派 `worker`，不要派 general-purpose：它沿用主對話的模型（通常是 Opus），實測曾有 408 次實作跑在 Opus 上。
- 子 agent 看不到這段對話，委派訊息要自足：目標、檔案路徑、限制、回傳格式。
- 子 agent 的結論先抽查它附的證據再採用；「沒有、找不到」這類結論沒有證據可查，主對話自己再搜一次才轉述。
- worker、worker-hard、bulk 的回報前兩行固定是 `狀態：完成｜失敗｜需要決策` 與 `驗證：通過｜未驗證｜失敗`，照這兩行決定下一步，不用讀完全文再判斷：
  - `完成`＋`通過` → 抽查證據後採用
  - `完成` 但驗證不是 `通過`、或前兩行不合格式 → 當成 `失敗` 處理
  - `失敗` → 走下面的升級鏈
  - `需要決策` → 不升級；主對話判斷，判斷不了就問使用者
- 失敗升級依序：補背景後同一個 agent 重派 → bulk 失敗改 worker → worker 失敗改 worker-hard（附失敗報告）→ 仍失敗就停下，重新規劃或詢問使用者，不再往上升。
- 完成要有可執行的驗證（測試、lint、實際執行），「看起來完成」不算。
- 持續萃取：做出決定、完成子任務、查到關鍵事實時，就順手更新 handoff，不要等 context 提醒。
- micro-skills：這個 repo 怎麼跑的固定指令事實（測試怎麼下、哪個指令才對、要吃哪個環境變數、產出檔放哪），確認後記進 `claude-memory/` MEMORY.md 的「指令事實」區，讓之後的 session 不用重新摸索同一件事。
- 對話變長時，UserPromptSubmit hook 會帶入目前的 context 大小；那時用 handoff skill 寫交接筆記，並照提醒文字的指示回報（有設自動壓縮就只需告知，不用手動處理）。
- loop guard：PostToolUse hook 會偵測同一個錯誤反覆出現，並注入一句提醒換方向；看到這類提醒就認真考慮改路、退一步或回報使用者，別用同樣方式硬重試。
- 專案有 `claude-memory/` 時，下方會附上它的記憶索引；有 `handoff.md` 時也會附上，那是上一個對話留下的進度。沒有 `claude-memory/` 時記憶在 auto memory（Claude Code 自己會帶入它的 MEMORY.md；handoff.md 則由本 hook 帶入）。
