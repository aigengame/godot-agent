---
status: accepted
---

# Make Formula notation a canonical reversible projection of structured bodies

Issue #590 established module-level Formula declarations as structured, Model Source-owned pure
programs and made their resolved bodies part of RIR and Model explanation. Follow-up issue #606
tracks this decision's ordered implementation. The structured representation is precise for agents
and conforming implementations, but it is too verbose for routine human review. The existing
`model inspect` presentation only indents the same JSON tree; it does not render conventional
mathematics or accept mathematical notation as authoring input.

Adding an independent infix DSL would create a second semantic authority. Treating notation as
display-only text would instead allow it to drift from the AST, while flattening the current
let-bound program into an expression tree would lose local identities, sharing, evaluation count,
and deterministic resource charges. RIR also needs to carry the paired representation without
making presentation wording part of semantic equivalence.

## Decision

- **The required wire pair is `body` plus `expression`.** Every Formula declaration data instance
  carries those adjacent members. `body` is the pair's sole authoritative source member;
  `expression` is its canonical, reversible projection under one exact Kernel/LDB and Formula
  context. Paired-artifact admission requires `expression` to be byte-identical to
  `render(body).expression` and requires parsing it to produce the byte-identical Kernel-canonical
  `body`. Missing members, non-canonical expression bytes, or body/expression drift produce a typed
  refusal; admission never chooses, repairs, or regenerates either member. This source-level
  ownership does not replace Kernel/LDB language semantics, Typed HIR static semantics, or RIR as
  the public semantic boundary.

- **Formula notation uses conventional package-owned mathematics.** Each Package Release that
  exports a pure Operation owns its notation, including tokens or call names, ordered port mapping,
  precedence, and associativity. The selected LDB closes collision and ambiguity rules. The
  `standard.schema` release owns the generic notation wire grammar and structural/parse Diagnostics;
  `standard.compiler` owns contextual resolution, local result inference, exact canonical-body
  equivalence, and HIR normalization. A host parser or renderer consumes those authorities and
  cannot hard-code an operation catalog.

  The first RPG vertical requires `core.quantity@2.1.0` to declare these exact conventional
  mappings: `quantity.subtract` is infix `-` with ordered ports `left`, `right`;
  `quantity.floor-zero` is `floor_zero(value)`; `quantity.maximum` is `max(left, right)`; and
  `quantity.identity` is `identity(value)`. The list is the initial conformance witness, not a
  complete or host-owned Operation catalog.

- **The canonical surface preserves the Formula program.** A sequence of
  `let <local> = <expression>;` bindings followed by one result expression preserves node order,
  local identities, sharing, evaluation count, and final result. Rendering emits one binding per
  line and the result expression on the final line. A bare identifier matches
  `[A-Za-z_][A-Za-z0-9_]*` and is not a reserved grammar word; every other identifier is enclosed in
  backticks, with backtick and backslash escaping fixed by `standard.schema`. Each segment of a
  module-qualified Symbol or Formula coordinate follows the same rule. Whitespace and parentheses
  are canonical; arbitrary authored layout is not round-tripped.

  The committed `mitigated-damage` body therefore renders without flattening either local:

  ```text
  let raw_damage = damage_before_defense - mitigation;
  let damage = floor_zero(raw_damage);
  damage
  ```

  The committed kebab-case local in `effective-accuracy` demonstrates canonical quoting:

  ```text
  let `minimum-accuracy` = max(base, 1);
  `minimum-accuracy`
  ```

- **Reverse conversion is contextual.** A complete notation-to-body conversion requires the
  Formula's module/import scope, parameter and result contracts, and exact Kernel/LDB. Resolution
  selects exact package/version/Operation coordinates, constructs total named port bindings, and
  infers only local-binding results under the existing typing rules. A bare expression may receive
  lexical or syntax Diagnostics, but it cannot claim a resolved Formula body.

