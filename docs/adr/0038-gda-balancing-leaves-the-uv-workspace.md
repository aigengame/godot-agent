---
status: accepted
---

# gda-balancing leaves the uv workspace and releases from its own project boundary

[ADR-0037](0037-workspace-members-join-the-single-authority-release-model.md)
registered `libs/gda-balancing` as a release-please package while it remained a
**uv workspace member** of the root `gda` project, and recorded the consequence
that the root `"."` package absorbs every commit: release-please attributes a
commit to the root whenever it touches anything in the repo. #528 tried to
retire that absorption with `"exclude-paths": ["libs/gda-balancing"]` on the
root package, so that member PRs could stop pretending to be `chore` and carry
truthful `feat`/`fix` titles.

The exclusion does not reach far enough, for a mechanism reason verified
against release-please's matcher:

- **`exclude-paths` matches DIRECTORY PREFIXES only** — the check is literally
  `file.indexOf(path + "/") === 0`. A root-level *file* cannot be excluded at
  all, by any spelling.
- **A commit is dropped from a package only when EVERY changed file is
  excluded.** One unexcluded file re-attributes the whole commit.

The single workspace `uv.lock` sits exactly on that seam. It is a root-level
file, and a workspace member's dependency change necessarily rewrites it: such
a PR edits `libs/gda-balancing/pyproject.toml` **and** the root `uv.lock`, so
one of its files is unexcludable and the commit still counts for the root `gda`
package. #527 is precisely that shape. The shared lock therefore defeats the
exclusion for the one class of member change most likely to deserve a release
of its own.

## Decision

**`gda-balancing` stops being a uv workspace member and becomes an independent
uv project inside the repo, with its own lock under its own directory.**

- The root `pyproject.toml` drops `[tool.uv.workspace]`. The two projects
  resolve separately: `uv.lock` at the repo root holds `gda`'s closure only,
  and `libs/gda-balancing/uv.lock` holds the toolkit's.
- `libs/gda-balancing` gains its own `[dependency-groups] dev` (`pytest`,
  `pyright`) — the root's dev group is now a different environment and installs
  nothing for the member's gates. `ruff` stays root-only: it is file-based and
  the `lint` job runs it repo-wide, so a second pin here could only drift from
  the one that actually gates. It also gains its own `.python-version`: uv does
  not inherit the root's, so an unpinned member project would build its venv on
  whatever interpreter uv defaults to, silently diverging from the interpreter
  CI resolves against.
- Every file a member change can touch — including a dependency change — now
  lives under `libs/gda-balancing/`, so the existing single `exclude-paths`
  entry covers it completely and the root package genuinely stops absorbing
  member commits.
- CI and Release sync per project rather than per workspace: the shared
  `setup-python-env` action takes a `sync` input (`root` | `member` | `both` |
  `none`) instead of the blanket `uv sync --dev --all-packages`, and member
  commands run under `uv run --project libs/gda-balancing`. The member's
  release build syncs the member only — its release train no longer resolves
  or installs anything belonging to `gda`.

## Consequences

- **What is lost: the shared lock's co-installability feedback.** While both
  products resolved into one lock, uv proved on every change that their
  dependency closures stay mutually satisfiable. Two independent locks each
  resolve alone and can drift into wheels that cannot be installed side by
  side, with nothing noticing until a user (or an agent image) that wants both
  hits it. **Compensated by making the claim an explicit test**: the CI
  `coinstall-smoke` job builds both wheels, installs them together into one
  clean environment, and runs `gda --help` and `gda-balancing version`. What
  was an implicit property of the packaging layout is now an asserted one.
- **The release-PR lock sync generalizes to two locks.** ADR-0037's sync ran
  `uv lock` and committed the root lock on every Release PR branch. Each branch
  now refreshes **both** locks and commits whichever actually changed. Which
  package a branch releases is answered by the diff, not by parsing
  release-please's branch-naming convention — that would be a second, brittle
  authority on package identity.
