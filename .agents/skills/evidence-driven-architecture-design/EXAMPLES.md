# Examples

## Example: deterministic policy-simulation framework

The team needs a framework that lets several product domains author policies, simulate them in two
independent runtimes, and publish auditable results. New domains should not require runtime switches.

### 1. Design contract

- Requirement: declarative policies, deterministic simulation, typed refusals, extensible domains,
  independently checkable audit artifacts.
- Non-goal: a general-purpose scripting language or compatibility with every workflow standard.
- Vision under test: a new bounded domain enters through versioned extensions with unchanged core
  semantics and runtime dispatch.

### 2. Theory and external research

The theory matrix uses compiler construction to separate authoring syntax, typed policy meaning,
canonical public semantics, and runtime-private execution. State-machine theory owns lifecycle
transitions; event sourcing informs audit boundaries but is not imported wholesale.

The team studies a pinned workflow specification, a component-extension system, and an audit-log
model. For each it records the adopted mechanism, local owner, rejected format/runtime surfaces,
and vectors. None becomes a peer authority merely because its terminology is reused.

### 3. Iterative probes

1. A vertical tracer compiles one policy, runs it, and publishes an audit. It confirms connectivity
   but exposes ambiguous refusal staging and identity.
2. Two independent runtimes consume each other's canonical artifacts. A mutation test reveals one
   rule was still host-coded, so the rule moves into the versioned language bundle.
3. An extension probe adds a billing policy and a scheduling policy without rebuilding either
   runtime. Cross-product tests expose an unspecified precedence rule; the extension contract gains
   canonical ordering and a negative vector.
4. A structurally different access-control domain reuses the same extension and audit path. If it
   needs a runtime switch, the extensibility gate fails and the architecture reopens.

### 4. Dogfooding synthesis

| Observation | Classification | Owner update | Non-claim |
| --- | --- | --- | --- |
| one end-to-end run succeeds | confirmed-narrowly | architecture topology and tracer scenario | not framework completeness |
| runtimes disagree on a host-coded rule | refined-adopted | language decision and conformance vector | not fixed by documenting one runtime |
| extension interaction order is absent | open then refined | extension specification and boundary vector | packages are not yet orthogonal |

Prototype code stays on fixed evidence commits. Only the corrected decisions, terms, scenarios, and
vectors enter the authority branch.

### 5. Four-axis conclusion

- **Abstraction:** supported for the canonical semantic boundary; optimizer freedom remains private.
- **Completeness:** the known policy stories map to scenarios, but production recovery remains open.
- **Orthogonality:** extension state is separate; precedence is now explicit and mutation-tested.
- **Extensibility:** two domains pass; the out-of-family witness is still required before a general
  claim.

The next step is a permanent conformance foundation, not another connectivity prototype. Production
readiness waits for durable storage, recovery, authentication, capacity, observability, rollout,
and rollback evidence.
