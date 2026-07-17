---
status: proposed
---

# Formulas as data: named forms first, a closed-operator expression tree as fallback

Attribute bases, effect magnitudes, and growth curves need formulas that are
inspectable, mechanically validatable, and mutable by agents (PRD #501 US3, US8) — and
tunable by Phase-2 search methods. PRD #501's problem statement records the inversion
this bADR reverses: code owning the formulas while data supplies only scalar
coefficients. This bADR fixes the authoritative formula representations (design gate
#503).

## Decision

- **Two authoritative representations, layered:**
  1. **Named form** — a declared, parameterized formula shape: a form id, an `input`
     reference, and form-specific fields (e.g. `{"form": "linear", "input":
     {"attr": "vit"}, "base": 20, "per_point": {"param": "hp_per_vit"}}`), including
     lookup/curve tables for sampled curves. **The v1 form set is normative here**:
     `linear`, `piecewise_linear`, `polynomial`, `exponential`, `lookup_table` — each
     with the normative contract below. Adding a form is a schema **minor** bump
     (bADR-0001) justified by template need — never an implementation-time choice. Precedent, multi-party (#503 research):
     engine framework — Unreal GAS curve tables (row per stat, column per level, CSV/JSON
     import, explicitly for whole-game rebalancing and spreadsheet pipelines); Unity —
     `AnimationCurve` documented as a general-purpose data curve with `Evaluate(time)`
     keyframe lookup, plus community stat systems shipping curve-typed stat values;
     tabletop — d20's Score→Modifier published lookup tables; literature — the canonical
     Game Balance text treats spreadsheets as the baseline numeric-design medium.
  2. **Expression tree** — a JSON-structured AST over a **closed operator set**. **The
     v1 node and operator set is normative here**: leaf nodes `{"literal": <number>}`,
     `{"attr": "<attribute id>"}`, and `{"param": "<parameter id>"}` — references are
     **typed at the node**, so an id existing in both the attribute and parameter
     namespaces (legal, bADR-0002) is never ambiguous; there is no bare untyped `ref`
     and no special context reference. Operator nodes are `{"op": "<name>", "args":
     [<nodes>]}` with fixed arity: `add`, `multiply`, `min`, `max` are n-ary (≥ 2);
     `subtract`, `divide`, `power` are binary; `floor`, `ceil`, `round` are unary.
     `round` rounds **half away from zero**. No conditionals in v1; adding an operator
     is a schema **minor** bump (bADR-0001). The general fallback for arbitrary
     per-game formulas (US7). Progression variables (e.g. a level) are **ordinary
     attributes** a template declares (`base: direct`) and formulas reference like any
     other — US3's "HP from VIT and Level" is expressible today; progression
     *semantics* over such attributes land with the `growth` section (#507) as a minor
     bump, adding no new reference kind.

- **Normative v1 named-form contracts.** Every named form declares `input` — a single
  typed reference node (`attr` or `param`) that is the form's independent variable —
  and its form-specific fields. Each field value is either a **literal number** or a
  **parameter reference** `{"param": "<id>"}`: the top-level `parameters` section
  remains the *sole declaration home* (a form never declares parameters, it references
  them), and only referenced parameters are tuning knobs — a literal is a deliberate
  non-knob. The forms, with `x` = the evaluated input:
  - `linear` — fields `base`, `per_point`; value `base + per_point·x`.
  - `piecewise_linear` — field `points`: an array of `[x, y]` pairs, `x` strictly
    increasing, ≥ 2 pairs; value by linear interpolation between neighboring points;
    inputs outside the range **clamp** to the first/last `y` (no extrapolation).
  - `polynomial` — field `coefficients`: `[c0, c1, …, cn]` in **ascending degree**
    (value `c0 + c1·x + … + cn·xⁿ`), 1–8 coefficients.
  - `exponential` — fields `coefficient`, `growth_rate` (> 0); value
    `coefficient · growth_rate^x`.
  - `lookup_table` — field `table`: an array of `[x, y]` pairs, ≥ 1 pair, `x` strictly
    increasing; a **step function**: value is the `y` of the greatest `x ≤ input`;
    inputs below the first `x` take the first `y`. (Interpolating curves use
    `piecewise_linear`; `lookup_table` never interpolates.)
     Precedent, expression-language ecosystem (#503 research): JsonLogic (explicitly "an
     abstract syntax tree", one operator per rule) and MathJSON (function application as
     JSON arrays); CEL attests the closed-set discipline — deliberately
     non-Turing-complete, host-data-only, with subsetting/extension of the operator
     surface as a first-class design feature. **Recorded deviation from engine
     practice:** the dominant engine framework has no in-data expression language — GAS's
     data layer stops at simple modifier operations plus curve lookups and escapes to
     C++ (`ExecutionCalculation`) for multi-attribute formulas. An in-schema expression
     tree therefore goes *beyond* engine precedent, and necessarily so: a design-time
     pure-data authority has no code layer to escape to.

- **Formula consumers.** One representation pair serves every formula in the document:
  attribute bases declared `formula` (bADR-0002), effect modifier magnitudes including
  per-tick amounts (bADR-0006), and — as their sections land — growth/economy curves
  (#507). No consumer gets a private formula dialect.

- **Named forms are the preferred representation** for growth curves, derived bases,
  and effect magnitudes.
  Their parameters are explicit, named tuning knobs — Phase-2 sensitivity analysis and
  search operate on named parameters directly, with no structure mining. Templates
  (#505, #506) ship named-form-heavy defaults; the expression tree is reached for only
  when no form fits. Of the two authoritative representations, the expression tree —
  showing the whole computation explicitly — is the more human-readable; the priority
  order optimizes for tunability, not against readability.

- **Parameters are first-class, named, and declared in one home.** The document's
  top-level `parameters` section (bADR-0001) is the sole declaration home: a map of
  parameter id → value (ids per bADR-0002's namespace rules). Formulas reference
  declared parameters by id; an undeclared reference is a typed refusal (bADR-0004).
  The parameter set is the design's tuning surface. (Tuning ranges/annotations on
  parameters are Phase-2 material — the declaration shape reserves room, milestone #9.)

- **Numeric semantics.** Formula values are IEEE-754 doubles. Every formula evaluation
  must produce a **finite** result: division by zero, overflow to infinity, or NaN is
  an **Evaluation refusal** — the single sanctioned downstream refusal class
  (bADR-0004): finiteness depends on runtime values the boundary funnel cannot see, so
  the evaluator refuses with a stable code rather than propagating a non-finite value.
  Expression trees are bounded — depth ≤ 32, ≤ 256 nodes per formula (v1 normative
  limits; raising them is a minor bump) — so evaluation cost is bounded by
  construction.

- **Operator closure is a validation surface.** An expression tree using an operator
  outside the closed set, or referencing an undeclared attribute/parameter, is an
  element-level typed refusal at the boundary funnel (bADR-0004) — never a runtime
  evaluation error.

- **Caps and clamps are first-class schema fields** on attribute declarations
  (bADR-0002), never functions inside expressions. **This is a recorded deviation
  without dominant precedent** (#503 research flag): GAS's Min/MaxValue data columns are
  explicitly non-functional — clamping is hand-coded in imperative hooks
  (`PreAttributeChange` / `PostGameplayEffectExecute`) — and JsonLogic composes
  `min`/`max` inside the expression tree. Neither option is available or right here: a
  design-time pure-data authority has no code hooks, and burying bounds inside
  expressions hides them from the validator and from Phase-2 tuning. The deviation is
  kept honest by fixing its **evaluation semantics**: a declared cap/floor is exactly a
  clamp applied to the attribute's **final value** — formula-computed and/or
  contribution-driven, whichever channels its facets admit (bADR-0002) —
  semantically equivalent to lowering into an in-expression `min(max(…))` at evaluation
  time, i.e. the declarative field changes *where bounds are stated*, not *how they
  compute* (which matches dominant practice). (`min`/`max` *operators* remain available inside expressions for genuine
  formula logic; the *output clamp* of an attribute is declarative.)

- **Infix strings are not authoritative.** A spreadsheet-style string syntax (e.g.
  `"20 + 5*VIT"`) may later be added as one-way authoring sugar that *compiles to* the
  authoritative representations; it is never stored as the authority and never
  round-tripped back. Precedent (single ecosystem, labeled as such): MathJSON treats the
  JSON tree as the canonical computational form and LaTeX as a non-authoritative
  parse/serialize boundary. (A parallel claim about CEL's canonical AST was refuted in
  verification — CEL is deliberately **not** cited for this point.)

## Considered options

- **Named forms + closed expression tree** (chosen) — machine-first (US8: agents
  generate/check/mutate documents), explicit knobs for Phase-2 tuning, expressiveness
  preserved via the fallback.
- **Pure expression tree** (rejected) — single mechanism, but tuning knobs become
  implicit tree leaves; sensitivity analysis must first mine structure to find them.
- **Pure named forms** (rejected) — an expressiveness ceiling: per-game custom mechanics
  (US7) would force either forking the toolkit or growing the form set unboundedly.
- **Infix-string DSL as the authority** (rejected) — human-readable, but the grammar
  becomes a second spec surface; JSON Schema can only pattern-check it (structural
  validation stops at the string boundary), and agent mutation pays
  parse→mutate→serialize on every edit.
- **Code plugins for formulas** (rejected outright) — formulas must be data (PRD #501).

## Consequences

- #504 implements exactly two evaluators (form interpreter, tree walker) behind one
  formula seam; adding a v1 form or operator is a schema **minor** bump (bADR-0001).
- The pinned tree limits (depth ≤ 32, ≤ 256 nodes) are enforced as element-level
  semantic rules at the boundary funnel (bADR-0004) — pathological documents are refused
  at the boundary, not discovered in the evaluator.
- The Phase-2 tuning loop (milestone #9) gets its knob inventory for free: the declared
  parameter set.

## References

- Research provenance (non-normative, provenance-labeled, incl. the refuted-claims list):
  issue #503 comments — main report and supplement. Precedents examined there: Unreal GAS
  curve tables & modifier ops; Unity `AnimationCurve` & community stat systems (Fluid
  Stats); Godot Gameplay Attributes; d20 SRD; Schreiber & Romero, *Game Balance*;
  JsonLogic; MathJSON; CEL.
