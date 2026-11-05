# 常見問題

<p><a href="../README.md">← 回到 README</a> · <a href="faq.en.md">English</a></p>

**Chutora 要付費嗎？**
不用，MIT 授權。用量跟平常一樣算在你的 Claude 方案裡；Chutora 的目的就是讓同樣的用量做更多事。

**會不會改我的設定？**
plugin 安裝本身不改 `settings.json`。只有 `/chutora:route-setup` 會在你逐項同意後寫入，寫之前先備份，已有的值不覆蓋。`/chutora mode` 和 `/chutora lang` 只寫 `~/.claude/chutora/` 底下自己的兩個小檔案。`/chutora doctor` 完全唯讀。

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
