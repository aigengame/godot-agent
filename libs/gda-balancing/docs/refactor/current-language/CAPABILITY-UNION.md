# Current package capability union

Issue: [#869](https://github.com/aigengame/godot-agent/issues/869), stage S2.
Baseline: `0ada66475c7cae4af8cb77a6e93a1d707fc62193`.
Decision and sequencing: [bADR-0028](../../badr/0028-current-language-refactor-and-pre-1.0-retirement.md)
and [PLAN.md](PLAN.md). This receipt records the bounded capability-union slice; the overall
refactor remains open.

## Delivered content and deletion

After Schema 1 retirement, the packaged graph converges on 13 namespaces and 13 current releases.
`game.build@2.0.0` owns reward replacement and contribution, including the six Build nominal types;
`game.effect@2.0.0` owns all five periodic lifecycle Operations and contribution. Their complete
declared capabilities, types, dependencies and Operations remain under their existing package
owners. The current Quantity definition supplies the full nine-Operation union.

The slice deletes these seven old manifest/conformance-vector pairs:
`core.quantity@2.1.0`, `game.build@1.0.0`, `game.check@1.0.1`, `game.combat@2.1.0`,
`game.effect@1.0.0`, `game.generation@1.0.0`, and `game.resource@1.0.1`.
It also deletes the overlapping old full-domain literal profile `quantity.dimensionless-int64`. The current
`quantity.dimensionless-int64-v2-2` and distinct
`quantity.positive-dimensionless-int64-v2-2` profiles remain; a positive floor-division denominator
is a real input-domain constraint.

After coordinate normalization, 64 vector definitions were exact duplicates apart from their own
`id`. They are deleted, their references are redirected to the matching surviving case, and the
declared graph is resealed. The [removed-to-survivor map](evidence/current-union/vector-retirement.json)
records every retired ID. No differing expected result, negative case, policy, resource boundary or
nominal contract is discarded as a duplicate. The contracted graph contains 313 vector definitions,
28 Operation definitions and 34 Model-program cases. Of those vectors, 25 are `operation-execution`
cases rooted at five Operation coordinates; that count does not establish execution coverage of
all 28 definitions.

Kernel bytes are unchanged from the baseline. The union adds no compiler/evaluator genre dispatch,
host fallback or compatibility adapter. Version-coordinate fields and selectors still exist until
#870–#872. Whole-LDB/Build-receipt execution bindings still require dependency closure #874 followed
by their mandatory deletion in #875.

## Preserved inputs and public composition

The original five maintained Models and seven Experiments retain their authored scenarios,
assignments and targets while their exact authority/build/runtime bindings are deliberately
refreshed. A local before/after comparison covered all 26 Metric samples across those Experiments:
metric/scenario keys, values, target status, dimensions, units/windows, source/provenance,
member/replication identity and logical time remained equal. This is semantic observation parity,
not equality of the changed artifact identities.

The new [progression-derived periodic Effect](../../../examples/schema2/progression-periodic-effect/README.md)
adds one maintained Model and Experiment. Ordinary Model Formula bindings derive `5 × 17 = 85`;
the periodic lifecycle leaves health 70 after two ticks and expiry. Changing only level to 4 and
its terminal target derives 68 and leaves health 36. The Experiment never assigns the derived
threshold. The public test compares CLI artifacts with execution through a real local HTTP service
for both cases. This bounded witness does not close a genre row or activate deferred #542–#544.

## Verification boundary

The local contracted-graph receipt identifies LDB
`sha256:cddf6f50b5ba759b42c70918a0db5f22674ab711a6ff2e0d153bda45be458aa6`.
Production and independent admission agree, and all 25 declared Operation-execution vectors match
their expected observations through both consumers. Kernel byte equality and the retired-coordinate
scan pass. All six Models and eight Experiments execute against the contracted graph; the original
26 Metric samples preserve the observation parity above. An independently installed wheel loads
all 28 authority JSON resources with source-byte equality and executes the new composed example
without importing the checkout. The issue PR owns the exact reviewed-head CI status and final
acceptance; these bounded checks do not substitute for that required matrix.

The [packaged authority](../../../src/gda_balancing/schema2/authorities/language-bundle.json) owns
the current graph. Permanent verification belongs to the
[capability/dependency tests](../../../tests/test_schema2_bootstrap_language.py),
[dual-compiler Model cases](../../../tests/test_schema2_model_lowerer_conformance.py),
[two-consumer Operation-vector gate](../../../tests/test_schema2_experiment_cli.py), and
[public composed-path test](../../../tests/test_current_package_composition.py).
The PR's exact-head validation receipt must distinguish these checks, remaining failures or skips,
and final CI; neither smaller counts nor this document can satisfy an unfinished gate.

## Rollback

Revert the coherent #869 issue commit on the development branch: packaged authorities, generated
bindings/oracles, authored source bindings, tests and examples move together to the same known
revision. Do not mix the old graph with current receipts or restore historical lookup through a
fallback. A rollback reopens this slice and preserves the accepted endpoint: complete current
capabilities followed by actual selector and redundant-binding deletion. Existing process/session
lifecycle rules continue to govern admitted in-flight work.
