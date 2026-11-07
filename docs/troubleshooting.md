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

### 狀態列沒顯示目前動作

先確認狀態列本身有出現（上一節）。plugin 安裝的狀態列檔案放在 `~/.claude/chutora/statusline/`，新版的 `deck.py` 會在下一次開新對話時自動同步過去；install.sh 安裝的要把它印出的 hooks 片段（含 PreToolUse、PostToolUseFailure、SubagentStart、SubagentStop 的 `activity.py`）重新合併進 `settings.json`。`/chutora doctor` 會檢查這一項。`CHUTORA_ACTIVITY=0` 會關掉它。

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

輸出最後一行有原文路徑，請 Claude 用 Read 讀；常遇到的話，`/chutora mcp-trim exclude <server>` 讓那個 server 完全不瘦身（或把工具名、前綴寫進 `~/.claude/chutora/mcp-trim-exclude`），或 `/chutora mcp-trim off`。0.15 以前純文字的說明文件也會被瘦身，0.16 起預設不動。

### 危險守門擋到不該擋的指令

先看原因裡的規則 id（例如 `[rm-home]`）。只是這一次：照提示允許即可。以後都不想被問：在 `~/.claude/chutora/always-ask` 加一行 `!rm-home`。全部關掉：`/chutora guard off` 或 `CHUTORA_GUARD=0`。如果是誤判（指令其實很安全），請開 issue 附上那個指令。

### `claude -p` 或略過權限模式下，指令被守門擋下沒有執行

這是預期行為：非互動執行沒有人可以按確認，Claude Code 會把「先問你」當成拒絕。略過權限模式（`--dangerously-skip-permissions`）下，確認視窗可能被跳過，所以 force push、刪專案外或家目錄的東西、`DROP TABLE`、`terraform destroy`、`kubectl delete` 這幾類做了沒有備份可以救回的，守門會直接擋下（原因會寫「因為目前是略過權限模式」）。確定要做，就自己在終端機執行，或關掉略過權限模式後再試一次；也可以那一次加上 `CHUTORA_GUARD=0`。

### 在你自己的互動式 Claude Code 驗證危險守門

下面全部用安全的假目標：remote 不存在、要刪的資料夾也不存在，就算真的執行也不會改到任何東西。先開一個拋棄式的資料夾：

```sh
mkdir -p /tmp/chutora-guard-test && cd /tmp/chutora-guard-test && git init -q && git commit -q --allow-empty -m init
```

**(a) 一般模式：危險指令會跳確認視窗**

1. 在這個資料夾執行 `claude`（不要加任何權限旗標），確認 `/chutora` 顯示「危險守門（實驗中）：開啟」。
2. 跟 Claude 說：「用 Bash 執行 `git push --force chutora-guard-test-nowhere HEAD`，被擋就停下來，不要重試。」
3. 預期：跳出確認視窗，原因寫著 `Chutora 守門：這在「永遠要問」清單上：強制推送… [force-push]`。選「不要」。
4. 再試 `rm -rf ~/chutora-guard-test-xxx`：預期一樣跳確認、規則是 `[rm-home]`。選「不要」（選允許也沒關係，這個資料夾不存在）。

**(b) 略過權限模式：ask 類是否被放行、deny 類是否被擋**

1. 結束後改用 `claude --dangerously-skip-permissions` 在同一個資料夾重開。
2. deny 類：再要 Claude 執行上面兩個指令。預期：**不跳視窗、直接被擋**，原因寫著「因為目前是略過權限模式…所以直接擋下」，Claude 會請你自己在終端機執行。
3. ask 類：要 Claude 執行 `git reset --hard`（這個拋棄式 repo 沒有未提交的修改，執行了也沒有損失）。看它是跳出確認、被擋，還是直接執行——這就是你這個版本的 Claude Code 在略過權限模式下怎麼處理 hook 的「先問你」。
4. 看紀錄：`/chutora` 會顯示「近 7 天攔下 N 次」；`tail ~/.claude/chutora/projects/*/observations.jsonl` 會看到 `guard_ask`、`guard_deny`，略過權限模式擋下的那幾筆帶 `"bypass_deny": true`。
5. 驗證完刪掉 `/tmp/chutora-guard-test`。結果（特別是第 3 步）歡迎開 issue 回報，附上 `claude --version`。

### 決策引擎沒有自動執行

依序檢查：`/chutora` 顯示「決策引擎（實驗中）：開啟」、危險守門也開著；你回過 `/chutora ok <id> auto`（`/chutora changes` 的「最近已處理」看得到 `ok_auto`）；這次的指令和那次夠像（路徑樣式不同就不算，例如 `build/` 同意過不代表 `dist/`）；整段指令只有刪除這件事（接了 `&& npm run build` 就不會自動）；24 小時內沒有復原過相似的；要刪的東西不超過 200 MB／2 萬個檔案（`CHUTORA_BACKUP_MAX_MB`），而且 `~/.claude/chutora/projects/` 可以寫入（`/chutora doctor` 會檢查）。settings 的 `permissions.deny` 擋下的，引擎也放不行，這是 Claude Code 的設計。

### 回覆結尾一直出現「Chutora 自動做了…」那一行

那是待確認的提醒，回應之後就停：`/chutora ok all auto`、`/chutora ok all ask`，或只想清掉不想讓它學：`/chutora ok all`。

### 觀察紀錄沒有寫入

先看 `/chutora` 是否顯示「觀察紀錄（實驗中）：開啟」。install.sh 安裝的要把新版 hooks 片段（PostToolUse、PostToolUseFailure、SubagentStop、UserPromptSubmit 的 `observe.py`，以及 PreToolUse 的 `guard.py`）合併進 `settings.json`；`/chutora doctor` 會檢查這一項。

### 還是不行

開一個 issue，附上 `/chutora doctor` 的輸出和 Claude Code 版本（`claude --version`）。
