---
status: accepted
---

# Value projection: compound Variants (`Dictionary`/`Array`/`Object`) to structured JSON on the read side

`project get` / `node get` / `resource get` (and the live `game get` read) project a value into the
result's `value` field through the shared `_jsonify` helper (#55): scalars and a few fixed-shape value
types (`Vector2`, `Vector2i`, `Color`) pass through, but **every other type — `Dictionary`, `Array`,
and any `Object` — degrades to the Variant's `str()` debug string**. So a compound-valued setting
(surfaced dogfooding Panda Adventure S2's `fire` InputMap action, #381) reads back as
`"{ \"deadzone\": 0.5, \"events\": [InputEventKey: keycode=74 (J), …] }"` — an agent cannot index the
deadzone or enumerate the bound keys, and the event list is not even valid JSON. For a tool whose
positioning is structured, machine-readable output, compound values are exactly where the structure is
missing. `_jsonify` is **byte-identical mirrored** into the [gda harness](../../CONTEXT.md) (the
`--- shared coercion ---` block, enforced by `tests/harness/test_harness_coercion_mirror.py`), so it is also the
projector for the live `game get` read (and any future live value-returning operation) — where a value
can be an **arbitrary runtime Object (a live `Node`) or a cyclic graph**.

## Decision

Extend the shared, mirrored `_jsonify` into a **`Value projection`** (see `CONTEXT.md`): the one
read-side contract for turning a Godot Variant into structured JSON, applied uniformly to **every value
gda emits through `_jsonify`** — the headless `get` reads (`project`/`node`/`resource get`), the value
echoed back by `node set` / `resource set`, the per-entry `value` of `project list` and `scene
get-exports`, and the live `game get` read (and any future live value-returning op).

- **Containers project recursively.** `Dictionary` → a JSON object (keys coerced to strings); `Array`
  and the **packed-array family** (`PackedInt32Array`, `PackedStringArray`, `PackedVector2Array`, …) → a
  JSON array. Each element/value re-enters the projection.
- **Objects render as one of three projection kinds:**
  - **Reference projection** — an `Object` that is a `Resource` with a non-empty `res://` path:
    `{"type": "<Class>", "resource_path": "res://…"}`, **not inlined**. The read-side mirror of
    ADR-0033's write-side `res://`-reference model — read and write name an external resource the same
    way, and a `project get` of a resource-valued setting stays a small, bounded payload.
  - **Inline value projection** — a **whitelisted** path-less value `Object` (`InputEvent` subclasses
    initially, e.g. the `InputEventKey`s inside an InputMap action): `{"type": "<Class>", <its own
    storage properties, each re-projected>}`, reusing the same storage-property model `node get`
    exposes.
  - **String fallback** — any other `Object` (not whitelisted, no `res://` path — the typical live
    `game get` `Node`): the existing `str()` form, unchanged.
- **Reserved keys and collision rules** (the shape is public ABI, so these are fixed here, not left to
  the implementation):
  - Every Object projection carries a `type` discriminator; a **reference projection additionally
    carries `resource_path`**, and an agent distinguishes the two kinds by the presence of
    `resource_path`.
  - To keep that branch unambiguous, the **inline value projection excludes the `Object`/`Resource`
    base bookkeeping** properties (`resource_path`, `resource_name`, `resource_local_to_scene`,
    `script`). Every `InputEvent` **is a `Resource`**, so without this exclusion a path-less value
    Object would emit an empty `resource_path` and masquerade as a reference; the exclusion also drops
    noise. A whitelisted class's own storage property named `type` is **shadowed** by the discriminator
    — documented, not silent.
  - `Dictionary` keys are coerced to strings. If two keys collide after stringification — only possible
    for a **non-string-keyed** Dictionary, never the settings case — the **last entry in Godot's
    insertion-ordered iteration wins** (deterministic, documented), rather than an undefined clobber.
- **Bounded, not cycle-tracked.** A hard recursion **depth cap** degrades an over-deep node to its
  string form; there is **no visited-set**. The structural bounds (references are not descended,
  non-whitelisted Objects stop at `str()`) already make on-disk stored values acyclic trees; the depth
  cap is the backstop against a pathological self-referential `Dictionary` on the live side. The
  projection is **always JSON-encodable** — it never hands `JSON.stringify` an unencodable Variant.
- **Scalars are unchanged** — no regression to the existing round-trip.
- **The whitelist is the risk-isolation boundary.** Because the projector is shared with the live
  harness, projecting *arbitrary* Objects would blow up on a returned `Node` (whole scene tree, cycles,
  huge payloads). The whitelist admits only small, path-less value Objects, so headless and live share
  one projection while the live-only risk stays isolated behind the list.
- **Both `.gd` files change byte-identically**; the mirror invariant and
  `tests/harness/test_harness_coercion_mirror.py` are preserved, not bypassed.

## Considered options

- **A `project get`-only compound renderer, leaving the shared `_jsonify` untouched** — **rejected.**
  The `str()` degradation #381 reports for `project get` exists **identically** for `node get` /
  `resource get` / `game get` / `project list`; a second, project-get-only projector would split the
  read contract and let the same value read two different ways depending on the command.
- **A curated per-type field table for each supported Object class** — **rejected.** It needs a
  registry to maintain and does not generalize to new types; the generic storage-property projection
  reuses the model `node get` already defines, and the whitelist (not a field map) becomes the single
  control point.
- **Inline a `res://` Resource's contents instead of referencing it by path** — **rejected.** It
  produces large payloads and breaks read/write symmetry with ADR-0033, which references external
  resources rather than inlining them.
- **Visited-set cycle detection** — **rejected.** The bookkeeping complicates the byte-identical mirror
  for a case the depth cap already renders safe (no crash, no hang); the shared block stays simple.
- **Nesting the inline projection's fields under a `properties` sub-object** — **rejected** in favor of
  the base-bookkeeping exclusion above: excluding `resource_path`/`resource_name`/… keeps the flat,
  directly-indexable `value.events[0].keycode` shape #381 targets while still removing the
  reference/inline ambiguity.

## Consequences

- **New public output ABI.** Agents and tooling may rely on the projected shapes — indexing
  `value.deadzone`, `value.events[0].keycode`, and the projection fields (`type`, `resource_path`).
  This is why the decision is recorded.
- **Carrying the ABI into the `--schema` / model chain (ADR-0004).** The top-level `value` field stays
  `Any` — a setting's or property's value shape is not statically knowable, so it cannot be fully typed;
  this is a **deliberate, bounded exception** to ADR-0004's model-driven-output rule, limited to the one
  dynamically-typed `value` field. The *stable* parts are modeled and surfaced: the implementation must
  (a) update the `value` descriptions on `ProjectGetResult`, `ListedProjectSetting`, `NodeProperty`, and
  `GameGetResult` (which today describe only scalars and packed Vector/Color lists), (b) define the
  reference / inline value projection shapes as **named result models** so they are documented and
  consumable rather than prose-only, and (c) cover them with `--schema` / round-trip / mirror tests. The
  #381 implementation brief names these surfaces.
- **Uniform read contract + a live-side gain.** A value reads the same across the whole read surface;
  `game get` of a whitelisted value Object now gains structure too, with the live-only risk isolated
  behind the whitelist.
- **The mirrored shared-coercion block grows**; `operations.gd` ↔ `gda_harness.gd` stay byte-identical
  and the mirror test is unaffected.
- **No new `Gda error code`.** This is a read projection; a missing setting is still the existing
  `unknown_setting`.
- **Ties to ADR-0033 (write-side reference model), ADR-0004 (self-description), and #55 (`_jsonify`
  origin).** The deferred inline sub-resource work of ADR-0033 has a read-side counterpart here: a
  path-less inline value Object is projected (whitelisted), not referenced.
