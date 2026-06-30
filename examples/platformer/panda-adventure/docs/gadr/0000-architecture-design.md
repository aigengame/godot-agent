---
status: accepted
---

# Architecture: layered and data-driven, with JSON as the authoritative config source

Panda Adventure is authored by an AI agent driving Godot through `gda`, and its numeric
configuration is the **output of an offline Python data-design pipeline** (design + TTK/TTD
balancing + Monte-Carlo combat simulation), not hand-tuned in the editor. We therefore adopt a
layered, data-driven architecture: **Resource** (data) / **Controller** (logic) / **CanvasItem**
(view) are kept separate; no configuration is hardcoded in code; and **JSON is the single
authoritative source** for all config/stat data, converted by a JSON→Resource pipeline into
Godot `Resource`s that the runtime consumes. The Godot `Resource` is a **derived artifact**, not
a source of truth.

## Considered options

- **JSON authoritative → Resource (chosen).** The source of truth lives *upstream* of Godot,
  where the balancing/simulation pipeline emits it. JSON is also what an agent writes, diffs,
  and reviews reliably, and what the Phase-2 Python asset pipelines consume; a JSON Schema gives
  the agent validation.
- **Native Godot `.tres`/`.res` authored in the editor (rejected).** Godot's own data-driven
  path, but it puts the source of truth *inside* the editor — exactly where this project does
  **not** author. It is editor-bound and a poor diff/review target for an agent, and it can't be
  the head of a Python balancing pipeline.
- **Hardcoded constants in GDScript (rejected).** Violates the data-driven principle; couples
  tuning to code and breaks the offline balancing loop.

## Consequences

- `Resource` files are **regenerated from JSON** (e.g. at build) and are never hand-edited;
  changing config means changing the JSON.
- A JSON→Resource conversion step (with JSON Schema validation) is required machinery.
- Drift between JSON and Resource is prevented by treating the Resource strictly as a derived
  output of the authoritative JSON.
