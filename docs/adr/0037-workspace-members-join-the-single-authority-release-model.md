---
status: accepted
---

# Workspace members join the single-authority release model

The repo becomes a uv workspace with #502: `libs/gda-balancing` is wired in as
an independently versioned member (a sibling product; not a `gda` dependency).
ADR-0008 made release-please the single authority for *the* version — written
when the repo held exactly one package. A second package must not reintroduce
the two-authority problem ADR-0008 removed, and its releases must not be able
to trigger the root `gda` publish pipeline.

Two facts verified against release-please's documentation shape this decision:

- **Per-path outputs, unprefixed root.** With a multi-package manifest the
  action emits `<path>--*` outputs per non-root path while the root (`.`)
  component keeps its *unprefixed* `release_created`/`tag_name`/`sha` outputs.
  The existing release workflow reads the unprefixed outputs, so its entire
  gda build → publish → GitHub-release tail is already root-scoped.
- **The root package absorbs all commits.** Release-please attributes a commit
  to the root `"."` package whenever it touches *anything* in the repo —
  including files under another package's path. A releasing-typed commit that
  only touches `libs/gda-balancing/**` would therefore also propose a root
  `gda` release.

## Decision

**Every workspace member's version line is governed by release-please under
ADR-0008's single-authority rule: one manifest ledger, per-package components,
separate release trains, and no hand-edited version anywhere.**

- `.release-please-manifest.json` gains a `libs/gda-balancing` entry (starting
  at the `0.0.0` placeholder); the member's `pyproject.toml` version is a
  release-please-authored output from now on, exactly like the root's.
- The member releases under its own component and tag scheme:
  `component: gda-balancing`, `include-component-in-tag: true` → tags
  `gda-balancing-vX.Y.Z`. The root keeps its component-less `vX.Y.Z` tags, so
  the two tag namespaces cannot collide.
- `separate-pull-requests: true`: each package gets its own Release PR, so
  merging one package's release can never release the other.
- The release workflow's uv.lock sync iterates **all** Release PR branches:
  the single workspace lock records every member's version, so a member
  Release PR needs the same sync the root needed (#97).
- **Because the root absorbs all commits, the non-releasing title discipline
  for member PRs continues after registration**: PRs whose changes live under
  `libs/gda-balancing/**` keep non-bumping conventional-commit types
  (`chore`/`docs`/`refactor`/...) until a member release is deliberately
  wanted. Registration governs the version line; it does not open the release
  train.
- **Publishing gda-balancing is deferred.** No PyPI publish tail, no trusted
  publisher, no artifact upload. Known dormant consequence, accepted: if a
  member Release PR were merged today, the cut job would leave a tag-less
  draft release with no publish job to complete it — and the release-PR
  maintenance tag gate (#79/#82) only guards the root package's tag. The
  member's first-release issue must wire its publish tail, extend the tag
  gate to its component, and only then may member PRs adopt releasing types.

## Consequences

> **Outcome (2026-07-20, #528):** the root package now declares
> `"exclude-paths": ["libs/gda-balancing"]` (mechanism verified against
> release-please's manifest documentation), so a releasing-typed commit that
> only touches the member's path no longer proposes a root `gda` release —
> retiring the absorption fact above and the two-Release-PR slip mode below.
> The member's **non-releasing title discipline stays in force**: this ADR's
> flip precondition (wire the publish tail, extend the tag gate to the member
> component) is unchanged and tracked on #528.


- One ledger now spans both packages; neither `pyproject.toml`, the manifest,
  `uv.lock`, tags, nor changelogs are hand-versioned for any member.
- The gda pipeline is provably unaffected: its jobs key on the root-scoped
  action outputs, and a (future) member release leaves them all skipped.
- A slipped releasing-typed commit under `libs/` proposes **two** Release PRs
  (member and root). Separate PRs make the mistake recoverable — close the
  unwanted PR(s) and fix the title going forward — instead of releasing both
  from one merge.
- The member's changelog will accumulate at `libs/gda-balancing/CHANGELOG.md`
  once its first releasing commit lands; until then release-please proposes
  nothing for it (its history is non-releasing by discipline).

## Considered options

- **Register the member with its own component + separate PRs** (chosen) —
  single authority extends unchanged; tag namespaces disjoint; release trains
  independent; smallest workflow surgery (only the lock sync generalizes).
- **Keep the member out of release-please** — its `0.0.0` would be hand-owned,
  a second version authority by omission; the first release would then need a
  retroactive ledger entry — exactly the desync class ADR-0008 retired.
- **One combined Release PR for both packages** (release-please default) —
  fewer PRs, but merging it releases whatever it contains; a slipped member
  commit would ride the next gda release irrevocably instead of sitting in a
  closable PR of its own.
