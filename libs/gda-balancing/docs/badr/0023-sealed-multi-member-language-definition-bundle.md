---
status: accepted
---

# Seal the Language Definition Bundle as a content-addressed artifact graph

> **Partial supersession (2026-09-06, [bADR-0028](0028-current-language-refactor-and-pre-1.0-retirement.md)):**
> bADR-0028 supersedes versioned collection descriptors as the target and irrelevant whole-LDB
> identity propagation into execution. One current definition per namespace replaces historical
> version selection; selected execution inputs must close before redundant
> whole-LDB/Build-receipt binding fields and fallback reads are deleted. #871 replaces descriptor
> id/version coordinates with namespace ids and id-only ordering; see
> [bADR-0028](0028-current-language-refactor-and-pre-1.0-retirement.md#native-wire-delivery-871-2026-09-07).
> The old coordinate shapes below remain history. Canonical bytes and digests, declared
> membership, complete selected closure, and refusal of ambient discovery remain.

The first permanent Schema 2.0 slices packaged every language definition and Domain package in one
`language-bundle.json`. That proved exact Kernel/LDB admission, but the artifact reached 226,613 of
the Kernel's 262,144-byte ingress limit after one bounded RPG path. It also serialized package
semantic closures beside reverse-conformance-checked flat registries. The duplication was guarded,
but it made the physical artifact scale with every package and made broad package ownership such as
`game.rpg` easier to hide. Splitting packages exposed a second scaling defect: package-owned
normative vectors were semantically owned by each release but physically inlined beside its runtime
semantic closure. The largest package files were already dominated by evidence rather than
executable language semantics.

Source-file splitting alone does not fix either problem. Reassembling the fragments into the same
monolith retains the size limit, while treating fragments as independent peer authorities breaks
bADR-0012's single LDB authority. The LDB therefore needs one closed multi-member identity and
admission boundary.

> **Amendment (2026-08-02, bADR-0024):** Formula notation grammar, pure-Operation notation
> declarations, diagnostics, rules, and vectors are ordinary sealed package content. Changing any
> of them reidentifies its normal vector/release/root graph and exact wrappers that bind the whole
> LDB. bADR-0024 owns the separate Package-Lock and RIR projection effects. No notation catalog enters
> RIR, and no host notation registry or peer grammar authority is introduced.

> **Amendment (2026-08-24, #545):** Replay comparison policies are ordinary sealed Package Release
> content. The implementation advances `standard.experiment` from `1.0.0` to `1.1.0`; it does not
> add a new package id such as `standard.comparison`. `standard.experiment@1.1.0` owns the first
> policy, `exact-replay-v1`, at
> `language.replay_comparison_policies`. The Kernel package contract admits a closed policy with
> `id`, `version`, one policy-wide `comparator`, and ordered stable check keys. Complete
> reproduction-identity equality is an exact Replay precondition, not a policy mode. The Kernel
> includes the collection in required language members,
> `exports.replay_comparison_policies` declares owned policy ids, semantic closure includes the
> authority path, and admission derives one read-only index keyed by policy id. Introducing these
> Kernel contract shapes reidentifies the Kernel, the whole LDB, and downstream exact wrappers. A
> later policy-only change reidentifies the owning release's semantic and content identities, the
> whole LDB, and downstream exact wrappers without changing the Kernel. The Kernel vector union adds
> a `replay-comparison` variant that binds one policy, complete original and Replay observations,
> and expected ordered checks and result. The package-owned vector child uses package-contract
> vectors for structure, ownership, exports, and semantic closure; it uses `replay-comparison`
> vectors with internally consistent observation bundles to exercise every check key and the
> complete ordered result each bundle induces. The policy is not an independent artifact, registry,
> or discovery source.

## Decision

- **The LDB is one sealed multi-member artifact graph.** One canonical root manifest binds the
  exact Kernel identity, LDB resources, and a canonically ordered set of child descriptors. The
  Kernel declares descriptor order as package `id`, then `version`; loaders normalize transport
  order before deriving identity or indexes. The manifest is the only membership authority.
  Loaders never scan directories, registries, entry points, or network locations to discover
  semantic members.

- **Each root child is one complete Domain-package release manifest.** A root descriptor binds the
  manifest's artifact kind, logical package id and version, canonical content identity, and
  canonical byte size. The Package Release is a sealed one-level aggregate represented by exactly
  two authority JSON members: the manifest and one package-owned
  `package-conformance-vector-set`. The manifest closes exact `{id, version}` dependency
  coordinates, capabilities, types, components, operations, conversions, Diagnostics, profiles,
  rules/bodies, Replay comparison policies, resources, and a descriptor for that exact vector child.
  The child binds the owning package id/version and closes the ordered vector id inventory and
  definitions, including a closed empty set. The vector set is not independently versioned,
  selected, published, discovered, or treated as a peer authority.

- **Each package has one independent physical directory.** The dot-separated package id maps to one
  hyphenated directory under `packages/`. For coordinate `game.combat@2.0.0`, the directory is
  `packages/game-combat/` and contains exactly
  `game.combat@2.0.0.json` plus
  `game.combat@2.0.0.conformance-vectors.json`. Directory names and locators are distribution
  metadata, not semantic membership or identity authority. Loaders follow only root and manifest
  descriptors; source/wheel inventory checks reject missing or undeclared directory members. The
  Kernel owns the package-id and version patterns used by root descriptors, manifests, vector
  children, dependencies, public command schemas, loaders, admission, and the rebuild tool. Host
  code retains only path-confinement checks needed before authority admission.

- **Identity separates evidence, release content, and runtime semantics.** Vector-set identity
  covers the canonical evidence child. Package Release content identity covers the manifest,
  including its exact vector-child descriptor. Package Release semantic identity covers only its
  runtime semantic closure. Root graph identity covers the root's normative members and canonical
  Package Release descriptors; downstream exact identities bind that root according to their
  existing contracts. A vector-only change therefore changes vector-set, Package Release content,
  root-LDB, and downstream exact identities while preserving Package Release semantic identity and
  selected runtime semantic payload bytes. Descriptor reordering, physical relocation, directory
  naming, and Locators never enter semantic identity. The Kernel identity law declares the
  domain-separated identity target for the Kernel, LDB root, Package Release collection, and
  package-vector collection; loaders, both bootstrap consumers, and rebuild tooling project those
  declarations instead of maintaining host-owned domain strings.

- **Admission is atomic and closed.** Before exposing any admitted language, both independent
  bootstrap consumers verify root, Package Release manifest, and vector-child canonical encoding,
  identities, sizes, coordinates, exact membership, uniqueness, dependency closure, acyclicity,
  resource bounds, package completeness, vector ownership, and cross-package references. Missing,
  unreadable, extra, duplicate, substituted, malformed, digest/size/coordinate-mismatched,
  unresolved, cyclic, or over-limit input produces a deterministic typed refusal. No partial
  package set or derived index becomes visible. Packaged LDB root, manifest, and vector-child raw
  bytes must equal the Kernel canonical encoding of their decoded value; alternate whitespace or
  key order is refused before descriptor sizes or identities can be treated as valid.

- **Resource accounting is graph-aware.** The Kernel bounds root bytes, each JSON child, aggregate
  bytes per Package Release, total graph bytes, package count, package-member count, nesting depth,
  collection size, dependency depth/steps, and admission work. Boundary and boundary-plus-one
  vectors cover each limit. Splitting evidence from semantics never bypasses bounded observation by
  moving bytes out of a manifest.

- **Flat language indexes are derived non-authorities.** After successful graph admission, a
  consumer may construct read-only indexes for operations, types, Diagnostics, profiles, rules,
  schemas, Replay comparison policies, and vectors. Those indexes are deterministic projections of
  the admitted children. They are not packaged, independently hashed, edited, or consumed without
  graph admission.

- **Public retrieval exposes the exact graph.** `schema get language-bundle` exposes the admitted
  root, Package Release manifests, and vector sets. `package list` enumerates root-declared
  coordinates; `package get` retrieves either the exact release manifest or its
  `conformance-vectors` member without regenerating or merging bytes. Source-tree and installed-wheel
  executions expose byte-identical members. A build fails if either declared member is absent or an
  undeclared JSON file appears in a package directory. Command success schemas close every vector
  definition's top-level shape as the Kernel-declared rule, Diagnostic, package-contract,
  operation-contract, operation-execution, model-program, or `replay-comparison` variant; an invented
  child object cannot pass a public success schema merely because the enclosing vector set is
  closed.

- **The initial RPG tracer uses mechanic packages, not a genre umbrella.** `game.resource`,
  `game.check`, and `game.combat` own their bADR-0017 mechanics independently. The example composes
  them and uses `core.quantity.Quantity` directly. `game.rpg`, `rpg.value`, and `RpgValue` are
  retired before Schema 2.0 release. Generic Model admission, resolution, and compile-profile
  semantics belong to `standard.compiler`; Runtime, Experiment, and observation semantics remain
  with their corresponding standard owners rather than moving under a core or game package.

- **The change is clean-forward.** The unpublished single-file Schema 2.0 form has no compatibility
  reader, fallback, dual authority, or migration path. Formula authoring remains owned by #590 and
  is not introduced by this decision.

## Considered options

- **Maintain fragments and emit one monolithic LDB** (rejected) — reduces merge conflicts but keeps
  the hard size ceiling and serialized projection duplication.
- **Treat package files as peer authorities** (rejected) — permits missing or substituted semantics
  without changing one closed LDB identity.
- **Use one LDB per genre** (rejected) — fragments cross-domain composition and turns package
  selection into an ambient host choice.
- **Use a sealed content-addressed artifact graph** (chosen) — preserves one exact authority while
  allowing bounded, independently verifiable package members.

## Consequences

- Kernel admission and packaged authority loading become graph-aware.
- The root stays small as Domain packages grow; aggregate limits remain explicit.
- Package runtime semantics and conformance evidence become separately bounded and inspectable
  without becoming peer authorities.
- Consumers use one admission-produced view instead of serialized global registries.
- Adding a package still changes the whole-LDB and Resolved Model wrapper identities. If the package
  is unselected and introduces no ambiguity, the selected Package Lock and RIR semantic payload
  remain byte-identical under bADR-0013 and bADR-0016.

## Validation

- Mutate, delete, substitute, duplicate, reorder, relocate, or add a manifest/vector child and
  assert the specified identity or refusal result.
- Exercise root, JSON-child, Package Release aggregate, graph aggregate, count, depth, and
  admission-work limits at and above the bound.
- Build and install the wheel, then compare root, manifest, and vector-child bytes with source-tree
  public retrieval results.
- Add a non-RPG package witness without changing Kernel primitives, core constructors, runtime
  phases, compiler/evaluator dispatch, or host capability code.
- Run the #540 configure/build/check/run/inspect/edit/rerun loop using the admitted
  `game.resource`, `game.check`, and `game.combat` releases.

The permanent conformance suite's non-RPG economy witness reaches the selected Package Lock,
canonical RIR, fixed evaluator, Event trace, Snapshot, and Metric result without adding a Kernel
primitive or genre-selected compiler/evaluator branch. This closes the bounded #592 extension
witness, not bADR-0016's stronger public Extension Invariance Receipt or a genre-support claim.

## References

- PRD #534
- Issue #540
- Issue #592
- bADR-0012
- bADR-0013
- bADR-0016
- bADR-0017
- bADR-0022
- [OCI Image Specification v1.1.1, Content Descriptor: Merkle DAG, `digest`, `size`, and verification](https://specs.opencontainers.org/image-spec/descriptor/?v=v1.1.1)
  (design input only; this bADR does not claim OCI wire-format compatibility)
