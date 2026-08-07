---
name: design-domain-modular-architecture
description: Design and review framework-independent, domain-centered modular software architectures with domain models as the basis for boundaries, ownership, dependencies, and evolution. Use when no project- or framework-specific modular topology governs the primary structure, or to reason about domain boundaries within an existing topology while structuring a new system, modularizing a codebase, reviewing coupling, or planning an incremental architecture change.
---

# Design Domain Modular Architecture

## Goal

Design the smallest usable architecture that gives the current system complete and
distinct responsibilities, one authority for each rule, one-way dependencies, and
clear extension paths.

Use Domain-Driven Design (DDD) as the theoretical basis for judging module boundaries
and evolution. Do not treat it as a set of patterns that every project must implement.
Introduce a Bounded Context, Aggregate, Repository, Domain Service, or other DDD
building block only when it solves an observed problem.

For design work, recommend one concrete architecture. Include a module tree,
responsibility placement, dependency and communication rules, and incremental
implementation steps. Present alternatives only after the recommendation, with the
conditions that would make an alternative preferable.

For analysis or review-only work, describe the observed architecture and report
verified findings. Recommend a change only when evidence shows that the current design
does not meet the applicable criteria.

Use the default topology in this skill only when no project- or framework-specific
modular topology already governs the system. When one exists, preserve its module names
and dependency rules. Use the DDD guidance here to judge language, ownership, and
evolution within those boundaries.

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

Use the Ubiquitous Language of the applicable Bounded Context to name modules, types,
interfaces, events, use cases, tests, and documents. When no Bounded Context is defined,
use the established project and domain terms.

Do not infer a DDD meaning from a filename alone. For example, a file named
`CONTEXT.md` does not necessarily define a Bounded Context.

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
| External interaction boundary | `adapters`, `interfaces`, `delivery` |
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

Divide modules by conceptual cohesion and reason to change, not by file type, framework
component, or organization chart.

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

## Split Bounded Contexts When Evidence Requires It

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

Allow each Bounded Context to contain its applicable Domain, Application, and Adapters.
Do not treat a Bounded Context as another dependency layer. When several models exist,
organize the applicable layers inside each context.

Integrate contexts through explicit public contracts. Translate models at the boundary
when their meanings differ. Add an Anti-Corruption Layer when one model would otherwise
leak into another. Do not share an internal domain model merely to remove translation.

Allow similar words to have different precise meanings in different contexts. Do not
force a system-wide model when the language does not support one.

Do not assume that a Bounded Context is a module, service, directory, deployment unit,
or team. Introduce multiple contexts only when a real model boundary exists.

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

At every project size, keep the Ubiquitous Language, alignment between the domain model
and implementation, rule and state ownership, model scope, and conceptual module
boundaries visible.

### Apply Strategic Design to Current Decisions

Identify the Core Domain as the cohesive part of the model that expresses the system's
main domain-specific value. Classify a necessary custom capability that is not the main
differentiator as a Supporting Subdomain. Classify a common capability that gives no
domain-specific advantage as a Generic Subdomain. Apply these distinctions when they
change modeling effort, ownership, or sourcing, even within one Bounded Context.

Consider Bounded Contexts, a Context Map, upstream and downstream relationships, an
Anti-Corruption Layer, or a Shared Kernel only when several models, languages, or
ownership boundaries make them useful.

Map only the contexts needed for the current decision. Do not model the complete system
in advance.

### Apply Tactical Building Blocks by Problem

Use a building block only when its semantics fit:

| Building block | Use it when |
| --- | --- |
| Entity | An object is distinguished by identity rather than attributes, and its identity continues through its lifecycle; storage persistence is not required. |
| Value Object | A concept is defined by values, constraints, and value equality. |
| Domain Event | An occurred fact has domain meaning. |
| Domain Service | Domain behavior has no natural Entity or Value Object owner. |
| Aggregate | Related Entities and Value Objects need one consistency and transaction boundary, with external access controlled by an Aggregate Root. |
| Factory | Complex construction must always produce a valid result. |
| Repository | An Aggregate Root needs collection-like access expressed in the Ubiquitous Language. |
| Module | A set of concepts shares meaning and a reason to change. |