- **A releasing-typed member PR must stay inside the member directory**, since
  the all-files rule still holds: a `feat` touching the member *and* anything
  outside it proposes two Release PRs. A guard asserts this at PR time
  (`scripts/release_scope_guard.py`, run by the `release-scope-guard`
  workflow). Both of its inputs are **derived** from
  `release-please-config.json` rather than restated: the member directory from
  the root package's `exclude-paths`, and the set of releasing commit types
  from the **non-hidden `changelog-sections`** — which is wider than `feat`
  and `fix` alone (`deps` and `revert` are visible sections here, and
  release-please's default versioning strategy patch-bumps them). A breaking
  `!` marker releases on any type.
  `changelog-sections` is an **inherited input**, like the four in
  `release_tags.py`: release-please resolves it per package, a package's own
  value overriding the top-level default. The guard resolves it the same way,
  **by key presence rather than truthiness** — release-please's precedence is
  nullish, so a package declaring an explicit `[]` overrides the top-level
  list with "no visible sections" and must not silently inherit it. It then
  combines the touched packages' sets **conservatively — releasing for ANY of
  them, not for all of them**. Reading only the top-level list would have
  passed a PR whose type is visible solely through a package override;
  requiring every touched package to release it would pass one that bumps the
  root alone, which is the original harm. The shipped config declares no
  package-level override, so all packages resolve to the one top-level list
  today and a drift test pins that.
  **There is no default fallback: a package with sections at neither level
  fails the guard loudly.** release-please's built-in defaults are
  per-`release-type`, and this repo declares `"release-type": "python"`, whose
  strategy makes `deps` and `docs` visible on top of the generic
  `DEFAULT_CHANGELOG_SECTIONS` (`feat, fix, perf, revert`). Falling back to
  the generic list therefore reported a `deps:` or `docs:` title as
  non-releasing — a FALSE PASS, the one direction a guard must never fail in.
  The alternative, reimplementing upstream's per-strategy default tables,
  would make the guard a second authority on release-please's internals, which
  is exactly what deriving its inputs from the config exists to avoid. So the
  config is required to say what it means.
  The guard runs on **title edits** as well as pushes: its verdict is a
  function of the PR title, and the default `pull_request` activity types omit
  `edited`, so without it a mixed-path PR could pass as `chore` and then be
  retitled to a releasing type against the same green check. That is why it is
  its own workflow — the rest of CI is a function of the tree and does not want
  to re-run on a title edit. It blocks a merge only once it is a **required
  status check**, which is a repo-settings action.
  The guard is belt-and-braces while the non-releasing title discipline is
  still in force, and becomes load-bearing when #528 flips it.

  > **Outcome (2026-07-20, #528):** the flip has happened and the guard is a
  > **required** status check, so it is load-bearing now: a releasing-typed PR
  > spanning `libs/gda-balancing` and anything outside it cannot merge. The
  > discipline is lifted for that path only. Every un-excluded path stays
  > attributed to the **root release train**, so its title type must honestly
  > describe the change's effect on `gda`: a genuine `gda` feature or fix keeps
  > its truthful releasing type and bumps `gda` (ADR-0007/ADR-0034), while work
  > that lands in an un-excluded path without being a `gda` change —
  > `examples/**` is the standing case — takes a non-releasing type so it does
  > not bump `gda` falsely (ADR-0037's flip note).

- **Required `gda-balancing` feedback follows the independent project
  boundary.**
  > **Outcome (2026-07-30, #597/#598):** required feedback no longer extends
  > the root Python job's serial critical path. Root CI owns only the workflow
  > topology: a fail-closed path-classification job, inventory gate, parallel
  > required matrix, wheel/subprocess smoke, and stable
  > `gda-balancing required` aggregator.
  > `libs/gda-balancing/tools/ci.py` is the single authority for affecting
  > paths, shard membership, process budgets, logical inventory, and allowed
  > historical skip outcomes; the workflow derives those values rather than
  > restating them. Nightly, manual evidence, and release validation retain the
  > complete unfiltered suite. Repository protection adopted the stable
  > aggregator before the duplicate member test/build steps were removed from
  > the root job. Because this topology changes un-excluded root automation but
  > not the `gda` product, its commits and squash title use non-releasing `ci`
  > types.
- **CI and Release share one exact uv tool version.** The shared
  `setup-python-env` action owns the pin for every project-sync and release
  consumer; workflows may not opt back into a moving `latest` or restate the
  pin per job. The stdlib-only path classifier pins Python 3.13 directly with
  `actions/setup-python`, avoiding uv installation on the latency-critical
  unrelated-path route while keeping its interpreter explicit.
- **Tag identity has one implementation.** Three places need to know a
  package's tag — the root release build's validation, the member release
  build's validation, and the release-PR tag gate — and each composing its own
  would let a supported config change (`include-v-in-tag`, `tag-separator`)
  make release-please mint a tag one of them rejects.
  `scripts/release_tags.py` is the single derivation all three call, reading
  all four inherited inputs per package with the top-level value as the
  default. Its **supported contract is an explicit `component` key**:
  release-please can also resolve a component from other package metadata, but
  reimplementing that resolution would be a second copy of release-please's
  internals, so a config that would need inference fails loudly instead. A test
  asserts the shipped config stays inside that contract.
- **The release scripts are stdlib-only about DEPENDENCIES, not about the
  interpreter.** `release_tags.py` and `release_scope_guard.py` import nothing
  outside the stdlib, so no job that runs them has to resolve or install either
  project's closure — that is the whole benefit, and it is why their jobs use
  `setup-python-env` with `sync: none`. It is *not* a claim that any
  interpreter will do. Both are load-bearing release gates and both target the
  repo's pinned Python like the rest of the codebase, so every call site names
  the interpreter explicitly (`uv run --no-project --python 3.13 python …`):
  `--no-project` keeps the no-sync property honest, `--python` pins the
  version. A bare `python3` would be whatever the runner image happens to
  ship — neither `.python-version` nor a project `.venv` redirects it — which
  makes the gate's interpreter a property of GitHub's base image rather than of
  this repo.
- **ADR-0037's release model is otherwise unchanged.** One manifest ledger,
  per-package components, disjoint tag namespaces, separate Release PRs, the
  member's own PyPI environment, and the tag gate over every released component
  all stand exactly as recorded. Only the *workspace premise* underneath it is
  superseded — the member is now a sibling project rather than a member, which
  changes how environments are synced and how locks are kept, not who owns a
  version.
- The two projects may now pin different versions of a shared dependency
  (`pydantic` today) without one dragging the other. That is a real gain in
  independence and a real loss in enforced uniformity; the co-install smoke is
  the floor that keeps the divergence honest.

## Considered options

- **Leave the workspace, lock per project** (chosen) — makes the member's
  entire change surface a directory, which is the only shape
  `exclude-paths` can express. The fix matches the mechanism instead of
  working around it.
- **Keep the workspace, force member PRs to `chore`** — rejected. A member
  runtime-dependency change may itself warrant a release, and `chore` would
  make the version line lie about it. This is the very discipline #528 exists
  to retire; re-adopting it as the fix concedes the goal.
- **Keep the workspace, split the `pyproject` and lock edits into two PRs** —
  rejected as impossible in practice: the intermediate state (a bumped
  dependency with a stale lock) fails the repo's frozen-lock CI, so the first
  PR of the pair can never go green.
- **Keep the workspace, hand-maintain a "root-owned paths" allowlist** —
  rejected. It would be a second authority on package boundaries, restating
  by hand what the packaging layout already knows, and drifting the first time
  a root-level file is added. Single-authority (ADR-0008's premise) argues
  against it directly.
