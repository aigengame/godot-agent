---
status: accepted
---

# Provide a local HTTP execution service

> **Partial supersession (2026-09-06, [bADR-0028](0028-current-language-refactor-and-pre-1.0-retirement.md)):**
> bADR-0028 requires the HTTP path to consume the current Standard Schema contract after
> obsolete version selectors and execution bindings are removed. This is a coordinated
> nested-contract migration, not a new transport authority or a cosmetic /v1 rename.
> Protocol-neutral application ownership, process capability, loopback lifecycle, complete-run
> behavior, and consistent active-session inputs remain. The explicit incremental lifecycle
> work remains separately tracked in #745.

Issue #679 records a missing engine- and application-agnostic interface for local interactive
clients. These clients can use different local UI technologies, including a browser-based UI. The
CLI is an effective human and automation boundary, but its process-per-command and
filesystem-publication workflow is not a suitable coordination protocol for a running client. The
new interface must reuse the existing Application and Domain behavior without creating another
Model, Experiment, Runtime, artifact, identity, or refusal authority.

> **Follow-up decision:** accepted bADR-0027 extracts the shared Execution Open Host Service and its
> Published Language from transport-specific ownership. This bADR remains the authority for the
> current `/v1` protocol contract and local host. The follow-up changes integration ownership, not
> the Standard Schema authorities or the accepted HTTP behavior recorded here. It classifies
> `/v1/status`, like `/v1/shutdown`, as a local-host operation rather than a shared OHS capability
> while preserving both routes and response shapes.

## Decision

### Service and authority boundary

- The design separates two Interface responsibilities. The **Execution HTTP API** owns the
  application-agnostic execution protocol. The **local companion host** owns the in-process server
  lifecycle, loopback binding, its process capability, readiness state, status, and shutdown. The
  owning client remains responsible for executable discovery, child-process launch, and forced
  termination after its own timeout. This separation does not add a framework or substitution
  interface; it prevents local process control from becoming execution meaning.
- The service ships in the existing gda-balancing wheel and runs as a local foreground process. It
  is not a machine-wide daemon, remote multi-tenant service, or separately packaged application.
- One client application starts and owns each service process, its capability token, and its
  shutdown. Several components under that owner may create isolated Execution sessions. An
  unrelated application starts its own service process; it does not discover, join, or terminate
  another owner's process. The service adds no process registry, shared daemon, owner lease, or
  cross-process session discovery.
- The first increment exposes complete Experiment runs. A run uses one exact admitted Experiment
  revision, creates a new Runtime instance, and executes to its declared terminal boundary. A new
  revision can affect a later run; it cannot mutate an active run.
- Complete-run-only is an initial delivery boundary, not a permanent product restriction. Any
  concrete client need for Runtime steps, declared external input, active-run observation, or
  another interaction reopens the protocol immediately. The next increment adds the smallest
  authority-preserving capability needed; it does not wait for a second consumer or preserve the
  first boundary for its own sake.
- The HTTP boundary receives complete Model Source Package and Experiment Specification documents
  by value. It does not read caller-supplied filesystem paths or define JSON Patch, field-path
  mutation, or partial-update semantics. A future measured need may add content-addressed upload or
  verified artifact references without changing authored authority.

### Execution-session lifecycle

- One **Execution session** binds one exact Resolved Model for its lifetime. It can admit several
  immutable Experiment revisions against that Model. A Model Source change creates a new session
  because it can change the RIR, Scenario Input Contracts, Experiment binding, and reproduction
  graph. A session is host coordination, not a Standard Schema authority, Runtime instance, or HTTP
  transport session.
- Fixed-Model sessions are also an initial boundary. A concrete need to edit Model Source through a
  running client reopens the design for explicit Model revisions or session lineage. The service
  cannot silently rebind Experiment revisions or migrate active Runtime state.
- An **Experiment revision** is an immutable Execution-session binding to one complete admitted
  Experiment Specification and its exact content identity. Creating one submits a complete
  replacement specification. The service fully admits and identifies it before the revision becomes
  runnable in the session. Admission detaches the stored value from caller-owned containers.
  Refusal leaves every admitted revision unchanged.
- A run must name an exact revision. A session has no implicit current or active revision. Earlier
  revisions remain runnable until the session is deleted.
- A `session_id` is an opaque random handle scoped to one service process. A `revision_id` is the
  existing Experiment Specification content identity, not a new identity family. Re-admitting the
  same Experiment in the same session is idempotent.
