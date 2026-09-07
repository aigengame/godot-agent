---
status: accepted
---

# aADR-0003: Keep prompts and concept references as project-owned preparation inputs

Recorded on 2026-09-07 from the project owner's added prompt-management and
concept-reference requirements. This refines aADR-0001 and aADR-0002 for enabled
generation workflows; it does not change the gda integration contract.

## Context

Panda composes a generation prompt and includes it in the manifest emitted after
acquisition and postprocessing. That offers useful reuse, but does not establish
generation-time preservation or explicit selection across attempts. A failed
generation can lose its prepared input, and later style edits can change the next
prompt without making that change visible.

The previous design starts from completed images or a saved Blender source. It
does not cover generating and selecting a concept before new model or sprite
authoring. These are preparation needs inside Asset Pipeline, with project-owned
art direction; they are not Godot engine facts or a new bounded context.

## Decision

### Prompt preparation

Save a **prompt record** before invoking a generator or handing work to an
external tool. It contains authored text or a simple template and explicit inputs,
the resolved prompt, selected reference inputs, and requested non-secret producer
options where available. The project chooses the content and storage location.
The workflow preserves the text and reference files needed to reuse that attempt.

Each attempt uses a separate ordinary file location. Inspect/reuse reads its saved
inputs. Explicit revision creates another record and exposes the changed text or
inputs; editing a style file must not silently change an earlier attempt. Record
location is sufficient identity. Ordinary files and Git are sufficient management;
there is no global prompt catalog, revision graph, or Repository requirement.

Register output files after generation, retaining requested settings separately
from provider-reported information. If a caller supplies different text actually
submitted to an external tool, retain that text too. Unavailable execution details
remain unknown. An associated local file does not independently prove what a
provider executed, and identical prompts do not guarantee identical images.

### Concept references before authoring

New model or sprite production through this workflow first prepares an image-gen
concept request, obtains candidate images, and explicitly selects references before
authoring. Projects specify subject, style, and useful views/poses in a small brief.
The caller can be an agent or a user; selection does not imply a new human approval
gate. An already generated, explicitly selected concept can be reused.

The **authoring handoff** contains usable selected image files, their prompt-record
links, intended model/sprite use, and project instructions. Preserve the selected
content for the receiving step; editing a candidate later must not silently replace
it. The first implementation must demonstrate actual reference use in Blender and
in a small sprite-sheet authoring path. A file-path field with no working consumer
does not meet the requirement. Tool-specific reference loading belongs in a local
adapter or reusable tool recipe, not Domain or the gda host.

Concept references have a distinct file role from runtime assets. They are not
automatically installed into Godot. This preparation does not require an Aseprite
adapter, general procedural model generator, art-quality evaluator, or automatic
repair loop. Artistic consistency is an aim supported by explicit reusable inputs,
not a mechanically guaranteed result.

### Application and integration

Domain owns the small prompt/reference values and validity/selection rules.
Application saves preparation before external effects, registers outputs, selects
references, and returns the authoring handoff. Existing local file handling stores
the records and selected files; producer ACLs translate generation and authoring
tool options. No vendor types or project style policy enter the domain model.

Add preparation and output-registration operations through the same
`gda asset-pipeline` entry and package API. The implementation slices freeze their
public names and schemas. No additional top-level command group or Godot port is
needed for these producer-side operations. Existing gda integration translates the
new service inputs/results without taking ownership of their workflow rules.

When image gen is available only to an agent, preparation returns an explicit
external handoff; registering the completed local output is a separate action.
Python does not pretend to call a tool available only in the agent runtime.
Missing references, no selection, and unknown generation completion stop dependent
authoring. Failed import must not replay concept generation.

## Scope and consequences

Prompt records are required only for enabled preparation/generation. Existing-file
admission, saved Blender export, and ordinary gda operations remain independently
usable. These input records are separate from optional selected content receipts
in aADR-0002: no import hashes, engine evidence, immutable store, or persistent
PipelineRun is needed to keep a prompt. Provider credentials are not record fields.

Two vertical issues separate prompt preservation/reuse from generated concepts and
their authoring consumers. The latter depends on the former; both reuse the first
installed workflow slice. Saved-source export remains its own complete path.
Panda is only a one-time source of reusable composition ideas and tests.

AP-06 in [the architecture](../ARCHITECTURE.md) remains open until two-attempt
preservation, explicit reuse/selection, real concept generation, and actual
reference consumption have been demonstrated. Recording this decision delivers
none of those runtime capabilities.
