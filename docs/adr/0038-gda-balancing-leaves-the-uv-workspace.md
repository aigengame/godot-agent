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
  outside it proposes two Release PRs. A CI guard asserts this at PR time,
  deriving the member directory from `release-please-config.json`'s root
  `exclude-paths` rather than restating it. The guard is belt-and-braces while
  the non-releasing title discipline is still in force, and becomes
  load-bearing when #528 flips it.
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
