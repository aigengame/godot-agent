# Normative vectors — Standard Schema v1 design (#503)

These vectors are **part of the reviewed design** (bADR-0004): each gives a concrete
input fragment and its required outcome, so #504 implements one result rather than
choosing among several. Fragments assume an enclosing valid Design document
(`schema_version`, `meta`) unless the vector says otherwise. Exact refusal-code strings
are fixed by the generated semantic rule catalog (bADR-0005); vectors identify the
violated rule by its bADR definition, which the catalog's ids must map onto 1:1.

## V1 — Minimal valid document (bADR-0001)

```json
{ "schema_version": "1.0.0", "meta": { "name": "smallest" } }
```

**Expected:** valid. `parameters`/`attributes`/`effects` are designed sections, not
required keys. Adding any unknown top-level key (e.g. `"extra": {}`) → structural
refusal (closed envelope).

## V2 — Typed same-id references (bADR-0002/0003)

```json
"parameters": { "power": 10 },
"attributes": { "items": { "power": { "domain": "number", "base": { "direct": 5 } },
  "strike": { "domain": "number", "base": { "formula": { "op": "add",
    "args": [ { "attr": "power" }, { "param": "power" } ] } } } } }
```

**Expected:** valid — `power` exists in both namespaces; the typed nodes disambiguate.
`strike` evaluates to `5 + 10 = 15`. A hypothetical untyped `{"ref": "power"}` node is
a **structural** refusal (no such node kind exists).

## V3 — Collection-valued named forms (bADR-0003)

With `"level"` declared `{ "domain": "number", "base": { "direct": 3 } }`:

- `{"form": "piecewise_linear", "input": {"attr": "level"}, "points": [[1,10],[5,30]]}`
  → `20` (interpolation); input `0` → `10`; input `9` → `30` (clamp, no extrapolation).
- `{"form": "lookup_table", "input": {"attr": "level"}, "table": [[1,10],[5,30]]}`
  → `10` (step function, greatest `x ≤ 3`); input `5` → `30`; input `0` → `10`.
- `points: [[5,30],[1,10]]` → semantic refusal (strictly-increasing rule).
- `points: [[1,10],[5,{"param":"p"}]]` → structural refusal (collection elements are
  literals only).

## V4 — Tier-pattern satisfaction (bADR-0002)

```json
"tiers": { "primary": { "base": "direct", "accepts": ["allocation", "effects"] } },
"items": { "str": { "domain": "number", "base": { "direct": 8 },
                    "accepts": ["allocation", "effects"], "tier": "primary" },
           "agi": { "domain": "number", "base": { "direct": 8 },
                    "accepts": ["allocation"], "tier": "primary" } }
```

**Expected:** `str` valid; `agi` → semantic refusal at `/attributes/items/agi`
(exact-set matching: pattern requires exactly `{allocation, effects}`).

## V5 — Instant vs persistent stacking declarations (bADR-0006)

- `{"id": "burst", "duration": "instant", "stacking": {"type": "buff", "lifetime":
  "independent"}, ...}` → semantic refusal (instant effects declare no stacking).
- A `timed` effect with **no** `stacking` → semantic refusal (persistent effects
  require one).
- A `timed` effect whose modifiers are all `one_shot` still declares stacking — valid
  but **inert** (one_shot deltas are never selection-gated); not a defect.

## V6 — `period` legality (bADR-0006)

- All-`one_shot` effect declaring `period: 1` → semantic refusal (nothing ticks).
- Continuous-only effect declaring `period: 1` → **valid**: its continuous magnitudes
  re-evaluate at each tick. Without `period`, they evaluate once at application and
  hold.
- `period: 0.01` → semantic refusal (minimum granularity 0.05); `timed` duration `100`
  with `period: 0.005` would additionally violate the tick budget — but granularity
  refuses first (report-all lists both).

## V7 — Additive and multiplicative deltas, same-instant semantics (bADR-0002/0006)

Attribute `hp`: `domain: number`, `base: {direct: 100}`, `bounds: {floor: 0, cap: 200}`,
`accepts: ["effects"]`. Current value `100`. Two `duration: instant` effects apply at
the same instant — `e_hit` (id-earlier): one_shot `add` magnitude `-30`; `e_curse`:
one_shot `multiply` magnitude `0.5`.

**Expected:** both magnitudes and the multiply's realized delta evaluate against the
**common pre-instant snapshot** (`100`): realized `multiply` delta = `100 × (0.5 − 1) =
−50`. Writes land in stable order (`e_curse` after `e_hit` by id): `100 − 30 = 70`,
then `70 − 50 = 20`. Result `20` — **not** `35` (`(100−30)×0.5`), which a
sequential-snapshot implementation would wrongly produce. Later pipeline changes never
re-scale the already-applied `−50`.

## V8 — Global override winner across stacking types (bADR-0006)

Two `infinite` effects with **different** stacking types, each a `continuous`
`override` on `speed` (magnitudes `50` and `80`), applied at t=1 and t=2.

**Expected:** both survive per-type selection; the **latest-applied** (`80`, t=2) wins
globally. If both applied at the same instant, effect-id order decides.

## V9 — Continuous re-evaluation with interacting effects (bADR-0006)

`focus`: `base: {direct: 50}`, `accepts: ["effects"]`. `e_aura`: `timed` 10 s,
`period: 4`, continuous `add` magnitude `{"op": "multiply", "args": [{"literal": 0.1},
{"attr": "focus"}]}` applied at t=0 → contribution `5` (snapshot 50). `e_potion`:
instant one_shot `add` `+50` to `focus` at t=3.

**Expected:** the first tick boundary is one full period after application (t=4), so
the contribution holds at `5` through t=3; at t=4 the magnitude re-evaluates against
the t=4 pre-instant snapshot — the observed value per bADR-0002's per-instant
composition, which **includes `e_aura`'s own prior contribution**: `50 + 5 + 50 = 105`
→ new contribution `10.5`. Had `e_aura` declared no `period`, the contribution would
stay `5` for its whole duration.

## V10 — Non-finite Evaluation refusal (bADR-0003/0004)

`ratio`: `base: {formula: {"op": "divide", "args": [{"literal": 100},
{"attr": "armor"}]}}`. A debuff drives `armor`'s current value to `0` at simulation
time.

**Expected:** the funnel accepts the document (finiteness is not statically decidable);
at evaluation, `100 / 0` → **Evaluation refusal** with the non-finite rule's stable
code — never a propagated `Infinity`.

## V11 — Absent default ≡ materialized default (bADR-0005)

An attribute declared without `accepts` and the same attribute with `"accepts": []`.

**Expected:** semantically equal documents; canonical emission materializes
`"accepts": []`; round-trip acceptance treats both inputs as the same design.

## V12 — Version dispatch (bADR-0001)

- `"schema_version": "1.0.999"` on a `1.0.x` validator → accepted (patch ignored),
  validated against the `1.0` envelope.
- `"schema_version": "1.7.0"` on a `1.2` validator → preflight refusal (newer minor).
- A `1.0` document containing `"builds": {}` → semantic refusal (reserved under 1.0),
  even on a validator whose newest line designs `builds`.
