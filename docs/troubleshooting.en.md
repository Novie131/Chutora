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

### Still stuck

Open an issue with the output of `/chutora doctor` and your Claude Code version (`claude --version`).
