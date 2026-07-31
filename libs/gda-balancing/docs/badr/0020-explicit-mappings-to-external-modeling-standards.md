---
status: accepted
---

# Adopt explicit mechanisms from modeling standards without importing their runtimes or formats

Standard Schema 2.0 draws on UCUM, MLIR, SBML, FMI, Modelica, and ONNX. Naming those systems without
a mapping would be decorative borrowing: it would not tell an implementer which semantics are
binding, which features are excluded, or how conformance is tested. Directly adopting all six
formats/runtimes would instead create multiple authorities and a scope far beyond game balancing.

PRD #534 therefore requires every external influence to be recorded as a Reference-standard
mapping: adopted mechanism, local owner, rejected surface, and evidence. With one exception—pinned
UCUM physical-unit semantics—the external documents remain provenance rather than runtime
dependencies or alternative specifications.

## Decision

- **External standards enter only through the local layered authority chain.** An irreducible
  mechanism belongs to the Schema-major Kernel Specification; language and package content belongs
  to an exact Language Definition Bundle interpreted under that Kernel Specification. Every adopted
  mechanism is restated as local types, operations, lifecycle rules, verifier laws, lowering rules,
  and normative vectors in its owning layer. Host implementations and the external documents are
  never peer authorities. A newer external-standard release never changes an existing Kernel
  Specification or bundle automatically; adoption or upgrade requires explicit versioned artifacts
  and, where the contract changes, a new bADR.

- **UCUM 2.2 is the pinned physical-unit code and semantic substrate.** A physical Quantity uses a
  case-sensitive UCUM 2.2 expression. Full conformance is required for parsing, canonical semantic
  equality, commensurability, dimension, and conversion magnitude; literal-only “limited
  conformance” is insufficient. UCUM annotations carry no semantics and cannot encode game kinds.
  Health, mana, currencies, damage channels, and other game-only concepts remain namespaced nominal
  kinds/units in Domain packages. Cross-kind conversion still requires an explicit bADR-0016
  Conversion operation.

- **MLIR contributes the operation/dialect/interface/conversion architecture only.** The local
  mapping is:
  - Domain package → dialect-like namespace;
  - Operation specification → declarative operation definition;
  - capability/effect contract → interface/trait-like contract;
  - static legality → verifier;
  - HIR-to-RIR lowering → conversion target plus explicit legal/illegal operations and typed
    conversions.
  Standard Schema 2.0 does not depend on MLIR libraries or TableGen, expose MLIR textual/bytecode
  syntax, accept dynamic evaluator dialects, or make EIR portable. The local Operation
  specification has game/runtime fields MLIR does not supply and remains authoritative.

- **SBML Level 3 contributes modular core/package declarations and semantics-preserving
  composition.** Standard Schema adopts explicit package use, required capability disclosure,
  orthogonality, and deterministic flattening of composed source into a closed RIR. Unlike an SBML
  tool that may preserve unsupported package content, this system fails closed on every unknown or
  unsupported package/capability (bADR-0016). No SBML XML/RNG import/export, biological reaction
  semantics, or claim of SBML conformance is included. Composition conformance is proved by
  source-to-RIR identity/provenance plus golden and differential vectors.

- **FMI 3.0.2 contributes lifecycle-state discipline, not FMU interoperability.** One execution
  instance follows the local Runtime lifecycle:
  - `instantiated`: exact RIR, Experiment Specification, Resolved Runtime profile, inputs, and seed
    are bound; no mutable state exists;
  - `initializing`: initialization operations evaluate against one immutable pre-Snapshot
    Initialization frame and atomically create and validate Snapshot 0; refusal discards the frame
    before Event dispatch and cannot claim an Event, Snapshot, rollback, or terminal audit;
  - `event`: the bADR-0014 scheduler executes atomic events at the current logical time;
  - `step`: the scheduler advances to the next declared observation/logical boundary;
  - `terminated`: terminal trace, snapshot, metrics, and evidence identities are sealed;
  - reset: the runtime instance is discarded and a new initialization begins from the same immutable
    artifacts, never by mutating RIR.
  FMU archives, XML model descriptions, C ABI, Model Exchange, Co-Simulation, Scheduled Execution,
  clocks, callbacks, and binary/source FMUs are not adopted.

- **Modelica 3.6 contributes a reserved equation-modeling pattern, not an initial 2.0 package.**
  `math.equation` is reserved but absent from the initial Language Definition Bundle and first
  tracer. A later bADR and package admission must fix integrator and version, tolerance policy,
  continuous-state Snapshot boundaries, zero-crossing/event coupling, deterministic resource
  bounds, runtime-profile scope, and positive/negative/differential vectors before typed algebraic
  equations or first-order ODEs may lower into RIR. Until then, source requesting the package is a
  `resolution` refusal. The object-oriented class language, `connect` ecosystem, unrestricted
  algorithms/functions, general high-index DAE solving, complete synchronous language, and
  Modelica file compatibility remain excluded.

