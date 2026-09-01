---
status: accepted
---

# Publish the Execution Open Host Service through one Published Language

Issue #789 records the next integration boundary for gda-balancing. The existing local Execution
HTTP API already reused Application and Domain behavior, preserved exact identities, and supported
several application-agnostic clients. Its integration contract still belonged to the HTTP adapter.
Leaving that contract transport-owned would have made HTTP an accidental owner of execution meaning
and forced any later adapter either to copy the contract or to call HTTP.

## Decision

### Execution Open Host Service

- gda-balancing publishes one **Execution Open Host Service**. It exposes a small set of
  application-agnostic execution capabilities to downstream contexts. The initial capabilities
  establish an Execution session, admit an Experiment revision, run an exact revision, and release
  the session.
- The OHS is a strategic integration boundary. It is not a tactical Domain Service, Python service
  class, public-network deployment, machine-wide daemon, or game-specific endpoint.
- The protocol-neutral Application service coordinates the OHS use cases and returns typed results
  or refusals. It does not know Interface protocols, frameworks, Godot, or a consumer product.
- Domain remains the sole owner of Model and Experiment admission, Runtime execution, Evidence,
  artifact construction, identities, and refusals. The OHS adds no parallel semantic path.

### Execution Service Language

- The OHS uses one **Execution Service Language** as its Published Language. This language contains
  only the integration concepts introduced by the OHS: explicit session handles, revision
  selection, service-response framing, shared OHS errors, and their contract schema.
- The Interface layer owns the executable OHS-specific contract. That owner is protocol-neutral
  and sits outside transport adapters. The Application layer remains responsible for use-case
  coordination, and the Domain layer remains responsible for Standard Schema meaning.
- The initial contract is **Execution Service Language revision 1**. This is a compatibility label,
  not a Package Release coordinate, HTTP path major, toolkit release, transport-protocol revision,
  or Standard Schema version. A breaking integration change selects a new contract revision and an
  explicit adapter migration. Compatible additions do not create another language or schema owner.
- The Published Language does not become a Standard Schema authority. Kernel, LDB, Model,
  Experiment, Runtime, Evidence, and other accepted authorities continue to own their schemas,
  rules, semantics, identities, and refusals. The Execution Service Language carries their values
  opaquely, and the Domain applies the applicable authority-owned contracts. The language does not
  copy their fields, emit a peer schema, reinterpret them, or expose an implementation-private
  Domain model.
- The OHS-specific integration shapes have one executable owner outside transport adapters. JSON
  Schema and HTTP contract documentation for those shapes are derived projections. Any future
  adapter projection must derive from the same owner. A projection is not a second authority.
- Revision 1 closes only the OHS envelopes. Nested Model Source, Experiment, and artifact values
  remain opaque to its Pydantic schemas. Domain validates or produces these values under the
  applicable authority-owned contracts, so the Published Language cannot retain a stale accepted
  copy of their internal shape.
- Revision 1 does not publish a combined Standard Schema. If a later consumer requires one, its
  projection must use resolvable references to authority-owned Standard Schema values instead of
  expanding duplicate definitions. That need must not introduce a peer schema authority or an
  otherwise unnecessary schema registry.
- Human documentation defines lifecycle, identity, refusal, ordering, and evolution semantics that
  cannot be expressed by JSON Schema alone. It references the relevant bADR or specification rather
  than copying the normative algorithm or field inventory.

### Initial contract and `/v1` projection

Execution Service Language revision 1 contains four execution capabilities. The following table
maps the shared contract to the current Pydantic shapes and routes without copying their complete
schemas. Model Source Packages, Experiment Specifications, and artifact members remain opaque
values governed by their authority-owned contracts. `Schema2RefusalReport` remains the reused
authority-owned refusal contract.