- **The CLI exposes `formula parse` and `formula render`.** Both are non-executing, structured,
  descriptor-owned transformations. `parse` accepts grammar-valid notation, including
  non-canonical whitespace or redundant parentheses, plus its Formula context; it returns the
  complete structured `body` and canonical `expression`. `render` accepts a `body` plus the same
  context, validates it, and returns the same canonical pair. They publish no Resolved Model or
  other semantic artifact. Paired-artifact admission remains stricter than conversion and refuses
  an `expression` that is not already the exact renderer output. Production commands, Model Source
  admission, RIR emission, and Model explanation share one parser, renderer, and equivalence
  implementation. A conformance consumer independently implements the same contracts from sealed
  Kernel/LDB authority and mutually consumes the production artifacts; it cannot import or reuse
  the production parser, renderer, or equivalence implementation.

- **Every Formula data instance carries the same named pair.** Model Source, RIR, and Model
  explanation require adjacent `body` and `expression` members for every Formula declaration.
  Embedded Model Sources, templates, conformance vectors, examples, and fixtures inherit the rule.
  Schema/grammar definitions and records carrying only a Formula identity, binding, or source
  pointer are meta/reference records, not Formula data instances, and do not synthesize the pair.

- **Formula-notation identities derive from orthogonal projections.** Every notation-content
  mutation reidentifies its owning Package Release and whole LDB; Resolved Model consequently
  changes because it binds the exact whole LDB. Package Lock changes if and only if the owning
  Package Release is selected. RIR `content_identity` is the hash of the complete canonical RIR JSON
  and changes if and only if any covered canonical byte changes. Holding every other RIR member
  fixed, a notation-only mutation changes it if and only if at least one canonical `expression` byte
  sequence in the selected reachable Formula projection changes. RIR `semantic_identity` covers
  only the executable semantic projection, excludes `expression`, and never changes for a
  notation-only mutation. Package selection and expression projection effect are therefore
  separate; RIR never embeds a notation catalog merely because a release is selected.

  | Owning Package Release selected | Canonical RIR expression bytes change | Package Release / whole LDB | Package Lock | RIR content | RIR semantic | Resolved Model |
  | --- | --- | --- | --- | --- | --- | --- |
  | yes | yes | change | change | change | unchanged | change |
  | yes | no | change | change | unchanged | unchanged | change |
  | no | no | change | unchanged | unchanged | unchanged | change |

  Under unchanged candidate and ambiguity closure, an unselected release cannot change the current
  model's canonical RIR expression bytes; observing the excluded `no`/`yes` combination exposes an
  invalid selection, ambiguity, or projection closure. A Formula semantic-body mutation within a
  fixed dependency closure is the control case: it changes both RIR identities and downstream exact
  bindings while Package/LDB/Lock identities remain unchanged.

- **The unreleased 2.0 baseline changes clean-forward.** Formula-bearing 2.0 data without the
  canonical expression is refused. Repository-owned authorities, identities, schemas, vectors,
  examples, and fixtures are rebuilt atomically. There is no optional-field fallback, old-Formula
  reader, implicit upgrader, or dual representation authority.

## Considered options

- **Canonical reversible notation derived from the AST** (chosen) — gives humans conventional
  mathematics while retaining one semantic authority and exact round-trip validation.
- **Fully qualified operation-call dumps** (rejected) — simpler to parse but does not meet the human
  mathematical-readability goal and exposes package coordinates as the primary notation.
- **A display-only pretty-printer** (rejected) — cannot satisfy notation-to-AST conversion and lets
  duplicated text drift without an admission invariant.
- **An infix string as a peer authority** (rejected) — duplicates typing, resolution, identity, and
  evaluation semantics beside the structured Formula language.
- **Flatten locals into a pure expression tree** (rejected) — loses local identities and can change
  sharing, evaluation count, and deterministic resource accounting.
- **Include notation in RIR semantic identity** (rejected) — turns a presentation-only change into a
  false behavior change.
- **Keep expression optional for compatibility** (rejected) — creates a permanent dual baseline for
  an unpublished format and weakens the synchronization invariant.

## Consequences

- Notation declarations become sealed LDB package content and must participate in package/vector/root
  reidentification and compatibility checks.