- **ONNX contributes separation of model/IR/operator-set versions and namespaced operator domains.**
  Standard Schema already separates Schema/LDB, artifact, package/opset, evaluator, and product
  versions; Package Lock binds exact `(domain, operation-set version)`-like identities. Initial 2.0
  has no ONNX model import, graph execution, tensor runtime, or inference dependency. Any future
  learned-model Domain package requires its own decision and must bind exact model content, operator
  domains/versions, runtime/evaluator, Numeric profile, determinism, resource bounds, and declared
  effects before it can enter RIR.

- **A mapping is admitted or claimed only with executable evidence.** The initial Language
  Definition Bundle must carry UCUM vectors for parsing, equality, commensurability, conversion,
  special/non-ratio behavior, and rejection of semantic annotations. MLIR/SBML-derived patterns
  require verifier, package-resolution, conversion-legality, flattening, and cross-evaluator
  vectors. FMI-derived lifecycle rules require legal/illegal transition vectors. The reserved
  Modelica mapping initially requires a negative package-admission vector proving `math.equation`
  cannot enter RIR; a later admission must add solvable, under/overdetermined, event, unit, numeric,
  and resource-limit vectors. ONNX-derived version separation requires package/opset compatibility
  vectors even before learned-model execution can be admitted. Until #534 supplies and validates
  these vectors, this bADR records required mappings but makes no implementation/conformance claim.

- **External names do not appear as unsupported marketing claims.** Documentation may say a
  mechanism is “adopted from” the named version and link this bADR. It may not say Standard Schema is
  FMI-, SBML-, Modelica-, MLIR-, UCUM-, or ONNX-compatible unless the full corresponding conformance
  surface is later implemented and separately decided.

## Considered options

- **Explicit mechanism-by-mechanism mappings** (chosen) — captures mature design lessons while
  preserving one local layered authority chain and testable scope.
- **Treat all standards as informal inspiration** (rejected) — makes references unfalsifiable and
  leaves reviewers unable to distinguish real adoption from terminology.
- **Adopt each external format/runtime directly** (rejected) — creates incompatible authorities,
  dependencies, and far more surface than RPG/Roguelike balancing needs.
- **Use MLIR as the public RIR implementation** (rejected) — leaks compiler framework ABI into the
  Standard Schema contract and conflicts with evaluator-specific EIR freedom.
- **Use UCUM annotations for health/mana/currency** (rejected) — UCUM defines annotations as
  semantically meaningless; package nominal kinds are the honest authority.
- **Promise generic Modelica/SBML import** (rejected) — their full semantics exceed the restricted,
  deterministic, resource-bounded core and would make refusal behavior ambiguous.
- **Embed ONNX now for future ML balance models** (rejected) — no initial user story requires it;
  versioning is useful now, inference is a separately justified package later.

## Consequences

- UCUM 2.2 becomes a normative dependency for physical-unit vectors and must be represented in the
  Language Definition Bundle/version identity.
- The compiler architecture can use generated operation definitions, interfaces, verifiers, and
  legality-checked lowering without introducing an MLIR dependency.
- Package composition and runtime lifecycle gain explicit conformance targets instead of framework
  analogies.
- The Equation package remains a named future extension rather than an underspecified runtime
  bridge in the initial 2.0 bundle.
- External-version updates are deliberate Schema/package evolution, never ambient dependency drift.

## Validation

- Every claimed mapping identifies one exact external version, its local Kernel Specification or LDB
  owner, excluded surfaces, and executable vectors; an unowned or prose-only mapping fails review.
- UCUM vectors cover parsing, canonical semantic equality, commensurability, conversion magnitude,
  special/non-ratio units, and rejection of semantic annotations across independent consumers.
- MLIR/SBML-derived vectors cover verifier legality, package/capability resolution, deterministic
  flattening, and cross-evaluator RIR equivalence; FMI-derived vectors cover every legal and illegal
  lifecycle transition.
- The initial bundle refuses `math.equation`; ONNX-derived package/opset vectors prove exact version
  separation without claiming model import or execution. Updating an external dependency without a
  new local identity must not change any accepted model or result.

## References

- UCUM 2.2 specification (2024-06-17): https://unitsofmeasure.org/ucum
- MLIR dialect, operation, interface, and conversion documentation:
  https://mlir.llvm.org/docs/DefiningDialects/ and
  https://mlir.llvm.org/docs/DialectConversion/
- SBML Level 3 Version 2 Core Release 2 and package catalog:
  https://sbml.org/documents/specifications/
- FMI 3.0.2 specification: https://fmi-standard.org/docs/3.0.2/
- Modelica Language Specification 3.6: https://specification.modelica.org/maint/3.6/
- ONNX versioning and operator-set domains: https://onnx.ai/onnx/repo-docs/Versioning.html
- PRD #534 and bADR-0012/0013/0014/0016 — local authority, IR, runtime, and package contracts.
