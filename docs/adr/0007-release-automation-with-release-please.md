---
status: accepted
---

# Release automation with release-please

Releasing required manually coordinating three steps: bump the
`pyproject.toml` version via PR, create a `v*` tag that exactly matches it,
and push the tag to trigger the release workflow. The workflow carried a
dedicated validation step ("tag must equal `v{version}`") precisely because
that coordination is a known failure mode. At the same time the repo already
enforces strict conventional commits — the raw material for computing version
bumps and changelogs mechanically — and maintained no `CHANGELOG.md`.

## Decision

**Releases are driven by [release-please](https://github.com/googleapis/release-please)
(manifest mode, `release-type: python`), and the human release action is
merging its Release PR.**

On every push to `main`, release-please parses conventional commits since the
last release and maintains a Release PR holding the computed version bump
(`pyproject.toml`), an updated `CHANGELOG.md`, and the release notes. Merging
that PR creates a **draft** GitHub release; the same workflow then runs the
full test suite (unit + Godot e2e) against the release commit, builds
distributions with `uv build`, uploads them, and publishes the draft. A
release is therefore never published without green tests and attached
artifacts.

Pre-1.0 bump semantics follow the SemVer 0.x convention via
`bump-minor-pre-major` + `bump-patch-for-minor-pre-major`: breaking changes
bump minor, `feat`/`fix` bump patch. Nothing crosses 1.0 until we say so with
`release-as`.

The build chain lives in the **same workflow** as release-please, gated on its
`release_created` output, because tags created with the default `GITHUB_TOKEN`
do not trigger other workflows (GitHub's recursion guard). For the same reason
no PAT is introduced: the default token suffices to open the Release PR, and a
long-lived credential is a cost we do not need to pay.

A `workflow_dispatch` escape hatch retains the previous manual semantics:
given an existing tag, it runs the same verify-and-build chain and creates a
release from that tag.

## Consequences

- The version/tag mismatch failure mode is gone by construction; the tag
  validation step survives as an invariant check, not a human guard.
- `CHANGELOG.md` becomes a maintained artifact, generated from the commit
  history agents already write.
- The human review gate moves earlier: from "publish the draft release" to
  "review and merge the Release PR", where the version bump and changelog are
  visible before anything happens.
- Pushing a `v*` tag no longer triggers a release. The only release paths are
  merging the Release PR and the manual `workflow_dispatch` escape hatch.
- CI's `pull_request` jobs do not run on the Release PR (same `GITHUB_TOKEN`
  recursion guard). Acceptable: it touches only version and changelog. If
  branch protection ever requires checks on it, switch the action's token to a
  GitHub App token.
- Release cadence is decoupled from commit cadence: the Release PR accumulates
  changes until someone decides to merge it.

## Considered options

- **release-please** (chosen) — the only option in this space whose core is a
  reviewable Release PR; preserves a human gate while removing the manual
  version/tag coordination, and the repo's commit discipline already satisfies
  its one precondition.
- **semantic-release** — releases on every push to the default branch with no
  review gate; incompatible with the project's human-in-the-loop style.
- **release-drafter** — only drafts release notes; does not manage versions or
  tags, so the core failure mode remains.
- **Status quo (manual tagging)** — sound (validated, draft-gated) but keeps
  the manual three-step coordination and leaves the changelog unmaintained.