- Model Source, RIR, Model explanation, their schemas, a separately implemented conformance
  consumer, and every embedded Formula fixture must enforce the same `body`/`expression` pair and
  exact canonical-equivalence rule.
- RIR gains distinct content and semantic identities; callers must use the correct one for exact
  retrieval versus semantic comparison.
- The command taxonomy, descriptor registry, manifest, `--schema`, help, diagnostics, and
  conformance harness gain the `formula` group.
- The RPG combat example must demonstrate both conversions, paired JSON in all three artifact
  surfaces, build/inspect continuity, and unchanged runtime meaning.

## Validation

- Render every admitted Formula node/operand kind, parse the result under the same exact context,
  and require byte-identical canonical `body` and `expression`. Repeat through a separately
  implemented conformance consumer, then mutually consume each implementation's paired artifacts.
- Cover integer and admitted Numeric literals; precedence; associativity; required parentheses;
  bare, reserved, Unicode, and backtick-escaped identifiers; ordered Operation-port mappings; named
  Formula-call arguments; module-qualified Symbols; conditionals; local reuse; and zero-node
  parameter bodies.
- Require the initial `core.quantity` witness to round-trip `quantity.subtract`,
  `quantity.floor-zero`, `quantity.maximum`, and `quantity.identity`, including the committed
  two-binding `mitigated-damage` body, the literal `1`, and the quoted `minimum-accuracy` local.
  Mutating a declared token, call name, precedence, associativity, or ordered port mapping must
  produce the exact owning refusal or new canonical pair rather than a host-dependent result.
- Prove `formula parse` canonicalizes grammar-valid whitespace and redundant parentheses, while
  paired Model Source/RIR/Model-explanation admission refuses those same non-canonical bytes unless
  they already equal `render(body).expression`. An unquoted `minimum-accuracy` must never resolve as
  the kebab-case local.
- Refuse missing pair members, AST/expression drift, ambiguous package notation, unresolved names,
  invalid port closure, incompatible types, invalid identifier escaping, and resource-limit
  boundaries with exact stages, Diagnostics, and source locations.
- Prove `formula parse` and `formula render` project from their live Command descriptors and agree
  for argv/structured input, success, refusal, usage, and internal outcomes.
- Mutate notation in a selected Package Release so at least one canonical RIR Formula expression
  changes. Require new Package Release, whole-LDB, Package Lock, RIR content, Resolved Model, and
  downstream exact-wrapper identities while preserving RIR semantic identity.
- Mutate notation in a selected Package Release without changing canonical RIR expression bytes;
  use an Operation outside the selected reachable Formula projection as the required witness.
  Require new Package Release, whole-LDB, Package Lock, Resolved Model, and downstream exact-wrapper
  identities while preserving both RIR identities.
- Mutate notation in an unselected Package Release without changing candidate or ambiguity closure.
  Require new Package Release, whole-LDB, Resolved Model, and downstream exact-wrapper identities
  while preserving Package Lock and both RIR identities.
- For all three notation-only vectors, require the same executable semantic projection and the same
  controlled observations without claiming Replay or Evidence across different exact wrappers.
  Mutate Formula semantics within a fixed dependency closure as a control and require both RIR
  identities plus downstream exact bindings to change while Package/LDB/Lock identities remain
  fixed.
- Build and run the committed RPG combat example after round-tripping its Formulas. Require paired
  Formula data in Model Source, RIR, and Model explanation and the same deterministic trace, state,
  Metrics, and refusal behavior as the corresponding structured bodies.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- Issue #590 — Formula authoring and RPG dogfooding.
- Issue #606 — canonical Formula notation, paired JSON, and RPG combat dogfooding.
- bADR-0012 — language and artifact authority domains.
- bADR-0013 — compiler stages and semantic-equivalence boundary.
- bADR-0021 — Schema 2.0 CLI taxonomy and structured surface.
- bADR-0022 — machine-readable language rules and formal semantics.
- bADR-0023 — sealed multi-member Language Definition Bundle.
