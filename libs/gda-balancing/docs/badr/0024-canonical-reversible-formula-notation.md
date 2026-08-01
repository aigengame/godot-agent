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

- **The structured Formula body remains the sole semantic authority.** Every notation string is a
  canonical, reversible projection of one body under one exact Kernel/LDB. When a Formula data
  instance carries both, admission reparses the notation and requires structural equivalence with
  the body. A missing or mismatched notation is a typed refusal; implementations never silently
  choose, repair, or regenerate one side during admission.

- **Formula notation uses conventional package-owned mathematics.** Each Domain package declares
  notation for its pure Operations, including tokens or call names, ordered port mapping,
  precedence, and associativity. The selected LDB closes collision and ambiguity rules. The
  `standard.schema` release owns the generic notation wire grammar and structural/parse
  Diagnostics; `standard.compiler` owns contextual resolution, local result inference,
  AST-equivalence, and HIR normalization. A host parser or renderer consumes those authorities and
  cannot hard-code an operation catalog.

- **The canonical surface preserves the Formula program.** A sequence of
  `let <local> = <expression>;` bindings followed by one result expression preserves node order,
  local identities, sharing, evaluation count, and final result. Operation bodies use the selected
  conventional infix/function notation. Conditionals, Formula calls, module-qualified Symbols, and
  identifiers that require quoting have one closed LDB-owned spelling. Whitespace and parentheses
  are canonical; arbitrary authored layout is not round-tripped.

- **Reverse conversion is contextual.** A complete notation-to-body conversion requires the
  Formula's module/import scope, parameter and result contracts, and exact Kernel/LDB. Resolution
  selects exact package/version/Operation coordinates, constructs total named port bindings, and
  infers only local-binding results under the existing typing rules. A bare expression may receive
  lexical or syntax Diagnostics, but it cannot claim a resolved Formula body.

- **The CLI exposes `formula parse` and `formula render`.** Both are non-executing, structured,
  descriptor-owned transformations. `parse` accepts notation plus its Formula context and returns a
  complete body plus canonical notation. `render` accepts a body plus the same context, validates
  it, and returns the same paired result. They publish no Resolved Model or other semantic artifact.
  The commands, Model Source admission, RIR emission, and Model explanation share one parser,
  renderer, and equivalence implementation.

- **Every Formula data instance carries the pair.** Model Source, RIR, and Model explanation require
  an adjacent `expression` for every Formula declaration body. Embedded Model Sources, templates,
  conformance vectors, examples, and fixtures inherit the rule. Schema/grammar definitions and
  records carrying only a Formula identity, binding, or source pointer are meta/reference records,
  not Formula data instances, and do not synthesize an expression.

- **RIR separates wire integrity from semantic equivalence.** `content_identity` covers the complete
  canonical RIR JSON, including each validated expression. `semantic_identity` covers only the
  executable semantic projection and excludes expression text. Resolved Model records and validates
  both. A notation-only change therefore changes the exact wire artifact without claiming a model
  behavior change.

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
- Model Source, RIR, Model explanation, their schemas, independent consumers, and every embedded
  Formula fixture must enforce the same pair and equivalence rule.
- RIR gains distinct content and semantic identities; callers must use the correct one for exact
  retrieval versus semantic comparison.
- The command taxonomy, descriptor registry, manifest, `--schema`, help, diagnostics, and
  conformance harness gain the `formula` group.
- The RPG combat example must demonstrate both conversions, paired JSON in all three artifact
  surfaces, build/inspect continuity, and unchanged runtime meaning.

## Validation

- Render every admitted Formula node/operand kind, parse the result under the same exact context,
  and require byte-identical canonical body and notation. Repeat through an independent consumer.
- Cover precedence, associativity, required parentheses, quoted identifiers, named Formula-call
  arguments, module-qualified Symbols, conditionals, local reuse, and zero-node parameter bodies.
- Refuse missing notation, non-canonical notation, AST/notation drift, ambiguous package notation,
  unresolved names, invalid port closure, incompatible types, and resource-limit boundaries with
  exact stages, Diagnostics, and source locations.
- Prove `formula parse` and `formula render` project from their live Command descriptors and agree
  for argv/structured input, success, refusal, usage, and internal outcomes.
- Mutate only canonical notation metadata. Require new LDB/package and RIR content identities while
  the RIR semantic identity and execution observations remain unchanged. Mutate the Formula body and
  require both identities plus downstream exact bindings to change.
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
