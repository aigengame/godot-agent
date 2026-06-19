---
status: accepted
---

# gda-mcp packaging and launch: one distribution behind a `[mcp]` extra, launched as a stdio command

ADR-0011 makes [gda-mcp](../../CONTEXT.md) a subprocess adapter over the `gda` CLI;
ADR-0008 makes release-please the single authoritative version source for the one
`gda` distribution. This ADR fixes how gda-mcp is packaged and how an agent launches
it.

## Decision

**One distribution, MCP behind an optional `[mcp]` extra.** gda-mcp ships inside the
existing `gda` distribution, not as a separate package. The `mcp` SDK and the
`gda-mcp` console-script entry point are gated behind a `gda[mcp]` extra, so a plain
`gda` install stays lean (pydantic + typer) and only `gda[mcp]` pulls the MCP SDK.
This keeps a **single version** (ADR-0008) shared by the CLI and its adapter —
structurally eliminating any CLI/adapter version skew — and one release pipeline
(ADR-0007 / ADR-0008), at the cost of declaring the `gda-mcp` entry point even when
the extra is absent (running it without the extra fails with a clear "install
`gda[mcp]`" message).

**Launched as a stdio command.** gda-mcp is the `gda-mcp` console script — an `mcp`
**low-level** stdio server. The portable registration vector across every surveyed
agent (Claude Code, Codex, Claude Desktop, Cursor) is a stdio server described by
`command` + `args` (+ optional `env`); gda-mcp targets exactly that shape. Two
invocations are supported: the installed console script `gda-mcp`, and a zero-install
`uvx`. Until `gda` is published to PyPI (tracked by #207), the zero-install form
resolves the package from the public git repo —
`uvx --from "gda[mcp] @ git+https://github.com/aigengame/godot-agent" gda-mcp`; once on
PyPI it simplifies to the canonical `uvx --from "gda[mcp]" gda-mcp`.

**Per-agent registration recipes are a shipped deliverable** (user- and
project-scope) — not left to the user to derive — because the agents diverge in
config location and format (`.mcp.json` / `~/.claude.json`; `~/.codex/config.toml`
plus repo-local `.codex/config.toml`; `claude_desktop_config.json`; `.cursor/mcp.json`
/ `~/.cursor/mcp.json`).

## Considered options

- **Separate `gda-mcp` distribution depending on `gda` (rejected).** Cleaner
  dependency isolation, but introduces a second version line that can skew against the
  installed `gda` and a second release pipeline — both at odds with ADR-0008's
  single-version authority. Co-distribution behind an extra gets the isolation (lean
  default install) without the skew.
- **gda-mcp in the core dependency set, no extra (rejected).** Would force the `mcp`
  SDK onto every CLI-only user.
- **One distribution + `[mcp]` extra + stdio console script (chosen).**

## Consequences

- A known cross-agent constraint, recorded so the recipes account for it:
  GUI-launched agents (Claude Desktop, Cursor) spawn servers with a **minimal PATH**
  that often excludes `~/.local/bin`, so a bare `command = "uvx"` / `"gda-mcp"` may
  not resolve. Recipes for those agents use an **absolute path** to the executable (or
  inject a full `PATH` via `env`); the CLI agents (Claude Code, Codex) inherit a normal
  shell PATH and are unaffected.
- Do **not** depend on the launch working directory (see ADR-0014): Claude Code
  ignores a configured `cwd` (claude-code#17565), Cursor / Claude Desktop leave it at
  the launch location or undefined, and `uvx` can further skew `os.getcwd()`
  (python-sdk#1520).
- The `gda-mcp` entry point exists in every install; without the `[mcp]` extra it
  errors on a missing `mcp` import with an actionable message.
- **Which `gda` gda-mcp shells out to, and the `GDA_BIN` escape hatch (#193).** By
  default gda-mcp invokes `[sys.executable, "-m", "gda", …]` (ADR-0011) — the
  interpreter running gda-mcp, hence the *same install*. This preserves this ADR's
  single-version guarantee **structurally**: the adapter and the CLI are one
  distribution, so no CLI/adapter skew is possible. An optional `GDA_BIN` env var
  overrides that command for unusual deployment layouts (e.g. gda installed under a
  different interpreter); it is an **explicit escape hatch**, analogous to `--godot`
  overriding engine resolution (ADR-0006). When set, it can point at a *different*
  `gda` and therefore transfers responsibility for CLI/adapter version alignment to
  the operator — the structural no-skew guarantee holds only for the default. A
  binary the override cannot launch is surfaced as a structured `isError`, never an
  escaping exception (ADR-0011's can't-run edge).