- **`CONTEXT.md` gains the `Value projection` glossary term** in this same change.

> **Amendment (2026-08-24, #666) — a fourth projection kind: the texture projection.**
> Dogfooding GDA-DF-011: a path-less `Texture2D` (e.g. `ImageTexture.create_from_image()`, whose
> `resource_path` is intentionally empty) fell to the string fallback — an instance ID that proves two
> objects differ but cannot say what either shows. This amendment adds a **texture projection** for
> path-less `Texture2D` values: `{"type": <Class>, "width": <int>, "height": <int>, "object_string":
> "<the former str() form>", "digest": <"sha256:…" | null>}`. It revises three rules of this ADR,
> named explicitly because the shapes are public ABI:
>
> 1. **"The reference projection shape `{type, resource_path}` is fixed as public ABI"** — unchanged
>    in shape, but no longer the only projection a `Texture2D` can take: one WITH a `res://` path
>    still projects as a reference (dimensions are NOT added to the reference shape); only a
>    path-less one takes the new kind.
> 2. **"The two Object projection kinds are discriminated by the presence of `resource_path`"** — the
>    texture projection carries its own discriminator instead: the presence of **`object_string`**,
>    which the other object shapes never emit. It does NOT emit `resource_path` (not even null), so
>    the reference branch stays unambiguous.
> 3. **"A curated per-type field table — rejected"** — superseded **narrowly, for this one type**,
>    per the issue's triage decision, which this dated note records: the GENERAL curated-table
>    mechanism (a registry of per-class field maps) remains rejected, and the fixed `Texture2D`
>    projector is its one narrow exception — a **new projection kind** (like the reference kind, a
>    fixed shape read off getters), not a whitelist entry: the inline kind emits storage
>    properties, and `Texture2D`'s dimensions are getters while `ImageTexture`'s storage property
>    is a large `image` payload — exactly the live-side risk the whitelist isolates.
>
> `digest` is an **explicit opt-in** (`game get --texture-digest`; the wire param `texture_digest`
> threads through the shared projection): computing it needs `Texture2D.get_image()`, a GPU-to-CPU
> readback on the live side, so every ordinary read keeps it `null`. When requested it is
> `"sha256:"` + the hex digest over the image's dimensions, format, and raw bytes; an image the
> engine cannot read back keeps `null`. The field is **required-but-nullable** — the producer
> always emits the key. The same projection serves headless and live reads (one
> value shape everywhere); the headless read commands do not expose the opt-in flag today — a
> path-less texture only exists where runtime code constructed one, so on the headless side the
> digest field is always `null`. The mirrored shared-coercion block and
> `tests/harness/test_harness_coercion_mirror.py` are preserved.
>
> Two boundary rules complete the kind. **Path-less means EMPTY**: a non-empty, non-`res://`
> `resource_path` (a `user://` path, `take_over_path`) stays the string fallback it always was —
> only the empty path takes this kind. **`object_string` is a reserved key**: the inline value
> projection's exclusion list drops a whitelisted class's own storage property of that name rather
> than copying it, so the presence-based discrimination cannot be spoofed by a custom
> `@export var object_string`. And the live-side risk story now has **two controls, stated
> explicitly**: the inline whitelist remains the boundary for projections that EMIT STORAGE
> PROPERTIES (this ADR's original rule, unchanged for that kind), while the texture kind is safe by
> CONSTRUCTION — a fixed shape read off cheap getters, with the one expensive operation
> (`get_image()`) behind the explicit digest opt-in. The historical whitelist prose above is
> preserved as written; it now governs the inline kind specifically.
