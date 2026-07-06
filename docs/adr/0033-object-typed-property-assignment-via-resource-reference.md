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

- **Object resolution stays outside shared `_coerce_value`.** The shared coercion helper is
  **byte-identical mirrored** into the [gda harness](../../CONTEXT.md) for `game set` (ADR live layer).
  Since #427, its `(raw, type, current = null)` signature may use the current value only for
  typed `Dictionary` / `Array` container assignment; it still does **not** carry the property's
  expected Resource class. Object resolution is therefore a **separate, headless-only step** in
  `node set` / `resource set` that reads the expected-class hint from the full property-list entry.
  Assigning a Resource on a live `game set` is **out of scope**; the mirror stays green.
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
  structured code. The concrete `GdaError` codes are **not fixed here** — since `GdaError.code` is
  public ABI whose authoritative source is the error registry (ADR-0002), the implementation slice
  (#363) mints them and registers them there when it lands (the ADR-0031 pattern).
- **Value-typed coercion** (scalar / `Vector2` / `Color`, plus JSON container coercion) remains
  separate from Object reference loading.

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

- **New public value-form ABI:** `node set` / `resource set` accept a `res://` path for
  **engine-class-typed** Resource/Object properties (script-`class_name`-typed properties are deferred,
  per the contract edge above); agents and tooling may rely on it. This is why the decision is recorded.
- **The [Project-code execution surface](../../CONTEXT.md) (ADR-0009) widens.** `node set` / `resource
  set` gain a new entry point that **loads** an external Resource value (`--value res://…`), so a
  **script-backed** Resource's `_init` runs on load — from a point the surface did not previously
  enumerate (it covered `_init` only for a resource an operation *constructs*, e.g. `resource create`).
  This stays **within** ADR-0009's Trusted-project assumption and adds **no new trust axis** — only a
  documented widening of the same surface, the ADR-0031 precedent. `CONTEXT.md`'s
  `Project-code execution surface` glossary entry is aligned in this same change.
- **A recorded asymmetry:** `script` → `script attach`; every other **engine-class-typed** Resource
  property → `node set` / `resource set`. Intentional — one authoritative script-attach path.
- **Ties to ADR-0032:** script-`class_name`-typed property validation will reuse ADR-0032's unified
  `class_name` resolver when that extension (or the deferred inline sub-resource work) lands.
- **The mirrored `_coerce_value` stays byte-identical**; the mirror test (`operations.gd` ↔
  `gda_harness.gd`) remains the guard. Container type context introduced by #427 is mirrored; Object
  expected-class context is not.
