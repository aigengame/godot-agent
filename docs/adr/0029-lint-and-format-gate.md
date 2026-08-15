---
status: accepted
---

# Lint and format gate: ruff (`check` + `format`), enforced in CI

CI ([`ci.yml`](../../.github/workflows/ci.yml)) ran only `pytest -m "not e2e"` + `uv build`
(+ a nightly e2e job) — **no lint or format gate**. Ruff was already used ad-hoc locally via
`uvx` (a stray `.ruff_cache/`, versions 0.15.16 → 0.15.19, was the evidence) but it was
**unconfigured, unpinned, and unenforced**: no `[tool.ruff]` config, no declared dependency,
nothing to catch a finding on a PR. Style and lint therefore drifted silently. The repo
already records CI/infra decisions as ADRs ([ADR-0007](0007-release-automation-with-release-please.md)
release automation, [ADR-0016](0016-publish-to-pypi-via-trusted-publishing.md) PyPI
publishing), so the choice of *what* gate to add — and what to leave out — belongs in the
record too.

## Decision

**Enforce a lint + format gate with ruff alone (`ruff check` + `ruff format`), in CI only.**

- **One tool, one config.** Ruff subsumes flake8 + black + isort, so none of those are added.
  A single `[tool.ruff]` block in `pyproject.toml` is the authoritative config — consistent
  with the project's single-authoritative-source habit, and faster than a multi-tool stack.

- **A parallel `lint` CI job.** It runs `ruff check .` then `ruff format --check .`, reusing
  the `setup-python-env` composite. It runs alongside the `python` job (fails fast,
  independent signal) and sets `save-cache: false` because the `python` job already populates
  that dependency-cache key — this job only reads it.

- **ruff is a pinned dev dependency, locked in `uv.lock`.** `ruff format`'s output can shift
  between versions, so the exact version is locked and CI resolves it with `uv sync --frozen`.
  Local and CI then agree byte-for-byte — closing the version-drift the stray cache showed. A
  ruff upgrade becomes a deliberate `uv.lock` bump, reviewed (and re-formatted) as its own
  change rather than surprising a PR.

- **Rule set = ruff's default high-signal `E4/E7/E9/F`, made explicit.** Deliberately *not*
  full `E`: the `E1/E2/E3/E5` whitespace and line-length rules are owned by the formatter, and
  enabling them fights `ruff format`. `F811` is ignored for [`src/gda/cli.py`](../../src/gda/cli.py):
  Typer attaches same-named subcommands (`create`, `get`, …) to different sub-apps, so reusing
  the function name is intentional — the descriptor-driven command surface
  ([ADR-0023](0023-command-descriptor-single-registration.md)) — and F811 "redefinition" is a
  false positive for that idiom.

  > **Outcome (2026-08-15, [ADR-0040](0040-per-command-group-modules.md)):** the per-file
  > ignore was removed with the per-command-group split — command function names are unique
  > per group module, so `cli.py` no longer redefines names.

- **CI-only enforcement.** No pre-commit hook: developers run `uv run ruff format .` locally,
  and the CI `lint` job is the authoritative backstop. The gate adds no new local-tooling
  framework or convention the repo does not already have.

## Considered options

- **ruff only (chosen).** One binary, one config, formatter + linter + import-sort in a single
  fast pass; pins cleanly via `uv.lock`.
- **black + flake8 (+ isort) (rejected).** Three tools, three configs to keep coherent, slower,
  and redundant with ruff — the opposite of the single-source habit.
- **A broader rule set — `B` (bugbear), `UP` (pyupgrade), `I` (isort), or full `E` (deferred).**
  Full `E` conflicts with the formatter; the others add value but also one-time churn and
  judgement calls. Start with the high-signal default and **ratchet later** (a config-only
  change) rather than land a large reformat and a rule expansion at once.
- **Also add a pre-commit hook (deferred).** Better local feedback, but it introduces the
  pre-commit framework and a new contributor convention the repo lacks today; the CI gate
  already guarantees correctness. Revisit if local friction shows up.
- **Gate GDScript too, via gdtoolkit (`gdlint`/`gdformat`) (deferred).** Only two `.gd` files
  exist (the [gda harness](../../CONTEXT.md)); a separate Godot-ecosystem toolchain for that is
  out of scope this round and can be its own decision if the GDScript surface grows.

## Consequences

- A one-time mechanical normalization precedes the gate: `ruff format` over the tree (81 files)
  plus fixing the 5 real findings ruff reported (4 × `F401` unused import, 1 × `F841` unused
  local). Landed as a separate `style:` commit so the gate-enabling diff stays reviewable.
- The `cli.py` `F811` per-file-ignore also masks a *genuine* accidental redefinition in that
  file. Accepted: `cli.py` is the command-registration module, full of intentionally same-named
  commands, so the idiom dominates; a stray real redefinition there would surface as a failing
  command, not silently.
  > **Outcome (2026-08-15, [ADR-0040](0040-per-command-group-modules.md)):** this risk ended
  > when the ignore was removed — `F811` now covers `src/` without exception.
- [README](../../README.md) documents the gate (the **Development** and **Contributing**
  sections) — `ruff check` / `ruff format` commands and the CI job. No new
  [CONTEXT.md](../../CONTEXT.md) term: a lint gate is build tooling, not a domain concept.
- Implemented and verified in PR #305 (tracked by #306): the `lint` job is green, `ruff check`
  and `ruff format --check` pass under the locked version, a negative test confirms the gate
  blocks a bad file, and `pytest -m "not e2e"` is unaffected.
