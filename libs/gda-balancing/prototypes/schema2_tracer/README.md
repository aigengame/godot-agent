# Standard Schema 2.0 throwaway tracer

This directory is a disposable architecture probe for PRD #534 and bADR-0012…0022. It is not
production code, a supported `gda-balancing` surface, a conforming Language Definition Bundle, or
evidence that any open row in `docs/standard-schema-2.0/genre-coverage.md` is closed. Delete the
prototype after its design feedback is incorporated.

No code under `src/gda_balancing/` or the 1.x test suite is imported or changed. The prototype uses
only the Python standard library and keeps every file below this directory.

## Question and scope

The probe asks whether one narrow RPG scenario can cross the proposed authority and execution
boundaries, and where the proposed authority contract still falls back to host-language semantics:

`canonical LDB + Model Source Package → AST → Typed HIR → content-addressed RIR → atomic runtime → Metrics → Evaluation Run → Evidence assertions`

It exercises a partial layer traversal:

- a bootstrap-parsed LDB that selects operation primitives and evaluates a limited set of admission
  premises for import resolution, exact types/effects, package binding, subscriptions, and
  lowering;
- a two-module Model Source Package with explicit imports and typed stat composition;
- separate `model build` and `experiment run` processes joined only by identities in a local,
  prototype-only content-addressed store;
- two dynamic enemy candidates with stable target selection, mana reservation/commit, two named
  SHA-256 counter streams, staged damage/mitigation/shield/health/defeat, and a model-authored
  reactive Signal subscription;
- `input → transition → observation` event order, buffered writes, Metric and Evaluation Run
  structures, and emitted `well_typed`/`resolved`/`evaluable` assertions whose normative validity
  remains unproven; and
- canonical success output plus stage-aware static and runtime refusal output.

The host Python implementation still defines `exact.add`, every RPG runtime primitive, and the
SHA-256 counter RNG algorithm. The LDB does not define or independently validate those semantics;
it names primitives implemented by the host and drives only the limited admission-rule ontology
implemented by the bootstrap interpreter. Consequently this prototype is not a non-fixture-specific
evaluator, and neither LDB authority nor an executable Standard Schema 2.0 semantic law has been
validated. This is an observed design gap, not an implementation detail to hide.

It deliberately does not claim full grammar/rule coverage, package conformance, interruption,
immunity, stacking, resource-insufficient behavior, every tracer matrix row, or a production
artifact transport. A byte-identical replay check is part of the `e2e.py` target, but even a passing
check cannot justify a `reproducible` Evidence assertion without an independent replay-comparison
artifact.

## One-command run

From this directory:

```bash
python3 e2e.py
```

The script runs real subprocesses and uses a fresh temporary store. It checks all three public
prototype descriptors and their `--schema` projections, build/store/run, byte-identical repetition,
one semantic-normal-form identity case, typed gameplay observations, an interpreted-rule mutation,
compile and malformed-invocation refusals, Runtime-profile budget and named-stream enforcement,
invocation-level publication under deterministic store faults, and event-level rollback on a
scheduler-cursor refusal. These are prototype checks, not evidence that the corresponding 2.0
contracts are complete or independently conformant.

## Public prototype commands

- `python3 cli.py model build --params-json <json | ->`
- `python3 cli.py experiment run --params-json <json | ->`
- `python3 cli.py manifest [--params-json <json | ->]`

Each command also accepts bare `--schema`. The live descriptor registry is the only prototype CLI
registry and drives the checked structured-parameter admission. Success/refusal output is one
canonical JSON document on stdout; usage/internal output is one canonical JSON document on stderr,
using exits `0`, `2`, `3`, and `4` respectively. These are local probe results, not a normative 2.x
CLI contract; see [`DOGFOODING.md`](DOGFOODING.md). No command is installed as the real
`gda-balancing` executable.

`model build` persists the LDB, Package Lock, RIR, and Capability manifest.
`experiment run` accepts an Experiment Specification whose exact RIR identity is already bound,
reloads RIR, lock, and LDB from the store, and executes the stored RIR. The current Package Lock and
Capability manifest are minimal skeletons: they do not prove complete dependency-graph,
capability, type, or conversion closure. Store filenames are SHA-256 identities and reads recheck
the content identity. A committed index is the prototype's atomic visibility point for one batch;
the local mechanism does not define production crash recovery, concurrency, retention, or
transport. See [`DOGFOODING.md`](DOGFOODING.md).

## Files

- `bundle.py` — closed bootstrap shape and structured-premise interpreter.
- `compiler.py` — wire parse, AST, resolution/type/effect checks, Typed HIR, lock, and RIR lowering.
- `runtime.py` — RIR-only sequential atomic runtime and evidence artifacts.
- `store.py` — prototype-only content-addressed local store.
- `cli.py` — descriptor registry and thin structured CLI.
- `e2e.py` — subprocess vertical-slice and refusal checks.
- `fixtures/` — LDB, two-module RPG source, experiments, and static-negative source.
- `DOGFOODING.md` — observed specification pressure and proposed changes.

## Interpretation

The only defensible conclusion is local: the proposed layers can be connected for one exact-integer
RPG tracer, and the connection exposes concrete contract gaps. Complete Standard Schema 2.0
feasibility, a non-fixture-specific evaluator, LDB semantic authority, package/capability closure,
and normative Evidence issuance remain unvalidated. The second-iteration executable checks can
confirm local behavior, but cannot close these specification questions without independent
interpreters, closed wire contracts, and normative vectors.
