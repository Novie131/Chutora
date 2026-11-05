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

A mode changes exactly one thing: the delegation conventions injected into the main conversation at session start. Each agent's model and effort live in its agent file, and a plugin can't change them per mode, so switching modes never moves worker to a different model. The actual effect depends on how closely Claude follows the conventions.

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

Shows `model │ ctx 95k │ reminder 100k │ compact 120k`, with the compact point read from `autoCompactWindow` (not shown if unset). A plugin cannot configure the main status line: plugin users should use `/chutora:route-setup`, which places the file in a fixed location; install.sh users can run `bash install.sh --with-statusline` or paste this into settings.json by hand:

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/chutora/statusline.py" }
```

### Subagent board and reply-mode switch (optional)

Two optional mods (Claude Code interface extensions; they need 2.1.299 or later and were tested by the author in the VS Code extension 2.1.301):

| mod | What it does |
|---|---|
| `agent-board` | A persistent panel listing each subagent's type, model, status, elapsed time, tokens, and estimated cost (API list prices), with totals at the top. It collapses to a one-line summary and toggles with `/agent-board`; a reply-mode switch ("⇄ 回覆：精簡／詳細", concise/detailed) sits at the bottom |
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
│   ├── hooks/                        ← SessionStart injection, context-length reminder, loop guard, modes/ (three modes), weekly.py (weekly recap), trim.py (noisy-output trimming)
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
