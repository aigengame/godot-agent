---
status: proposed
---

# Publish the Execution Open Host Service through one Published Language

Issue #789 records the next integration boundary for gda-balancing. The existing local Execution
HTTP API already reuses Application and Domain behavior, preserves exact identities, and supports
several application-agnostic clients. Its integration contract still belongs to the HTTP adapter.
A future MCP adapter would therefore have to copy that contract or call the HTTP adapter. Either
choice would make a transport an accidental owner of execution meaning.

## Decision

### Execution Open Host Service

- gda-balancing publishes one **Execution Open Host Service**. It exposes a small set of
  application-agnostic execution capabilities to downstream contexts. The initial capabilities
  establish an Execution session, admit an Experiment revision, run an exact revision, and release
  the session.
- The OHS is a strategic integration boundary. It is not a tactical Domain Service, Python service
  class, public-network deployment, machine-wide daemon, or game-specific endpoint.
- The protocol-neutral Application service coordinates the OHS use cases and returns typed results
  or refusals. It does not know HTTP, MCP, Starlette, JSON-RPC, Godot, or a consumer product.
- Domain remains the sole owner of Model and Experiment admission, Runtime execution, Evidence,
  artifact construction, identities, and refusals. The OHS adds no parallel semantic path.

### Execution Service Language

- The OHS uses one **Execution Service Language** as its Published Language. This language contains
  only the integration concepts introduced by the OHS: explicit session handles, revision
  selection, service-response framing, shared OHS errors, and their contract schema.
- The Interface layer owns the executable OHS-specific contract. That owner is protocol-neutral
  and sits outside the HTTP and MCP adapters. The Application layer remains responsible for use-case
  coordination, and the Domain layer remains responsible for Standard Schema meaning.
- The initial contract is **Execution Service Language revision 1**. This is a compatibility label,
  not a Package Release coordinate, HTTP path major, MCP protocol revision, toolkit release, or
  Standard Schema version. A breaking integration change selects a new contract revision and an
  explicit adapter migration. Compatible additions do not create another language or schema owner.
- The Published Language does not become a Standard Schema authority. Kernel, LDB, Model,
  Experiment, Runtime, Evidence, and other accepted authorities continue to own their schemas,
  rules, semantics, identities, and refusals. The Execution Service Language references their
  exact normative contracts and versions. It does not copy their fields, emit a peer schema,
  reinterpret them, or expose an implementation-private Domain model.
- The OHS-specific integration shapes have one executable owner outside the HTTP and MCP adapters.
  JSON Schema, HTTP contract documentation, and MCP input or output schema for those shapes are
  derived projections. A projection is not a second authority.
- An integration schema refers to an authority-owned Standard Schema value instead of expanding a
  duplicate definition. The first implementation slice must prove that a changed authority-owned
  schema cannot leave a stale accepted copy in the Published Language.
- Human documentation defines lifecycle, identity, refusal, ordering, and evolution semantics that
  cannot be expressed by JSON Schema alone. It references the relevant bADR or specification rather
  than copying the normative algorithm or field inventory.

### Initial contract and `/v1` projection

Execution Service Language revision 1 contains four execution capabilities. The following table
maps the shared contract to the current Pydantic shapes and routes without copying their complete
schemas. Model Source Packages, Experiment Specifications, artifact members, and
`Schema2RefusalReport` remain references to their authority-owned contracts.

| Shared capability | Shared input and result | Current HTTP shape | Current route |
| --- | --- | --- | --- |
| `establish-session` | Input: one Model Source Package and initial Experiment Specification. Result: session handle, exact Resolved Model identity, and admitted revision identity, or an authority-owned admission refusal. | `CreateExecutionSessionRequest` to `ExecutionSessionCreatedResponse` or `RefusalResponse` | `POST /v1/execution-sessions` |
| `admit-experiment-revision` | Input: session handle and complete Experiment Specification. Result: revision identity and whether it was newly admitted, an admission refusal, or `unknown_execution_session`. | Path `session_id` plus `AdmitExperimentRevisionRequest` to `ExperimentRevisionAdmittedResponse`, `RefusalResponse`, or the shared OHS error | `POST /v1/execution-sessions/{session_id}/experiment-revisions` |
| `run-experiment-revision` | Input: session handle and exact revision identity. Result: authority-owned success, verdict, or refusal artifacts, `unknown_execution_session`, or `unknown_experiment_revision`. | Path `session_id` plus `RunExperimentRequest` to `RunSuccessResponse`, `RunVerdictResponse`, `RunRefusalResponse`, `unknown_execution_session`, or `unknown_experiment_revision` | `POST /v1/execution-sessions/{session_id}/runs` |
| `release-session` | Input: session handle. Result: released session handle or `unknown_execution_session`. | Path `session_id` and an empty body to `ExecutionSessionDeletedResponse` or the shared OHS error | `DELETE /v1/execution-sessions/{session_id}` |