- Revision state retains the admitted Experiment, its exact Resolved Model binding, and any required
  compatibility-resolution result. Reproduction artifacts bind the existing Kernel, LDB, Resolved
  Model, Experiment, Runtime-profile, and evaluator identities. Session handles and process
  credentials never enter Standard Schema artifact identity.
- Sessions and revisions are process-local and non-persistent. A client recreates them from complete
  authored documents after restart. Normal client shutdown deletes its sessions; process exit
  releases residual resources. The service adds no database, Repository, or recovery protocol.

### Foreground command lifecycle

- `serve` remains one registered Command descriptor in the existing descriptor registry. This
  decision narrowly amends bADR-0008, bADR-0011, and bADR-0021 with one
  `foreground-service` execution marking and a typed readiness result. It adds no second command
  list, schema path, dispatch path, or general service framework.
- The descriptor owns the command input, readiness model, usage and internal-error schemas, help,
  `--schema`, Surface-manifest projection, and conformance fixtures. The foreground marking selects
  an Interface-owned runner instead of the normal one-shot handler tail. It does not change Domain
  handlers or add a second semantic execution path.
- `gda-balancing serve --host 127.0.0.1 --port 0` starts the foreground runner. The operating system
  selects the port. After the local host accepts requests, the runner writes and flushes exactly one
  readiness JSON document to standard output. It then writes no more stdout content and waits for
  shutdown. Normal authenticated shutdown exits with code 0 and emits no terminal result.
- Argument validation failures before startup retain the existing descriptor-owned usage contract.
  A socket-binding or other internal startup failure leaves stdout empty, writes one sanitized
  `internal_error` envelope to standard error, and exits with code 4. After readiness, standard
  error becomes an operational log stream rather than a result channel. A later fault writes one
  sanitized `internal_error` envelope as its final log record and exits with code 4 while the
  readiness document remains on stdout. Post-readiness operation is the only exception to
  bADR-0008's empty-stdout and single-document stderr rules.
- `serve` is an ungrouped operational meta command. It is not an authority-oriented noun group,
  standalone Runtime surface, or Experiment command. Experiment remains the execution authority
  boundary.

### Local host and process security
- The service accepts only loopback bindings and refuses wildcard or external-interface addresses.
  Startup creates one high-entropy process capability token and returns it only in the readiness
  record. Every `/v1/*` request requires that token as an HTTP Bearer credential.
- The credential grants access to the local process only. It is not a user identity, Standard
  Schema authority, or Execution-session identity. The first increment adds no CORS, remote access,
  loopback TLS, accounts, roles, token refresh, or persistent credential storage.
- A later local browser-based client can reuse the same Execution HTTP API. If direct browser access
  demonstrates a need for an origin rule or local proxy, that change belongs to the Interface and
  local host. It cannot change Application or Domain semantics. This decision does not prebuild
  browser launch, CORS, proxy, or credential-distribution behavior.

### Versioned HTTP protocol

- The application-agnostic Execution HTTP API contains exactly:
  - `POST /v1/execution-sessions`;
  - `POST /v1/execution-sessions/{session_id}/experiment-revisions`;
  - `POST /v1/execution-sessions/{session_id}/runs`;
  - `DELETE /v1/execution-sessions/{session_id}`.
- The local companion host adds `GET /v1/status` and `POST /v1/shutdown`. They are versioned with the
  transport, but they are not Experiment execution operations. A later local host is not required to
  expose the same operational endpoints.
- Session creation receives a complete Model Source Package and initial Experiment Specification.
  A run names one exact revision identifier. The first protocol has no session/revision listing,
  implicit revision, partial update, artifact query, progress, cancellation, or streaming endpoint.
- `/v1` is the HTTP protocol major, not a Standard Schema or toolkit version. Readiness and status
  report the protocol major and toolkit version. Request and response schemas are closed. A breaking
  protocol change uses a new major path. Bodyless routes reject non-empty bodies. Unknown endpoints,
  unsupported methods, and undeclared trailing-slash variants use the same closed service-error
  envelope as other protocol failures. The first routes declare no query parameters and reject any
  non-empty query input.
- The Execution Service Language models are the single executable source for shared OHS shapes. The
  local companion host owns the status and shutdown models. bADR-0026, bADR-0027, and
  `docs/ARCHITECTURE.md` describe meaning and boundaries without copying every field.
  The existing Command-descriptor `--schema` convention describes the `serve` command and readiness
  result only; the first protocol adds no `/v1/schema`, OpenAPI surface, schema registry, schema
  identity, client generator, or general negotiation framework.
