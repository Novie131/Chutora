# Smart Agent Route

<p align="center"><a href="README.md"><b>繁體中文</b></a> · <b>English</b></p>

**Make Claude Code work like a small team: Opus is the lead who thinks, Sonnet and Haiku do the hands-on work. When the conversation gets long, it writes a handoff note first, then picks up from the note after the conversation is cleared.**

The Traditional Chinese docs are the primary version; this English version is a translation and may lag behind.

**Goal**: get more done on the same budget, without long working sessions getting more expensive and messier as the conversation grows.

**Why use it**

- **The expensive model only where it counts**: Opus only thinks and decides; writing code goes to Sonnet, and reading logs, looking at screenshots, and searching go to Haiku.
- **Long conversations stay under control**: past 100k tokens of context you get a reminder and a handoff note is written first; after a compact, a `/clear`, or a new conversation the next day, your progress comes back automatically.
- **Works right after install**: two commands, no changes to your CLAUDE.md. Advanced setup asks one item at a time and backs up your settings before changing them.
- **Verifies its work, stops at forks**: subagents must verify before reporting done; when a decision is needed, they list the options for you instead of choosing on their own. Failures follow a fixed escalation order, with no endless retries.
- **Memory that accumulates across conversations**: memory is plain Markdown files you can put in git or open in Obsidian; external information is saved with its source.
- **Measurable**: `usage-stats` measures main-conversation context length, how many tokens each agent used, and an estimated cost at API list prices, and can write an HTML report with daily charts.
- **See what subagents are doing** (optional): the `agent-board` panel stays above the prompt and shows each subagent's type, model, status, elapsed time, tokens, and estimated cost as it runs.
- **Replies you can read at a glance** (optional): `reply-detail` makes replies lead with the current state, what you need to do, and what you need to decide; switch the board's reply mode ("⇄ 回覆：精簡／詳細") to detailed when you want full replies.

---

## What problem this solves

After using Claude Code for a while, two things tend to happen:

- **It gets expensive**: the main conversation's Opus does everything itself, including reading long logs, looking through piles of screenshots, and editing dozens of files. Most of that work is fine on a cheaper model.
- **Conversations keep growing**: every message and every file read is sent to the model again on every later turn. Late in a long conversation, most of what you pay for is re-reading old content. Measured on one heavy user across 21 sessions, the median context per main-conversation call was about 240k tokens.

This plugin works like a lead running a team: the lead (Opus) listens, thinks it through, and decides who gets the work; the hands-on work goes to team members (Sonnet, Haiku), who finish it at their own desks and hand back only the conclusion, so the lead's desk stays clean. When the desk is nearly full, the lead writes a handoff note, clears the desk, and continues from the note.

**Good fit**: you already use Claude Code for multi-step work (changing code, reading logs, looking things up) and want to save money or keep long conversations under control. If you only ask the occasional one-off question, the benefit of delegation is small.

---

## Quick start

Inside Claude Code, run:

```
/plugin install smart-agent-route --marketplace Novie131/smart-agent-route
/reload-plugins
```

(Claude Code 2.1.275 and earlier: first run `/plugin marketplace add Novie131/smart-agent-route`, then `/plugin install smart-agent-route@smart-agent-route`.)

It works right after install. Two things are recommended next:

1. **Set the main conversation to Opus**: `/model opus`. The plugin never changes this automatically.
2. **Turn on the full feature set**: run `/smart-agent-route:route-setup` to set up the context status line, the auto-compact threshold, the Haiku-based Explore, and a `claude-memory/` store. It asks one item at a time, explains what each does, its impact, and how to undo it, and you can skip any of them. It backs up `settings.json` before writing and never overwrites values that already exist. If you skip it, the session start hook reminds you (at most 3 times).

