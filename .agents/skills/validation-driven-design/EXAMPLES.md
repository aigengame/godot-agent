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
and evidence. Machine-checkable observable claims get executable conformance cases. None becomes a
peer authority merely because its terminology is reused.

### 3. Iterative probes

The selected direction is translated into a concrete module structure. That structural pass returns
claims about responsibility ownership, dependency direction, and extension boundaries. The probes
below test those claims; an adopted refinement changes only the affected structural decisions.

1. An end-to-end slice compiles one policy, runs it, and publishes an audit. It confirms connectivity
   but exposes ambiguous refusal staging and identity.
2. Two independent runtimes consume each other's canonical artifacts. A mutation test reveals one
   rule was still host-coded, so the rule moves into the versioned language bundle.
3. An extension probe adds a billing policy and a scheduling policy without rebuilding either
   runtime. Cross-product tests expose an unspecified precedence rule; the extension contract gains
   canonical ordering and a negative conformance case.
4. A structurally different access-control domain reuses the same extension and audit path. If it
   needs a runtime switch, the extensibility gate fails and the architecture reopens.

### 4. Dogfooding synthesis

| Observation | Disposition | Owner update | Non-claim |
| --- | --- | --- | --- |
| one end-to-end run succeeds | confirmed-no-change | architecture topology and end-to-end scenario | not framework completeness |
| runtimes disagree on a host-coded rule | refined-adopted | language decision and executable conformance case | not fixed by documenting one runtime |
| extension interaction order is absent | gap-opened | open specification owner and boundary conformance case | packages are not yet orthogonal |

Prototype code stays at immutable evidence revisions. Only the corrected decisions, terms,
scenarios, and executable conformance cases enter their owning authoritative artifacts and authority map.

### 5. Design-axis conclusion

- **Abstraction:** supported for the canonical semantic boundary; optimizer freedom remains private.
- **Completeness:** the known policy stories map to scenarios, but production recovery remains open.
- **Orthogonality:** extension state is separate; precedence is now explicit and mutation-tested.
- **Extensibility:** two domains pass; the out-of-family witness is still required before a general
  claim.

The next step is a permanent conformance foundation, not another connectivity prototype.
Cross-cutting reliability and operability remain open until durable storage, recovery,
authentication, capacity, observability, rollout, and rollback have evidence.

## Example: make a lightweight internal persistence decision

A service proposes bounded in-memory batching while retaining its existing database as the sole
persistence authority. The author selects `lightweight`: one owner, one decision record, one
falsifier (an acknowledged item is absent after recovery), one crash-boundary check, reliability as
the affected quality, explicit non-claims about exactly-once delivery and performance, and a human
decision gate.

The author does not create theory or external-system matrices, a prototype portfolio, or the full
delivery plan. If the crash check exposes ambiguous commit state, the owner either opens one focused
idempotency decision or rejects the design; that evidence need does not silently promote the entire
engagement to `full-design` mode.

## Example: audit an existing event-delivery architecture

The team claims that a fixed document set completely specifies retry order, deduplication, and
failure recovery. The auditor selects `audit-only`, pins the artifact revision and claimed scope, and
makes no edits.

- The authority audit finds retry precedence restated differently in the standard and deployment guide.
- Two independent readers derive different behavior for equal-time retries, so the affected
  conformance claim is `open`; passing integration tests do not turn it into conformance proof.
- Orthogonality and reliability remain open, while unrelated extensibility claims are not re-evaluated.

The report proposes one normative owner and a discriminating boundary conformance case, then stops. The human
decision owner conditionally accepts the audit, authorizes specification repair, and leaves the
conformance claim open.
