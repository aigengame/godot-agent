# Asset Pipeline

Asset Pipeline is a supporting subdomain implemented as the internal `gda_assets`
package. It turns producer outputs into usable, checked Godot assets by coordinating
prompt/reference preparation, production, file processing, installation, import,
and selected acceptance steps.
Users access it through `gda asset-pipeline`; they do not operate a second product.
This is the accepted target vocabulary, with implementation tracked by
[#907](https://github.com/aigengame/godot-agent/issues/907).

## Boundary

Asset Pipeline owns workflow order, prompt preservation and reference selection,
project expectation evaluation, compatible report comparison, and producer
adaptation. gda owns engine operations and the meaning of engine facts. A project
owns its recipes and acceptance policy. Blender
and image-generation systems own their native authoring/generation models.

The context initially serves Blender and image-generation outputs. Aseprite is a
later extension driven by a real use case; it does not set today's abstraction cost.
Panda Adventure is a scaffold source, not the pipeline's domain model or client
compatibility requirement.

## Language

**Asset recipe**: Project-owned input selecting a producer or existing files,
output locations, applicable preparation/processing/import choices, and optional
acceptance or preview settings. A small declarative input, not a programming
language or workflow DAG.

**Prompt record**: Project-local saved input for one generation attempt: authored
text/template and inputs, resolved prompt, selected reference inputs, and requested
producer options. Output files and reported details can be associated afterward.
It supports inspect, explicit revision, and reuse; it is not a content receipt,
provider-execution proof, or guarantee of reproducible output.

**Concept reference**: An explicitly selected image-gen result used to guide new
model or sprite authoring. Its role differs from a finished runtime asset. Project
art direction determines suitable views, poses, and style.

**Authoring handoff**: Selected usable concept files, their prompt-record links,
intended use, and project instructions delivered to a tool or agent before authoring.
It is a small prepared input, not a persisted workflow aggregate.

**Producer**: A boundary that supplies asset files from a native source or generation
request. Its adapter owns vendor options and failure translation. A producer need
not support modeling, source inspection, animation, or interactive sessions.

**Produced files**: The files handed to the next stage, with roles, source mode, and
available producer information. This is an ordinary result, not an immutable asset
identity, version registry entry, or proof that the metadata is independently true.

**Source mode**: The actual input used by a producer, such as a saved Blender file,
an explicitly supported unsaved scene, or previously generated image files. A saved
file and an unsaved interactive scene are not interchangeable fallback inputs.

**Godot asset port**: A narrow application-owned contract for the Godot capabilities
a workflow needs. Implemented by the gda host through existing or extended engine
operations. Port result projection preserves engine fact scope and unavailable data.

**Model facts**: Bounded observations of a selected resource or instance, including
measurement basis, origin, locators, and omissions. A project expectation is not an
engine fact. Blender base/evaluated/export meshes and Godot meshes need not have
equal counts.

**Asset expectations**: Project-authored conditions on compatible facts: required
node paths/types, dimension/count ranges, material slots, or animation bindings.
They do not define universal artistic quality or infer gameplay requirements.

**Asset check result**: Per-condition observations and a verdict of pass, fail, or
insufficient information. Invalid expectations are input errors. Omitted facts
cannot prove a dependent condition passes or that a compared object was deleted.

**Pipeline result**: The stages completed, produced/installed outputs, checks, and
any failure or unsupported step. It describes the work that actually happened.
It is not a persisted run aggregate or a promise of automatic resume.

**Selected content receipt**: Optional workflow output that associates selected
file/configuration/artifact hashes and their observation limits. Producer
declarations remain labelled. It does not prove runtime instance freshness or full
reproducibility. No core operation requires a receipt.

**Controlled refresh**: An optional workflow step after successful import and load
that stops the previous daemon, launches an explicit test scene, waits for readiness,
and compares the selected instance with the imported model. It loses runtime state.
The workflow compares complete, compatible gda content samples; it does not define
the engine sampler or infer instance content from a file hash. Its session and frame
values are observations for this invocation, not persistent asset identities.

**Preview recipe**: An isolated, owned fixture plus settings that fix three camera
views, lighting, viewport, renderer, static pose, monitors, and sample window. The
workflow uses existing gda inspection, capture, diagnostic, and performance
operations and returns one compact invocation result. Baselines compare only
matching observed setups and report scene-level mean/p95 deltas; they do not prove
content equality, repeatable pixels or timing, or per-mesh cost. The current fixture
has no overlays, and Godot node names provide only limited source-object mapping.

**Package acceptance**: Copy one bounded standalone PCK into owned staging, inspect
selected resources through a desktop editor in the package namespace, and apply the
same model expectations. Exact declared exclusions are presence checks, not globs or
package inventory. The result preserves package identity, inspecting engine, fact
scope, verdict, partial failure and cleanup. Editor inspection and native executable
render/input behavior remain separate observations.

## Naming and authority

- Product command: `gda asset-pipeline` (singular `asset`).
- Physical home: `libs/gda-assets`; Python package: `gda_assets`.
- Avoid `gda-assets` as a user command, `assets-pipeline`, a generic `pipeline`
  group, or an `asset` group duplicating resource/scene/game operations.
- gda's Engine session, cache states, and capture-receipt terms retain their root
  meanings. The host translates them; this context does not redefine them.

See [the architecture](docs/ARCHITECTURE.md) for placement and validation, and
[root ADR-0042](../../docs/adr/0042-asset-pipeline-supporting-context-integration.md)
for the integration contract.
