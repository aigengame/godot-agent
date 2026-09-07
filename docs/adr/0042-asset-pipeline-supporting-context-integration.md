---
status: accepted
---

# Integrate Asset Pipeline as an internal supporting context

Accepted by the project owner on 2026-09-07. Requirements and delivery status:
[#907](https://github.com/aigengame/godot-agent/issues/907),
[gda-blender milestone](https://github.com/aigengame/godot-agent/milestone/14).
This records the accepted target. #908 supplies the first file-handoff integration;
later producer, acceptance, runtime, and package workflows remain separately tracked.

## Context

Blender-to-Godot work repeatedly requires proving what was exported, what Godot
imported, and what a selected running instance uses. Project checks and preview
recipes also need production and file-processing steps. Adding all of that to
gda's Godot operation groups would give those groups unrelated reasons to change.

The owner requires a single gda entry, a new supporting context at `libs/gda-assets`,
and primarily additive changes to the existing gda topology. Panda Adventure's
generic asset scripts can seed the new context once; the game is not a dependency
or an ongoing migration target.

## Decision

1. **One product entry, two models.** Add the command group `gda asset-pipeline`.
   The internal Python package is `gda_assets`, carried by `libs/gda-assets`.
   It has no user-facing CLI, daemon, separate setup flow, or service deployment.
   `gda-mcp` continues to derive its public tools from the same gda descriptors.
2. **The supporting context supplies the pipeline service.** For this service
   contract, gda-assets is upstream and gda's entry/integration is downstream.
   gda-assets owns application orchestration from production through selected checks.
   Subdomain importance, data-flow order, and runtime call direction do not change
   this contract-specific relationship.
3. **The host supplies Godot capabilities by injection.** gda-assets declares
   narrow application-owned ports for the engine operations its use cases need.
   A gda-side adapter implements them through typed, returning gda operations.
   It translates engine results into the pipeline's required facts while preserving
   measurement scope, omissions, failure reasons, and unsupported cases.
   gda remains the authority for import/cache semantics and runtime observations.
4. **Source imports stay acyclic.** gda integration imports the explicit
   `gda_assets` API/port contracts and gda operations. gda-assets imports neither
   gda internals nor its CLI, and never starts a nested gda process. No operation
   adapter calls back into the asset-pipeline service. gda's composition constructs
   the host adapter and injects it into the service.
5. **Translation is local.** The gda integration translates public gda requests,
   results, and registered errors at the service boundary. The same compact
   integration module can hold the host-port adapter; two abstract frameworks are
   unnecessary. Blender and image-generation anti-corruption layers live inside
   gda-assets. Their vendor SDK types, errors, and transport semantics do not enter
   the gda core or the pipeline Domain.
6. **Core operations remain independently useful.** Resource import/inspection,
   scene/property operations, session control, capture, diagnostics, and export
   continue to work without a recipe, receipt, profile, or pipeline history.
   Selected hashes and check results are optional workflow data, not a new core
   precondition. New engine facts go in their existing owning group.

## gda implementation seam

The planned addition is a thin `commands/asset_pipeline.py` group and a compact
`integrations/asset_pipeline.py` host adapter/factory. The group retains its gda
params/result models, renderers, classifiers, descriptors, and dispatch. Its recipe
delegates cross-tool application work to the supporting context. This extends
ADR-0040 only at this group; it does not move other groups or rebuild the core.

Composition remains rooted in `cli.py`. The integration module must not import
that root to recover a service. Prefer returning operation functions; CLI dispatch
tails emit output and can exit, so they are not host service methods.
`HeadlessCommand.execute` is not a generic recipe executor. Extract a narrow
returning operation only where the actual needed seam is absent.

The first command slice must extend descriptor execution metadata truthfully for
a composite asset-pipeline recipe. It must not label the entire workflow as one
headless or live operation or add a generalized runner engine. The selected steps
retain their own engine/platform/readiness checks; a file/import-only workflow
does not acquire live-session requirements from an optional preview step.

Canonical spelling is `asset-pipeline`, with planned `run`, `check`, and `preview`
verbs introduced by their own slices. Each implemented verb must reach help,
structured params, schema, generated MCP, human output, and shipped skill guidance
together. #908 implements `run` for explicit PNG/GLB file handoff; it does not
advertise `check`, `preview`, or producer generation as available.

## Packaging and lifecycle

A normal gda installation must include a compatible gda-assets implementation with
no separate user install. The first integration slice owns the packaging decision
and proves it by installing built artifacts outside the checkout; a source-only
path dependency is insufficient. Coordinate package compatibility and release
ordering with the existing release authority before shipping that slice.
ADR-0038's independent sibling-product release model does not automatically apply
to this internal supporting library.

### First-slice packaging and execution decision (#908)

Root `pyproject.toml` builds `src/gda` and `libs/gda-assets/src/gda_assets` into
one gda distribution. Hatchling provides both wheel roots and the sdist through
the existing `uv build` PEP 517 path. The previous uv_build backend supports
multiple names under one source root, which does not fit these two owned roots.
No workspace-only dependency, separate version, release train, or assets extra
is introduced. PNG processing makes Pillow a normal runtime dependency; its
import stays local to PNG admission/processing.

The descriptor uses `ExecutionKind.COMPOSITE` as truthful self-description.
`dispatch_recipe` calls the workflow; there is no additional runner-selection
branch. The injected Godot adapter reuses returning resource import and bounded
resource-load operations. The latter obtains actual engine type/version and
texture dimensions or instantiated scene node count, without introducing a
second public resource command or a full model-inspection contract.

Workflow failures use the optional generic `error.partial_result` extension in
[ADR-0004](0004-schema-flag-self-description.md). The host maps the supporting
context's stage/file outcomes into it; core errors contain no asset-domain type.
Ordinary operations omit it and need no workflow records.

Importing the public API, listing schema, and displaying help/version must not
initialize vendor SDKs, discover/connect to Blender, read credentials, or contact a
generation service. Producer configuration is checked only for a selected producer.
External tools still require their normal installation and configuration.

## Alternatives and consequences

- An external script invoking gda would reuse the current surface with less initial
  integration work, but would not satisfy the accepted single-entry support model.
- Putting the workflow in gda command groups would avoid a package seam but couple
  producer changes and project policy to Godot operations.
- The selected package boundary adds a small supported internal API and explicit
  translation tests. It does not require a public Python SDK, plugin registry,
  message bus, persisted workflow engine, or separate product release promise.

The supporting context owns its model and decisions in
[ASSETS-CONTEXT.md](../../libs/gda-assets/ASSETS-CONTEXT.md) and its
[architecture](../../libs/gda-assets/docs/ARCHITECTURE.md). Those documents reference
this integration contract instead of redefining gda's core semantics.

## Verification still required

The #908 tests exercise CLI/structured/MCP discovery, host injection and real
PNG/GLB loading. `scripts/smoke_asset_pipeline.py` also exercises a built gda
distribution in an isolated consumer project. AP-01 in the local architecture
tracks this integration evidence; the broader producer, runtime and package
claims still require their own real-system cases. A passing file handoff does
not establish those later workflows.
