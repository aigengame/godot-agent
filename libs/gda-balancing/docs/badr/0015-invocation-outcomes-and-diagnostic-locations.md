---
status: accepted
---

# Preserve the exit algebra while generalizing refusals by stage and diagnostic location

bADR-0008 gives the current CLI a useful five-way outcome algebra: success, negative verdict,
typed refusal, usage error, and internal error. Standard Schema 2.x introduces failures that the
1.x envelope cannot represent honestly. A dependency conflict is not a JSON element, a runtime
budget refusal belongs to an event and snapshot, an evaluation may be impossible without making
the model invalid, and an approval may either be a valid negative decision or be impossible because
its evidence is malformed.

Adding an exit code for every compiler/runtime stage would make automation brittle. Forcing every
location into a JSON Pointer would lose the source, symbol, artifact, and runtime identity agents
need to remediate it. PRD #534 therefore preserves the small outcome algebra while making the
refusal payload stage-aware and artifact-aware.

> **Amendment (2026-08-13, #640):** For an Operation refusal inside a selected Kernel
> `guard-block`, the terminal audit's `instruction_index` uses guard-expanded local Operation order.
> The guard has its outer-body position, its body follows in authored order, and the remaining outer
> nodes follow the body. This coordinate identifies the refusing node without making the guard body
> a separate Operation, Event, or audit scope. bADR-0022 owns the guard grammar and execution order;
> this record owns the terminal-audit member and its binding.

## Decision

- **The exit-code and output-channel algebra remains stable:**

  | Exit | Meaning | Payload | Channel |
  |---|---|---|---|
  | `0` | requested operation completed with a positive or non-judgment result | typed result | stdout |
  | `1` | requested judgment completed with a negative Verdict | typed verdict report | stdout |
  | `2` | expected domain condition refused completion | refusal Error envelope | stdout |
  | `3` | invocation surface is malformed or inaccessible | usage Error envelope | stderr |
  | `4` | toolkit implementation failed unexpectedly | internal Error envelope | stderr |

  Exits 0–2 are machine-readable products of a correctly invoked command. Exits 3–4 mean the
  command did not perform its domain job. Every channel contains exactly one JSON document and
  stdout is empty for exits 3–4.

- **A negative judgment is a Verdict, not a refusal.** Failing a balance target or declining a
  governance approval after valid evidence is evaluated returns exit 1 with the command's typed
  verdict report. Missing evidence, invalid signatures, an unevaluable metric, or any condition
  preventing the judgment is a typed refusal at the applicable stage. A positive judgment returns
  the command's exit-0 result.

- **Standard Schema 2.x defines eight stable Refusal stages:** `ingress`, `parse`, `static`,
  `resolution`, `runtime`, `evaluation`, `migration`, and `approval`.
  - `ingress` owns byte/resource caps, artifact identity/version dispatch, and safe admission.
  - `parse` owns wire grammar and source construction.
  - `static` owns structural, name, type, unit, and other compile-time semantic rules.
  - `resolution` owns package dependency/capability binding and HIR-to-RIR lowering preconditions.
  - `runtime` owns legal execution under bADR-0014.
  - `evaluation` owns metric computability and statistical evaluation preconditions.
  - `migration` owns source/artifact conversion preconditions and loss classification.
  - `approval` owns evidence, attestation, and governance-policy preconditions.
  A refusal envelope names the earliest stage that cannot complete; later stages do not run.
  “Bundle admission” is a process name, not a ninth stage: byte caps, artifact identity/version,
  Kernel/LDB binding, and safe format admission are `ingress`; after those pass, malformed rule/fact
  structure and rule-semantic illegality are `static`. The non-self-hosted Kernel Specification
  publishes this admission meta-diagnostic-to-stage projection; an LDB can publish only the
  post-admission projection, so it never authorizes the reason for rejecting itself.
  The set is a closed Schema-major discriminant: a bundle, package, descriptor, or evaluator cannot
  add, omit, rename, or repurpose a stage. An unknown stage is rejected during ingress rather than
  forwarded as an extension value. `usage` and `internal` remain Error-envelope categories, never
  Refusal stages.

- **The 2.x refusal envelope carries Diagnostics rather than 1.x JSON-Pointer-only entries.** The
  closed refusal variant contains `category: refusal`, one `stage`, a non-empty `diagnostics` array,
  and `truncated`. It may additionally carry only the closed, stage-bound fields defined here:
  `reproduction` after stochastic identity exists, a `terminal_audit` receipt after runtime
  dispatch has begun, and `migration_report` only for a migration-stage refusal. The migration
  field is the inline, LDB-validated refusal report: it records attempted mappings and deprecated
  constructs but never claims or publishes a successful Model Source Package. Other stages cannot
  fabricate these fields, and no ambient refusal-detail extension bag exists. The envelope has no
  envelope-level diagnostic code: stable codes belong to individual entries.

- **Every Diagnostic has one stable code, explanatory message, tagged primary location, and zero
  or more related locations.** Primary and related locations use a closed tagged union:
  - `invocation` for a whole admitted request or dependency-resolution context;
  - `source` for package/module identity plus a source span;
  - `artifact` for content identity plus an artifact-native pointer;
  - `symbol` for a canonical symbol identity, optionally with its declaration source;
  - `runtime` for run, Initialization-frame, Formula evaluation-site, Event, and Snapshot-boundary
    identities.
  No implementation may fabricate a JSON Pointer for a non-JSON location. Diagnostic codes and
  location identities are normative; message wording is not an automation key.

- **Report-all behavior is stage-bounded.** Parse and static stages report all safely discoverable
  diagnostics up to the deterministic cap. Resolution reports the complete bounded conflict set.
  Runtime, evaluation, migration, and approval may produce one terminal diagnostic plus related
  locations, or a bounded set when the operation can establish independence. Diagnostics sort by
  the location-kind order above, canonical location key, then code; duplicates are removed by
  `(code, primary location, related locations)`. `truncated` records cap exhaustion.

- **Terminal audit is referenced, retrievable, and never accidental success.** Once Event dispatch
  has begun, a runtime refusal atomically publishes a separately typed terminal-audit artifact set
  and returns its content-identity/locator receipt. The set identifies the ordered committed trace
  prefix, last committed Snapshot, refusing event, rollback facts, Diagnostic, Resolved Runtime
  profile, and exact reproduction identities. It is committed as one refusal-only publication
  under bADR-0021. Semantic admission revalidates the audit's internal closure, not only member
  schemas and top-level identities: trace indexes and per-Scenario Snapshot/state chains, the last
  Snapshot and rollback equality, refusing-event index/Snapshot/order, terminal condition, budget
  coordinate, Diagnostic code/stage/location, and reproduction receipt must agree. The audit
  therefore carries the admitted Event-catalog prefix, the complete last Snapshot record, and the
  complete refusing Event specification. Recovery re-derives catalog membership from the checked
  Experiment, Metrics, committed parent Events, and RIR schedule sites; it then recomputes the
  Snapshot identity, continuation journals, pending set, and exact catalog/trace/resource counts.
  A derived refusing observation is exactly the next Metric at the last Snapshot's logical boundary
  and enqueue cursor. An operation refusal records the exact failing instruction and completed
  nested-call prefix needed to derive the current Event charge from admitted RIR. Without rerunning
  the evaluator, Recovery walks the admitted RIR resource transitions through that first budget
  breach and treats those coordinates as evidence to compare, not path authority. Attempted Event
  and node steps close against the last committed resource ledger plus those independently derived
  current-Event and applicable Formula charges; they are not merely bounded values. Re-hashing
  independently wire-valid drift does not make it trusted recovery evidence. Only after commit does
  the command emit the category-`refusal` envelope on stdout with exit 2; stdout is not part of the
  artifact-store transaction. No completed Evaluation run,
  Metric dataset, success result, Verdict, or positive Evidence assertion is published. A receipt
  must resolve to bytes whose identity verifies; an unpublished digest is not a retrievable receipt.
  The terminal-audit set has a closed member-kind contract and may include already successful
  authority/build/profile prerequisites needed to resolve every audit reference, but those members
  do not convert the set into a command-success outcome and it may never include partial
  Evaluation/Metric/Replay/Evidence artifacts.

- **Initialization refusal is a pre-Event Runtime variant, not a fabricated terminal audit.**
  Initialization may begin only after the exact Runtime inputs and reproduction identities exist,
  but Snapshot 0 and the first Event do not yet exist. If an initialization Formula or resource
  bound refuses, the command returns a `runtime`-stage refusal without `terminal_audit`; its
  Diagnostic binds the exact Initialization-frame and Formula evaluation-site provenance. No
  Event, rollback fact, Snapshot, trace, Evaluation, Metric, comparison, or Evidence artifact is
  published. The descriptor must distinguish this reachable pre-Event variant from the
  post-dispatch Runtime variant whose terminal-audit receipt is mandatory.

- **Publication/delivery failure has explicit command semantics.** If terminal-audit publication
  fails before commit, no Runtime-refusal envelope can truthfully carry a receipt; the command emits
  `internal_error` on stderr with exit 4 and no receipt. If commit succeeds but result-envelope
  delivery fails or the process crashes, the committed terminal-audit set remains authoritative and
  recoverable by its caller-supplied Invocation key under bADR-0021. Idempotent retry of the
  original command with the same canonical input re-emits the recorded Runtime-refusal envelope
  without re-executing the model.

- **Usage and internal variants remain separate and closed.** They carry one envelope-level code
  and no domain-diagnostic array. Usage covers only command/argument/path failures before artifact
  admission. Internal uses `internal_error`; under explicit debug mode its sanitized envelope may
  add a `debug` string. Typed domain conditions must never be caught and relabeled `internal`, and
  unexpected exceptions must never be exposed as typed refusals.

- **Kernel and LDB split Diagnostic authority at the admission boundary.** The non-self-hosted
  Schema-major Kernel contract owns the closed meta-diagnostic codes, payloads, precedence, and
  `ingress`/`static` assignments required to admit or reject a Kernel/LDB. Once admitted, the LDB
  owns language, compiler, runtime, evaluation, migration, and approval typed-refusal codes and
  stage membership; Core and extension packages declare versioned, namespaced codes only through
  that bundle. The CLI usage family and fixed internal code remain command-surface concerns. A code
  cannot move stages or change meaning within a compatible Schema line, and the closed stage
  vocabulary itself cannot be extended by bundle content. Implementations generate or
  reverse-enumerate every reachable rule, Operation, Kernel refusal, and direct host-boundary exit
  against the authority available before that table is used. The reachable reason map and
  Diagnostic catalog must be exact—missing, extra, duplicate, or stage-drifting entries fail
  admission—and conformance vectors must trigger every authoritative code and confirm its stage; a
  host-only code or stage mapping is a conformance failure.

- **The Command descriptor remains the sole per-command surface authority.** Under bADR-0021's
  shared Command schema profile, it names one closed input model (empty for a zero-parameter
  command), each reachable success/verdict model, applicable refusal stages and projected refusal
  schema, handler, argument presentation, execution markings, and fixtures for every applicable
  outcome. A gate-only command does not declare an unreachable success model. Dispatch,
  help/schema/manifest projections, and the conformance harness walk that one registration seam.

- **The conformance harness expands without creating a second registry.** It asserts channel,
  exit, closed-envelope shape, diagnostic code/stage membership, stable location encoding,
  truncation/order/deduplication, terminal-audit receipts, reproduction identity, and
  each declared result/verdict schema, plus rejection of any undeclared outcome.

- **This decision supersedes only the conflicting 2.x portions of bADR-0004, bADR-0008, and
  bADR-0011.** It replaces the three-phase-only refusal boundary, JSON-Pointer-only refusal entry,
  and 1.x closed envelope for 2.x. It retains gated validation, preflight caps, typed/report-all
  refusal, the 0–4 exit/channel meanings, single JSON payload, sanitized internal failures, one
  Command descriptor seam, and registry-walking conformance. Their existing contracts remain
  normative for Standard Schema 1.x and the current CLI until 2.x commands ship.

## Considered options

- **Keep five outcomes and add refusal stage/location** (chosen) — preserves automation behavior
  while making new compiler, runtime, evidence, and governance failures actionable.
- **One exit code per pipeline stage** (rejected) — couples shell automation to pipeline growth and
  confuses failure origin with outcome meaning.
- **Map runtime/evaluation failure to internal error** (rejected) — these are expected domain
  conditions with stable remediation, not toolkit defects.
- **Return runtime refusal as success with a partial-result flag** (rejected) — makes incomplete
  execution indistinguishable from a requested terminal result.
- **Treat a negative approval as approval refusal** (rejected) — the judgment completed; its answer
  is negative, exactly the Verdict distinction.
- **Keep JSON Pointer as the only location** (rejected) — multi-file source, symbols, dependency
  graphs, events, and snapshots do not have honest JSON Pointer coordinates.
- **Wrap success, verdict, and errors in one universal envelope** (rejected) — adds ceremony without
  improving discrimination; descriptor-projected schemas already define successful payloads.

## Consequences

- The 2.x wire specification needs closed schemas for all location variants, refusal envelopes,
  terminal-audit artifact sets/receipts, and verdict reports.
- Existing refusal codes need an explicit 1.x-to-2.x mapping and stage assignment during migration.
- Runtime, evaluation, migration, and approval implementations gain typed failure paths and may not
  signal expected conditions with exceptions.
- CLI taxonomy may change only through a separate decision that updates command descriptors and
  their projections; this bADR fixes outcome behavior, not command names.
- Issue #534's capability mismatch, `not_evaluable`, Runtime refusal, migration, and approval gates
  now have one carrier and stable automation contract.

## Validation

- Enumerate all eight Refusal stages from the authoritative stage contract and reject missing,
  duplicate, misspelled, unknown, or category-valued stages before command dispatch.
- For every registered command, execute each declared reachable success/Verdict, every applicable
  Refusal stage, usage, and injected internal failure; assert exact exit, channel, closed schema,
  location kind, diagnostic ordering/deduplication, and truncation behavior. A descriptor with no
  success model must reject an injected exit-0/completed result as an internal conformance fault.
- Inject a runtime fault after dispatch and assert that exit 2 carries one resolving
  `terminal_audit` receipt, the separately typed artifact set verifies by content identity, and no
  success artifact set is visible. Faults before dispatch must not claim terminal audit.
- Trigger an initialization Formula refusal after Runtime inputs bind but before Snapshot 0 and
  Event dispatch. Assert exit 2 on stdout with stage `runtime`, exact frame/site provenance, no
  `terminal_audit`, no Event/Snapshot/trace artifact, and no success/Verdict/Evidence publication.
- Validate the terminal-audit artifact itself, not only its set membership: require the committed
  trace and admitted-Event-catalog prefixes, complete last Snapshot and refusing Event specification,
  rollback facts, complete Diagnostic location, Resolved Runtime profile, and exact reproduction
  identities. Include coordinated fresh-hash vectors for Snapshot identity/continuation/budgets and
  refusing Event identity/specification, not only individually mismatched references.
- Fail terminal-audit publication before commit and assert `internal_error`/exit 4 with no receipt;
  fail or crash after commit but before envelope delivery and assert recovery/retry returns the
  committed refusal without rerunning the model.
- Mutate a Kernel-owned admission Diagnostic or its stage and assert bootstrap conformance fails;
  mutate an admitted package Diagnostic or its post-admission stage and assert LDB conformance fails.
  Neither path may allow an evaluator- or descriptor-local override.
- Delete and reidentify each Kernel admission mapping and each post-admission reason/Diagnostic pair
  one at a time; both independent consumers must refuse before the missing code can be needed. Then
  trigger every authoritative code and assert its exact stage, proving behavioral coverage rather
  than catalog membership alone.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0004 — Standard Schema 1.x boundary-funnel validation semantics.
- bADR-0008 — current invocation result contract.
- bADR-0011 — command registration seam and conformance harness.
- bADR-0014 — deterministic atomic event runtime.
- bADR-0021 — command descriptors and artifact-set publication.
