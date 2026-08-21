---
status: accepted
---

# Workspace members join the single-authority release model

> **Superseded in part (2026-07-20, #528) by
> [ADR-0038](0038-gda-balancing-leaves-the-uv-workspace.md):** the *workspace
> premise* below no longer holds. `libs/gda-balancing` left the uv workspace
> and is now an independent uv project with its own `uv.lock`, so the
> statements here that assume `[tool.uv.workspace]`, a single shared lock, or
> `uv sync --all-packages` are superseded — each is marked inline. The release
> model this record decides (one manifest ledger, per-package components,
> disjoint tags, separate Release PRs) is **unchanged**.

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
  *(Superseded by ADR-0038: there is no single workspace lock any more. Each
  branch now refreshes **both** locks — the root's and the member's — and
  commits whichever changed. The sync-every-branch rule itself stands.)*
- **Because the root absorbs all commits, the non-releasing title discipline
  for member PRs continues after registration**: PRs whose changes live under
  `libs/gda-balancing/**` keep non-bumping conventional-commit types
  (`chore`/`docs`/`refactor`/...) until a member release is deliberately
  wanted. Registration governs the version line; it does not open the release
  train. *(Historical — superseded by the dated **Flip** note in Consequences:
  the member's path is excluded and the discipline is lifted for it. The
  underlying rule still holds for un-excluded paths — a title there must be
  truthful about its effect on `gda`, which means a non-releasing type for
  non-`gda` work such as `examples/**`, and a truthful releasing type for a
  genuine `gda` change.)*
- **Publishing gda-balancing is deferred.** No PyPI publish tail, no trusted
  publisher, no artifact upload. Known dormant consequence, accepted: if a
  member Release PR were merged today, the cut job would leave a tag-less
  draft release with no publish job to complete it — and the release-PR
  maintenance tag gate (#79/#82) only guards the root package's tag. The
  member's first-release issue must wire its publish tail, extend the tag
  gate to its component, and only then may member PRs adopt releasing types.
  *(Historical — all three preconditions were met by #528/#529; see the dated
  **Flip** note in Consequences. Publishing is wired but no member release has
  been cut yet.)*

## Consequences

> **Outcome (2026-07-20, #528):** this record's deferred consequences are
> discharged as follows — one of them only partly, and said so plainly.
> - The root package declares `"exclude-paths": ["libs/gda-balancing"]`, so a
>   commit whose changed files all live under the member's path no longer
>   proposes a root `gda` release.
>   **The exclusion had a verified limit, recorded here rather than glossed:**
>   release-please drops a commit from a package only when *every* changed file
>   is excluded, and its matcher treats each entry as a **directory prefix**
>   (`file.indexOf(path + "/") === 0`) — so a root-level *file* such as the
>   workspace `uv.lock` could not be excluded at all. A member change that also
>   updated the shared lock (a dependency change; #527 is exactly that shape)
>   therefore still counted for the root package.
>   **Resolved by [ADR-0038](0038-gda-balancing-leaves-the-uv-workspace.md)**
>   (same issue, later in the round): the member left the uv workspace and took
>   its lock with it, so there is no longer a root-level file a member change
>   can touch, and the one `exclude-paths` entry now covers the member's whole
>   change surface. The all-files rule still holds, so a releasing-typed member
>   PR must stay inside the member directory — a CI guard asserts that.
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
> **Flip (2026-07-20, #528):** every precondition this record set is now met —
> publish tail wired, tag gate extended, and the `Member releasing-PR scope
> guard` made a **required** status check — so the non-releasing title
> discipline is **lifted for `libs/gda-balancing`**: its PRs use truthful
> `feat`/`fix` types and release on their own train.
>
> Two limits the flip does **not** touch, both still in force:
> - **It is scoped to the excluded path only.** Every un-excluded path is still
>   attributed to the root package, so a title there must honestly describe the
>   change's effect on `gda`: a genuine `gda` feature or fix keeps its truthful
>   releasing type and bumps `gda` — that is the normal release flow
>   (ADR-0007/ADR-0034) — while work that merely *lives* in an un-excluded path
>   without being a `gda` change (`examples/**`, panda) takes a non-releasing
>   type so it does not bump `gda` falsely. The flip changes which paths are
>   attributed to the root, not the rule that the type must be truthful.
> - **A PR spanning the member and anything outside it is still absorbed.** The
>   scope guard refuses such a PR when its title is releasing-typed; split it.
>
> **First-release changelog:** the member's foundation (#502, #504) landed under
> `chore` titles by the very constraint this issue retires, so those commits are
> invisible to release-please's changelog. The first member release therefore
> gets **hand-authored release notes** describing the schema core as a one-time
> cost of the old discipline; every release after it is fully generated.
>
> **First-release changelog outcome (2026-08-21, #528):** the generated
> `gda-balancing` 0.1.0 notes initially listed only the first releasing change,
> #579. Closeout for #528 backfilled the repository changelog and the published
> GitHub Release notes with the #502/#504 foundation summary promised above.
> The tag, package artifacts, version, and release date did not change.


- One ledger now spans both packages; neither `pyproject.toml`, the manifest,
  a `uv.lock`, tags, nor changelogs are hand-versioned for any member.
- The gda pipeline is provably unaffected: its jobs key on the root-scoped
  action outputs, and a (future) member release leaves them all skipped.
- A slipped releasing-typed commit under `libs/` proposes **two** Release PRs
  (member and root). Separate PRs make the mistake recoverable — close the
  unwanted PR(s) and fix the title going forward — instead of releasing both
  from one merge. *(Narrowed by the Outcome note above: a commit confined to
  the member's path now proposes only the member's Release PR. Under ADR-0038 a
  member dependency change is confined too — the shared lock is gone — so this
  bullet now describes a commit that genuinely spans both packages, where
  separate PRs remain the recovery property and a CI guard rejects the shape
  at PR time.)*
- The member's changelog will accumulate at `libs/gda-balancing/CHANGELOG.md`
  once its first releasing commit lands; until then release-please proposes
  nothing for it (its history is non-releasing by discipline). *(The
  parenthetical is historical — the discipline is lifted per the **Flip** note;
  the changelog still starts empty because the pre-flip history is `chore`,
  which is why the first release's notes are hand-authored.)*

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
