# Current namespace contract and S3 deletion verification

Issue: [#872](https://github.com/aigengame/godot-agent/issues/872), stage S3-contract.
The starting development commit is `9873df54500a48f139f826847401e2fda7ba6f35`, the
#871 integration from [PR #897](https://github.com/aigengame/godot-agent/pull/897).
Its tree equals the independently reviewed `6ff286b76bedb227f57ff93448c2689baa35448c`.
The [implementation workflow](IMPLEMENTATION.md) still requires this issue's own
reviewed PR into dev. GitHub owns final acceptance and integration status.

The coupled #871 migration already removed the S3 transition mechanisms. This
contract slice verifies their actual absence, reconciles the delivery records and
defines the complete S3 rollback. It does not add a replacement selector, another
authoring graph or a compatibility reader merely to produce a new code change.

## Disposition of every expand surface

The four rows in [the expand inventory](NAMESPACE-EXPAND.md) have these endpoints:

| Former surface | Current implementation and deletion |
| --- | --- |
| Exact-coordinate to namespace bridge | `project_current_namespace_packages` and its `{id, version}` conversion and exact-version checks are deleted. `derive_current_namespace_packages` in [graph.py](../../../src/gda_balancing/domain/authority/graph.py) reads native namespace strings and definitions from the attached admitted graph. The context accessor retains that direct derivation, with no old-shape branch. |
| Separate Model resolution and Lock traversals | `project_required_namespace_closure` traverses once. Model judgments receive its unresolved Source facts; `admit_namespace_selection` finalizes them after those judgments. `CheckedModel.namespace_selection` is required. `_resolution_relations` consumes the projection and `_package_lock` consumes the selection; neither traverses a historical coordinate graph. |
| Exact catalog selection and coordinate schema projections | [package_catalog.py](../../../src/gda_balancing/domain/authority/package_catalog.py), [package_projection.py](../../../src/gda_balancing/domain/authority/package_projection.py) and their public inputs use the namespace id. SemVer selection, coordinate members and old conflict rules are deleted. The remaining namespace grammar helper does not parse versions or choose historical releases. |
| Version-bearing public requirements and references | Source/Lock roots and dependencies are namespace strings; imports use `{alias, package, symbol}`; Type/Operation references use `{package, id}`. Model, Template, Experiment and LDB policy own-version labels and Template version arguments are removed. Nominal definitions have no authored owner: their attached package or outer RIR row owns them. CLI, HTTP, Runtime and independent consumers use these same native forms. |

There is one current definition for each of 13 package namespaces, in 28 declared
JSON authority resources. All 20 nominal definitions have exactly `id`,
`constructor` and `definition`. Equal-shaped Types in different namespaces remain
distinct. Selection closes required dependencies and unique capability providers;
authored Operation body order remains semantic.

## Acceptance evidence

These are existing permanent witnesses, not a second acceptance registry. The
issue PR must record the final head and full required CI result. Inspection of a
field name or agreement between two consumers alone cannot close an AC.

| #872 AC | Required witness and current evidence |
| --- | --- |
| 1 — native public path | [public namespace tests](../../../tests/test_current_namespace_public.py), [Template CLI tests](../../../tests/test_schema2_template_cli.py) and [HTTP tests](../../../tests/test_http_service.py) exercise native selection, retired-input refusal and current execution. PR #897 also records six actual maintained builds and eight run/Replay/HTTP artifact comparisons. |
| 2 — actual deletion | The four dispositions above cover every named transition surface. Production inspection finds no internal SemVer reader, historical lookup, epoch/range solver or coordinate-restoring shim. Old-field negative tests remain intentional refusal obligations; they do not admit those fields. |
| 3 — ownership and closure | [namespace resolution tests](../../../tests/test_current_namespace_resolution.py) cover diamonds, required/optional edges and nominal ownership. [Model lowerer conformance](../../../tests/test_schema2_model_lowerer_conformance.py) covers recursive Record/List Types, production/reference artifact equality and mutual artifact admission. An unselected same-name nominal shadow cannot supply another namespace's values. |
| 4 — order and mutation discrimination | Namespace permutations preserve selection while authored body-order mutations remain observable. Missing/cyclic/duplicate ownership and the zero/one/two selected capability-provider matrix have declared refusals. [Model CLI tests](../../../tests/test_schema2_model_cli.py) prove one closure supplies both judgments and Lock, including invalid Source roots. All 34 Model vector verdicts and independent artifact comparisons remain required. |
| 5 — maintained consumers and conformance | [CI at the inherited exact tree](https://github.com/aigengame/godot-agent/actions/runs/34076861843) passed all eight required shards plus installed-wheel/subprocess smoke: 1,508 unique JUnit cases, 1,483 passed, 25 declared skips, no failures/errors. It includes all 313 active vector obligations and 27 smoke cases. Seven separately executed real Godot headless scripts passed 87 assertions; this is not rendered player acceptance. The #872 PR runs the full matrix again. |
| 6 — coherent completion and rollback | No transition form or duplicated authored current graph remains in the inspected implementation. Independent S3 review and the final PR checks remain required before issue closure. Whole-S3 rollback restores the checkpoint below, including code, authority, sources, tests and evidence. |

The inherited code, authority, maintained examples, tests and CI policy remain
unchanged in this contract record. Their Git tree identities make evidence reuse
checkable; the final PR distinguishes inherited evidence from new verification.
Use the existing `tools/ci.py` inventory, shard selection and outcome checks rather
than a new test selector or relaxed timeout. The two whole-module groups contain
exactly the former 428 cases, split into 98 composition and 330 interface cases;
all test definitions, fixtures, allowed skips and 480-second process bounds remain.

## Retained meanings and later mandatory deletion

Distribution versions, Schema/artifact format markers, actual Kernel Runtime,
invocation, component, Template primitive and Formula grammar contracts identify
their own protocols. The bounded periodic-Effect extension contract and authored
data fields named `version` or `package` do not select historical packages. Opaque
declaration ids also do not constitute a version solver. Do not delete these by
string matching or relabel them as S3 transition forms.

Whole-LDB/Build-receipt execution prerequisites and the broad evaluator provenance
binding still require #874 dependency closure followed by mandatory #875 deletion.
S3 completion cannot close those ACs, the non-RPG witness #878 or final refactor
acceptance #879. Incremental Runtime, simulation policy, authenticated claims,
main integration and formal release retain their separate scope and gates.

## Whole-S3 rollback

Restore `ef0eba2d89c2487979ea7fa785172b3129958c38` (#869, package subtree
`384ca743b917da316ac680be16937d34c80c2db2`) for a complete pre-S3 public baseline.
Revert dependent slices, then the #872 contract, #871 migration and #870 expansion
in reverse dependency order. Restore code, machine authority, authored examples,
tests and evidence together; intermediate revert states are not accepted endpoints.

`08fd871aa9ab63a4410d43e86002122941e2d093` in the #871 migration record is the
narrow boundary for undoing #871 while retaining #870's expand stage. It is not the
whole-S3 rollback endpoint. The #872 PR records a fresh archive-based restoration
check against the #869 Git blobs, sealed-authority verification and both existing
progression/periodic CLI-and-HTTP composition cases. That bounded check does not
claim a rerun of the entire historical suite.

Rollback reopens the affected acceptance criteria while retaining the accepted
deletion endpoint. Never combine old consumers with new artifacts or add fallback
reads to conceal a partial restore.
