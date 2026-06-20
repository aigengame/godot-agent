---
status: accepted
---

# Distribution: publish `gda` to PyPI via Trusted Publishing

[ADR-0013](0013-gda-mcp-packaging-and-launch.md) makes the canonical install and
registration commands `pip install "gda[mcp]"` and `uvx --from "gda[mcp]" gda-mcp`.
Neither works today: `gda` is not on PyPI (`pypi.org/pypi/gda` → 404). The
release pipeline ([ADR-0007](0007-release-automation-with-release-please.md))
builds distributions with `uv build` and attaches them to a **GitHub Release
only** — there is no publish step to a package index. As a stopgap the
[#195](https://github.com/aigengame/godot-agent/issues/195) registration recipes
ship the git-source form
`uvx --from "gda[mcp] @ git+https://github.com/aigengame/godot-agent" gda-mcp`,
which the ADR-0013 prose promises to simplify "once on PyPI". This ADR records
the decision that makes the canonical form real.

## Decision

**Publish the built `gda` distributions (sdist + wheel) to PyPI on every cut
release, via PyPI Trusted Publishing (OIDC) — no long-lived API token.**

- **Where it runs: a minimal publish job, isolated from build/test.** The former
  single `github-release` job is split into three jobs in `release.yml`:
  `build-release` (checkout the tagged commit, run the full suite, `uv build`,
  upload the `dist/` as a run-scoped artifact), `publish-pypi` (download the
  artifact, publish to PyPI), and `publish-github-release` (download the
  artifact, upload it to the GitHub Release and un-draft). One release pipeline,
  one version source (ADR-0007 / ADR-0008) — unchanged; what changes is only the
  job graph.

- **Auth: Trusted Publishing, not a stored token — scoped to the publish job
  alone.** `publish-pypi` requests an OIDC token (`permissions: id-token: write`)
  and `pypa/gh-action-pypi-publish` exchanges it for a short-lived, scoped PyPI
  upload credential. This honours ADR-0007's stance that "a long-lived
  credential is a cost we do not need to pay": no `PYPI_API_TOKEN` secret to
  store, rotate, or leak. Crucially, `id-token: write` is granted to
  **`publish-pypi` only** — a job that runs no project, test, or build-backend
  code, just an artifact download and the publish — so the build/test
  environment never holds publishing authority and an injected build/test path
  cannot mint a PyPI credential. The trust is further scoped to a named GitHub
  Environment (`pypi`) so only this job can request a publishable token.

- **Ordering, and a re-runnable recovery across the split.** Un-drafting the
  GitHub Release (in `publish-github-release`) is what creates the git tag, and
  ADR-0007's recovery model treats **the tag as the atomic "release succeeded"
  signal** — everything that must succeed runs before it, so a failure leaves a
  *tag-less draft* that the release-PR-maintenance gate flags ("needs recovery")
  and **"Re-run failed jobs"** converges. Ordering `publish-pypi` before the
  un-draft keeps PyPI under that guarantee; the tag-as-commit-point property is a
  function of the job *sequence*, not of co-locating publish with build.

  Splitting one job into three does introduce a hazard the single job lacked:
  GitHub's **"Re-run failed jobs"** reliably re-runs *failed* jobs and their
  dependents, but whether it re-runs a job that was *skipped* because an upstream
  failed is **undocumented** — and a naive split makes each downstream job skip
  on upstream failure, so recovery could leave the un-draft stuck skipped and
  never converge. To keep ADR-0007's contract independent of that grey area, each
  downstream job (`publish-pypi`, `publish-github-release`) **runs on any
  non-cancelled post-cut outcome** (`if: !cancelled() && release_created`) and a
  first **guard step fails it explicitly** when its upstream did not succeed,
  instead of skipping. Every post-cut job is therefore either *successful* or
  *failed* (never skipped-because-upstream-failed), so "Re-run failed jobs"
  re-runs the entire failed tail and drives through to tag creation once the
  failure is repaired — exactly as the single job did. The guard on
  `publish-github-release` doubles as a correctness check: it blocks the un-draft
  (hence the tag) unless PyPI actually published.

- **Idempotent, like the GitHub-Release upload.** PyPI files are **immutable**
  (a filename can never be re-uploaded), so the publish uses `skip-existing:
  true`: a re-run from the same tagged commit skips whatever already landed and
  uploads the rest. This mirrors the `--clobber` idempotency of the
  `gh release upload` step — together they make the whole publish phase
  re-runnable, which is what ADR-0007's recovery depends on. Re-runs are safe
  because they build from the **same** tagged commit (ADR-0008's single version
  authority), so "skip what exists" never hides a content change.

- **Project name `gda`, claimed only by the first publish — not by setup.**
  `gda` is unregistered on PyPI today. Registering a *pending publisher* does
  **not** reserve the name: PyPI creates the project (and thereby claims the
  name) only on the first successful publish, and if another account registers
  `gda` before then, the pending publisher is invalidated. So the name is
  effectively claimed by *landing the first release*, not by configuring the
  publisher — until that release publishes, `gda` stays available to anyone. If
  it is taken or squatted before then, the fallback is to pick an alternative
  distribution name and update ADR-0013's canonical commands accordingly; the
  workflow change is unaffected.

### One-time human setup (outside this repo)

The workflow is inert until a maintainer configures the PyPI side once (tracked
on #207, labelled `ready-for-human`):

1. On PyPI (account with 2FA), register a **pending publisher** for project
   `gda`: owner `aigengame`, repository `godot-agent`, workflow `release.yml`,
   environment `pypi`.
2. Create the GitHub Environment `pypi` in the repo settings (auto-created on
   first use if omitted; created explicitly if protection rules are wanted).

Optionally a TestPyPI pending publisher (same fields, `environment: testpypi`)
enables a dry run before the first real publish.

## Considered options

- **Trusted Publishing / OIDC (chosen).** No stored credential; the upload
  token is short-lived and scoped to one environment. Aligns with ADR-0007's
  no-long-lived-credential stance and is the PyPA-recommended path for CI.
- **PyPI API token in GitHub Secrets (rejected).** A long-lived credential that
  must be stored, scoped, and rotated, and is exfiltratable from a compromised
  workflow — precisely the cost ADR-0007 declined to pay for the GitHub token.
- **A separate, isolated publish job with artifact hand-off (chosen).** A
  minimal `publish-pypi` job — download the `dist/` artifact, publish, nothing
  else — is the PyPA-recommended shape, and it keeps `id-token: write` out of
  the build/test environment. It does *not* break the tag-as-commit-point
  invariant: the tag is created by the *downstream* `publish-github-release`
  job's un-draft, so ordering `publish-pypi` ahead of it preserves "everything
  load-bearing happens before the tag" while isolating the OIDC privilege. (An
  earlier draft of this ADR rejected this option on the false premise that a
  separate job must run *after* the GitHub Release; the recovery model depends on
  job *ordering*, not on co-locating publish with build.)
- **One job holding OIDC across build, test, and publish (rejected).** Inlining
  the publish step in the build/test job is simpler, but `id-token: write` is
  job-scoped, so the whole test/build environment — project autoloads, the test
  suite, the build backend — could request an OIDC token and exchange it for a
  PyPI credential. That is the supply-chain privilege bleed the PyPA action
  explicitly warns against; the split above removes it.
- **No GitHub Environment scoping (rejected).** Trusted Publishing works without
  naming an environment, but then any workflow in the repo that can request an
  OIDC token could publish. Scoping to a `pypi` environment is cheap defence in
  depth and the recommended configuration.

## Consequences

- After the one-time setup and the next cut release, `pip install "gda[mcp]"`
  and `uvx --from "gda[mcp]" gda-mcp` work from a clean environment — the
  ADR-0013 promise is fulfilled.
- **Follow-up, gated on the first successful publish:** reconcile the git-source
  form back to the canonical form in the #195 registration recipes
  (`docs/gda-mcp-registration.md`), `README.md`, and ADR-0013's prose. Done only
  *after* a real PyPI release exists, so the docs never advertise a command that
  404s.
- The `pypi` GitHub Environment carries no protection rules, keeping the release
  fully automated; the human gate stays at the Release PR merge (ADR-0007).
  Adding required reviewers to the environment is an available hardening — it
  would introduce a second, pre-publish human gate — but is deliberately not
  taken now.
- Trusted Publishing emits PEP 740 attestations by default, so released
  artifacts carry verifiable provenance at no extra cost.
- **Supply-chain note.** `pypa/gh-action-pypi-publish@release/v1` is pinned to
  the action's recommended floating major tag, consistent with the repo's other
  tag-pinned actions; pinning to a full commit SHA is an available future
  hardening.
