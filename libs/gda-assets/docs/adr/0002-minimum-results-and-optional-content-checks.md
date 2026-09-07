---
status: accepted
---

# aADR-0002: Keep workflow results small and content checks optional

Accepted on 2026-09-07. The project owner explicitly requires that identity,
evidence, version, and profile mechanisms remain proportionate to current needs
and do not become dependencies of gda's core operations.

## Decision

The default pipeline result contains completed stages, output locations, check
results, and the failed or unsupported step with remaining state. Local results
may be written for inspection/reuse; they do not require a persistent job engine.
Resume initially means explicitly reusing available files or reports and rerunning
the selected remaining work, with input checks. No implicit replay of generation,
session restart, or other external effects is promised.

Add only the observations needed by an enabled acceptance check:

- Structural checks need bounded model facts, exact locators, origin, measurement
  scope, and omissions. Missing observations produce insufficient information.
- Selected content receipts may hash selected source/configuration/dependencies
  and import artifacts. Distinguish producer declarations from observations,
  disclose coverage, and reject an observed changing input rather than certify
  mixed content. No hash is required for ordinary resource import or CRUD.
- Runtime checks need a selected Engine session and instance plus content-sensitive
  observations for a supported scope. Restart success, resource path/UID, summary
  equality, or a screenshot cannot substitute for that comparison.
- Package checks need facts from the actual package in isolation and its identity.
  They do not prove a native release executable's rendering or input behavior.

There is no default immutable handoff store, revision graph, whole-project hash,
central asset registry, universal profile framework, domain-event log, automatic
retry engine, or state-preserving hot swap. Do not make the absence of those
mechanisms change gda's resource, scene, game, capture, or export behavior.

## Failure and effect boundary

[aADR-0003](0003-project-prompts-and-concept-references.md) adds required prompt
records for enabled preparation/generation. These are reusable project inputs,
not optional content receipts or a persistent job history. They add no prerequisite
to existing-file import, saved-source export, or ordinary gda operations.

Validate input and output targets before mutation. Produce/process files in a
selected workspace before installing them. The workflow reports each installed
file and stops before import if multi-file installation is incomplete. A set of
file writes, engine import, and a remote producer is not one atomic transaction.
Do not claim rollback of all effects; preserve usable outputs and report remaining
state. Limit cleanup to workflow-owned temporary files.

Timeouts and unknown external outcomes are distinct from a confirmed failure.
Recovery starts from available artifacts after validation and never silently
regenerates an image or discards an authored scene/material override. gda's own
import and daemon outcomes remain authoritative at those boundaries.

## Consequences

This supports the current milestone without building a general provenance or
workflow platform. It also limits claims: when a necessary observation is not yet
implemented, the requested validation is unsupported/incomplete, not successful.
Deferring machinery does not weaken the A/B and omission regressions in the issues.

AP-03, AP-04, and AP-05 in [the architecture](../ARCHITECTURE.md) track the required
option-change, runtime-content, and recovery checks. All remain open until the
implementation slices provide the stated evidence.