Do not create `entities/`, `services/`, `repositories/`, or similar directories merely
to display these patterns.

### Apply Supple Design

Prefer a design that reveals intent and remains easy to change:

- Use names that express domain meaning.
- Expose behavior instead of internal data.
- Make side effects and state changes visible.
- Keep invariants close to their owner.
- Make composition predictable.
- Keep a common change from crossing unrelated modules.

### Apply Evolving Order

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

1. Define the current goal, evidence, constraints, success conditions, and excluded scope.
2. Read the existing context, language, architecture, and decision artifacts.
3. Confirm the needed domain model and identify the owners of rules, state, invariants,
   use cases, and external effects.
4. Choose module boundaries, topology, and project-appropriate names.
5. For design work, recommend one concrete module tree and give representative contents
   for each area. For review-only work, record the observed tree and verified findings.
6. Trace source dependencies and downward, upward, and horizontal communication.
7. Add only the DDD building blocks and communication mechanisms that solve observed
   problems.
8. Review completeness, orthogonality, DRY, and extensibility.
9. For design work or accepted changes, plan reversible migration slices, validation,
   and reconciliation of affected project artifacts. Otherwise, report validation and
   stop.

## Review the Architecture

### Completeness

Confirm that the selected responsibilities, modules, and contexts cover the current
problem space:

- Every required behavior, state, rule, invariant, and use case has an owner.
- Every input, output, and external effect has a responsible module.
- Every use case has a complete valid execution path.
- Relevant lifecycle, failure, transaction, concurrency, and persistence boundaries are
  covered.
- No unnamed `misc`, `common`, or hidden module is required to explain the system.
- The design can compose every required current capability.

An essential capability with no owner proves that the design is incomplete.

### Orthogonality

Use **orthogonal basis** as a system metaphor for the modules or cohesive module groups
that own the required capabilities. Together, they must cover the current capability
set, while each owner remains necessary and non-overlapping. Confirm that:

- Each capability owner has an indispensable responsibility.
- Removing any owner leaves a required capability without an owner.
- Each owner has a distinct concept and reason to change.
- No pair of owners overlaps in rule, state, or decision ownership.
- One change does not require several owners to repeat the same decision.
- Owners compose through contracts rather than shared internals.
- No owner exists only to preserve symmetry.

Merge or redraw modules or groups that are interchangeable, always change together for
the same reason, or cannot state distinct responsibilities. Remove one whose absence
does not affect a required capability.

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

## Output

Return only the sections needed for the request, but keep the result concrete. Include:

1. Current constraints, assumptions, and the authority sources consulted.
2. A recommended architecture profile, module tree, and exact local names for design
   work, or the observed architecture and verified findings for review-only work.
3. Responsibility placement, capability ownership, and authoritative sources for shared
   rules and knowledge.
4. Source dependencies and downward, upward, and horizontal communication.
5. Important domain terms, model boundaries, and DDD choices.
6. Findings from the completeness, orthogonality, DRY, and extensibility checks.
7. Incremental implementation, validation, and affected project artifacts when changes
   are proposed; otherwise, validation and the retained architecture.

For design work, if several solutions remain valid, recommend one first. State the
conditions under which another solution would become better.

## Avoid Overdesign

Do not introduce these mechanisms by default:

- One interface for every implementation or a global event bus.
- A Repository for every object or an Aggregate for every object group.
- A service or microservice for every module, or one global domain model.
- A mixed-responsibility `common` module or directories named only after DDD patterns.
- A complete context map or extension points before evidence requires them.
- A target architecture that requires a complete rewrite before validation.
