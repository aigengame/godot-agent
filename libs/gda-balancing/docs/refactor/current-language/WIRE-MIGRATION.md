# Current namespace wire migration

Issue [#871](https://github.com/aigengame/godot-agent/issues/871) starts from
`08fd871aa9ab63a4410d43e86002122941e2d093`, the reviewed #870 integration on
`codex/gda-balancing-refactor-delete-dev`. Its branch is
`codex/gda-balancing-871-current-wire-migration`. This record fixes implementation
choices under [bADR-0028](../../badr/0028-current-language-refactor-and-pre-1.0-retirement.md);
it does not assert that migration or the final #872 contract gate has passed.
The issue PR owns validation, intermediate failures and the actual integration receipt.

## Native forms and deletion boundary

| Surface | Current form after migration |
| --- | --- |
| Package required/optional dependencies, Source requirements, Lock root requirements | Lists of namespace strings |
| Imports | `{alias, package, symbol}` |
| Nominal Type identities/references and Operation references | `{package, id}` |
| Package descriptors and selected package rows | Namespace `id` plus meaningful content, semantic and resource fields |
| Model manifest | `id` and `entry_module` |
| Package and Template selection | Current namespace or Template id; no version argument |

Remove the old fields and their validators, schema properties, writers and readers
together. There is no `{id}` wrapper for a string requirement, default version,
empty coordinate sentinel, compatibility reader or execution-time reconstruction.
Normalize the old nominal `type_identity.symbol` member to `id`: it names the same
type declaration that Runtime already converts to a nominal reference. Source
imports still use `symbol`; Model Symbol names and targets retain their meaning.
Delete `requirement_package_member`, the requirement/import version members and
their routing equivalences. Existing relation terms with `path: []` read the
namespace directly and retain its `/package_requirements/<index>` pointer.
Delete the inert `dependency_selection: exact-version` and
`package_conflict: single-version-per-id` profile fields and the obsolete
single-version judgment. Missing-package diagnostics describe the namespace.

Model and Experiment own-version labels, Runtime profile and evidence claim-kind
definition versions, and Replay policy versions have no independent execution
meaning in the current readers. Remove these labels, required schema members and
provenance echoes in this migration. Template version is an active historical
selector and is removed with its CLI argument and provenance echo. These deletions
do not wait for #875. Actual policy bodies, checks, comparators and their meaningful
content identities remain available to consumers.

Retain distribution version, Schema-major/source/artifact format markers, Metric
Dataset format version, and actual Kernel Runtime, invocation, component, Template
primitive and Formula grammar contract markers. A digit or a field named `version`
alone does not establish historical selection. Preserve arbitrary authored Record
fields, literal data and extension payloads with that name, and preserve ordered
Operation bodies. Opaque declaration IDs containing `@1` or `-v1` are not renamed
mechanically. Approval has no current production reader or packaged schema to port;
do not invent one or activate deferred governance.

## Ownership and closure

The attached admitted package graph is the sole authored source. Package-owned
Operations, Components, Conversions and nominal Types have identity
`(namespace, authority path, definition key)`. Their namespace comes from the
containing package closure. Removing version from a flattened `(id, version)`
index must not accidentally impose global bare-id uniqueness. Do not add a second
authored owner field or registry. Two namespaces may own the same local declaration
id; each qualified Operation reference must execute its own body. Duplicate
definitions within one owner refuse.

Constructors, structured-operation vocabulary and capability contract identifiers
retain their existing global meanings. Each required capability has one provider
within the selected closure. Required dependencies close transitively; optional
references must exist but are not automatically selected. Required cycles, duplicate
dependency edges and duplicate Source requirements refuse. Internal root-set
deduplication is not a public acceptance policy.

Source resolution needs facts about an incomplete selection before it can issue
the machine-defined missing-package or capability diagnostic. Project required
closure once, retaining raw roots and every selected provider row. The Model
judgment chain consumes those facts and owns public diagnostic stages and pointers.
After its judgments pass, finalize that same projection without traversing again;
`CheckedModel` carries the required `NamespaceSelection` into Lock lowering.
The strict graph convenience API composes projection and finalization. It must not
preempt a Source judgment with a host exception, add a validation-mode flag, or
leave the old Lock traversal as an optional fallback.

Kernel fixed nominal contracts also own namespaces. Derive those namespaces from
`runtime_program.fixed_value_contracts[*].type` and require them to be disjoint
from LDB package owners under the existing identifier-uniqueness law. A baseline
[counterexample](evidence/namespace-ownership/README.md) admits both an empty
`kernel` package and one exporting `kernel.Boolean`. Removing reference versions
would make the latter collide with the Kernel type. The refusal must concern
namespace ownership, including an empty package, rather than a hardcoded type-name
blacklist. This baseline observation is not proof of the repaired behavior.

## Implementation and verification order

1. Change machine contracts and the 26 package/vector resource filenames as one
   foundation. Keep the 13 namespace directories and exactly 28 authority JSON
   resources, including the Kernel and LDB root. Update the existing rebuild tool;
   one owner writes authority bytes and derived identities.
2. Migrate production and independent admission, resource lookup, namespace selection
   and shared reference keys to that contract. Kernel pins change with the actual
   Kernel content; a component-contract pin changes only if that contract changes.
   Use a fresh process after authority changes because admitted contexts are cached.
3. Migrate Model/Formula, Runtime/Experiment/Replay/session, Template/CLI and HTTP
   consumers through the same native forms. Reuse the namespace resolver rather
   than retaining separate Source, Lock or Template dependency traversals. Sequence
   shared foundations before dependent work; independent work uses isolated worktrees
   in batches of at most five workers.
4. Regenerate current independent conformance expectations and seal the one graph.
   Rebuild all six maintained Models, rebind all eight Experiments and port generated
   Template inputs. Negative cases must reach their intended ownership, type or
   dependency boundary, not merely fail on an accidentally retained version field.
5. Prove production and independent admission, order invariance, reserved-owner and
   duplicate refusal, same-local-id Operation dispatch with different bodies,
   distinct nominal types, optional/required closure and capability cardinality.
   Preserve a real authored value named `version`. Run maintained public
   source → artifact → run, Replay, session and actual HTTP paths, plus installed-wheel
   resource and execution checks. Reconcile the existing inventory after explicit
   test/vector disposition; counts alone do not establish preservation.

Intermediate foundation revisions can fail while paired contracts and consumers
are being ported. Record those failures; a build-only adapter is not a complete
#871 handoff. Every remaining transition form must have an explicit #872 deletion
owner. Do not retain a form merely to leave work for that issue: #872 verifies the
complete contracted path and removes any actual residue. Neither slice merges
independently into main. Broader execution bindings retain their separate mandatory
#874 closure → #875 deletion sequence.

## Rollback

Restore code, machine contracts, authored inputs and derived evidence together to
the reviewed #870 integration above. If later slices depend on the migrated wire
form, roll them back to the same coherent boundary. Reopen affected acceptance
criteria and retain the mandatory deletion endpoint. Do not mix old consumers with
new artifacts or add a fallback to conceal that mismatch.