| Shared capability | Shared input and result | Current HTTP shape | Current route |
| --- | --- | --- | --- |
| `establish-session` | Input: one Model Source Package and initial Experiment Specification. Result: session handle, exact Resolved Model identity, and admitted revision identity, or an authority-owned admission refusal. | `EstablishExecutionSessionRequest` to `ExecutionSessionEstablishedResponse` or `RefusalResponse` | `POST /v1/execution-sessions` |
| `admit-experiment-revision` | Input: session handle and complete Experiment Specification. Result: revision identity and whether it was newly admitted, an admission refusal, or `unknown_execution_session`. | Path `session_id` and body `experiment_specification` project to `AdmitExperimentRevisionRequest`, then to `ExperimentRevisionAdmittedResponse`, `RefusalResponse`, or the shared OHS error | `POST /v1/execution-sessions/{session_id}/experiment-revisions` |
| `run-experiment-revision` | Input: session handle and exact revision identity. Result: authority-owned success, verdict, or refusal artifacts, `unknown_execution_session`, or `unknown_experiment_revision`. | Path `session_id` and body `revision_id` project to `RunExperimentRequest`, then to `RunSuccessResponse`, `RunVerdictResponse`, `RunRefusalResponse`, `unknown_execution_session`, or `unknown_experiment_revision` | `POST /v1/execution-sessions/{session_id}/runs` |
| `release-session` | Input: session handle. Result: released session handle or `unknown_execution_session`. | Path `session_id` and an empty body project to `ReleaseExecutionSessionRequest`, then to `ExecutionSessionReleasedResponse` or the shared OHS error | `DELETE /v1/execution-sessions/{session_id}` |

`GET /v1/status` and `POST /v1/shutdown` are not OHS capabilities. They are local-companion-host
operations. The former projects `StatusResponse`; the latter projects `ShutdownResponse`. Their
paths and response contracts remain unchanged during contract extraction.

### Current adapter and deferred extensions

- Resource-oriented HTTP is the current inbound Interface adapter. It projects the OHS capabilities
  and Execution Service Language and calls the Application service directly.
- Adapter-specific facts remain local. HTTP owns resource identifiers, methods, status codes,
  headers, media types, and HTTP error projection. The local companion host owns process
  authentication and lifecycle. Neither owns Model, Experiment, Runtime, artifact, identity,
  outcome, or refusal meaning.
- An MCP adapter is deferred. The current delivery adds no MCP module, placeholder interface, tool,
  resource, prompt, schema projection, compatibility layer, protocol dependency, specification pin,
  tracer, or parity gate. A named agent consumer, a concrete tool workflow, or a separately approved
  MCP delivery issue can reopen that work.
- If MCP is later selected, it is a peer Interface adapter that uses the Execution Service Language
  and calls Application directly. It does not wrap HTTP or create a second semantic path. The future
  delivery pins the then-current MCP specification and designs only the behavior justified by its
  concrete consumer. This deferral is not a permanent prohibition.

### Responsibility partition

| Owner | Owns | Current error or refusal mapping |
| --- | --- | --- |
| Execution Service Language | Capability names, OHS handles and selections, response framing, and shared OHS errors | `unknown_execution_session` and `unknown_experiment_revision` |
| Application | Session and revision state, admission order, execution order, and the conditions behind `unknown_execution_session` and `unknown_experiment_revision` | Raises typed conditions; owns no transport code or response envelope |
| Domain | Standard Schema admission, execution, artifacts, identities, outcomes, and refusals | `Schema2RefusalReport` and execution success, verdict, or refusal meaning |
| Resource-oriented HTTP adapter | Routes, methods, media types, request bounds, HTTP status, and HTTP error projection | `invalid_request`, `request_too_large`, `unsupported_media_type`, `unknown_endpoint`, `method_not_allowed`, and `internal_error` |
| Local companion host | Process capability authentication, readiness, status, shutdown, request-admission closure, and process fault lifecycle | `authentication_required` and `service_shutting_down`; a fatal fault uses the HTTP adapter's sanitized `internal_error` projection before process exit when possible |

The extraction separates the shared `ExecutionServiceErrorCode` values from transport-local and
local-host errors without changing their accepted `/v1` spelling or status mapping. A shared OHS
error remains distinct from a Domain refusal and from an adapter parsing failure.

### Resource-oriented HTTP and REST evolution

- The existing `/v1` surface remains a Resource-oriented HTTP API. bADR-0026 continues to own its
  routes, loopback host, process capability, readiness, shutdown, request limits, and current
  protocol behavior.
