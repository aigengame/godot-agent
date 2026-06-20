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

- **Where it runs.** The publish is a step inside the existing `github-release`
  job of `release.yml`, not a new workflow. That job already checks out the
  exact tagged commit, runs the full test suite, and `uv build`s the
  distributions; PyPI publish consumes the same `dist/` those steps produce. One
  release pipeline, one version source (ADR-0007 / ADR-0008) — unchanged.

- **Auth: Trusted Publishing, not a stored token.** The job requests an OIDC
  token (`permissions: id-token: write`) and `pypa/gh-action-pypi-publish`
  exchanges it for a short-lived, scoped PyPI upload credential. This honours
  ADR-0007's stance that "a long-lived credential is a cost we do not need to
  pay": no `PYPI_API_TOKEN` secret to store, rotate, or leak. The OIDC trust is
  scoped to a named GitHub Environment (`pypi`) so only this job — not an
  arbitrary workflow in the repo — can mint a publishable token.

- **Ordering: publish to PyPI *before* the GitHub Release is un-drafted.**
  Un-drafting the GitHub Release is what creates the git tag, and ADR-0007's
  recovery model treats **the tag as the atomic "release succeeded" signal** —
  everything that must succeed runs before it, so a failure leaves a *tag-less
  draft* that the release-PR-maintenance gate flags ("needs recovery") and
  "Re-run failed jobs" converges. Slotting PyPI publish between `uv build` and
  the un-draft brings PyPI under that same guarantee: a PyPI failure wedges the
  draft exactly like a build failure does, and recovery is the existing,
  documented re-run — no new failure mode, no new runbook.

- **Idempotent, like the GitHub-Release upload.** PyPI files are **immutable**
  (a filename can never be re-uploaded), so the publish uses `skip-existing:
  true`: a re-run from the same tagged commit skips whatever already landed and
  uploads the rest. This mirrors the `--clobber` idempotency of the
  `gh release upload` step — together they make the whole publish phase
  re-runnable, which is what ADR-0007's recovery depends on. Re-runs are safe
  because they build from the **same** tagged commit (ADR-0008's single version
  authority), so "skip what exists" never hides a content change.

- **Project name `gda`, claimed via a pending publisher.** `gda` is free on
  PyPI today. Trusted Publishing's *pending publisher* mechanism both registers
  the trust and reserves the name: the project is created automatically on the
  first successful publish. If the name turns out to be taken or squatted before
  setup, the fallback is to pick an alternative distribution name and update
  ADR-0013's canonical commands accordingly — the workflow change is unaffected.

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
- **A separate publish workflow / job with artifact hand-off (rejected).** A
  standalone job (download the `dist/` artifact, publish) is the PyPA tutorial's
  shape, but it would run *after* `github-release` — i.e. after the tag already
  exists — breaking the "everything load-bearing happens before the tag"
  invariant the recovery model rests on. Inlining the step keeps PyPI under the
  existing tag-as-commit-point guarantee at the cost of running the whole job in
  the `pypi` environment.
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
