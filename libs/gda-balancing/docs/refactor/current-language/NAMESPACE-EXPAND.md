# Current namespace resolution: expand and handoff

Issue: [#870](https://github.com/aigengame/godot-agent/issues/870), stage S3-expand.
Common base: `ef0eba2d89c2487979ea7fa785172b3129958c38`, after #869 integration.
The issue branch is `codex/gda-balancing-870-current-namespace-resolution`; its target is
`codex/gda-balancing-refactor-delete-dev`. The [implementation workflow](IMPLEMENTATION.md)
governs review and integration. The issue PR records the validated and integrated commits;
this document does not assert completion or contain a self-referential integration SHA.

The sequence is #870 expand → [#871 migrate](https://github.com/aigengame/godot-agent/issues/871)
→ [#872 contract](https://github.com/aigengame/godot-agent/issues/872). Expand is an
integration-only witness pending production consumer migration. Existing public wire contracts
and machine admission remain unchanged at this stage. Neither intermediate issue merges
independently into `main`; #872 owns mandatory deletion and the final coherent public contract.

## One authored graph

The existing attached, admitted package graph remains the sole authored authority.
`AdmittedAuthorityContext.current_namespace_packages()` temporarily projects its exact current
manifests into `CurrentPackage` values. `NamespaceSelection` and `resolve_current_namespaces`
in [graph.py](../../../src/gda_balancing/domain/authority/graph.py) provide namespace selection
from that derived view. There is no separately editable graph, package registry or release solver.

Ownership is `(namespace, authority path, definition key)`. It is derived from each attached
package's owned definitions and the admitted ownership contract, never reconstructed from the
flattened `language` collections. Equal-shaped definitions in different namespaces retain
distinct nominal identities; duplicate namespace ownership is refused before building a lookup.

Selection follows required dependencies transitively and binds capabilities only within that
selected closure. Missing dependencies, required cycles, duplicate dependency declarations, and
missing or multiple selected providers must not disappear through deduplication or global provider
lookup. Optional references remain validated but are not automatically selected. Namespace and
dependency enumeration is deterministic; authored Operation body order remains semantic.
Existing graph admission, content verification and resource bounds remain in force.

## Temporary surfaces and deletion owners

| Surface | #871 handoff | Mandatory #872 endpoint |
| --- | --- | --- |
| `AdmittedAuthorityContext.current_namespace_packages()` and `graph.py::project_current_namespace_packages()` bridge from exact manifests | Feed migrating consumers from the one current graph | Remove the transition projection; derive namespace selection directly from the contracted authored graph |
| Separate dependency traversals in `model/_resolution.py::_resolution_relations` and `model/_lowering.py::_package_lock` | Replace both with the common namespace selection result | Delete the old coordinate traversal and conflicting-release branches |
| Exact package catalog selection and coordinate schema projections in `authority/package_catalog.py` and `authority/package_projection.py` | Migrate catalog consumers and their public contracts together | Remove historical selectors and obsolete coordinate fields and validators |
| Version-bearing requirements, imports, dependency references, nominal/Operation references and generated Lock projections | Migrate their current producers and consumers as one traced set | Delete obsolete package-version fields, bridges and fallback forms from code, contracts, sources and tests |

These are transition obligations, not a permanent compatibility policy. Any additional bridge
introduced during #871 must be added to its handoff inventory and deleted by #872. Namespace
ownership, nominal distinction and dependency/capability closure survive contraction. Unrelated
Schema, Template or extension metadata must be assessed by its own meaning rather than a blanket
deletion of every member named `version`.

## Validation and handoff receipt

Before #870 closes, its PR must identify the common base, reviewed expand commit, integration
commit consumed by #871, validation commands and results, and any unresolved scope. The namespace
witness must cover ordering, transitive closure, missing/cyclic/duplicate ownership, selected
capability failures and nominal distinction. Existing public Model, Experiment, CLI/HTTP and
packaged-resource checks must remain green. A test of the derived view alone does not establish
production consumer migration or satisfy the parent version-deletion acceptance criteria.

#871 receives this temporary-surface inventory and the exact integrated expand commit. #872 must
prove that every transition form is removed and that current public paths use the contracted
graph. Execution dependency closure #874 and mandatory broad-binding deletion #875 retain their
separate acceptance criteria; namespace expansion cannot close either obligation.

## Rollback

Revert the coherent #870 issue change on the development branch, including its derived view,
projection, witness tests and documentation. The common base above preserves the completed #869
capability union and its existing public contract. If #871 or #872 already depends on this change,
restore those dependent slices together to a coherent reviewed boundary. Do not combine mismatched
graph, source, contract or evidence revisions, or add a historical fallback to conceal the mismatch.
A rollback reopens the affected slice while preserving the accepted deletion endpoint.
