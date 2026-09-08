# Context Map

One context glossary per domain context in this repo — the root's is `CONTEXT.md`; a local
domain names its own (see `docs/agents/domain.md`). Each non-root domain's layout and
override rules are declared in its own `AGENTS.md`.

- [gda](CONTEXT.md) — the agent-facing Godot toolchain: `gda`, `gda-mcp`, `gda-daemon`.
- [Panda Adventure](examples/platformer/panda-adventure/GAME-CONTEXT.md) — the 2D-platformer game demo.
- [gda-balancing](libs/gda-balancing/BALANCING-CONTEXT.md) — the standalone numeric design & balancing toolkit.
- [Asset Pipeline](libs/gda-assets/ASSETS-CONTEXT.md) — the internal supporting
  context, physically carried by `libs/gda-assets` and exposed through
  `gda asset-pipeline`. Workflow requirements and delivery status are tracked by
  [#907](https://github.com/aigengame/godot-agent/issues/907).

## Asset Pipeline integration

On the **pipeline service contract**, Asset Pipeline (`gda-assets`) is the upstream
provider and the gda entry/integration is the downstream consumer. The gda host
translates between the two models and injects implementations of the narrow Godot
capability ports declared by Asset Pipeline. Godot operations and engine facts remain
owned by gda. Runtime callbacks through those ports do not create reverse source
imports: `gda-assets` never imports `gda` or invokes its CLI.

Blender and image-generation systems are external producers. Asset Pipeline owns
their outbound adapters and anti-corruption layers. Its application also owns
prompt preparation and concept-reference handoff. Project recipes, prompts,
selected concepts, art direction, and gameplay expectations are project-owned
inputs. Panda Adventure is a one-time scaffold source for this work; it is not a
runtime dependency or a migration target.
Its planned archival does not mean that it has already been archived.

The gda-side integration contract is owned by
[ADR-0042](docs/adr/0042-asset-pipeline-supporting-context-integration.md);
internal workflow design is owned by the
[Asset Pipeline architecture](libs/gda-assets/docs/ARCHITECTURE.md).
