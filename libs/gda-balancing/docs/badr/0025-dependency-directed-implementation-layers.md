---
status: accepted
---

# Organize the implementation as dependency-directed layers

Issue #624 records that the implementation has outgrown its original module layout. The
`schema2` namespace groups code by specification generation rather than by ownership: Model
checking and lowering share a module with publication and recovery, bootstrap admission shares a
module with several independent language contracts, and Experiment admission shares a module with
Runtime execution, replay, Evidence, and artifact validation. Command modules also implement
Template semantics and large authority projections. These joins make unrelated changes collide and
allow domain behavior to depend on CLI descriptors and envelopes.

The public product contract is nevertheless stable. The CLI is the current supported user
interface. An accepted decision can add another inbound Interface without changing the layer
model. Kernel/LDB authority, authored authority domains, Formula pairing, RIR identity,
deterministic Runtime behavior, Evidence, publication atomicity, diagnostics, and structured
outcomes remain governed by the existing bADRs. This decision changes implementation ownership and
dependency direction, not Standard Schema semantics.

> **Amendment (2026-08-24, #545):** Comparison semantics is one explicit Domain responsibility. It
> consumes complete authenticated observation inputs and admitted LDB comparison policies, produces
> ordered comparison facts, and independently validates each comparison. Application coordinates
> authentication, execution, comparison, and publication without owning comparison rules. Artifact
> policy owns set completeness and publication. Evidence validation consumes an already published
> comparison and never produces or reinterprets it. The first Replay slice can use one cohesive
> Domain module; it adds no layer, service locator, registry, Repository, or plug-in boundary.

## Decision

- **The implementation has four layers, ordered from lowest to highest:**
  1. **Infrastructure** owns domain-neutral technical mechanisms such as bounded byte input,
     package-resource access, file locking, and atomic filesystem operations.
  2. **Domain** owns Standard Schema authority admission, the Kernel-defined canonical JSON
     profile, and the Formula, Model, Runtime, Experiment, Comparison, Evidence, Template,
     artifact-identity, and publication rules that implement the accepted language and artifact
     contracts.
  3. **Application** owns end-to-end use-case orchestration. It resolves required inputs, invokes
     Domain behavior, coordinates Infrastructure operations, and returns typed results or
     refusals without knowing CLI syntax or rendering.
  4. **UI / Interfaces** owns inbound protocol binding and presentation. The current CLI Interface
     owns argv binding, Command descriptors, the descriptor registry, help, response-schema
     projection, stdout/stderr rendering, exit codes, and mapping Application outcomes to the
     public CLI envelope. Another accepted inbound Interface owns its own transport facts without
     redefining Application or Domain behavior.

- **Imports point from higher layers to lower layers.** The allowed cross-layer direction is
  `interfaces -> application -> domain -> infrastructure`. A module may depend on its own layer or
  a lower one, never a higher one. Same-layer dependencies must remain acyclic. During incremental
  migration, existing unclassified modules may call newly extracted lower-layer modules. Migrated
  lower layers cannot depend on legacy UI or command modules. A migrated CLI Interface module may
  temporarily use the legacy descriptor and envelope modules, whose ownership moves in the final
  UI-composition step, but it cannot import a legacy command handler.

- **Each executable Interface entry point is a composition root for its process.** It may construct
  and connect lower-layer components and sibling inbound adapters, but it owns no language, Model,
  Runtime, Experiment, Template, or publication rule. The current CLI entry point remains the
  composition root for command processes. One UI-owned immutable descriptor registry remains the
  source for CLI dispatch, help, command-schema projection, and the Surface manifest.

- **Modules follow the ubiquitous language and one reason to change.** Authority, Formula, Model,
  Runtime, Experiment, Comparison, Evidence, and Template are candidate cohesive ownership areas,
  not a predeclared internal dependency graph. Their actual boundaries are extracted and checked
  one vertical slice at a time. Generic `common`, `shared`, catch-all artifact, and catch-all
  diagnostic modules are prohibited because they hide ownership rather than establish it.

- **Downward calls are direct; upward observation creates no dependency.** Application and UI code
  call lower-layer behavior directly. Lower layers return typed results and refusals that callers
  interpret. There is no architectural event bus, service locator, or dependency-injection
  container. A callback or event sink may be added only when a concrete producer has a real
  asynchronous consumer; the abstraction belongs with that producer and is wired at the
  composition root. Standard Schema Runtime `Event` values remain domain data, not layer
  notifications.

- **Technical mechanisms do not own Standard Schema policy.** Infrastructure may read an explicitly
  named resource and provide domain-neutral byte operations. Domain code retains the Kernel-defined
  canonical JSON profile, authority-owned member selection, canonical ordering, identity preimage,
  semantic projection, and refusal policy. Authority JSON remains Domain-owned content even though
  Infrastructure reads its packaged bytes.

- **Storage indirection remains evidence-driven.** Domain/Application code separates artifact-set
  completeness, identity, and publication rules from atomic filesystem operations. It does not add
  a Repository or storage port until a second implementation, a required test substitution, or a
  demonstrated dependency inversion need exists.

- **The admitted packaged authority retains one lifecycle owner.** Refactoring cannot introduce a
  second discovery path, admission owner, process cache, or mutable alias. The existing single-
  flight initialization, deterministic cached refusal, immutable published context, and explicit
  test reset remain observable behavior.

- **Standard Schema 1.x is isolated migration input.** Its validator and data model may be used by
  the migration application flow, but active 2.x Domain behavior never depends on them and the 1.x
  implementation does not depend on CLI envelopes.

- **Migration proceeds as end-to-end tracer bullets.** The first tracer is `package list`; later
  command families migrate in the dependency order recorded by #624. A slice moves one coherent
  behavior through Infrastructure, Domain, Application, and CLI while preserving its public
  outputs. Each slice lands green and remains independently revertible. There is no long-lived
  dual authority or second implementation path.

## Considered options

- **Keep `schema2` and split only the largest files** (rejected) — reduces file size without
  correcting the command/domain dependency direction or making ownership discoverable.
- **Adopt Godot directory names literally** (rejected) — Add-ons, Systems, Content, and UI express
  useful dependency principles, but they do not name this Python product's Standard Schema
  responsibilities.
- **Adopt ports, repositories, and events for every boundary** (rejected) — creates more types and
  navigation without a current substitution or asynchronous communication need.
- **Move the whole package in one change** (rejected) — delays feedback, makes behavior drift hard
  to localize, and prevents narrow rollback.
- **Use four dependency-directed layers with vertical migration** (chosen) — makes ownership and
  allowed change paths explicit while preserving working software after every slice.

## Consequences

- New production modules live under `infrastructure`, `domain`, `application`, or an explicit
  `interfaces` adapter according to ownership. Existing modules disappear only after their
  responsibilities and callers have migrated; undocumented Python import paths receive no
  permanent compatibility shim.
- A small AST-level architecture test rejects upward imports and cycles among migrated modules.
- Command handlers become thinner as semantics move down; lower layers no longer import CLI
  descriptors, envelopes, or response schemas.
- The migration may temporarily contain old and new module locations, but never two semantic
  authorities or two writers for the same result.
- The bADR remains the decision authority. `docs/ARCHITECTURE.md` describes the implemented current
  structure after migration; no permanent third module map is maintained.

## Validation

- Run focused public-boundary tests after each small change and the complete suite plus pyright
  before completing a coherent migration stage.
- Compare CLI stdout/stderr, exit codes, diagnostic content and ordering, canonical artifact bytes
  and identities, publication receipts and recovery, Formula round trips, and deterministic Runtime
  outcomes across each affected slice.
- For every additional inbound Interface, prove that its framework, transport, lifecycle, and
  presentation dependencies do not enter Application or Domain and that it reaches the same
  semantic owners as the CLI where their use cases overlap.
- Run source/wheel parity when packaged resources, entry points, or publication are affected.
- Preserve the existing authority-lifecycle tests proving a single production owner, single-flight
  admission, immutable context, and deterministic cached refusal.
- Treat any public behavior difference as a separate requirement change rather than absorbing it
  into this refactor.