- Resource orientation is an initial architecture boundary, not a permanent restriction. A
  demonstrated consumer need can add applicable REST constraints, such as richer resource
  representations, links, cache semantics, or a complete REST architecture. A breaking change uses
  an explicit versioned decision and migration path.
- The product does not claim full REST conformance while required REST constraints remain absent.
  It does not add hypermedia, persistent Run resources, a generic Repository, background jobs, or
  other machinery only to obtain a REST label.
- The Published-Language extraction preserves the accepted `/v1` protocol behavior: routes,
  methods, normative headers, statuses, closed decoded JSON shapes and values, identities, error
  codes, ordering, authentication, and lifecycle. It does not freeze JSON key order, whitespace, or
  other serializer details unless an authority or demonstrated consumer requires byte stability.

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
    -> Resource-oriented HTTP Interface adapter
    -> semantic parity and end-to-end evidence
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

## Considered options

- **Keep the HTTP contract as the common service contract** was rejected. It makes HTTP status,
  routes, and transport models the hidden owner of any later adapter.
- **Publish the internal Domain model** was rejected. It freezes implementation structure and lets
  integration needs change Domain ownership.
- **Adopt full REST immediately** was rejected. No current consumer requires the additional
  hypermedia, cache, or persistent resource machinery.
- **Extract one Published Language and make the current HTTP adapter consume it** was selected. It
  removes transport ownership without changing Standard Schema authority or current `/v1`
  behavior. Additional adapters remain deferred until a concrete consumer requires one.

## Consequences

- The HTTP adapter no longer owns the shared OHS integration shapes. The implementation moves only
  the shared contract and preserves semantic HTTP behavior.
- The HTTP projection and any later adapter projection must derive from the one Published-Language
  owner. Revision 1 keeps nested Standard Schema values opaque. Domain validates or produces these
  values under the applicable authority-owned contracts. A later combined schema must use
  resolvable references if a demonstrated consumer requires that projection.
- Existing playtests remain HTTP consumers. They gain no Kernel, LDB, or artifact awareness.
- bADR-0026 remains accepted for the current local host and `/v1` behavior. This decision refines
  only the shared integration ownership and the rule for future adapters.

## Validation and delivery evidence

1. **Design acceptance**: the maintainer accepted the reconciled boundary before implementation.
   This bADR, bADR-0026, `BALANCING-CONTEXT.md`, `docs/ARCHITECTURE.md`, and issue #789 record the
   same decision.
2. **Published-Language extraction**: `interfaces/execution_service_language.py` owns the
   OHS-specific contract. HTTP contract tests preserve `/v1` routes, methods, normative headers,
   statuses, closed decoded JSON shapes and values, identities, error codes, ordering,
   authentication, lifecycle, and playtest use under revision 1.
3. **Authority conformance**: contract tests prove that the integration schemas close OHS
   envelopes, leave nested authority-owned values opaque and unchanged, and let Domain validate or
   produce those values under the applicable authority-owned contracts. Positive, refusal,
   boundary, and mutation cases cover the current contract. A later combined schema must use
   resolvable authority-owned references if a demonstrated consumer requires it.
4. **HTTP adoption**: the Resource-oriented HTTP adapter consumes the shared contract and retains
   bADR-0026 lifecycle, security, failure, and source/wheel evidence. The local companion host owns
   status and shutdown outside the four OHS capabilities.
5. **Accepted scope**: the implementation adds no MCP-specific production artifact or gate. Deeper
   REST, asynchronous Runs, Runtime interaction, discovery, schema delivery, or another transport
   adapter requires a concrete consumer and a separate approved delivery scope.

The implementation closes the two load-bearing claims: the Published Language owns the OHS-specific
contract without copying Standard Schema contracts, and extraction preserves the accepted semantic
`/v1` protocol behavior. Published-Language, HTTP, authority, mutation, CLI-parity, and wheel tests
provide the evidence. The reserved future-adapter seam is not implementation evidence.

The decision is falsified if the HTTP adapter must copy Standard Schema semantics to consume the
Published Language or if extraction changes the accepted `/v1` protocol behavior. Such evidence
reopens the Published-Language boundary instead of permitting a transport-specific semantic escape
hatch. A later adapter must define and validate its own delivery evidence when its concrete need is
approved.
