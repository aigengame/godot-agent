# Formula Runtime conformance seam

This record defines the implementation and validation scope of [#612](https://github.com/aigengame/godot-agent/issues/612),
the existing prerequisite of #876. The development baseline is
`aa94ec79d63b0595e5d6af8bce6180aba9d5b397`, which integrates #875 through PR #906.
The issue and its pull request own live acceptance status. This plan does not claim
that the implementation or its verification is complete.

## Problem and boundary

At the development baseline, the shipped `_evaluate_value_program_vector`
function is called only by tests.
It implements its own charge, cache key, numeric refusal and result projection.
Normal initialization, Event and observation Formula execution uses a different
program loop. Sharing the instruction interpreter alone does not prove that the
vectors exercise the execution path used by an Experiment.

A baseline probe replaced the normal lifecycle evaluator with an unconditional
failure. Both vector consumers still matched all ten shipped value-program
expectations. This establishes a conformance-evidence gap; it does not establish
that a maintained public Experiment produces an incorrect result.

Extract one identified program evaluation inside the existing Runtime execution
module. The existing coordinator keeps graph reachability, operand resolution,
lifecycle frame construction and target writes. The shared function owns:

- selected Kernel instruction dispatch and numeric semantics;
- the declared `resource_bounds.max_steps` charge before a cache lookup;
- the program, site, frame, operands and numeric contract in the cache key;
- the admitted value and updated consumed steps; and
- precise program, evaluation-site, frame and charge information on a fault.

The input uses the existing compiled program and explicit selected contracts.
There is no new public IR, wire artifact, registry, implicit authority lookup or
test-only Runtime branch. A separate Formula module is unnecessary for this cut:
moving the shared Event helpers would add relocation without changing ownership.

Inline Event Formula instructions retain their existing per-instruction total,
Event and Operation counters and exact failure index. Extracting the program
function does not replace this ledger with a bulk charge. The committed prefix
and rollback boundary remain unchanged.

## Confirmed fault-charge correction

Public runs with admitted Runtime profile node limits of 5 and 20 expose a
pre-existing failure in the Event and observation Formula fault paths. Both the
development baseline and the initial extraction return an internal error when
publication rejects the prepared terminal audit. The call assigning
`total_steps = _evaluate_initialization_programs(...)` never receives a result
when the function raises, so the callers report their pre-call counter. The
independent artifact validator correctly requires the attempted Formula charge.

The shared fault now carries consumed steps. Both callers must retain that value
before constructing the refusal audit. This repairs conformance to the existing
charge and audit laws; it does not weaken the validator or change the language,
resource policy or public refusal schema. Previously valid artifacts retain their
behavior. The affected runs now publish the required typed refusal instead of an
internal publication failure. Permanent public tests cover both cases.

## Consumers and refusal scope

Normal nonempty initialization, Event and observation programs call the shared
function. A test-side adapter translates each vector into the same request and
projects the returned value or fault. It may orchestrate the requested repeated
evaluations, but it does not calculate charges, construct a second cache key or
interpret generic numeric exceptions. Delete the shipped vector-only entry point.

Keep the reference vector consumer and independent artifact replay independently
implemented. Each vector consumer compares its observation with the shipped
expectation; agreement between the consumers alone is insufficient.

The Kernel requires a positive divisor domain, and current public admission
enforces that precondition. Preserve the negative division vectors through a
narrow internal domain failure from the shared instruction path. Do not convert
arbitrary `ValueError` exceptions into `invalid-domain`, add a selected reason or
expand the public refusal protocol for an input public admission already rejects.
Malformed, unknown and context-incompatible direct requests must fail without
cache insertion or a partially published result. This does not require a second
general-purpose program admission implementation.

## Verification and implementation order

1. Capture the post-#875 public artifact baseline and a discriminating failure
   showing that the existing vectors do not depend on normal Formula evaluation.
2. Extract the charged single-program function and connect the three lifecycle
   callers while preserving the Event ledger and existing public fault projection.
3. Move vector adaptation under tests and delete the production vector entry point.
   Retain all ten expectations and the separately implemented reference consumer.
4. Exercise real public paths with nonempty shared-function calls in each lifecycle.
   Check charge before cache hits, a declared charge larger than instruction count,
   different Snapshot frames with equal operands, numeric/resource boundaries,
   exact fault provenance and atomic refusal. A spy on an empty coordinator is not
   evidence that a program was evaluated.
5. Compare public artifacts, verify independent consumer imports and required test
   inventory, and run the package checks and full CI. Review Standards, Spec and
   domain architecture independently before integration into dev.

The byte comparison preserves Kernel/LDB identities, RIR meaning, admitted Formula
semantics and previously valid semantic execution artifacts. The two confirmed
fault-charge failures above require a separate before/after result, since the
baseline could not publish a valid refusal artifact. Under the
[execution identity contract](EXECUTION-IDENTITY.md), source changes must update
the evaluator implementation fingerprint. Producer manifests and publication
records that identify their bytes therefore change truthfully. Enumerate those
differences in the validation evidence; do not freeze fingerprints or exclude
unrelated result differences from comparison.

## Rollback and completion

Rollback restores code, test adapters and this issue's documentation together to
the development baseline. No compatibility entry point or alternate evaluator
remains for rollback. Verify the reverse patch and execute the restored public
baseline before closing #612.

Completion requires the shared production path, deletion of the vector-only
function, independent expectation checks, preserved public behavior and complete
review/CI evidence. It does not delete the value alias or maximum primitive: #876
owns those separately adopted language and resource-contract changes.

## Recorded implementation evidence

The production source is confined to `domain/runtime/execution.py`. The tested
source has SHA-256 `3084f48a17a7cd5f00bfce8b53ec059469998d0b4bc1121f2db7a8c7d20d7050`.
An isolated before/after capture ran 26 actual CLI subprocess calls: six maintained
Model builds, eight Experiment checks and runs, and two additional numeric-refusal
build/run pairs. All 28 authority files, eight Model artifact sets, eight successful
behavior artifact sets, nine resolved Runtime profiles and the inline Formula
terminal audit stayed byte-identical. Fresh task-owned stores and fixed paths and
invocation keys prevented publication reuse from hiding execution changes.

The complete changed-file set was nine evaluator manifests, nine dependent
publication manifests and nine receipt envelopes. The evaluator build identity
changed from `8c64e8e9d055a7a55fa463656dcf8611b3b8852ee25de9467c212f7935510a70`
to `6bd51724cf80f41f8c9600c68cef10b5d029b3307fc9c222dc4d7f66c556b30b`.
Every changed JSON leaf was an evaluator build identity, its manifest content
identity or a dependent publication/receipt identity; no general normalization was
used. The source fingerprint was independently reconstructed from Domain files.

Separate public build/check/run probes confirmed the resource-refusal correction:
Event limit 5 changed from an invalid audit with 3 steps and exit 4 to a valid
audit with 6 steps and exit 2. Observation limit 20 changed from an invalid audit
with 18 steps and exit 4 to a valid audit with 21 steps and exit 2. Both preserved
the exact committed prefix and refusal site. These are corrected failures, not
part of the previously valid byte-equivalence claim.

Permanent reproduction is in `tests/test_formula_runtime_seam.py`,
`tests/test_public_formula_runtime_seam.py`, and
`test_package_value_program_vectors_execute_in_two_consumers` in
`tests/test_schema2_experiment_cli.py`. Together they pass 24 collected cases;
the vector case checks all ten shipped expectations independently in both
consumers, with the production consumer evaluated in each lifecycle phase.
The public cache-hit case explicitly instruments prewarming; it does not claim
a naturally occurring hit. These tests use real in-process CLI dispatch, while
the byte capture above used subprocesses. Neither establishes wheel or Godot
validation.

Inventory closure accounts for all 1,741 current tests in nine disjoint shards,
including all 849 required baseline test IDs and 313 current package vectors.
Ruff, Pyright and sealed-LDB checks pass. These local results do not replace the
full CI and independent review required by the issue.
