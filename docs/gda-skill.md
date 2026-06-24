# Installing the `gda` Skill with your agent

`gda` ships an agent **Skill** — a `SKILL.md` that teaches an AI agent *how and when* to drive
Godot through the `gda` CLI. It is the lightest of `gda`'s three agent-facing surfaces
(**CLI · Skill · MCP**): no server to register, just a file your agent loads. The Skill is
bundled in the `gda` package and emitted by `gda skill`, so its guidance is version-locked to
the installed CLI (ADR-0024).

## Get the Skill

One canonical file, two ways to obtain it:

- **From an installed `gda`** (recommended) — `gda skill` prints the manifest; `gda skill --json`
  wraps it as `{name, version, content}`. This is **version-locked** to your installed `gda`, so
  the guidance always matches the CLI it describes (ADR-0024).
- **From the repo** — [`src/gda/skill/SKILL.md`](../src/gda/skill/SKILL.md), raw at
  `https://raw.githubusercontent.com/aigengame/godot-agent/main/src/gda/skill/SKILL.md`. This
  tracks `main`, so it may differ from an older installed `gda` — prefer `gda skill` if you
  already have `gda`.

## Install it where your agent loads skills

Agent Skills (a `SKILL.md`) are loaded natively by **Claude Code** (and other agents in the Claude
ecosystem). `gda skill --install --dir <dir>` writes `<dir>/SKILL.md` (creating parent dirs); there
is **no built-in default location**, so point `--dir` at the agent's skills directory:

- **Claude Code** — personal (every project): `~/.claude/skills/gda/`; project scope (committed,
  shared with your team): your project's skills directory, e.g. `.claude/skills/gda/`.

  ```bash
  gda skill --install --dir ~/.claude/skills/gda
  # …or fetch the same file directly, instead of going through `gda skill`:
  curl --create-dirs -o ~/.claude/skills/gda/SKILL.md \
    https://raw.githubusercontent.com/aigengame/godot-agent/main/src/gda/skill/SKILL.md
  ```

- **Agents that don't load `SKILL.md` (e.g. Codex, Cursor)** — drive `gda` through the
  [MCP server](gda-mcp-registration.md) or the raw CLI instead; the Skill's content can also be
  pasted in as context.

## What the Skill assumes

The Skill teaches the CLI — the agent still needs `gda` on its `PATH` and a Godot engine to run.
Point `gda` at the engine with `GDA_GODOT`, and resolve a project with `GDA_PROJECT` (or run
inside a Godot project directory), exactly as for any `gda` use. See the README's
[Configuration](../README.md#configuration).

## Notes

- The Skill, the [MCP server](gda-mcp-registration.md), and the raw CLI are three ways into the
  **same** `gda` command surface — pick whichever your agent supports (ADR-0024).
- `gda skill` is itself on the `gda schema` surface, so an MCP agent can fetch the same guidance
  through its generated tool.
- The bundled `SKILL.md` is the single source; this repo's copy and the `gda skill` output are
  the same file, so the guidance never drifts from the installed CLI.