`GET /v1/status` and `POST /v1/shutdown` are not OHS capabilities. They are local-companion-host
operations. The former projects `StatusResponse`; the latter projects `ShutdownResponse`. Their
paths and response bytes remain unchanged during contract extraction.

### Sibling Interface adapters

- Resource-oriented HTTP and MCP are sibling inbound Interface adapters. Both project the same OHS
  capabilities and Execution Service Language. Both call the same Application service directly
  when they run in the same process.
- The MCP adapter does not wrap or call the HTTP adapter. The HTTP adapter does not import MCP.
  Neither adapter owns Model, Experiment, Runtime, artifact, identity, outcome, or refusal meaning.
- Adapter-specific facts remain local. HTTP owns resource identifiers, methods, status codes,
  headers, media types, and HTTP error projection. MCP owns its protocol messages, tool and resource
  descriptions, capability metadata, and model-facing presentation. The local companion host owns
  process authentication and lifecycle.
- MCP tools are designed around complete agent tasks. They are not generated mechanically from
  HTTP routes. MCP resources can expose immutable contract or artifact representations when a
  demonstrated client need exists. MCP prompts are optional interaction aids and never own
  execution semantics.
- The selected MCP specification revision is pinned when implementation starts. It is an external
  protocol authority for MCP messages only. It cannot define local Domain meaning.

### Responsibility partition

| Owner | Owns | Current error or refusal mapping |
| --- | --- | --- |
| Execution Service Language | Capability names, OHS handles and selections, response framing, and shared OHS errors | `unknown_execution_session` and `unknown_experiment_revision` |
| Application | Session and revision state, admission order, execution order, and the conditions behind `unknown_execution_session` and `unknown_experiment_revision` | Raises typed conditions; owns no wire code or response envelope |
| Domain | Standard Schema admission, execution, artifacts, identities, outcomes, and refusals | `Schema2RefusalReport` and execution success, verdict, or refusal meaning |
| Resource-oriented HTTP adapter | Routes, methods, media types, request bounds, HTTP status, and HTTP error projection | `invalid_request`, `request_too_large`, `unsupported_media_type`, `unknown_endpoint`, `method_not_allowed`, and `internal_error` |
| MCP adapter | Tools, resources, optional prompts, MCP schemas, structured content, and MCP error projection | Maps shared results and errors to the selected MCP revision without HTTP codes |
| Local companion host | Process capability authentication, readiness, status, shutdown, request-admission closure, and process fault lifecycle | `authentication_required` and `service_shutting_down`; a fatal fault uses the HTTP adapter's sanitized `internal_error` projection before process exit when possible |

The current `ServiceErrorCode` union is a transport-local mixture of these categories. The first
extraction splits ownership without changing its accepted `/v1` spelling or status mapping. A
shared OHS error remains distinct from a Domain refusal and from an adapter parsing failure.

### Resource-oriented HTTP and REST evolution

- The existing `/v1` surface remains a Resource-oriented HTTP API. bADR-0026 continues to own its
  routes, loopback host, process capability, readiness, shutdown, request limits, and current wire
  behavior.
- Resource orientation is an initial architecture boundary, not a permanent restriction. A
  demonstrated consumer need can add applicable REST constraints, such as richer resource
  representations, links, cache semantics, or a complete REST architecture. A breaking change uses
  an explicit versioned decision and migration path.
- The product does not claim full REST conformance while required REST constraints remain absent.
  It does not add hypermedia, persistent Run resources, a generic Repository, background jobs, or
  other machinery only to obtain a REST label.
- The first Published-Language extraction preserves the accepted `/v1` wire contract. It can expose
  the existing contract from a new owner before a later decision changes any public resource or
  representation.

### Evolution boundary

- Current complete-run, fixed-Model, synchronous, process-local, and loopback boundaries remain
  changeable. A concrete need for Runtime input, stepping, observation, progress, cancellation,
  browser access, or another interaction reopens the smallest affected contract.
- A new capability must preserve the one-way authority flow:

  ```text
  requirements
    -> OHS and Published Language decision
    -> Standard Schema authorities plus the OHS integration contract
    -> derived executable schemas and conformance cases
    -> protocol-neutral Application service
    -> Resource-oriented HTTP and MCP Interface adapters
    -> parity and end-to-end evidence
    -> human acceptance
  ```

