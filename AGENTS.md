## Primary

Read @RULES.md if exists, to align communication style, collaboration specification, as well as other matters.

Read @CONTEXT.md to align with the project's nature and shared language; consult `docs/adr/` for the architecture and the decisions behind it. README.md is human-facing onboarding (install, usage, contributing) and has grown large — read specific sections on demand (e.g. its "Project status" section for current state) rather than the whole file.

Read @STATE.md and @PITFALLS.md if they exist.

The primary worker maintains `STATE.md` through the `state` skill and `PITFALLS.md`
through the `pitfalls` skill. Parallel subagents and sub-tasks treat both files as
read-only and report state changes or candidate pitfalls to the primary worker.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues in `aigengame/godot-agent` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, default label names. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context: `CONTEXT-MAP.md` at the repo root is the routing authority — one entry per
domain context. The root's own context is the `gda` domain (`CONTEXT.md` + `docs/adr/`);
each non-root domain declares its layout and override rules in its own `AGENTS.md`. See
`docs/agents/domain.md`.
