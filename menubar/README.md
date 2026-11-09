# Chutora 用量儀表（Mac 選單列）

在選單列顯示 Claude Code 與 Codex 的額度，例如 `C 5h42% 週18% · X 5h10% 週3%`（C＝Claude、X＝Codex）。
用量 ≥80% 變黃、≥95% 變紅。點開看重置時間、上一輪 token、Claude 的淨省≈、資料多久前更新。

## 安裝

1. 安裝 SwiftBar：`brew install --cask swiftbar`，啟動後選一個外掛資料夾（xbar 也能用）。
2. 需要 `python3`。macOS 沒有的話執行 `xcode-select --install`。
3. 把腳本連結到外掛資料夾並加上執行權限：

   ```bash
   chmod +x menubar/chutora-usage.1m.py
   ln -s "$PWD/menubar/chutora-usage.1m.py" "$HOME/Library/Application Support/SwiftBar/Plugins/"
   ```

   或一行搞定：`bash install.sh --with-menubar`（資料夾不在預設位置時加 `SWIFTBAR_PLUGINS_DIR=<資料夾>`）。

檔名的 `.1m.` 表示每分鐘更新一次；點選單最後一行「重新整理」可立即更新。

## 資料來源與限制

- Claude：讀 `~/.claude/chutora/usage.json`，由 chutora 狀態列與 agent-board 面板寫入。沒有裝它們、或還沒開過 Claude Code，就沒有 Claude 這一節。
- Codex：讀 `$CODEX_HOME`（預設 `~/.codex`）下最新的 `sessions/YYYY/MM/DD/rollout-*.jsonl`，只看檔案最後約 256KB 的最後一筆 `token_count`。5 小時／每週依視窗長度分辨，不依順序。
- 資料超過 6 小時標「（舊資料）」；已過重置時間的讀數顯示「—」，因為重置後用量已歸零。
- Opus／Sonnet 分項：外掛拿不到，所以不顯示。
- Cowork 在雲端執行，每一輪的細節到不了這台 Mac，選單列看不到；Cowork 請看面板。額度是整個帳號共用的，所以在別處用掉的量會反映在 5h／週百分比上。
- 淨省≈ 是估計，可能是負值（外掛本身的固定開銷大於省下的），照實顯示。
- 時間一律用本機時區。任何讀取錯誤都只會顯示 `Chutora —`，不會跳錯誤。
