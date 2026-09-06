# Schema 1 input retirement

Issue: [#868](https://github.com/aigengame/godot-agent/issues/868), stage S1b.
Decision: [bADR-0028](../../badr/0028-current-language-refactor-and-pre-1.0-retirement.md).
Inventory baseline: `2b370cbdad33d987038ac42fa866eb27210af877`.

The toolkit retires its Schema 1 source stack, `model migrate`, `tooling.migration`,
converter defaults and migration-only contracts. Current authors enter through ordinary Model
Source admission, build and Experiment execution. No general converter or compatibility adapter
remains, and no named unresolved source requires a temporary offline converter.

## Bounded source inventory and disposition

The inventory inspected all 113 tracked `.json` blobs across the full repository at the fixed
baseline, parsed their root objects, and examined `schema_version` values beginning with `1.`.
Every tracked JSON blob parsed. Two roots matched: one authored-input fixture and one generated
semantic catalog. Searching text mentions additionally found current Model/Experiment and authority
resources that use independent package versions; those strings do not make them Schema 1 sources.
The inventory also classified test-constructed inputs and the separately owned Panda stack.

| Observed input or record | Disposition | Resulting current-source validation |
| --- | --- | --- |
| `tests/fixtures/minimal_design.json`: `schema_version: "1.0.0"`, `meta.name: "smallest"`, no numeric declarations | Deliberately deprecate and remove the fixture with the retired contract. It represents the old empty-source admission minimum, not a game design to recover. | Not applicable: no current Model is produced, no numeric policy is invented, and no semantic conversion or equivalence is claimed. |
| `tests/goldens/semantic_catalog.json` and the other old generated structural/catalog goldens | Retire with their generator and historical expectation. The catalog is generated rule metadata, not authored Model Source. | Not applicable: generated old output is not converted into new authored authority. |
| Schema 1 documents constructed inside retired tests | Retire their old-only expectation and test IDs; route still-required input robustness to current admission tests below. | No conversion claim. Current robustness must pass on current Model/authority inputs. |
| Current five maintained Models and seven Experiments under `examples/schema2/` | Retain authored semantics and refresh exact generated authority/binding facts where needed after removing the package. | Validate through normal current build/run and CLI/HTTP gates; this is current-path regression evidence, not evidence that the old fixture was migrated. |
| Panda's embedded balancing implementation and adapter | Remain owned by [#517](https://github.com/aigengame/godot-agent/issues/517). No toolkit Schema 1 consumer was established by that distinct implementation. | No Panda cutover, numeric parity or current-source equivalence is claimed here. |

The fixture's exact baseline SHA-256 is
`91b41be8fbcaa580c778e0c4835bedc6dc2e87452a79fe645917b3cfd5950cf5`; its
[historical bytes](https://github.com/aigengame/godot-agent/blob/2b370cbdad33d987038ac42fa866eb27210af877/libs/gda-balancing/tests/fixtures/minimal_design.json)
remain recoverable from Git. This bounded search does not prove that no untracked, non-JSON,
external or user-held source exists. None was named as an unresolved supported source. Hypothetical
consumers cannot postpone this deletion; a later concrete recovery need requires its own explicit
source disposition and does not silently restore production compatibility.

## Removed path and retained owners

- Remove the CLI registration, input/result/detail models and application conversion flow; there
  is no `model migrate` discovery, schema, help, invocation or structured-parameter alternative.
- Remove the Schema 1 validator/model/funnel stack and its old-only resource access. Retain generic
  bounded byte reading and current Model/authority admission under their existing owners.
- Remove the `tooling.migration` manifest/vector members and root descriptor; delete converter,
  migration report/refusal-report schemas, diagnostics, defaults and related exports. Reseal the
  declared graph and regenerate affected current artifacts together. No old identity labels
  changed bytes as unchanged.
- Remove the `migration` Refusal stage and `migration_report` detail. The remaining seven stages
  retain the same typed outcome and diagnostic responsibilities; evaluation/approval are not
  removed merely because some later features are deferred.
- Retire historical migration and old-input test IDs with their contracts. Keep current admission,
  atomic publication, exact identity and negative-path coverage. A smaller test count alone is not
  preservation evidence.

Historical bADRs, dated delivery descriptions, captured requirement text and disposable probes
remain historical records. They are not packaged authority, current CLI discovery, executable
conversion support, or a reason to restore a removed namespace. The rest of the current-language
refactor remains open, including package version-selection and redundant execution-binding removal.

## Coverage routing and acceptance evidence

| Retained behavior | Current validation owner |
| --- | --- |
| Bounded byte ingress and malformed source parsing | Current Model CLI source-size and wire-decode cases; Infrastructure byte-input tests |
| Duplicate keys and canonical authority transport | Current authority loader tests and independent bootstrap consumer |
| Report-all ordering, diagnostic caps and truncation | Model static-admission and bootstrap-resource cases |
| Type/semantic rejection and exact content integrity | Current Model/authority admission plus reidentified-tamper and independent-consumer cases |
| Framed atomic publication, direct/symlink/source-disappearance aliases and recovery | Current Model build/publication tests |
| Normal public execution and installed resources | Maintained Models/Experiments, CLI/HTTP parity, manifest/schema/help, wheel and inventory checks |

Current-path robustness checks during retirement exposed two internal-error paths: a duplicate
JSON key containing an unpaired surrogate, and nesting that exceeds the decoder/canonicalizer
capacity. Current file admission must report typed parse refusal for both without publication;
excessive nesting at the in-memory entrypoint follows the same refusal boundary.
The same check also exposed an Interface projection mismatch:
Model parse reports the root Artifact location as the empty JSON Pointer, while its envelope schema
required a slash. The descriptor projection must accept the exact empty string or a slash-prefixed
pointer; a bare newline must not pass as an empty pointer. These are retained input/diagnostic
contracts repaired in the active path, not reasons to preserve the old funnel. Their discriminating
negative cases and outcome results belong to the issue's reviewed validation receipt.

The issue PR must record actual results at its reviewed head, including retained outcomes,
retired IDs, independent-consumer checks and any skips. This record states source disposition and
validation ownership; it does not predeclare every test passed. A valid current example is not a
substitute for the negative, resource and integrity cases above. #868 cannot close while a named
source, temporary offline converter, dangling current contract or required validation is unfinished.

## Rollback

Revert this coherent issue slice on the development branch, restoring code, packaged authority,
current example bindings and affected test inventories from one known revision together. Do not
mix a restored converter with the contracted authority graph, reuse old identities for changed
bytes, or relabel historical output as current Evidence. A rollback reopens the retirement issue;
it does not reverse the accepted deletion endpoint or promise historical support. Process-local
sessions using replaced implementation are invalidated through their established lifecycle.

Panda rollback and eventual embedded-stack removal remain #517's responsibility. No source
conversion, telemetry migration, save recovery or formal-release commitment is introduced here.
