---
name: harness-tune
description: 讓 harness 對反覆卡關的任務越調越好;改前確認、可回滾
---
# Harness Tune（輕量自我強化迴圈）

取自 google-research/harness2 的想法：**模型權重不動，調的是模型外圍的八個元件**（system prompt、guardrails、memory、tool guidance、subagents、skills、scripts、plugins）。這份 skill 是它的**輕量、手動**版——不自動迭代（那會燒 token），而是在你覺得某類任務總是做不順時，有章法地改一次、記一次。

## 什麼時候用

- 某類任務一再出現，而且每次都要你多講一樣的話、或結果總差一點。
- 你剛讀完一次失敗，想把教訓固化進 harness，而不是下次重犯。

## 流程：Propose – Probe – Compose

1. **先讀 harness-lessons**：`claude-memory/harness-lessons.md`（沒有就說明並提議建立）。看這類任務以前試過什麼、什麼有效／無效，別重試已知沒用的。
2. **Propose（提案）**：針對這一類任務，提出**一到三個**具體、最小的調整。每個要寫清楚：
   - 改哪個元件（例如：worker 的委派提示、某個 skill 的某段、guide.md 的某條、tool guidance）。
   - 改成什麼、為什麼這會讓這類任務更順。
   - 怎麼復原。
3. **Probe（試）**：跟使用者確認要試哪一個後，**改前先備份**該檔，套用調整，然後在下一次同類任務上看效果（或當場用一個代表性例子比較前後）。一次只動一項，才分得出是哪個有效。
4. **Compose（取捨）**：有效就留下；無效或更糟就用備份還原。把結果寫進 harness-lessons。

## 界線

- **不自動改。** 每個調整都要先跟使用者確認；改前備份、改動可一步回滾（呼應整套 harness 的「可逆」原則）。
- **一次一項。** 同時改多項就分不清是誰的功勞或誰闖的禍。
- **記錄比調整本身重要。** 真正累積價值的是 harness-lessons：它讓下一次 tune 站在上一次的結論上，而不是從零摸索。

## harness-lessons 怎麼記

`claude-memory/harness-lessons.md`，一列一個調整：日期、任務類型、改了什麼、結果（有效／無效／更糟）、現在狀態（已保留／已還原）。範本在 `skills/route-setup/templates/harness-lessons.md`。
