---
status: accepted
---

# Seal the Language Definition Bundle as a content-addressed artifact graph

The first permanent Schema 2.0 slices packaged every language definition and Domain package in one
`language-bundle.json`. That proved exact Kernel/LDB admission, but the artifact reached 226,613 of
the Kernel's 262,144-byte ingress limit after one bounded RPG path. It also serialized package
semantic closures beside reverse-conformance-checked flat registries. The duplication was guarded,
but it made the physical artifact scale with every package and made broad package ownership such as
`game.rpg` easier to hide.

Source-file splitting alone does not fix either problem. Reassembling the fragments into the same
monolith retains the size limit, while treating fragments as independent peer authorities breaks
bADR-0012's single LDB authority. The LDB therefore needs one closed multi-member identity and
admission boundary.

## Decision

- **The LDB is one sealed multi-member artifact graph.** One canonical root manifest binds the
  exact Kernel identity, LDB resources, and a canonically ordered set of child descriptors. The
  Kernel declares descriptor order as package `id`, then `version`; loaders normalize transport
  order before deriving identity or indexes. The manifest is the only membership authority.
  Loaders never scan directories, registries, entry points, or network locations to discover
  semantic members.

- **Each child is one complete Domain-package release.** A descriptor binds the child's artifact
  kind, logical package id and version, canonical content identity, and canonical byte size. Every
  package artifact remains complete under bADR-0016: dependencies, capabilities, types,
  components, operations, conversions, Diagnostics, profiles, rules/bodies, resources, and
  executable vectors belong to that one release identity.

- **Identity has three distinct layers.** Child identity covers the canonical child artifact. Root
  graph identity covers the root's normative members and canonical descriptor set; descriptors bind
  every child identity and size. Downstream exact identities bind the root graph identity according
  to their existing contracts. A physical locator or path is packaging metadata and never enters
  semantic identity. Descriptor reordering or physical relocation cannot change graph identity;
  changing one child must change that child and the root graph identities.

- **Admission is atomic and closed.** Before exposing any admitted language, both independent
  bootstrap consumers verify root and child canonical encoding, identities, sizes, coordinates,
  exact membership, uniqueness, dependency closure, acyclicity, resource bounds, package
  completeness, vectors, and cross-package references. Missing, unreadable, extra, duplicate,
  substituted, mismatched, unresolved, cyclic, or over-limit input produces a deterministic typed
  refusal. No partial package set or derived index becomes visible.

- **Resource accounting is graph-aware.** The Kernel bounds root bytes, per-child bytes, aggregate
  graph bytes, member count, nesting depth, dependency depth, and admission work. Boundary and
  boundary-plus-one vectors cover each limit. A larger package inventory never bypasses bounded
  observation by moving bytes out of the root file.

- **Flat language indexes are derived non-authorities.** After successful graph admission, a
  consumer may construct read-only indexes for operations, types, Diagnostics, profiles, rules,
  schemas, and vectors. Those indexes are deterministic projections of the admitted children. They
  are not packaged, independently hashed, edited, or consumed without graph admission.

- **Public retrieval exposes the exact graph.** The public surface retrieves the root manifest,
  lists its descriptors, and retrieves one canonical child by exact logical coordinate. Source-tree
  and installed-wheel executions expose byte-identical members. A build fails if a declared child
  is absent from the distribution or an undeclared file is treated as active language content.

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
- Package ownership and conformance evidence become physically inspectable without becoming peer
  authorities.
- Consumers use one admission-produced view instead of serialized global registries.
- Adding a package still changes the whole-LDB and Resolved Model wrapper identities. If the package
  is unselected and introduces no ambiguity, the selected Package Lock and RIR semantic payload
  remain byte-identical under bADR-0013 and bADR-0016.

## Validation

- Mutate, delete, substitute, duplicate, reorder, relocate, or add a child and assert the specified
  identity or refusal result.
- Exercise root, child, aggregate, count, depth, and admission-work limits at and above the bound.
- Build and install the wheel, then compare root and child bytes with the source-tree public
  retrieval results.
- Add a non-RPG package witness without changing Kernel primitives, core constructors, runtime
  phases, compiler/evaluator dispatch, or host capability code.
- Run the #540 configure/build/check/run/inspect/edit/rerun loop using the admitted
  `game.resource`, `game.check`, and `game.combat` releases.

## References

- PRD #534
- Issue #540
- Issue #592
- bADR-0012
- bADR-0013
- bADR-0016
- bADR-0017
- bADR-0022
- OCI Image Specification descriptor and Merkle-DAG model (design input only)