The context-length reminder needs `python3`; without it, the reminder hook quietly disables itself. To install without the marketplace, see [Other ways to install](#other-ways-to-install).

---

## Using it

Just talk normally; the main conversation decides whether to delegate:

| You say | Who handles it |
|---|---|
| "Help me think through how to do this" | The main conversation (Opus) thinks it through itself |
| "Do what we just discussed" | worker (Sonnet) does it, verifying before reporting back |
| "Check these 18 screenshots for layout breakage", "Why did this log fail" | bulk (Haiku) reads it all and returns only the conclusion |
| "Did I note anything about X before?" | librarian (Haiku) searches memory and cites where it found things |
| "How do I configure the new version of this API" | The research skill looks it up and cites sources; official material is saved to `claude-memory/web/` |
| "Hand off" | The handoff skill writes `handoff.md`, after which you can `/clear` |

To force a specific agent, use `@agent-smart-agent-route:worker`.

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

## How it works

```
You ──► main conversation (Opus)  ← the front door: understands, decides who gets the work
          │
          ├──► worker (Sonnet)       ← direction is settled, just do it
          │      └► worker-hard       ← escalation after worker fails
          ├──► bulk (Haiku)          ← lots to read, only conclusions needed: images, long logs, web pages
          ├──► librarian (Haiku)     ← searches the knowledge base. Read-only
          ├──► harvester (Sonnet)    ← mines past conversations into the knowledge base. Manual trigger
          ├──► security-review (Sonnet) ← static security review of your own code. Read-only
          └──► security-test (Sonnet)   ← authorized dynamic testing of your own dev environment

skill: handoff (handoff notes), research (look up external info with sources), usage-stats (measure context and subagent usage), route-setup (one-time full setup), evidence-analysis (evidence-based analysis), toolprune (tool pruning), harness-tune (self-improvement)
hook : session start injects the delegation guide and memory; a reminder fires when the context gets long; after each tool call it watches for repeated errors and nudges you to change course (loop guard)
```

| Component | Model | What it does |
|---|---|---|
| worker | Sonnet, effort medium | Work whose direction is already decided: writing code, fixing bugs, adding tests. It must verify before reporting done |
| worker-hard | Sonnet, effort high | Only used after worker fails; the delegation must include the previous failure report |
| bulk | Haiku | Reads large amounts of material and returns only conclusions: many images, long logs, web pages, commands with huge output, and mechanical batch edits |
| librarian | Haiku, effort low | Searches the knowledge base and memory. It has only `Read`, `Glob`, and `Grep`, so it cannot modify anything; it returns verbatim excerpts with their sources, plus which terms it searched and what it did not find |
| harvester | Sonnet | Mines past conversation transcripts into knowledge-base notes. Only runs when you explicitly ask; it is costly |
| security-review | Sonnet, effort medium | Static security review of your own code (OWASP categories, evidence and remediation, severity). Read-only; only for code you own or are authorized to test |
| security-test | Sonnet, effort medium | Dynamic security testing against your own, authorized, isolated dev environment to confirm whether findings are exploitable. Confirms the authorization scope first, never touches production, never exfiltrates data |
| Explore (optional) | Haiku | The built-in Explore runs on Opus when the main conversation is Opus. A plugin cannot override it (only a user- or project-level agent named `Explore` can), so route-setup or `bash install.sh --with-explore` installs a Haiku version into `~/.claude/agents/` |

- **Skills**: `handoff` writes `handoff.md`; `research` looks up external information and cites sources; `usage-stats` measures main-conversation context length and, per agent, dispatch counts, token usage, and estimated cost (read-only; add `--html` for a report with charts); `route-setup` is the one-time full setup.
- **Hooks**: SessionStart injects the delegation guide, the memory index, and the handoff note; UserPromptSubmit reminds you when the context window is too long.
- **Analysis & security**: `evidence-analysis` (separates observation / inference / unknown and cites sources); `security-review` / `security-test` (defensive security: static review plus authorized dynamic testing). The security capabilities apply only to your own or explicitly authorized code and environments; dynamic testing runs only in an isolated environment, never touches production, and never exfiltrates data.
- **Saving tokens & self-improvement**: `toolprune` (flags long-unused tools and suggests disabling them, reversibly); `harness-tune` (adjusts the harness for a recurring task type, confirmed before changing and roll-back-able, from harness2); a PostToolUse `loop guard` hook (nudges you to change course when the same error repeats, nudge-only, never interrupts, from TokenEconomizer); micro-skills (records this repo's fixed command facts into memory).

How the main conversation delegates does not depend on your CLAUDE.md: the SessionStart hook injects the delegation table at the start of every session (see `hooks/guide.md`). Design rationale and trade-offs are in [docs/spec.md](docs/spec.md) (Traditional Chinese).

### Why this saves money

**Routing happens after Opus, not before.** Judging intent requires reading the message, and reading it is already planning, so a cheap router in front is not possible. Opus is always the entry point and does the delegating.

The savings come from four places, in order of impact:

1. **Context isolation** (the biggest, and it compounds). Running 30 tool calls in the main conversation means paying for those 30 results until the conversation ends; in a subagent, the main conversation receives only a summary. Delegate whole chunks of work, not single steps, because each subagent launch pays the system prompt and memory injection again.
2. **Model tiering.** Useful but linear: the saving is roughly the price difference.
3. **`effort` levels.** worker uses `medium`, escalating to worker-hard (`high`) only on failure; librarian uses `low`.
4. **Do not keep the main conversation open too long.** Isolation only covers tool calls, not the conversation itself growing longer, so the plugin also watches length and reminds you to write a handoff note past a threshold (see [Advanced settings](#advanced-settings)). Starting a new conversation or `/clear` when a topic ends is still the cheapest.

### When things fail

Subagents finish with a fixed report format so the main conversation can decide the next step from the first two lines: a status line (done, failed, or needs a decision) and a verification line (passed, not verified, or failed). Done is only allowed together with verification passed. If a subagent hits a fork that requires a decision, it stops and reports the options and their consequences instead of picking one itself.

Failure escalation order: re-delegate to the same agent with added background, then bulk failure falls back to worker, worker failure goes to worker-hard (with the previous failure report), and if that still fails it stops to re-plan or ask you. It never escalates endlessly.

---

## Advanced settings

### Context reminders and auto-compact

- The UserPromptSubmit hook reminds you once when the context passes 100k tokens, then every additional 40k. Adjust the threshold with the environment variable `CONTEXT_REMIND_TOKENS`.
- On reminder, Claude writes the current state into `handoff.md` with the handoff skill (current task / done / next steps / open questions).
- If `autoCompactWindow` is set, the reminder just tells you auto-compact will happen at about N k and the handoff will be restored; otherwise it gives you a copyable command: `/clear` at a stopping point, `/compact` with a focus mid-task, or `/rewind` with a partial summary if the later part is debugging noise.
- The SessionStart hook injects `handoff.md` after every compact, `/clear` and startup: from `claude-memory/` if the project has it, otherwise from the auto memory directory next to the transcript (Claude Code only injects the MEMORY.md index of auto memory, never handoff.md).

Recommended: set auto-compact as a safety net in `~/.claude/settings.json` (a plugin cannot set it for you; `/smart-agent-route:route-setup` writes it safely):

```
"autoCompactWindow": 153000
```

After subtracting a buffer of about 33k, auto-compact triggers at roughly 120k, leaving about 20k of headroom after the 100k reminder to write the handoff. The 33k figure was measured on the author's machine (it is not known to be fixed); after writing the value, confirm with `/context` that the Autocompact buffer is about 33k and the compact point about 120k (and also check any per-model overrides in `modelSettings`).

### Status line (optional)

Shows `model │ ctx 95k │ reminder 100k │ compact 120k`, with the compact point read from `autoCompactWindow` (not shown if unset). A plugin cannot configure the main status line: plugin users should use `/smart-agent-route:route-setup`, which places the file in a fixed location; install.sh users can run `bash install.sh --with-statusline` or paste this into settings.json by hand:

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/smart-agent-route/statusline.py" }
```

### Subagent board and reply-mode switch (optional)

Two optional mods (Claude Code interface extensions; they need 2.1.299 or later and were tested by the author in the VS Code extension 2.1.301):

| mod | What it does |
|---|---|
| `agent-board` | A persistent panel listing each subagent's type, model, status, elapsed time, tokens, and estimated cost (API list prices), with totals at the top. It collapses to a one-line summary and toggles with `/agent-board`; a reply-mode switch ("⇄ 回覆：精簡／詳細", concise/detailed) sits at the bottom |
| `reply-detail` | Injects a reply format into the system prompt: by default a short three-part reply (current state / what you need to do / what you need to decide or provide), for the main conversation only. Switch the board's reply mode to detailed and every reply stays detailed until you switch back; for a one-off, type "詳細說明" to get a detailed rewrite of the previous reply |

Install: from the plugin marketplace, `/plugin install agent-board@smart-agent-route` and `/plugin install reply-detail@smart-agent-route`; with install.sh, add `--with-agent-board` and `--with-reply-detail` (VS Code cannot pass `--plugin-dir`, so the script adds the folders to `env.CLAUDE_CODE_PLUGIN_DIRS` in `settings.json`). Afterwards, run Developer: Reload Window in VS Code.

agent-board settings (plugin userConfig, all on by default): `autoOpen` opens the panel when a subagent starts, `persistent` opens it when the session starts and keeps it open, `detailButton` shows the reply-mode switch at the bottom (the name is kept from earlier versions). In detailed mode the board attaches a "write this turn in detail" request to every message you send; a reload resets it to concise.

Limits: a mod cannot add buttons to the VS Code prompt toolbar (the row with the model picker), so the switch lives in the board. They could also go under the reply or in the band above the prompt, but VS Code wraps those mod-drawn areas in a frame labeled "From the … plugin" (a mod cannot turn it off), so they are not used. Also, Claude Code applies a width threshold to panes the user did not open (144 columns if never opened by hand), which the VS Code chat panel often falls short of, leaving the pane invisible and "unplaced"; persistent mode checks and reopens it when a surface attaches, the width changes, and a turn starts or ends.

### Checking the fixed cost

To see what every turn pays up front (system prompt, tool definitions, MCP, skills, memory files), type `/context` in a conversation, or run `claude -p "/context"` in a terminal (no interactive session needed; it is computed locally and does not call the model). On the author's machine a fresh conversation starts at about 29k tokens, about 18k of which is Claude Code's own system prompt and tool definitions; tools marked deferred are loaded only when used and are not counted. Fixed content hits the prompt cache every turn, so it is rarely the main cost: deal with conversation length and output first, and only then consider removing unused MCP servers or plugins.

---

## Memory

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

## Design trade-offs

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

## Other ways to install

If you prefer not to use the marketplace, the repo ships `install.sh`, or you can run `claude --plugin-dir ./plugins/smart-agent-route` directly.

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

- Names have no namespace in this mode: the agent is `worker` and the skill is `/handoff` (plugin install uses `smart-agent-route:worker`).
- Installed items are recorded in `~/.claude/.smart-agent-route-installed`. Existing files with identical content are added to the manifest; files with different content (yours) are not overwritten, and you get a warning.
- `--with-statusline` can be combined with the default copy mode or `--link`, but not with `--agents-only` or `--uninstall`. It touches only the `statusLine` key in `settings.json`: it creates the file if missing, never overwrites an existing `statusLine` (it only prints a suggested snippet), and otherwise backs the file up as `settings.json.bak-<timestamp>` before writing. It does nothing if the JSON is broken or python3 is missing.
- `--with-agent-board` and `--with-reply-detail` have the same restrictions as `--with-statusline` and can be used together. They touch only `env.CLAUDE_CODE_PLUGIN_DIRS`: existing paths are kept and the file is backed up before writing; `--uninstall` removes only the paths they added.
- install.sh does not edit your `settings.json` hooks. It prints a snippet at the end that you merge into `"hooks"` yourself. After that, run `/route-setup` for the full feature set.

For more detail, see the [deployment notes](docs/%E9%83%A8%E7%BD%B2%E5%AE%89%E8%A3%9D.md) (Traditional Chinese only) and [plugins/smart-agent-route/INSTALL.en.md](plugins/smart-agent-route/INSTALL.en.md).

---

## Layout

```
smart-agent-route/
├── .claude-plugin/marketplace.json   ← marketplace catalog
├── plugins/smart-agent-route/            ← the plugin itself
│   ├── .claude-plugin/plugin.json
│   ├── agents/                       ← worker / worker-hard / bulk / librarian / harvester / security-review / security-test
│   ├── skills/                       ← handoff / research / usage-stats / route-setup / evidence-analysis / security-review / security-test / toolprune / harness-tune
│   ├── hooks/                        ← SessionStart injection, context-length reminder
│   (templates are in skills/route-setup/templates/: MEMORY.md, knowledge-base guide, Explore, Haiku-layer example)
├── plugins/agent-board/              ← subagent board mod (optional)
├── plugins/reply-detail/             ← reply format mod (optional)
├── docs/
│   ├── spec.md                       ← architecture design and implementation appendix (Traditional Chinese)
│   └── ...                           ← deployment and publishing notes (Traditional Chinese only)
├── claude-memory/                    ← memory store (not under version control)
└── install.sh                        ← install method that skips the marketplace
```

---

## Status

**v0.10.0, early version.** Versions up to 0.7.0 were named tiered-agents; to upgrade, remove the old version first (see the section on upgrading from tiered-agents (0.7.0 and earlier) in the [deployment notes](docs/%E9%83%A8%E7%BD%B2%E5%AE%89%E8%A3%9D.md)). The context reminder hook, handoff, bulk, and the Explore override were ported from the author's personal setup: the hook has fired in real conversations and Explore and bulk are confirmed to run on Haiku, but all are still being validated. The worker-hard escalation chain, the research skill, and the plugin form of the hooks have not been used in practice yet. agent-board and reply-detail have been tested in the VS Code extension 2.1.301 for the board; persistent mode, the button in the board, and the reply-format injection are still being validated.

Known rough edges:

- Delegation relies on `description` matching and is not guaranteed. To be sure, use `@agent-smart-agent-route:worker`.
- Hook behavior in Cowork is unverified.
- `MEMORY.md` decays and needs periodic tidying (over 150 lines is the signal).
- The Haiku execution layer is empty by default; see the enabling conditions in `plugins/smart-agent-route/skills/route-setup/templates/runner.md.example`.
- `harvester` only reads local sessions.
- The mod API is marked early access; Claude Code updates may require adjustments.

Issues are welcome.

---

## License

MIT
