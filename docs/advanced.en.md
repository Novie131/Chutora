# Chutora advanced guide

<p><a href="../README.en.md">← Back to README</a> · <a href="advanced.md">繁體中文</a></p>

The README keeps only the three-minute start; this is the full guide.

<a name="problem"></a>

## <img src="../assets/icons/puzzle.svg" width="26" height="26" alt=""> What problem this solves

After using Claude Code for a while, two things tend to happen:

- **It gets expensive**: the main conversation's Opus does everything itself, including reading long logs, looking through piles of screenshots, and editing dozens of files. Most of that work is fine on a cheaper model.
- **Conversations keep growing**: every message and every file read is sent to the model again on every later turn. Late in a long conversation, most of what you pay for is re-reading old content. Measured on one heavy user across 21 sessions, the median context per main-conversation call was about 240k tokens.

This plugin works like a lead running a team: the lead (Opus) listens, thinks it through, and decides who gets the work; the hands-on work goes to team members (Sonnet, Haiku), who finish it at their own desks and hand back only the conclusion, so the lead's desk stays clean. When the desk is nearly full, the lead writes a handoff note, clears the desk, and continues from the note.

**Good fit**: you already use Claude Code for multi-step work (changing code, reading logs, looking things up) and want to save money or keep long conversations under control. If you only ask the occasional one-off question, the benefit of delegation is small.

---

<a name="usage"></a>

## <img src="../assets/icons/bubble.svg" width="26" height="26" alt=""> Using it

Just talk normally; the main conversation decides whether to delegate:

| You say | Who handles it |
|---|---|
| "Help me think through how to do this" | The main conversation (Opus) thinks it through itself |
| "Do what we just discussed" | worker (Sonnet) does it, verifying before reporting back |
| "Check these 18 screenshots for layout breakage", "Why did this log fail" | bulk (Haiku) reads it all and returns only the conclusion |
| "Did I note anything about X before?" | librarian (Haiku) searches memory and cites where it found things |
| "How do I configure the new version of this API" | The research skill looks it up and cites sources; official material is saved to `claude-memory/web/` |
| "Hand off" | The handoff skill writes `handoff.md`, after which you can `/clear` |

To force a specific agent, use `@agent-chutora:worker`.

When the conversation gets long (past 100k tokens by default) you get a reminder, and Claude first writes the current progress into `handoff.md`. After that, whether it is an auto-compact, a `/clear`, or a new conversation the next day, the handoff note comes back automatically, so you do not have to explain everything again.

### Glossary

- **context**: everything the model sees on this turn, including the system prompt, conversation history, and tool results. Measured in tokens; the longer it is, the more it costs.
- **subagent**: a helper the main conversation sends out. It works in its own separate context and hands back only the conclusion.
- **skill**: a fixed procedure you can invoke, such as `handoff` for writing a handoff note.
- **hook**: a script Claude Code runs automatically at certain moments, such as when a session starts or when you send a message.
- **effort**: how hard the model thinks. Higher means longer thinking and higher cost.
- **auto-compact**: when the context is nearly full, Claude Code condenses the old conversation into a summary.
- **Cowork**: the agentic work mode in the Claude desktop app.

---

<a name="modes"></a>

## <img src="../assets/icons/sliders.svg" width="26" height="26" alt=""> Modes, language and weekly recap

### Three modes

A mode changes the delegation conventions injected into the main conversation at session start, plus the thresholds for noisy-output and MCP trimming and how many clarify questions are asked at once (economy 3, balanced 4, quality 5). Each agent's model and effort live in its agent file, and a plugin can't change them per mode, so switching modes never moves worker to a different model. The actual effect depends on how closely Claude follows the conventions.

| Mode | What actually changes |
|---|---|
| `economy` | Delegate more eagerly: reading more than 3 files, images, long logs or long command output all go to bulk or Explore; even small changes go to worker as a whole; when worker fails, re-dispatch once with more context before escalating; verify with the relevant tests only |
| `balanced` (default) | Follow the delegation conventions as written, no extra adjustments |
| `quality` | Escalate to worker-hard after a single worker failure; the main conversation reviews the key diff itself before accepting; verify with the full test suite; ask you first when a design trade-off is involved |

Switch with `/chutora mode economy` (or `balanced`, `quality`). The setting is saved to `~/.claude/chutora/mode` and takes effect when a new conversation starts; the conversation where you switched follows the new mode too. Delete the file to go back to the default.

### Language

Reminders, handoff prompts, the status line and `/chutora` check, in order:

1. The `CHUTORA_LANG` environment variable (`zh` or `en`)
2. `~/.claude/chutora/lang` (written by `/chutora lang zh` or `/chutora lang en`; `/chutora lang auto` removes it)
3. The system locale: the first of `LC_ALL`, `LC_MESSAGES`, `LANG` that is set; Chinese if it starts with `zh`
4. Otherwise English

### Weekly recap

When the first conversation of each ISO week starts, one line of estimate appears: if the tokens subagents handled over the past 7 days had been processed by the main conversation's most-used model instead, how much more they would have cost at API list prices.

- Model price difference only; savings from context isolation are not included, so it's a conservative estimate.
- Subscriptions aren't billed per token; use the number for relative comparison only.
- It shares the price table with `usage-stats`; for the full report run `/chutora:usage-stats`.
- To turn it off, add `"CHUTORA_WEEKLY": "0"` to `"env"` in `~/.claude/settings.json`.
- With noisy-output trimming on, the same line adds an estimate of how many tokens trimming kept out of the context.

