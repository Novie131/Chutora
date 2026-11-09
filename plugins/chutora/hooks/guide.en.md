# chutora: delegation conventions for this session (injected by a hook at session start)

The main conversation understands, plans, decides and reviews; hands-on work and heavy reading happen in a subagent's own context, and only the conclusion comes back. Every tool output left in the main conversation is billed again on every later turn until the conversation ends — that is the main reason to delegate.

| Work | Hand it to |
|---|---|
| Implementation once the direction is settled: writing or changing code, fixing bugs, adding tests | `worker` |
| Escalation after worker fails (attach the previous failure report) | `worker-hard` |
| Heavy reading where only the conclusion matters: many images or frames, long logs, fetching web pages, commands with lots of output | `bulk` |
| "What did we note before": memories, notes and external-source notes in claude-memory/ or auto memory | `librarian` |
| Searching code, finding files or usages | `Explore` |
| External docs, APIs, version differences; answers need sources | `/research` |
| Mining past conversations into the knowledge base (only when the user explicitly asks) | `harvester` |
| Investigations that must separate fact from guess, root-causing, reviewing conclusions; answers split into observation / inference / unknown with sources | `/evidence-analysis` |
| Static security review of the user's own code (OWASP, evidence and fixes, severity) | `security-review` |
| Dynamic security testing of the user's own, authorized, isolated dev environment (confirm the scope first) | `security-test` |
| Which tools / MCP servers have gone unused and could be turned off to save tokens | `/toolprune` |
| Making this harness better at a recurring kind of task (confirm before changing, reversible) | `/harness-tune` |
| A big task that is vague (touches several files, unclear scope, several possible approaches), or the user asks you to ask first or says they are not sure | Clarify first (main conversation, AskUserQuestion; see "Clarify" below) |
| The user wants the current status, doesn't know what's available, wants an install check, or wants to switch mode or language | `/chutora` (`/chutora doctor`, `/chutora mode`, `/chutora lang`, `/chutora ask`) |

When installed as a plugin, the names above are prefixed with `chutora:` (for example `chutora:worker`, `/chutora:research`).

- Security boundary: `security-review` / `security-test` are only for code and environments the user owns or is explicitly authorized to test; dynamic testing only in isolated environments, never production, never sending data out, and always confirm the scope first.

- Delegate a complete piece of work, not a single step; every subagent start pays for the system prompt again. Small, well-defined things are cheaper done directly in the main conversation.
- Send implementation to `worker`, not general-purpose: general-purpose inherits the main conversation's model (usually Opus); in one measurement 408 implementation runs ended up on Opus.
- Subagents can't see this conversation, so the delegation message must be self-contained: goal, file paths, constraints, return format.
- Spot-check the evidence a subagent attaches before adopting its conclusion; conclusions like "none" or "not found" have no evidence to check, so search again in the main conversation before passing them on.
- The first two lines of a worker, worker-hard or bulk report are always `狀態：完成｜失敗｜需要決策` (status: done | failed | needs decision) and `驗證：通過｜未驗證｜失敗` (verification: passed | not verified | failed). Decide the next step from those two lines instead of reading the whole report first:
  - done + passed → spot-check the evidence, then adopt
  - done but verification not passed, or the first two lines are malformed → treat as failed
  - failed → follow the escalation chain below
  - needs decision → don't escalate; the main conversation decides, or asks the user if it can't
- Escalation order: re-dispatch the same agent with more context → if bulk fails, use worker → if worker fails, use worker-hard (with the failure report) → if it still fails, stop and re-plan or ask the user; never escalate further.
- Done means an executable verification (tests, lint, actually running it); "looks done" doesn't count.
- Keep extracting: whenever a decision is made, a subtask is finished or a key fact is found, update the handoff right away instead of waiting until the conversation gets long.
- micro-skills: fixed facts about how this repo runs (how tests are invoked, which command is the right one, which environment variables matter, where outputs go) — once confirmed, record them in the "command facts" section of `claude-memory/` MEMORY.md so later sessions don't rediscover them.
- Clarify: only the main conversation asks; subagents never do. Don't ask about small or already-clear tasks. When you ask, use AskUserQuestion with at most the number of questions the mode allows (economy 3, balanced 4, quality 5), only about what would change the result: scope (in / out), what counts as done, constraints (what must not change), edge cases, trade-offs (fast vs complete). Put the recommended option first and offer "use the defaults, stop asking". Write the answers into a short brief, `claude-memory/briefs/<date>-<slug>.md` (or `briefs/` in the auto memory folder), mark "what counts as done" as the acceptance criteria, and attach it when delegating to worker.
- Read dedup and MCP trimming: a "Chutora dedup" note means this conversation already read that unchanged range, so use the earlier result; a "Chutora MCP trim" note gives the path of the full original, which you can Read when you need what was omitted.
- loop guard: the PostToolUse hook detects the same error repeating and injects a nudge to change direction; when you see one, seriously consider a different path, stepping back or reporting to the user instead of retrying the same way.
- If the project has `claude-memory/`, its memory index is attached below, plus `handoff.md` if present — that is the progress left by the previous conversation. Without `claude-memory/`, memory lives in auto memory (Claude Code loads its MEMORY.md itself; handoff.md is loaded by this hook).
