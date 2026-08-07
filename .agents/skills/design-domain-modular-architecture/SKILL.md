---
name: design-domain-modular-architecture
description: Design and review practical modular software architectures with domain models as the basis for boundaries, ownership, dependencies, and evolution. Use when structuring a new system, modularizing an existing codebase, separating domain rules from use-case coordination and external integration, identifying context or module boundaries, reviewing coupling, or planning an incremental architecture change.
---

# Design Domain Modular Architecture

## Goal

Design the smallest usable architecture that gives the current system complete and
distinct responsibilities, one authority for each rule, one-way dependencies, and
clear extension paths.

Use Domain-Driven Design (DDD) as the theory for judging boundaries and evolution. Do
not treat it as a set of patterns that every project must implement. Introduce a bounded
context, aggregate, repository, domain service, or other DDD building block only when
it solves an observed problem.

Unless the user asks only for analysis or review, recommend one concrete architecture.
Include a module tree, responsibility placement, dependency and communication rules,
and incremental implementation steps. Present alternatives only after the
recommendation, with the conditions that would make an alternative preferable.

## Respect Existing Project Authority

Before defining a domain model or naming modules, inspect the project artifacts that
already govern language and architecture. These can include:

- Repository and directory instructions.
- Context maps and context documents.
- Glossaries and ubiquitous-language documents.
- Architecture documents and ADRs.
- Requirements, specifications, and design documents.
- Module manifests, public interfaces, tests, and code conventions.

Follow the declared priority of these artifacts and any rules scoped to a directory or
domain context. Preserve established terms, definitions, context boundaries, and
owners. Do not introduce a second name for an existing concept or silently change a
term's meaning.

Do not infer a DDD meaning from a filename alone. For example, a file named
`CONTEXT.md` does not necessarily define a bounded context.

Report conflicts between authoritative artifacts and explain their architecture
impact. Do not hide a conflict by selecting one source without explanation.

When the project has no relevant artifacts, derive the smallest useful language and
model from the request, code, tests, and examples. Mark facts that cannot be verified
as assumptions. Do not require a new glossary, context map, or ADR unless the user asks
for one or the change needs a durable decision record.

## Frame the System

Establish only the facts that can change the design:

- The system form, such as application, service, library, plugin, or data pipeline.
- The delivery mechanisms, such as UI, API, CLI, messages, or scheduled work.
- The databases, frameworks, operating systems, and external services involved.
- The rules, state, and invariants that carry domain complexity.
- The scope in which each model and language applies.
- The capabilities that need independent reuse, testing, deployment, or evolution.
- The observed variation points, team size, change rate, and maintenance budget.

Ask only questions whose answers would materially change the architecture. Continue
with explicit, reasonable assumptions for the rest.

## Start with a Usable Default

When there is no evidence of several independent domain models, start with this
single-context shape:

```text
foundation/
domain/
application/
adapters/
  inbound/
  outbound/
bootstrap/
```

Treat these names as responsibility labels, not required directory names. Select names
that match the project language and system form.

| Responsibility | Common name choices |
| --- | --- |
| Domain-neutral technical capabilities | `foundation`, `libs`, `platform`, `infrastructure` |
| Domain model and rules | `domain`, `model`, `business`, a domain capability name |
| Use cases and application flow | `application`, `use-cases`, `workflows`, `services` |
| External interaction boundary | `adapters`, `interfaces`, `ports`, `delivery` |
| Input adaptation | `inbound`, `ui`, `presentation`, `api`, `cli`, `consumers` |
| Output adaptation | `outbound`, `infrastructure`, `integrations`, `persistence`, `gateways` |
| Composition and startup | `bootstrap`, `composition-root`, `startup`, `app` |

State the local meaning when a name is ambiguous. For example, `infrastructure` can
mean a technical foundation or concrete external integration, `services` can mean use
cases or domain services, and `model` can mean a domain model or a data-transfer shape.
Do not use one name for several responsibilities without explicit subdivisions.

Keep an existing physical layout when it already expresses the required boundaries.
Create only the areas whose responsibilities exist. Do not create empty directories
for symmetry.

### Foundation

Place domain-neutral technical capabilities here. Examples include:

- General result and identifier types.
- Time, random-number, diagnostic, and validation abstractions.
- General collections, algorithms, and base protocol types.