### Noisy-output trimming

Commands such as `npm install`, `pytest` and `cargo build` often print hundreds of lines of progress and logs when only the errors and the final summary matter, yet all of it enters the context and is resent every turn. Chutora uses a standard PostToolUse hook (`hooks/trim.py`) to trim the result before it reaches the context:

- **When**: only successful Bash commands whose output is over the threshold. Thresholds follow the mode: economy 3000 characters or 80 lines, balanced 4000 or 120, quality 8000 or 250. Commands it doesn't recognize get double the threshold and keep more lines.
- **How**: strips color codes and `\r` progress rewrites, collapses progress bars and repeated lines, and keeps a few dozen lines at the start and end. Lines with error, fail, exception, traceback, warning, assert and similar keywords are always kept, with 2 lines around them, as are summary lines such as test results and install totals. If trimming would save less than a fifth, it leaves the output alone.
- **Never touched**: file-reading commands (`cat`, `head`, `tail`, `sed`, `grep`, `ls`…), `git diff`/`show`/`log`/`status`, commands already piped into `| head` or `| grep`, `python -c`, JSON output, background commands, and very large output Claude Code already saved to a file. Failed commands go through PostToolUseFailure, which can't rewrite output, so error output always arrives in full.
- **The original is always kept**: saved to `~/.claude/chutora/raw/<tool_use_id>.log` (the 50 most recent are kept). The last line of the trimmed output names the path, so Claude can Read it when it needs something that was omitted.
- **Switch**: `/chutora trim off` (saved to `~/.claude/chutora/trim`) or the `CHUTORA_TRIM=0` environment variable; `/chutora trim on` turns it back on.
- **How much it saved**: trimmed characters accumulate in `~/.claude/chutora/trim-stats.json`; `/chutora` and the weekly recap show them as tokens using "characters ÷ 4", which is an estimate.


### Read dedup

Claude often re-reads the same unchanged file within one conversation, paying for it again each time. `hooks/dedup.py` (PostToolUse, Read) replaces the result with one line ("same as read #N, the file is unchanged, use that earlier result") only when **all** of these hold:

