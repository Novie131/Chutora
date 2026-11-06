# 常見問題

<p><a href="../README.md">← 回到 README</a> · <a href="faq.en.md">English</a></p>

**Chutora 要付費嗎？**
不用，MIT 授權。用量跟平常一樣算在你的 Claude 方案裡；Chutora 的目的就是讓同樣的用量做更多事。

**會不會改我的設定？**
plugin 安裝本身不改 `settings.json`。只有 `/chutora:route-setup` 會在你逐項同意後寫入，寫之前先備份，已有的值不覆蓋。`/chutora mode` 和 `/chutora lang` 只寫 `~/.claude/chutora/` 底下自己的兩個小檔案。`/chutora doctor` 完全唯讀。實驗中的觀察紀錄寫在 `~/.claude/chutora/projects/`，危險守門攔下時在 `claude-memory/changes.jsonl`（或 auto memory 目錄）追加一行，都不碰 `settings.json`。

**跟 Claude Code 內建的 `/rewind` 差在哪？**
`/rewind` 會在你每次送出訊息前存檔，可以還原主對話用編輯工具改過的檔案。官方文件寫明兩個例外：子 agent 改的檔案、Bash 指令改的檔案，都不會被還原。Chutora 把實作交給 worker 子 agent，所以這部分目前請用 git；路線圖上的「卡關救援」會補上這塊。

**主對話一定要用 Opus 嗎？**
建議用，因為主對話負責規劃、判斷和驗收，派工的品質取決於它。換成其他模型也能運作，只是判斷品質可能下降。

**為什麼有時候主對話自己做，沒有派工？**
派工是依 agent 的說明文字比對，不是保證；而且小而明確的事直接做比派工省，這是刻意的。想確定就用 `@agent-chutora:worker` 指定。

**省錢模式會讓結果變差嗎？**
有可能：它縮小驗證範圍、主對話看得比較少。重要的工作用平衡或品質模式。

**每週回顧的金額是實際花費嗎？**
不是。它是依 API 牌價、只算模型價差的估算；訂閱方案不按 token 計費。

**資料會外送嗎？**
hooks 只讀寫本機檔案。只有你要查外部資料時（research）才會連網；`security-test` 明確規定不外送資料、不碰 production。

**支援 VS Code 嗎？**
支援 Claude Code 的終端機版和 VS Code 擴充。選裝的看板 mod 裝完要在 VS Code 執行 Developer: Reload Window。

**可以只用一部分功能嗎？**
可以。看板和回覆格式是選裝；`bash install.sh --agents-only` 只裝 agent；不需要的 skill 可以在 `/plugin` 裡停用整個 plugin，或用 install.sh 安裝後自己刪掉。

**噪音輸出瘦身會不會砍掉重要資訊？**
它刻意保守：只處理成功、而且超過門檻的安裝／建置／測試輸出；錯誤、警告、assert、stack trace 這類行連同前後 2 行一定保留，開頭與結尾也保留；失敗的指令、讀檔類指令、`git diff` 都不動。萬一真的需要被略過的部分，原文一定在 `~/.claude/chutora/raw/`。

**怎麼看被瘦身前的原文？**
瘦身後的輸出最後一行會寫原文路徑（`~/.claude/chutora/raw/<id>.log`），直接請 Claude「讀原文」，或自己打開那個檔案。想完全關掉：`/chutora trim off`。

**讀檔去重會不會讓 Claude 看不到檔案？**
不會讓它看不到「還在對話裡」的內容：只有先前那次讀取的結果還在目前這條對話鏈上、檔案也完全沒變時才去重；壓縮、`/clear`、`/rewind` 之後就照常重讀。萬一 Claude 說找不到先前的內容，請它讀不同範圍，或 `/chutora dedup off`。

**反問會不會什麼事都問？**
不會。小事和已經講清楚的不問，一次最多 3 到 5 題，而且一定有「照預設、別問了」。只想要它少問：說「別問了，照預設」，或 `/chutora ask off` 關掉「你說不確定時」的提醒。

**MCP 輸出瘦身會不會漏掉我要的欄位？**
被略過的筆數、截斷的字串都會在輸出裡註明，原文一定存在 `~/.claude/chutora/raw/`。某個工具一定要完整輸出，就把它加進排除清單（`CHUTORA_MCP_TRIM_EXCLUDE` 或 `~/.claude/chutora/mcp-trim-exclude`）。

**MCP 瘦身為什麼不瘦純文字了？**
0.15 曾把一個 connector 的使用說明砍掉 204 行，Claude 就照著殘缺的說明做事。說明文件每一行都可能有用，所以 0.16 起純文字與 Markdown 預設不動，只處理 JSON 的長陣列與重複項。真的想瘦純文字：`/chutora mcp-trim text on`。

**危險守門會不會擋到我平常的指令？**
它只看「永遠要問清單」：`git push origin feat/x`、`rm -rf node_modules`、`npm install` 這類一般指令不攔，commit 訊息或 `echo` 裡「提到」危險指令也不攔。某條規則一直問到你不想再被問，就在 `~/.claude/chutora/always-ask` 加一行 `!<規則 id>`（`/chutora guard rules` 列出 id）。

**用 `--dangerously-skip-permissions` 時守門還有用嗎？**
有。`rm -rf ~` 這類「直接擋」在任何權限模式都擋（官方文件寫明）。「先問你」的項目用 `claude -p` 加這個旗標實測時沒有執行（沒有人能確認，當成拒絕），Claude 會收到原因並向你說明。互動模式下的行為還沒實測。

**觀察紀錄會不會花 token？存了什麼？**
不花：它不輸出任何東西，實測有沒有它，同一個任務的輸入 token 只差每次執行本來就有的幾個。它只存精簡摘要（指令、路徑、工具名、輸出大小），不存工具輸出內容，一般提示只記長度，常見金鑰格式會遮罩。檔案在 `~/.claude/chutora/projects/<專案 id>/`，超過 5 MB 自動輪替；不想要就 `/chutora observe off`。

**Benchmark 的數字在哪？**
還沒公布。`bench/run.py` 已經可以跑，但在實際跑完、核對過之前不放任何數字，見 README 的 [Benchmark](../README.md#benchmark)。

**駕駛艙會不會拖慢 Claude？**
狀態列版每次工具呼叫只寫一個小 JSON 檔，transcript 用增量讀取；面板版只觀察工具呼叫、不改結果，重繪最多每 250ms 一次，時間線最多留 40 筆。任何一邊出錯都會安靜放行，不會擋住工具。
