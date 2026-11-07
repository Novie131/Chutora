# FAQ

<p><a href="../README.en.md">← Back to README</a> · <a href="faq.md">繁體中文</a></p>

**Does Chutora cost anything?**
No, it's MIT-licensed. Usage counts against your Claude plan as usual; the point of Chutora is to get more done with the same usage.

**Will it change my settings?**
Installing the plugin doesn't touch `settings.json`. Only `/chutora:route-setup` writes to it, item by item after you agree, with a backup first and without overwriting existing values. `/chutora mode` and `/chutora lang` only write two small files of their own under `~/.claude/chutora/`. `/chutora doctor` is read-only. The experimental observation log lives under `~/.claude/chutora/projects/`, and when the danger guard stops something it appends a line to `claude-memory/changes.jsonl` (or the auto memory folder); neither touches `settings.json`.

**How is this different from Claude Code's built-in `/rewind`?**
`/rewind` saves a checkpoint before each message you send and can restore files the main conversation changed with its editing tools. The official docs name two exceptions: files changed by subagents and files changed by Bash commands are not restored. Chutora hands implementation to the worker subagent, so for now use git for those; the "stuck rescue" on the roadmap will cover this gap.

**Does the main conversation have to be Opus?**
It's recommended, because the main conversation plans, decides and reviews, and the quality of delegation depends on it. Other models work too, but judgment may be weaker.

**Why does the main conversation sometimes do the work itself instead of delegating?**
Delegation matches the agents' descriptions and isn't guaranteed; also, small well-defined tasks are cheaper to do directly, on purpose. To be sure, name the agent with `@agent-chutora:worker`.

**Does economy mode make results worse?**
It can: it narrows verification and the main conversation looks at less. Use balanced or quality for important work.

**Is the weekly recap my actual spending?**
No. It's an estimate at API list prices covering only the model price difference; subscriptions aren't billed per token.

**Does any data leave my machine?**
The hooks only read and write local files. Only looking up external information (research) goes online; `security-test` explicitly never sends data out or touches production.

**Does it work in VS Code?**
Yes, both the Claude Code CLI and the VS Code extension. After installing the optional board mod, run Developer: Reload Window in VS Code.

**Can I use only part of it?**
Yes. The board and reply-format mods are optional; `bash install.sh --agents-only` installs only the agents; you can disable the whole plugin in `/plugin`, or delete skills you don't want after an install.sh install.

**Can noisy-output trimming cut something important?**
It is deliberately conservative: it only touches successful install/build/test output over the threshold; error, warning, assert and stack-trace lines are always kept with 2 lines around them, as are the start and the end; failed commands, file-reading commands and `git diff` are never touched. If you do need an omitted part, the original is always in `~/.claude/chutora/raw/`.

**How do I see the original before trimming?**
The last line of the trimmed output names the original's path (`~/.claude/chutora/raw/<id>.log`). Ask Claude to "read the original", or open the file yourself. To turn trimming off entirely: `/chutora trim off`.

**Can read dedup hide a file from Claude?**
Not content that is still in the conversation: it only dedups when the earlier result is still on the current conversation chain and the file is exactly unchanged; after a compact, `/clear` or `/rewind` files are read normally. If Claude says it can't find the earlier content, ask it to read a different range, or run `/chutora dedup off`.

**Will clarify ask about everything?**
No. Small or already-clear tasks aren't questioned, it asks at most 3 to 5 questions, and "use the defaults, stop asking" is always an option. To have it ask less: say "stop asking, use the defaults", or `/chutora ask off` to turn off the reminder when you say you're unsure.

**Can MCP trimming drop a field I need?**
Omitted items and cut strings are noted in the output, and the original is always saved under `~/.claude/chutora/raw/`. If a tool must always come through in full, add it to the exclude list (`CHUTORA_MCP_TRIM_EXCLUDE` or `~/.claude/chutora/mcp-trim-exclude`).

**Why doesn't MCP trimming trim plain text any more?**
0.15 once cut 204 lines from a connector's usage guide, and Claude then followed the broken guide. Every line of a guide may matter, so from 0.16 plain text and Markdown are left alone by default and only long JSON lists and repeats are trimmed. To trim plain text anyway: `/chutora mcp-trim text on`.

**Will the danger guard get in the way of normal commands?**
It only looks at the always-ask list: ordinary commands such as `git push origin feat/x`, `rm -rf node_modules` and `npm install` pass, and merely mentioning a dangerous command in a commit message or `echo` isn't caught. If one rule keeps asking and you don't want it to, add a line `!<rule id>` to `~/.claude/chutora/always-ask` (`/chutora guard rules` lists the ids).

**Does the guard still work with `--dangerously-skip-permissions`?**
Yes. Blocks such as `rm -rf ~` apply in every permission mode (the official docs say so). And because a confirmation prompt may be skipped in this mode, the kinds a backup can't undo (force push, deleting outside the project or in your home folder, `DROP TABLE`, `terraform destroy`, `kubectl delete`) are blocked too; the reason names bypass-permissions mode and asks you to run it yourself in a terminal or turn the mode off and retry. Other ask-first items (such as `git reset --hard`) did not run when tested with `claude -p` and this flag (nobody could confirm, so it counts as a refusal). Interactive mode has not been tested yet; you can check it yourself with the steps in [troubleshooting](troubleshooting.en.md#check-the-danger-guard-in-your-own-interactive-claude-code).

**Will `/chutora:route-setup` ask me twice?**
No. It asks you about each item first and then calls the `apply_settings.py` inside Chutora's own folder; the guard recognizes that script and doesn't prompt a second time. Any other way of changing `settings.json` (a same-named script elsewhere, `sed -i`, writing the file directly) still asks.

**Does the observation log cost tokens? What does it keep?**
No tokens: it prints nothing, and in testing the same task used the same input tokens with and without it, apart from the few every run varies by. It keeps short summaries only (command, path, tool name, output size), never tool output; ordinary prompts only record their length and common key formats are masked. It also notes which output keeps getting trimmed and which files keep being re-read (files outside the project only as a path hash). Your corrections keep their first 160 characters by default (masked); for stricter privacy, `/chutora observe privacy strict` keeps only the length of corrections and choices. The files are in `~/.claude/chutora/projects/<project id>/` and rotate past 5 MB; turn it off with `/chutora observe off`.

**Can the decision engine do something dangerous on its own?**
No. It only acts automatically when you have explicitly said "this kind may be automatic" and the action is recoverable (inside the project, restore point saved), and the whole command must be just that one thing. Anything on the always-ask list — force push, deleting outside the project, `DROP TABLE` — and the rules you added in `always-ask` are out of its reach; pushing to a remote or writing to outside services is never automatic. Claude can't grant itself permission either: running `/chutora ok … auto` itself is stopped by the guard.

**How do I make a kind of action automatic, or stop it?**
When the line appears at the end of a reply, answer `/chutora ok <id> auto` (may be automatic from now on) or `/chutora ok <id> ask` (ask me next time); if it got something wrong, `/chutora undo <id>` restores it from the restore point and similar actions stay manual for 24 hours. `/chutora changes` lists what is still waiting; `/chutora decide off` turns automatic runs off entirely.

**Where are the benchmark numbers?**
Not published yet. `bench/run.py` works, but no numbers go up until a real run has been done and checked; see [Benchmark](../README.en.md#benchmark) in the README.

**Does the Flight Deck slow Claude down?**
The status-line path writes one small JSON file per tool call and reads the transcript incrementally; the panel only observes tool calls without changing results, redraws at most every 250 ms and keeps at most 40 timeline entries. Either side fails quietly and never blocks a tool.
