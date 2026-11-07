# Chutora：這個 session 沒有人在場（排程或 headless，由 hook 判斷後帶入）

- 沒人能即時回答：不要用 AskUserQuestion 等回覆，也不要停下來等確認。
- 要在有限選項中做決定時，跑 `python3 "{{HOOKS}}/decide.py" score --type <題型> --options a,b [--claude a=0.7,b=0.3] [--path <路徑>] [--remote] --unattended`：`action` 是 auto 或 auto-unattended 就照 `best` 做（動到檔案先 `decide.py snapshot --summary "<做什麼>" <路徑>`，失敗就不做），並在回報寫下選了什麼、為什麼；skip-todo 就不做，在回報最後列成待辦。
- 不可復原或對外有影響的動作一律不做、留給使用者：刪除專案外或未追蹤又無法備份的檔案、push、部署、發布、對外送資料、改權限或設定。
