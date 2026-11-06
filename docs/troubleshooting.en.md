# Troubleshooting

<p><a href="../README.en.md">← Back to README</a> · <a href="troubleshooting.md">繁體中文</a></p>

When something's off, run **`/chutora doctor`** first. It's read-only and lists each item as OK / optional / FIX, with a fix for anything that needs one. Common cases:

### Nothing happens after installing

1. Run `/reload-plugins`; in VS Code run Developer: Reload Window; in the terminal restart `claude`.
2. Run `/chutora doctor` and look at the hooks line.
3. On macOS the hooks need a working `python3`. Without the Command Line Tools, `/usr/bin/python3` is only a stub that pops up an installer, so Chutora quietly skips the reminder features. Run `xcode-select --install`, then restart.

### Messages are in the wrong language

Run `/chutora lang en` (or `zh`). To follow the system locale again: `/chutora lang auto`.

### Long conversation but no context reminder

- The threshold defaults to 100k tokens; adjust it with the `CONTEXT_REMIND_TOKENS` environment variable.
- The check runs when you send your next message, and reminds once per step (then again every additional 40k).
- It needs `python3`; if the "hook activity" line in `/chutora doctor` stays empty, the hooks aren't running.

### No status line

A plugin can't set the main status line by itself. Plugin installs: run `/chutora:route-setup`; install.sh installs: `bash install.sh --with-statusline`.

### The status line does not show the current action

First check the status line itself appears (previous section). For plugin installs the status-line files live in `~/.claude/chutora/statusline/`, and the new `deck.py` is synced there the next time a session starts; install.sh users need to merge the hooks snippet it prints again (it now includes `activity.py` for PreToolUse, PostToolUseFailure, SubagentStart and SubagentStop) into `settings.json`. `/chutora doctor` checks this. `CHUTORA_ACTIVITY=0` turns it off.

### Every agent shows up twice

An old version is still installed: `smart-agent-route` (0.10.0 and earlier) or `tiered-agents` (0.7.0 and earlier). `/chutora doctor` lists the leftovers; remove them as described in the upgrade section of the [deployment notes](%E9%83%A8%E7%BD%B2%E5%AE%89%E8%A3%9D.md) (Chinese).

### Subagents run on Opus and nothing is saved

- Send implementation to `worker`, not general-purpose (which inherits the main conversation's model).
- The built-in Explore runs on Opus along with the main conversation; install the Haiku version with `/chutora:route-setup`.
- The "agent type" table in `/chutora:usage-stats` shows which model each kind of agent actually ran on.

### Loop guard does nothing after an install.sh install

Before 0.12.0, the hooks snippet printed by install.sh was missing PostToolUse. Re-run `bash install.sh` and merge the new snippet into `~/.claude/settings.json`. `/chutora doctor` checks this.

### Loop guard is too sensitive or not sensitive enough

Set `LOOP_GUARD_REPEAT` to how many repeats of the same error trigger a nudge (default 3).

### I don't want the weekly recap

Add `"CHUTORA_WEEKLY": "0"` to `"env"` in `~/.claude/settings.json`.

### After trimming, Claude is missing something from a command's output

The last line of the trim note names the original's path; ask Claude to Read that file. If it happens often, switch to quality mode (`/chutora mode quality`, higher threshold, keeps more) or turn trimming off with `/chutora trim off`.

### Checking that noisy-output trimming works

Type `/chutora`: the status shows whether it is on and how many tokens it has trimmed (estimate). With an install.sh install, `/chutora doctor` checks that settings.json has the `trim.py` PostToolUse hook; if not, re-run `bash install.sh` and merge the hooks snippet it prints.

### Claude says the content is the same as before, but it needs to look again

That's read dedup. It only steps in when the earlier result is still in the conversation and the file hasn't changed; if Claude needs to look again (for example it skimmed past part of it), ask it to read a different range, or turn it off with `/chutora dedup off`.

### Clarify asks too much or too little

The number of questions follows the mode: economy 3, balanced 4, quality 5 (`/chutora mode`). Too many: say "stop asking, use the defaults", or `/chutora ask off`. Too few: say "ask me first" or type `/chutora ask`.

### An MCP tool's trimmed output is missing something

The last line of the output has the original's path, so ask Claude to Read it; if it keeps happening, `/chutora mcp-trim exclude <server>` keeps that server untouched (or write tool names or prefixes into `~/.claude/chutora/mcp-trim-exclude`), or `/chutora mcp-trim off`. Before 0.16 plain-text guides were trimmed too; from 0.16 they are left alone by default.

### The danger guard stops a command it shouldn't

Look at the rule id in the reason (for example `[rm-home]`). Just this once: allow it at the prompt. Never ask about it again: add a line `!rm-home` to `~/.claude/chutora/always-ask`. Turn it all off: `/chutora guard off` or `CHUTORA_GUARD=0`. If it is a false alarm (the command really is safe), please open an issue with the command.

### With `claude -p` or a skip-permissions mode, the guard stopped a command and it didn't run

That is expected: a non-interactive run has nobody to confirm, so Claude Code treats "ask first" as a refusal. If you are sure, run it yourself in a terminal, or set `CHUTORA_GUARD=0` for that run.

### Nothing is written to the observation log

Check that `/chutora` shows "Observation log (experimental): on". For an install.sh install, merge the new hooks snippet into `settings.json` (`observe.py` on PostToolUse, PostToolUseFailure, SubagentStop and UserPromptSubmit, plus `guard.py` on PreToolUse); `/chutora doctor` checks this.

### Still stuck

Open an issue with the output of `/chutora doctor` and your Claude Code version (`claude --version`).
