## Primary

Read @RULES.md if exists, to align communication style, collaboration specification, as well as other matters.

Read @CONTEXT.md to align with the project's nature and shared language; consult `docs/adr/` for the architecture and the decisions behind it. README.md is human-facing onboarding (install, usage, contributing) and has grown large — read specific sections on demand (e.g. its "Project status" section for current state) rather than the whole file. README.md is the authoritative source; its translations live under `docs/README.<lang>.md` and are gated by `tests/test_readme_i18n_sync.py`. When you edit README.md, re-translate the affected sections and run `uv run python scripts/update_readme_i18n.py` to re-stamp the freshness markers.

Read @STATE.md if exists for the latest session state — a lightweight cross-session daily report (≤10 lines): current milestone/phase, what the last session did, pitfalls worth reusing, and recommended next issues/tasks. Treat it as read-only startup context. Only the **primary worker** updates it, at session end, via the `state` skill; parallel sub-agents and sub-tasks must not write it.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues in `aigengame/godot-agent` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, default label names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
