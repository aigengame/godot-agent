"""Bounded selected-closure cases for the #878 priority witness.

This helper deliberately names the finite extension-owned identities exercised by
the witness. It does not discover or rewrite unrelated LDB packages, package
vectors, artifact families, or arbitrary JSON strings.
"""

from __future__ import annotations

import hashlib
from typing import Any

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
)
from priority_protocol_support import authorities, source, specification
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root


_EXTENSION_PACKAGES = frozenset({"game.action", "game.turn"})
_MODEL_ROLES = frozenset(
    {
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "model-explanation",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    }
)
_SELECTED_IDENTITY_RENAMES = {
    "Counter": "RenamedCounter",
    "Counters": "RenamedCounters",
    "PendingIds": "RenamedPendingIds",
    "Outcome": "RenamedOutcome",
    "count-match": "renamed-count-match",
    "cancel-reverse-step": "renamed-cancel-reverse-step",
    "propose": "renamed-propose",
    "append-counter": "renamed-append-counter",
    "resolve": "renamed-resolve",
    "open": "renamed-open",
    "respond": "renamed-respond",
    "pass": "renamed-pass",
}


def _renamed(identity: str) -> str:
    return _SELECTED_IDENTITY_RENAMES.get(identity, identity)


def _rename_coordinate(coordinate: dict[str, Any]) -> None:
    if coordinate.get("package") in _EXTENSION_PACKAGES and isinstance(
        coordinate.get("id"), str
    ):
        coordinate["id"] = _renamed(coordinate["id"])


def _rename_typed_value(value: Any) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("type"), dict):
        return
    _rename_coordinate(value["type"])


def _rename_instruction_sequence(instructions: list[dict[str, Any]]) -> None:
    for instruction in instructions:
        operation = instruction.get("operation")
        if isinstance(operation, dict):
            _rename_coordinate(operation)
        literal = instruction.get("literal")
        if isinstance(literal, dict):
            _rename_typed_value(literal)
        body = instruction.get("body")
        if isinstance(body, list):
            _rename_instruction_sequence(body)


def _rename_operation_definition(definition: dict[str, Any]) -> None:
    definition["id"] = _renamed(definition["id"])
    owner_type = definition.get("owner_type")
    if isinstance(owner_type, str):
        definition["owner_type"] = _renamed(owner_type)
    for port in definition["inputs"]:
        type_reference = port.get("type")
        if isinstance(type_reference, dict):
            _rename_coordinate(type_reference)
    result = definition.get("result")
    if isinstance(result, dict) and isinstance(result.get("type"), dict):
        _rename_coordinate(result["type"])
    _rename_instruction_sequence(definition["body"])


def _rename_nominal_type_definition(definition: dict[str, Any]) -> None:
    definition["id"] = _renamed(definition["id"])
    shape = definition["definition"]
    element = shape.get("element")
    if isinstance(element, dict):
        _rename_coordinate(element)
    for field in shape.get("fields", []):
        type_reference = field.get("type")
        if isinstance(type_reference, dict):
            _rename_coordinate(type_reference)


def _rename_package_semantics(package: dict[str, Any]) -> None:
    exports = package["exports"]
    exports["operations"] = [_renamed(value) for value in exports["operations"]]
    exports["nominal_types"] = [_renamed(value) for value in exports["nominal_types"]]
    for row in exports["types"]:
        row["id"] = _renamed(row["id"])
    for closure in package["semantic_closure"]:
        if closure["authority_path"] == "language.operations":
            for definition in closure["definitions"]:
                _rename_operation_definition(definition)
        elif closure["authority_path"] == "language.nominal_types":
            for definition in closure["definitions"]:
                _rename_nominal_type_definition(definition)


def _rename_source_semantics(model_source: dict[str, Any]) -> None:
    for module in model_source["modules"]:
        for imported in module["imports"]:
            if imported["package"] not in _EXTENSION_PACKAGES:
                continue
            imported["alias"] = _renamed(imported["alias"])
            imported["symbol"] = _renamed(imported["symbol"])
        for symbol in module["symbols"]:
            type_reference = symbol.get("type")
            if isinstance(type_reference, str):
                symbol["type"] = _renamed(type_reference)
            elif isinstance(type_reference, dict):
                _rename_coordinate(type_reference)
    for entrypoint in model_source["entrypoints"]:
        _rename_coordinate(entrypoint["operation"])