- This schema-delivery choice is an initial boundary, not a restriction on protocol evolution. A
  concrete independent-repository client, offline code-generation need, or dynamic-discovery need
  immediately reopens it. Any later schema bundle or discovery surface must be derived from the
  same executable models rather than becoming a second contract.
- A run is one synchronous HTTP operation. The response waits for complete execution and returns
  the existing success, verdict, or refusal result. The service adds no background job, durable
  task queue, status polling, progress stream, cancellation protocol, or result Repository. A
  measured need for long-run progress, cancellation, or reconnect recovery must reopen this
  boundary and add the smallest asynchronous Run resource required.
- Each session serializes revision admission, runs, and deletion in request-admission order.
  Requests for separate sessions can arrive and wait concurrently without sharing state or
  identities. The first service executes at most one CPU-bound admission or run operation at a
  time. This is concurrent submission with process-wide serial execution, not CPU parallelism. A
  measured queue-latency problem may justify a bounded multiprocess executor without changing
  per-session ordering or exact-revision selection.

### Outcomes and execution reuse

- HTTP status describes transport and service-protocol handling, not gda-balancing meaning. A
  well-formed request that reaches an Application use case returns HTTP 200 with exactly one
  `success`, `verdict`, or `refusal` outcome. Non-2xx status is reserved for malformed protocol,
  failed authentication, unknown service resources, unsupported methods, request limits, internal
  faults, or shutdown.
- The HTTP adapter projects existing Application and Domain results. It does not copy diagnostic
  catalogs, rewrite refusals, or classify closed Operation outcomes as failures. It owns one small,
  closed service-error schema for HTTP-protocol failures and does not reuse the CLI-only
  usage/internal envelope.
- One CLI-independent Application use case coordinates Domain admission, complete Experiment
  execution, and Domain construction of existing artifact members. The CLI adapter adds
  invocation-key handling, atomic filesystem publication, recovery, and the Artifact-set receipt.
  The HTTP adapter instead returns the complete artifact set and content identities inline without
  a temporary output directory.
- Experiment admission has one value-based Domain semantic core that accepts the complete verified
  Model artifact set, including the Build receipt, Package Lock, Resolved Model, and RIR. The CLI
  path locates and authenticates that set from the committed artifact store before calling the
  core. An Execution session compiles and verifies the same set in memory and passes it directly.
  Under bADR-0013, the Build receipt records publication-independent build provenance; the HTTP
  path does not synthesize an Artifact-set receipt. File and JSON-value inputs share canonical
  admission; the service creates no temporary store, HTTP-only Model format, or second Experiment
  checker.
- Success and verdict responses contain the complete existing artifact set. Runtime refusal retains
  terminal-audit evidence; other refusal stages retain the existing refusal report. The service
  defines no application-specific endpoint, gameplay result, simplified artifact, or intermediate
  case schema. A measured response-size problem may justify later retrieval or streaming design.

### Host implementation

- `interfaces/cli/main` and the existing dispatch path remain the process-level composition and
  command-registry owner. `interfaces/cli/serve` binds the operational descriptor, integrates the
  foreground runner, assembles the server components, emits the readiness record on standard
  output, and maps operational logs to standard error.
- `interfaces/http/api_v1` owns the four Execution OHS routes, JSON transport,
  and HTTP status mapping. `interfaces/http/local_host` owns the in-process ASGI server, loopback
  binding, process-capability authentication, server lifecycle, the status and shutdown routes, and
  the typed readiness state consumed by `interfaces/cli/serve`. These names state responsibility
  boundaries; they do not require an abstract interface or plugin mechanism. None of these modules
  owns Standard Schema meaning.
- `application/execution_sessions` owns ephemeral session/revision coordination, idempotent
  admission order, per-session ordering, and the process-wide execution gate without knowing HTTP
  or CLI. `application/experiment_execution` coordinates the publication-independent use-case
  order. The existing CLI flow calls that use case before filesystem publication and recovery.
- Session creation uses the existing value-based Model admission and compilation behavior. The
  verified in-memory Model artifact aggregation is a host value over existing artifacts, not a new
  authority or identity.
- Domain owns Model and Experiment admission, Runtime execution semantics, artifact-content
  construction, Evidence, identity, and refusal policy.
  Infrastructure receives only demonstrated domain-neutral mechanisms. This work adds no generic
  Repository, port hierarchy, dependency-injection container, service locator, or event bus.
