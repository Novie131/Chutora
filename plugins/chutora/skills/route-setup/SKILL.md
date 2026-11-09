---
name: route-setup
description: 一次性的完整功能設定：記憶位置（claude-memory）、Haiku 版 Explore、自動壓縮門檻、context 狀態列。裝完 chutora 已可直接使用，想要完整功能時才執行。
disable-model-invocation: true
---
# Route setup

chutora 裝完就能用；這個 skill 只是把「想要完整功能」要做的事一項一項帶你做完。**每一項都先說「做什麼 → 影響 → 怎麼還原」，一次只問一項，使用者可以略過任何一項。** 沒得到同意前不要動任何檔案。

寫 `settings.json` 一律透過 `python3 "${CLAUDE_SKILL_DIR}/apply_settings.py"`，不要自己用 Edit 或 Write 改它。這支腳本只碰 `statusLine` 與 `autoCompactWindow`，已有值不覆蓋，壞掉的 JSON 不寫，寫入前自動備份成 `settings.json.bak-<時間>`。因為你已經逐項問過使用者，Chutora 的危險守門認得這支（Chutora 自己目錄裡的）腳本，不會再跳第二次確認；路徑要照寫 `${CLAUDE_SKILL_DIR}/apply_settings.py`，複製到別處或同一行再重導向到設定檔，守門就會照常詢問。

**若工具呼叫被權限（例如 auto mode）擋下：不要重試、不要繞路。** 把完整指令交給使用者，請他在輸入框用 `! <指令>` 自己執行，並附還原方式（把 `~/.claude/settings.json.bak-<時間>` 改回 `settings.json`）。

## 1. 記憶

- 檢查專案目錄有沒有 `claude-memory/`。有 → 告知「已就緒」，跳下一項。
- 沒有 → 說明：**auto memory 已經可用**（Claude Code 自己的記憶，每個 session 會自動帶入），不設定也能正常用。`claude-memory/` 是進階選項：可以放進 git、跨環境共用、Cowork 沙盒重建後也活得下來。
- 使用者要才建立：`mkdir -p claude-memory/{topics,kb,web}`，再從 `${CLAUDE_SKILL_DIR}/templates/`（即 skills/route-setup/templates/；`MEMORY.md`，需要時 `KNOWLEDGE-BASE.md`）複製。**目標檔案已存在就不覆蓋。**
- 還原：刪掉 `claude-memory/` 即可（若剛建立；先確認裡面沒有新內容）。

## 2. Haiku 版 Explore

- 做什麼：把 `${CLAUDE_SKILL_DIR}/templates/Explore.md`（即 skills/route-setup/templates/Explore.md）複製成 `~/.claude/agents/Explore.md`，讓搜程式碼改用 Haiku（plugin 蓋不掉內建的 Explore，主對話是 Opus 時內建版也跑 Opus）。
- `~/.claude/agents/Explore.md` 已存在就不覆蓋，只告知。
- 還原：刪掉 `~/.claude/agents/Explore.md`。

## 3. autoCompactWindow 153000

- 做什麼：在 `~/.claude/settings.json` 加 `"autoCompactWindow": 153000`，讓對話約 12 萬自動壓縮（扣掉 buffer 後）；給 handoff 留下緩衝，壓縮後 SessionStart hook 會自動帶回交接筆記，不需要手動 /clear。
- 先跑 `python3 "${CLAUDE_SKILL_DIR}/apply_settings.py" --status`：
  - `autoCompactWindow` 已有值 → **不覆蓋**，只告知現值並詢問使用者要不要自己改。
  - `modelSettingsOverridesAutoCompact` 為 true → 提醒有逐模型覆蓋，那些模型不吃這個全域值。
- 使用者同意才執行 `python3 "${CLAUDE_SKILL_DIR}/apply_settings.py" --set-autocompact 153000`。
- 寫入後請使用者用 `/context` 確認 Autocompact buffer（33k 只是作者機器的實測值，以他看到的為準）；壓縮點應約 120k，不是的話請他回報，再調整數值。
- 還原：把 `settings.json.bak-<時間>` 改回 `settings.json`，或手動刪掉該鍵。

## 4. 狀態列

- 做什麼：把 `statusLine` 指到本 plugin 的 `statusline.py`，閒置時顯示 `模型 │ 5h 42%(2h13m) │ 週 18%(週四14:00) │ ctx 95k │ 上輪 12.3k │ 淨省≈+3k │ 壓縮 120k`（額度只在有讀數時出現；`提醒 100k` 只在 context 提醒開啟時出現），Claude 工作時顯示目前動作，例如 `▶ worker·Sonnet 跑測試 npm test · 12s │ 5h 42%(2h13m) │ ctx 95k/120k │ 上輪 12.3k │ 淨省≈+3k`（駕駛艙穩定版）。
- 先決定指令路徑：
  - `~/.claude/hooks/chutora/statusline.py` 存在（install.sh 安裝）→ 指令用 `python3 ~/.claude/hooks/chutora/statusline.py`。
  - 否則（plugin 安裝）→ 先把 `statusline.py`、`compact.py`、`deck.py` 與 `usage.py` 複製到固定位置 `~/.claude/chutora/statusline/`（來源是 `${CLAUDE_PLUGIN_ROOT}/hooks/`；沒有這個變數就用 `${CLAUDE_SKILL_DIR}/../../hooks/`）。**不能直接指向 plugin 快取**（目錄含版本號，升級會失效；user settings 也不會展開 `${CLAUDE_PLUGIN_ROOT}`）。指令用 `python3 ~/.claude/chutora/statusline/statusline.py`。之後 plugin 升級時，session 開始的 hook 會自動把這幾個檔同步過去。
- 先 `--status` 看 `statusLine` 有沒有值：已有 → 不覆蓋，只告知現值；使用者要換請他自己決定。
- 使用者同意才執行 `python3 "${CLAUDE_SKILL_DIR}/apply_settings.py" --set-statusline "<指令>"`。
- 還原：把 `settings.json.bak-<時間>` 改回 `settings.json`；plugin 安裝另可刪掉 `~/.claude/chutora/`。

## 5. 模型

只回報目前主對話模型（`--status` 的 `model` 欄位，或你自己的模型）。**不強制改成 opus**；使用者想改自己用 `/model opus`。

## 6. 結束：寫入完成標記

不管使用者做了哪幾項、或全部略過，最後都要寫入完成標記，session 開始時就不會再提示設定：

```sh
mkdir -p ~/.claude/hooks && touch ~/.claude/hooks/.route-setup-done
d="${CLAUDE_PLUGIN_DATA:-}"; [ -n "$d" ] && mkdir -p "$d" && touch "$d/.route-setup-done"
```

（install.sh 安裝用第一行的位置；plugin 安裝的 hook 看的是 `${CLAUDE_PLUGIN_DATA}`，若 shell 環境沒有這個變數，就用 skill 文字中被替換出的 `${CLAUDE_PLUGIN_DATA}` 路徑。兩處都寫沒有壞處。）

最後用兩三句總結：做了哪些、略過哪些、備份檔在哪。若有改 settings，提醒重開 Claude Code 讓狀態列生效。
