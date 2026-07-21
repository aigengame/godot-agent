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

- **The 2.x refusal envelope carries Diagnostics rather than 1.x JSON-Pointer-only entries.** The
  closed refusal variant contains `category: refusal`, one `stage`, a non-empty `diagnostics` array,
  and `truncated`. It may additionally carry `reproduction` after stochastic identity exists and a
  `terminal_evidence` receipt after runtime has committed evidence. It has no envelope-level
  diagnostic code: stable codes belong to individual entries.

- **Every Diagnostic has one stable code, explanatory message, tagged primary location, and zero
  or more related locations.** Primary and related locations use a closed tagged union:
  - `invocation` for a whole admitted request or dependency-resolution context;
  - `source` for package/module identity plus a source span;
  - `artifact` for content identity plus an artifact-native pointer;
  - `symbol` for a canonical symbol identity, optionally with its declaration source;
  - `runtime` for run, event, and Snapshot-boundary identities.
  No implementation may fabricate a JSON Pointer for a non-JSON location. Diagnostic codes and
  location identities are normative; message wording is not an automation key.

- **Report-all behavior is stage-bounded.** Parse and static stages report all safely discoverable
  diagnostics up to the deterministic cap. Resolution reports the complete bounded conflict set.
  Runtime, evaluation, migration, and approval may produce one terminal diagnostic plus related
  locations, or a bounded set when the operation can establish independence. Diagnostics sort by
  the location-kind order above, canonical location key, then code; duplicates are removed by
  `(code, primary location, related locations)`. `truncated` records cap exhaustion.

- **Terminal evidence is referenced, not embedded as accidental success.** A runtime refusal may
  attach a receipt identifying the ordered trace, last committed snapshot, refusing event, and
  Runtime profile. The envelope remains category `refusal` and exit 2. Consumers can inspect or
  replay the evidence without mistaking partial execution for a completed result.

- **Usage and internal variants remain separate and closed.** They carry one envelope-level code
  and no domain-diagnostic array. Usage covers only command/argument/path failures before artifact
  admission. Internal uses `internal_error`; under explicit debug mode its sanitized envelope may
  add a `debug` string. Typed domain conditions must never be caught and relabeled `internal`, and
  unexpected exceptions must never be exposed as typed refusals.

- **The Language Definition Bundle owns typed-refusal diagnostic codes and stage membership.**
  Core and extension packages declare versioned, namespaced codes through the bundle authority.
  The CLI usage family and fixed internal code remain command-surface concerns. A code cannot move
  stages or change meaning within a compatible Schema line.

- **The Command descriptor remains the sole surface authority.** In 2.x it names the command's
  input and success-result models; optional verdict model; applicable refusal stages and projected
  refusal schema; handler; argument presentation; execution markings; and fixtures for every
  applicable outcome. Dispatch, help/schema/manifest projections, and the conformance harness walk
  that one registration seam.

- **The conformance harness expands without creating a second registry.** It asserts channel,
  exit, closed-envelope shape, diagnostic code/stage membership, stable location encoding,
  truncation/order/deduplication, terminal-evidence receipts, reproduction identity, and
  result/verdict schemas for every registered command.

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
  terminal-evidence receipts, and verdict reports.
- Existing refusal codes need an explicit 1.x-to-2.x mapping and stage assignment during migration.
- Runtime, evaluation, migration, and approval implementations gain typed failure paths and may not
  signal expected conditions with exceptions.
- CLI taxonomy may change only through a separate decision that updates command descriptors and
  their projections; this bADR fixes outcome behavior, not command names.
- Issue #534's capability mismatch, `not_evaluable`, Runtime refusal, migration, and approval gates
  now have one carrier and stable automation contract.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0004 — Standard Schema 1.x boundary-funnel validation semantics.
- bADR-0008 — current invocation result contract.
- bADR-0011 — command registration seam and conformance harness.
- bADR-0014 — deterministic atomic event runtime.
