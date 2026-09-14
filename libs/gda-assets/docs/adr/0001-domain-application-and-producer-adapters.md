---
status: accepted
---

# aADR-0001: Separate workflow rules, application use cases, and producer adapters

Accepted on 2026-09-07. The project owner approved a greenfield supporting context
with DDD boundaries and limited initial complexity. This decision is not evidence
that its implementation works.

## Context

Panda Adventure separated generic asset tooling from game configuration, but its
main path assumed raster input/output and did not model Blender production. A
universal asset superclass would preserve those assumptions under new names.

## Decision

- Use a compact Domain / Application / Adapters structure inside the context.
  Domain holds recipe constraints, artifact roles, expectations, and compatible
  comparison rules. Application sequences use cases and owns required outbound
  ports. External adapters translate native data and failures.
- Start with ordinary data/value types and explicit application functions.
  There is no observed need for entity lifecycle, aggregate identity, Repository,
  domain events, or a persisted PipelineRun. Do not introduce them for DDD symmetry.
- Use one narrow producer boundary that returns produced files. Keep Blender
  option validation and scene/export handling in its adapter, and image service
  configuration/response interpretation in the image-generation adapter.
  Source inspection is an optional, producer-specific capability, not a required
  method on every producer. File and raster processing have their own small owners.
- The first Blender path uses an explicit saved source and scene/root selection.
  A future interactive or MCP transport must preserve its declared source mode;
  it must not silently substitute a saved file for unsaved edits. No snapshot
  manager is required for the first path.
- The image-generation boundary can accept already generated local files. When
  the agent's native generation tool cannot be called by the Python process,
  report the required handoff instead of claiming the command generated an image.
  A real callable provider may be added behind the same boundary when configured.
  Uncertain external completion must not cause automatic regeneration.
- Copy useful generic Panda code once into this context and refactor here.
  Preserve source attribution and tests where their semantics still apply.
  Keep Panda style, dimensions, fonts, manifests, and game policy out of the new
  defaults. Do not update the game to become a library client or maintain its
  private import paths as compatibility APIs.

The service and Godot-port integration is owned by
[root ADR-0042](../../../../docs/adr/0042-asset-pipeline-supporting-context-integration.md).
Application imports neither gda nor vendor SDKs. The host implements and injects
the Godot ports; outbound producer adapters stay local.

## Consequences and alternatives

[aADR-0003](0003-project-prompts-and-concept-references.md) refines preparation:
project prompts are preserved before generation, and selected image-gen concepts
are delivered to new model/sprite authoring. Existing-file and saved-source paths
retain their independent scope. This adds local application behavior, not a new
context or reverse dependency on gda.

Keeping the original Panda pipeline would minimize edits but leave a raster-shaped
orchestrator and continued game coupling. A generic plugin/workflow framework would
add configuration and lifecycle mechanisms before two concrete paths work. The
selected design extracts only the useful pieces and proves existing-image and
saved-Blender paths first. Aseprite adapters and broader capabilities wait for need.

AP-01 and AP-02 in [the architecture](../ARCHITECTURE.md) remain open. Their tests
must prove installation, engine integration, and producer substitution rather than
only import isolation or fake adapters.
