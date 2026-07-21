---
status: accepted
---

# Align the Schema 2.0 CLI with model, experiment, and evidence artifacts

bADR-0007 organized the 1.x surface around a single Design document and reserved generic
`evaluation` and `tuning` groups. Standard Schema 2.0 instead has Model Source Packages, package
resolution, RIR builds, Experiment Specifications, Evaluation runs, Metric datasets, and evidence
graphs. Retaining `design validate` or adding independent runtime flags would hide the new authority
domains and allow command-line arguments to redefine an experiment.

The descriptor, structured-output, atomic-write, and noun-group principles remain valuable. PRD
#534 therefore replaces the 1.x nouns while making the previously deferred aggregate manifest and
structured-params adapter part of the first vertical tracer.

## Decision

- **The binary remains `gda-balancing` with noun-group commands.** Registered domain commands use
  `gda-balancing <group> <command>`. Tokens are kebab-case; delivery phase never appears in the
  tree. `version`, `manifest`, and human-facing `help` remain ungrouped meta commands.

- **The Standard Schema 2.x command taxonomy is:**

  | Group | Commands | Authority/artifact boundary |
  |---|---|---|
  | `schema` | `get language-bundle`, `get wire-schema`, `get diagnostic-catalog` | emit the Language Definition Bundle or a named generated projection |
  | `package` | `list`, `get` | enumerate or retrieve package definitions from one exact language bundle |
  | `model` | `check`, `build`, `inspect`, `diff`, `migrate` | validate/resolve source, build or compare RIR artifacts, or attempt limited 1.x source conversion |
  | `template` | `list`, `get`, `instantiate` | enumerate template releases or create a new Model Source Package identity |
  | `experiment` | `check`, `run`, `replay`, `compare` | validate Experiment Specifications or produce/compare deterministic Evaluation runs and Metric datasets |
  | `evidence` | `inspect`, `verify` | inspect or verify the immutable evidence graph and content identities |

  `calibration` and `approval` are reserved noun groups. They are absent until their first vertical
  commands have complete descriptors, bADR-0018 statistical/governance contracts, and conformance
  fixtures. Invoking a reserved-but-undelivered group is an unknown-command usage error.

- **There is no standalone `runtime` group.** Runtime execution requires an exact Resolved Model,
  Experiment Specification, Runtime profile, evaluator, external inputs, and seed identity. Public
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

- **`experiment run` is the public execution/evaluation boundary.** It admits artifact identities
  rather than redefining source values in flags and returns the completed Evaluation run, Metric
  dataset, trace/evidence identities, and verdict when applicable. `experiment replay` requires the
  exact prior reproduction identities; it is replay of 2.x evidence, not 1.x migration.

- **`manifest` ships with the first 2.x tracer.** It emits the Surface manifest by walking the live
  Command-descriptor registry. Each registered entry carries command name/description, input,
  success, optional verdict, and error schemas; execution markings; and artifact behavior. Help and
  reserved/undelivered groups are excluded because they have no dispatchable descriptor.

- **Every registered command ships `--schema`.** Its closed result contains `input`, `success`,
  optional `verdict`, and `error`. `verdict` is present only for commands that can return exit 1;
  `error` includes the applicable bADR-0015 usage/internal and stage-aware refusal variants. The
  exact same models feed argv/structured binding, dispatch validation, manifest emission, and the
  conformance harness.

- **Structured params input ships with the first 2.x tracer.** `--params-json <json | ->` binds the
  descriptor's typed input model, with `-` reading stdin. It is mutually exclusive with individual
  argv fields; conflict is a usage error. Bare `--schema` takes precedence over all other arguments
  and emits without reading artifacts or executing the handler. Structured input cannot express
  fields the descriptor does not own.

- **The Command descriptor remains the only registration seam.** In addition to bADR-0015 fields,
  it owns artifact input/output roles and receipts, structured-params eligibility, and fixtures for
  success, verdict, every applicable refusal stage, usage, internal fault injection, schema,
  manifest, and stochastic reproduction. Parallel argument maps, command lists, error schemas, or
  manifest rows are prohibited.

- **Artifact output retains the safe bADR-0009 law.** Results always remain on stdout. `--out`
  writes the descriptor-declared primary artifact atomically and adds its path/size/content identity
  receipt to the success result; generated companion-artifact identities remain in the typed result.
  Input artifacts are never mutated, direct/symlink aliasing of input and output is a usage error,
  and failed invocations leave no partial authoritative output.

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
  agent-driven; the first tracer is the real consumer that justifies the adapters.
- **Hand-maintain a CLI manifest** (rejected) — recreates command-surface drift beside the descriptor
  authority.
- **One generic `artifact` group** (rejected) — erases the domain actions and authority boundaries
  agents need to choose a safe operation.

## Consequences

- The first 2.x tracer must register schema/model/template/experiment/evidence commands only as they
  become executable; the manifest exposes exactly the delivered subset.
- CLI schema and conformance fixtures cover success, optional Verdict, all applicable Refusal
  stages, usage/internal failures, structured input, artifacts, and reproduction.
- Existing 1.x command implementation/issues must be rewritten around the new descriptors rather
  than aliased indefinitely.
- Calibration and approval delivery require vertical command decisions but their noun ownership is
  protected now.
- Issue/README/help surfaces must use the same nouns and may not advertise reserved commands as
  available.

## References

- PRD #534 — Standard Schema 2.0 language, runtime, and evidence architecture.
- bADR-0007/0009/0011 — 1.x taxonomy, structured I/O, and descriptor contracts superseded for the
  2.x surface only.
- bADR-0012 — authored authority domains.
- bADR-0015 — invocation outcomes and diagnostic locations.
- bADR-0018 — metrics/evidence ownership.
- bADR-0019 — clean break and limited migration.
