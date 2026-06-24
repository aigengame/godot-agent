---
status: accepted
---

# gda skill: an Agent Skill as a third agent-facing channel, shipped in-package

An agent can reach [gda](../../CONTEXT.md) two ways today: the CLI directly, and
[gda-mcp](../../CONTEXT.md) (ADR-0011), which exposes the same surface as MCP tools
generated from `--schema` (ADR-0012). This ADR adds a third — an **Agent Skill**: a
`SKILL.md` that teaches an agent *how and when* to drive the `gda` CLI — and fixes how it
is distributed. It mirrors the single-distribution packaging stance ADR-0013 took for
gda-mcp.

## Decision

**A Skill is the third agent-facing channel.** The three channels ride the one `gda`
command surface and are equivalent in capability: the **CLI** is raw invocation;
**gda-mcp** is that surface as generated tools (ADR-0012); a **Skill** points the agent at
the CLI itself plus the guidance for how and when to use it. An agent uses whichever its
runtime supports — a Skill is the lightest path (no server to register), native to agents
that load `SKILL.md`.

**Shipped in-package, emitted by `gda skill`.** The canonical `SKILL.md` lives inside the
`gda` distribution under the package dir — the same way the GDScript payload ships
(resolved by a package-relative path, not `importlib.resources`) — so a `gda skill`
meta-command can emit it and the guidance stays **version-locked to the installed CLI**.
This is the single-version argument ADR-0013 makes for the MCP adapter, applied to the
Skill: the manifest and the commands it describes cannot skew because they are one
distribution. `gda skill` is a **pure emitter** meta-command (no Godot spawn), a sibling
of `info`/`schema`, carrying `--json`/`--schema` like them; an optional `--install` writes
the manifest into the agent's skills directory.

**Hybrid distribution, one source.** Because the canonical file lives in the repo *under*
the package, it is both shipped in the wheel and browsable / curl-able from the source
tree — one source, two access paths (the `gda skill` command for installed users; the
repo file for a manual drop-in). There is no second copy to drift.

**Vendor specifics stay out of the core.** The `SKILL.md` content and the CONTEXT.md term
stay agent-neutral; agent-specific install directories live in the registration recipes
doc, not in the manifest or this ADR — the same separation ADR-0014 draws for project
resolution.

## Considered options

- **Repo-hosted `SKILL.md`, manual copy only (rejected as the sole mechanism).** Zero
  code, but the guidance is not version-locked to the installed CLI and can drift, and
  there is no self-install. Kept as *one* of the two hybrid access paths, not the only one.
- **A separate skill package or marketplace plugin (rejected).** A second distribution and
  version line, at odds with the single-distribution authority (ADR-0008 / ADR-0013).
- **In-package `SKILL.md` + `gda skill` command, hybrid access (chosen).**

## Consequences

- `gda skill` reaches the MCP surface like any meta command (it carries `--schema`), so an
  MCP agent can fetch the same guidance — the channels reinforce rather than fork.
- The Skill covers the **full** surface (headless + live); live's prerequisites (a running
  daemon, Godot 4.6+, macOS/Linux, `--windowed` for `screen` capture) are stated in the
  body, not gated by it.
- The `description` is the only thing an agent sees when deciding to load the Skill; it is
  tuned to trigger on building/modifying a Godot game and kept free of time-sensitive
  detail (no versions/dates that drift).
- The one canonical `SKILL.md` under the package dir is the single source; the README's
  "Use it as a Skill" section and `docs/gda-skill.md` link to it and to the `gda skill`
  install path.