Do not use Foundation as a catch-all. Keep domain rules, use-case flow, and vendor
integration out of it. If the project calls this area `infrastructure`, distinguish it
from outer database, network, and vendor adapters.

### Domain

Place language, model, and rules that describe the problem domain here. Examples
include:

- Entities and value objects.
- Domain state, transitions, rules, and invariants.
- Domain events, policies, calculations, and cohesive modules.
- Creation or persistence contracts when the domain language needs them.

Keep the Domain independent of UI, databases, network protocols, concrete frameworks,
and vendor SDKs.

### Application

Place behavior that drives the domain model toward a user or system goal here.
Examples include:

- Use cases, application commands, and workflows.
- Transaction boundaries, entry-point authorization, and cross-module coordination.
- The order of external calls and application input and output models.
- Ports for technical capabilities that a use case requires.

Let Application decide when to invoke domain behavior. Do not repeat domain rules or
move domain invariants into Application.

### Inbound Adapters

Place code that translates external input into application intent here. Examples
include:

- UI controllers and presentation adapters.
- HTTP, RPC, or GraphQL endpoints and CLI commands.
- Message consumers, scheduled jobs, and batch entry points.
- Framework lifecycle callbacks.

Call Application entry points. Do not mutate Domain internals directly.

### Outbound Adapters

Place concrete external integrations here. Examples include:

- Databases and file storage.
- Message publishers and HTTP or RPC clients.
- Search, cache, and object storage.
- Email, payment, identity, operating-system, framework, and vendor integrations.

Implement ports owned by Application or Domain. Let the side that needs a capability
own its contract. Put a port in Domain only when the capability is part of the domain
language; otherwise, let Application own it.

### Bootstrap

Place construction and startup work here. Examples include:

- Creating module instances.
- Binding ports, adapters, and configuration.
- Registering entry points and managing process startup and shutdown.

Allow Bootstrap to know the concrete types that it composes. Keep domain rules and
use-case flow out of it.

## Split Multiple Domain Contexts When Evidence Requires It

Use a context-first shape when the system contains different languages, models, rule
owners, or independent evolution boundaries:

```text
contexts/
  <context-name>/
    domain/
    application/
    adapters/
      inbound/
      outbound/
foundation/
bootstrap/
```

Allow each context to contain its own Domain, Application, and Adapters. Do not add a
bounded-context layer above an existing layer structure.

Integrate contexts through explicit public contracts. Translate models at the boundary
when their meanings differ. Add an anti-corruption layer when one model would otherwise
leak into another. Do not share an internal domain model merely to remove translation.

Allow similar words to have different precise meanings in different contexts. Do not
force a system-wide model when the language does not support one.

Do not assume that a bounded context is a module, service, directory, deployment unit,
or team. Introduce multiple contexts only when a real model boundary exists.

## Form a Minimal Orthogonal Basis

Treat the selected responsibility areas and core modules as the architecture's
functional pillars. Together, they must form a minimal orthogonal basis for the current
problem space:

- Give each pillar one indispensable responsibility.
- Give each pillar a distinct concept and reason to change.
- Do not let two pillars own the same rule, state, or decision.
- Compose complete behavior through small public contracts.
- Hide each pillar's internal state and implementation.
- Remove a pillar when its removal leaves no required capability without an owner.
- Merge or redraw pillars that remain interchangeable or always implement the same
  decision together.

Name modules, types, interfaces, events, use cases, tests, and documents with the
project's ubiquitous language. Divide modules by conceptual cohesion and reason to
change, not by file type, framework component, or organization chart.

Give every rule, state, invariant, and public contract one authoritative owner. Let
other modules consume that authority instead of reproducing it.

## Keep Dependencies and Communication Directed

### Source Dependencies

Use this default source-dependency direction:

```text
Inbound Adapters
       ↓
   Application
       ↓
     Domain
       ↓
   Foundation
```

Let Outbound Adapters depend on ports and contracts owned by Application or Domain. Do
not let Application or Domain depend on a concrete Outbound Adapter.

Allow same-area modules to depend on public interfaces in one direction. Keep the
complete dependency graph acyclic.

### Downward Communication

Use direct calls through public interfaces for stable downward requests:

- Let an Inbound Adapter invoke an Application use case.
- Let Application invoke Domain behavior.
- Let Application or Domain invoke a port that it owns.
- Return the result through the existing call stack.

### Upward Communication

