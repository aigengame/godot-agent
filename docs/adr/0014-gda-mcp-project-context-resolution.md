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
as ADR-0006 specifies. gda-mcp resolves one target project for the server and hands it
to its `gda` subprocesses through gda's own **`GDA_PROJECT`** channel (ADR-0006) — set
on the subprocess environment, **not** a `--project` flag. The env channel applies
uniformly: project-taking domain commands consume it, while meta commands (`info`) that
take no project simply ignore it — so gda-mcp needs no per-command knowledge of which
commands accept a project, and a `--project` flag (which meta commands reject outright)
is never forged.

**Resolution is by a portable precedence, with cwd only as a last resort** — because
the launch working directory is not reliably the project across MCP clients (clients
differ in whether the operator can set it, and several leave it at an arbitrary launch
directory or undefined). The precedence names only agent-neutral primitives — gda's own
env, the MCP protocol's own workspace signal, and cwd; how any specific agent is
configured to supply them belongs to the registration recipes (ADR-0013), not here.
gda-mcp resolves, first hit wins:

1. an explicit **`GDA_PROJECT`** in the server's environment — the operator pins it in
   the MCP server's `env` config; the neutral, agent-independent anchor,
2. the MCP **`roots/list`** the client advertises — the protocol-native workspace signal,
3. the process **cwd**, as a last-resort fallback.

**A candidate is asserted as the project only when it is a valid Godot project** (it
contains `project.godot`). gda-mcp does **not** promote an unvalidated cwd or root,
because ADR-0006 gives `$GDA_PROJECT` strict semantics (must be a real project) while
leaving cwd lenient. So a validated `roots` or cwd candidate is exported as
`GDA_PROJECT=<dir>` on the subprocess; if nothing resolves to a valid project, gda-mcp
sets **no** `GDA_PROJECT` and lets `gda` apply its own ADR-0006 resolution over the
inherited environment — including running projectless when neither `$GDA_PROJECT` nor
the cwd is a project. An explicitly set but **invalid** `GDA_PROJECT` is left untouched
in the inherited environment (not silently shadowed by a roots/cwd candidate), so `gda`
surfaces its own strict typed error for project-taking commands. gda-mcp does not itself
reject projectless operation; an op that requires a project surfaces `gda`'s own typed
error, relayed unchanged.

## Considered options

- **Per-call `project` tool parameter (rejected for now).** Lets one user-scoped
  server target any project per call, but (a) deviates from ADR-0006 (project becomes
  an operation parameter) and (b) breaks ADR-0012's pure transform — gda-mcp would
  synthesize a field absent from `--schema` into every tool. Not worth it for the
  first delivery; project-scoped registration covers the common workflow.
- **cwd as the primary signal (rejected).** The obvious choice, but unusable: most MCP
  clients can't set it reliably or leave it undefined. Demoted to last-resort fallback.
- **Server context via a portable precedence (chosen).**

## Consequences

- **Recommended registration is project-scoped** (or with `GDA_PROJECT` pinned),
  giving one server : one project — the clean, ADR-0006-aligned mode.
- A **user-scoped** server with nothing pinned falls back through `roots/list` / cwd;
  it works for the single-active-project workflow but cannot, in this first delivery,
  follow a user juggling several projects in one session.
- The `roots/list` read (precedence 2) is part of the resolution contract, not a
  staged extra — the first delivery implements the full precedence above. Because
  `roots/list` is a server→client request that needs a live session, it cannot run
  at process startup; resolution is **snapshotted on the first tool call** and then
  cached for the server's lifetime (one server : one project). Re-resolving when the
  client's active root changes is the deferred `roots/list_changed` path below.
- **No vendor coupling in the core.** This ADR names no specific agent; per-agent
  registration — how each agent's config sets the server's `env` / launch command and
  pins the project — is the registration recipes' concern (ADR-0013), which must cover
  several top agents rather than privilege one. Keeping vendor specifics out of the
  resolution contract is what lets gda-mcp stay an independent, consumer-agnostic service.
- **Future multi-project without a tool parameter:** honour MCP `roots/list_changed`
  to re-resolve when the client's active root changes — the MCP-native path to
  multi-project support that still keeps the project out of the tool surface. This
  *dynamic* re-resolution (not the static `roots/list` read) is the piece deferred
  until a concrete need appears, and is out of scope for the first delivery per PRD #8.
