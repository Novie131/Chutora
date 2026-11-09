# VS Code 自我檢查

確認 Chutora 在 VS Code 的 Claude Code 擴充裡有載入、hook 有觸發。

## 步驟

1. 在 VS Code 的 Claude Code 開一個**新對話**。
2. 貼上這句（把 `<外掛路徑>` 換成實際路徑）：

   > 請執行 Chutora 自我檢查：`python3 <外掛路徑>/hooks/selfcheck.py`，並把結果原樣貼給我。

3. 外掛路徑怎麼找：
   - 用 plugin 安裝：通常在 `~/.claude/plugins/` 底下，找含 `hooks/selfcheck.py` 的 `chutora` 目錄（`find ~/.claude/plugins -name selfcheck.py`）。
   - 用 `install.sh` 或 clone 安裝：repo 內的 `plugins/chutora`。
   - 也可以直接問 Claude：「找出 selfcheck.py 的位置再執行」。

這個腳本唯讀、不呼叫模型、不會真的執行檢查用的指令。

## 看哪幾行算通過

| 行 | 通過的樣子 |
|---|---|
| 執行環境 | `CLAUDE_CODE_ENTRYPOINT=claude-vscode`（VS Code 擴充通常是這個值；照實顯示） |
| 外掛來源與版本 | 路徑是你預期的，版本是最新的 |
| hook 觸發紀錄 | 有「最近一次寫入」，而且是剛剛。出現 ⚠️ 代表 hook 沒觸發：讓 Claude 用任一工具後再跑一次，仍然沒有就是外掛沒載入 |
| 守門 dry（兩行） | 都是 ✅，決定為 `ask`（`force-push`、`claude-settings`） |
| 瘦身 dry | `150 行 → 數行` |
| 語言 | 與你的提示語言相符 |

最後一行 `❌ 0` 即通過；有 ❌ 請把整份報告貼給維護者。
