---
status: accepted
---

# Align the Schema 2.0 CLI with model, experiment, and evidence artifacts

> **Partial supersession (2026-09-06, [bADR-0028](0028-current-language-refactor-and-pre-1.0-retirement.md)):**
> bADR-0028 supersedes model migrate as a permanent forward command and requires removal of
> obsolete version selectors and execution-binding fields from descriptors and every derived
> surface when their owning slice lands. The command table retains its accepted target status;
> the live CLI manifest defines command availability. Delivered migration/version/binding forms
> remain current implementation contracts until their replacements land. The unused artifact
> sink is also retired without removing active
> artifact-set publication. Descriptor ownership, typed outcomes, diagnostics, invocation-key
> recovery, and atomic publication remain binding.

bADR-0007 organized the 1.x surface around a single Design document and reserved generic
`evaluation` and `tuning` groups. Standard Schema 2.0 instead has Model Source Packages, package
resolution, RIR builds, Experiment Specifications, Evaluation runs, Metric datasets, and evidence
graphs. Retaining `design validate` or adding independent runtime flags would hide the new authority
domains and allow command-line arguments to redefine an experiment.

The descriptor, structured-output, atomic-write, and noun-group principles remain valuable. PRD
#534 therefore replaces the 1.x nouns while making the previously deferred aggregate manifest and
structured-params adapter part of the first vertical tracer.

