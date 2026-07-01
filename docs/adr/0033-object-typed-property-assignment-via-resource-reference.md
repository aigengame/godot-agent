---
status: accepted
---

# Object-typed property assignment: reference an existing Resource by `res://` path; script property routed to `script attach`; inline sub-resources deferred

`node set` and `resource set` coerce **value-typed** properties (scalars, `Vector2`, `Color`, … via
the shared comma-form `_coerce_value`) but reject every **Object-typed** property with
`uncoercible_value`. So an agent can add nodes and resources but cannot give them a Resource-typed
field — e.g. a `CollisionShape2D`'s `shape` — leaving most functional scenes hand-authored as `.tscn`
text (surfaced dogfooding Panda Adventure S1, #361). Note the adjacent capability is **not** missing:
binding a **script** to a node already ships as `script attach` (#118), which verifies compile + base
compatibility and reports the displaced script. The genuinely missing piece is assigning a
**Resource** to a Resource-typed property.

## Decision

`node set` / `resource set` accept a **`res://…` resource path** as `--value` for an Object-typed
property that expects a **Resource (sub)class**. The path is `load()`ed, **type-checked** against the
property's declared expected class, and assigned as an **external reference** (`ext_resource`) — the
resource is **not inlined**. Combined with the existing `resource create` (which already builds a
built-in *or* project-local `class_name` Resource, #342 / ADR-0032) and `resource set`, this completes
the external sub-resource workflow with **no new command**:

```
gda resource create res://shapes/box.tres --type RectangleShape2D
gda resource set    res://shapes/box.tres --property size  --value 32,64
gda node set scene.tscn --node Col --property shape --value res://shapes/box.tres
```

**Explicit contract edges:**

- **The shared `_coerce_value` is unchanged.** Its `(raw, type)` signature carries only the
  `Variant.Type` (`TYPE_OBJECT`), not the property's expected class, and it is **byte-identical
  mirrored** into the [gda harness](../../CONTEXT.md) for `game set` (ADR live layer). Object
  resolution is therefore a **separate, headless-only step** in `node set` / `resource set` that reads
  the property's expected-class hint from its property-list entry. Assigning a Resource on a live
  `game set` is **out of scope**; the mirror stays green.
- **The `script` property is excluded** from this generic Object path and routed to **`script attach`**
  (#118) — the one authoritative way to bind a script. `node set --property script` returns an
  **actionable** [Operation-reported error code](../../CONTEXT.md) pointing at `script attach`, never a
  second attach entry that would bypass its compile/base-type verification and `replaced_script`
  reporting.
- **Type-check scope: engine-class-typed** Object properties (e.g. `shape: Shape2D`). A property typed
  as a **script `class_name`** (e.g. `config: PlayerConfig`) is **deferred** — its validation reuses
  the unified `class_name` resolver of ADR-0032.
- **Structured failures**, not `uncoercible_value`: a non-`res://` value, a path that does not load as
  a Resource, and a resource whose type is incompatible with the property each report a distinct,
  structured code.
- **Value-typed coercion** (scalar / `Vector2` / `Color`) is unchanged.

## Considered options

- **Create + assign an inline sub-resource** (an embedded `SubResource`, no separate `.tres`) —
  **deferred**, not rejected. It needs new command surface (an `add-subresource` verb) and **nested
  addressing** to `set` the sub-resource's own fields afterward. The external `.tres` reference
  delivers the same "wired scene" value for the highest-value case (mutating existing scenes, per
  #361's own scope note) at a far smaller change. It can be added later under ADR-0025 if a concrete
  "must be inline" need appears.
- **Route the `script` property through the generic Object path too** — **rejected.** It creates two
  ways to attach a script; `script attach` already owns compile / base-type verification and clobber
  reporting (#118, #132).
- **Extend the shared `_coerce_value` to load an Object from a `res://` path** — **rejected.** It lacks
  the expected-class hint, and the change would ride the harness mirror into live `game set` (out of
  scope) for no benefit, while breaking the byte-identical mirror.

## Consequences

- **New public value-form ABI:** `node set` / `resource set` accept a `res://` path for Resource-typed
  properties; agents and tooling may rely on it. This is why the decision is recorded.
- **The [Project-code execution surface](../../CONTEXT.md) (ADR-0009) is not newly widened.** Loading a
  `.tres` runs the same resource `_init` that `resource create` / `load` already run, within the
  Trusted-project assumption — no new trust axis.
- **A recorded asymmetry:** `script` → `script attach`; every other Resource-typed property → `node
  set` / `resource set`. Intentional — one authoritative script-attach path.
- **Ties to ADR-0032:** script-`class_name`-typed property validation will reuse ADR-0032's unified
  `class_name` resolver when that extension (or the deferred inline sub-resource work) lands.
- **The mirrored `_coerce_value` stays byte-identical**; the mirror test (`operations.gd` ↔
  `gda_harness.gd`) is unaffected.
