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

> **Outcome (2026-07-20, #528):** this record's deferred consequences are
> discharged as follows — one of them only partly, and said so plainly.
> - The root package declares `"exclude-paths": ["libs/gda-balancing"]`, so a
>   commit whose changed files all live under the member's path no longer
>   proposes a root `gda` release.
>   **The exclusion has a verified limit, recorded here rather than glossed:**
>   release-please drops a commit from a package only when *every* changed file
>   is excluded, and its matcher treats each entry as a **directory prefix**
>   (`file.indexOf(path + "/") === 0`) — so a root-level *file* such as the
>   workspace `uv.lock` cannot be excluded at all. A member change that also
>   updates the shared lock (a dependency change; #527 is exactly that shape)
>   therefore still counts for the root package. The absorption fact above is
>   narrowed, not retired.
> - The member's **publish tail is wired**: a mirror of the gda build →
>   PyPI → GitHub-release chain keyed on the path-prefixed cut outputs, with
>   its own PyPI trusted publisher under the **distinct** `pypi-gda-balancing`
>   environment (a shared environment would let either product's publish job
>   mint a token for the other, since the OIDC trust tuple is
>   owner/repo/workflow/environment). The member's GitHub release un-drafts
>   with `--latest=false` so the repo-global Latest badge stays on gda (#87).
> - The **tag gate now covers every manifest package**, skipping any component
>   still at the `0.0.0` placeholder: that version is an unambiguous
>   never-released marker (release-please's first bump cannot produce it), and
>   requiring a tag that cannot exist yet would deadlock both trains.
>
> Remaining before member PRs may adopt releasing types: the title-discipline
> flip itself, tracked on #528. Until then the discipline stays in force.


- One ledger now spans both packages; neither `pyproject.toml`, the manifest,
  `uv.lock`, tags, nor changelogs are hand-versioned for any member.
- The gda pipeline is provably unaffected: its jobs key on the root-scoped
  action outputs, and a (future) member release leaves them all skipped.
- A slipped releasing-typed commit under `libs/` proposes **two** Release PRs
  (member and root). Separate PRs make the mistake recoverable — close the
  unwanted PR(s) and fix the title going forward — instead of releasing both
  from one merge. *(Narrowed by the Outcome note above: a commit confined to
  the member's path now proposes only the member's Release PR. This bullet
  still describes a member commit that also touches a root-level file such as
  the shared lock, where separate PRs remain the recovery property.)*
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
