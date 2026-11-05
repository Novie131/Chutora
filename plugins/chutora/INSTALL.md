# 三種環境怎麼裝

[English](INSTALL.en.md) | 繁體中文

先講結論:

| 環境 | 裝法 | 跟誰共用 |
|---|---|---|
| **Cowork(桌面版)** | 點 `.plugin` 檔安裝 | 自成一套 |
| **Claude Code CLI** | 跑 `install.sh` | ← 跟 VS Code 共用 |
| **VS Code 擴充** | 同上,裝一次兩邊都有 | ← 跟 CLI 共用 |

**CLI 和 VS Code 共用 `~/.claude/`,所以裝一次兩邊都吃得到。** Cowork 走自己的安裝流程,要另外裝一次。

---

## Cowork(桌面版)

點 `.plugin` 檔的安裝按鈕就好,**裝完即可用**(想要狀態列、自動壓縮門檻、Haiku Explore、claude-memory 等完整功能,執行 `/chutora:route-setup`),而且**所有對話都能用**(plugin 是使用者層級,不綁對話)。

要驗證的話,在新對話問「有哪些 agent 可以用?」,應該看得到 `worker`、`worker-hard`、`bulk`、`librarian`、`harvester`、`security-review`、`security-test`。

---

## Claude Code CLI 與 VS Code 擴充

這兩個共用同一份設定,所以下面做一次就好。

### 一鍵安裝

在 repo 根目錄執行(或把 `install.sh` 和 `chutora.plugin` 放同一個目錄;沒有 `.plugin` 時腳本會直接用 `plugins/chutora/`):

```bash
bash install.sh
```

腳本會把 agent、skill、hook **複製**到 `~/.claude/`(`agents/*.md` → `~/.claude/agents/`、`skills/<名>/` → `~/.claude/skills/`、`hooks/` → `~/.claude/hooks/chutora/`),不需要 marketplace、不需要 `/plugin install`。注意 Claude Code 不會載入 `~/.claude/skills/` 底下的 plugin 資料夾,所以腳本是把內容拆開放,而不是整包塞進去;舊版腳本裝在 `~/.claude/skills/chutora/` 的殘留會被自動移除。

這個模式下名稱**不帶命名空間**:agent 叫 `worker`(不是 `chutora:worker`),skill 叫 `/handoff`。

安裝過的項目會記在 `~/.claude/.chutora-installed`。已存在的同名檔:內容相同就納入清單,內容不同(你自己寫的)則不覆蓋並提醒;符號連結(`--link` 裝的)不動。

**hook 不會自動啟用**:腳本不改你的 `settings.json`,結尾會印出一段設定片段,要自己合併進 `~/.claude/settings.json` 的 `"hooks"`(已有同類 hook 時先移除舊的)。

裝完重開 Claude Code,即可使用;想要完整功能(狀態列、自動壓縮門檻、Haiku Explore、claude-memory)執行 `/route-setup`(此模式下 hook 要先照上面貼進 settings.json,提示才會出現)。

### 狀態列(選用)

