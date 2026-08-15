---
status: proposed
---

# Provide a local HTTP execution service

Issue #679 records a missing engine- and application-agnostic interface for local interactive
clients. These clients can use different local UI technologies, including a browser-based UI. The
CLI is an effective human and automation boundary, but its process-per-command and
filesystem-publication workflow is not a suitable coordination protocol for a running client. The
new interface must reuse the existing Application and Domain behavior without creating another
Model, Experiment, Runtime, artifact, identity, or refusal authority.

## Decision

### Service and authority boundary

- The design separates two Interface responsibilities. The **Execution HTTP API** owns the
  application-neutral execution protocol. The **local companion host** owns process launch,
  loopback binding, its process capability, readiness, and shutdown. This separation does not add
  a framework or substitution interface; it prevents local process control from becoming execution
  meaning.
- The service ships in the existing gda-balancing wheel and runs as a local foreground process. It
  is not a machine-wide daemon, remote multi-tenant service, or separately packaged application.
- One client application owns each service process, its capability token, and its shutdown. Several
  components under that owner may create isolated Execution sessions. An unrelated application
  starts its own service process; it does not discover, join, or terminate another owner's process.
  The service adds no process registry, shared daemon, owner lease, or cross-process session
  discovery.
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
- Creating an Experiment revision submits one complete replacement Experiment Specification. The
  service fully admits and identifies it before publication in the session. Refusal leaves every
  admitted revision unchanged.
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

### Local host and process security

- `gda-balancing serve --host 127.0.0.1 --port 0` starts the foreground process. The operating
  system selects the port. After it can accept requests, the process writes one structured JSON
  readiness record to standard output. Operational logs use standard error.
- `serve` is an ungrouped operational meta command. It is not an authority-oriented noun group,
  standalone Runtime surface, or Experiment command. This decision amends bADR-0021 only to add the
  process-control entry point; Experiment remains the execution authority boundary.
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

- The application-neutral Execution HTTP API contains exactly:
  - `GET /v1/status`;
  - `POST /v1/execution-sessions`;
  - `POST /v1/execution-sessions/{session_id}/experiment-revisions`;
  - `POST /v1/execution-sessions/{session_id}/runs`;
  - `DELETE /v1/execution-sessions/{session_id}`.
- The local companion host adds `POST /v1/shutdown` as its authenticated process-control endpoint.
  It is versioned with the transport, but it is not an Experiment execution operation and a later
  local host is not required to expose it.
- Session creation receives a complete Model Source Package and initial Experiment Specification.
  A run names one exact revision identifier. The first protocol has no session/revision listing,
  implicit revision, partial update, artifact query, progress, cancellation, or streaming endpoint.
- `/v1` is the HTTP protocol major, not a Standard Schema or toolkit version. Readiness and status
  report the protocol major and toolkit version. Request and response schemas are closed. A breaking
  protocol change uses a new major path.
- Pydantic request and response models are the single executable source for the first HTTP schemas.
  bADR-0026 and `docs/ARCHITECTURE.md` describe meaning and boundaries without copying every field.
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
- One CLI-independent Application use case owns admission, complete Experiment execution, and
  creation of existing artifact members. The CLI adapter adds invocation-key handling, atomic
  filesystem publication, recovery, and the publication receipt. The HTTP adapter instead returns
  the complete artifact set and content identities inline without a temporary output directory.
- Experiment admission has one value-based semantic core that accepts the complete verified set of
  existing Build receipt, Package Lock, Resolved Model, and RIR artifacts. The CLI path locates and
  authenticates that set from the committed artifact store before calling the core. An Execution
  session compiles and verifies the same set in memory and passes it directly. File and JSON-value
  inputs share canonical admission; the service creates no temporary store, synthetic publication
  receipt, HTTP-only Model format, or second Experiment checker.
- Success and verdict responses contain the complete existing artifact set. Runtime refusal retains
  terminal-audit evidence; other refusal stages retain the existing refusal report. The service
  defines no application-specific endpoint, gameplay result, simplified artifact, or intermediate
  case schema. A measured response-size problem may justify later retrieval or streaming design.

### Host implementation

- `interfaces/cli/serve` binds the operational command and is the process composition root.
  It emits the readiness record on standard output and sends operational logs to standard error.
- `interfaces/http/api_v1` owns the five Execution HTTP API routes, closed schemas, JSON transport,
  and HTTP status mapping. `interfaces/http/local_host` owns loopback binding, process-capability
  authentication, server lifecycle, the shutdown route, and the typed readiness state consumed by
  `interfaces/cli/serve`. These names state responsibility boundaries; they do not require an
  abstract interface or plugin mechanism. None of these modules owns Standard Schema meaning.
- `application/execution_sessions` owns ephemeral session/revision state, idempotent admission,
  per-session ordering, and the process-wide execution gate without knowing HTTP or CLI.
  `application/experiment_execution` owns publication-independent execution. The existing CLI flow
  calls that use case before filesystem publication and recovery.
- Session creation uses the existing value-based Model admission and compilation behavior. The
  verified in-memory Model artifact aggregation is a host value over existing artifacts, not a new
  authority or identity.
- Domain retains Model, Experiment, Runtime, Evidence, identity, artifact, and refusal policy.
  Infrastructure receives only demonstrated domain-neutral mechanisms. This work adds no generic
  Repository, port hierarchy, dependency-injection container, service locator, or event bus.
- Starlette owns the five execution routes, the local control route, middleware, JSON responses,
  exception mapping, and lifespan.
  Uvicorn provides the single-worker ASGI server and graceful lifecycle. Existing Pydantic models
  define closed request and response schemas with unknown fields refused. Reload, WebSockets,
  proxy-header trust, CORS, and default access logging are disabled.
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
- The authenticated shutdown endpoint stops new work, lets work already inside the synchronous
  execution boundary finish, returns an acknowledgement, and exits. The owning client may terminate
  the child process after its own graceful-shutdown timeout. Non-persistent service state cannot be
  partially published by forced process termination.

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
- This proposed record does not authorize implementation or alter accepted Runtime and Experiment
  contracts until the design is accepted.

## Validation

- Prove source and wheel parity for `serve`, readiness, packaged authorities, and protocol schemas.
- Prove that `interfaces/http/api_v1` does not depend on the local-host implementation, that
  Application and Domain do not import Starlette or Uvicorn, and that the service imports no game,
  engine, playtest, or example module.
- Test authentication, loopback-only binding, request bounds, closed schemas, and service-error
  mapping without weakening Domain refusal behavior.
- Compare CLI publication and HTTP inline execution from the same admitted inputs. Assert identical
  semantic artifacts and content identities while retaining Interface-specific transport facts.
- Test exact Model/session binding, idempotent Experiment admission, explicit revision selection,
  refusal atomicity, per-session ordering, cross-session isolation, disconnect behavior, deletion,
  and graceful/forced shutdown.
- Run the focused service and Application suites, the existing Model/Experiment/Runtime/Evidence
  suites, source/wheel checks, dependency-layer checks, type checks, and the complete test suite.
