# Installing in three environments

[English](INSTALL.en.md) | [繁體中文](INSTALL.md)

The short version:

| Environment | How to install | Shared with |
|---|---|---|
| **Cowork (desktop)** | Click the `.plugin` file to install | Its own setup |
| **Claude Code CLI** | Run `install.sh` | ← shared with VS Code |
| **VS Code extension** | Same as above; install once, both get it | ← shared with CLI |

**The CLI and VS Code share `~/.claude/`, so one install covers both.** Cowork uses its own install flow and needs a separate install.

---

## Cowork (desktop)

Click the install button on the `.plugin` file. **It works right after install** (for the full feature set, such as the status line, auto-compact threshold, Haiku Explore, and claude-memory, run `/chutora:route-setup`), and **it is available in every conversation** (a plugin is user-level, not tied to a conversation).

After installing, type `/chutora` for the status and a menu of what it can do; if nothing seems to happen, run `/chutora doctor`, which checks each piece and tells you how to fix it.

To verify, ask in a new conversation "which agents are available?". You should see `worker`, `worker-hard`, `bulk`, `librarian`, `harvester`, `security-review`, and `security-test`.

---

## Claude Code CLI and VS Code extension

These two share the same configuration, so do the steps below once.

### One-command install

Run from the repo root (or put `install.sh` and `chutora.plugin` in the same directory; without a `.plugin`, the script uses `plugins/chutora/` directly):

```bash
bash install.sh
```

The script **copies** agents, skills, and hooks into `~/.claude/` (`agents/*.md` → `~/.claude/agents/`, `skills/<name>/` → `~/.claude/skills/`, `hooks/` → `~/.claude/hooks/chutora/`). No marketplace and no `/plugin install` needed. Note that Claude Code does not load a plugin folder placed under `~/.claude/skills/`, so the script spreads the contents out instead of dropping the whole package in; leftovers from older script versions in `~/.claude/skills/chutora/` are removed automatically.

In this mode names have **no namespace**: the agent is `worker` (not `chutora:worker`) and the skill is `/handoff`.

Installed items are recorded in `~/.claude/.chutora-installed`. For an existing file with the same name: identical content is added to the manifest; different content (your own) is left alone with a warning; symlinks (from `--link`) are not touched.

**Hooks are not enabled automatically.** The script does not edit your `settings.json`. It prints a settings snippet at the end, which you merge into `"hooks"` in `~/.claude/settings.json` yourself (remove any older hook of the same kind first).

Restart Claude Code after installing and you can start using it. For the full feature set (status line, auto-compact threshold, Haiku Explore, claude-memory), run `/route-setup` (in this mode, paste the hooks into settings.json first, otherwise the reminder will not appear).

### Status line (optional)

Add `--with-statusline` (it can be combined with the default copy mode or `--link`, but not with `--agents-only` or `--uninstall`). The script only handles the `statusLine` key in `~/.claude/settings.json`: it creates the file if missing; if `statusLine` already exists it does not overwrite it and only prints a suggested snippet; otherwise it first backs the file up as `settings.json.bak-<timestamp>`, then adds just this one key. If the JSON is broken or python3 is missing, it changes nothing. To do it by hand, paste this (the path applies only to install.sh installs; plugin users should use `/chutora:route-setup`):

```json
"statusLine": { "type": "command", "command": "python3 ~/.claude/hooks/chutora/statusline.py" }
```

We also recommend `"autoCompactWindow": 153000` (the script does not write it): after subtracting a buffer of about 33k, auto-compact triggers at roughly 120k, leaving headroom for the handoff; the handoff is injected back automatically after compaction. The 33k figure was measured on the author's machine; after writing the value, confirm with `/context` that the compact point is about 120k.

### Board mod (optional)

Add `--with-agent-board` (it can be combined with the default copy mode or `--link`, but not with `--agents-only` or `--uninstall`). VS Code cannot take `--plugin-dir`, so this mod (`plugins/agent-board`) is loaded through the `CLAUDE_CODE_PLUGIN_DIRS` environment variable; the script adds its directory to `env.CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json` (multiple paths are separated by `:`). It only touches that one variable: it creates `env` if missing, appends to an existing value, and does not add the path twice; it first backs the file up as `settings.json.bak-<timestamp>`; if the JSON is broken or python3 is missing, it changes nothing and prints the snippet to add by hand. With `--link` the path points at `plugins/agent-board` inside the repo; in copy mode it first copies the folder to `~/.claude/chutora/agent-board/` (recorded in the install manifest) and points there; installs from a `.plugin` archive do not include agent-board, so it is skipped. `--uninstall` removes the path this script added from the variable (other paths and variables are left alone).

After installing, run Developer: Reload Window in VS Code, or restart `claude` in the terminal, for it to load. Users who install from the plugin marketplace do not need this flag; use `/plugin install agent-board@chutora` instead. To do it by hand, add this to `settings.json`:

```json
"env": { "CLAUDE_CODE_PLUGIN_DIRS": "/absolute/path/to/plugins/agent-board" }
```

### Detail button and reply format (optional)

Add `--with-reply-detail` (the restrictions, `--link`/copy modes and `--uninstall` handling are all the same as `--with-agent-board`, and the two flags can be used together). This mod (`plugins/reply-detail`) injects a reply-format rule into the system prompt (a compact three-part reply: status / what you need to do / what you need to decide or provide; main conversation only, sub-agents ignore it). Switching the board's reply mode ("⇄ 回覆：精簡／詳細") to detailed keeps every later reply detailed; for a one-off, typing "詳細說明" asks for a detailed rewrite of the previous reply. The switch is not drawn under the reply or above the prompt, because VS Code wraps those mod-drawn areas in a frame and label. It is loaded the same way, through `env.CLAUDE_CODE_PLUGIN_DIRS`: with `--link` the path points at `plugins/reply-detail` inside the repo; in copy mode it first copies the folder to `~/.claude/chutora/reply-detail/` (recorded in the install manifest) and points there; installs from a `.plugin` archive do not include it, so it is skipped. `--uninstall` removes only the path this script added. After installing, run Developer: Reload Window in VS Code, or restart `claude` in the terminal. Users who install from the plugin marketplace should use `/plugin install reply-detail@chutora` instead.

### Verify

```
/agents
```

You should see seven agents (`worker`, `worker-hard`, `bulk`, `librarian`, `harvester`, `security-review`, `security-test`). Or try an @-mention:

```
@agent-worker
```

Once the hooks snippet is pasted, check it with `/hooks`.

If you also want code search to run on Haiku, add `--with-explore` (it places `skills/route-setup/templates/Explore.md` into `~/.claude/agents/`, and does not overwrite an existing file):

```bash
bash install.sh --with-explore
```

### If the agents do not appear

First make sure you restarted Claude Code, then check that the five `.md` files exist under `~/.claude/agents/`. If you want only the agents and not the skills and hooks, use:

```bash
bash install.sh --agents-only
```

This copies only the agent definitions (also recorded in the manifest). The trade-off: hooks (context reminder, memory injection at session start) and skills (`/handoff`, `/research`, `/usage-stats`) will not take effect.

### Maintaining it yourself, with edits taking effect immediately

```bash
bash install.sh --link
```

This symlinks agents, skills, and hooks to the files in the repo, so `git pull` or your own edits apply without reinstalling. Names have no namespace (`worker`, `/handoff`). The script does not edit `settings.json`; it prints a hooks snippet for you to paste. Existing files with the same name are never overwritten; if you move the repo, just run it again.

### Just trying it, without installing

```bash
claude --plugin-dir ./chutora.plugin
```

`--plugin-dir` accepts a zip archive, and a `.plugin` is a zip. This only lasts for the current session, which suits a quick trial.

---

## Version requirements

This plugin uses a few newer frontmatter fields:

| Field | Purpose | If unsupported |
|---|---|---|
| `model` | Sets which model an agent uses | Everything follows the main conversation model; tiering stops working |
| `memory` | Persistent memory | Memory stops working (the connected-folder route still works) |
| `effort` | Sets reasoning effort by cost of failure | Follows the session setting |
| `omitClaudeMd` | bulk does not load CLAUDE.md (needs 2.1.271+) | CLAUDE.md is loaded too; costs more but works |

The context-length reminder hook needs `python3`; if it is not found, the hook quietly disables itself.

Check your version:

```bash
claude --version
```

If it is too old:

```bash
claude update
```

Also, `memory` depends on auto memory. If you disabled `autoMemoryEnabled` or set the environment variable `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, that field has no effect. In that case use the "`claude-memory/` in a connected folder" route (worker prefers it anyway).

---

## Set the main conversation model separately

**The plugin only defines subagents; it does not change your main conversation model.** You need to turn on the first tier yourself:

```
/model opus
```

Or put it in `~/.claude/settings.json`:

```json
{ "model": "opus" }
```

If you do not set it, the main conversation uses your existing default model, and the quality of delegation decisions drops.

---

## Memory folder in each environment

Memory lives in a **folder you choose**, not inside the plugin. Each of the three environments connects it differently:

- **Cowork**: connect the memory folder every time you start a new conversation. This is the only step you have to repeat; forget it and you effectively lose your memory.
- **CLI**: start the session inside the memory folder, or treat it as the project root.
- **VS Code**: add the memory folder to your workspace.

If all three point to the **same folder**, memory is shared. This is also why we suggest opening that folder in Obsidian: it is where agents read and write, where you view and tidy, and what each environment connects to.

---

## Updating

Just re-run `install.sh`: items in the manifest (installed earlier) are deleted and recopied as the new version, and your own same-named files are left alone. On Cowork, click the new `.plugin` file again.

**Remember to update both sides.** Behavior differs between versions, and this kind of problem is hard to notice: you will think an agent is unreliable when the two machines are actually running different versions.