加 `--with-statusline`(可與預設複製模式或 `--link` 併用;不能與 `--agents-only`、`--uninstall` 併用)。腳本只處理 `~/.claude/settings.json` 的 `statusLine`:檔案不存在就建立;已有 `statusLine` 不覆蓋,只印建議片段;沒有時先備份成 `settings.json.bak-<時間>`,再只加這一個鍵。JSON 壞掉或沒有 python3 則不修改。手動做法是貼這段(路徑只適用 install.sh 安裝;plugin 安裝的使用者請用 `/chutora:route-setup`):

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/chutora/statusline.py" }
```

另建議 `"autoCompactWindow": 153000`(腳本不會寫):扣掉約 33k buffer 後約 120k 自動壓縮,10 萬提醒後留 2 萬緩衝寫 handoff,壓縮後自動帶回交接筆記。33k 是作者機器的實測值,寫入後用 `/context` 確認壓縮點約 120k。

### 看板 mod(選用)

加 `--with-agent-board`(可與預設複製模式或 `--link` 併用;不能與 `--agents-only`、`--uninstall` 併用)。VS Code 不能帶 `--plugin-dir`,所以這個 mod(`plugins/agent-board`)要靠環境變數 `CLAUDE_CODE_PLUGIN_DIRS` 載入;腳本會替你把目錄加進 `~/.claude/settings.json` 的 `env.CLAUDE_CODE_PLUGIN_DIRS`(多個路徑用 `:` 分隔)。只碰這一個變數:沒有 `env` 就建立,已有值就附加,已含該路徑則不重複;先備份成 `settings.json.bak-<時間>`;JSON 壞掉或沒有 python3 則不修改,改印手動片段。`--link` 時路徑指向 repo 內的 `plugins/agent-board`;複製模式則先複製到 `~/.claude/chutora/agent-board/`(記入安裝清單)再指向那裡;從 `.plugin` 封包安裝時不含 agent-board,會略過。`--uninstall` 會把本腳本加的路徑從該變數移除(其他路徑與變數不動)。

裝完,VS Code 執行 Developer: Reload Window、終端機重開 `claude` 才會載入。用 plugin 市集安裝的人不需要這個旗標,改用 `/plugin install agent-board@chutora`。手動做法是在 `settings.json` 加:

```json
"env": { "CLAUDE_CODE_PLUGIN_DIRS": "/絕對路徑/plugins/agent-board" }
```

### 回覆格式與回覆模式（選用）

加 `--with-reply-detail`（限制、`--link`／複製模式、`--uninstall` 的處理全部同 `--with-agent-board`，可與它同時使用）。這個 mod（`plugins/reply-detail`）會在 system prompt 注入「精簡版三段式（現況／你要做的／需要你決定／提供）」的回覆格式規則（只對主對話生效，子 agent 忽略）。看板的「⇄ 回覆：精簡／詳細」切換鍵切到詳細後，之後每則回覆都是詳細版；只要單次的話輸入「詳細說明」，就會把上一則回覆改寫成詳細版。切換鍵不畫在回覆底下或輸入框上方，因為 VS Code 會替 mod 畫的這些區塊加上外框與標籤。一樣靠 `env.CLAUDE_CODE_PLUGIN_DIRS` 載入：`--link` 時路徑指向 repo 內的 `plugins/reply-detail`；複製模式則先複製到 `~/.claude/chutora/reply-detail/`（記入安裝清單）再指向那裡；從 `.plugin` 封包安裝時不含它，會略過。`--uninstall` 只移除本腳本加的這條路徑。裝完，VS Code 執行 Developer: Reload Window、終端機重開 `claude` 才會載入。用 plugin 市集安裝的人改用 `/plugin install reply-detail@chutora`。

### 驗證

```
/agents
```

應該看得到五個 agent(`worker`、`worker-hard`、`bulk`、`librarian`、`harvester`)。或直接 @-mention 試試:

```
@agent-worker
```

hook 貼好片段後,可用 `/hooks` 確認。

搜程式碼也想改用 Haiku 的話,加上 `--with-explore`(會把 `skills/route-setup/templates/Explore.md` 放到 `~/.claude/agents/`,已存在則不覆蓋):

```bash
bash install.sh --with-explore
```

### 如果 agent 沒出現

先確認有重開 Claude Code,再檢查 `~/.claude/agents/` 底下有沒有那五個 `.md`。只想要 agent、不要 skill 與 hook 的話,可改用:

```bash
bash install.sh --agents-only
```

只複製 agent 定義(同樣記入清單)。代價是 hook(context 提醒、session 開始帶入記憶)與 skill(`/handoff`、`/research`、`/usage-stats`)不會生效。

### 想自己維護、改了立即生效

```bash
bash install.sh --link
```

把 agent、skill、hook 用符號連結接到 repo 裡的檔案,`git pull` 或自己改完就生效,不用重裝。名稱不帶命名空間(`worker`、`/handoff`)。腳本不改 `settings.json`,會印出 hook 設定片段讓你自己貼。已存在的同名檔一律不覆蓋;repo 搬家後重跑一次即可。

### 只想先試不想裝

```bash
claude --plugin-dir ./chutora.plugin
```

`--plugin-dir` 吃得下 zip 壓縮檔,而 `.plugin` 就是 zip。這只對當次 session 有效,適合先試用。

---

## 版本需求

這個 plugin 用到幾個較新的 frontmatter 欄位:

| 欄位 | 用途 | 沒支援會怎樣 |
|---|---|---|
| `model` | 指定 agent 用哪個模型 | 全部跟隨主對話模型,分層失效 |
| `memory` | 持久記憶 | 記憶功能失效(但連接資料夾那條路仍可用) |
| `effort` | 依失敗代價配置推理量 | 跟隨 session 設定 |
| `omitClaudeMd` | bulk 不載入 CLAUDE.md(需 2.1.271+) | 會多載入 CLAUDE.md,較貴但可用 |

context 長度提醒 hook 需要 `python3`;找不到時安靜停用。

檢查版本:

```bash
claude --version
```

太舊的話:

```bash
claude update
```

另外 `memory` 依賴 auto memory。如果你關過 `autoMemoryEnabled`,或設了環境變數 `CLAUDE_CODE_DISABLE_AUTO_MEMORY`,那個欄位不會生效——這種情況下改用「連接資料夾裡的 `claude-memory/`」那條路(worker 本來就優先走它)。

---

## 主對話模型要另外設

**plugin 只定義 subagent,不會改你主對話的模型。** 分層架構的第一層要自己開:

```
/model opus
```

或寫進 `~/.claude/settings.json`:

```json
{ "model": "opus" }
```

沒設的話,主對話會用你原本的預設模型,派工判斷的品質會下降。

---

## 記憶資料夾在各環境的差別

記憶存在**你自己指定的資料夾**裡,不在 plugin 裡。三個環境的接法不同:

- **Cowork**:每次開新對話時把記憶資料夾連接進來。這是唯一需要重複做的動作,忘了連就等於失憶。
- **CLI**:在記憶資料夾底下開 session,或把它當專案根目錄。
- **VS Code**:把記憶資料夾加進工作區。

三個環境指向**同一個資料夾**的話,記憶就是共用的。這也是為什麼建議用 Obsidian 開那個資料夾——它同時是 agent 讀寫的地方、你檢視整理的地方、以及各環境連接的目標。

---

## 更新

重跑一次 `install.sh` 即可:清單內(之前裝的)項目會先刪再複製成新版,你自己的同名檔不會被動。Cowork 那邊則是重新點一次新的 `.plugin` 檔。

**兩邊要記得都更新。** 版本不一致時行為會不一樣,而這種問題很難察覺——你會以為是 agent 不穩定,其實是兩台在跑不同版本。
