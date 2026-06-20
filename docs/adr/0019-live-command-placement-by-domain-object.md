---
status: accepted
---

# Live command placement: distributed by domain object, with a narrow `game` object for the running game's scene graph

ADR-0005 groups commands by Godot **domain object** and explicitly **rejected**
grouping by capability phase (a `headless` group / `live` group), because that leaks
the delivery dimension into the user surface and separates commands users think of as
siblings. Phase 2 (ADR-0017) now adds [live operations](../../CONTEXT.md), and the
naive move — a single `live` / `runtime` / `game` group holding *all* of them — would
resurrect exactly that rejected phase group wearing a domain-object costume.

## Decision

**1. Live operations are placed by their real Godot domain object, like headless
operations.** The headless/live distinction is carried by the per-command `kind`
(ADR-0017), never by a group. So the live-only capabilities become their **own
domain-object groups** populated by their actual object — input simulation under an
`input` group, viewport capture under a `screen` / `viewport` group, runtime
monitoring under a `perf` / `monitor` group, etc. — not lumped together as "live".
There is **no single live group**, so the phase still never appears in the tree
(ADR-0005 holds).

**2. The one genuine collision gets a narrow `game` object.** The only place a
headless reading and a runtime reading of the same thing both exist is the **running
game's scene graph**: the runtime scene tree and runtime node properties, versus the
on-disk `.tscn` read by `scene get` / `node get`. The *running game* is itself a Godot
domain object (the runtime `SceneTree` / `MainLoop`, distinct from on-disk assets), so
it gets a **narrow `game` group** holding only its live scene graph (`tree`, runtime
`get` / `set`). `game` is **not** a catch-all for all live ops.

**Why `game` is a domain-object group, not the rejected phase group.** ADR-0005
rejected grouping by *delivery phase*. `game` is named after an *object* (the running
game) that merely happens to exist only at runtime; input / capture / perf are
separate object groups, so nothing collapses into one "live" bucket. The phase is
still invisible; only objects appear in the tree.

## Considered options

- **A single `live` / `runtime` / `game` mega-group for all live ops** — rejected: it
  *is* ADR-0005's phase group renamed, and it buckets unrelated capabilities (input,
  capture, perf) by their phase rather than their object.
- **Keep runtime tree/props under `scene` / `node`, disambiguated by a name qualifier
  or a `--running` flag** — the flag is rejected (one command = one schema = one
  context; a flag that swaps the output schema breaks that). A name qualifier under
  `scene` / `node` is viable but conflates "the authored on-disk scene" with "the
  running game's tree", which are different enough to be different objects.

## Consequences

- The "scene tree" concept now spans two objects: on-disk under `scene`, runtime under
  `game`. Mitigated by help / `--schema` cross-references; accepted because the two are
  genuinely different objects (authored asset vs running runtime tree).
- `docs/command-catalog.md`'s Phase-2 section is narrowed accordingly: running-game
  scope, live ops distributed by object, the narrow `game` group for the runtime scene
  graph.
- Error-code allocation is orthogonal to placement (by failure-mode / source —
  ADR-0017, ADR-0002), so this grouping decision does not affect codes.
