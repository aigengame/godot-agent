# Installing the `gda` Skill with your agent

`gda` ships an agent **Skill** — a `SKILL.md` that teaches an AI agent *how and when* to drive
Godot through the `gda` CLI. It is the lightest of `gda`'s three agent-facing surfaces
(**CLI · Skill · MCP**): no server to register, just a file your agent loads. The Skill is
[`skills/gda/SKILL.md`](../skills/gda/SKILL.md) in this repository, where the Skills CLI finds
it, and the `gda` package carries the same file, which `gda skill` emits version-locked to the
installed CLI (ADR-0024, ADR-0046).

## Get the Skill

One file, two ways to obtain it:

- **With the [Skills CLI](https://github.com/vercel-labs/skills)** — it asks which agents to
  install the Skill for (name them with `-a`) and writes each agent's skills directory:

  ```bash
  npx skills add aigengame/godot-agent --skill gda       # project scope
  npx skills add aigengame/godot-agent --skill gda -g    # user scope
  ```

  This tracks `main`: `npx skills update` brings in the latest `main`, which can describe
  commands that an older installed `gda` does not have.
- **From an installed `gda`** — `gda skill` prints the manifest; `gda skill --json` wraps it as
  `{name, version, content}`. This is **version-locked** to your installed `gda`, so the guidance
  always matches the CLI it describes (ADR-0024). It needs no Node.js.

## Install it where your agent loads skills

A `SKILL.md` is loaded by most coding agents — only the **discovery directory** differs:

| Agent | Personal (all projects) | Project scope (committed) |
| --- | --- | --- |
| **Claude Code** | `~/.claude/skills/gda/` | `.claude/skills/gda/` |
| **Codex and other agents** | `~/.agents/skills/gda/` | `.agents/skills/gda/` |

### Name your agent (recommended)

For the agents above, let `gda` resolve the directory — `--install --provider <agent> --scope
<project|user>` (ADR-0027). `--scope` defaults to `user`; `--provider` implies `--install`:

```bash
gda skill --install --provider claude --scope user      # ~/.claude/skills/gda/
gda skill --install --provider claude --scope project   # ./.claude/skills/gda/
gda skill --install --provider codex  --scope project   # ./.agents/skills/gda/
```

Codex uses the cross-agent `.agents/skills` namespace (per OpenAI's Codex docs), not `.codex/skills`.

### Or give the directory yourself

`gda skill --install --dir <dir>` writes `<dir>/SKILL.md` (creating parent dirs) — the neutral path
for any agent, listed above or not (there is **no** built-in default; `--dir` and `--provider` are
mutually exclusive):

```bash
gda skill --install --dir ~/.claude/skills/gda    # an explicit directory
# …or fetch the file from `main` directly, instead of going through `gda skill`:
curl --create-dirs -o ~/.agents/skills/gda/SKILL.md \
  https://raw.githubusercontent.com/aigengame/godot-agent/main/skills/gda/SKILL.md
```

Check your agent's docs if its skills directory differs; whichever directory it scans, the
manifest is the same file.

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
- `skills/gda/SKILL.md` is the single source. The package path `src/gda/skill/SKILL.md` is a
  symbolic link to it, so at any one commit the Skills CLI, the raw file and `gda skill` give the
  same bytes.
- The Skills CLI and `gda skill --install` can write the same skills directory; the last write
  wins.
