"""Shared authority inputs and owner-preserving mutable test projections."""

from copy import deepcopy
from typing import Any, cast

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.authority.package_semantics import (
    package_runtime_semantic_closure,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from schema2_bootstrap_conformance_support import (
    _declared_identity_domain,
    _encoded,
    _identity_from_kernel,
)


def mutable_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Return an owned mutable copy of the admitted packaged authorities."""
    return packaged_authority_context().mutable_pair()


def reseal_authority_graph(kernel: dict[str, Any], graph: dict[str, Any]) -> None:
    """Reseal a finite authored test graph after an explicit fixture mutation."""
    packages = graph["packages"]
    vectors = graph["vector_sets"]
    root = graph["ldb_root"]
    package_ids = [package["id"] for package in packages]
    if (
        len(package_ids) != len(set(package_ids))
        or sorted(package_ids) != sorted(row["package_id"] for row in vectors)
        or sorted(package_ids)
        != sorted(row["id"] for row in root["package_descriptors"])
    ):
        raise ValueError("package, vector, and root membership do not close")

    def seal(value: dict[str, Any], **selector: str) -> None:
        domain = _declared_identity_domain(kernel, **selector)
        identity = _identity_from_kernel(kernel, domain, value) if domain else None
        if identity is None:
            raise ValueError("unsupported authored identity contract")
        value["content_identity"] = identity

    by_package = {row["package_id"]: row for row in vectors}
    meta = kernel["meta_format"]["package_release"]
    for package in packages:
        vector = by_package[package["id"]]
        seal(vector, collection="language_bundle.package_conformance_vector_sets")
        package["conformance_vectors"] = {
            "artifact_kind": vector["artifact_kind"],
            "byte_size": len(_encoded(vector)),
            "content_identity": vector["content_identity"],
        }
        closure = package_runtime_semantic_closure(package, kernel)
        package["semantic_identity"] = content_identity(
            meta["semantic_closure"]["domain"], cast(JsonValue, closure)
        )
        seal(package, collection="language_bundle.language.packages")
    order = kernel["meta_format"]["language_bundle"]["package_descriptor"][
        "canonical_order"
    ]
    packages.sort(key=lambda package: tuple(package[field] for field in order))
    graph["vector_sets"] = [by_package[package["id"]] for package in packages]
    root["kernel_identity"] = kernel["content_identity"]
    root["package_descriptors"] = [
        {
            "artifact_kind": package["artifact_kind"],
            "byte_size": len(_encoded(package)),
            "content_identity": package["content_identity"],
            "id": package["id"],
        }
        for package in packages
    ]
    seal(root, artifact="language-bundle")


def refresh_package_semantic_closures(
    language_bundle: LanguageBundleIndex, kernel: dict[str, Any]
) -> None:
    """Apply unambiguous flat fixture edits without inventing definition ownership.

    A flat index has no owner for a package-scoped definition. When several
    namespaces export the same local key, only unchanged attached definitions
    can be matched safely. Edit their attached closures and reidentify the graph
    directly when a test needs to change a colliding definition.
    """
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]
    unique_law = next(
        law
        for law in kernel["admission"]["laws"]
        if law["id"] == "kernel.identifiers.unique"
    )
    scoped = {
        contract["path"].removeprefix("language_bundle.")
        for contract in unique_law["arguments"]["collections"]
        if contract.get("scope") == "package"
    }

    def path_values(root: Any, dotted: str) -> list[Any]:
        values = [root]
        for segment in dotted.split("."):
            selected: list[Any] = []
            for value in values:
                child = value[segment]
                selected.extend(child if isinstance(child, list) else [child])
            values = selected
        return values

    packages = language_bundle["language"]["packages"]
    updates: list[tuple[dict[str, Any], list[Any]]] = []
    for projection in projections:
        path = projection["authority_path"]
        key_member = projection["key_member"]

        def key(definition: Any) -> Any:
            return definition if key_member is None else definition[key_member]

        definitions = path_values(language_bundle, path)
        for package in packages:
            entry = next(
                item
                for item in package["semantic_closure"]
                if item["authority_path"] == path
            )
            owned = path_values(package, projection["owners_path"])
            selected = []
            for definition in definitions:
                local_key = key(definition)
                if local_key not in owned:
                    continue
                owners = [
                    candidate
                    for candidate in packages
                    if local_key in path_values(candidate, projection["owners_path"])
                ]
                if path in scoped and len(owners) > 1:
                    if definition not in entry["definitions"]:
                        if not any(
                            definition in candidate_entry["definitions"]
                            for owner in owners
                            for candidate_entry in owner["semantic_closure"]
                            if candidate_entry["authority_path"] == path
                        ):
                            raise AssertionError(
                                f"ambiguous flat mutation at {path}:{local_key}; "
                                "mutate the owning package closure directly"
                            )
                        continue
                projected = deepcopy(definition)
                if path == "language.artifact_wire_schemas" and projected.get(
                    "protocol_role"
                ) in {
                    "metric-dataset",
                    "evaluation-run",
                    "experiment-verdict",
                    "event-trace",
                    "rir-semantic-payload",
                    "artifact-set-receipt",
                    "artifact-set-manifest",
                    "publication-index",
                    "replay-comparison",
                    "build-receipt",
                    "resolution-receipt",
                    "resolved-model",
                    "model-build-command-input",
                    "debug-map",
                    "package-lock",
                    "capability-manifest",
                    "model-explanation",
                    "evaluator-capability-manifest",
                    "resolved-runtime-profile",
                    "snapshot-series",
                    "runtime-terminal-audit",
                    "template-release",
                    "template-instantiate-command-input",
                    "template-instantiation-receipt",
                }:
                    from gda_balancing.domain.authority.metric_projection import (
                        metric_outcome_schema,
                    )
                    from gda_balancing.domain.authority.trace_projection import (
                        trace_protocol_schema,
                    )
                    from gda_balancing.domain.authority.rir_projection import (
                        rir_protocol_schema,
                    )
                    from gda_balancing.domain.authority.publication_projection import (
                        publication_protocol_schema,
                    )

                    from gda_balancing.domain.authority.runtime_projection import (
                        runtime_output_schema,
                    )

                    from gda_balancing.domain.authority.template_projection import (
                        template_protocol_schema,
                    )

                    from gda_balancing.domain.authority.replay_projection import (
                        replay_comparison_schema,
                    )

                    from gda_balancing.domain.authority.model_projection import (
                        model_protocol_schema,
                    )
                    from gda_balancing.domain.authority.runtime_evidence_projection import (
                        runtime_evidence_protocol_schema,
                    )

                    contracts = [
                        row
                        for row in language_bundle["language"]["artifact_contracts"]
                        if row["schema_kind"] == projected["artifact_kind"]
                    ]
                    if len(contracts) == 1:
                        if projected["protocol_role"] == "event-trace":
                            expected_schema = trace_protocol_schema(
                                kernel, contracts[0]["artifact_kind"]
                            )
                        elif projected["protocol_role"] in {
                            "artifact-set-receipt",
                            "artifact-set-manifest",
                            "publication-index",
                        }:
                            expected_schema = publication_protocol_schema(
                                kernel,
                                projected["protocol_role"],
                                contracts[0]["artifact_kind"],
                            )
                        elif projected["protocol_role"] in {
                            "template-release",
                            "template-instantiate-command-input",
                            "template-instantiation-receipt",
                        }:
                            expected_schema = template_protocol_schema(
                                kernel,
                                projected["protocol_role"],
                                contracts[0]["artifact_kind"],
                            )
                        elif (
                            projected["protocol_role"]
                            in kernel["meta_format"]["language_definitions"][
                                "wire_schema_protocol_roles"
                            ]["model_structure"]["containers"]
                        ):
                            expected_schema = model_protocol_schema(
                                kernel,
                                projected["protocol_role"],
                                contracts[0]["artifact_kind"],
                                language=language_bundle["language"],
                            )
                        elif projected["protocol_role"] in {
                            "evaluator-capability-manifest",
                            "resolved-runtime-profile",
                        }:
                            expected_schema = runtime_output_schema(
                                kernel,
                                projected["protocol_role"],
                                contracts[0]["artifact_kind"],
                            )
                        elif projected["protocol_role"] in {
                            "snapshot-series",
                            "runtime-terminal-audit",
                        }:
                            expected_schema = runtime_evidence_protocol_schema(
                                kernel,
                                projected["protocol_role"],
                                contracts[0]["artifact_kind"],
                            )
                        elif projected["protocol_role"] in {
                            "metric-dataset",
                            "evaluation-run",
                            "experiment-verdict",
                        }:
                            expected_schema = metric_outcome_schema(
                                kernel,
                                language_bundle["language"],
                                projected["protocol_role"],
                                contracts[0]["artifact_kind"],
                            )
                        elif projected["protocol_role"] == "replay-comparison":
                            expected_schema = replay_comparison_schema(
                                kernel,
                                language_bundle["language"],
                                contracts[0]["artifact_kind"],
                            )
                        else:
                            expected_schema = rir_protocol_schema(
                                kernel, language_bundle, contracts[0]["artifact_kind"]
                            )
                        if canonical_bytes(projected.get("schema")) == canonical_bytes(
                            expected_schema
                        ):
                            del projected["schema"]
                if path == "language.artifact_contracts":
                    binding_schemas = [
                        row
                        for row in language_bundle["language"]["artifact_wire_schemas"]
                        if row["artifact_kind"] == projected["schema_kind"]
                    ]
                    if len(binding_schemas) == 1:
                        expected_exclusions = (
                            list(
                                kernel["meta_format"]["language_definitions"][
                                    "wire_schema_protocol_roles"
                                ]["publication_structure"]["receipt"]["transport"]
                            )
                            if binding_schemas[0].get("protocol_role")
                            == "artifact-set-receipt"
                            else []
                        )
                        if canonical_bytes(
                            projected.get("identity_excluded_members")
                        ) == canonical_bytes(expected_exclusions):
                            del projected["identity_excluded_members"]
                    schemas = [
                        row
                        for row in language_bundle["language"]["artifact_wire_schemas"]
                        if row["artifact_kind"] == projected["schema_kind"]
                        and row.get("protocol_role") == "rir-semantic-payload"
                    ]
                    semantic_projection = kernel["meta_format"]["language_definitions"][
                        "wire_schema_protocol_roles"
                    ]["rir_structure"]["semantic_projection"]
                    if len(schemas) == 1 and canonical_bytes(
                        projected.get("semantic_identity_projection")
                    ) == canonical_bytes(semantic_projection):
                        del projected["semantic_identity_projection"]
                if (
                    path == "language.artifact_wire_schemas"
                    and projected.get("protocol_role") == "experiment-specification"
                ):
                    from gda_balancing.domain.authority.experiment_projection import (
                        experiment_input_schema,
                    )

                    if canonical_bytes(projected.get("schema")) == canonical_bytes(
                        experiment_input_schema(kernel)
                    ):
                        del projected["schema"]
                selected.append(projected)
            updates.append((entry, selected))
    for entry, definitions in updates:
        entry["definitions"] = definitions
