---
status: accepted
---

# `gda skill --install --provider <agent> --scope <scope>`: a known-agent install convenience

[ADR-0024](0024-gda-skill-channel-and-distribution.md) shipped `gda skill` and decided that
**core carries no agent-specific default install location**: a plain `gda skill` prints the
manifest, and `--install` requires an explicit `--dir`. The per-agent target directory (Claude
Code's `.claude/skills/`, the cross-agent `.agents/skills/`, …) was documented in
`docs/gda-skill.md`, *not* defaulted in core. That keeps the default neutral, but it pushes a
rote lookup onto every user: to install, you must first go read which directory your agent scans
and type it out. This ADR adds a convenience that removes the lookup **without** giving up the
neutral default.

## Decision

**Name a known agent instead of a directory.** `gda skill --install` gains two optional params:
`--provider <agent>` (a closed set — currently `claude`, `codex`) and `--scope <project|user>`
(default `user`). When `--provider` is given, `gda` resolves that agent's skills directory at the
chosen scope and installs there, reusing the exact `--dir` write path. `--provider` implies
`--install` (as `--dir` already does), and `--dir` and `--provider` are **mutually exclusive** —
they name the same target two ways.

| provider | `--scope project` (CWD-relative) | `--scope user` (under `$HOME`) |
| --- | --- | --- |
| `claude` | `.claude/skills/gda` | `~/.claude/skills/gda` |
| `codex`  | `.agents/skills/gda` | `~/.agents/skills/gda` |

Codex follows the cross-agent **Agent Skills** namespace `.agents/skills` (per OpenAI's Codex
docs), **not** `.codex/skills`; the `gda/` leaf is the skill's own directory
(`<base>/gda/SKILL.md`), the layout `docs/gda-skill.md` already documents.

**This extends ADR-0024, it does not reverse it.** The default behaviour is unchanged: plain
`gda skill` and a bare `--install` still carry no built-in path, the `SKILL.md` content stays
agent-neutral, and `--dir` remains the general, vendor-neutral escape hatch for any agent — listed
here or not. The agent→directory table is the *one* piece of vendor knowledge admitted into core,
quarantined to a single module (`gda/skill_targets.py`) and reachable **only** when the caller
explicitly opts in by naming a provider. It is best-effort and may lag an agent's upstream change;
`--dir` is always the fallback.

**One normalization point.** `--provider`/`--scope` resolve to `install_dir` inside `SkillParams`
(the model), so the argv flags and a `--params-json` object produce identical params and the same
install — the same single-source-of-truth seam ADR-0015 draws for every command. `provider` and
`scope` therefore appear as enum-constrained fields in `gda skill --schema`, so **gda-mcp generates
a closed-choice tool** (`skill(provider=…, scope=…)`) with no skill-specific code (ADR-0011/0012).

## Considered options

- **Keep core neutral, docs only (rejected).** Honours ADR-0024 to the letter but leaves the rote
  per-agent lookup in place — the usability gap this ADR exists to close.
- **A general default install location in core (rejected).** Reintroduces exactly the agent-specific
  default ADR-0024 refused, and for the *default* path, not an opt-in one.
- **`--provider` as the value of `--install` (rejected).** `gda skill --install claude` reads well
  but turns `--install` from a boolean into a value option, breaking the existing
  `gda skill --install --dir <path>` form. A separate `--provider` is additive and backward-compatible.
- **A known-agent table behind an explicit `--provider`, `--dir` as the neutral fallback (chosen).**

## Consequences

- The vendor table lives only in `gda/skill_targets.py`; adding an agent is a one-line table entry,
  and `--dir` covers any agent absent from it, so the closed `--provider` set never blocks a user.
- `--scope` is agent-neutral (it only toggles project-local vs. user-level); a project-scope install
  resolves against the CWD, so the reported `installed_path` is relative — consistent with a relative
  `--dir`.
- `docs/gda-skill.md` and the README "Use it as a Skill" section document the convenience alongside
  the still-supported `--dir` and raw-`curl` paths; ADR-0024 carries a dated note pointing here.
