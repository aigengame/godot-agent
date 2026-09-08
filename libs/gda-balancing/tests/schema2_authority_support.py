"""Shared authority inputs and owner-preserving mutable test projections."""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.canonical import canonical_bytes


def mutable_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Return an owned mutable copy of the admitted packaged authorities."""
    return packaged_authority_context().mutable_pair()


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
                ) in {"event-trace", "rir-semantic-payload", "artifact-set-receipt"}:
                    from gda_balancing.domain.authority.trace_projection import (
                        trace_protocol_schema,
                    )
                    from gda_balancing.domain.authority.rir_projection import (
                        rir_protocol_schema,
                    )
                    from gda_balancing.domain.authority.receipt_projection import (
                        receipt_protocol_schema,
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
                        elif projected["protocol_role"] == "artifact-set-receipt":
                            expected_schema = receipt_protocol_schema(
                                kernel, contracts[0]["artifact_kind"]
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
                                ]["receipt_structure"]["transport"]
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
                selected.append(projected)
            updates.append((entry, selected))
    for entry, definitions in updates:
        entry["definitions"] = definitions
