---
status: accepted
---

# Single authoritative version source; retire the manual release path

ADR-0007 left two ways to release: the automated release-please path and a
manual `workflow_dispatch` escape hatch that releases an existing tag. They
carry **different version authorities**, and the manual one is inconsistent
with release-please's bookkeeping:

- On the **automated** path release-please is the sole author. It computes the
  next version from `.release-please-manifest.json` (the ledger of what was
  last released) plus the conventional commits, and writes that version into
  `pyproject.toml`, the manifest, and `CHANGELOG.md` together; the tag is
  derived at publish. Everything is consistent by construction — except
  `uv.lock`, whose editable `gda` self-version release-please never updates, so
  it drifts every release (#97).
- On the **manual** path the human is the authority: they bump `pyproject.toml`
  and push a matching tag, and the workflow only *validates* `tag == v{version}`.
  Crucially it **does not touch the manifest**. Since release-please's lookback
  is tag-based but anchored to the manifest version, a manual release leaves
  the ledger stale, and the next push makes release-please treat the
  already-released commits as unreleased and re-propose them.

Two authorities, one of which corrupts the other's ledger, is the root of the
version-consistency problem — not merely the `uv.lock` drift.

## Decision

**release-please is the single authority for the version, with
`.release-please-manifest.json` as the ledger; every version-bearing file is a
release-please-authored output. The manual `workflow_dispatch` escape hatch is
retired.**

- All version-bearing artifacts — `pyproject.toml`, the manifest, `uv.lock`,
  the git tag, `CHANGELOG.md` — are produced or derived by release-please. No
  file is hand-edited to set a version. `uv.lock` is brought under this rule by
  regenerating it on the Release PR branch so its `gda` self-version tracks the
  bumped `pyproject.toml` in the same PR (#97).
- The only release path is **merging the Release PR**. The two needs the manual
  path historically served are met within the automated model:
  - *Force a specific version* → release-please's `release-as` (a one-off
    config entry), not a hand-pushed tag.
  - *Recover a failed/partial release* → "Re-run failed jobs" on the release
    run, made reliable by the idempotent publish (ADR-0007, #84).
- There is no standing manual release path. A genuine break-glass (main or the
  release-please config itself unusable) is handled by fixing forward; if an
  out-of-band release is ever unavoidable it must also reconcile the manifest,
  precisely the coupling this decision removes from the everyday path.

## Consequences

- One authority, one ledger: the manifest-desync failure mode is gone, and the
  three version sources (`pyproject.toml`, manifest, `uv.lock`) cannot drift.
- The Release workflow loses its `workflow_dispatch` trigger and the
  `github-release` branches, inputs, dispatch-only concurrency lane, and
  empty-tag guard that served it (ADR-0007's #85/#87 hardening of the manual
  path becomes moot and is removed).
- ADR-0007's escape-hatch statements are superseded by this ADR: the "only
  release paths" are now merging the Release PR (the manual path is gone), and
  the failure-recovery guidance no longer needs to warn against the escape
  hatch.
- Releasing an arbitrary historical tag with no GitHub Release is no longer a
  one-click action; it was never an everyday need and `release-as` covers
  intentional version targeting.

## Considered options

- **Single authority, retire the manual path** (chosen, Option A) — one author
  for every version file; `release-as` + re-run cover the manual path's real
  uses; simplest and removes the desync vector. Cost: no one-click break-glass,
  accepted as rare and fixable forward.
- **Keep the manual path but make it consistent** (Option C) — have it also
  write the manifest, `pyproject.toml`, and `uv.lock`. Preserves break-glass
  but duplicates release-please's bookkeeping in a second code path that must
  be kept in lockstep — the maintenance cost the single-authority model exists
  to avoid.
- **Keep the manual path, document the caveat** (Option B) — retain it as a
  break-glass and warn that it desyncs the manifest. Cheapest, but leaves a
  footgun whose misuse silently re-proposes released commits.
