## Primary

Read @RULES.md if exists, to align communication style, collaboration specification, as well as other matters.

Read @CONTEXT.md to align with the project's nature and shared language; consult `docs/adr/` for the architecture and the decisions behind it. README.md is human-facing onboarding (install, usage, contributing) and has grown large — read specific sections on demand (e.g. its "Project status" section for current state) rather than the whole file.

Read @STATE.md if exists for the latest session state — a lightweight cross-session daily report; the `state` skill is the single authority for its format and fields. Treat it as read-only startup context. Only the **primary worker** updates it, at session end, via the `state` skill; parallel sub-agents and sub-tasks must not write it.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues in `aigengame/godot-agent` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, default label names. See `docs/agents/triage-labels.md`.

### Domain docs

One `CONTEXT.md` + `docs/adr/` at the repo root — the `gda` domain. Two subtrees carry
their own local domain contexts (overrides declared in their own `AGENTS.md`):
`examples/platformer/panda-adventure/` (game domain) and `libs/gda-balancing/`
(balancing-toolkit domain). See `docs/agents/domain.md`.
