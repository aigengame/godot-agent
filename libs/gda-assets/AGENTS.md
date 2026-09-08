# Asset Pipeline context

This subtree carries **Asset Pipeline**, gda's internal asset-workflow supporting
context. It is not a sibling user-facing product. File handoff (#908) and saved
Blender production (#909) are implemented; other workflows remain planned. Requirements and delivery status live in
[#907](https://github.com/aigengame/godot-agent/issues/907).

Inherit root `AGENTS.md`, `RULES.md`, issue tracker, and triage conventions except
for domain-document routing. Local domain authority is:

| Artifact | Owns |
| --- | --- |
| `ASSETS-CONTEXT.md` | Local language and responsibility boundaries |
| `docs/ARCHITECTURE.md` | Target structure, workflow, validation gaps, and delivery mapping |
| `docs/adr/NNNN-*.md` | Local asset decisions, cited as aADR-NNNN |

For domain skills, map `CONTEXT.md` to `ASSETS-CONTEXT.md` and `docs/adr/` to this
subtree's `docs/adr/`. The repo-root `CONTEXT-MAP.md` remains the routing authority.
Read root ADR-0042 for integration with gda; root ADRs own gda transport and engine
contracts. Write producer/project vocabulary here, not into the root glossary.

## Implementation boundaries

- Domain owns small asset rules and values. Application owns cross-tool use cases
  and the ports they require. Outbound adapters translate external systems.
- `gda_assets` must not import `gda`, call its CLI, or import game code. The gda host
  injects implementations of the Godot ports. Only the explicit package API and
  published port/result contracts are consumed across the package boundary.
- Blender/image-generation SDKs belong behind local adapters. Load/configure them
  when requested, not during public API import or gda discovery.
- Project recipes own art direction, node expectations, collision/script/material
  policies, and output paths. Do not embed Panda Adventure defaults in the framework.
- Transplant useful Panda asset code once, then refactor here. Do not modify the
  original game to consume this library or preserve its internal import API.
- Add structures when a vertical slice needs them. Do not scaffold empty pattern
  directories, a generic job system, a central asset registry, or an event bus.

Implementation issues use the same GitHub tracker and milestone #14. Use
`asset-pipeline:` for workflow titles; keep Godot primitive titles with their
existing object group. A context boundary does not imply a separate release train.
