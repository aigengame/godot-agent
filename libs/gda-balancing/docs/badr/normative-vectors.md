# Normative vectors — Standard Schema v1 design (#503)

These vectors are **part of the reviewed design** (bADR-0004): each gives a concrete
input fragment and its required outcome, so the owning issue (bADR-0004's ownership
split — validation vectors → #504, runtime evaluation vectors → #510) implements one
result rather than choosing among several. Fragments assume an enclosing valid Design document
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

- `"effects": {"items": {"burst": {"duration": "instant", "stacking": {"type": "buff",
  "lifetime": "independent"}, ...}}}` → semantic refusal (instant effects declare no
  stacking).
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
  with `period: 0.005` violates granularity **and** the tick budget — report-all lists
  both refusals.
- **Continuous-only tick budget:** a `timed` 600 s effect with only `continuous`
  modifiers declaring `period: 0.05` → `600 / 0.05 = 12 000 > 10 000` → semantic
  refusal. The budget applies to **any** timed effect declaring `period`, not only to
  `periodic` deltas.

## V7 — Additive and multiplicative deltas, same-instant semantics (bADR-0002/0006)

Attribute `hp`: `domain: number`, `base: {direct: 100}`, `bounds: {floor: 0, cap: 200}`,
`accepts: ["effects"]`. Current value `100`. Two `duration: instant` effects apply at
the same instant — `a_hit` (id-earlier): one_shot `add` magnitude `-30`; `b_curse`:
one_shot `multiply` magnitude `0.5`.

**Expected:** both magnitudes and the multiply's realized delta evaluate against the
**common pre-instant snapshot** (`100`): realized `multiply` delta = `100 × (0.5 − 1) =
−50`. Writes land in stable order (`b_curse` after `a_hit` by id): `100 − 30 = 70`,
then `70 − 50 = 20`. Result `20` — **not** `35` (`(100−30)×0.5`), which a
sequential-snapshot implementation would wrongly produce. (No bound is crossed here,
so the two writes commute — order sensitivity under clamping is V13's job.) Later
pipeline changes never re-scale the already-applied `−50`.

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
{"attr": "armor"}]}}`. A debuff drove `armor`'s current value to `0` at an **earlier
instant**, so `armor = 0` is part of the current instant's pre-instant snapshot (a
same-instant write would be observed only on the following instant, per the
read-environment rule).

**Expected:** the funnel accepts the document (finiteness is not statically decidable);
during simulation, `ratio`'s base formula recomputes reading the **pre-instant
snapshot** (bADR-0003 read environments), observes `armor = 0`, and `100 / 0` →
**Evaluation refusal** with the non-finite rule's stable code — never a propagated
`Infinity`.

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

## V13 — Saturated ledger persistence and order-sensitive clamping (bADR-0006)

Attribute `hp`: `base: {direct: 100}`, `bounds: {floor: 0, cap: 120}`,
`accepts: ["effects"]`. Ledger equation: `L ← clamp(P + L + d, bounds) − P`.

**Part A — overflow is lost, not banked.** Current value `100` (`P = 100`, `L = 0`).
A one_shot `multiply` `2` realizes `100 × (2 − 1) = +100`; the write saturates:
`L ← clamp(100 + 0 + 100, [0,120]) − 100 = +20`. The pipeline later falls to `P = 50`
→ observed `clamp(50 + 20) = 70` — **not** `120` (a full-delta ledger banking the
clipped `+80` is the rejected alternative).

**Part B — bound-crossing writes are order-sensitive.** Same attribute, current `100`.
Same-instant effects `a_blessing` (one_shot `multiply` `2` → realized `+100` from
snapshot `100`) and `b_strike` (one_shot `add` `−80`). Stable order by id:
`a_blessing` first — `L ← clamp(100 + 0 + 100) − 100 = +20` (saturated at 120), then
`b_strike` — `L ← clamp(100 + 20 − 80) − 100 = −60`. Observed `40`. Had the ids
ordered the strike first: `100 − 80 = 20`, then `+100` saturates at `120` → observed
`120`. The stable order is therefore load-bearing exactly when writes cross bounds.

## V14 — Instant phase order: activation, delta, expiry (bADR-0006)

Attribute `hp`: `base: {direct: 100}`, `bounds: {floor: 0, cap: 120}`,
`accepts: ["effects"]`. At t=1, one `timed` 2 s effect applies carrying **both** a
`continuous` `add` `+20` and a `one_shot` `add` `+10`.

**Expected (phase order: expiry → activation → pipeline → writes):** at t=1 the
continuous contribution activates first, so the pipeline component becomes
`P = 100 + 20 = 120`; the one_shot then writes against it —
`L ← clamp(120 + 0 + 10, [0,120]) − 120 = 0` (fully saturated away). Observed `120`.
At t=3 (expiry) the continuous contribution leaves: observed
`clamp(100 + 0) = 100` — **not** `110`, which the rejected write-before-activation
order (`P = 100`, `L = +10`) would produce. Expiry alone never touches the ledger.

## V15 — Tick coincident with expiry does not fire (bADR-0006)

Attribute `hp`: `base: {direct: 100}`, `bounds: {floor: 0, cap: 120}`,
`accepts: ["effects"]`. At t=0 a `timed` 4 s effect applies with `period: 2` and a
single `periodic` `add` `−10` modifier (stacking declared; type immaterial here).

**Expected:** ticks are due at t=2 and t=4. The t=2 tick fires (`L ← clamp(100 + 0 −
10) − 100 = −10`, observed `90`). At t=4 the effect expires in phase 1 **before**
phase-4 writes, so the coincident tick does **not** fire: `duration = 2 × period`
fires exactly one tick. Final observed value `90` — never `80`.

## V16 — `round` tie rule (bADR-0003)

`{"op": "round", "args": [{"literal": 2.5}]}` → `3`;
`{"op": "round", "args": [{"literal": -2.5}]}` → `-3`;
`{"op": "round", "args": [{"literal": 2.4}]}` → `2`.

**Expected:** half away from zero only — a round-half-even implementation
(`round(2.5) = 2`) is non-conforming. The arithmetic rounding mode
(round-to-nearest-even) governs `add`/`subtract`/`multiply`/`divide`/`min`/`max`
results, never the semantic `round` operator.

## V17 — Phase-3 suborder: re-evaluate before selecting (bADR-0006)

`charge`: `base: {direct: 10}`, `accepts: ["effects"]`. `power`:
`base: {direct: 100}`, `accepts: ["effects"]`. Stacking type `buff`:
`aggregation: keep_best`. Two `infinite` effects of type `buff`, both applied at t=0,
both declaring `period: 2`, each one `continuous` `add` on `power`:

- `a_steady`: magnitude `{"attr": "charge"}` → `10` at t=0
- `b_scaling`: magnitude `{"op": "subtract", "args": [{"literal": 21},
  {"op": "multiply", "args": [{"literal": 2}, {"attr": "charge"}]}]}` → `1` at t=0

At t=0, `keep_best` selects `a_steady` (`10` > `1`): observed `power = 110`. At t=1 a
one_shot `add` `−9` drives `charge` to `1`.

**Expected at the t=2 tick:** phase 3a re-evaluates **both** magnitudes against the
pre-instant snapshot (`charge = 1`): `a_steady` → `1`, `b_scaling` → `21 − 2 = 19`;
phase 3b then selects `b_scaling` (`19`); observed `power = 119`. The rejected
select-before-re-evaluate order would keep `a_steady` and observe `101`.