> **Amendment (2026-07-31, #590):** bADR-0014/0015 now distinguish initialization refusal before
> Event dispatch from post-dispatch Runtime refusal. A Command descriptor exposes both reachable
> variants: the initialization variant has no Snapshot/Event/trace/success artifact or
> `terminal_audit`, while the post-dispatch variant requires the exact terminal-audit receipt.
> Under bADR-0013, every successful `model build` publishes a Model explanation in its complete
> build-companion set. This record owns only the CLI projection: `model inspect` retrieves that
> stored companion, may render deterministic indented JSON without changing stored canonical bytes,
> and never regenerates, edits, or executes it. bADR-0022 owns the explanation's Formula and
> Operation contents.

> **Amendment (2026-08-02, bADR-0024):** The 2.x noun taxonomy additionally requires the non-executing
> `formula parse` and `formula render` transformations. Both bind their structured inputs to one
> exact Kernel/LDB and Formula declaration context, return a complete structured body plus canonical
> expression, and publish no semantic artifact. Their live Command descriptors remain the only CLI,
> structured-input, outcome, schema, manifest, and help authority.

> **Amendment (2026-08-15, bADR-0026):** `serve` is an ungrouped operational meta command with one
> live Command descriptor. Its `foreground-service` execution marking selects the Interface-owned
> foreground runner defined by bADR-0026. The descriptor remains the single source for input,
> readiness, errors, help, `--schema`, manifest projection, and conformance. `serve` is not a
> standalone Runtime group or another Experiment authority.

> **Amendment (2026-08-24, #545):** The initial `experiment replay` input contains one Experiment
> Specification, one original Experiment-run Artifact-set receipt, one output locator, and one
> Invocation key. The receipt is the single anchor for the original run; the command does not accept
> a second list of member identities or discover runs through a store scan. A completed Replay
> comparison publishes one atomic Artifact set with the comparison as its primary member. A match
> uses the success set, which also contains the new Evaluation run and its trace, Snapshot, Metric,
> reproduction, Runtime-profile, and evaluator artifacts. A mismatch uses one fixed Verdict set. It
> contains the comparison and the same observation and reproduction artifacts, but no
> `evaluation-run` or `experiment-verdict` member. The comparison records both outcome statuses.
> The original run remains a separate publication and is referenced by identity. A post-dispatch
> Runtime refusal publishes only the existing refusal-only terminal-audit set and no partial Replay
> comparison.

## Decision

- **The binary remains `gda-balancing` with noun-group commands.** Registered domain commands use
  `gda-balancing <group> <command>`. Tokens are kebab-case; delivery phase never appears in the
  tree. `version`, `manifest`, `serve`, and human-facing `help` remain ungrouped meta commands.

- **The Standard Schema 2.x command taxonomy is:**

  | Group | Commands | Authority/artifact boundary |
  |---|---|---|
  | `schema` | `get language-bundle`, `get wire-schema`, `get diagnostic-catalog` | emit the Language Definition Bundle or a named generated projection |
  | `package` | `list`, `get` | enumerate root-declared packages or retrieve an exact Package Release manifest/conformance-vector member from one exact language bundle |
  | `model` | `check`, `build`, `inspect`, `diff`, `migrate` | validate/resolve source, build or compare RIR artifacts, or attempt limited 1.x source conversion |
  | `template` | `list`, `get`, `instantiate` | enumerate template releases or create a new Model Source Package identity |
  | `experiment` | `check`, `run`, `replay`, `compare` | validate Experiment Specifications or produce/compare deterministic Evaluation runs and Metric datasets |
  | `evidence` | `inspect`, `verify` | inspect or verify the immutable evidence graph and content identities |

  `calibration` and `approval` are reserved noun groups. They are absent until their first vertical
  commands have complete descriptors, bADR-0018 statistical/governance contracts, and conformance
  fixtures. Invoking a reserved-but-undelivered group is an unknown-command usage error.

- **There is no standalone `runtime` group.** Runtime execution requires an exact Resolved Model,
  Experiment Specification, Resolved Runtime profile, external inputs, and seed identity. Public
  execution therefore enters through `experiment run` or `experiment replay`; free-form runtime
  flags cannot become a fourth experiment authority.

- **There is no standalone `metrics` group in the initial surface.** Metric definitions belong to
  Experiment Specifications; Metric datasets are produced by experiment commands and verified as
  evidence. A future independently justified transformation/ingestion workflow may add a noun group
  through a new decision, but storage format alone is not a group.

- **`model build` is the public compiler boundary.** It admits a Model Source Package and exact
  Language Definition Bundle/resolution inputs, then returns identities/receipts for the generated
  Package Lock, Resolved Model (RIR), Capability manifest, and compiler provenance.
  `model check` performs the same gated front end without claiming or emitting a build artifact.

- **`package get` preserves Package Release member boundaries.** The exact package coordinate and
  closed `member` selector retrieve either `release` (the default manifest) or
  `conformance-vectors`. The command returns the stored canonical member without merging,
  regenerating, or treating the vector child as an independently selectable package. Its success
  schema is derived from the admitted Kernel contracts for both member kinds.

- **`experiment run` is the public execution/evaluation boundary.** It admits artifact identities
  rather than redefining source values in flags. It returns a complete producing-outcome artifact
  set with an Evaluation run or Experiment Verdict, Metric dataset, Event trace, Snapshot series,
  and reproduction identities. `experiment replay` requires the exact prior reproduction
  identities; it repeats an accepted 2.x Evaluation run and publishes a separate comparison. It is
  not a 1.x migration path.

- **`manifest` ships with the first 2.x tracer.** It emits the Surface manifest by walking the live
  Command-descriptor registry. Each registered entry carries command name/description, input,
  reachable success, optional verdict, and error schemas; execution markings; and artifact behavior.
  A gate-only command with no positive result omits `success` rather than advertising an unreachable
  outcome. Every command retains one closed `input` schema; a zero-parameter command uses an empty
  closed object rather than omitting the binding contract. Help and reserved/undelivered groups are
  excluded because they have no dispatchable descriptor.

- **Every registered command ships `--schema`.** Its closed result contains `input`, optional
  reachable `success`, optional `verdict`, and `error`. `success`/`verdict` are present only for
  commands that can return exit 0/1 respectively; `input` is always present, even when it admits
  only `{}`. `error` includes the applicable bADR-0015 usage/internal and stage-aware refusal
  variants. The exact same models feed argv/structured binding, defaults, required/unknown-field
  handling, type decoding, conflict detection, dispatch validation, manifest emission, and the
  conformance harness.
  A schema with only an object shell while handler code owns its fields, or any parallel parameter
  map, is non-conforming.

- **All public command schemas use one closed Command schema profile.** One immutable,
  content-addressed cross-command rules artifact in the command-descriptor registry exhaustively
  lists the JSON Schema Draft 2020-12 `$schema` URI, admitted keywords and formats,
  content/version-derived absolute `$id` law, local `$defs`/exact-content-reference policy, object
  closure via
  `unevaluatedProperties: false`, and annotation/default-binding rules. Remote network resolution,
  unlisted keywords, and implementation-defined formats are prohibited. `default` remains an
  annotation in JSON Schema; each Command descriptor remains the sole per-command authority and
  owns/applies its CLI/adapter defaults under the profile.
  Referenced artifact Structural schemas and their semantic defaults remain LDB-owned and cannot be
  redefined by a descriptor. The Surface manifest identifies the exact Command schema profile, and
  changing it is a command-surface compatibility decision.

- **Structured params input is mandatory in every 2.x vertical tracer.** `--params-json <json | ->` binds the
  descriptor's typed input model, with `-` reading stdin. It is mutually exclusive with individual
  argv fields; conflict is a usage error. Bare `--schema` takes precedence over all other arguments
  and emits without reading artifacts or executing the handler. Structured input cannot express
  fields the descriptor does not own.

- **The Command descriptor remains the only registration seam.** In addition to bADR-0015 fields,
  it owns artifact input/output-set roles, publication receipts/locators, structured-params
  eligibility, closed typed models, and fixtures for every reachable success/verdict, every
  applicable refusal stage, usage, internal fault injection, schema, manifest, and stochastic
  reproduction. Dispatch
  cannot accept an input, default, outcome, refusal stage, or artifact behavior absent from that
  descriptor, and the descriptor cannot advertise an input or outcome the handler cannot reach.
  Parallel argument maps, command lists, error schemas, artifact lists, or manifest rows are
  prohibited.

  A `foreground-service` descriptor uses the same registry and projections but has a lifecycle
  runner instead of the normal one-shot handler tail. The runner emits the descriptor's typed
  readiness result only after the service accepts requests, then waits for shutdown. It cannot
  introduce a parallel registration, schema, error, help, or manifest path.

- **Artifact output uses one invocation-level publication transaction.** Results always remain on
  stdout. A descriptor declares the complete success artifact set: primary and companion artifacts,
  their types, content identities, locators, and one set receipt. `--out` selects the declared
  primary presentation/destination; it is not the atomicity unit. The implementation stages and
  verifies every member, then makes the set receipt and all locators visible at one commit point. A
  crash, collision, write fault, or verification failure before that point leaves the previous
  visible set unchanged and publishes neither a receipt nor a subset. Storage/transport may vary,
  but every receipt must resolve and rehash independently. The committed publication index anchors
  the originally committed receipt identity; lookup revalidates that anchor, receipt, complete member
  set, and every member so a coherent record/member rewrite cannot silently become a new outcome.
  Each standardized store adapter must declare and test the durability/trust boundary that makes its
  index immutable. Input artifacts are never mutated, and direct/symlink aliasing of any input/output
  member is a usage error.

- **Refusal publication is separate from success publication.** A pre-runtime refusal publishes no
  command success artifacts. After runtime dispatch, bADR-0014/0015 requires one separately typed
  terminal-audit artifact set; the command commits that entire refusal-only set and its locator
  receipt before emitting the exit-2 envelope. It cannot reuse the success artifact-set type,
  expose a partial Evaluation run/Metric dataset/Evidence set, or return an unresolvable digest as a
  receipt.

- **Artifact commit and result-envelope delivery are ordered, not one cross-transport
  transaction.** The publication transaction covers the durable artifact set, locator index, and
  receipt only; stdout/stderr cannot participate in that transaction. Every artifact-producing
  Command descriptor requires a caller-supplied `invocation_key` of 64 lowercase hexadecimal digits
  encoding 32 octets, exposed as `--invocation-key` and through the same structured input model. The
  publication index binds `(descriptor identity, invocation_key)` to one canonical command-input
  identity and committed Artifact-set receipt. That canonical input excludes `invocation_key` and
  presentation-only output locators. Reuse with different canonical input is an
  `invocation_key_conflict` usage error and never dispatches; retrying the original command with the
  same key/input after commit re-emits the stored outcome without executing.
  Publication failure before commit produces `internal_error` on stderr with exit 4 and no
  domain-result envelope or receipt. If the set commits but the process crashes or envelope
  delivery fails, the caller already knows the key and recovery returns the immutable set. Retention
  may later collect an unclaimed set, but cannot pretend it never committed.

- **Verb meanings are closed.** `get` retrieves one definition/artifact, `list` enumerates,
  `instantiate` creates a new model authority from a template, `check` performs gated analysis,
  `build` emits a resolved artifact, `run` executes a new experiment, `replay` repeats exact
  reproduction identities, `compare` evaluates declared comparable artifacts, `inspect` returns
  structured internal facts, `diff` returns semantic model differences, `verify` validates evidence
  claims, and `migrate` attempts bADR-0019's limited conversion. `read`, `show`, `validate`, `format`,
  `simulate`, `tune`, and other synonyms cannot enter the 2.x tree without amending this record.

- **`version` reports distinct identities.** It returns the toolkit package version, supported
  Standard Schema lines, Language Definition Bundle versions, and command-surface version without
  conflating them. Schema 2.0 still does not imply product version 2.0.0.

- **This decision supersedes bADR-0007 for the 2.x surface and the conflicting 2.x portions of
  bADR-0009/0011.** It replaces the `design` group and reserved `evaluation`/`tuning` nouns, delivers
  rather than defers `manifest`/`--params-json`, expands per-command schema outcomes, and extends the
  descriptor/harness. It retains one binary, noun groups, explicit help, JSON channel discipline,
  schema projection, safe output, input immutability, one descriptor registry, and exhaustive
  conformance. The current 1.x CLI remains only until the clean-break tracer replaces it
  (bADR-0019).

## Considered options

- **Artifact-oriented groups with experiment-owned runtime** (chosen) — mirrors authority domains
  and prevents command flags from becoming hidden model/experiment definitions.
- **Keep `design/evaluation/tuning`** (rejected) — encodes the 1.x single-document worldview and
  obscures compiled/evidence artifacts.
- **Expose `runtime run` with free flags** (rejected) — duplicates Experiment Specification authority
  and makes reproduction inputs invisible.
- **Expose every artifact type as a top-level group** (rejected) — storage nouns such as metrics,
  locks, and traces do not each justify independent workflows.
- **Continue deferring manifest and structured params** (rejected) — the 2.x surface is large and
  agent-driven; disposable vertical tracers are the first consumers that justify the adapters.
- **Hand-maintain a CLI manifest** (rejected) — recreates command-surface drift beside the descriptor
  authority.
- **One generic `artifact` group** (rejected) — erases the domain actions and authority boundaries
  agents need to choose a safe operation.

## Consequences

- The first 2.x tracer must register schema/model/template/experiment/evidence commands only as they
  become executable; the manifest exposes exactly the delivered subset.
- CLI schema and conformance fixtures cover each declared reachable success/Verdict, all applicable
  Refusal stages, usage/internal failures, structured input, artifacts, and reproduction. They also
  prove undeclared success/Verdict outcomes are rejected.
- Existing 1.x command implementation/issues must be rewritten around the new descriptors rather
  than aliased indefinitely.
- Calibration and approval delivery require vertical command decisions but their noun ownership is
  protected now.
- Issue/README/help surfaces must use the same nouns and may not advertise reserved commands as
  available.

## Validation

- Project every live Command descriptor into `--schema` and `manifest`, then drive argv and
  `--params-json` through those exact models. Cover required, optional/defaulted, unknown,
  wrong-type, malformed-JSON, stdin, argv/JSON conflict, and bare-`--schema` cases; no handler-local
  field may be accepted or omitted from the projection.
- Validate every projection with two independent Draft-2020-12 validators under the closed local
  profile. Reject remote references, unknown profile keywords/formats, open object shapes, `$id`
  drift, and any difference between descriptor-applied defaults and schema annotations.
- Enumerate every declared reachable success/Verdict, all applicable closed Refusal stages, usage,
  and injected internal failure from each descriptor; assert exact model, channel, exit, and
  artifact behavior. For a gate-only descriptor, inject an exit-0/completed result and require an
  internal conformance failure because `success` is undeclared.
- For multi-artifact build and experiment commands, inject faults before staging, between member
  writes, after verification, and immediately before/after the commit point. Assert readers observe
  either the old complete set or the new complete set, never a mixture, and every visible locator
  rehashes to its receipt identity. Then coherently rewrite the record, member files, and reidentified
  receipt while leaving the committed publication-index anchor unchanged; lookup must reject the
  replacement. Run the corresponding index-compromise/durability tests at each adapter's declared
  trust boundary.
- Inject runtime refusal after committed events and assert exactly one complete terminal-audit set
  is retrievable while no success artifact member or success-set receipt is visible. Repeat with
  concurrent readers and crash-recovery fixtures under each standardized store adapter.
- Inject initialization refusal before Snapshot 0 and assert the same descriptor emits stage
  `runtime` without a `terminal_audit` field or any Event/Snapshot/trace/success artifact. The
  post-dispatch Runtime variant must still require its exact terminal-audit receipt.
- Fail publication before commit and assert `internal_error`, exit 4, and no visible set. Fail or
  crash after commit but before/during stdout delivery and assert the set remains retrievable by its
  caller-known Invocation key and retry of the original command re-emits the recorded envelope
  without model execution. Reusing the key with changed canonical input must be a usage error before
  dispatch.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0007/0009/0011 — 1.x taxonomy, structured I/O, and descriptor contracts superseded for the
  2.x surface only.
- bADR-0012 — authored authority domains.
- bADR-0013 — compiler stages and mandatory build companions.
- bADR-0015 — invocation outcomes and diagnostic locations.
- bADR-0018 — metrics/evidence ownership.
- bADR-0019 — clean break and limited migration.
