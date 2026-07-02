---
status: accepted
---

# Value projection: compound Variants (`Dictionary`/`Array`/`Object`) to structured JSON on the read side

`project get` / `node get` / `resource get` (and the live `game` reads) project a value into the
result's `value` field through the shared `_jsonify` helper (#55): scalars and a few fixed-shape value
types (`Vector2`, `Vector2i`, `Color`) pass through, but **every other type — `Dictionary`, `Array`,
and any `Object` — degrades to the Variant's `str()` debug string**. So a compound-valued setting
(surfaced dogfooding Panda Adventure S2's `fire` InputMap action, #381) reads back as
`"{ \"deadzone\": 0.5, \"events\": [InputEventKey: keycode=74 (J), …] }"` — an agent cannot index the
deadzone or enumerate the bound keys, and the event list is not even valid JSON. For a tool whose
positioning is structured, machine-readable output, compound values are exactly where the structure is
missing. `_jsonify` is **byte-identical mirrored** into the [gda harness](../../CONTEXT.md) (the
`--- shared coercion ---` block, enforced by `tests/test_harness_coercion_mirror.py`), so it is also the
projector for the live `game get` / `game call` reads — where a value can be an **arbitrary runtime
Object (a live `Node`) or a cyclic graph**.

## Decision

Extend the shared, mirrored `_jsonify` into a **`Value projection`** (see `CONTEXT.md`): the one
read-side contract for turning a Godot Variant into structured JSON, applied uniformly across every
read surface (headless `project`/`node`/`resource get` + set-echo + `project list`, and the live
`game` reads).

- **Containers project recursively.** `Dictionary` → a JSON object (keys coerced to strings); `Array`
  and the **packed-array family** (`PackedInt32Array`, `PackedStringArray`, `PackedVector2Array`, …) → a
  JSON array. Each element/value re-enters the projection.
- **Objects render as one of three descriptor kinds:**
  - **Reference descriptor** — an `Object` that is a `Resource` with a `res://` path:
    `{"type": "<Class>", "resource_path": "res://…"}`, **not inlined**. The read-side mirror of
    ADR-0033's write-side `res://`-reference model — read and write name an external resource the same
    way, and a `project get` of a resource-valued setting stays a small, bounded payload.
  - **Inline value descriptor** — a **whitelisted** path-less value `Object` (`InputEvent` subclasses
    initially, e.g. the `InputEventKey`s inside an InputMap action): `{"type": "<Class>", <its storage
    properties, each re-projected>}`, reusing the same storage-property model `node get` already
    exposes.
  - **String fallback** — any other `Object` (not whitelisted, no `res://` path — the typical live
    `game get` `Node`): the existing `str()` form, unchanged.
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
  `tests/test_harness_coercion_mirror.py` are preserved, not bypassed.

## Considered options

- **A `project get`-only compound renderer, leaving the shared `_jsonify` untouched** — **rejected.**
  The `str()` degradation #381 reports for `project get` exists **identically** for `node get` /
  `resource get` / `game get`; a second, project-get-only projector would split the read contract and
  let the same value read two different ways depending on the command.
- **A curated per-type field table for each supported Object class** — **rejected.** It needs a
  registry to maintain and does not generalize to new types; the generic storage-property projection
  reuses the model `node get` already defines, and the whitelist (not a field map) becomes the single
  control point.
- **Inline a `res://` Resource's contents instead of referencing it by path** — **rejected.** It
  produces large payloads and breaks read/write symmetry with ADR-0033, which references external
  resources rather than inlining them.
- **Visited-set cycle detection** — **rejected.** The bookkeeping complicates the byte-identical mirror
  for a case the depth cap already renders safe (no crash, no hang); the shared block stays simple.

## Consequences

- **New public output ABI.** Agents and tooling may rely on the projected shapes — indexing
  `value.deadzone`, `value.events[0].keycode`, and the descriptor fields (`type`, `resource_path`).
  This is why the decision is recorded.
- **Uniform read contract + a live-side gain.** A value reads the same across `project`/`node`/`resource
  get` and the live `game` reads; `game get` / `game call` of a whitelisted value Object now gains
  structure too, with the live-only risk isolated behind the whitelist.
- **The mirrored shared-coercion block grows**; `operations.gd` ↔ `gda_harness.gd` stay byte-identical
  and the mirror test is unaffected.
- **No new `Gda error code`.** This is a read projection; a missing setting is still the existing
  `unknown_setting`.
- **Ties to ADR-0033 (write-side reference model) and #55 (`_jsonify` origin).** The deferred inline
  sub-resource work of ADR-0033 has a read-side counterpart here: a path-less inline value Object is
  projected (whitelisted), not referenced.
- **`CONTEXT.md` gains the `Value projection` glossary term** in this same change.
