---
status: accepted
---

# gda skill: an Agent Skill as a third agent-facing channel, shipped in-package

> **Extension (2026-06-25) — opt-in known-agent install ([ADR-0027](0027-gda-skill-provider-install.md)).**
> The "core carries no agent-specific default install location" decision below stands for the
> *default* path: a plain `gda skill` and a bare `--install` still require an explicit `--dir`.
> ADR-0027 adds an **opt-in** convenience on top — `--install --provider <agent> --scope <scope>`
> resolves a known agent's skills directory (Claude Code's `.claude/skills/`, the cross-agent
> `.agents/skills/`) only when the caller names a provider, with `--dir` remaining the neutral
> fallback and the `SKILL.md` content still agent-neutral.

An agent can reach [gda](../../CONTEXT.md) two ways today: the CLI directly, and
[gda-mcp](../../CONTEXT.md) (ADR-0011), which exposes the same surface as MCP tools
generated from `--schema` (ADR-0012). This ADR adds a third — an **Agent Skill**: a
`SKILL.md` that teaches an agent *how and when* to drive the `gda` CLI — and fixes how it
is distributed. It mirrors the single-distribution packaging stance ADR-0013 took for
gda-mcp.

## Decision

**A Skill is the third agent-facing channel.** The three channels expose the **same
underlying `gda` command surface** but differ as integration mechanisms: the **CLI** is
raw invocation; **gda-mcp** is that surface as generated tools (ADR-0012); a **Skill** is
guidance that teaches an agent to drive the CLI itself — it executes nothing of its own. An
agent uses whichever its runtime supports — a Skill is the lightest path (no server to
register), native to agents that load `SKILL.md`.

**Shipped in-package, emitted by `gda skill`.** The canonical `SKILL.md` lives inside the
`gda` distribution under the package dir — the same way the GDScript payload ships
(resolved by a package-relative path, not `importlib.resources`) — so a `gda skill`
meta-command can emit it and the guidance stays **version-locked to the installed CLI**.
This is the single-version argument ADR-0013 makes for the MCP adapter, applied to the
Skill: the manifest and the commands it describes cannot skew because they are one
distribution. `gda skill` is a **pure emitter** meta-command (no Godot spawn), a sibling
of `info`/`schema`, carrying `--json`/`--schema` like them. Installing is neutral: `gda
skill` emits to stdout, and an optional `--install --dir <path>` writes the manifest to a
**caller-supplied** directory — core carries no agent-specific default location (see below).

**Hybrid distribution, one source.** Because the canonical file lives in the repo *under*
the package, it is both shipped in the wheel and browsable / curl-able from the source
tree — one source, two access paths (the `gda skill` command for installed users; the
repo file for a manual drop-in). There is no second copy to drift.

**Vendor specifics stay out of the core.** The `SKILL.md` content and the CONTEXT.md term
stay agent-neutral, and **`gda skill` defaults to no agent-specific install path**: it
emits to stdout, and `--install` requires an explicit `--dir`. The per-agent target path
(e.g. a given agent's skills directory) is documented in the registration recipes doc, not
defaulted in core — the same separation ADR-0014 draws for project resolution.

## Considered options

- **Repo-hosted `SKILL.md`, manual copy only (rejected as the sole mechanism).** Zero
  code, but the guidance is not version-locked to the installed CLI and can drift, and
  there is no self-install. Kept as *one* of the two hybrid access paths, not the only one.
- **A separate skill package or marketplace plugin (rejected).** A second distribution and
  version line, at odds with the single-distribution authority (ADR-0008 / ADR-0013).
- **In-package `SKILL.md` + `gda skill` command, hybrid access (chosen).**

## Consequences

- `gda skill` is a descriptor-backed command and appears in the aggregate `gda schema`
  manifest, so gda-mcp generates a tool for it through the normal dispatchable surface
  (ADR-0011 / ADR-0012) — not via any skill-specific path. An MCP agent can therefore fetch
  the same guidance; the channels reinforce rather than fork.
- The Skill covers the **full** surface (headless + live); live's prerequisites (a running
  daemon, Godot 4.6+, macOS/Linux, `--windowed` for `screen` capture) are stated in the
  body, not gated by it.
- The one canonical `SKILL.md` under the package dir is the single source; the user-facing
  "Use it as a Skill" README section and `docs/gda-skill.md` (added in #267) will link to
  it and to the `gda skill` install path.
