# chutora：本 session 的分工慣例

主對話只理解、決定、審查：實作給 `worker`，大量讀取給 `bulk`，查記憶給 `librarian`，搜程式碼給 `Explore`。

- 實作別派 general-purpose（沿用貴模型）。
- 子 agent 看不到對話，委派訊息要自足（目標、路徑、限制、回傳格式）。
- worker/worker-hard/bulk 回報前兩行：`狀態：完成｜失敗｜需要決策`、`驗證：通過｜未驗證｜失敗`。完成+通過→抽查後採用；完成但驗證未過或格式不符→當失敗；需要決策→不升級，自己判斷或問使用者。
- 升級：bulk→worker→worker-hard（附失敗報告）→仍失敗就停下，重新規劃或問人。
- 完成要有可執行的驗證（測試、lint、實跑）。
- 安全測試只限自有或已授權的目標，動態測試限隔離環境、不碰 production。
- 只有主對話反問（AskUserQuestion），小事不問；題數依模式；答案寫進 `claude-memory/briefs/<日期>-<slug>.md`，標出驗收標準，派工附上。
- 有決定或關鍵事實就更新 handoff。
