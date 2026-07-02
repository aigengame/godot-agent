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

> **Superseded in part by [ADR-0034](0034-pre-1.0-feature-bumps-minor.md):**
> `bump-patch-for-minor-pre-major` is removed, so pre-1.0 a `feat` now bumps the
> **minor** and only a `fix` bumps the patch. `bump-minor-pre-major` and the
> "nothing crosses 1.0 without `release-as`" rule are unchanged.

The build chain lives in the **same workflow** as release-please, gated on its
`release_created` output, because tags created with the default `GITHUB_TOKEN`
do not trigger other workflows (GitHub's recursion guard). For the same reason
no PAT is introduced: the default token suffices to open the Release PR, and a
long-lived credential is a cost we do not need to pay.

Within that workflow, **release-please itself runs twice**, bracketing the
verify-and-build chain: a release-cutting invocation before it and a
release-PR-maintenance invocation after the publish. A draft release carries
no git tag until it is published, and release-please's lookback is tag-based —
so computing the next Release PR while the just-cut release is still a draft
reads the entire history as unreleased and proposes a spurious full-history
release (#79). Bracketing alone only fixes the happy path: the hazardous state
survives a failed run, so maintenance additionally **gates on the manifest
version's tag actually existing** and is skipped (with a warning annotation)
when it does not — that gate, not the bracketing, is what stops a later push
from regenerating the spurious Release PR across runs (#82). Two further
guards harden the chain: the build job checks out the exact commit
release-please tagged rather than the push HEAD, so concurrent pushes cannot
publish artifacts from the wrong commit (#83); and the publish is idempotent so
a re-run recovers a partial publish (#84).
(A third guard, an isolated concurrency lane for manual dispatch (#85), is
[superseded by ADR-0008](0008-single-authoritative-version-source.md): with the
manual escape hatch retired the lane was removed, and the release workflow's
concurrency group reverted to the simple `${{ github.workflow }}-${{ github.ref }}`
form.)

A `workflow_dispatch` escape hatch retains the previous manual semantics:
given an **existing** tag, it runs the same verify-and-build chain and creates
a release from that tag. It is deliberately *not* the recovery path for a
failed automated release (which leaves a tag-less draft) — see "Failure
handling and recovery" below.

> **Superseded by [ADR-0008](0008-single-authoritative-version-source.md):**
> the manual escape hatch is retired. release-please is the single version
> authority and merging the Release PR is the only release path; forcing a
> version uses `release-as`, and recovery uses "Re-run failed jobs".

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
  ([ADR-0008](0008-single-authoritative-version-source.md) retires the escape
  hatch — merging the Release PR is now the only release path.)
- CI's `pull_request` jobs do not run on the Release PR (same `GITHUB_TOKEN`
  recursion guard). Acceptable: it touches only version and changelog. If
  branch protection ever requires checks on it, switch the action's token to a
  GitHub App token.
- Release cadence is decoupled from commit cadence: the Release PR accumulates
  changes until someone decides to merge it.
- PRs are merged **squash-only** (repo setting). With merge commits,
  release-please counted both the PR title and every conventional commit inside
  the merge, double-listing each PR in the changelog — the 0.1.1 changelog
  carries these historical duplicates. The squash commit title is forced to the
  PR title (which must therefore be a conventional commit message) and the body
  is left blank, so a squashed body can never be re-parsed into phantom
  changelog entries. A breaking change is flagged with `!` in the PR title.
- The 0.1.2 and 0.1.3 releases are spurious — produced by the draft-tag race
  before release-please was split into two invocations (#79). They are kept
  (fix-forward); their changelog sections are reduced to one-line notes.

## Failure handling and recovery

The pipeline has one state that is not self-healing: a **wedged tag-less
draft**. If the verify-and-build chain fails (or is cancelled) after the
release was cut, the draft GitHub release exists but was never published, so it
has no git tag; meanwhile release-please has already relabelled the merged
Release PR `autorelease: tagged` (so it is never re-cut) and the manifest on
`main` is ahead of every tag.

**Recognising it.** The release-PR-maintenance job emits a warning annotation
("Release pipeline needs recovery…") whenever the manifest version's tag is
absent, and skips maintenance. A persistent such warning on ordinary pushes
means a release is wedged.

**Recovering it — re-run, do not improvise.** Open the failed release run and
use **"Re-run failed jobs"**. The build job rebuilds and the publish is
idempotent (`--clobber` upload, plus an already-no-op un-draft), so the re-run
converges to a published release, which creates the tag and unwedges
maintenance. Do **not** hand-push the tag — `gh release create` would then mint
a *second* release for that tag name beside the orphaned draft, leaving two
releases sharing one tag. (Before [ADR-0008](0008-single-authoritative-version-source.md)
this also warned against the `workflow_dispatch` escape hatch, now retired.)

If the cut release is unwanted, delete the draft release and revert the
manifest/`CHANGELOG` bump so the Release PR returns to `autorelease: pending`.

**Known narrow windows** (low probability, documented rather than guarded):

- *Non-atomic cut.* release-please creates the draft and then relabels the PR;
  a crash in between leaves a `pending` PR with a draft already created, so the
  next run cuts a duplicate tag-less draft for the same version.
- *Multiple pending Release PRs.* If more than one merged Release PR is pending
  when a single run cuts, multiple drafts are created but only one tag is
  published, so an orphaned draft can re-wedge the lookback. In a single-package
  repo this requires an abnormal precondition (an earlier cut that crashed, or
  concurrency queue replacement).

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
