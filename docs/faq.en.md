# FAQ

<p><a href="../README.en.md">← Back to README</a> · <a href="faq.md">繁體中文</a></p>

**Does Chutora cost anything?**
No, it's MIT-licensed. Usage counts against your Claude plan as usual; the point of Chutora is to get more done with the same usage.

**Will it change my settings?**
Installing the plugin doesn't touch `settings.json`. Only `/chutora:route-setup` writes to it, item by item after you agree, with a backup first and without overwriting existing values. `/chutora mode` and `/chutora lang` only write two small files of their own under `~/.claude/chutora/`. `/chutora doctor` is read-only.

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

**Where are the benchmark numbers?**
Not published yet. `bench/run.py` works, but no numbers go up until a real run has been done and checked; see [Benchmark](../README.en.md#benchmark) in the README.