- Same context: the main conversation and each subagent (the hook input's `agent_id`) are tracked separately, never across contexts.
- Same file and same range (offset/limit, start line, line count), with an identical content hash.
- The earlier result is still on **the current conversation chain**: the hook reads the transcript and walks back from the newest entry along `parentUuid` looking for that `tool_use_id`. After a compact, `/clear` or `/rewind` the earlier result is off the chain, so the file is read normally; if the transcript can't be read, nothing is deduped.
- Not an image, PDF or notebook, not a truncated read, and at least 1,500 characters.

Since 2.1.86 Claude Code has had a similar built-in mechanism (an unchanged re-read returns `file_unchanged`), but it is behind a remote flag, and community reports say many sessions stopped seeing it after 2.1.286 ([anthropics/claude-code#100265](https://github.com/anthropics/claude-code/issues/100265)). When the built-in one fires, this hook receives no full content and does nothing.

Switch: `/chutora dedup off` (saved to `~/.claude/chutora/dedup`) or `CHUTORA_DEDUP=0`. Savings are recorded under `dedup` in `trim-stats.json`; the token figure is an estimate.

### MCP output trimming

`hooks/mcptrim.py` (PostToolUse, `mcp__.*`) handles huge payloads from MCP tools and replaces them through `updatedMCPToolOutput`:

- **When**: only when the whole output is over the threshold; thresholds and how much is kept depend on the mode: economy 3,000 chars / 20 list items, balanced 4,000 / 30, quality 8,000 / 60. Left alone if it saves less than a fifth.
- **JSON**: long lists keep the first N items with a count of the rest, consecutive identical items are merged into one line, and empty fields (`null`, `""`, `[]`, `{}`) are dropped. String fields are not cut.
- **Plain text and Markdown are left alone**: in usage guides and document content every line may matter. 0.15 once cut 204 lines from the Claude Docs connector's `guide` text; from 0.16 they are not touched by default. To trim plain text anyway, use `/chutora mcp-trim text on` (or `CHUTORA_MCP_TRIM_TEXT=1`): the noisy-output line rules apply (start, end, errors and summaries kept) and long strings inside JSON are cut (economy 800, balanced 1,500, quality 3,000 chars).
- **Shape preserved**: a string stays a string, a content array stays a content array; images and other non-text blocks are untouched.
- **Original**: saved to `~/.claude/chutora/raw/<tool_use_id>.log`, with the path on the last line of the output.
- **Exclude list**: `/chutora mcp-trim exclude <server>` (`include` to undo; the file is backed up to `.bak` first), or set the `CHUTORA_MCP_TRIM_EXCLUDE` environment variable (comma-separated) or `~/.claude/chutora/mcp-trim-exclude` (one per line) yourself. Use full tool names, prefixes (`mcp__github__`) or just a server name (`github`, same as `mcp__github__`).
- **Switch**: `/chutora mcp-trim off` or `CHUTORA_MCP_TRIM=0`.

### Clarify

Inspired by the clarify step in [github/spec-kit](https://github.com/github/spec-kit) (find what is underspecified, ask, fold the answers back into the spec), Chutora does a lightweight version that needs no full spec:

- **When**: you say "ask me first" or type `/chutora ask`; you say you're not sure ("not sure", "what do you think" — `hooks/ask.py` adds a reminder next to your prompt); or a big task is vague (several files, unclear scope, several approaches), which the delegation conventions leave to the main conversation's judgment. Small or already-clear tasks aren't questioned. Only the main conversation asks; subagents never do.
- **How**: Claude Code's built-in AskUserQuestion, at most 3 questions in economy, 4 in balanced, 5 in quality; the recommended option comes first and "use the defaults, stop asking" is always there. It only asks what changes the result: scope (in / out), what counts as done, constraints (what must not change), edge cases, trade-offs (fast vs complete).
- **Where the answers go**: `claude-memory/briefs/<date>-<slug>.md` (or `briefs/` in the auto memory folder) with goal, scope, acceptance criteria, constraints, edge cases and trade-offs, attached when delegating to worker. "What counts as done" is the acceptance criteria, ready for the planned completion checks.
- **Switch**: `/chutora ask off` or `CHUTORA_ASK=0` only turns off the reminder when you say you're unsure; `/chutora ask` always forces it.

### Danger guard (experimental)

`hooks/guard.py` (PreToolUse, `Bash|Write|Edit|MultiEdit|NotebookEdit|Read|mcp__.*__device_bash`) checks an always-ask list before a tool runs and, on a match, returns the standard `hookSpecificOutput.permissionDecision` with a bilingual `permissionDecisionReason`:

- **Ask you first (ask)**: force push (`--force`, `-f`, `--force-with-lease`, `+branch`); pushing to main/master (including no branch given while you are on main); `rm -rf` or deleting files outside the project (temp folders excepted); deleting the whole project or its `.git`; a delete path with a variable that can't be checked; reading or writing `.env` (templates such as `.env.example` excepted) and key files (`id_rsa`, `*.pem`, `*.key`, `.netrc`…); `DROP TABLE` / `DROP DATABASE` / `TRUNCATE`; `terraform destroy`; `kubectl delete`; changing `~/.claude/settings.json`, the project's `.claude/settings.json` or Chutora settings (including `/chutora guard off`; except when `/chutora:route-setup` runs the `apply_settings.py` inside Chutora's own folder, since it has already asked you item by item. A script with the same name elsewhere, a redirect into a settings file on the same line, or rewriting that script itself still asks); `git reset --hard`; `git clean -f`; Claude granting itself automatic permission (running `/chutora ok … auto` or editing `decisions.jsonl`, rule `self-grant`, blocked outright in bypass-permissions mode).
- **Blocked (deny)**: unmistakable disasters: `rm -rf /`, `rm -rf ~`, deleting a system folder, `mkfs`, `dd of=/dev/<disk>`. The reason goes back to Claude, and it's up to you to run it yourself in a terminal.
- **No false alarms**: commands go through a small shell tokenizer first (quotes, heredocs, `$(...)`, `sh -c`, `sudo` / `env` prefixes, paths after `cd`), so merely *mentioning* these words in a commit message, `echo` or `grep` isn't caught; `git push origin feat/x`, `rm -rf node_modules` and `rm -rf build/` run as usual. When a command can't be parsed (an unclosed quote, say) it falls back to a conservative whole-text match. It is a best-effort check, not a sandbox.
- **Permission modes**: PreToolUse hooks run first in every permission mode. The official docs say `deny` still applies under bypassPermissions / `--dangerously-skip-permissions`; they don't say what `ask` does there, so it was tested with `claude -p` on Claude Code 2.1.319: in default mode, with `--allowedTools Bash` (an allow rule) and with `--dangerously-skip-permissions`, a command the guard asks about did not run (nobody could confirm it; it shows up in `permission_denials`) and the reason went back to Claude. The confirmation prompt in an interactive session, and interactive bypass mode, have not been tested yet (steps to check it are in [troubleshooting](troubleshooting.en.md#check-the-danger-guard-in-your-own-interactive-claude-code)). In bypassPermissions / dontAsk mode the reason also tells Claude "this did not run; explain it to the user and don't work around it".
- **Blocked in bypass-permissions mode**: when the hook input's `permission_mode` (the official docs list `default`, `plan`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`) is `bypassPermissions`, a confirmation prompt may be skipped, so the six rules a backup can't undo, `force-push`, `rm-outside`, `rm-home`, `sql-drop`, `terraform-destroy` and `kubectl-delete`, plus `self-grant`, go from ask to deny; the reason says it is because of bypass-permissions mode and asks you to run it yourself in a terminal or turn bypass-permissions mode off and retry. Every other rule and every other mode is unchanged; with `claude -p --dangerously-skip-permissions` the hook was seen receiving exactly `bypassPermissions`.
- **Your rules**: `~/.claude/chutora/always-ask`, one per line: `<regex>` adds an ask rule (matched against the whole Bash command, or a file tool's path), `deny: <regex>` adds a block rule, `!<rule id>` removes a default rule (`/chutora guard rules` lists the ids), and `#` starts a comment. Broken regexes are skipped and listed by `/chutora doctor`.
- **Record**: every stop is written to the change log (see [Memory](#memory)) and the observation log; if the same call then actually runs (you allowed it), it is marked `user_response: approved`.
- **Switch**: `/chutora guard off` (saved to `~/.claude/chutora/guard`; this command itself asks you first) or `CHUTORA_GUARD=0`.

### Observation log (experimental)

`hooks/observe.py` (PostToolUse, PostToolUseFailure, SubagentStop, UserPromptSubmit) records what happened in `~/.claude/chutora/projects/<project id>/observations.jsonl`, the groundwork for learning from outcomes later.

- **No tokens**: the hook prints nothing. Running the same task twice each way, input tokens were 83,795 / 83,790 with these hooks and 83,788 / 83,785 without, within the few tokens every run varies by anyway.
- **Project id**: from `CLAUDE_PROJECT_DIR` (or the current folder) up to the git repo, the first 12 characters of the sha256 of the remote URL (credentials and `.git` removed); with no remote, of the repo root path; outside a repo, of the folder path. The same repo cloned elsewhere gets the same id. `meta.json` in that folder says which project it is.
- **Each record**: time, session, agent (`main` or the subagent type), signal (`tool_ok`, `tool_fail`, `repeat_error`, `delegation_result`, `user_correction`, `user_choice`, `user_prompt`, `guard_ask`, `guard_deny`, `trimmed`, `reread`), tool name, a short summary (command, path or subagent description, at most 160 characters) and the output size. **Tool output is never stored**; ordinary prompts only record their length; common key formats (`sk-…`, `ghp_…`, `AKIA…`, JWTs, `Bearer …`, `password=…`, credentials in URLs, private-key blocks) are masked.
- **Corrections and choices**: "不對", "錯了", "我不是要這個", "不是這樣", "that's wrong", "not what I asked" and the like become `user_correction`; a bare number, "option B" and AskUserQuestion answers become `user_choice`.
- **Trimmed and re-read**: when noisy-output or MCP trimming actually trims, a `trimmed` record is written (tool, `kind`, original length `orig_chars`, `saved_chars`); when read dedup decides a read is a re-read, a `reread` record (inside the project the relative path `file`, outside it only the first 12 characters of the path's sha256 as `file_hash`; which read `n`, `saved_chars`). Both only write to the file and print nothing, so they add no tokens. When Claude Code itself saves a very large output to a file (around 30 KB and up), trimming doesn't step in, so there's no `trimmed` record.
- **Privacy**: by default a correction keeps its first 160 characters (masked) and a choice its first 40. With `/chutora observe privacy strict` (saved to `~/.claude/chutora/observe-privacy`) or `CHUTORA_OBSERVE_PRIVACY=strict`, corrections and choices (AskUserQuestion answers included) keep only their length, none of your words; `/chutora observe privacy normal` switches back. The environment variable wins over the file; `/chutora` and doctor show the current setting.
- **Rotation**: past 5 MB the file moves to `archive/` next to it, keeping at most 5 (`CHUTORA_OBSERVE_MAX_MB` to adjust).
- **Switch**: `/chutora observe off` (saved to `~/.claude/chutora/observe`) or `CHUTORA_OBSERVE=0`.


### Decision engine (experimental)

`hooks/decide.py` scores bounded decisions (yes/no, pick one, a level) and decides whether something may be done without asking you. It calls no model and doesn't use Laya / Clef; only their method is borrowed.

- **Confidence**: `p_i = w·(n_i+α)/(N+kα) + (1−w)·c_i`, `w = N/(N+m)`. `n_i` is how often similar records chose i (each weighted by similarity), `N` the total, `k` the number of options, `c_i` Claude's own estimate (uniform if none), `α=1`, `m=5`. When you have explicitly said "this kind may be automatic / ask me next time", the most recent such answer with similarity ≥0.8 becomes `c` (0.9 for that option), because your words beat Claude's guess.
- **Similarity**: rule-based weighted matching of context features (decision type must match; category, action, path pattern, git branch, whether files are tracked, whether they can be regenerated, project); only records with similarity ≥0.6 count. No vector database.
- **Calibration**: every time the answer becomes known it is recorded with a Brier score; predictions of the same type are bucketed by 0.1 and buckets with ≥5 samples are pulled toward the observed hit rate (if the 0.7 bucket is right only 60% of the time, it is lowered). `/chutora decide stats` shows the mean Brier and buckets.
- **Recoverable (objective checks)**: being inside the project folder is required; tracked in git and committed → recoverable; caches and build output that can be regenerated → no impact; anything else is recoverable only once an automatic backup succeeds; pushing to a remote or writing to outside services → not recoverable.
- **Thresholds**: recoverable with no impact ≥0.70 runs automatically; recoverable with impact ≥0.85 (after a backup); not recoverable with impact never. Economy −0.05, quality +0.05; +0.10 when there is no similar history; similar contexts undone in the last 24 hours never run automatically.
- **No time to choose** (`--unattended`: you didn't answer, said "you decide", or a scheduled run has nobody to ask): pick the most likely option and record why; not recoverable with impact, or best <0.5 and not recoverable → not done, saved as a to-do (`decision_todo`).
- **A restore point before every automatic action**: copies of files / folders (config files get a timestamp with `--config`) and `git stash create` (leaves the working tree alone; kept under `refs/chutora/restore/<id>`). Over 200 MB or 20,000 files (`CHUTORA_BACKUP_MAX_MB`) or a failed write → not automatic. Restore points live in `~/.claude/chutora/projects/<project id>/restore/`.
- **Hooked into the guard**: it only looks when the guard found nothing, or only `git-reset-hard` / `git-clean`; the whole command must be just that one thing (in-project `rm` / `rmdir` / `unlink`, optionally after `cd`; or a lone `git reset --hard` / `git clean`) — pipes, redirections, `$`, backticks, `sudo` or any other command are never approved. Every other guard rule, your `always-ask` rules and the bypass-mode denies stay with the guard; the engine can't touch them. It returns `permissionDecision: "allow"` only when it has learned you're fine with this kind running automatically and the restore point was saved. Tested on Claude Code 2.1.319: `allow` skips the prompt, but `permissions.deny` in settings still wins, so an auto-approved call is only listed as "to confirm" after PostToolUse shows it really ran.
- **How learning starts**: the first time, after you allow it in the prompt, Chutora asks once whether this kind may be automatic from now on; in bypass-permissions mode, in-project deletes still run but a restore point is saved first and you're told afterwards; when the guard asks about `git reset --hard` / `git clean`, the reason ends with `/chutora ok <id> auto`.
- **Notifications**: every automatic action goes into `changes.jsonl`; right away, PreToolUse `additionalContext` asks Claude to end its reply with one line; after that, each message you send makes UserPromptSubmit ask for one line again (several merged into one) until you respond; the status line shows "to confirm N". If you already agreed and the context is nearly identical (similarity ≥0.95), you're told only that once. Nothing is output when nothing is waiting.
- **Feedback**: `/chutora ok <id|all> auto` (got it, this kind may be automatic), `/chutora ok <id|all> ask` (got it, but ask me next time), `/chutora undo <id>` (restore from the restore point, recorded as strongly negative [weight 3], no automatic runs for similar contexts for 24 hours), `/chutora ok <id>` (just mark as seen, not used for learning), `/chutora changes` (list what's waiting). The `/chutora ok` / `undo` you type are handled directly by the UserPromptSubmit hook; Claude running `ok … auto` itself or editing `decisions.jsonl` is stopped by the guard as `self-grant` (blocked outright in bypass-permissions mode). Kinds on the always-ask list can never be learned as automatic.
- **Command line for the main conversation**: `decide.py score --type <kind> --options a,b [--claude a=0.7,b=0.3] [--path <paths>] [--remote] [--unattended]`, `record <id> <answer>`, `snapshot [--config] [--git] --summary <what> <paths>…`, `undo <id>`, `pending`, `stats`.
- **Records**: `claude-memory/decisions.jsonl` (without `claude-memory/`, next to `changes.jsonl` in the auto memory folder): decision type, options, context features, predicted probabilities, actual outcome, whether it was automatic, recoverability, Brier.
- **Instructions only when needed**: the delegation conventions no longer carry decision-engine text; a hook injects a short note only in these cases, and adds nothing otherwise:
  - Something automatic is waiting for you → UserPromptSubmit asks Claude to end its reply with one line (see "Notification").
  - You leave the decision to Claude ("you decide", "either is fine", "up to you", "your call", 「你決定」「都可以」「你幫我選」…) → UserPromptSubmit adds the short usage (`decide.py score` / `snapshot` / `record`).
  - Claude is about to ask you with AskUserQuestion → PreToolUse scores your past answers for the same question kind (header) in the same project; only when there are related records and one option stands out, it adds one line "based on your past picks, suggest X (confidence 0.xx)" and appends a note to that option's description so you see it in the dialog. No records, nothing added. Measured on Claude Code 2.1.319: PreToolUse fires before the dialog appears, but `additionalContext` only reaches Claude with the tool result after you answer, so the hook also uses `updatedInput` (without `permissionDecision`, the dialog still shows) to change the option's description; labels are left alone. PostToolUse records your answer in `decisions.jsonl` (typed-in answers and multi-select questions are skipped; with strict privacy only hashes are stored).
  - Nobody is present (scheduled or headless) → SessionStart adds "how to choose when nobody answers, and what not to do" (`hooks/unattended.en.md`). Checked in order: `CHUTORA_UNATTENDED=1` / `0` forces it; `CLAUDE_CODE_SESSION_ATTENDED`, which Claude Code passes to hooks (measured on 2.1.319: `0` under `claude -p`, `1` interactive; not in the official docs); on older versions without it, `CLAUDE_CODE_ENTRYPOINT=sdk-cli` or `CI` / `GITHUB_ACTIONS=true` count too. The SessionStart input has no `permission_mode` (measured), so the permission mode isn't used here; bypass-permissions handling stays in PreToolUse.
  - The guard lets a learned action through → the existing one-line PreToolUse notice.
- **Tokens**: in the normal case (interactive, nothing waiting, no decision handed over) nothing extra is injected, as in batch 1; measured (`claude -p`, Sonnet, `CHUTORA_UNATTENDED=0` to mimic interactive) 41,895 in English vs 42,184 before this change and 41,864 for batch 1 (the 29 extra come from the `/chutora` skill description now mentioning changes / ok / undo, which sits in the skill list). With one action waiting, each message adds about 240 tokens (Chinese). Sessions with nobody present, such as `claude -p`, also get the unattended note (about 200 tokens, not measured).
- **Switch**: `/chutora decide off` (saved to `~/.claude/chutora/decide`) or `CHUTORA_DECIDE=0` turns off only the automatic decisions; with the guard off the engine never runs automatically either.

---

<a name="details"></a>

## <img src="../assets/icons/branch.svg" width="26" height="26" alt=""> How it works in detail

### Why this saves money

**Routing happens after Opus, not before.** Judging intent requires reading the message, and reading it is already planning, so a cheap router in front is not possible. Opus is always the entry point and does the delegating.

The savings come from four places, in order of impact:

1. **Context isolation** (the biggest, and it compounds). Running 30 tool calls in the main conversation means paying for those 30 results until the conversation ends; in a subagent, the main conversation receives only a summary. Delegate whole chunks of work, not single steps, because each subagent launch pays the system prompt and memory injection again.
2. **Model tiering.** Useful but linear: the saving is roughly the price difference.
3. **`effort` levels.** worker uses `medium`, escalating to worker-hard (`high`) only on failure; librarian uses `low`.
4. **Do not keep the main conversation open too long.** Isolation only covers tool calls, not the conversation itself growing longer, so the plugin also watches length and reminds you to write a handoff note past a threshold (see [Advanced settings](#advanced)). Starting a new conversation or `/clear` when a topic ends is still the cheapest.

### When things fail

Subagents finish with a fixed report format so the main conversation can decide the next step from the first two lines: a status line (done, failed, or needs a decision) and a verification line (passed, not verified, or failed). Done is only allowed together with verification passed. If a subagent hits a fork that requires a decision, it stops and reports the options and their consequences instead of picking one itself.

Failure escalation order: re-delegate to the same agent with added background, then bulk failure falls back to worker, worker failure goes to worker-hard (with the previous failure report), and if that still fails it stops to re-plan or ask you. It never escalates endlessly.

---

<a name="advanced"></a>

## <img src="../assets/icons/wrench.svg" width="26" height="26" alt=""> Advanced settings

### Context reminders and auto-compact

- The UserPromptSubmit hook reminds you once when the context passes 100k tokens, then every additional 40k. Adjust the threshold with the environment variable `CONTEXT_REMIND_TOKENS`.
- On reminder, Claude writes the current state into `handoff.md` with the handoff skill (current task / done / next steps / open questions).
- If `autoCompactWindow` is set, the reminder just tells you auto-compact will happen at about N k and the handoff will be restored; otherwise it gives you a copyable command: `/clear` at a stopping point, `/compact` with a focus mid-task, or `/rewind` with a partial summary if the later part is debugging noise.
- The SessionStart hook injects `handoff.md` after every compact, `/clear` and startup: from `claude-memory/` if the project has it, otherwise from the auto memory directory next to the transcript (Claude Code only injects the MEMORY.md index of auto memory, never handoff.md).

Recommended: set auto-compact as a safety net in `~/.claude/settings.json` (a plugin cannot set it for you; `/chutora:route-setup` writes it safely):

```
"autoCompactWindow": 153000
```

After subtracting a buffer of about 33k, auto-compact triggers at roughly 120k, leaving about 20k of headroom after the 100k reminder to write the handoff. The 33k figure was measured on the author's machine (it is not known to be fixed); after writing the value, confirm with `/context` that the Autocompact buffer is about 33k and the compact point about 120k (and also check any per-model overrides in `modelSettings`).

### Status line (optional)

When idle it shows `model │ ctx 95k │ reminder 100k │ compact 120k`; while Claude works it shows the current action instead (the Flight Deck stable path): `▶ worker·Sonnet Run tests npm test · 12s │ session 42k tok │ trimmed≈8k │ ctx 95k/120k`. "session" is the tokens newly processed this session (input + cache writes + output, excluding cache reads, main plus subagents, summed exactly from the transcript); "trimmed≈" is the characters kept out by trimming, dedup and MCP trimming ÷4, an estimate. The current action is recorded by `activity.py` under `~/.claude/chutora/activity/` (`CHUTORA_ACTIVITY=0` turns it off); when space is short, later fields are dropped by importance (`CHUTORA_STATUS_WIDTH` sets the width). The compact point is read from `autoCompactWindow` (not shown if unset). A plugin cannot configure the main status line: plugin users should use `/chutora:route-setup`, which places the file in a fixed location; install.sh users can run `bash install.sh --with-statusline` or paste this into settings.json by hand:

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/chutora/statusline.py" }
```

### Subagent board and reply-mode switch (optional)

Two optional mods (Claude Code interface extensions; they need 2.1.299 or later and were tested by the author in the VS Code extension 2.1.301):

| mod | What it does |
|---|---|
| `agent-board` (Flight Deck panel) | A big "Now" card, segmented to-do progress, a three-colour workload bar with three stat cards (share handed to Sonnet/Haiku, tokens kept out by trimming, main context), an action timeline (plain words or raw commands, subagents indented, repeated actions merged, up to 40 entries), files touched (edited with +/− lines, read files expandable), and the subagent list (type, model, status, elapsed time, tokens, estimated cost). Graphic via Svg on desktop, VS Code and mobile; text and colour blocks in the terminal. Collapses to a one-line summary, toggles with `/agent-board`, and has plain/raw and "⇄ reply: concise/detailed" switches at the bottom. Tool calls are observed, never changed |
| `reply-detail` | Injects a reply format into the system prompt: by default a short three-part reply (current state / what you need to do / what you need to decide or provide), for the main conversation only. Switch the board's reply mode to detailed and every reply stays detailed until you switch back; for a one-off, type "詳細說明" to get a detailed rewrite of the previous reply |

Install: from the plugin marketplace, `/plugin install agent-board@chutora` and `/plugin install reply-detail@chutora`; with install.sh, add `--with-agent-board` and `--with-reply-detail` (VS Code cannot pass `--plugin-dir`, so the script adds the folders to `env.CLAUDE_CODE_PLUGIN_DIRS` in `settings.json`). Afterwards, run Developer: Reload Window in VS Code.

agent-board settings (plugin userConfig, all on by default): `autoOpen` opens the panel when a subagent starts, `persistent` opens it when the session starts and keeps it open, `detailButton` shows the reply-mode switch at the bottom (the name is kept from earlier versions). In detailed mode the board attaches a "write this turn in detail" request to every message you send; a reload resets it to concise.

Limits: a mod cannot add buttons to the VS Code prompt toolbar (the row with the model picker), so the switch lives in the board. They could also go under the reply or in the band above the prompt, but VS Code wraps those mod-drawn areas in a frame labeled "From the … plugin" (a mod cannot turn it off), so they are not used. Also, Claude Code applies a width threshold to panes the user did not open (144 columns if never opened by hand), which the VS Code chat panel often falls short of, leaving the pane invisible and "unplaced"; persistent mode checks and reopens it when a surface attaches, the width changes, and a turn starts or ends.

### Checking the fixed cost

To see what every turn pays up front (system prompt, tool definitions, MCP, skills, memory files), type `/context` in a conversation, or run `claude -p "/context"` in a terminal (no interactive session needed; it is computed locally and does not call the model). On the author's machine a fresh conversation starts at about 29k tokens, about 18k of which is Claude Code's own system prompt and tool definitions; tools marked deferred are loaded only when used and are not counted. Fixed content hits the prompt cache every turn, so it is rarely the main cost: deal with conversation length and output first, and only then consider removing unused MCP servers or plugins.

---

<a name="memory"></a>

## <img src="../assets/icons/brain.svg" width="26" height="26" alt=""> Memory

```
<your folder>/claude-memory/
├── MEMORY.md    ← resident index, injected by the hook at session start, 40-line budget
├── handoff.md   ← handoff note, injected automatically into the next session
├── topics/      ← knowledge accumulated by agents
├── kb/          ← your own notes
└── web/         ← external-info notes saved by research (with source and expiry date)
```

Without a `claude-memory/` folder, memory falls back to Claude Code's own auto memory, which works fine. `claude-memory/` is an advanced option; its advantage is that it can go into git and be shared across environments.

`MEMORY.md` **holds only trigger conditions; the knowledge itself lives in topic files.** This makes cost proportional to how much you use this time, not to how much is remembered in total: knowledge can grow without limit while the fixed startup cost stays constant. Write the index as conditions, not topics:

- Bad: `setup.md — about environment setup` (a topic)
- Good: `setup.md — read first when you need to change paths or a command will not run` (a condition)

Where memory lives:

- Agents prefer the `claude-memory/` folder inside a connected (working) folder, and fall back to their own agent memory directory (`~/.claude/agent-memory/worker/`) when it is missing.
- In Claude Code (terminal) the fallback persists across conversations. In Cowork the sandbox home directory is rebuilt every session, so only the connected folder survives: connect it again in each new conversation.
- If you disabled `autoMemoryEnabled` or set `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, the `memory` field has no effect, and connecting a folder becomes required rather than optional.
- The folder opens directly as an Obsidian vault with no integration needed, since a vault is just a pile of `.md` files. Use a new, dedicated vault rather than your existing personal notes, because agents have write access.
- Memory should record "how to do it next time", not "what was done this time". A running log does not make the next run faster.

Keeping `MEMORY.md` thin matters: it is truncated beyond its limit (the hook injects up to 120 lines; auto memory 200), and resident content is a fixed cost paid in every session. It decays over time, so tidy it periodically; more than 150 lines is the warning sign.

### Change log and memory identity (experimental)

**Change log** `claude-memory/changes.jsonl` (the auto memory folder when there is no claude-memory): one JSON object per line, append-only. Fields: `id`, `ts`, `action` (an action code such as `guard_ask`), `summary` (masked and shortened), `restore_point` (where to restore from, such as a backup file or a git commit; `null` when there is none), `notified` (whether you were told), `user_response` (`null`, `approved`, `rejected`, `undone`…), `source`, `session`. Later updates append a line `{"id": …, "update": {…}}`, merged when read. The danger guard and the decision engine write to it (the engine adds the actions `auto_allow` / `unattended_run` / `approved_run` / `auto_cli` / `decision_todo`, the fields `category`, `ran`, `quiet`, and the `user_response` values `ok_auto`, `ok_ask`, `ack`); the module is `hooks/changes.py` (`python3 changes.py list` shows the latest entries), for later features that change settings to record what changed, how to undo it and how you responded.

**Memory identity**: newly written memory files can start with a YAML block (module `hooks/memmeta.py`):

```yaml
---
id: mem-20261107-a1b2c3
created: 2026-11-07T10:00:00+0800
last_used: 2026-11-07T10:00:00+0800
confidence: 0.7        # 0 to 1: 0.9+ when you said it yourself, around 0.5 when inferred
source: user           # user / observed / handoff / research / inferred / imported
bound_files:           # files this memory relies on, with content fingerprints (first 12 chars of sha256)
  - path: src/app.py
    sha: 3f2a9c0d11ee
version: 1
supersedes: null       # id of the older memory this one replaces
status: active         # active / stale / superseded / archived
---
```

- The `bound_files` fingerprints let a later check notice that a file the memory relies on has changed (`memmeta.py check <file>`).
- **Existing memory files are never rewritten**; `memmeta.py new` only creates new files and refuses when the file exists. Other front-matter fields in old files (such as auto memory's `name`, `description`, `type`) are kept as they are.
- This batch only provides the format and the tool; nothing writes memory automatically yet.

### Knowledge base and harvester

You can feed the knowledge base in two ways: drop `.md` files into `kb/` yourself (no preprocessing, librarian finds them immediately), or ask `harvester` to mine past conversations (it lists the available sessions and lets you choose the scope first). Four limits to know:

- It only sees local sessions; conversations on the web or mobile are out of scope.
- It is costly, so treat it as an occasional batch job, not an always-on feature.
- Extraction is always lossy: spot-check the output, especially the first few runs.
- It writes into `kb/`, which is otherwise yours. If you care about that boundary, have it write to `kb/harvested/` first.

Run it once after first install to seed the knowledge base; after that worker records memory as it goes, so it is rarely needed again.

---

<a name="tradeoffs"></a>

## <img src="../assets/icons/scale.svg" width="26" height="26" alt=""> Design trade-offs

### This is RAG, just without vectors

`librarian` retrieves using keyword search and conditional judgment. At personal scale (dozens to hundreds of notes) this is usually better than vectors: no extra infrastructure, retrieval failures are explainable, and chunking does not break Markdown structure. It also swaps synonyms, switches languages, and retries by searching file names, which a fixed vector query cannot do.

Vectors are worth considering only for thousands of notes, large numbers of PDFs, or long transcripts. At that point the markdown in `kb/` can serve directly as the corpus.

### When to add a Haiku execution layer

`skills/route-setup/templates/runner.md.example` is a reserved slot that is **deliberately not loaded**. The Haiku layer is the only layer that really saves money and the only one that is really risky: it does not stop to ask, it quietly does what it thinks you meant. So each Haiku agent must be bound to one concrete task.

Enable one only when all three hold:

- You have done the task three to five times with nearly the same steps.
- Success is obvious at a glance.
- Mistakes are affordable and reversible (nothing deleted, sent out, or overwritten without a backup).

Otherwise leave it with worker. Retrieval (librarian) is the exception, because it is read-only.

---

<a name="install"></a>

## <img src="../assets/icons/box.svg" width="26" height="26" alt=""> Other ways to install

If you prefer not to use the marketplace, the repo ships `install.sh`, or you can run `claude --plugin-dir ./plugins/chutora` directly.

```
bash install.sh                    # copy install (agents, skills, hooks go into ~/.claude/, no namespace prefix; re-run to update)
bash install.sh --agents-only      # copy agents only (hooks and skills will not take effect)
bash install.sh --link             # symlink agents, skills, hooks (edits in the repo apply immediately)
bash install.sh --uninstall        # remove (follows the install manifest, leaves your own files alone)
bash install.sh --with-explore     # also install the Haiku-based Explore into ~/.claude/agents/
bash install.sh --with-statusline  # also add the context status line to ~/.claude/settings.json
bash install.sh --with-agent-board   # also load the subagent board mod (written to env.CLAUDE_CODE_PLUGIN_DIRS in settings.json)
bash install.sh --with-reply-detail  # also load the reply format mod (same mechanism)
```

Notes:

- Names have no namespace in this mode: the agent is `worker` and the skill is `/handoff` (plugin install uses `chutora:worker`).
- Installed items are recorded in `~/.claude/.chutora-installed`. Existing files with identical content are added to the manifest; files with different content (yours) are not overwritten, and you get a warning.
- `--with-statusline` can be combined with the default copy mode or `--link`, but not with `--agents-only` or `--uninstall`. It touches only the `statusLine` key in `settings.json`: it creates the file if missing, never overwrites an existing `statusLine` (it only prints a suggested snippet), and otherwise backs the file up as `settings.json.bak-<timestamp>` before writing. It does nothing if the JSON is broken or python3 is missing.
- `--with-agent-board` and `--with-reply-detail` have the same restrictions as `--with-statusline` and can be used together. They touch only `env.CLAUDE_CODE_PLUGIN_DIRS`: existing paths are kept and the file is backed up before writing; `--uninstall` removes only the paths they added.
- install.sh does not edit your `settings.json` hooks. It prints a snippet at the end that you merge into `"hooks"` yourself. After that, run `/route-setup` for the full feature set.

For more detail, see the [deployment notes](%E9%83%A8%E7%BD%B2%E5%AE%89%E8%A3%9D.md) (Traditional Chinese only) and [plugins/chutora/INSTALL.en.md](../plugins/chutora/INSTALL.en.md).

---

<a name="layout"></a>

## <img src="../assets/icons/folder.svg" width="26" height="26" alt=""> Layout

```
chutora/
├── .claude-plugin/marketplace.json   ← marketplace catalog
├── plugins/chutora/            ← the plugin itself
│   ├── .claude-plugin/plugin.json
│   ├── agents/                       ← worker / worker-hard / bulk / librarian / harvester / security-review / security-test
│   ├── skills/                       ← handoff / research / usage-stats / route-setup / evidence-analysis / security-review / security-test / toolprune / harness-tune / chutora-hub
│   ├── hooks/                        ← SessionStart injection, context-length reminder, loop guard, modes/ (three modes), weekly.py (weekly recap), trim.py (noisy-output trimming), dedup.py (read dedup), mcptrim.py (MCP output trimming), ask.py (clarify reminder), guard.py (danger guard), observe.py (observation log), decide.py (decision engine), changes.py (change log), memmeta.py (memory identity), projectid.py, redact.py
│   (templates are in skills/route-setup/templates/: MEMORY.md, knowledge-base guide, Explore, Haiku-layer example)
├── plugins/agent-board/              ← subagent board mod (optional)
├── plugins/reply-detail/             ← reply format mod (optional)
├── bench/                            ← token benchmark: run.py, tasks.json, fixtures/
├── docs/
│   ├── spec.md                       ← architecture design and implementation appendix (Traditional Chinese)
│   └── ...                           ← deployment and publishing notes (Traditional Chinese only)
├── claude-memory/                    ← memory store (not under version control)
└── install.sh                        ← install method that skips the marketplace
```
