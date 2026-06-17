---
status: accepted
---

# gda-mcp project-context resolution: server context, not a tool parameter; resolved by a portable precedence because cwd is unreliable

ADR-0006 makes the target project **process context** for `gda`
(`--project` flag → `$GDA_PROJECT` → cwd), deliberately kept out of `--schema` input
and therefore out of any tool's inputSchema. ADR-0012 makes [gda-mcp](../../CONTEXT.md)
a pure schema→tool transform. This ADR fixes how gda-mcp — a long-lived server serving
many calls — determines which Godot project its `gda` subprocesses act on, without
breaking either decision.

## Decision

**The target project is server context, not a per-call tool parameter.** gda-mcp does
**not** inject a `project` field into any tool's inputSchema; the tool surface stays a
faithful mirror of `--schema` (ADR-0012), and `gda` still receives the project exactly
as ADR-0006 specifies. gda-mcp resolves one target project for the server and passes
it as `--project` to every `gda` subprocess it spawns.

**Resolution is by a portable precedence, with cwd only as a last resort** — because
the launch working directory is not reliably the project across agents (Claude Code
ignores a configured `cwd`, claude-code#17565; Cursor / Claude Desktop leave it at the
launch dir or undefined `/`; only Codex sets it reliably). gda-mcp resolves, first hit
wins:

1. an explicit **`GDA_PROJECT`** in the server's environment (the user pins it in any
   agent's `env` / TOML; Cursor can inject `${workspaceFolder}`),
2. **`CLAUDE_PROJECT_DIR`** (Claude Code sets this in the server env to the project
   root, for free),
3. the MCP **`roots/list`** the client advertises (Claude Code populates it with the
   launch dir),
4. the process **cwd**, as a last-resort fallback.

The resolved path is passed as `gda --project <dir>`.

## Considered options

- **Per-call `project` tool parameter (rejected for now).** Lets one user-scoped
  server target any project per call, but (a) deviates from ADR-0006 (project becomes
  an operation parameter) and (b) breaks ADR-0012's pure transform — gda-mcp would
  synthesize a field absent from `--schema` into every tool. Not worth it for the
  first delivery; project-scoped registration covers the common workflow.
- **cwd as the primary signal (rejected).** The obvious choice, but unusable: three of
  four agents can't set it or leave it undefined. Demoted to last-resort fallback.
- **Server context via a portable precedence (chosen).**

## Consequences

- **Recommended registration is project-scoped** (or with `GDA_PROJECT` pinned),
  giving one server : one project — the clean, ADR-0006-aligned mode.
- A **user-scoped** server with nothing pinned falls back through `CLAUDE_PROJECT_DIR`
  / `roots/list` / cwd; it works for the single-active-project workflow but cannot, in
  this first delivery, follow a user juggling several projects in one session.
- **Future multi-project without a tool parameter:** honour MCP `roots/list_changed`
  to re-resolve when the client's active root changes — the MCP-native path to
  multi-project support that still keeps the project out of the tool surface. Deferred
  until a concrete need appears. (The startup `roots/list` read at precedence 3 may
  itself be staged after the env-based resolution in the first slice.)