def _rename_experiment_semantics(experiment: dict[str, Any]) -> None:
    for scenario in experiment["scenarios"]:
        for event in scenario["event_plan"]:
            for fact in event.get("facts", []):
                _rename_typed_value(fact["value"])
        for assignment in scenario["assignments"]:
            _rename_typed_value(assignment["value"])


def _rename_selected_authority(language) -> None:
    vector_sets = {
        value["package_id"]: value for value in language.package_conformance_vector_sets
    }
    for package in language["language"]["packages"]:
        if package["id"] not in _EXTENSION_PACKAGES:
            continue
        _rename_package_semantics(package)
        vector_set = vector_sets[package["id"]]
        for vector in vector_set["vector_definitions"]:
            vector["operation"] = _renamed(vector["operation"])
            expected = vector.get("expect")
            if vector["probe"]["path"] == "body" and isinstance(expected, list):
                _rename_instruction_sequence(expected)
        _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(language)


def _language_bundle_payload(bundle) -> dict[str, Any]:
    return {
        "projection": dict(bundle),
        "root": bundle.root,
        "package_releases": bundle.package_releases,
        "package_conformance_vector_sets": bundle.package_conformance_vector_sets,
        "root_byte_size": bundle.root_byte_size,
        "package_byte_sizes": list(bundle.package_byte_sizes),
        "vector_set_byte_sizes": list(bundle.vector_set_byte_sizes),
    }


def _coordinate(row: dict[str, Any]) -> str:
    identity = row.get("id")
    if identity is None:
        identity = row["definition"]["id"]
    return f"{row['package']}::{identity}"


def selected_dependency_binding(
    artifacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Bind the whole compiler-selected closure without a parallel taxonomy."""
    if set(artifacts) != _MODEL_ROLES:
        raise ValueError("priority binding requires the exact eight Model members")
    rir = artifacts["rir-semantic-payload"]
    selected = rir["selected_semantics"]
    selected_types = [
        _coordinate(row)
        for row in selected["types"]
        if row["package"] in _EXTENSION_PACKAGES
    ]
    selected_operations = [
        _coordinate(row)
        for row in selected["operations"]
        if row["package"] in _EXTENSION_PACKAGES
    ]
    return {
        "rir_semantic_identity": rir["semantic_identity"],
        "selected_semantics_sha256": "sha256:"
        + hashlib.sha256(canonical_bytes(selected)).hexdigest(),
        "model_artifact_identities": {
            role: artifact["content_identity"]
            for role, artifact in sorted(artifacts.items())
        },
        "extension_type_coordinates": sorted(selected_types),
        "extension_operation_coordinates": sorted(selected_operations),
    }


def admits_selected_dependency_binding(
    artifacts: dict[str, dict[str, Any]], binding: dict[str, Any]
) -> bool:
    """Re-derive the finite witness binding; missing or stale data fails closed."""
    try:
        return canonical_bytes(binding) == canonical_bytes(
            selected_dependency_binding(artifacts)
        )
    except (KeyError, TypeError, ValueError):
        return False


def build_priority_case(*, renamed: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one authored priority case and its bounded proof markers."""
    kernel, language, operations = authorities()
    if renamed:
        _rename_selected_authority(language)
    model_source = source(operations)
    if renamed:
        _rename_source_semantics(model_source)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    checked = check_model_source_value(model_source, authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    artifacts = compile_checked_model(checked)
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    experiments = {
        variant: specification(rir, variant == "variant")
        for variant in ("baseline", "variant")
    }
    if renamed:
        for value in experiments.values():
            _rename_experiment_semantics(value)
    dependency_binding = selected_dependency_binding(artifacts)
    selected_coordinates = set(dependency_binding["extension_type_coordinates"]) | set(
        dependency_binding["extension_operation_coordinates"]
    )
    expected_identities = set(
        _SELECTED_IDENTITY_RENAMES.values() if renamed else _SELECTED_IDENTITY_RENAMES
    )
    assert expected_identities == {
        coordinate.split("::", 1)[1] for coordinate in selected_coordinates
    }
    case = {
        "authority": "renamed" if renamed else "original",
        "kernel": kernel,
        "language_bundle": _language_bundle_payload(language),
        "source": model_source,
        "mapping": (
            dict(sorted(_SELECTED_IDENTITY_RENAMES.items())) if renamed else {}
        ),
        "experiments": experiments,
    }
    proof = {
        "kernel_sha256": hashlib.sha256(canonical_bytes(kernel)).hexdigest(),
        "renamed_identity_count": len(_SELECTED_IDENTITY_RENAMES) if renamed else 0,
        "scope": "priority selected execution closure and generated 8+6 members",
    }
    return case, proof