- The HTTP Interface uses Starlette to implement the four execution routes, two local-host routes,
  middleware, JSON responses, and exception mapping. The local host owns readiness, status, and
  shutdown directly, so ASGI lifespan handling is disabled. Uvicorn provides the single-worker ASGI
  server and graceful lifecycle. Existing Pydantic models define closed request and response
  schemas with unknown fields refused. Reload, WebSockets, proxy-header trust, CORS, and default
  access logging are disabled.
- Python's standard-library development HTTP server is not used. FastAPI, automatic OpenAPI
  publication, Gunicorn, worker management, an HTTP client dependency, and a general service
  framework are also outside the first increment. Starlette and Uvicorn are Interface
  implementation dependencies, not protocol or Domain authorities.
- The HTTP Interface caps aggregate request bytes before JSON parsing. Session creation derives its
  cap from two admitted `language_bundle.resources.max_source_bytes` allowances plus a small fixed
  protocol-envelope allowance. Revision creation uses one source allowance plus that envelope.
  Small closed schemas bound other request bodies. Domain still applies the exact per-document
  limits and refusal laws.
- The first increment adds no configurable quota system, rate limiter, generic resource-policy
  framework, session-count limit, revision-count limit, or revision eviction. Explicit deletion,
  process lifetime, and measured use govern the initial service.

### Failure and shutdown behavior

- A disconnected request or crashed process produces no durable service result. A client must not
  infer success. It may explicitly restart the service, recreate a session from complete authored
  documents, and rerun the exact revision. The service does not automatically replay an ambiguous
  in-flight request or add a recovery log, retry queue, or circuit breaker.
- The authenticated shutdown endpoint closes local request admission before it returns an
  acknowledgement. A later request that still reaches the host receives the closed
  `service_shutting_down` response. Work that already passed admission can finish before the process
  exits. The owning client may terminate the child process after its own graceful-shutdown timeout.
  Non-persistent service state cannot be partially published by forced process termination.

The protocol is intentionally small but not frozen at this feature set. Its stable obligations are
authority preservation, exact identity, explicit selection, deterministic ordering, typed outcomes,
and versioned transport. New proven interactions may extend the protocol without preserving an
obsolete first-version convenience boundary.

## Considered options

- Pre-generated application-specific cases were rejected as a live protocol because they duplicate
  data shapes and cannot admit new Experiment revisions while a client runs.
- A process-per-run CLI adapter was rejected because it repeats bootstrap and file publication and
  does not provide session/revision coordination.
- A long-lived standard-input protocol was rejected for multiple local clients because process
  ownership, multiplexing, discovery, and isolation would become application-specific.
- A remote or machine-wide HTTP service was rejected because all identified consumers run locally
  and no deployment, identity, tenancy, or remote-security requirement supports it.
- A speculative step API, background job system, worker pool, persistence layer, and generic service
  framework were rejected until a demonstrated interaction requires them.

## Consequences

- The wheel gains Starlette and Uvicorn runtime dependencies and an operational `serve` command.
- Local clients with different UI technologies can build on one versioned engine- and
  application-agnostic execution protocol. The first host directly supports non-browser local
  clients; browser launch or origin adaptation remains evidence-driven Interface work.
- Consumer-specific process discovery, UI, content projection, source location, and distribution
  remain outside this decision.
- This record authorizes the local service without altering Runtime or Experiment semantic
  authority.

## Validation

- Prove that `serve` remains one descriptor in the existing registry and Surface manifest, and that
  its `--schema` result, readiness result, help, usage failures, and internal failures all derive
  from that descriptor. Prove readiness flush, stdout silence after readiness, normal shutdown,
  and the documented pre-readiness and post-readiness error behavior.
- Prove source and wheel parity for `serve`, readiness, packaged authorities, and protocol schemas.
- Prove that `interfaces/http/api_v1` does not depend on the local-host implementation, that
  Application and Domain do not import Starlette or Uvicorn, and that the service imports no game,
  engine, playtest, or example module.
- Test authentication, loopback-only binding, request bounds, closed schemas, and service-error
  mapping without weakening Domain refusal behavior.
- Compare CLI publication and HTTP inline execution from the same admitted inputs. Assert identical
  semantic artifacts and content identities while retaining Interface-specific transport facts.
  Assert that the in-memory path retains the publication-independent Build receipt and does not
  synthesize an Artifact-set receipt.
- Test exact Model/session binding, idempotent Experiment admission, explicit revision selection,
  refusal atomicity, per-session ordering, cross-session isolation, disconnect behavior, deletion,
  and graceful/forced shutdown.
- Run the focused service and Application suites, the existing Model/Experiment/Runtime/Evidence
  suites, source/wheel checks, dependency-layer checks, type checks, and the complete test suite.
