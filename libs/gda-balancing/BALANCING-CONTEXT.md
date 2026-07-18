# gda-balancing

The shared language of gda-balancing: a standalone, engine- and game-agnostic toolkit for
designing a game's numerics before development and validating balance quantitatively during
it, with structured output suitable for programmatic consumption. (Requirements: PRD #501.)

## Language

### Product

**gda-balancing**:
The toolkit itself. The `gda-` prefix is the **product-family brand** — this is a sibling
product of `gda`, not a `gda` component (contrast `gda-mcp` / `gda-daemon`, which are gda's
own components). It neither depends on nor extends `gda`; its CLI *interface style* follows
gda's conventions (PRD #501 addendum).
_Avoid_: gda balancing module, balancing plugin

**Standard Schema**:
The machine-readable schema for game numeric systems (character attributes, combat, builds,
encounters, growth, economy) that is the toolkit's **sole spec and single authority source**.
The pipeline designs and configures numbers before game development; a game is then developed
consuming the pipeline's Standard Schema output. Non-standard game configs are not adapted or
imported.
_Avoid_: config format, data model, descriptor

**Genre template**:
A genre's numeric design baseline — default values plus formulas-as-data — shipped as an
*instance of the Standard Schema*, never as code paths. First families: RPG (CRPG/JRPG/ARPG)
and Roguelike (metroidvania-like, survivors-like, deckbuilder-like).
_Avoid_: preset, profile

**Reference fixture**:
A paper-game config per supported genre, living in the test suite as an executable consumer
and golden example — exercising template superset paths no live game exercises yet.
_Avoid_: sample project, demo config

### Standard Schema design

**Design document**:
The single root JSON document holding one game's complete numeric design — an instance of
the Standard Schema, declaring the `schema_version` it targets. Subsystems are sections
within it; there is no multi-file document set (bADR-0001). The document names its game;
the toolkit stays game-agnostic.
_Avoid_: config file, numbers file, design config

**Attribute facet**:
One of the orthogonal properties an attribute declaration composes: `domain`
(number / percentage / probability), `base` (direct vs formula — the single scalar
authority), `accepts` (contribution channels: allocation, effects), `bounds` (mandatory
for percentage/probability domains), and descriptive `category`. Facets combine subject
to the cross-facet validity rules enforced at the boundary funnel; no *named tier
composition* is ever mandatory (bADR-0002).
_Avoid_: attribute type, tier (different concept)

**Attribute tier**:
A genre template's **named facet composition** — the vocabulary a template groups its
attributes by (e.g. an RPG template's primary/derived/tertiary layers; a survivors-like's
single flat layer). Template data, not schema law: the Standard Schema requires no tier
taxonomy to exist (bADR-0002).
_Avoid_: stat level, attribute class, schema-enforced tier

**Effect**:
A first-class, time-scoped carrier of numeric influence — the numerical core of a
buff/debuff, status effect, or over-time effect: a list of modifiers, a duration
(instant / timed / infinite), a tick period (its legality governed by the modifier mix),
and — for persistent timed/infinite effects — a reference to a declared stacking type
plus its own re-application `lifetime` (independent / refresh) (bADR-0006). Builds offer effects; combat applies them; simulation consumes their
numbers.
_Avoid_: buff (as the generic term), status (alone), proc

**Modifier**:
One numeric operation inside an `Effect`: a target attribute, an operation
(add / multiply / override), an application kind — continuous (contributes to the value
pipeline while active) or one_shot/periodic (a delta to the simulated current value) —
and a formula-capable magnitude (per-tick amount when periodic). Not an attribute tier
and not a bounded correction coefficient (bADR-0006).
_Avoid_: modifier tier, correction coefficient, stat bonus (vague)

**Stacking policy**:
How same-type effect magnitudes combine — `aggregation` (stack / keep_best), declared
**once per stacking type** in the document's stacking-type catalog, the single authority
no individual effect can override. Orthogonal to an effect's re-application `lifetime`.
Declared data, never formula logic (bADR-0006).
_Avoid_: stacking rule (as a per-effect property), stack behavior

**Named form**:
A parameterized formula shape — a form id plus named parameters (e.g. linear, piecewise
linear, lookup table). The preferred formula representation: its parameters are explicit,
named tuning knobs for Phase-2 sensitivity analysis and search (bADR-0003).
_Avoid_: formula preset, curve type (as a term of art)

**Expression tree**:
The JSON-structured formula AST over a closed operator set — the general fallback when no
named form fits a per-game formula. Operator closure and reference integrity are validated
at the boundary funnel; infix strings are never authoritative (bADR-0003).
_Avoid_: formula script, expression DSL, infix formula

**Reserved section**:
A top-level Design-document section whose name is fixed but whose shape is not yet designed
(`combat`, `encounters`, `builds`, `growth`, `economy`, `targets`). A document using one is
refused until the owning issue lands its shape as a minor schema bump — never
accepted-and-ignored (bADR-0001).
_Avoid_: placeholder section, stub, TODO section

### Validation & self-description

**Boundary funnel**:
The single validation boundary every Design document crosses before any use — three
phases, each gating the next: preflight (ingress caps + version dispatch), structural
(against the structural schema), semantic (the rules the semantic rule catalog indexes).
Validity is a property of a document *state*: any mutation re-enters the funnel before
evaluation or emission. Downstream code never re-validates input; the one sanctioned
downstream class is the non-finite `Evaluation refusal` (bADR-0004).
_Avoid_: input guard, validation pass (as something repeatable downstream)

**Typed refusal**:
The element-level rejection of invalid input: a stable refusal code, a JSON Pointer to the
offending element, and human-readable detail; validation reports **all** violations
(bounded), not fail-fast. A refusal rejects invalid *input*; a verdict judges a *valid*
design against balance targets — the two are never conflated (bADR-0004). One downstream
class exists beyond the funnel: the non-finite `Evaluation refusal` (bADR-0003). The CLI
envelope carrying refusals is #518's contract.
_Avoid_: validation error (vague), warning, exception

**Structural schema**:
The published JSON Schema 2020-12 artifact whose instances are Design documents, `$id`
versioned with the Standard Schema. Passing it means structurally well-formed — not valid;
the semantic layer closes the gap (bADR-0005). Ecosystem validators can run it without the
toolkit installed.
_Avoid_: meta-schema (JSON Schema term of art for schemas-of-schemas), the JSON file

**Semantic rule catalog**:
The machine-readable **index** of semantic-phase rules — rule id (identical to the
refusal code), scope, description, since-version. Together with the structural schema it
answers "what is structurally well-formed and which semantic rules exist"; full validity
additionally requires the versioned validator, the third required artifact. Derived from
the validator or guarded by conformance tests, never hand-maintained twice (bADR-0005).
_Avoid_: rules doc, validation spec (as a prose document)

### Simulation

**Evaluation method**:
A method that *estimates* balance metrics from a config — Monte-Carlo encounter estimation
and system-dynamics (first-order nonlinear ODE) long-horizon prediction. Distinct from a
`Tuning method`; Monte-Carlo is an estimation method, never an "exact algorithm".
_Avoid_: exact algorithm, precise algorithm

**Tuning method**:
A method that *searches* config space toward balance targets — parameter sensitivity
analysis first, then simple (greedy) search; stronger optimizers later. Delivery ordering is
simple-to-hard.
_Avoid_: approximation algorithm, auto-balancer

**Metrics schema**:
The one shape shared by simulated results and (future) observed playtest results, so the
playtest feedback loop can be wired later without schema rework — round-trip capable by
design; ingestion wiring is deferred until playtests produce real feedback.
_Avoid_: report format (as a separate shape)
