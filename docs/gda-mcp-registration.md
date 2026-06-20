# Registering `gda-mcp` with your agent

`gda-mcp` is a stdio [MCP](https://modelcontextprotocol.io) server that exposes the
whole `gda` command surface as MCP tools, generated from `gda`'s own `--schema`. It
ships inside the one `gda` distribution behind an optional `[mcp]` extra (ADR-0013), so
any MCP-speaking agent can drive Godot through it.

This guide gives copy-pasteable registration recipes for **Claude Code**, **Codex**,
**Cursor**, and **Claude Desktop**, at user and project scope — except **Claude Desktop**, which has
a single per-user config (no project scope).

## Before you start

### Launch command

`gda-mcp` is launched as a `command` + `args` stdio server. Two forms:

- **Zero-install (recommended to try)** — run it straight from PyPI with
  [`uv`](https://docs.astral.sh/uv/):

  ```
  uvx --from "gda[mcp]" gda-mcp
  ```

- **Installed** — put the `gda-mcp` console script on your PATH:

  ```
  uv tool install "gda[mcp]"
  ```

### The server needs a Godot engine

`gda-mcp` shells out to `gda`, which spawns the Godot engine. If `godot` is not at
`gda`'s default location (or you want to pin a specific build), add `GDA_GODOT` to the
recipe's `env` block, e.g. `"GDA_GODOT": "/Applications/Godot.app/Contents/MacOS/Godot"`.

### How the server finds your Godot project

`gda-mcp` resolves one target Godot project for the server by an agent-neutral
precedence (ADR-0014), first hit wins:

1. **`GDA_PROJECT`** in the server's `env` — explicit and portable; works in every agent.
2. the **`roots/list`** the client advertises — used automatically by clients that
   support it (e.g. Claude Code), no config needed.
3. the process **cwd** — last-resort fallback (unreliable across agents).

A `roots` or cwd candidate is used only when it is a real Godot project (contains
`project.godot`); otherwise resolution moves on. An explicitly set **`GDA_PROJECT`** is stricter: if
it is not a valid project, `gda` reports a typed error rather than silently falling back to `roots`
or cwd. **Recommended: register at project scope, or pin `GDA_PROJECT`.** Each recipe below shows the
right way to pin the project for that agent.

## Two cross-cutting constraints

### Minimal PATH on GUI-launched agents

**Claude Desktop and Cursor** are launched from the Dock/Finder with a **minimal PATH**
that usually omits `~/.local/bin`, `/opt/homebrew/bin`, and `/usr/local/bin`, so a bare
`command: "uvx"` or `"gda-mcp"` can fail with "command not found". For those two agents,
use an **absolute path** to the executable, or inject a `PATH` into `env`:

```jsonc
// find the absolute path first:  which uvx   /   which gda-mcp
"command": "/Users/you/.local/bin/uvx"
// …or keep the bare command and repair PATH:
"env": { "PATH": "/opt/homebrew/bin:/usr/local/bin:/Users/you/.local/bin:/usr/bin:/bin" }
```

The CLI agents (**Claude Code**, **Codex**) inherit a normal shell PATH and are
unaffected.

### Project pinning is agent-specific

The mechanism is always one of the three neutral signals above, but how you supply the
project path differs per agent: `GDA_PROJECT` everywhere, `${workspaceFolder}` on Cursor (project
scope),
`${CLAUDE_PROJECT_DIR}` or `roots` on Claude Code, an absolute path on Codex / Claude
Desktop.

---

## Claude Code

Config: `.mcp.json` at the project root (project scope, shareable via version control) or
`~/.claude.json` (user/local scope). No `type` field — stdio is implicit.

Claude Code **advertises `roots`**, so `gda-mcp` auto-detects the workspace project with
no `GDA_PROJECT` needed. Pin `GDA_PROJECT` explicitly only if you want a project other
than the launch workspace.

### Project scope — `.mcp.json` (committed to the repo)

```json
{
  "mcpServers": {
    "gda-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "gda[mcp]",
        "gda-mcp"
      ],
      "env": {}
    }
  }
}
```

The empty `env` is enough: Claude Code's advertised `roots` resolve the project. To pin
it explicitly instead, set `"env": { "GDA_PROJECT": "${CLAUDE_PROJECT_DIR}" }` (Claude
Code provides `CLAUDE_PROJECT_DIR` in the server environment).

### User scope — the CLI

```bash
claude mcp add --scope user gda-mcp -- \
  uvx --from "gda[mcp]" gda-mcp
```

Everything after `--` is the launch command. `--scope user` makes the server available
across all your projects (stored in `~/.claude.json`); use `--scope project` to write a
`.mcp.json` instead, or `--scope local` for this project only. Add `--env KEY=VALUE`
(repeatable) before the `--` to set environment variables.

### Verify

```bash
claude mcp list          # gda-mcp should be listed
claude mcp get gda-mcp   # shows the command/args/env
```

In a session, `/mcp` shows server status and the `scene_*`, `node_*`, `info`, … tools.

---

## Codex

Config: `~/.codex/config.toml` (global) or `.codex/config.toml` at the project root
(project-local, **trusted projects only**; the closest file to your cwd wins). TOML, with
a `[mcp_servers.<name>]` table. No `type` key — Codex infers stdio from `command`.

Codex does not reliably advertise `roots` or set the project cwd, so **pin `GDA_PROJECT`
explicitly** (an absolute path — Codex has no `${workspaceFolder}` substitution).

### Global scope — `~/.codex/config.toml`

```toml
[mcp_servers.gda-mcp]
command = "uvx"
args = ["--from", "gda[mcp]", "gda-mcp"]

[mcp_servers.gda-mcp.env]
GDA_PROJECT = "/absolute/path/to/your/godot/project"
```

### Project scope — `.codex/config.toml` (committed; project must be trusted)

```toml
[mcp_servers.gda-mcp]
command = "uvx"
args = ["--from", "gda[mcp]", "gda-mcp"]
# Pin the project; you can also set cwd = "..." for the server process.

[mcp_servers.gda-mcp.env]
GDA_PROJECT = "/absolute/path/to/your/godot/project"
```

### The CLI

```bash
codex mcp add gda-mcp --env GDA_PROJECT=/absolute/path/to/project -- \
  uvx --from "gda[mcp]" gda-mcp
```

`--env KEY=VALUE` (repeatable) precedes `--`; everything after `--` is the launch
command. This writes into `~/.codex/config.toml`.

---

## Cursor

Config: `.cursor/mcp.json` at the project root (project scope) or `~/.cursor/mcp.json`
(global scope); project takes precedence. The stdio `type` field is required in current
Cursor.

Cursor resolves `${workspaceFolder}`, `${userHome}`, and `${env:NAME}` inside
`command`/`args`/`env`, so the **project-scoped** config pins the open project cleanly with
`"GDA_PROJECT": "${workspaceFolder}"`. Cursor is **GUI-launched** — mind the minimal-PATH
constraint above.

### Project scope — `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "gda-mcp": {
      "type": "stdio",
      "command": "/Users/you/.local/bin/uvx",
      "args": [
        "--from",
        "gda[mcp]",
        "gda-mcp"
      ],
      "env": {
        "GDA_PROJECT": "${workspaceFolder}"
      }
    }
  }
}
```

Replace the absolute `command` path with the output of `which uvx`. To keep a bare
`"command": "uvx"`, add a repaired `PATH` to `env`:
`"PATH": "/opt/homebrew/bin:/usr/local/bin:${userHome}/.local/bin:${env:PATH}"`.

### Global scope — `~/.cursor/mcp.json`

Same structure, but set `GDA_PROJECT` to a literal **absolute** project path: `${workspaceFolder}` is
only reliable in the project-level `.cursor/mcp.json` — Cursor does not document it for the global
config, and it has been reported passed through unexpanded there.

---

## Claude Desktop

Config: a single per-user file (no project scope — Claude Desktop is a desktop app with
one global config):

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

(Settings → Developer → "Edit Config" opens it.) Same `mcpServers` schema as Claude Code;
no `type` field. Claude Desktop is **GUI-launched** — use an **absolute path** and pin
`GDA_PROJECT` to an absolute path.

```json
{
  "mcpServers": {
    "gda-mcp": {
      "command": "/Users/you/.local/bin/uvx",
      "args": [
        "--from",
        "gda[mcp]",
        "gda-mcp"
      ],
      "env": {
        "GDA_PROJECT": "/absolute/path/to/your/godot/project"
      }
    }
  }
}
```

Find the `command` path with `which uvx` (or `which gda-mcp` if you used `uv tool
install`). After editing, fully quit and reopen Claude Desktop.

---

## Working across multiple projects

`gda-mcp` targets **one** Godot project per server: it resolves the project once (on the first tool
call) and reuses it for the server's lifetime. A fresh agent session spawns a fresh server, which
resolves again.

- **One project at a time** — the common case; nothing special needed. A project-scoped registration
  (or a pinned `GDA_PROJECT`) gives one server : one project.
- **Several projects** — the reliable pattern is **one registration per project**: register at
  project scope (the per-repo `.mcp.json` / `.codex/config.toml` / `.cursor/mcp.json` above) so each
  project gets its own server pinned to it.
- A **user/global** registration follows the open project only where the client advertises a
  per-session signal: **Claude Code** advertises `roots`, so it targets the workspace you open it in.
  **Cursor** and **Codex** have no reliable per-window signal for a global config (Cursor's
  `${workspaceFolder}` is reliable only in the project-level file), so a global registration there is
  pinned to the single `GDA_PROJECT` you set — register at project scope for those if you work across
  several projects.

Switching the active project **within a single live session** (without starting a new one) is not yet
supported — the server keeps the project it first resolved. Dynamic re-resolution when the client's
active workspace changes is tracked in
[#209](https://github.com/aigengame/godot-agent/issues/209).

## Notes

- **`gda` is on [PyPI](https://pypi.org/project/gda/)**, so the `"gda[mcp]"` spec above
  resolves directly — `uv tool install "gda[mcp]"` / `pip install "gda[mcp]"` work as shown.
- **`GDA_BIN`** overrides which `gda` the adapter shells out to (default: the `gda` in
  the same install). An escape hatch for unusual layouts; see ADR-0013.
- **Trust** — a `--project` op runs the target project's own code at engine startup
  (autoloads); `gda` assumes a trusted project (ADR-0009). Only point `gda-mcp` at
  projects you trust.