- The architecture does not prebuild a service locator, dependency-injection container, event bus,
  schema registry, generic service framework, or speculative extension point. A real substitution,
  discovery, or asynchronous interaction need must justify the smallest new seam.

## Theory and external references

- Eric Evans' [*Domain-Driven Design Reference*](https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf)
  (2015) motivates an Open Host Service when several downstream contexts need one coherent
  integration protocol. It motivates a Published Language as a documented interchange language
  instead of freezing an internal model. This bADR adopts those two mechanisms. It does not make
  the external terminology a local semantic authority.
- Roy Fielding's [REST dissertation chapter](https://www.ics.uci.edu/~fielding/pubs/dissertation/rest_arch_style.htm)
  (2000) defines REST through constraints that include stateless interaction, cache, a uniform
  interface, self-descriptive messages, and hypermedia. This bADR therefore describes the current
  HTTP surface as Resource-oriented and makes no full-REST claim.
- The official [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
  is research evidence for a stateless protocol core and explicit application handles. It is not a
  runtime dependency or a compatibility promise. The implementation gate must pin and recheck the
  then-selected MCP revision.

## Considered options

- **Keep the HTTP contract as the common service contract** was rejected. It makes HTTP status,
  routes, and transport models the hidden owner of a future MCP surface.
- **Implement MCP as an HTTP client** was rejected. It adds a second serialization and failure
  boundary and prevents in-process adapters from sharing one Application service directly.
- **Define independent HTTP and MCP schemas** was rejected. They can drift in identities, outcomes,
  refusals, and authority references.
- **Publish the internal Domain model** was rejected. It freezes implementation structure and lets
  integration needs change Domain ownership.
- **Adopt full REST immediately** was rejected. No current consumer requires the additional
  hypermedia, cache, or persistent resource machinery.
- **Extract one Published Language and use sibling adapters** was selected. It removes transport
  ownership without changing Standard Schema authority or current `/v1` behavior.

## Consequences

- The current HTTP Pydantic models will no longer be the permanent owner of shared OHS integration
  shapes. The first implementation slice moves only the shared contract and preserves the wire.
- A later HTTP or MCP schema projection must be generated from the one Published-Language owner and
  must refer to authority-owned Standard Schema contracts.
- HTTP and MCP can evolve their protocol presentation independently while retaining the same
  execution meaning.
- Existing playtests remain HTTP consumers. They gain no Kernel, LDB, artifact, or MCP awareness.
- bADR-0026 remains accepted for the current local host and `/v1` behavior. This decision refines
  only the shared integration ownership and future adapter topology.

## Validation and delivery gates

1. **Design acceptance**: reconcile this bADR, bADR-0026, `BALANCING-CONTEXT.md`,
   `docs/ARCHITECTURE.md`, and issue #789. A human accepts the boundary before implementation.
2. **Published-Language extraction**: move the OHS-specific contract to one protocol-neutral owner.
   Start from a before-change HTTP wire corpus and preserve `/v1` bytes, status behavior, identities,
   outcomes, refusals, ordering, and playtest use under Execution Service Language revision 1.
3. **Authority conformance**: prove that integration schemas reference authority-owned Standard
   Schema contracts and cannot retain a copied stale shape. Include positive, refusal, boundary,
   and mutation cases.
4. **HTTP adoption**: make the Resource-oriented HTTP adapter consume the shared contract. Retain
   bADR-0026 lifecycle, security, failure, and source/wheel evidence.
5. **MCP tracer**: implement one minimal end-to-end MCP path against the same Application service
   and Published Language. Compare its semantic artifacts, identities, outcomes, and refusals with
   equivalent CLI and HTTP use cases after transport facts are excluded.
6. **MCP completion**: add only the tools, resources, documentation, and operational behavior proven
   by the tracer and named consumer stories.
7. **Reopen on evidence**: consider deeper REST, asynchronous Runs, Runtime interaction, discovery,
   or schema delivery only when a concrete consumer exposes that gap.

While this bADR is Proposed, three load-bearing claims remain open: one language can serve HTTP and
MCP without copied Standard Schema contracts; extraction can preserve the accepted `/v1` wire
corpus; and MCP can call the Application service without an HTTP proxy or second semantic path.
Mutation and conformance tests, the before/after HTTP corpus, and the minimal MCP tracer close these
claims during the ordered delivery gates.

The decision is falsified if HTTP and MCP require different execution identities, outcomes,
refusals, or ordering, or if either adapter must copy Standard Schema semantics to work. Such
evidence reopens the Published-Language boundary instead of permitting an adapter-specific semantic
escape hatch.
