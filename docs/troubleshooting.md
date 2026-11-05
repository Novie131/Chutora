# 疑難排解

<p><a href="../README.md">← 回到 README</a> · <a href="troubleshooting.en.md">English</a></p>

遇到問題先跑 **`/chutora doctor`**。它是唯讀的，會逐項列出「正常／選用／要修」，要修的項目附上修法。下面是常見情況。

### 裝了沒反應

1. 執行 `/reload-plugins`；VS Code 執行 Developer: Reload Window，終端機重開 `claude`。
2. 執行 `/chutora doctor`，看 hooks 那一項。
3. macOS 上 hooks 需要可用的 `python3`。沒裝 Command Line Tools 時，`/usr/bin/python3` 只是一個會跳安裝視窗的殼，Chutora 會安靜跳過提醒功能。執行 `xcode-select --install` 安裝後重開。

### 提醒訊息是英文（或想改成英文）

執行 `/chutora lang zh`（或 `en`）。macOS 從 Dock 或 VS Code 啟動時常常沒有設定 `LANG`，所以會預設成英文。改回依系統語言：`/chutora lang auto`。

### 對話很長卻沒看到 context 提醒

- 門檻預設 10 萬 token，可用環境變數 `CONTEXT_REMIND_TOKENS` 調整。
- 提醒在你送出下一則訊息時才檢查，而且同一格只提醒一次（之後每多 4 萬再提醒）。
- 需要 `python3`；`/chutora doctor` 的「hook 觸發紀錄」一直是空的，代表 hooks 沒在跑。

### 狀態列沒出現

plugin 沒辦法自己設定主狀態列。plugin 安裝的用 `/chutora:route-setup`；install.sh 安裝的用 `bash install.sh --with-statusline`。

### 每個 agent 都出現兩份

舊版沒移除：`smart-agent-route`（0.10.0 以前）或 `tiered-agents`（0.7.0 以前）。`/chutora doctor` 會列出殘留位置，照 [部署安裝](部署安裝.md) 的升級章節移除。

### 子 agent 跑在 Opus 上，沒有省到

- 實作要交給 `worker`，不要交給 general-purpose（它會沿用主對話的模型）。
- 內建的 Explore 會跟著主對話跑 Opus，用 `/chutora:route-setup` 裝 Haiku 版。
- `/chutora:usage-stats` 的「agent 類型」表可以看到每類 agent 實際跑在哪個模型。

### install.sh 安裝後 loop guard 沒作用

0.12.0 以前的 install.sh 印出的 hooks 片段少了 PostToolUse。重跑 `bash install.sh`，把新印出的片段合併進 `~/.claude/settings.json`。`/chutora doctor` 會檢查這一項。

### loop guard 太敏感或不夠敏感

用環境變數 `LOOP_GUARD_REPEAT` 調整同一錯誤重複幾次才提醒（預設 3）。

### 不想看到每週回顧

在 `~/.claude/settings.json` 的 `"env"` 加 `"CHUTORA_WEEKLY": "0"`。

### 指令輸出被瘦身後，Claude 少看到需要的內容

瘦身說明的最後一行有原文路徑，請 Claude 用 Read 讀那個檔案即可。常常遇到的話：改用品質模式（`/chutora mode quality`，門檻較高、保留較多），或 `/chutora trim off` 關掉。

### 想確認噪音輸出瘦身有沒有作用

輸入 `/chutora`，狀態裡會顯示開關與累計瘦身的 token（估算）。用 install.sh 安裝的，`/chutora doctor` 會檢查 settings.json 裡有沒有 `trim.py` 這個 PostToolUse hook；沒有就重跑 `bash install.sh`，把印出的 hooks 片段合併進去。

### Claude 說內容跟先前一樣，但它其實需要重看

這是讀檔去重。它只在先前那次結果還在對話裡、檔案也沒變時才出手；如果 Claude 需要重看（例如前面的內容被它自己略過了），請它讀不同範圍，或 `/chutora dedup off` 關掉。

### 反問太多或太少

題數依模式：省錢 3、平衡 4、品質 5（`/chutora mode`）。太多：說「別問了，照預設」，或 `/chutora ask off`。太少：直接說「先問我」或輸入 `/chutora ask`。

### MCP 工具的輸出被瘦身後少了需要的內容

輸出最後一行有原文路徑，請 Claude 用 Read 讀；常遇到的話，把那個工具加進 `~/.claude/chutora/mcp-trim-exclude`（一行一個工具名或前綴），或 `/chutora mcp-trim off`。

### 還是不行

開一個 issue，附上 `/chutora doctor` 的輸出和 Claude Code 版本（`claude --version`）。