Do not let a lower area import, hold, or invoke a concrete higher-area type. When a
lower area must initiate an upward notification, use an indirect mechanism:

- Use a callback for a small local response supplied by higher-level code.
- Use an observer for one-to-many notification in one process.
- Use a domain or application event for a fact that has already occurred.
- Use publish/subscribe or a message queue only when participants need time, process,
  or deployment independence.

Define a callback or observer contract in the lower area or in a neutral boundary. Let
the higher area register its implementation. Let the module that owns a fact define its
event, and let subscribers decide how to respond.

Treat a return value as the response to an existing downward call, not as an
independent upward dependency. Do not use a global event bus to hide unclear ownership
or control flow.

### Horizontal Communication

Choose one clear direction between peer modules, coordinate them in Application, or
use an event defined by the owner of a fact. At a context boundary, use an explicit
integration contract and model translation.

When the direction is unclear, identify who owns the rule, who owns the fact, and who
coordinates the use case. Do not create reciprocal references.

### Runtime Control Flow

Distinguish source dependency from runtime control flow. Application can call an
Outbound Adapter through a port at runtime while the adapter still depends on the
inner-owned port in source code.

Do not use a service locator, shared mutable state, dynamic lookup, or a global message
hub to bypass the dependency rules.

## Apply DDD Selectively

### Always Apply the Core Ideas

At every project size, keep the ubiquitous language, model-to-code alignment, rule and
state ownership, model scope, and conceptual module boundaries visible.

### Apply Strategic Design by Complexity

Consider subdomains, core and supporting capabilities, bounded contexts, context maps,
upstream and downstream relationships, anti-corruption layers, or a shared kernel only
when several models, languages, or ownership boundaries make them useful.

Map only the contexts needed for the current decision. Do not model the complete system
in advance.

### Apply Tactical Building Blocks by Problem

Use a building block only when its semantics fit:

| Building block | Use it when |
| --- | --- |
| Entity | An object has persistent identity and a lifecycle. |
| Value Object | A concept is defined by values, constraints, and value equality. |
| Domain Event | An occurred fact has domain meaning. |
| Domain Service | Domain behavior has no natural Entity or Value Object owner. |
| Aggregate | Several objects must enforce one consistency boundary. |
| Factory | Complex construction must always produce a valid result. |
| Repository | The Domain needs collection-like access to persisted objects. |
| Module | A set of concepts shares meaning and a reason to change. |

Do not create `entities/`, `services/`, `repositories/`, or similar directories merely
to display these patterns.

### Keep the Design Supple

Prefer a design that reveals intent and remains easy to change:

- Use names that express domain meaning.
- Expose behavior instead of internal data.
- Make side effects and state changes visible.
- Keep invariants close to their owner.
- Make composition predictable.
- Keep a common change from crossing unrelated modules.

### Let Order Evolve

Establish only the large-scale rules needed now. Change module boundaries when new
domain knowledge or implementation evidence shows that the current structure no longer
expresses the model, duplicates ownership, or obstructs common changes.

Do not preserve an obsolete plan only because it was defined early. Do not add a
speculative extension point to prepare for an unverified future.

## Isolate Experiments When Needed

Use an optional `experiments/`, `sandbox/`, or project-specific area when prototypes
need looser internal rules. Allow experiments to depend on production modules; never
let production depend on experiments. Before promotion, classify each accepted
responsibility, move or reimplement it under the correct owner, and add its tests.

## Workflow

1. Define the current goal, evidence, constraints, success conditions, and excluded
   scope.
2. Read the existing context, language, architecture, and decision artifacts.
3. Confirm the smallest domain language and model needed for the decision.
4. Identify the owners of rules, state, invariants, use cases, and external effects.
5. Select indispensable, non-overlapping functional pillars.
6. Choose a single-context or context-first topology and select project-appropriate
   names.
7. Recommend one concrete module tree and give representative contents for each area.
8. Trace source dependencies and downward, upward, and horizontal communication.
9. Add only the DDD building blocks and communication mechanisms that solve observed
   problems.
10. Check completeness, orthogonality, DRY, and extensibility.
11. Plan the smallest reversible migration slices and their validation.
12. Identify the glossary, context, ADR, architecture, test, and configuration artifacts
    that the change must reconcile.

## Review the Architecture

### Completeness

Treat the selected pillars as the span of the current problem space. Confirm that:

- Every required behavior, state, rule, invariant, and use case has an owner.
- Every input, output, and external effect has a responsible module.
- Every use case has a complete valid execution path.
- Relevant lifecycle, failure, transaction, concurrency, and persistence boundaries are
  covered.
- No unnamed `misc`, `common`, or hidden module is required to explain the system.
- The pillars can compose every required current capability.

An essential capability with no owner proves that the selected basis is incomplete.

### Orthogonality

Treat the selected pillars as a minimal independent basis. Confirm that:

- Each pillar owns an indispensable responsibility.
- Removing any pillar leaves a required capability without an owner.
- Each pillar has a distinct concept and reason to change.
- No pair of pillars overlaps in rule, state, or decision ownership.
- One change does not require several pillars to repeat the same decision.
- Pillars compose through contracts rather than shared internals.
- No pillar exists only to preserve symmetry.

Merge or redraw pillars that are interchangeable, always change together for the same
reason, or cannot state distinct responsibilities. Remove a pillar whose absence does
not affect a required capability.

### DRY

Treat DRY as single authority for knowledge and rules, not only as removal of similar
code. Confirm that:

- Each rule, invariant, state transition, contract, event, and protocol has one
  authoritative owner.
- Consumers refer to that authority in one direction instead of copying or redefining
  it.
- No pair of modules defines each other's required knowledge through a cycle.
- Derived text, tests, configuration, and code trace back to the same authority.
- A required generated copy identifies its source and can be regenerated from it.
- Similar syntax is not shared when its meaning or reason to change differs.

When the same knowledge has several independently editable copies, select one authority
and replace the others with one-way references or derived representations.

### Extensibility

Review extension paths against observed variation points. Confirm that:

- A new input mechanism normally adds an Inbound Adapter and composition wiring.
- A replacement database, external service, or vendor normally replaces an Outbound
  Adapter.
- A new use case mainly changes Application and its composition.
- A new domain capability fits an existing owner or a new orthogonal module.
- A new context does not require changes to unrelated context internals.
- Public contracts remain small and stable enough for the expected substitutions.
- Indirect upward communication can add a subscriber without changing the lower
  publisher.
- Extension points correspond to observed variation, not imagined requirements.
- Extension does not require a growing central switch, global registry, or shared
  mutable state.

Do not demand an interface, plugin point, or event at every location. Preserve
extension seams only for changes the current evidence supports.

## Scale the Structure

- For a small or early project, prefer one context and a compact physical structure.
  Keep ownership and dependency direction clear even when responsibilities share a
  directory. Do not add ports or events without a real boundary.
- For a medium system, separate Domain from Application, divide modules by domain
  capability, and add Adapters for external systems. Add ports at stable boundaries and
  events where independent evolution requires them.
- For a system with several models, prefer a context-first structure. Translate models
  at context boundaries and assign ownership for each integration contract.

Scale the number of mechanisms, not the meaning of the boundaries.

## Output

Return only the sections needed for the request, but keep the result concrete. A full
design should include:

1. Current constraints and explicit assumptions.
2. Existing context, terminology, and architecture sources consulted.
3. One recommended architecture profile and module tree.
4. The selected names and their exact local meanings.
5. The responsibility, necessity, and non-overlap boundary of each functional pillar.
6. The authority for each important rule, state, and contract.
7. Source dependencies and downward, upward, and horizontal communication.
8. Important domain terms, models, and context boundaries.
9. DDD building blocks selected or rejected, with reasons.
10. Missing responsibilities, overlaps, duplicate knowledge, or cycles found.
11. Supported extension paths and their change surface.
12. Incremental implementation steps and proportional validation.
13. Existing glossaries, context documents, ADRs, architecture documents, tests, or
    configuration that must change with the design.

If several solutions remain valid, recommend one first. State the conditions under
which another solution would become better.

## Avoid Overdesign

Do not introduce these mechanisms by default:

- One interface for every implementation or a global event bus.
- A Repository for every object or an Aggregate for every object group.
- A service or microservice for every module, or one global domain model.
- A mixed-responsibility `common` module or directories named only after DDD patterns.
- A complete context map or extension points before evidence requires them.
- A target architecture that requires a complete rewrite before validation.

Use the least structure that gives the current system a complete, orthogonal, and
extensible set of functional pillars, one authority for each rule, and one-way
references to that authority.
