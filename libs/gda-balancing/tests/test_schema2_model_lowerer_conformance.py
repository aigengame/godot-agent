"""Independent lowerer/consumer conformance for the #539 Model tracer."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import gda_balancing.domain.model._resolution as model_module
import gda_balancing.domain.model._admission as model_admission_module
import gda_balancing.domain.model._checking as model_checking_module
import gda_balancing.domain.model._lowering as model_lowering_module
import jsonschema
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.graph import (
    CurrentPackage,
    NamespaceSelection,
    project_required_namespace_closure,
    derive_current_namespace_packages,
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.domain.authority.admission import admit_authorities
from gda_balancing.domain.authority.source_projection import (
    SourceProjection,
    derive_default_source_native_bindings,
    project_source_value,
    source_schema_member,
)
from gda_balancing.domain.canonical import JsonValue
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.domain.model import (
    CheckedModel,
    admit_rir,
    admit_resolved_model,
    check_model_source,
    check_model_source_value,
)
from gda_balancing.domain.model._compilation import (
    compile_checked_model,
    lower_checked_model,
)
from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_authority_support import (
    refresh_package_semantic_closures,
    mutable_authorities,
)
from schema2_bootstrap_production_support import _recursive_nominal_owner_candidate
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_fact_is_closed,
    _consumer_b_operation_composition_subjects,
    _consumer_b_operation_value_is_admitted,
    _consumer_b_project_source,
    _consumer_b_source_fact_transport_is_supported,
    _consumer_b_source_semantic_selector,
)
from schema2_formula_conformance_support import (
    _inline_source_parameter,
    _source_abi_selector,
    _source_abi_value_and_paths,
    normalize_semantic_body,
)


def _inject_authority_context(monkeypatch, kernel, language_bundle):
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext)
    monkeypatch.setattr(
        model_admission_module, "packaged_authority_context", lambda: context
    )
    monkeypatch.setattr(
        model_checking_module, "packaged_authority_context", lambda: context
    )
    return context


class _ReferenceRuntimeProjectionExhausted(Exception):
    pass


class _ReferenceEntrypointError(ValueError):
    def __init__(self, pointer: str, message: str):
        super().__init__(message)
        self.pointer = pointer


class _ReferenceSourceFactError(ValueError):
    def __init__(self, pointer: str, message: str):
        super().__init__(message)
        self.pointer = pointer


class _ReferenceFormulaPairsError(Exception):
    def __init__(self, diagnostics: tuple[tuple[str, str], ...]):
        self.diagnostics = diagnostics


class _ReferenceFormulaError(ValueError):
    def __init__(self, reason_id: str, pointer: str, message: str):
        super().__init__(message)
        self.reason_id = reason_id
        self.pointer = pointer


def _reference_validate_canonical(value: Any) -> None:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            value.encode("utf-8")
        return
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            raise ValueError("integer is outside signed Int64")
        return
    if isinstance(value, list):
        for item in value:
            _reference_validate_canonical(item)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical object keys must be strings")
        for item in value.values():
            _reference_validate_canonical(item)
        return
    raise TypeError("value is outside the canonical JSON profile")


def _reference_encoded(value: Any) -> bytes:
    _reference_validate_canonical(value)

    def plain(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, list):
            return [plain(child) for child in item]
        return item

    return (
        json.dumps(
            plain(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        + "\n"
    ).encode()


def _reference_content_identity(domain: str, value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            f"gda-balancing:{domain}:".encode() + _reference_encoded(value)
        ).hexdigest()
    )


def _reference_rir_semantic_projection(
    language_bundle: dict[str, Any], artifact: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    contract = next(
        item
        for item in language_bundle["language"]["artifact_contracts"]
        if item["schema_kind"]
        == next(
            row["artifact_kind"]
            for row in language_bundle["language"]["artifact_wire_schemas"]
            if row.get("protocol_role") == "rir-semantic-payload"
        )
    )
    projection = contract["semantic_identity_projection"]
    result = {
        key: deepcopy(value)
        for key, value in artifact.items()
        if key not in set(projection["excluded_root_members"])
    }
    seen: set[str] = set()
    for row in projection["collection_member_exclusions"]:
        collection_member = row["collection_member"]
        assert collection_member not in seen
        excluded = set(row["excluded_members"])
        result[collection_member] = [
            {key: value for key, value in item.items() if key not in excluded}
            for item in result[collection_member]
        ]
        seen.add(collection_member)
    return contract["semantic_identity_domain"], result


def _symbol(name: str, role: str) -> dict[str, Any]:
    return {
        "symbol": name,
        "type": "quantity",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
        "value_policy": {
            "mode": (
                "model-fixed"
                if role == "constant"
                else "experiment-required"
                if role in {"parameter", "input", "state"}
                else "named-stream"
                if role == "random"
                else "none"
            ),
            **({"value": 1} if role == "constant" else {}),
        },
    }


def _source(symbols: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "example.quantity-model",
            "entry_module": "main",
        },
        "package_requirements": ["core.quantity"],
        "entrypoints": [],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": symbols,
            }
        ],
    }


def _write_source(path: Path, source: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(source, separators=(",", ":")),
        encoding="utf-8",
    )


def _production_source_projection(
    source: dict[str, Any], kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> SourceProjection:
    from gda_balancing.domain.authority.source_projection import (
        derive_source_native_bindings,
        derive_source_semantic_index,
    )

    schema = next(
        item["schema"]
        for item in language_bundle["language"]["wire_schemas"]
        if item.get("protocol_role") == "model-source-package"
    )
    index = derive_source_semantic_index(kernel, language_bundle)
    profile = next(
        row
        for row in language_bundle["language"]["resolution_profiles"]
        if row.get("default") is True
    )
    bindings = derive_source_native_bindings(index, profile["source_native_bindings"])
    return project_source_value(source, schema, bindings)


def _reference_select_with_paths(
    root: Any,
    selector: list[str],
    base_path: tuple[object, ...] = (),
) -> list[tuple[Any, tuple[object, ...]]]:
    values = [(root, base_path)]
    for segment in selector:
        selected: list[tuple[Any, tuple[object, ...]]] = []
        for value, path in values:
            if segment == "*" and isinstance(value, list):
                selected.extend(
                    (item, (*path, index)) for index, item in enumerate(value)
                )
            elif isinstance(value, dict) and segment in value:
                selected.append((value[segment], (*path, segment)))
        values = selected
    return values


def _reference_path(root: Any, dotted: str) -> list[Any]:
    values = [root]
    for segment in dotted.split("."):
        selected: list[Any] = []
        for value in values:
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                if not isinstance(candidate, dict) or segment not in candidate:
                    continue
                child = candidate[segment]
                selected.extend(child if isinstance(child, list) else [child])
        values = selected
    return values


def _reference_lowering(language: dict[str, Any]) -> dict[str, Any]:
    profiles = [
        profile
        for profile in language["resolution_profiles"]
        if profile["default"] is True
    ]
    assert len(profiles) == 1
    matches = [
        lowering
        for lowering in language["model_lowerings"]
        if lowering["id"] == profiles[0]["model_lowering"]
        and lowering["resolution_profile"] == profiles[0]["id"]
    ]
    assert len(matches) == 1
    return matches[0]


def _reference_namespace_selection(
    source, kernel, language_bundle
) -> NamespaceSelection:
    """Construct expected selection facts with an independent required traversal."""
    language = language_bundle["language"]
    roots = tuple(sorted(source["package_requirements"]))
    assert len(roots) == len(set(roots))
    available = {row["id"]: row for row in language["packages"]}
    assert len(available) == len(language["packages"])
    selected = set()
    frontier = list(roots)
    while frontier:
        namespace = frontier.pop()
        assert namespace in available
        if namespace in selected:
            continue
        selected.add(namespace)
        frontier.extend(available[namespace]["dependencies"]["required"])
    projections = {
        row["authority_path"]: row
        for row in kernel["meta_format"]["package_release"]["semantic_closure"][
            "projections"
        ]
    }
    packages = []
    definitions = {}
    providers = {}
    edges = []
    for namespace in sorted(selected):
        package = available[namespace]
        owned = []
        for entry in package["semantic_closure"]:
            path = entry["authority_path"]
            key_member = projections[path]["key_member"]
            for definition in entry["definitions"]:
                key = definition if key_member is None else definition[key_member]
                owner = (namespace, path, key)
                assert owner not in definitions
                definitions[owner] = definition
                owned.append((path, key, definition))
        for capability in package["capabilities"]["provided"]:
            assert capability not in providers
            providers[capability] = namespace
        edges.extend(
            (namespace, dependency)
            for dependency in package["dependencies"]["required"]
        )
        packages.append(
            CurrentPackage(
                namespace=namespace,
                required=tuple(package["dependencies"]["required"]),
                optional=tuple(package["dependencies"]["optional"]),
                provides=tuple(package["capabilities"]["provided"]),
                requires=tuple(package["capabilities"]["required"]),
                definitions=tuple(owned),
            )
        )
    assert all(
        capability in providers
        for package in packages
        for capability in package.requires
    )
    return NamespaceSelection(
        packages=tuple(packages),
        dependency_edges=tuple(sorted(edges)),
        capability_bindings=tuple(sorted(providers.items())),
        definitions=MappingProxyType(dict(sorted(definitions.items()))),
        roots=roots,
    )


def _exact_path(root: Any, dotted: str) -> Any:
    value = root
    for segment in dotted.split("."):
        value = value[segment]
    return value


def _reference_package_runtime_closure(package, kernel):
    projection = kernel["meta_format"]["package_release"][
        "semantic_identity_projection"
    ]
    runtime_paths = set(package[projection["path_inventory_member"]])
    notation_source = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["source_notation"]["operation_source"]
    runtime_closure = deepcopy(
        [
            entry
            for entry in package[projection["source_member"]]
            if entry[projection["path_member"]] in runtime_paths
        ]
    )
    for entry in runtime_closure:
        if entry[projection["path_member"]] != notation_source["authority_path"]:
            continue
        for definition in entry["definitions"]:
            if not isinstance(definition, dict) or not isinstance(
                definition.get("extensions"), dict
            ):
                continue
            retained = {
                key: value
                for key, value in definition["extensions"].items()
                if key != notation_source["extension_member"]
            }
            if retained:
                definition["extensions"] = retained
            else:
                definition.pop("extensions")
    return runtime_closure


def _reidentify_language_bundle(language_bundle: dict[str, Any]) -> None:
    assert isinstance(language_bundle, LanguageBundleIndex)
    kernel, _ = mutable_authorities()
    refresh_package_semantic_closures(language_bundle, kernel)
    vector_sets_by_coordinate = {
        vector_set["package_id"]: vector_set
        for vector_set in language_bundle.package_conformance_vector_sets
    }
    projected_vectors = {vector["id"]: vector for vector in language_bundle["vectors"]}
    for package in language_bundle["language"]["packages"]:
        runtime_closure = _reference_package_runtime_closure(package, kernel)
        package["semantic_identity"] = _reference_content_identity(
            "domain-package-semantic-closure-v2",
            runtime_closure,
        )
        vector_set = vector_sets_by_coordinate[package["id"]]
        existing_vectors = {
            vector["id"]: vector for vector in vector_set["vector_definitions"]
        }
        vector_set["vector_definitions"] = [
            deepcopy(projected_vectors.get(vector_id, existing_vectors[vector_id]))
            for vector_id in vector_set["vectors"]
        ]
        vector_set["content_identity"] = _reference_content_identity(
            "package-conformance-vector-set-v2",
            {
                key: value
                for key, value in vector_set.items()
                if key != "content_identity"
            },
        )
        package["conformance_vectors"] = {
            "artifact_kind": vector_set["artifact_kind"],
            "byte_size": len(_reference_encoded(vector_set)),
            "content_identity": vector_set["content_identity"],
        }
        package["content_identity"] = _reference_content_identity(
            "domain-package-release-v2",
            {key: value for key, value in package.items() if key != "content_identity"},
        )
    members = sorted(
        zip(
            deepcopy(language_bundle["language"]["packages"]),
            deepcopy(language_bundle.package_conformance_vector_sets),
            strict=True,
        ),
        key=lambda member: member[0]["id"],
    )
    packages = [package for package, _vector_set in members]
    vector_sets = [vector_set for _package, vector_set in members]
    package_sizes = [len(_reference_encoded(package)) for package in packages]
    vector_set_sizes = [
        len(_reference_encoded(vector_set)) for vector_set in vector_sets
    ]
    root = deepcopy(language_bundle.root)
    root["resources"] = deepcopy(language_bundle["resources"])
    root["package_descriptors"] = [
        {
            "artifact_kind": package["artifact_kind"],
            "byte_size": size,
            "content_identity": package["content_identity"],
            "id": package["id"],
        }
        for package, size in zip(packages, package_sizes, strict=True)
    ]
    root["content_identity"] = _reference_content_identity(
        "language-definition-bundle-v2",
        {key: value for key, value in root.items() if key != "content_identity"},
    )
    rebuilt = derive_language_index(
        root,
        packages,
        vector_sets,
        kernel["admission"]["required_language_members"],
        kernel=kernel,
        root_byte_size=len(_reference_encoded(root)),
        package_byte_sizes=package_sizes,
        vector_set_byte_sizes=vector_set_sizes,
        descriptor_order=kernel["meta_format"]["language_bundle"]["package_descriptor"][
            "canonical_order"
        ],
    )
    language_bundle.root = deepcopy(rebuilt.root)
    language_bundle.package_releases = deepcopy(rebuilt.package_releases)
    language_bundle.package_conformance_vector_sets = deepcopy(
        rebuilt.package_conformance_vector_sets
    )
    language_bundle.root_byte_size = rebuilt.root_byte_size
    language_bundle.package_byte_sizes = rebuilt.package_byte_sizes
    language_bundle.vector_set_byte_sizes = rebuilt.vector_set_byte_sizes
    language_bundle.clear()
    language_bundle.update(dict(rebuilt))


def _reference_reason_matches(
    language_bundle: dict[str, Any], reason: dict[str, Any], values: list[Any]
) -> bool:
    predicate = reason["predicate"]
    operation = predicate["operation"]
    if operation == "not-member":
        inventory = _reference_path(
            language_bundle, cast(str, predicate["inventory_path"])
        )
        member_field = predicate.get("member_field")
        if member_field is not None:
            inventory = [
                item[member_field]
                for item in inventory
                if isinstance(item, dict) and member_field in item
            ]
        return any(value not in inventory for value in values)
    if operation == "has-duplicate":
        encoded = [
            _reference_content_identity("reference-scalar", value) for value in values
        ]
        return len(encoded) != len(set(encoded))
    if operation == "greater-than":
        limit = _reference_path(language_bundle, cast(str, predicate["limit_path"]))
        assert len(limit) == 1 and isinstance(limit[0], int)
        return len(values) > limit[0]
    if operation == "invalid-interval":
        return any(
            isinstance(value, dict)
            and isinstance(value.get("minimum"), int)
            and isinstance(value.get("maximum"), int)
            and value["minimum"] > value["maximum"]
            for value in values
        )
    if operation == "not-equal":
        return len(values) == 2 and values[0] != values[1]
    raise AssertionError(
        f"reference consumer observed unknown reason operation: {operation}"
    )


def _reference_check_source(
    source: dict[str, Any],
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
) -> tuple[tuple[str, str], ...] | ModelSourceContext:
    """Independently interpret the admitted source schema and model-check relation."""
    language = language_bundle["language"]
    source_schema = next(
        item["schema"]
        for item in language["wire_schemas"]
        if item.get("protocol_role") == "model-source-package"
    )
    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    schema_errors = sorted(
        jsonschema.Draft202012Validator(source_schema).iter_errors(source),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    reasons = {item["id"]: item for item in language["reasons"]}
    check_selectors = [
        (
            check,
            _consumer_b_source_semantic_selector(
                source_schema,
                [
                    *check.get("semantic_scope_selector", []),
                    *check["semantic_selector"],
                ],
            ),
        )
        for check in language["model_checks"]
    ]
    if schema_errors:

        def pointer_count(error: jsonschema.ValidationError) -> int:
            if error.validator == "required" and isinstance(error.instance, dict):
                required = cast(list[Any], error.validator_value)
                return max(
                    1,
                    len(set(required) - set(error.instance)),
                )
            if error.validator in {
                "additionalProperties",
                "unevaluatedProperties",
            } and isinstance(error.instance, dict):
                properties = (
                    error.schema.get("properties", {})
                    if isinstance(error.schema, dict)
                    else {}
                )
                if isinstance(properties, dict):
                    return max(1, len(set(error.instance) - set(properties)))
            return 1

        def preferred_errors(
            error: jsonschema.ValidationError,
        ) -> list[jsonschema.ValidationError]:
            if error.validator not in {"oneOf", "anyOf"} or not error.context:
                return [error]
            branches: dict[object, list[jsonschema.ValidationError]] = {}
            for child in error.context:
                schema_path = list(child.schema_path)
                markers = [
                    index
                    for index, segment in enumerate(schema_path)
                    if segment == error.validator
                ]
                branch = (
                    schema_path[markers[-1] + 1]
                    if markers and markers[-1] + 1 < len(schema_path)
                    else schema_path[0]
                    if schema_path and isinstance(schema_path[0], int)
                    else None
                )
                branches.setdefault(branch, []).append(child)
            alternatives = (
                error.schema.get(error.validator, [])
                if isinstance(error.schema, dict) and isinstance(error.validator, str)
                else []
            )

            def affinity(branch: object) -> tuple[int, int, int, int]:
                if not isinstance(branch, int) or not isinstance(error.instance, dict):
                    return (0, 0, 0, 0)
                if not isinstance(alternatives, list) or branch >= len(alternatives):
                    return (0, 0, 0, 0)
                candidate = alternatives[branch]
                if not isinstance(candidate, dict):
                    return (0, 0, 0, 0)
                properties = candidate.get("properties", {})
                if not isinstance(properties, dict):
                    return (0, 0, 0, 0)
                fixed = [
                    (name, child["const"])
                    for name, child in properties.items()
                    if isinstance(child, dict) and "const" in child
                ]
                different = sum(
                    name in error.instance and error.instance[name] != value
                    for name, value in fixed
                )
                matching = sum(
                    name in error.instance and error.instance[name] == value
                    for name, value in fixed
                )
                present = len(set(properties) & set(error.instance))
                required = candidate.get("required", [])
                covered = (
                    len(set(required) & set(error.instance))
                    if isinstance(required, list)
                    else 0
                )
                return (different, -matching, -present, -covered)

            if any(affinity(branch)[0] > 0 for branch in branches) and not any(
                affinity(branch)[1] < 0 for branch in branches
            ):
                return [error]

            selected = min(
                branches.items(),
                key=lambda row: (
                    *affinity(row[0]),
                    sum(pointer_count(item) for item in row[1]),
                    tuple(str(item.schema_path) for item in row[1]),
                ),
            )[1]
            preferred = [
                preferred for child in selected for preferred in preferred_errors(child)
            ]
            return (
                [error]
                if any(
                    item.validator in {"oneOf", "anyOf"} and item.context
                    for item in preferred
                )
                else preferred
            )

        diagnostics = []
        for schema_error in schema_errors:
            selected_errors = preferred_errors(schema_error)
            for preferred in selected_errors:
                paths = [tuple(preferred.absolute_path)]
                if preferred.validator == "required" and isinstance(
                    preferred.instance, dict
                ):
                    required = cast(list[Any], preferred.validator_value)
                    paths = [
                        (*paths[0], member)
                        for member in sorted(set(required) - set(preferred.instance))
                    ]
                elif preferred.validator in {
                    "additionalProperties",
                    "unevaluatedProperties",
                } and isinstance(preferred.instance, dict):
                    properties = (
                        preferred.schema.get("properties", {})
                        if isinstance(preferred.schema, dict)
                        else {}
                    )
                    if isinstance(properties, dict):
                        paths = [
                            (*paths[0], member)
                            for member in sorted(
                                set(preferred.instance) - set(properties)
                            )
                        ]
                for path in paths:
                    diagnostic = reasons[profile["structural_reason"]]["diagnostic"]
                    if preferred.validator not in {
                        "additionalProperties",
                        "required",
                        "type",
                        "unevaluatedProperties",
                    }:
                        for check, authored_selector in check_selectors:
                            selector = tuple(authored_selector)
                            if len(selector) == len(path) and all(
                                (expected is None and isinstance(actual, int))
                                or expected == actual
                                for expected, actual in zip(selector, path, strict=True)
                            ):
                                diagnostic = reasons[check["reason"]]["diagnostic"]
                                break
                    diagnostics.append((diagnostic, _reference_pointer(list(path))))
        return tuple(dict.fromkeys(diagnostics))

    independent_projection = _consumer_b_project_source(source, kernel, language_bundle)
    canonical_source, semantic_paths = _source_abi_value_and_paths(
        independent_projection.value,
        language_bundle,
        "source.root",
        preserve_native_discriminators=True,
    )
    authored_paths = {
        stable: independent_projection.authored_paths[semantic]
        for stable, semantic in semantic_paths.items()
    }
    source_projection = SourceProjection(
        value=canonical_source,
        authored_paths=authored_paths,
        authored_source=source,
    )

    def authored_pointer(canonical: tuple[object, ...] | str) -> str:
        pointer = (
            canonical
            if isinstance(canonical, str)
            else _reference_pointer(list(canonical))
        )
        return source_projection.authored_paths.get(pointer, pointer)

    def authored_semantic_pointer(semantic: tuple[object, ...]) -> str:
        pointer = _reference_pointer(list(semantic))
        return independent_projection.authored_paths.get(pointer, pointer)

    diagnostics_by_stage: dict[str, list[tuple[str, str]]] = {}
    for check in language["model_checks"]:
        reason = reasons[check["reason"]]
        canonical_scope_selector, scope_slots = _source_abi_selector(
            check.get("semantic_scope_selector", []), language_bundle
        )
        canonical_selector, _selected_slots = _source_abi_selector(
            check["semantic_selector"], language_bundle, scope_slots
        )
        canonical_full_selector = [
            *canonical_scope_selector,
            *canonical_selector,
        ]
        scopes = (
            _reference_select_with_paths(canonical_source, canonical_scope_selector)
            if canonical_scope_selector
            else [(canonical_source, ())]
        )
        for scope, scope_path in scopes:
            selected = _reference_select_with_paths(
                scope,
                canonical_selector,
                scope_path,
            )
            values = [value for value, _path in selected]
            code = reason["diagnostic"]
            if check["mode"] == "each":
                diagnostics_by_stage.setdefault(reason["stage"], []).extend(
                    (code, authored_pointer(path))
                    for value, path in selected
                    if _reference_reason_matches(language_bundle, reason, [value])
                )
                continue
            if not _reference_reason_matches(language_bundle, reason, values):
                continue
            operation = reason["predicate"]["operation"]
            if check["mode"] == "all" and operation == "has-duplicate":
                first_paths: dict[bytes, tuple[object, ...]] = {}
                for value, path in selected:
                    encoded = _reference_encoded(value)
                    if encoded not in first_paths:
                        first_paths[encoded] = path
                        continue
                    diagnostics_by_stage.setdefault(reason["stage"], []).append(
                        (code, authored_pointer(path))
                    )
                continue
            if check["mode"] == "count":
                limit_values = _reference_path(
                    language_bundle,
                    reason["predicate"]["limit_path"],
                )
                assert len(limit_values) == 1 and isinstance(limit_values[0], int)
                limit = limit_values[0]
                location = (
                    selected[limit][1]
                    if len(selected) > limit
                    else tuple(canonical_full_selector)
                )
            else:
                location = (
                    selected[0][1] if selected else tuple(canonical_full_selector)
                )
            diagnostics_by_stage.setdefault(reason["stage"], []).append(
                (code, authored_pointer(location))
            )

    resource_reason = reasons[profile["resource_reason"]]
    resource_diagnostic = resource_reason["diagnostic"]
    step_limit = _exact_path(
        language_bundle, resource_reason["predicate"]["limit_path"]
    )
    base_steps = 0

    class BudgetExhausted(Exception):
        pass

    def consume_base() -> None:
        nonlocal base_steps
        if base_steps >= step_limit:
            raise BudgetExhausted
        base_steps += 1

    relations: dict[str, list[dict[str, dict[str, str]]]] = {}
    available_packages = language["packages"]
    packages_by_coordinate = {package["id"]: package for package in available_packages}
    selected_packages: dict[str, dict[str, Any]] = {}
    pending = list(canonical_source["package_requirements"])
    while pending:
        namespace = pending.pop(0)
        package = packages_by_coordinate.get(namespace)
        if package is None or namespace in selected_packages:
            continue
        selected_packages[namespace] = package
        pending.extend(package["dependencies"]["required"])
    selected_package_values = [
        selected_packages[package_id] for package_id in sorted(selected_packages)
    ]

    def source_term(
        value: Any,
        canonical_base: tuple[object, ...],
        semantic_segments: list[str],
    ) -> tuple[Any, tuple[object, ...]]:
        target = value
        target_parts = list(canonical_base)
        for segment in semantic_segments:
            if isinstance(target, list):
                part: object = int(segment)
                target = target[cast(int, part)]
            elif isinstance(target, dict):
                part = segment
                target = target[cast(str, part)]
            else:
                raise KeyError("Source recipe path traverses a scalar")
            target_parts.append(part)
        return target, tuple(target_parts)

    def read_term(
        term: dict[str, Any],
        environment: dict[str, tuple[Any, tuple[object, ...] | None]],
    ) -> tuple[Any, tuple[object, ...] | None]:
        if term["root"] == "source":
            # Relation recipes are authored in current LDB semantic members;
            # fixed host traversal uses ``canonical_source`` outside this path.
            value: Any = independent_projection.value
            pointer: tuple[object, ...] | None = ()
        elif term["root"] == "language":
            value = language
            pointer = None
        elif term["root"] == "selected-packages":
            value = selected_package_values
            pointer = None
        elif term["root"] == "binding":
            value, pointer = environment[term["binding"]]
        else:
            raise AssertionError(
                f"reference consumer observed unknown term root: {term['root']}"
            )
        if pointer is not None:
            return source_term(value, pointer, term["path"])
        for segment in term["path"]:
            value = value[segment]
        return value, pointer

    try:
        for recipe in profile["relation_recipes"]:
            environments: list[dict[str, Any]] = [{}]
            for binding in recipe["bindings"]:
                next_environments = []
                for environment in environments:
                    candidates, source_pointer = read_term(
                        binding["source"], environment
                    )
                    assert isinstance(candidates, list)
                    for candidate_index, candidate in enumerate(candidates):
                        consume_base()
                        next_environments.append(
                            {
                                **environment,
                                binding["name"]: (
                                    candidate,
                                    (
                                        (*source_pointer, candidate_index)
                                        if source_pointer is not None
                                        else None
                                    ),
                                ),
                            }
                        )
                environments = next_environments
            relation_rows = []
            for environment in environments:
                rejected = False
                for predicate in recipe["predicates"]:
                    consume_base()
                    if (
                        predicate["operator"] == "equal"
                        and read_term(predicate["left"], environment)[0]
                        != read_term(predicate["right"], environment)[0]
                    ):
                        rejected = True
                        break
                if rejected:
                    continue
                values = {}
                pointers = {}
                for field in recipe["fields"]:
                    consume_base()
                    value, pointer = read_term(field["term"], environment)
                    values[field["name"]] = value
                    if field["pointer"]:
                        assert pointer is not None
                        pointers[field["name"]] = authored_semantic_pointer(pointer)
                relation_rows.append({"values": values, "pointers": pointers})
            relations[recipe["id"]] = relation_rows
    except BudgetExhausted:
        return ((resource_diagnostic, ""),)

    def matches(
        subject: dict[str, Any],
        target: dict[str, Any],
        fields: list[dict[str, str]],
    ) -> bool:
        return all(
            subject["values"][field["subject"]] == target["values"][field["target"]]
            for field in fields
        )

    def law_failures(
        law: dict[str, Any],
        consume: Callable[[], None],
    ) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
        operator = law["operator"]
        if operator == "require-match":
            failures = []
            for subject in relations[law["subject_relation"]]:
                consume()
                guard = law.get("guard")
                if guard is not None:
                    guarded = []
                    for target in relations[guard["target_relation"]]:
                        consume()
                        if matches(subject, target, guard["match"]):
                            guarded.append(target)
                    if guard["cardinality"] == "exactly-one" and len(guarded) != 1:
                        continue
                targets = []
                for target in relations[law["target_relation"]]:
                    consume()
                    if matches(subject, target, law["match"]):
                        targets.append(target)
                if law["cardinality"] == "exactly-one" and len(targets) != 1:
                    failures.append((subject, None))
            return failures
        if operator == "require-unique":
            fields = [*law["scope"], *law["key"]]
            first_by_key = {}
            failures = []
            for item in relations[law["relation"]]:
                consume()
                key = tuple(item["values"][field] for field in fields)
                previous = first_by_key.get(key)
                if previous is None:
                    first_by_key[key] = item
                else:
                    failures.append((item, previous))
            return failures
        raise AssertionError(
            f"reference consumer observed unknown resolution law: {operator}"
        )

    resolution_meta = kernel["meta_format"]["resolution_judgment"]
    operations = {item["id"]: item for item in resolution_meta["operations"]}

    def resolution_pointer(code: str) -> str:
        if code == "language.package_unavailable":
            for index, namespace in enumerate(canonical_source["package_requirements"]):
                if namespace not in packages_by_coordinate:
                    return authored_pointer(("package_requirements", index))
        return ""

    for stage in resolution_meta["stage_order"]:
        stage_steps = base_steps

        def consume_stage() -> None:
            nonlocal stage_steps
            if stage_steps >= step_limit:
                raise BudgetExhausted
            stage_steps += 1

        stage_diagnostics = list(diagnostics_by_stage.get(stage, []))
        try:
            for judgment in profile["judgment_chain"]:
                operation = operations[judgment["operation"]]
                if operation["stage"] != stage:
                    continue
                law = operation["law"]
                for item, _previous in law_failures(law, consume_stage):
                    code = reasons[judgment["reason"]]["diagnostic"]
                    pointer = item["pointers"].get(
                        law["pointer_field"],
                        resolution_pointer(code),
                    )
                    stage_diagnostics.append((code, pointer))
        except BudgetExhausted:
            return ((resource_diagnostic, ""),)
        if stage_diagnostics:
            return tuple(dict.fromkeys(stage_diagnostics))
    checked = ModelSourceContext(
        source=source,
        source_projection=source_projection,
        source_identity=_reference_content_identity(
            profile["source_identity_domain"], source
        ),
        kernel=kernel,
        language_bundle=language_bundle,
        namespace_selection=_reference_namespace_selection(
            canonical_source, kernel, language_bundle
        ),
    )
    try:
        _reference_semantic_artifacts(checked)
    except _ReferenceRuntimeProjectionExhausted:
        reason = reasons[lowering["runtime_projection"]["resource_reason"]]
        return ((reason["diagnostic"], ""),)
    except (_ReferenceEntrypointError, _ReferenceSourceFactError) as error:
        return (
            (
                reasons[profile["structural_reason"]]["diagnostic"],
                authored_pointer(error.pointer),
            ),
        )
    except _ReferenceFormulaPairsError as error:
        return error.diagnostics
    except _ReferenceFormulaError as error:
        return (
            (reasons[error.reason_id]["diagnostic"], authored_pointer(error.pointer)),
        )
    except (KeyError, ValueError) as error:
        pointer = (
            authored_pointer(("formula_bindings",))
            if "formula" in str(error).lower() or "binding" in str(error).lower()
            else authored_pointer(("entrypoints",))
        )
        return ((reasons[profile["structural_reason"]]["diagnostic"], pointer),)
    return checked


def _renamed_reason_authorities(
    reason_id: str, diagnostic: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    kernel, candidate_ldb = mutable_authorities()
    language = candidate_ldb["language"]
    renamed_reason = f"{reason_id}.renamed"
    renamed_diagnostic = f"{diagnostic}.renamed"
    reason = next(item for item in language["reasons"] if item["id"] == reason_id)
    reason["id"] = renamed_reason
    reason["diagnostic"] = renamed_diagnostic
    for check in language["model_checks"]:
        if check["reason"] == reason_id:
            check["reason"] = renamed_reason
    for profile in language["resolution_profiles"]:
        if profile["structural_reason"] == reason_id:
            profile["structural_reason"] = renamed_reason
        for member in (
            "parse_reason",
            "source_byte_reason",
            "resource_reason",
            "experiment_binding_reason",
            "experiment_numeric_domain_reason",
        ):
            if profile[member] == reason_id:
                profile[member] = renamed_reason
        for category, reference in profile["formula_resolution"][
            "refusal_reasons"
        ].items():
            if reference == reason_id:
                profile["formula_resolution"]["refusal_reasons"][category] = (
                    renamed_reason
                )
        for judgment in profile["judgment_chain"]:
            if judgment["reason"] == reason_id:
                judgment["reason"] = renamed_reason
    for profile in language["template_admission_profiles"]:
        if profile["resource_diagnostic"] == diagnostic:
            profile["resource_diagnostic"] = renamed_diagnostic
        if profile["structural_diagnostic"] == diagnostic:
            profile["structural_diagnostic"] = renamed_diagnostic
        for judgment in profile["judgments"]:
            if judgment["diagnostic"] == diagnostic:
                judgment["diagnostic"] = renamed_diagnostic
    for lowering in language["model_lowerings"]:
        if lowering["runtime_projection"]["resource_reason"] == reason_id:
            lowering["runtime_projection"]["resource_reason"] = renamed_reason
        if lowering["admission_reason"] == reason_id:
            lowering["admission_reason"] = renamed_reason
    next(item for item in candidate_ldb["diagnostics"] if item["code"] == diagnostic)[
        "code"
    ] = renamed_diagnostic
    for vector in candidate_ldb["vectors"]:
        if vector.get("reason") == reason_id:
            vector["reason"] = renamed_reason
            vector["diagnostic"] = renamed_diagnostic
        expect = vector.get("expect")
        if isinstance(expect, dict) and isinstance(expect.get("diagnostics"), list):
            for item in expect["diagnostics"]:
                if isinstance(item, dict) and item.get("code") == diagnostic:
                    item["code"] = renamed_diagnostic
    for package in language["packages"]:
        package["exports"]["reasons"] = [
            renamed_reason if item == reason_id else item
            for item in package["exports"]["reasons"]
        ]
        package["exports"]["diagnostics"] = [
            renamed_diagnostic if item == diagnostic else item
            for item in package["exports"]["diagnostics"]
        ]
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted
    return kernel, candidate_ldb, renamed_diagnostic


def _reference_apply(
    language: dict[str, Any],
    invocation: dict[str, str],
    fact: dict[str, Any],
) -> dict[str, Any]:
    """Independent index-and-render implementation of Kernel rule mechanics."""
    index: dict[str, dict[str, Any]] = {}
    for rule in language["rules"]:
        if rule["id"] in index:
            raise AssertionError("reference lowerer observed ambiguous rules")
        index[rule["id"]] = rule
    rule = index[invocation["rule"]]
    assert rule["phase"] == invocation["phase"]
    assert rule["judgment"] == invocation["judgment"]
    assert [item["fact_kind"] for item in rule["premises"]] == [fact["kind"]]
    environment = {
        variable: fact["fields"][source_field]
        for variable, source_field in rule["premises"][0]["bind"].items()
    }

    def render(term: dict[str, Any]) -> Any:
        return term["value"] if term["tag"] == "literal" else environment[term["name"]]

    return {
        "kind": rule["conclusion"]["fact_kind"],
        "fields": {
            name: render(term) for name, term in rule["conclusion"]["fields"].items()
        },
    }


def _reference_resolved_symbols(
    checked: ModelSourceContext,
) -> list[tuple[dict[str, Any], tuple[object, ...]]]:
    transport = checked.kernel["meta_format"]["language_definitions"]["collections"][
        "model_lowerings"
    ]["source_fact_transport"]
    if not _consumer_b_source_fact_transport_is_supported(transport):
        raise _ReferenceSourceFactError("", "Source Fact transport law is unsupported")
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    source = checked.source_projection.value
    requirements = set(source["package_requirements"])
    packages = {item["id"]: item for item in language["packages"]}
    model_id = source["manifest"]["id"]
    rows = []
    for module_index, module in enumerate(source["modules"]):
        imports = {item["alias"]: item for item in module["imports"]}
        for symbol_index, symbol in enumerate(module["symbols"]):
            imported = imports[symbol["type"]]
            package_key = imported["package"]
            assert package_key in requirements
            package = packages[package_key]
            assert imported["symbol"] in {
                item["id"] for item in package["exports"]["types"]
            }
            fields = {
                name: value
                for name, value in symbol.items()
                if name not in {"symbol", "type"}
            }
            adapters = [
                (profile["symbol_fact_member"], symbol["symbol"]),
                (
                    "resolved_symbol",
                    {
                        "model": model_id,
                        "module": module["id"],
                        "name": symbol["symbol"],
                    },
                ),
                (
                    "type_identity",
                    {
                        "package": package_key,
                        "id": imported["symbol"],
                    },
                ),
            ]
            targets = [name for name, _value in adapters] + ["value_kind"]
            if imported["symbol"] in package["exports"]["nominal_types"]:
                adapters.append(("value_kind", "nominal-structured"))
            pointer = (
                "modules",
                module_index,
                "symbols",
                symbol_index,
            )
            if len(set(targets)) != len(targets) or any(
                name in fields for name in targets
            ):
                raise _ReferenceSourceFactError(
                    _reference_pointer(list(pointer)),
                    "Source member conflicts with an initial Fact adapter",
                )
            fields.update(adapters)
            rows.append((fields, pointer))
    return sorted(
        rows,
        key=lambda item: (
            item[0]["resolved_symbol"]["model"],
            item[0]["resolved_symbol"]["module"],
            item[0]["resolved_symbol"]["name"],
        ),
    )


def _reference_artifact(
    checked: ModelSourceContext, artifact_kind: str, payload: dict[str, Any]
) -> dict[str, Any]:
    language = checked.language_bundle["language"]
    contract = next(
        item
        for item in language["artifact_contracts"]
        if item["schema_kind"]
        == next(
            row["artifact_kind"]
            for row in language["artifact_wire_schemas"]
            if row.get("protocol_role") == artifact_kind
        )
    )
    schema = next(
        item["schema"]
        for item in language["artifact_wire_schemas"]
        if item["artifact_kind"] == contract["schema_kind"]
    )
    wire_identity = _reference_content_identity(
        contract["wire_schema_identity_domain"],
        {key: value for key, value in schema.items() if key != "$id"},
    )
    body = {
        "artifact_kind": contract["artifact_kind"],
        "artifact_version": "2.0.0",
        "wire_schema_identity": wire_identity,
        **payload,
    }
    artifact = {
        **body,
        "content_identity": _reference_content_identity(
            contract["identity_domain"],
            {
                key: value
                for key, value in body.items()
                if key not in set(contract["identity_excluded_members"])
            },
        ),
    }
    jsonschema.Draft202012Validator(schema).validate(artifact)
    return artifact


def _reference_package_lock(checked: ModelSourceContext) -> dict[str, Any]:
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    available = {item["id"]: item for item in language["packages"]}
    requirements = sorted(checked.source_projection.value["package_requirements"])
    selected: dict[str, dict[str, Any]] = {}
    pending = list(requirements)
    dependency_edges = []
    while pending:
        namespace = pending.pop(0)
        package = available[namespace]
        if namespace in selected:
            continue
        selected[namespace] = package
        for dependency in sorted(package["dependencies"]["required"]):
            dependency_edges.append(
                {
                    "from_package": namespace,
                    "kind": "required",
                    "to_package": dependency,
                }
            )
            pending.append(dependency)
    selected_packages = [selected[name] for name in sorted(selected)]

    def definitions(package: dict[str, Any], authority_path: str) -> list[Any]:
        matches = [
            entry["definitions"]
            for entry in package["semantic_closure"]
            if entry["authority_path"] == authority_path
        ]
        assert len(matches) == 1 and isinstance(matches[0], list)
        return matches[0]

    providers: dict[str, str] = {}
    for package in selected_packages:
        for capability in package["capabilities"]["provided"]:
            assert capability not in providers
            providers[capability] = package["id"]
    for package in selected_packages:
        assert all(
            capability in providers
            for capability in package["capabilities"]["required"]
        )

    def exported(collection: str) -> list[dict[str, Any]]:
        rows = []
        for package in selected_packages:
            by_id = {
                item["id"]: item
                for item in definitions(package, f"language.{collection}")
            }
            rows.extend(
                {
                    "definition": by_id[identity],
                    "package": package["id"],
                }
                for identity in package["exports"][collection]
            )
        return sorted(
            rows, key=lambda item: (item["package"], item["definition"]["id"])
        )

    numeric_definitions = {
        item["id"]: item
        for package in selected_packages
        for item in definitions(package, "language.quantity.numeric_policies")
    }
    runtime_definitions = {
        item["id"]: item
        for package in selected_packages
        for item in definitions(package, "language.runtime_profiles")
    }
    numeric_profiles = sorted(
        {
            profile_id
            for package in selected_packages
            for profile_id in package["profiles"]["numeric"]
        }
    )
    runtime_profiles = sorted(
        {
            profile_id
            for package in selected_packages
            for profile_id in package["profiles"]["runtime"]
        }
    )
    diagnostics = sorted(
        {
            code
            for package in selected_packages
            for code in package["exports"]["diagnostics"]
        }
    )
    diagnostic_reasons = sorted(
        [
            reason
            for package in selected_packages
            for reason in definitions(package, "language.reasons")
            if reason["diagnostic"] in diagnostics
        ],
        key=lambda item: item["id"],
    )
    dependency_edges.sort(
        key=lambda item: (
            item["from_package"],
            item["to_package"],
        )
    )
    types = sorted(
        [
            {**exported_type, "package": package["id"]}
            for package in selected_packages
            for exported_type in package["exports"]["types"]
        ],
        key=lambda item: (item["package"], item["id"]),
    )
    payload = {
        "resolution_profile": profile,
        "root_requirements": requirements,
        "packages": [
            {
                "id": package["id"],
                "content_identity": package["content_identity"],
                "semantic_identity": package["semantic_identity"],
            }
            for package in selected_packages
        ],
        "package_semantic_closures": [
            {
                "package": package["id"],
                "semantic_identity": package["semantic_identity"],
                "definitions": _reference_package_runtime_closure(
                    package, checked.kernel
                ),
            }
            for package in selected_packages
        ],
        "dependency_edges": dependency_edges,
        "capability_bindings": [
            {
                "capability": capability,
                "provider_package": providers[capability],
            }
            for capability in sorted(providers)
        ],
        "types": types,
        "components": exported("components"),
        "conversions": exported("conversions"),
        "operations": exported("operations"),
        "numeric_profiles": [numeric_definitions[name] for name in numeric_profiles],
        "runtime_profiles": [runtime_definitions[name] for name in runtime_profiles],
        "diagnostics": diagnostics,
        "diagnostic_reasons": diagnostic_reasons,
        "language_rules": sorted(
            {
                rule
                for package in selected_packages
                for rule in package["exports"]["language_rules"]
            }
        ),
    }
    semantic_projection = {
        "packages": [
            {
                "id": package["id"],
                "semantic_identity": package["semantic_identity"],
            }
            for package in selected_packages
        ],
        "package_semantic_closures": payload["package_semantic_closures"],
        "capability_bindings": payload["capability_bindings"],
        "types": payload["types"],
        "components": payload["components"],
        "conversions": payload["conversions"],
        "operations": payload["operations"],
        "numeric_profiles": payload["numeric_profiles"],
        "runtime_profiles": payload["runtime_profiles"],
    }
    payload["selected_semantics"] = semantic_projection
    payload["semantic_identity"] = _reference_content_identity(
        "package-lock-selected-semantics-v2",
        semantic_projection,
    )
    return _reference_artifact(checked, "package-lock", payload)


def _reference_formula_contract(
    source_contract: dict[str, Any],
    imports: dict[str, dict[str, str]],
) -> dict[str, Any]:
    imported = imports[source_contract["type"]]
    return {
        key: deepcopy(value) for key, value in source_contract.items() if key != "type"
    } | {
        "type_identity": {
            "package": imported["package"],
            "id": imported["symbol"],
        }
    }


def _reference_formula_contract_matches_operation(
    formula_contract: dict[str, Any],
    operation_contract: dict[str, Any],
) -> bool:
    formula_type = formula_contract["type_identity"]
    operation_type = operation_contract["type"]
    actual_domain = formula_contract.get("domain")
    formal_domain = operation_contract.get("domain")
    domain_matches = formal_domain == {"kind": "actual"} or (
        actual_domain == formal_domain
        or (
            formula_contract.get("domain_kind") == "closed-interval"
            and isinstance(actual_domain, dict)
            and isinstance(formal_domain, dict)
            and formal_domain.get("kind") == "closed-interval"
            and all(
                isinstance(domain.get(member), int)
                and not isinstance(domain[member], bool)
                for domain in (actual_domain, formal_domain)
                for member in ("minimum", "maximum")
            )
            and formal_domain["minimum"] <= actual_domain["minimum"]
            and actual_domain["maximum"] <= formal_domain["maximum"]
        )
    )
    return (
        formula_type
        == {
            "package": operation_type["package"],
            "id": operation_type["id"],
        }
        and domain_matches
        and all(
            formula_contract[member] == operation_contract[member]
            for member in ("representation", "kind", "unit", "numeric_policy")
        )
    )


def _reference_selected_operation_coordinates(
    checked: ModelSourceContext,
    lock: dict[str, Any],
    formula_roots: set[tuple[str, str]],
    *,
    consume_instruction: Callable[[], None] | None = None,
) -> set[tuple[str, str]]:
    operations = {
        (
            row["package"],
            row["definition"]["id"],
        ): row["definition"]
        for row in lock["operations"]
    }
    selected = {
        (
            entrypoint["operation"]["package"],
            entrypoint["operation"]["id"],
        )
        for entrypoint in checked.source_projection.value["entrypoints"]
    } | formula_roots
    reference_nodes = {
        node["id"]
        for node in checked.kernel["meta_format"]["runtime_program"]["nodes"]
        if "operation" in node["required_members"]
    }

    def references(body: list[dict[str, Any]]) -> set[tuple[str, str]]:
        coordinates = set()
        for instruction in body:
            if consume_instruction is not None:
                consume_instruction()
            if instruction["node"] in reference_nodes:
                coordinates.add(
                    (
                        instruction["operation"]["package"],
                        instruction["operation"]["id"],
                    )
                )
            if isinstance(instruction.get("body"), list):
                coordinates.update(references(instruction["body"]))
        return coordinates

    pending = list(selected)
    while pending:
        operation = operations.get(pending.pop())
        if operation is None:
            continue
        for dependency in references(operation.get("body", [])):
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return selected


def _reference_formula_phases(kernel: dict[str, Any]) -> tuple[str, str, str]:
    runtime = kernel["meta_format"]["runtime_program"]
    configuration = runtime["runtime_configuration"]
    return (
        configuration["formula_initialization_phase"],
        configuration["lifecycle_roles"]["active"],
        runtime["scheduler"]["observation"]["phase"],
    )


def _reference_invocation_node_ids(kernel: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        row["id"]
        for row in kernel["meta_format"]["runtime_program"]["nodes"]
        if row.get("semantics", {}).get("operator") == "invoke-operation"
    )


def _reference_formulas_and_bindings(
    checked: ModelSourceContext,
    declarations: list[dict[str, Any]],
    lock: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    available = {
        (row["package"], row["definition"]["id"]) for row in lock["operations"]
    }
    source = checked.source_projection.value
    for index, entrypoint in enumerate(source["entrypoints"]):
        reference = entrypoint["operation"]
        if (reference["package"], reference["id"]) not in available:
            member = (
                "package"
                if reference["package"] not in {row["id"] for row in lock["packages"]}
                else "id"
            )
            raise _ReferenceEntrypointError(
                _reference_pointer(["entrypoints", index, "operation", member]),
                "entrypoint Operation is not selected",
            )
    policy = profile["formula_resolution"]
    domains = policy["identity_domains"]
    formula_contexts = {
        phase: {"phase": phase} for phase in _reference_formula_phases(checked.kernel)
    }
    actual_operand_domain = checked.kernel["meta_format"]["runtime_program"][
        "invocation_contract"
    ]["identity_domains"]["actual_operand"]
    invocation_node_ids = _reference_invocation_node_ids(checked.kernel)
    declarations_by_source = {
        (
            declaration["resolved_symbol"]["module"],
            declaration["resolved_symbol"]["name"],
        ): declaration
        for declaration in declarations
    }
    prototypes: dict[tuple[str, str], dict[str, Any]] = {}
    dependencies: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for module_index, module in enumerate(source["modules"]):
        module_id = module["id"]
        imports = {
            item["alias"]: {
                "package": item["package"],
                "symbol": item["symbol"],
            }
            for item in module["imports"]
        }
        for formula_index, source_formula in enumerate(module.get("formulas", [])):
            key = (module_id, source_formula["id"])
            source_body = normalize_semantic_body(
                deepcopy(source_formula["body"]),
                checked.language_bundle,
                kernel=checked.kernel,
            )
            inline_kind, inline_reference, _inline_member = _inline_source_parameter(
                checked.kernel, checked.language_bundle
            )
            if source_body.get("node") == inline_kind:
                source_body = {
                    "nodes": [],
                    "result": {
                        "kind": inline_kind,
                        inline_reference: source_body[inline_reference],
                    },
                }
            parameters = [
                {
                    "id": parameter["id"],
                    **_reference_formula_contract(parameter, imports),
                }
                for parameter in source_formula["parameters"]
            ]
            parameters.sort(key=lambda item: item["id"])
            prototypes[key] = {
                "module": module_id,
                "id": source_formula["id"],
                "parameters": parameters,
                "result": _reference_formula_contract(
                    source_formula["result"],
                    imports,
                ),
                "imports": imports,
                "source_body": source_body,
                "expression": source_formula["expression"],
                "pointer": f"/modules/{module_index}/formulas/{formula_index}",
            }
            dependencies[key] = [
                (node["formula"]["module"], node["formula"]["id"])
                for node in source_body["nodes"]
                if node["node"] == "formula-call"
            ]

    order: list[tuple[str, str]] = []
    visited: set[tuple[str, str]] = set()

    def visit(key: tuple[str, str]) -> None:
        if key in visited:
            return
        for dependency in dependencies[key]:
            visit(dependency)
        visited.add(key)
        order.append(key)

    for key in sorted(prototypes):
        visit(key)

    operations = {
        (
            row["package"],
            row["definition"]["id"],
        ): row["definition"]
        for row in lock["operations"]
    }

    def operation_identity(coordinate: tuple[str, str]) -> str:
        return _reference_content_identity(
            domains["operation"],
            {
                "package": coordinate[0],
                "id": coordinate[1],
            },
        )

    def operand(
        source_operand: dict[str, Any],
        parameters: dict[str, dict[str, Any]],
        locals_: dict[str, dict[str, Any]],
        expected: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        kind = source_operand["kind"]
        if kind == "parameter":
            body = {
                "kind": kind,
                "parameter": source_operand["parameter"],
            }
            contract = parameters[source_operand["parameter"]]
        elif kind == "local":
            body = {"kind": kind, "local": source_operand["local"]}
            contract = locals_[source_operand["local"]]
        elif kind == "symbol":
            declaration = declarations_by_source[
                (source_operand["module"], source_operand["symbol"])
            ]
            body = {
                "kind": kind,
                "resolved_symbol": declaration["resolved_symbol"],
            }
            contract = declaration
        else:
            assert kind == "literal" and expected is not None
            body = {"kind": kind, "value": source_operand["value"]}
            contract = expected
        return (
            {
                **body,
                "identity": _reference_content_identity(
                    actual_operand_domain,
                    body,
                ),
            },
            contract,
        )

    resolved: dict[tuple[str, str], dict[str, Any]] = {}
    for key in order:
        prototype = prototypes[key]
        parameters = {item["id"]: item for item in prototype["parameters"]}
        locals_: dict[str, dict[str, Any]] = {}
        nodes: list[dict[str, Any]] = []
        formula_dependencies: set[str] = set()
        operation_dependencies: set[str] = set()
        refusals: set[str] = set()
        max_steps = 0
        termination_measure = 1
        for source_node in prototype["source_body"]["nodes"]:
            node_id = source_node["id"]
            if source_node["node"] == "formula-call":
                called = resolved[
                    (
                        source_node["formula"]["module"],
                        source_node["formula"]["id"],
                    )
                ]
                called_parameters = {item["id"]: item for item in called["parameters"]}
                arguments = [
                    {
                        "parameter": argument["parameter"],
                        "operand": operand(
                            argument["operand"],
                            parameters,
                            locals_,
                            called_parameters[argument["parameter"]],
                        )[0],
                    }
                    for argument in source_node["arguments"]
                ]
                arguments.sort(key=lambda item: item["parameter"])
                result = called["result"]
                body = {
                    "id": node_id,
                    "node": "formula-call",
                    "formula": {
                        "module": called["module"],
                        "id": called["id"],
                        "identity": called["identity"],
                    },
                    "arguments": arguments,
                    "result": result,
                }
                formula_dependencies.add(called["identity"])
                formula_dependencies.update(called["closure"]["formula_dependencies"])
                operation_dependencies.update(
                    called["closure"]["operation_dependencies"]
                )
                refusals.update(called["closure"]["refusals"])
                max_steps += (
                    policy["resource_charge_per_node"]
                    + called["closure"]["resource_charge"]["max_steps"]
                )
                termination_measure = max(
                    termination_measure,
                    1 + called["closure"]["termination_measure"],
                )
            elif source_node["node"] == "operation-call":
                coordinate = (
                    source_node["operation"]["package"],
                    source_node["operation"]["id"],
                )
                operation = operations[coordinate]
                ports = {item["id"]: item for item in operation["inputs"]}
                arguments = []
                for argument in source_node["arguments"]:
                    formal = ports[argument["port"]]
                    source_operand = argument["operand"]
                    if source_operand["kind"] == "literal":
                        profile_matches = [
                            item
                            for item in language["literal_typing_profiles"]
                            if item.get("source_kind") == "integer"
                            and item["minimum"]
                            <= source_operand["value"]
                            <= item["maximum"]
                            and item["type"] == formal["type"]
                            and all(
                                item[member] == formal[member]
                                for member in (
                                    "representation",
                                    "kind",
                                    "unit",
                                    "domain",
                                    "numeric_policy",
                                )
                            )
                        ]
                        assert len(profile_matches) == 1
                        operand_body = {
                            "kind": "literal",
                            "value": source_operand["value"],
                        }
                        actual = {
                            **operand_body,
                            "identity": _reference_content_identity(
                                actual_operand_domain,
                                operand_body,
                            ),
                        }
                    else:
                        actual, _ = operand(
                            source_operand,
                            parameters,
                            locals_,
                        )
                    arguments.append({"port": argument["port"], "operand": actual})
                arguments.sort(key=lambda item: item["port"])
                try:
                    _reference_inline_pure_scalar_operation(
                        coordinate,
                        operations,
                        {
                            argument["port"]: argument["operand"]
                            for argument in arguments
                        },
                        prefix=f"check.{prototype['module']}.{prototype['id']}.{node_id}",
                        reference=lambda _value: "operand",
                        local=lambda name: {"kind": "local", "local": name},
                        literal=lambda value: {"kind": "literal", "literal": value},
                        emit=lambda _instruction: None,
                        invocation_node_ids=invocation_node_ids,
                    )
                except ValueError as error:
                    raise _ReferenceFormulaError(
                        policy["refusal_reasons"]["type-mismatch"],
                        f"{prototype['pointer']}/expression",
                        str(error),
                    ) from error
                result = _reference_formula_contract(
                    source_node["result"],
                    prototype["imports"],
                )
                identity = operation_identity(coordinate)
                body = {
                    "id": node_id,
                    "node": "operation-call",
                    "operation": {
                        "package": coordinate[0],
                        "id": coordinate[1],
                        "identity": identity,
                    },
                    "arguments": arguments,
                    "result": result,
                }
                operation_dependencies.add(identity)
                refusals.update(operation["refusals"])
                max_steps += (
                    policy["resource_charge_per_node"]
                    + operation["resource_bounds"]["max_steps"]
                )
            else:
                assert source_node["node"] == "conditional"
                condition, _ = operand(
                    source_node["condition"],
                    parameters,
                    locals_,
                )
                when_true, result = operand(
                    source_node["when_true"],
                    parameters,
                    locals_,
                )
                when_false, _ = operand(
                    source_node["when_false"],
                    parameters,
                    locals_,
                    result,
                )
                body = {
                    "id": node_id,
                    "node": "conditional",
                    "condition": condition,
                    "when_true": when_true,
                    "when_false": when_false,
                    "result": {
                        member: value
                        for member, value in result.items()
                        if member != "id"
                    },
                }
                max_steps += policy["resource_charge_per_node"]
            node = {
                **body,
                "identity": _reference_content_identity(
                    domains["expression_node"],
                    body,
                ),
            }
            nodes.append(node)
            locals_[node_id] = body["result"]
        result_operand, _ = operand(
            prototype["source_body"]["result"],
            parameters,
            locals_,
            prototype["result"],
        )
        if result_operand["kind"] != "local":
            max_steps += policy["resource_charge_per_node"]
        formula_body = {
            "module": prototype["module"],
            "id": prototype["id"],
            "parameters": prototype["parameters"],
            "result": prototype["result"],
            "body": {"nodes": nodes, "result": result_operand},
            "closure": {
                "formula_dependencies": sorted(formula_dependencies),
                "operation_dependencies": sorted(operation_dependencies),
                "refusals": sorted(refusals),
                "resource_charge": {"max_steps": max_steps},
                "termination_measure": termination_measure,
            },
        }
        resolved[key] = {
            **formula_body,
            "expression": prototype["expression"],
            "identity": _reference_content_identity(
                domains["declaration"],
                formula_body,
            ),
        }

    source_bindings = source.get("formula_bindings", [])
    selected_keys = {
        (binding["formula"]["module"], binding["formula"]["id"])
        for binding in source_bindings
    }
    binding_pointers = {
        (binding["formula"]["module"], binding["formula"]["id"]): (
            _reference_pointer(["formula_bindings", index, "formula"])
        )
        for index, binding in enumerate(source_bindings)
    }
    pending = list(selected_keys)
    while pending:
        key = pending.pop()
        if key not in resolved:
            raise _ReferenceFormulaError(
                policy["refusal_reasons"]["binding-missing"],
                binding_pointers[key],
                "Formula binding names no declaration",
            )
        for dependency in dependencies[key]:
            if dependency not in selected_keys:
                selected_keys.add(dependency)
                pending.append(dependency)
    formulas = [resolved[key] for key in sorted(selected_keys)]
    slots = {}
    selected_operation_coordinates = _reference_selected_operation_coordinates(
        checked,
        lock,
        {
            (node["operation"]["package"], node["operation"]["id"])
            for formula in formulas
            for node in formula["body"]["nodes"]
            if node["node"] == "operation-call"
        },
    )
    for row in lock["operations"]:
        coordinate = (
            row["package"],
            row["definition"]["id"],
        )
        if coordinate not in selected_operation_coordinates:
            continue
        identity = operation_identity(coordinate)
        for slot in (
            row["definition"].get("extensions", {}).get("standard.formula-slots", [])
        ):
            slots[(*coordinate, slot["id"])] = (slot, identity)

    bindings = []
    bound_slots: set[tuple[str, str, str]] = set()
    for binding_index, source_binding in enumerate(source_bindings):
        formula_key = (
            source_binding["formula"]["module"],
            source_binding["formula"]["id"],
        )
        if formula_key not in resolved:
            raise _ReferenceFormulaError(
                policy["refusal_reasons"]["binding-missing"],
                _reference_pointer(
                    [
                        "formula_bindings",
                        binding_index,
                        "formula",
                    ]
                ),
                "Formula binding names no declaration",
            )
        formula = resolved[formula_key]
        if source_binding["site"]["kind"] == "operation-slot":
            source_operation = source_binding["site"]["operation"]
            key = (
                source_operation["package"],
                source_operation["id"],
                source_binding["site"]["slot"],
            )
            if key not in slots or key in bound_slots:
                raise _ReferenceFormulaError(
                    (
                        policy["refusal_reasons"]["binding-duplicate"]
                        if key in bound_slots
                        else policy["refusal_reasons"]["unreachable"]
                    ),
                    _reference_pointer(
                        [
                            "formula_bindings",
                            binding_index,
                            "site",
                        ]
                    ),
                    "Formula binding site is not one unique selected Operation slot",
                )
            slot, operation_identity_value = slots[key]
            active = checked.kernel["meta_format"]["runtime_program"][
                "runtime_configuration"
            ]["lifecycle_roles"]["active"]
            if slot.get("context") != formula_contexts[active]:
                raise _ReferenceFormulaError(
                    policy["refusal_reasons"]["context-mismatch"],
                    _reference_pointer(
                        [
                            "formula_bindings",
                            binding_index,
                            "site",
                        ]
                    ),
                    "Formula Operation slot has no admitted lifecycle context",
                )
            bound_slots.add(key)
            arguments = []
            for argument in source_binding["arguments"]:
                operand_body = {
                    "kind": "slot-parameter",
                    "parameter": argument["operand"]["parameter"],
                }
                arguments.append(
                    {
                        "parameter": argument["parameter"],
                        "operand": {
                            **operand_body,
                            "identity": _reference_content_identity(
                                actual_operand_domain,
                                operand_body,
                            ),
                        },
                    }
                )
            site_bodies = [
                {
                    "kind": "operation-slot",
                    "operation": {
                        "package": key[0],
                        "id": key[1],
                        "identity": operation_identity_value,
                    },
                    "slot": key[2],
                    "context": slot["context"],
                }
            ]
        else:
            site = source_binding["site"]
            declaration = declarations_by_source[(site["module"], site["symbol"])]
            arguments = [
                {
                    "parameter": argument["parameter"],
                    "operand": operand(
                        argument["operand"],
                        {},
                        {},
                    )[0],
                }
                for argument in source_binding["arguments"]
            ]
            site_bodies = [
                {
                    "kind": "derived-symbol",
                    "context": formula_contexts[phase],
                    "resolved_symbol": declaration["resolved_symbol"],
                }
                for phase in formula_contexts
            ]
        arguments.sort(key=lambda item: item["parameter"])
        for site_body in site_bodies:
            site = {
                **site_body,
                "identity": _reference_content_identity(
                    domains["evaluation_site"],
                    site_body,
                ),
            }
            binding_body = {
                "site": site,
                "formula": {
                    "module": formula["module"],
                    "id": formula["id"],
                    "identity": formula["identity"],
                },
                "arguments": arguments,
            }
            bindings.append(
                {
                    **binding_body,
                    "identity": _reference_content_identity(
                        domains["binding"],
                        binding_body,
                    ),
                }
            )
    bindings.sort(key=lambda item: item["identity"])
    if bound_slots != set(slots):
        raise _ReferenceFormulaError(
            policy["refusal_reasons"]["binding-missing"],
            _reference_pointer(["entrypoints", 0, "operation"]),
            "every selected Operation Formula slot requires exactly one binding",
        )
    return formulas, bindings


def _reference_inline_pure_scalar_operation(
    coordinate: tuple[str, str],
    operations: dict[tuple[str, str], dict[str, Any]],
    arguments: dict[str, dict[str, Any]],
    *,
    prefix: str,
    reference: Callable[[dict[str, Any]], str],
    local: Callable[[str], dict[str, Any]],
    literal: Callable[[JsonValue], dict[str, Any]],
    emit: Callable[[dict[str, Any]], None],
    invocation_node_ids: frozenset[str],
    result_target: str | None = None,
    stack: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any] | None:
    """Independently lower one scalar Operation and its lexical invoke graph."""
    if coordinate in stack:
        raise ValueError("independent Formula Operation graph is recursive")
    operation = operations[coordinate]
    if set(arguments) != {row["id"] for row in operation["inputs"]}:
        raise ValueError("independent Formula Operation arguments are incomplete")
    values = dict(arguments)
    operation_results: dict[str, dict[str, Any] | None] = {}
    result_source = operation["result"]["source"]
    returned_local = (
        result_source.get("name") if result_source["kind"] == "local" else None
    )
    for index, instruction in enumerate(operation["body"]):
        target = f"{prefix}.{index}"
        if instruction["node"] in invocation_node_ids:
            child_arguments = {}
            for argument in instruction["arguments"]:
                operand = argument["operand"]
                kind = operand["kind"]
                if kind in {"port", "local"}:
                    value = values[operand[kind]]
                elif kind == "literal":
                    value = literal(operand["literal"])
                else:
                    raise ValueError(
                        "independent Formula Operation operand has no scalar lowering"
                    )
                child_arguments[argument["port"]] = value
            child = instruction["operation"]
            child_result = _reference_inline_pure_scalar_operation(
                (child["package"], child["id"]),
                operations,
                child_arguments,
                prefix=target,
                reference=reference,
                local=local,
                literal=literal,
                emit=emit,
                invocation_node_ids=invocation_node_ids,
                stack=(*stack, coordinate),
            )
            binding = instruction["result"]
            if result_target is not None and (
                (binding["kind"] == "local" and binding.get("name") == returned_local)
                or (
                    result_source["kind"] == "operation-result"
                    and result_source["site"] == instruction["site"]
                )
            ):
                target = result_target
            if child_result is None:
                raise ValueError(
                    "independent Formula Unit invocation has no scalar lowering"
                )
            emit(
                {
                    "node": "copy",
                    "target": target,
                    "value": reference(child_result),
                }
            )
            child_result = local(target)
            operation_results[instruction["site"]] = child_result
            if binding["kind"] == "local":
                if child_result is None:
                    raise ValueError(
                        "independent Formula Unit result cannot bind a scalar local"
                    )
                values[binding["name"]] = child_result
            elif binding["kind"] not in {"operation-result", "discard"}:
                raise ValueError("independent Formula Operation result is malformed")
            continue
        source_target = instruction.get("target")
        if not isinstance(source_target, str):
            raise ValueError(
                "independent Formula Operation instruction has no scalar result"
            )
        if result_target is not None and source_target == returned_local:
            target = result_target
        compiled = {"node": instruction["node"], "target": target}
        for member, value in instruction.items():
            if member in {"node", "target"}:
                continue
            if member == "literal":
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError(
                        "independent Formula Operation literal is not an integer"
                    )
                compiled[member] = value
            elif isinstance(value, str) and value in values:
                compiled[member] = reference(values[value])
            else:
                raise ValueError(
                    "independent Formula Operation body has no scalar lowering"
                )
        emit(compiled)
        values[source_target] = local(target)
    if result_source["kind"] in {"local", "port"}:
        return values[result_source["name"]]
    if result_source["kind"] == "operation-result":
        return operation_results[result_source["site"]]
    if result_source["kind"] == "unit":
        return None
    raise ValueError("independent Formula Operation result source is unresolved")


def _reference_specialize_formula_slots(
    selected_semantics: dict[str, Any],
    formulas: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    invocation_node_ids: frozenset[str],
) -> dict[str, Any]:
    specialized = deepcopy(selected_semantics)

    operations = {
        (
            row["package"],
            row["definition"]["id"],
        ): row["definition"]
        for row in specialized["operations"]
    }
    formulas_by_identity = {item["identity"]: item for item in formulas}

    def runtime_operand(
        value: dict[str, Any],
        parameter_sources: dict[str, dict[str, Any]],
        local_sources: dict[str, dict[str, Any]],
        snapshot_sources: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if value["kind"] == "parameter":
            return parameter_sources[value["parameter"]]
        if value["kind"] == "local":
            return local_sources[value["local"]]
        if value["kind"] == "symbol":
            alias = f"formula.snapshot.{value['identity']}"
            snapshot_sources[alias] = value["resolved_symbol"]
            return {"kind": "local", "local": alias}
        return {"kind": "literal", "literal": value["value"]}

    def reference(value: dict[str, Any]) -> str:
        return value["port"] if value["kind"] == "port" else value["local"]

    def compile_formula(
        formula: dict[str, Any],
        parameter_sources: dict[str, dict[str, Any]],
        result_target: str,
        prefix: str,
        snapshot_sources: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        instructions = []
        local_sources: dict[str, dict[str, Any]] = {}
        final_local = (
            formula["body"]["result"]["local"]
            if formula["body"]["result"]["kind"] == "local"
            else None
        )
        for node in formula["body"]["nodes"]:
            node_id = node["id"]
            target = result_target if node_id == final_local else f"{prefix}.{node_id}"
            if node["node"] == "operation-call":
                operation_ref = node["operation"]
                child_values = {
                    argument["port"]: runtime_operand(
                        argument["operand"],
                        parameter_sources,
                        local_sources,
                        snapshot_sources,
                    )
                    for argument in node["arguments"]
                }
                called_result = _reference_inline_pure_scalar_operation(
                    (operation_ref["package"], operation_ref["id"]),
                    operations,
                    child_values,
                    prefix=f"{prefix}.{node_id}",
                    reference=reference,
                    local=lambda name: {"kind": "local", "local": name},
                    literal=lambda value: {"kind": "literal", "literal": value},
                    emit=instructions.append,
                    invocation_node_ids=invocation_node_ids,
                    result_target=target,
                )
                if called_result is None:
                    raise ValueError(
                        "independent Formula Unit result cannot bind a scalar result"
                    )
                if called_result != {"kind": "local", "local": target}:
                    instructions.append(
                        {
                            "node": "copy",
                            "target": target,
                            "value": reference(called_result),
                        }
                    )
                else:
                    instructions.append(
                        {"node": "copy", "target": target, "value": target}
                    )
            elif node["node"] == "conditional":
                instructions.append(
                    {
                        "node": "if",
                        "target": target,
                        "condition": reference(
                            runtime_operand(
                                node["condition"],
                                parameter_sources,
                                local_sources,
                                snapshot_sources,
                            )
                        ),
                        "when_true": reference(
                            runtime_operand(
                                node["when_true"],
                                parameter_sources,
                                local_sources,
                                snapshot_sources,
                            )
                        ),
                        "when_false": reference(
                            runtime_operand(
                                node["when_false"],
                                parameter_sources,
                                local_sources,
                                snapshot_sources,
                            )
                        ),
                    }
                )
            else:
                called = formulas_by_identity[node["formula"]["identity"]]
                called_sources = {
                    argument["parameter"]: runtime_operand(
                        argument["operand"],
                        parameter_sources,
                        local_sources,
                        snapshot_sources,
                    )
                    for argument in node["arguments"]
                }
                instructions.extend(
                    compile_formula(
                        called,
                        called_sources,
                        target,
                        f"{prefix}.{node_id}",
                        snapshot_sources,
                    )
                )
                instructions.append({"node": "copy", "target": target, "value": target})
            local_sources[node_id] = {"kind": "local", "local": target}
        result = runtime_operand(
            formula["body"]["result"],
            parameter_sources,
            local_sources,
            snapshot_sources,
        )
        if result != {"kind": "local", "local": result_target}:
            instructions.append(
                (
                    {
                        "node": "constant",
                        "target": result_target,
                        "literal": result["literal"],
                    }
                    if result["kind"] == "literal"
                    else {
                        "node": "copy",
                        "target": result_target,
                        "value": reference(result),
                    }
                )
            )
        return instructions

    replacements: dict[
        tuple[str, str],
        list[tuple[int, int, list[dict[str, Any]], str]],
    ] = {}
    snapshot_sources_by_operation: dict[
        tuple[str, str],
        dict[str, dict[str, Any]],
    ] = {}
    for binding in bindings:
        site = binding["site"]
        if site["kind"] != "operation-slot":
            continue
        operation_ref = site["operation"]
        coordinate = (
            operation_ref["package"],
            operation_ref["id"],
        )
        operation = operations[coordinate]
        slot = next(
            item
            for item in operation["extensions"]["standard.formula-slots"]
            if item["id"] == site["slot"]
        )
        slot_parameters = {item["id"]: item for item in slot["parameters"]}
        parameter_sources = {}
        for argument in binding["arguments"]:
            slot_parameter = slot_parameters[argument["operand"]["parameter"]]
            source = slot_parameter["source"]
            parameter_sources[argument["parameter"]] = {
                "kind": "port" if source["kind"] == "port" else "local",
                "port" if source["kind"] == "port" else "local": source["name"],
            }
        formula = formulas_by_identity[binding["formula"]["identity"]]
        snapshot_sources = snapshot_sources_by_operation.setdefault(coordinate, {})
        compiled = compile_formula(
            formula,
            parameter_sources,
            slot["target"],
            f"formula.{site['slot']}",
            snapshot_sources,
        )
        start = slot["placeholder_index"]
        replacements.setdefault(coordinate, []).append(
            (
                start,
                slot["placeholder_length"],
                compiled,
                site["identity"],
            )
        )

    for coordinate, operation_replacements in replacements.items():
        operation = operations[coordinate]
        ordered = sorted(operation_replacements, key=lambda row: row[0])
        occupied = {port["id"] for port in operation["inputs"]}
        occupied.update(
            instruction["target"]
            for instruction in operation["body"]
            if isinstance(instruction.get("target"), str)
        )
        occupied.update(
            instruction["target"]
            for _, _, compiled, _ in ordered
            for instruction in compiled
            if isinstance(instruction.get("target"), str)
        )
        next_charge = 0
        for _, _, compiled, _ in ordered:
            for instruction in compiled:
                if (
                    instruction.get("node") == "copy"
                    and instruction["target"] == instruction["value"]
                ):
                    while f"formula.invocation-charge.{next_charge}" in occupied:
                        next_charge += 1
                    name = f"formula.invocation-charge.{next_charge}"
                    instruction["target"] = name
                    occupied.add(name)
                    next_charge += 1
        for start, length, compiled, _site_identity in reversed(ordered):
            operation["body"][start : start + length] = compiled
        snapshot_sources = snapshot_sources_by_operation.get(coordinate, {})
        if snapshot_sources:
            operation["extensions"]["standard.snapshot-operands"] = {
                "kind": "pre-event-snapshot-symbols",
                "operands": [
                    {
                        "name": name,
                        "resolved_symbol": resolved_symbol,
                    }
                    for name, resolved_symbol in sorted(snapshot_sources.items())
                ],
            }
        provenance = operation["extensions"].setdefault(
            "standard.instruction-provenance",
            {
                "kind": "instruction-evaluation-sites",
                "sites": [],
            },
        )
        shift = 0
        for start, length, compiled, site_identity in ordered:
            final_start = start + shift
            provenance["sites"].extend(
                {
                    "instruction_index": final_start + index,
                    "evaluation_site_identity": site_identity,
                }
                for index in range(len(compiled))
            )
            shift += len(compiled) - length

    specialized_operations = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in specialized["operations"]
    }
    for closure in specialized["package_semantic_closures"]:
        for entry in closure["definitions"]:
            if entry["authority_path"] != "language.operations":
                continue
            entry["definitions"] = [
                specialized_operations.get(
                    (closure["package"], definition["id"]),
                    definition,
                )
                for definition in entry["definitions"]
            ]
    return specialized


def _reference_initialization_programs(
    selected_semantics: dict[str, Any],
    formulas: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    checked: ModelSourceContext,
) -> list[dict[str, Any]]:
    """Independently compile derived bindings to generic value programs."""

    operations = {
        (
            row["package"],
            row["definition"]["id"],
        ): row["definition"]
        for row in selected_semantics["operations"]
    }
    formulas_by_identity = {row["identity"]: row for row in formulas}
    profile = next(
        row
        for row in checked.language_bundle["language"]["resolution_profiles"]
        if row["id"]
        == _reference_lowering(checked.language_bundle["language"])[
            "resolution_profile"
        ]
    )
    domains = profile["formula_resolution"]["identity_domains"]
    invocation_node_ids = _reference_invocation_node_ids(checked.kernel)
    programs = []
    for binding in bindings:
        site = binding["site"]
        if site["kind"] != "derived-symbol":
            continue
        inputs: dict[str, dict[str, Any]] = {}
        body = []
        literal_index = 0

        def add_input(name: str, operand: dict[str, Any]) -> dict[str, Any]:
            candidate = name
            suffix = 1
            while candidate in inputs and inputs[candidate] != operand:
                suffix += 1
                candidate = f"{name}.{suffix}"
            inputs[candidate] = operand
            return {"kind": "input", "name": candidate}

        parameter_sources = {
            argument["parameter"]: add_input(argument["parameter"], argument["operand"])
            for argument in binding["arguments"]
        }

        def source(
            operand: dict[str, Any],
            parameters: dict[str, dict[str, Any]],
            locals_: dict[str, dict[str, Any]],
            prefix: str,
        ) -> dict[str, Any]:
            nonlocal literal_index
            if operand["kind"] == "parameter":
                return parameters[operand["parameter"]]
            if operand["kind"] == "local":
                return locals_[operand["local"]]
            if operand["kind"] == "symbol":
                symbol = operand["resolved_symbol"]
                return add_input(
                    f"symbol.{symbol['module']}.{symbol['name']}",
                    operand,
                )
            assert operand["kind"] == "literal"
            literal_index += 1
            return add_input(f"{prefix}.literal.{literal_index}", operand)

        def reference(value: dict[str, Any]) -> str:
            assert value["kind"] in {"input", "local"}
            return value["name"]

        def instruction_site(formula: dict[str, Any], node_id: str, prefix: str) -> str:
            return _reference_content_identity(
                domains["evaluation_site"],
                {
                    "kind": "initialization-instruction",
                    "root_site_identity": site["identity"],
                    "formula_identity": formula["identity"],
                    "node": node_id,
                    "path": prefix,
                },
            )

        def emit(instruction: dict[str, Any], site_identity: str) -> None:
            body.append(
                {
                    "evaluation_site_identity": site_identity,
                    "instruction": instruction,
                }
            )

        def compile_formula(
            formula: dict[str, Any],
            parameters: dict[str, dict[str, Any]],
            prefix: str,
        ) -> dict[str, Any]:
            locals_: dict[str, dict[str, Any]] = {}
            for node in formula["body"]["nodes"]:
                node_id = node["id"]
                target = f"{prefix}.{node_id}"
                site_identity = instruction_site(formula, node_id, prefix)
                if node["node"] == "operation-call":
                    operation_ref = node["operation"]
                    values = {
                        argument["port"]: source(
                            argument["operand"], parameters, locals_, prefix
                        )
                        for argument in node["arguments"]
                    }
                    result = _reference_inline_pure_scalar_operation(
                        (operation_ref["package"], operation_ref["id"]),
                        operations,
                        values,
                        prefix=target,
                        reference=reference,
                        local=lambda name: {"kind": "local", "name": name},
                        literal=lambda value: add_input(
                            f"{target}.$literal.{len(inputs)}",
                            {"kind": "literal", "value": value},
                        ),
                        emit=lambda compiled: emit(compiled, site_identity),
                        invocation_node_ids=invocation_node_ids,
                    )
                    if result is None:
                        raise ValueError(
                            "independent Formula Unit result cannot bind a scalar result"
                        )
                    emit(
                        {
                            "node": "copy",
                            "target": target,
                            "value": reference(result),
                        },
                        site_identity,
                    )
                elif node["node"] == "conditional":
                    emit(
                        {
                            "node": "if",
                            "target": target,
                            "condition": reference(
                                source(
                                    node["condition"],
                                    parameters,
                                    locals_,
                                    prefix,
                                )
                            ),
                            "when_true": reference(
                                source(
                                    node["when_true"],
                                    parameters,
                                    locals_,
                                    prefix,
                                )
                            ),
                            "when_false": reference(
                                source(
                                    node["when_false"],
                                    parameters,
                                    locals_,
                                    prefix,
                                )
                            ),
                        },
                        site_identity,
                    )
                else:
                    assert node["node"] == "formula-call"
                    called = formulas_by_identity[node["formula"]["identity"]]
                    called_result = compile_formula(
                        called,
                        {
                            argument["parameter"]: source(
                                argument["operand"],
                                parameters,
                                locals_,
                                prefix,
                            )
                            for argument in node["arguments"]
                        },
                        f"{prefix}.{node_id}",
                    )
                    emit(
                        {
                            "node": "copy",
                            "target": target,
                            "value": reference(called_result),
                        },
                        site_identity,
                    )
                locals_[node_id] = {"kind": "local", "name": target}
            result = source(
                formula["body"]["result"],
                parameters,
                locals_,
                prefix,
            )
            if formula["body"]["result"]["kind"] == "local":
                return result
            result_target = f"{prefix}.$result"
            emit(
                {
                    "node": "copy",
                    "target": result_target,
                    "value": reference(result),
                },
                instruction_site(formula, "$result", prefix),
            )
            return {"kind": "local", "name": result_target}

        formula = formulas_by_identity[binding["formula"]["identity"]]
        result = compile_formula(
            formula,
            parameter_sources,
            f"init.{site['identity']}",
        )
        max_steps = formula["closure"]["resource_charge"]["max_steps"]
        # A selected Operation's declared bound may exceed its current body.
        # Preserve that bound in the program and reject only an overrun.
        assert len(body) <= max_steps
        program = {
            "site": site,
            "target": site["resolved_symbol"],
            "inputs": [
                {"name": name, "operand": operand}
                for name, operand in sorted(inputs.items())
            ],
            "body": body,
            "result": result,
            "numeric_policy": formula["result"]["numeric_policy"],
            "resource_bounds": {"max_steps": max_steps},
            "refusals": formula["closure"]["refusals"],
        }
        programs.append(
            {
                **program,
                "identity": _reference_content_identity(
                    domains["initialization_program"],
                    program,
                ),
            }
        )
    return sorted(programs, key=lambda row: row["identity"])


def _reference_rir(
    checked: ModelSourceContext, lock: dict[str, Any] | None = None
) -> dict[str, Any]:
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    if lock is None:
        lock = _reference_package_lock(checked)
    declarations = []
    initial_facts = []
    for symbol, pointer in _reference_resolved_symbols(checked):
        rule_prefix = (
            "structured_" if symbol.get("value_kind") == "nominal-structured" else ""
        )
        fact = {"kind": lowering[f"{rule_prefix}initial_fact_kind"], "fields": symbol}
        if not _consumer_b_fact_is_closed(
            fact, checked.kernel["meta_format"], checked.language_bundle
        ):
            raise _ReferenceSourceFactError(
                _reference_pointer(list(pointer)), "Initial Source Fact is not closed"
            )
        initial_facts.append((fact, rule_prefix))
    for fact, rule_prefix in initial_facts:
        for invocation in lowering[f"{rule_prefix}rule_chain"]:
            fact = _reference_apply(language, invocation, fact)
        declarations.append(fact["fields"])
    from schema2_formula_conformance_support import pair_refusal

    profile = next(
        row
        for row in language["resolution_profiles"]
        if row["id"] == lowering["resolution_profile"]
    )
    policy = profile["formula_resolution"]
    reasons = {row["id"]: row for row in language["reasons"]}

    def authored_value(parts: tuple[object, ...]) -> Any:
        value: Any = checked.source
        for part in checked.source_projection.authored_parts(parts):
            value = value[part]
        return value

    source = checked.source_projection.value
    modules = source["modules"]
    authored_modules = authored_value(("modules",))
    pair_diagnostics = []
    for mi, module in enumerate(modules):
        for fi, _formula in enumerate(module.get("formulas", [])):
            authored_module = authored_value(("modules", mi))
            authored_formula = authored_value(("modules", mi, "formulas", fi))
            request = {
                "schema_version": authored_value(("schema_version",)),
                "package_requirements": authored_value(("package_requirements",)),
                "modules": authored_modules,
                "module": authored_module,
                "formula": authored_formula,
            }
            failure = pair_refusal(
                request, checked.language_bundle, kernel=checked.kernel
            )
            if failure is not None:
                category, member = failure
                reason_id = (
                    profile["structural_reason"]
                    if category is None
                    else policy["refusal_reasons"][category]
                )
                pair_diagnostics.append(
                    (
                        reasons[reason_id]["diagnostic"],
                        checked.source_projection.authored_pointer(
                            _reference_pointer(["modules", mi, "formulas", fi])
                        )
                        + _reference_pointer([member]),
                    )
                )
    if pair_diagnostics:
        ordered = sorted(set(pair_diagnostics), key=lambda row: (row[1], row[0]))
        raise _ReferenceFormulaPairsError(
            tuple(ordered[: checked.language_bundle["resources"]["max_diagnostics"]])
        )
    formulas, formula_bindings = _reference_formulas_and_bindings(
        checked,
        declarations,
        lock,
    )
    accounting = checked.kernel["meta_format"]["runtime_projection"][
        "resource_accounting"
    ]
    remaining = checked.language_bundle["resources"][accounting["limit_member"]]

    def consume() -> None:
        nonlocal remaining
        if remaining == 0:
            raise _ReferenceRuntimeProjectionExhausted
        remaining -= 1

    selected_semantics = _reference_runtime_projection(
        checked, lock, declarations, lowering, consume, formulas=formulas
    )
    initialization_programs = _reference_initialization_programs(
        selected_semantics,
        formulas,
        formula_bindings,
        checked,
    )
    selected_semantics = _reference_specialize_formula_slots(
        selected_semantics,
        formulas,
        formula_bindings,
        _reference_invocation_node_ids(checked.kernel),
    )
    payload = {
        "declarations": declarations,
        "formulas": formulas,
        "formula_bindings": formula_bindings,
        "initialization_programs": initialization_programs,
        "entrypoints": _reference_entrypoints(
            checked,
            declarations,
            selected_semantics,
            formula_bindings,
        ),
        "call_sites": _reference_call_sites(
            checked,
            selected_semantics,
            declarations=declarations,
        ),
        "selected_semantics": selected_semantics,
    }
    payload["selected_semantics"] = _reference_execution_closure(
        checked, payload, consume
    )
    semantic_domain, semantic_projection = _reference_rir_semantic_projection(
        checked.language_bundle,
        payload,
    )
    payload["semantic_identity"] = _reference_content_identity(
        semantic_domain,
        semantic_projection,
    )
    return _reference_artifact(
        checked,
        "rir-semantic-payload",
        payload,
    )


def _reference_exact_operation(
    operation_row: dict[str, Any],
) -> dict[str, str]:
    package = operation_row["package"]
    return {
        "package": package,
        "id": operation_row["definition"]["id"],
    }


def _reference_value_contract_matches(
    declaration: dict[str, Any],
    contract: dict[str, Any],
) -> bool:
    if declaration["type_identity"] != contract["type"]:
        return False
    if "value_kind" in declaration or "value_kind" in contract:
        return declaration.get("value_kind") == contract.get("value_kind")
    return all(
        declaration[member] == contract[member]
        for member in ("representation", "kind", "unit", "numeric_policy")
    )


def _reference_literal_context(
    value: Any,
    formal: dict[str, Any],
    checked: ModelSourceContext,
    selected_semantics: dict[str, Any],
) -> dict[str, Any] | None:
    law = checked.kernel["meta_format"]["literal_typing"]
    if law["selection"] != "unique-formal-match":
        return None
    profiles = [
        row["definition"] for row in selected_semantics["literal_typing_profiles"]
    ]
    if isinstance(value, dict):
        typed = law["typed_envelope_profile"]
        if set(value) != set(typed["admission"]["envelope_members"]):
            return None
        matches = [
            profile
            for profile in profiles
            if profile["source_kind"] == "typed-envelope"
            and profile["value_kind"] == typed["value_kind"]
            and formal.get("value_kind") == profile["value_kind"]
            and value[typed["type_member"]] == formal["type"]
        ]
        if len(matches) != 1 or not _consumer_b_operation_value_is_admitted(
            value,
            formal,
            ldb=checked.language_bundle,
            kernel=checked.kernel,
            resource_limit=checked.language_bundle["resources"]["max_rule_match_steps"],
        ):
            return None
        return {
            "id": matches[0]["id"],
            "type": value[typed["type_member"]],
            "value_kind": matches[0]["value_kind"],
        }
    if type(value) is bool:
        contract = checked.kernel["meta_format"]["runtime_program"][
            "fixed_value_contracts"
        ]["kernel-boolean"]
        if not _reference_operation_contract_matches(contract, formal):
            return None
        return {
            name: contract[name]
            for name in (
                "type",
                "representation",
                "kind",
                "unit",
                "domain",
                "numeric_policy",
            )
        }
    if type(value) is not int:
        return None
    matches = []
    for profile in profiles:
        if (
            profile["source_kind"] == "integer"
            and profile["minimum"] <= value <= profile["maximum"]
            and profile["type"] == formal["type"]
            and all(
                profile[member] == formal[member]
                for member in (
                    "representation",
                    "kind",
                    "unit",
                    "domain",
                    "numeric_policy",
                )
            )
        ):
            matches.append(profile)
    if len(matches) != 1:
        return None
    return {
        member: matches[0][member]
        for member in (
            "id",
            "type",
            "representation",
            "kind",
            "unit",
            "domain",
            "numeric_policy",
        )
    }


def _reference_assignment_mode(
    declaration: dict[str, Any],
    roles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    role = roles.get(declaration["role"])
    if role is None:
        raise ValueError("Symbol role has no assignment policy")
    matches = [
        mode
        for mode in role["modes"]
        if mode["id"] == declaration["value_policy"]["mode"]
    ]
    if len(matches) != 1:
        raise ValueError("Symbol value mode has no unique assignment contract")
    return matches[0]


def _reference_alias_rows(
    operation: dict[str, Any],
    aliases: dict[str, list[tuple[str, str]]],
) -> list[dict[str, Any]]:
    policy = operation["alias_policy"]
    writable_groups = {
        frozenset(group["ports"]): group["semantics"]
        for group in policy["writable_groups"]
    }
    rows = []
    for actual_identity, uses in aliases.items():
        if len(uses) < 2:
            continue
        ports = [name for name, _access in uses]
        if all(access == "read" for _name, access in uses):
            alias_policy = policy["read_only"]
        else:
            alias_policy = writable_groups.get(frozenset(ports))
            if alias_policy is None:
                raise ValueError("Operation does not admit this writable alias set")
        rows.append(
            {
                "actual_operand_identity": actual_identity,
                "ports": ports,
                "policy": alias_policy,
            }
        )
    return rows


def _reference_entrypoints(
    checked: ModelSourceContext,
    declarations: list[dict[str, Any]],
    selected_semantics: dict[str, Any],
    formula_bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lowering = _reference_lowering(checked.language_bundle["language"])
    policy = lowering["assignment_policy"]
    roles = {row["role"]: row for row in policy["roles"]}
    assert set(roles) == set(
        checked.language_bundle["language"]["quantity"]["symbol_roles"]
    )

    selected_namespaces = {row["id"] for row in selected_semantics["packages"]}
    operation_rows = selected_semantics["operations"]
    operations = {
        (
            row["package"],
            row["definition"]["id"],
        ): row
        for row in operation_rows
    }
    declarations_by_source = {
        (
            declaration["resolved_symbol"]["module"],
            declaration["resolved_symbol"]["name"],
        ): declaration
        for declaration in declarations
    }
    derived_dependencies: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for binding in formula_bindings:
        site = binding["site"]
        if site["kind"] != "derived-symbol":
            continue
        resolved_site = site["resolved_symbol"]
        derived_dependencies[(resolved_site["module"], resolved_site["name"])] = [
            declarations_by_source[
                (
                    argument["operand"]["resolved_symbol"]["module"],
                    argument["operand"]["resolved_symbol"]["name"],
                )
            ]
            for argument in binding["arguments"]
            if argument["operand"]["kind"] == "symbol"
        ]
    domains = checked.kernel["meta_format"]["runtime_program"]["invocation_contract"][
        "identity_domains"
    ]
    resolved_entrypoints = []
    seen: set[str] = set()
    for entrypoint_index, source_entrypoint in enumerate(
        checked.source_projection.value["entrypoints"]
    ):
        pointer = _reference_pointer(["entrypoints", entrypoint_index])
        entrypoint_id = source_entrypoint["id"]
        if entrypoint_id in seen:
            raise _ReferenceEntrypointError(
                f"{pointer}/id",
                "duplicate Model entrypoint",
            )
        seen.add(entrypoint_id)
        operation_ref = source_entrypoint["operation"]
        operation_row = operations.get(
            (
                operation_ref["package"],
                operation_ref["id"],
            )
        )
        if operation_row is None:
            member = (
                "package"
                if operation_ref["package"] not in selected_namespaces
                else "id"
            )
            raise _ReferenceEntrypointError(
                f"{pointer}/operation/{member}",
                "entrypoint Operation is not selected",
            )
        operation = operation_row["definition"]
        exact_operation = _reference_exact_operation(operation_row)
        formals = operation["inputs"]
        authored_arguments = source_entrypoint["arguments"]
        if [row["port"] for row in authored_arguments] != [
            row["id"] for row in formals
        ]:
            if len(authored_arguments) < len(formals):
                argument_pointer = f"{pointer}/arguments"
            else:
                mismatch = next(
                    (
                        index
                        for index, (actual, expected) in enumerate(
                            zip(
                                [row["port"] for row in authored_arguments],
                                [row["id"] for row in formals],
                                strict=False,
                            )
                        )
                        if actual != expected
                    ),
                    len(formals),
                )
                argument_pointer = f"{pointer}/arguments/{mismatch}/port"
            raise _ReferenceEntrypointError(
                argument_pointer,
                "entrypoint arguments do not close formal ports",
            )
        arguments = []
        aliases: dict[str, list[tuple[str, str]]] = {}
        initializers: dict[str, dict[str, Any]] = {}
        targets: dict[str, dict[str, Any]] = {}
        event_payload_targets: dict[str, dict[str, Any]] = {}
        event_reference_targets: dict[str, dict[str, Any]] = {}
        external_fact_targets: dict[str, dict[str, Any]] = {}

        def record_external_fact_target(
            declaration: dict[str, Any],
            resolved_symbol: dict[str, Any],
            target_identity: str,
        ) -> None:
            cardinality = _reference_assignment_mode(declaration, roles)[
                "external_fact_cardinality"
            ]
            if cardinality == "forbidden":
                return
            target = {
                "target": resolved_symbol,
                "target_identity": target_identity,
                "owner": "external-source",
                "cardinality": cardinality,
                "value_source": "external-input-fact",
                "value_contract": {
                    "type_identity": declaration["type_identity"],
                    "value_kind": "nominal-structured",
                }
                if declaration.get("value_kind") == "nominal-structured"
                else {
                    member: declaration[member]
                    for member in (
                        "type_identity",
                        "representation",
                        "kind",
                        "unit",
                        "domain_kind",
                        "domain",
                        "numeric_policy",
                    )
                },
            }
            previous = external_fact_targets.get(target_identity)
            if previous is not None and previous != target:
                raise ValueError("conflicting external Fact targets")
            external_fact_targets[target_identity] = target

        for argument_index, (formal, authored) in enumerate(
            zip(formals, authored_arguments, strict=True)
        ):
            operand_pointer = f"{pointer}/arguments/{argument_index}/operand"
            formal_body = {"operation": exact_operation, "name": formal["id"]}
            operand = authored["operand"]
            if operand["kind"] == "symbol":
                declaration = declarations_by_source.get(
                    (operand["module"], operand["symbol"])
                )
                if declaration is None or not _reference_value_contract_matches(
                    declaration, formal
                ):
                    raise _ReferenceEntrypointError(
                        operand_pointer,
                        "entrypoint Symbol is incompatible",
                    )
                access = formal["access"]
                role = declaration["role"]
                if access not in roles[role]["entrypoint_operand_access"]:
                    raise _ReferenceEntrypointError(
                        operand_pointer,
                        "entrypoint Symbol role is incompatible",
                    )
                symbol = declaration["resolved_symbol"]
                operand_body = {"kind": "symbol", "symbol": symbol}
                operand_identity = _reference_content_identity(
                    domains["actual_operand"], operand_body
                )
                resolved_operand = {
                    **operand_body,
                    "identity": operand_identity,
                }
                aliases.setdefault(operand_identity, []).append((formal["id"], access))
                value_policy = declaration["value_policy"]
                mode = _reference_assignment_mode(declaration, roles)
                if mode["experiment_cardinality"] != "forbidden":
                    target = {
                        "target": symbol,
                        "target_identity": operand_identity,
                        "owner": "experiment",
                        "initialization_source": "scenario-assignment",
                        "cardinality": mode["experiment_cardinality"],
                        "override": mode["override"],
                    }
                    previous = targets.get(operand_identity)
                    if previous is not None and previous != target:
                        raise ValueError("conflicting Scenario targets")
                    targets[operand_identity] = target
                if mode["event_payload_cardinality"] != "forbidden":
                    payload_target = {
                        "target": symbol,
                        "target_identity": operand_identity,
                        "owner": "experiment",
                        "value_source": "event-payload",
                        "cardinality": mode["event_payload_cardinality"],
                        "override": True,
                    }
                    previous_payload_target = event_payload_targets.get(
                        operand_identity
                    )
                    if (
                        previous_payload_target is not None
                        and previous_payload_target != payload_target
                    ):
                        raise ValueError("conflicting Event-local payload targets")
                    event_payload_targets[operand_identity] = payload_target
                record_external_fact_target(
                    declaration,
                    symbol,
                    operand_identity,
                )
                if mode["initialization_source"] in {
                    "model",
                    "model-with-experiment-override",
                }:
                    initializer = {
                        "target": symbol,
                        "target_identity": operand_identity,
                        "owner": "model",
                        "initialization_source": "value-policy",
                        "value": value_policy["value"],
                    }
                    previous = initializers.get(operand_identity)
                    if previous is not None and previous != initializer:
                        raise ValueError("conflicting Model initializers")
                    initializers[operand_identity] = initializer
                pending_dependencies = list(
                    derived_dependencies.get(
                        (
                            declaration["resolved_symbol"]["module"],
                            declaration["resolved_symbol"]["name"],
                        ),
                        [],
                    )
                )
                seen_dependencies: set[tuple[str, str]] = set()
                while pending_dependencies:
                    dependency = pending_dependencies.pop()
                    dependency_key = (
                        dependency["resolved_symbol"]["module"],
                        dependency["resolved_symbol"]["name"],
                    )
                    if dependency_key in seen_dependencies:
                        continue
                    seen_dependencies.add(dependency_key)
                    dependency_operand = {
                        "kind": "symbol",
                        "symbol": dependency["resolved_symbol"],
                    }
                    dependency_identity = _reference_content_identity(
                        domains["actual_operand"],
                        dependency_operand,
                    )
                    dependency_mode = _reference_assignment_mode(
                        dependency,
                        roles,
                    )
                    if dependency_mode["experiment_cardinality"] != "forbidden":
                        targets[dependency_identity] = {
                            "target": dependency["resolved_symbol"],
                            "target_identity": dependency_identity,
                            "owner": "experiment",
                            "initialization_source": "scenario-assignment",
                            "cardinality": dependency_mode["experiment_cardinality"],
                            "override": dependency_mode["override"],
                        }
                    if dependency_mode["event_payload_cardinality"] != "forbidden":
                        event_payload_targets[dependency_identity] = {
                            "target": dependency["resolved_symbol"],
                            "target_identity": dependency_identity,
                            "owner": "experiment",
                            "value_source": "event-payload",
                            "cardinality": dependency_mode["event_payload_cardinality"],
                            "override": True,
                        }
                    if dependency_mode["initialization_source"] in {
                        "model",
                        "model-with-experiment-override",
                    }:
                        initializers[dependency_identity] = {
                            "target": dependency["resolved_symbol"],
                            "target_identity": dependency_identity,
                            "owner": "model",
                            "initialization_source": "value-policy",
                            "value": dependency["value_policy"]["value"],
                        }
                    record_external_fact_target(
                        dependency,
                        dependency["resolved_symbol"],
                        dependency_identity,
                    )
                    pending_dependencies.extend(
                        derived_dependencies.get(dependency_key, [])
                    )
            elif operand["kind"] == "literal":
                context_type = _reference_literal_context(
                    operand["value"],
                    formal,
                    checked,
                    selected_semantics,
                )
                if formal["access"] != "read" or context_type is None:
                    raise _ReferenceEntrypointError(
                        operand_pointer,
                        "literal is incompatible",
                    )
                operand_body = {
                    "kind": "literal",
                    "value": operand["value"],
                    "context_type": context_type,
                }
                resolved_operand = {
                    **operand_body,
                    "identity": _reference_content_identity(
                        domains["actual_operand"], operand_body
                    ),
                }
            elif operand["kind"] == "event-reference":
                event_reference_contract = checked.kernel["meta_format"][
                    "runtime_program"
                ]["fixed_value_contracts"]["kernel-event-reference"]
                name = operand["name"]
                if formal["access"] != "read" or not (
                    _reference_operation_contract_matches(
                        event_reference_contract,
                        formal,
                    )
                ):
                    raise _ReferenceEntrypointError(
                        operand_pointer,
                        "Event reference is incompatible",
                    )
                operand_body = {
                    "kind": "event-reference",
                    "name": name,
                }
                operand_identity = _reference_content_identity(
                    domains["actual_operand"], operand_body
                )
                resolved_operand = {
                    **operand_body,
                    "identity": operand_identity,
                }
                aliases.setdefault(operand_identity, []).append(
                    (formal["id"], formal["access"])
                )
                reference_contract = {
                    "name": name,
                    "operand_identity": operand_identity,
                    "cardinality": "required",
                }
                previous_reference = event_reference_targets.get(name)
                if (
                    previous_reference is not None
                    and previous_reference != reference_contract
                ):
                    raise ValueError("conflicting Event reference targets")
                event_reference_targets[name] = reference_contract
            else:
                raise _ReferenceEntrypointError(
                    operand_pointer,
                    "unknown entrypoint operand kind",
                )
            arguments.append(
                {
                    "port": {
                        "identity": _reference_content_identity(
                            domains["formal_port"], formal_body
                        ),
                        "operation": exact_operation,
                        "name": formal["id"],
                    },
                    "operand": resolved_operand,
                    "access": formal["access"],
                }
            )
        try:
            alias_rows = _reference_alias_rows(operation, aliases)
        except ValueError as error:
            raise _ReferenceEntrypointError(
                f"{pointer}/arguments",
                str(error),
            ) from error
        authored_result = source_entrypoint["result"]
        if authored_result["kind"] == "discard":
            if operation["result"]["discardable"] is not True:
                raise _ReferenceEntrypointError(
                    f"{pointer}/result",
                    "required result cannot be discarded",
                )
            result_body = {"kind": "discard"}
        else:
            result_declaration = declarations_by_source.get(
                (authored_result["module"], authored_result["symbol"])
            )
            if (
                result_declaration is None
                or not roles[result_declaration["role"]]["entrypoint_result"]
                or not _reference_value_contract_matches(
                    result_declaration, operation["result"]
                )
            ):
                raise _ReferenceEntrypointError(
                    f"{pointer}/result",
                    "entrypoint result is incompatible",
                )
            result_body = {
                "kind": "symbol",
                "symbol": result_declaration["resolved_symbol"],
            }
        result = {
            **result_body,
            "identity": _reference_content_identity(domains["result"], result_body),
        }
        body = {
            "id": entrypoint_id,
            "operation": exact_operation,
            "arguments": arguments,
            "aliases": alias_rows,
            "result": result,
            "effects": operation["effects"],
            "refusals": operation["refusals"],
            "resource_bounds": operation["resource_bounds"],
            "scenario_input_contract": {
                "initializers": sorted(
                    initializers.values(),
                    key=lambda row: row["target_identity"],
                ),
                "targets": sorted(
                    targets.values(),
                    key=lambda row: row["target_identity"],
                ),
            },
            "event_local_payload_contract": {
                "targets": sorted(
                    event_payload_targets.values(),
                    key=lambda row: row["target_identity"],
                ),
                "event_references": sorted(
                    event_reference_targets.values(),
                    key=lambda row: row["name"],
                ),
            },
            "external_fact_contract": {
                "targets": sorted(
                    external_fact_targets.values(),
                    key=lambda row: row["target_identity"],
                )
            },
        }
        resolved_entrypoints.append(
            {
                **body,
                "identity": _reference_content_identity(domains["entrypoint"], body),
            }
        )
    return sorted(resolved_entrypoints, key=lambda row: row["id"])


def _reference_operation_contract_matches(
    actual: dict[str, Any],
    formal: dict[str, Any],
) -> bool:
    return actual["type"] == formal["type"] and all(
        actual[member] == formal[member]
        for member in (
            "representation",
            "kind",
            "unit",
            "domain",
            "numeric_policy",
        )
    )


def _reference_call_sites(
    checked: ModelSourceContext,
    selected_semantics: dict[str, Any],
    *,
    declarations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    operation_rows = selected_semantics["operations"]
    operations = {
        (row["package"], row["definition"]["id"]): row for row in operation_rows
    }
    definitions = {
        coordinate: row["definition"] for coordinate, row in operations.items()
    }
    if len(definitions) != len(operation_rows):
        raise ValueError("selected Operation coordinate is duplicated")
    declared = {_reference_encoded(row["resolved_symbol"]): row for row in declarations}
    snapshots = {}
    for coordinate, definition in definitions.items():
        operands = (
            definition.get("extensions", {})
            .get("standard.snapshot-operands", {})
            .get("operands", [])
        )
        if not operands:
            continue
        contracts = {}
        for operand in operands:
            declaration = declared[_reference_encoded(operand["resolved_symbol"])]
            if declaration.get("value_kind") == "nominal-structured":
                contract = {
                    "type": declaration["type_identity"],
                    "value_kind": "nominal-structured",
                }
            else:
                contract = {
                    member: declaration[member]
                    for member in ("representation", "kind", "unit", "numeric_policy")
                }
                contract.update(
                    type=declaration["type_identity"], domain={"kind": "actual"}
                )
            contracts[operand["name"]] = contract
        snapshots[coordinate] = contracts
    closures = {}
    subjects = _consumer_b_operation_composition_subjects(
        deepcopy(checked.kernel),
        deepcopy(checked.language_bundle),
        selected_operations=definitions,
        snapshot_contracts=snapshots,
        closed_operations=closures,
    )
    if subjects:
        raise ValueError(
            "independent selected composition refuses: " + ", ".join(subjects)
        )
    runtime = checked.kernel["meta_format"]["runtime_program"]
    domains = runtime["invocation_contract"]["identity_domains"]
    node_operators = {
        row["id"]: row["semantics"]["operator"] for row in runtime["nodes"]
    }

    def expanded_body(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
        instructions = []
        for instruction in body:
            instructions.append(instruction)
            if node_operators[instruction["node"]] == "guarded-outcome-block":
                instructions.extend(instruction["body"])
        return instructions

    rows = []
    for parent_key, operation_row in sorted(operations.items()):
        operation = operation_row["definition"]
        parent_ref = _reference_exact_operation(operation_row)
        for order, instruction in enumerate(expanded_body(operation["body"])):
            if instruction["node"] != "invoke":
                continue
            site = instruction["site"]
            child_ref = instruction["operation"]
            child_row = operations.get(
                (
                    child_ref["package"],
                    child_ref["id"],
                )
            )
            if child_row is None:
                raise ValueError("nested Operation is not selected")
            child = child_row["definition"]
            exact_child = _reference_exact_operation(child_row)
            child_ports = child["inputs"]
            authored_arguments = instruction["arguments"]
            aliases: dict[str, list[tuple[str, str]]] = {}
            arguments = []
            for formal, authored in zip(child_ports, authored_arguments, strict=True):
                formal_body = {"operation": exact_child, "name": formal["id"]}
                operand = authored["operand"]
                if operand["kind"] == "port":
                    operand_body = {
                        "kind": "port",
                        "parent_operation": parent_ref,
                        "port": operand["port"],
                    }
                    resolved_operand = {
                        "kind": "port",
                        "port": operand["port"],
                        "identity": _reference_content_identity(
                            domains["actual_operand"], operand_body
                        ),
                    }
                elif operand["kind"] == "local":
                    operand_body = {
                        "kind": "local",
                        "parent_operation": parent_ref,
                        "local": operand["local"],
                    }
                    resolved_operand = {
                        "kind": "local",
                        "local": operand["local"],
                        "identity": _reference_content_identity(
                            domains["actual_operand"], operand_body
                        ),
                    }
                elif operand["kind"] == "literal":
                    context_type = _reference_literal_context(
                        operand["literal"],
                        formal,
                        checked,
                        selected_semantics,
                    )
                    if formal["access"] != "read" or context_type is None:
                        raise ValueError("nested literal is incompatible")
                    operand_body = {
                        "kind": "literal",
                        "parent_operation": parent_ref,
                        "value": operand["literal"],
                        "context_type": context_type,
                    }
                    resolved_operand = {
                        "kind": "literal",
                        "value": operand["literal"],
                        "context_type": context_type,
                        "identity": _reference_content_identity(
                            domains["actual_operand"], operand_body
                        ),
                    }
                else:
                    raise ValueError("unknown nested operand kind")
                actual_identity = resolved_operand["identity"]
                aliases.setdefault(actual_identity, []).append(
                    (formal["id"], formal["access"])
                )
                arguments.append(
                    {
                        "port": {
                            "identity": _reference_content_identity(
                                domains["formal_port"], formal_body
                            ),
                            "operation": exact_child,
                            "name": formal["id"],
                        },
                        "operand": resolved_operand,
                        "access": formal["access"],
                    }
                )
            alias_rows = _reference_alias_rows(child, aliases)
            authored_result = instruction["result"]
            result_body = {
                "parent_operation": parent_ref,
                "site": site,
                "operation": exact_child,
                "binding": authored_result,
            }
            result = {
                "identity": _reference_content_identity(domains["result"], result_body),
                "binding": authored_result,
            }
            authored_outcomes = instruction["outcomes"]
            outcomes = []
            for mapping in authored_outcomes:
                action = mapping["action"]
                outcome_body = {
                    "parent_operation": parent_ref,
                    "site": site,
                    "operation": exact_child,
                    "outcome": mapping["outcome"],
                    "action": action,
                }
                outcomes.append(
                    {
                        "identity": _reference_content_identity(
                            domains["outcome"], outcome_body
                        ),
                        "outcome": mapping["outcome"],
                        "action": action,
                    }
                )
            child_effects, child_refusals, child_charge = closures[
                (child_ref["package"], child_ref["id"])
            ]
            body = {
                "parent_operation": parent_ref,
                "site": site,
                "order": order,
                "operation": exact_child,
                "arguments": arguments,
                "result": result,
                "outcomes": outcomes,
                "aliases": alias_rows,
                "closure": {
                    "effects": sorted(child_effects),
                    "refusals": sorted(child_refusals),
                    "resource_charge": 1 + child_charge,
                },
            }
            rows.append(
                {
                    **body,
                    "identity": _reference_content_identity(domains["call_site"], body),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            row["parent_operation"]["package"],
            row["parent_operation"]["id"],
            row["order"],
        ),
    )


def _reference_execution_closure(
    checked: ModelSourceContext,
    rir: dict[str, Any],
    consume: Callable[[], None],
) -> dict[str, Any]:
    """Interpret the declared selectors with an independent reachability walk."""
    meta = checked.kernel["meta_format"]
    contract = meta["runtime_projection"]["execution_closure"]
    result = deepcopy(rir["selected_semantics"])
    assert not set(contract["output_members"]) & result.keys()

    def at(value: Any, path: list[str]) -> Any:
        for member in path:
            value = value[member]
        return value

    def put(value: dict[str, Any], path: list[str], item: Any) -> None:
        for member in path[:-1]:
            value = value.setdefault(member, {})
        assert path[-1] not in value
        value[path[-1]] = deepcopy(item)

    def instructions(body: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for instruction in body:
            rows.append(instruction)
            if isinstance(instruction.get("body"), list):
                rows.extend(instructions(instruction["body"]))
        return rows

    operations = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in result["operations"]
    }
    reachable = {
        (row["operation"]["package"], row["operation"]["id"])
        for row in rir["entrypoints"]
    }
    # Fixed point over owner coordinates includes every nested reference node,
    # including scheduled calls, without assuming a particular node spelling.
    while True:
        expanded = set(reachable)
        for coordinate in reachable:
            for row in instructions(operations[coordinate]["body"]):
                if isinstance(row.get("operation"), dict):
                    ref = row["operation"]
                    expanded.add((ref["package"], ref["id"]))
        if expanded == reachable:
            break
        reachable = expanded
    node_contract = contract["nodes"]
    used_nodes = {
        row[node_contract["instruction_member"]]
        for coordinate in reachable
        for row in instructions(operations[coordinate]["body"])
    }
    # Formula reachability is separate for each lifecycle phase. A target in
    # another phase must not make an otherwise unused Formula executable.
    for phase in _reference_formula_phases(checked.kernel):
        programs = [
            program
            for program in rir["initialization_programs"]
            if program["site"]["context"]["phase"] == phase
        ]
        targets = {
            _reference_encoded(binding["operand"]["symbol"])
            for entrypoint in rir["entrypoints"]
            for binding in entrypoint["arguments"]
            if binding["operand"]["kind"] == "symbol"
        }
        while True:
            dependencies = {
                _reference_encoded(row["operand"]["resolved_symbol"])
                for program in programs
                if _reference_encoded(program["target"]) in targets
                for row in program["inputs"]
                if row["operand"]["kind"] != "literal"
            }
            if dependencies <= targets:
                break
            targets.update(dependencies)
        used_nodes.update(
            row["instruction"][node_contract["instruction_member"]]
            for program in programs
            if _reference_encoded(program["target"]) in targets
            for row in program["body"]
        )

    applicable = {
        "executable": bool(rir["entrypoints"] or used_nodes),
        "typed-values": any(
            row["definition"]["source_kind"] == "typed-envelope"
            for row in result["literal_typing_profiles"]
        ),
    }
    laws: dict[str, Any] = {}
    for selector in contract["law_selectors"]:
        consume()
        if applicable[selector["when"]]:
            put(laws, selector["output_path"], at(meta, selector["source_path"]))
    nodes = {
        node[node_contract["id_member"]]: node
        for node in at(meta, node_contract["source_path"])
    }
    selected_nodes = []
    for name in sorted(used_nodes):
        consume()
        selected_nodes.append(nodes[name])
    put(laws, node_contract["output_path"], selected_nodes)
    result["execution_laws"] = laws
    resources = {}
    for selector in contract["resources"]:
        consume()
        if not applicable[selector["when"]]:
            continue
        resources[selector["output_member"]] = checked.language_bundle["resources"][
            selector["source_member"]
        ]
    result["execution_resources"] = resources

    reasons = contract["reasons"]
    reason_path = reasons["authority_path"]
    diagnostic_path = reasons["diagnostic_authority_path"]
    catalogs: dict[str, dict[str, dict[str, Any]]] = {
        reason_path: {},
        diagnostic_path: {},
    }
    for package in checked.language_bundle["language"]["packages"]:
        for closure in package["semantic_closure"]:
            path = closure["authority_path"]
            if path not in catalogs:
                continue
            key = reasons["id_member" if path == reason_path else "diagnostic_member"]
            for definition in closure["definitions"]:
                consume()
                assert definition[key] not in catalogs[path]
                catalogs[path][definition[key]] = {
                    "package": package["id"],
                    "definition": deepcopy(definition),
                }
    requested_reasons: set[str] = set()
    signals = {
        (row["stage"], row["signal"])
        for row in reasons["roots"]
        if applicable[row["when"]]
    }
    for node in selected_nodes:
        signals.update(
            (reasons["node_signal_stage"], signal)
            for signal in node[reasons["node_signal_member"]]
        )
    for coordinate in sorted(reachable):
        operation = operations[coordinate]
        requested_reasons.update(operation[reasons["operation_reason_member"]])
        for instruction in instructions(operation["body"]):
            consume()
            semantics = nodes[instruction[node_contract["instruction_member"]]][
                "semantics"
            ]
            if reasons["instruction_reference"] in semantics:
                ref = semantics[reasons["instruction_reference"]]
                requested_reasons.add(instruction[ref["instruction_member"]])
    for stage, signal in signals:
        matches = [
            name
            for name, row in catalogs[reason_path].items()
            if row["definition"].get("stage") == stage
            and row["definition"].get("signal") == signal
        ]
        assert len(matches) == 1
        requested_reasons.add(matches[0])
    result["diagnostic_reasons"] = []
    diagnostic_codes = set()
    for name in sorted(requested_reasons):
        consume()
        row = catalogs[reason_path][name]
        definition = row["definition"]
        code = definition["diagnostic"]
        assert (
            catalogs[diagnostic_path][code]["definition"]["stage"]
            == definition["stage"]
        )
        result["diagnostic_reasons"].append(row)
        diagnostic_codes.add(code)
    result["diagnostics"] = []
    for code in sorted(diagnostic_codes):
        consume()
        result["diagnostics"].append(catalogs[diagnostic_path][code])

    # These definitions retain the actual containing owner, including implicit
    # execution dependencies outside the Source's authored root namespaces.
    closures = {
        row["package"]: row["definitions"]
        for row in result["package_semantic_closures"]
    }
    packages = {row["id"] for row in result["packages"]}
    for member, path in (
        ("diagnostic_reasons", reason_path),
        ("diagnostics", diagnostic_path),
    ):
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in result[member]:
            grouped.setdefault(row["package"], []).append(row["definition"])
        for owner, definitions in grouped.items():
            packages.add(owner)
            entries = closures.setdefault(owner, [])
            assert all(entry["authority_path"] != path for entry in entries)
            entries.append(
                {"authority_path": path, "definitions": deepcopy(definitions)}
            )
            entries.sort(key=lambda entry: entry["authority_path"])
    result["packages"] = [{"id": owner} for owner in sorted(packages)]
    result["package_semantic_closures"] = [
        {"package": owner, "definitions": closures[owner]} for owner in sorted(closures)
    ]
    return result


def _reference_runtime_projection(
    checked: ModelSourceContext,
    lock: dict[str, Any],
    declarations: list[dict[str, Any]],
    lowering: dict[str, Any],
    consume: Callable[[], None],
    *,
    formulas: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = lowering["runtime_projection"]

    def descend(value: Any, path: list[str]) -> Any:
        if not path:
            return value
        return descend(value[path[0]], path[1:])

    catalogs: dict[str, list[tuple[str, str | None, Any]]] = {}
    for specification in profile["collections"]:
        source = specification["source"]
        rows: list[tuple[str, str | None, Any]]
        if source["kind"] == "namespace-member":
            rows = []
            for value in lock[source["member"]]:
                consume()
                rows.append(
                    (
                        descend(value, source["package_path"]),
                        None,
                        value,
                    )
                )
        else:
            rows = []
            for closure in lock["package_semantic_closures"]:
                entries = [
                    entry
                    for entry in closure["definitions"]
                    if entry["authority_path"] == source["authority_path"]
                ]
                assert len(entries) <= 1
                if not entries:
                    continue
                entry = entries[0]
                for definition in entry["definitions"]:
                    consume()
                    rows.append(
                        (
                            closure["package"],
                            source["authority_path"],
                            definition,
                        )
                    )
        catalogs[specification["id"]] = rows

    selected = {name: set() for name in catalogs}
    root_law = checked.kernel["meta_format"]["runtime_projection"]["operation_roots"]
    operation_collection = profile["operation_roots"]["collection"]
    package_member, id_member = root_law["coordinate_members"]
    formula_roots = set()
    for formula in formulas:
        for node in descend(formula, root_law["formula_nodes_path"]):
            consume()
            if (
                node[root_law["formula_node_kind_member"]]
                == root_law["formula_node_kind"]
            ):
                reference = node[root_law["formula_reference_member"]]
                formula_roots.add((reference[package_member], reference[id_member]))
    reachable = _reference_selected_operation_coordinates(
        checked, lock, formula_roots, consume_instruction=consume
    )
    available = {(row[0], row[2][id_member]) for row in catalogs[operation_collection]}
    assert reachable <= available
    for coordinate in sorted(reachable):
        for index, row in enumerate(catalogs[operation_collection]):
            consume()
            if (row[0], row[2][id_member]) == coordinate:
                selected[operation_collection].add(index)

    for seed in profile["seeds"]:
        for declaration in declarations:
            if seed["applicability_member"] not in declaration:
                continue
            try:
                package = descend(declaration, seed["declaration_package_path"])
                expected = descend(declaration, seed["declaration_path"])
            except (KeyError, TypeError):
                assert seed["missing_declaration_path"] == "not-applicable"
                continue
            matched = False
            for index, row in enumerate(catalogs[seed["collection"]]):
                consume()
                if seed["same_package"] and row[0] != package:
                    continue
                assert seed["operator"] == "declaration-field"
                try:
                    target = descend(row[2], seed["target_path"])
                except (KeyError, TypeError):
                    assert seed.get("missing_target") == "not-applicable"
                    continue
                if target == expected:
                    selected[seed["collection"]].add(index)
                    matched = True
            assert matched

    type_closure = profile["type_reference_closure"]

    def nested_type_terms(value: Any):
        references = set()
        kinds = set()
        pending = [value]
        while pending:
            term = pending.pop()
            consume()
            if isinstance(term, list):
                pending.extend(term)
            elif isinstance(term, dict):
                coordinate = tuple(
                    term.get(member)
                    for member in checked.kernel["meta_format"]["literal_typing"][
                        "typed_envelope_profile"
                    ]["admission"]["nominal_type_reference"]["coordinate_members"]
                )
                if all(isinstance(member, str) and member for member in coordinate):
                    references.add(coordinate)
                kind = term.get(
                    checked.kernel["meta_format"]["runtime_projection"][
                        "type_reference_closure"
                    ]["structural_match"]["definition_kind_member"]
                )
                if isinstance(kind, str) and kind:
                    kinds.add(kind)
                pending.extend(term.values())
        return references, kinds

    previous = None
    while previous != selected:
        previous = {name: set(indexes) for name, indexes in selected.items()}
        for edge in profile["edges"]:
            for source_index in sorted(selected[edge["source_collection"]]):
                consume()
                source = catalogs[edge["source_collection"]][source_index]
                expected = descend(source[2], edge["source_path"])
                matched = False
                for target_index, target in enumerate(
                    catalogs[edge["target_collection"]]
                ):
                    consume()
                    if edge["same_package"] and source[0] != target[0]:
                        continue
                    try:
                        actual = descend(target[2], edge["target_path"])
                    except (KeyError, TypeError):
                        assert edge["missing_target"] == "not-applicable"
                        continue
                    if actual == expected:
                        matched = True
                        selected[edge["target_collection"]].add(target_index)
                if not matched and edge.get("missing_target") != "not-applicable":
                    raise ValueError("runtime projection edge did not resolve")
        references = set()
        constructor_kinds = set()
        for source_index in sorted(selected[type_closure["source_collection"]]):
            source = catalogs[type_closure["source_collection"]][source_index]
            definition = descend(source[2], type_closure["source_definition_path"])
            nested_references, nested_kinds = nested_type_terms(definition)
            references.update(nested_references)
            constructor_kinds.update(nested_kinds)
        type_collection = type_closure["target_type_collection"]
        for index, row in enumerate(catalogs[type_collection]):
            consume()
            if (row[0], row[2]["id"]) in references:
                selected[type_collection].add(index)
        constructor_collection = type_closure["target_constructor_collection"]
        for index, row in enumerate(catalogs[constructor_collection]):
            consume()
            try:
                kind = descend(row[2], type_closure["constructor_kind_path"][:-1])[
                    checked.kernel["meta_format"]["runtime_projection"][
                        "type_reference_closure"
                    ]["structural_match"]["constructor_kind_member"]
                ]
            except (KeyError, TypeError):
                continue
            if kind in constructor_kinds:
                selected[constructor_collection].add(index)

    selected_packages = {
        catalogs[name][index][0]
        for name, indexes in selected.items()
        for index in indexes
    }
    projection: dict[str, Any] = {}
    selected_closure_values: dict[tuple[str, str], list[Any]] = {}

    def projected_runtime_value(specification: dict[str, Any], value: Any) -> Any:
        roles = checked.kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["rir_structure"]["selected_collections"]
        matches = [
            role
            for role in roles.values()
            if all(
                _reference_encoded(specification["source"].get(key))
                == _reference_encoded(item)
                for key, item in role["source"].items()
            )
        ]
        assert len(matches) <= 1
        excluded = matches[0].get("excluded_members", []) if matches else []
        if not excluded:
            return value
        assert isinstance(value, dict)
        return {key: item for key, item in value.items() if key not in excluded}

    for specification in profile["collections"]:
        rows = []
        for index, row in enumerate(catalogs[specification["id"]]):
            consume()
            if index in selected[specification["id"]]:
                rows.append(
                    (
                        row[0],
                        row[1],
                        projected_runtime_value(specification, row[2]),
                    )
                )
        for package, authority_path, value in rows:
            if authority_path is not None:
                selected_closure_values.setdefault(
                    (package, authority_path), []
                ).append(value)
        roles = checked.kernel["meta_format"]["language_definitions"][
            "wire_schema_protocol_roles"
        ]["rir_structure"]["selected_collections"]
        matches = [
            (name, role["shape"])
            for name, role in roles.items()
            if all(
                _reference_encoded(specification["source"].get(key))
                == _reference_encoded(value)
                for key, value in role["source"].items()
            )
        ]
        assert len(matches) <= 1
        if not matches:
            continue
        member, shape = matches[0]
        if shape == "package-definition":
            projection[member] = [
                {"package": row[0], "definition": row[2]} for row in rows
            ]
        else:
            assert shape in {"as-is", "definition"}
            projection[member] = [row[2] for row in rows]

    selected_package_rows = []
    for package in lock["packages"]:
        consume()
        if package["id"] in selected_packages:
            selected_package_rows.append({"id": package["id"]})
    projection["packages"] = selected_package_rows
    selected_closures = []
    for closure in lock["package_semantic_closures"]:
        consume()
        package = closure["package"]
        if package not in selected_packages:
            continue
        values = []
        for entry in closure["definitions"]:
            definitions = selected_closure_values.get(
                (package, entry["authority_path"])
            )
            if definitions:
                values.append(
                    {
                        "authority_path": entry["authority_path"],
                        "definitions": definitions,
                    }
                )
        if values:
            selected_closures.append({"package": package, "definitions": values})
    projection["package_semantic_closures"] = selected_closures
    role_law = checked.kernel["meta_format"]["runtime_projection"][
        "symbol_role_bindings"
    ]
    role_bindings = {}
    assignment_policy = lowering["assignment_policy"]

    def binding_field_matches(actual, expected):
        if isinstance(expected, list) and not isinstance(actual, list):
            return actual in expected
        return actual == expected

    for binding in role_law["bindings"]:
        consume()  # One law-selector charge per Kernel-owned binding.
        matches = {
            row["role"]
            for row in assignment_policy["roles"]
            if all(
                binding_field_matches(row.get(member), expected)
                for member, expected in binding["role_fields"].items()
            )
            for mode in row["modes"]
            if all(
                binding_field_matches(mode.get(member), expected)
                for member, expected in binding["mode_fields"].items()
            )
        }
        assert len(matches) == 1
        role_bindings[binding["slot"]] = next(iter(matches))
    assert role_law["distinct"] is True
    assert len(set(role_bindings.values())) == len(role_bindings)
    projection[role_law["output_member"]] = role_bindings
    return projection


def _reference_pointer(parts: list[object]) -> str:
    return "".join(
        "/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _reference_source_pointer(checked: ModelSourceContext, parts: list[object]) -> str:
    canonical = _reference_pointer(parts)
    return checked.source_projection.authored_paths.get(canonical, canonical)


def _reference_debug_map(
    checked: ModelSourceContext, rir: dict[str, Any]
) -> dict[str, Any]:
    source = checked.source_projection.value
    model_id = source["manifest"]["id"]
    pointers = {
        (
            model_id,
            module["id"],
            symbol["symbol"],
        ): ["modules", module_index, "symbols", symbol_index]
        for module_index, module in enumerate(source["modules"])
        for symbol_index, symbol in enumerate(module["symbols"])
    }
    declarations = rir["declarations"]
    formula_pointers = {
        (module["id"], formula["id"]): [
            "modules",
            module_index,
            "formulas",
            formula_index,
        ]
        for module_index, module in enumerate(source["modules"])
        for formula_index, formula in enumerate(module.get("formulas", []))
    }
    declaration_entries = [
        {
            "rir_pointer": _reference_pointer(["declarations", index]),
            "source_pointer": _reference_source_pointer(
                checked,
                pointers[
                    (
                        declaration["resolved_symbol"]["model"],
                        declaration["resolved_symbol"]["module"],
                        declaration["resolved_symbol"]["name"],
                    )
                ],
            ),
        }
        for index, declaration in enumerate(declarations)
    ]
    formula_entries = [
        {
            "rir_pointer": _reference_pointer(["formulas", index]),
            "source_pointer": _reference_source_pointer(
                checked, formula_pointers[(formula["module"], formula["id"])]
            ),
        }
        for index, formula in enumerate(rir["formulas"])
    ]
    return _reference_artifact(
        checked,
        "debug-map",
        {
            "source_identity": checked.source_identity,
            "rir_identity": rir["content_identity"],
            "entries": declaration_entries + formula_entries,
        },
    )


def _reference_semantic_artifacts(
    checked: ModelSourceContext,
) -> dict[str, dict[str, Any]]:
    lock = _reference_package_lock(checked)
    rir = _reference_rir(checked, lock)
    resolved = _reference_artifact(
        checked,
        "resolved-model",
        {
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_content_identity": rir["content_identity"],
            "rir_semantic_identity": rir["semantic_identity"],
        },
    )
    return {
        "package-lock": lock,
        "rir-semantic-payload": rir,
        "resolved-model": resolved,
        "debug-map": _reference_debug_map(checked, rir),
    }


def _reference_admits_semantic_artifacts(
    candidate: dict[str, dict[str, Any]], checked: ModelSourceContext
) -> bool:
    expected = _reference_semantic_artifacts(checked)
    return all(
        candidate[name] == expected[name]
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    )


def _materialize_vector_source(
    vector: dict[str, Any], language_bundle: dict[str, Any]
) -> dict[str, Any]:
    fixture = vector["source_fixture"]
    source = deepcopy(fixture["source"])
    if fixture["mode"] == "literal":
        return source
    count = _exact_path(language_bundle, fixture["count_resource_path"])
    count += fixture["count_offset"]
    target: Any = source
    for segment in fixture["collection_path"]:
        target = target[int(segment)] if isinstance(target, list) else target[segment]
    assert isinstance(target, list) and not target
    for index in range(count):
        item = deepcopy(fixture["template"])
        item[fixture["index_member"]] = fixture["index_prefix"] + str(index).zfill(
            fixture["index_width"]
        )
        target.append(item)
    return source


def _reference_materialize_vector_source(
    vector: dict[str, Any], language_bundle: dict[str, Any]
) -> dict[str, Any]:
    fixture = vector["source_fixture"]
    if fixture["mode"] == "literal":
        return json.loads(json.dumps(fixture["source"]))
    source = json.loads(json.dumps(fixture["source"]))
    count_values = _reference_path(language_bundle, fixture["count_resource_path"])
    assert len(count_values) == 1
    count = count_values[0] + fixture["count_offset"]

    def descend(value: Any, segments: list[str]) -> Any:
        if not segments:
            return value
        segment = segments[0]
        child = value[int(segment)] if isinstance(value, list) else value[segment]
        return descend(child, segments[1:])

    collection = descend(source, fixture["collection_path"])
    assert isinstance(collection, list) and collection == []
    template = fixture["template"]
    for index in range(count):
        item = {key: deepcopy(value) for key, value in template.items()}
        digits = str(index)
        padding = "0" * max(0, fixture["index_width"] - len(digits))
        item[fixture["index_member"]] = fixture["index_prefix"] + padding + digits
        collection.append(item)
    return source


def _lock_oracle(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "resolution_profile": lock["resolution_profile"]["id"],
        "root_requirements": lock["root_requirements"],
        "packages": [{"id": item["id"]} for item in lock["packages"]],
        "dependency_edges": lock["dependency_edges"],
        "capability_bindings": lock["capability_bindings"],
        "types": lock["types"],
        "components": [item["definition"]["id"] for item in lock["components"]],
        "conversions": [item["definition"]["id"] for item in lock["conversions"]],
        "operations": [item["definition"]["id"] for item in lock["operations"]],
        "numeric_profiles": [item["id"] for item in lock["numeric_profiles"]],
        "runtime_profiles": [item["id"] for item in lock["runtime_profiles"]],
        "diagnostics": lock["diagnostics"],
        "diagnostic_reasons": [item["id"] for item in lock["diagnostic_reasons"]],
        "language_rules": lock["language_rules"],
    }


def test_permanent_model_program_vectors_close_both_compiler_pipelines(tmp_path):
    kernel, language_bundle = mutable_authorities()
    vectors = [item for item in language_bundle["vectors"] if "source_fixture" in item]
    vector_ids = {item["id"] for item in vectors}
    assert {
        "formula.schema.accept.named-typed-pure-graph",
        "formula.schema.refuse.dynamic-or-effectful-graph",
        "formula.compiler.accept.closed-static-graph",
        "formula.compiler.refuse.invalid-closure",
        "formula.quantity.accept.pure-operation-closure",
        "formula.combat.accept.damage-slot-binding",
        "formula.combat.refuse.missing-or-duplicate-slot-binding",
        "quantity.literal.integer-admitted",
        "game.combat.model-binding.contract-stale-package",
        "game.combat.model-binding.contract-version-member-forbidden",
        "game.combat.model-binding.contract-stale-id",
        "game.combat.model-binding.contract-wrong-type",
        "game.combat.model-binding.contract-wrong-representation",
        "game.combat.model-binding.contract-wrong-kind",
        "game.combat.model-binding.contract-wrong-unit",
        "game.combat.model-binding.contract-wrong-numeric-policy",
        "game.combat.model-binding.literal-wrong-type",
        "quantity.assignment-policy.optional-override",
        "game.combat.model-binding.multiple-entrypoints",
    } <= vector_ids
    vector_owners = {
        vector_id: [
            vector_set
            for vector_set in language_bundle.package_conformance_vector_sets
            if vector_id in vector_set["vectors"]
        ]
        for vector_id in vector_ids
    }
    assert all(len(owners) == 1 for owners in vector_owners.values())
    owner_coordinates = {owners[0]["package_id"] for owners in vector_owners.values()}
    packages = [
        package
        for package in language_bundle["language"]["packages"]
        if package["id"] in owner_coordinates
    ]
    assert {item["category"] for item in vectors} == {
        "positive",
        "negative",
        "boundary",
        "mutation",
        "semantic-equivalence",
    }
    assert set(vector_owners) == vector_ids
    assert all(
        entry["authority_path"] != "vectors"
        for package in packages
        for entry in package["semantic_closure"]
    )

    results: dict[str, dict[str, Any] | None] = {}
    diagnostic_stages = {
        item["code"]: item["stage"] for item in language_bundle["diagnostics"]
    }
    output_member = "declarations"
    for index, vector in enumerate(vectors):
        source = _materialize_vector_source(vector, language_bundle)
        reference_source = _reference_materialize_vector_source(vector, language_bundle)
        assert source == reference_source
        path = tmp_path / f"{index}-{vector['id']}.json"
        _write_source(path, source)

        production_checked = check_model_source(str(path))
        reference_checked = _reference_check_source(
            reference_source, kernel, language_bundle
        )
        expected = vector["expect"]
        if expected["outcome"] == "refused":
            assert isinstance(production_checked, Schema2RefusalReport), vector["id"]
            assert isinstance(reference_checked, tuple), vector["id"]

            def artifact_pointer(item: Schema2Diagnostic) -> str:
                assert isinstance(item.primary, ArtifactLocation)
                return item.primary.pointer

            production_diagnostics = [
                {
                    "code": item.code,
                    "stage": production_checked.stage,
                    "pointer": artifact_pointer(item),
                }
                for item in production_checked.diagnostics
            ]
            reference_diagnostics = [
                {
                    "code": code,
                    "stage": diagnostic_stages[code],
                    "pointer": pointer,
                }
                for code, pointer in reference_checked
            ]
            assert production_diagnostics == reference_diagnostics
            assert production_diagnostics == expected["diagnostics"]
            assert expected["semantic_artifacts"] is False
            results[vector["id"]] = None
            continue

        assert isinstance(production_checked, CheckedModel)
        assert isinstance(reference_checked, ModelSourceContext)
        production = lower_checked_model(production_checked)
        reference = _reference_semantic_artifacts(reference_checked)
        assert all(
            production[name] == reference[name]
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
                "debug-map",
            )
        )
        assert _reference_admits_semantic_artifacts(production, reference_checked)
        assert admit_resolved_model(
            {
                name: reference[name]
                for name in (
                    "package-lock",
                    "rir-semantic-payload",
                    "resolved-model",
                )
            }
        ).admitted
        assert _lock_oracle(production["package-lock"]) == expected["lock_oracle"]
        assert (
            production["rir-semantic-payload"]["content_identity"]
            == expected["rir_identity"]
        )
        assert (
            production["debug-map"]["content_identity"]
            == expected["debug_map_identity"]
        )
        declarations = cast(
            list[Any], production["rir-semantic-payload"][output_member]
        )
        assert len(declarations) == expected["declaration_count"]
        results[vector["id"]] = production

    for vector in vectors:
        relation = vector["expect"]["relation"]
        if relation["kind"] == "independent":
            continue
        current = results[vector["id"]]
        reference = results[relation["reference"]]
        assert current is not None and reference is not None
        if relation["kind"] == "semantic-change":
            assert (
                current["rir-semantic-payload"]["content_identity"]
                != reference["rir-semantic-payload"]["content_identity"]
            )
        else:
            assert current["package-lock"] == reference["package-lock"]
            assert current["rir-semantic-payload"] == reference["rir-semantic-payload"]
            assert current["debug-map"] != reference["debug-map"]

    optional = cast(
        dict[str, Any],
        results["quantity.assignment-policy.optional-override"],
    )
    optional_contract = optional["rir-semantic-payload"]["entrypoints"][0][
        "scenario_input_contract"
    ]
    optional_target = next(
        row
        for row in optional_contract["targets"]
        if row["target"]["name"] == "parameter_value"
    )
    optional_initializer = next(
        row
        for row in optional_contract["initializers"]
        if row["target"]["name"] == "parameter_value"
    )
    assert (optional_target["cardinality"], optional_target["override"]) == (
        "optional",
        True,
    )
    assert optional_initializer["value"] == 10

    multiple = cast(
        dict[str, Any],
        results["game.combat.model-binding.multiple-entrypoints"],
    )
    entrypoints = multiple["rir-semantic-payload"]["entrypoints"]
    assert [row["id"] for row in entrypoints] == [
        "combat.cast",
        "combat.cast.alternate",
    ]
    assert len({row["identity"] for row in entrypoints}) == 2
    assert len({_reference_encoded(row["arguments"]) for row in entrypoints}) == 2

    literal = cast(
        dict[str, Any],
        results["quantity.literal.integer-admitted"],
    )
    literal_operand = literal["rir-semantic-payload"]["entrypoints"][0]["arguments"][0][
        "operand"
    ]
    assert literal_operand["context_type"] == {
        "domain": {"kind": "actual"},
        "id": "quantity.dimensionless-int64-v2-2",
        "kind": "scalar",
        "numeric_policy": "exact-int64",
        "representation": "Int",
        "type": {
            "id": "Quantity",
            "package": "core.quantity",
        },
        "unit": "1",
    }


def test_independent_lowerers_mutually_consume_byte_identical_rir(tmp_path):
    roles = (
        "constant",
        "parameter",
        "input",
        "state",
        "derived",
        "output",
        "random",
    )
    path = tmp_path / "source.json"
    source = _source([_symbol(role, role) for role in roles])
    _write_source(path, source)
    kernel, language_bundle = mutable_authorities()
    checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, language_bundle)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, ModelSourceContext)

    production = lower_checked_model(checked)
    reference = _reference_semantic_artifacts(reference_checked)

    assert all(
        production[name] == reference[name]
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
            "debug-map",
        )
    )
    assert _reference_admits_semantic_artifacts(production, reference_checked)
    assert admit_resolved_model(
        {
            name: reference[name]
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        }
    ).admitted


def test_independent_lowerers_close_recursive_nominal_types_by_owner(
    tmp_path, monkeypatch
):
    authority = _recursive_nominal_owner_candidate()
    kernel, language_bundle = authority["kernel"], authority["language_bundle"]
    _inject_authority_context(monkeypatch, kernel, language_bundle)
    source = _source([])
    owners = ("test.nominal.alpha", "test.nominal.beta")
    source["package_requirements"] = list(owners)
    module = source["modules"][0]
    module["imports"] = [
        {"alias": owner, "package": owner, "symbol": "Node"} for owner in owners
    ]
    module["symbols"] = [
        {
            "symbol": owner.rsplit(".", 1)[1],
            "type": owner,
            "role": "state",
            "value_policy": {"mode": "experiment-required"},
        }
        for owner in owners
    ]
    path = tmp_path / "source.json"
    _write_source(path, source)
    production_checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, language_bundle)
    assert isinstance(production_checked, CheckedModel)
    assert isinstance(reference_checked, ModelSourceContext)
    production = lower_checked_model(production_checked)
    reference = _reference_semantic_artifacts(reference_checked)
    for name in ("package-lock", "rir-semantic-payload", "resolved-model", "debug-map"):
        assert production[name] == reference[name], name
    assert _reference_admits_semantic_artifacts(production, reference_checked)
    assert admit_resolved_model(
        {
            name: reference[name]
            for name in ("package-lock", "rir-semantic-payload", "resolved-model")
        }
    ).admitted
    selected = reference["rir-semantic-payload"]["selected_semantics"]
    definitions = {
        (row["package"], row["definition"]["id"]): row["definition"]
        for row in selected["nominal_types"]
    }
    assert set(definitions) == {
        (owner, local) for owner in owners for local in ("Node", "Token")
    }
    for owner in owners:
        assert set(definitions[(owner, "Node")]) == {"id", "constructor", "definition"}
        assert definitions[(owner, "Token")]["definition"]["members"] == [
            owner.rsplit(".", 1)[1]
        ]
        fields = definitions[(owner, "Node")]["definition"]["fields"]
        assert fields[-1]["type"] == {
            "kind": "list",
            "maximum_length": 2,
            "element": {"package": owner, "id": "Node"},
        }
    assert {row["id"] for row in selected["constructors"]} == {
        "standard.schema.enum",
        "standard.schema.record",
        "standard.schema.list",
    }


def test_independent_lowerers_close_the_rpg_entrypoint_and_nested_call_graph():
    path = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    source = cast(
        dict[str, Any],
        json.loads(path.read_text(encoding="utf-8")),
    )
    kernel, language_bundle = mutable_authorities()
    checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, language_bundle)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, ModelSourceContext)

    production = lower_checked_model(checked)
    reference = _reference_semantic_artifacts(reference_checked)

    assert production["rir-semantic-payload"] == reference["rir-semantic-payload"]
    rir = reference["rir-semantic-payload"]
    assert [
        entrypoint["id"]
        for entrypoint in cast(list[dict[str, Any]], rir["entrypoints"])
    ] == [
        "combat.enemy-attacks-player",
        "combat.enemy-attacks-player-without-eligibility",
        "combat.player-attacks-enemy",
        "combat.player-attacks-enemy-and-cancels-counterattack",
        "combat.player-attacks-enemy-without-eligibility",
        "combat.player-plans-attacks",
    ]
    assert len(cast(list[Any], rir["call_sites"])) == 6
    assert admit_resolved_model(
        {
            name: reference[name]
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        }
    ).admitted


def test_independent_lowerer_closes_operation_slots_reached_from_formulas():
    path = (
        Path(__file__).parents[1]
        / "examples/schema2/progression-periodic-effect/model-source.json"
    )
    source = json.loads(path.read_text())
    kernel, language_bundle = mutable_authorities()
    checked = check_model_source_value(
        source, kernel=kernel, language_bundle=language_bundle
    )
    assert isinstance(checked, CheckedModel)
    production = compile_checked_model(checked)
    assert len(production) == 8

    # The progression policy is reached through a derived-symbol Formula,
    # although the only authored entrypoint is the periodic Effect Operation.
    target = {"package": "game.progression", "id": "game.progression.contribution@1"}
    assert all(row["operation"] != target for row in source["entrypoints"])
    assert source["formula_bindings"][2]["site"]["operation"] == target
    independent_checked = _reference_check_source(source, kernel, language_bundle)
    assert isinstance(independent_checked, ModelSourceContext)
    independent = _reference_semantic_artifacts(independent_checked)
    initialization = next(
        row
        for row in independent["rir-semantic-payload"]["initialization_programs"]
        if row["target"]["name"] == "magnitude_threshold"
    )
    assert (
        len(initialization["body"]),
        initialization["resource_bounds"]["max_steps"],
    ) == (2, 3)
    assert all(
        production[name] == independent[name]
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
            "debug-map",
        )
    )
    assert _reference_admits_semantic_artifacts(production, independent_checked)
    assert admit_resolved_model(
        {
            name: independent[name]
            for name in ("package-lock", "rir-semantic-payload", "resolved-model")
        }
    ).admitted


def test_independent_lowerer_counts_guard_body_in_nested_operation_charge():
    path = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    checked = check_model_source(str(path))
    assert isinstance(checked, CheckedModel)
    artifacts = lower_checked_model(checked)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    selected_semantics = cast(dict[str, Any], deepcopy(rir["selected_semantics"]))
    operation_rows = cast(list[dict[str, Any]], selected_semantics["operations"])
    # This direct composition fixture injects a new guarded call below; select
    # its actual admitted definition instead of depending on unrelated roots.
    identity = deepcopy(
        next(
            row
            for row in cast(
                list[dict[str, Any]], artifacts["package-lock"]["operations"]
            )
            if row["package"] == "core.quantity"
            and row["definition"]["id"] == "quantity.identity"
        )
    )
    identity["definition"].pop("vectors")
    operation_rows.append(identity)
    for row in operation_rows:
        row["definition"]["resource_bounds"]["max_steps"] += 100
    damage = next(
        row["definition"]
        for row in operation_rows
        if row["definition"]["id"] == "game.combat.damage-v1"
    )
    read_port = next(
        port["id"] for port in damage["inputs"] if port["access"] == "read"
    )
    damage["body"].append(
        {"node": "equal", "target": "enabled", "left": read_port, "right": read_port}
    )
    damage["body"].append(
        {
            "node": "guard-block",
            "condition": "enabled",
            "body": [
                {"node": "constant", "literal": 1, "target": "one"},
                {
                    "node": "invoke",
                    "site": "identity",
                    "operation": {
                        "package": "core.quantity",
                        "id": "quantity.identity",
                    },
                    "arguments": [
                        {"port": "value", "operand": {"kind": "local", "local": "one"}}
                    ],
                    "result": {"kind": "local", "name": "guard-identity"},
                    "outcomes": [],
                },
            ],
            "outcome": damage["default_outcome"],
        }
    )

    production = model_lowering_module._resolved_call_sites(
        checked.kernel,
        selected_semantics,
        language_bundle=checked.language_bundle,
        declarations=rir["declarations"],
    )
    independent = _reference_call_sites(
        checked, selected_semantics, declarations=rir["declarations"]
    )

    assert independent == production
    production_rows = cast(list[dict[str, Any]], production)
    damage_calls = [
        row
        for row in production_rows
        if cast(dict[str, Any], row["operation"])["id"] == "game.combat.damage-v1"
    ]
    assert damage_calls
    assert {
        cast(dict[str, Any], row["closure"])["resource_charge"] for row in damage_calls
    } == {18}


def test_operation_formula_dependency_closure_includes_guard_invocations():
    root = ("example", "root")
    child = ("example", "child")
    operations = {
        root: {
            "definition": {
                "body": [
                    {
                        "node": "guard-block",
                        "body": [
                            {
                                "node": "invoke",
                                "operation": {
                                    "package": child[0],
                                    "id": child[1],
                                },
                            }
                        ],
                    }
                ]
            }
        },
        child: {"definition": {"body": []}},
    }
    dependencies: dict[tuple[str, str], list[dict[str, JsonValue]]] = {
        root: [{"model": "model", "module": "module", "name": "root"}],
        child: [{"model": "model", "module": "module", "name": "child"}],
    }

    result = model_lowering_module._reachable_operation_formula_dependencies(
        root,
        operations,
        dependencies,
        operation_node_ids={"invoke"},
    )

    assert result == [
        {"model": "model", "module": "module", "name": "child"},
        {"model": "model", "module": "module", "name": "root"},
    ]


def test_nested_integer_literal_is_identical_across_lowerers(
    monkeypatch,
):
    path = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    source = cast(
        dict[str, Any],
        json.loads(path.read_text(encoding="utf-8")),
    )
    kernel, candidate_ldb = mutable_authorities()
    cast_operation = next(
        operation
        for operation in candidate_ldb["language"]["operations"]
        if operation["id"] == "game.combat.cast-v1"
    )
    spend_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "spend-resource"
    )
    cost = next(
        argument for argument in spend_call["arguments"] if argument["port"] == "cost"
    )
    cost["operand"] = {"kind": "literal", "literal": 8}
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, candidate_ldb)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, ModelSourceContext)

    production = lower_checked_model(checked)
    reference = _reference_semantic_artifacts(reference_checked)

    assert all(
        production[name] == reference[name]
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
            "debug-map",
        )
    )
    rir = cast(dict[str, Any], production["rir-semantic-payload"])
    call_sites = cast(list[dict[str, Any]], rir["call_sites"])
    call_site = next(row for row in call_sites if row["site"] == "spend-resource")
    operand = next(
        row["operand"]
        for row in call_site["arguments"]
        if row["port"]["name"] == "cost"
    )
    assert operand == {
        "kind": "literal",
        "value": 8,
        "context_type": {
            "domain": {"kind": "actual"},
            "id": "quantity.dimensionless-int64-v2-2",
            "kind": "scalar",
            "numeric_policy": "exact-int64",
            "representation": "Int",
            "type": {
                "id": "Quantity",
                "package": "core.quantity",
            },
            "unit": "1",
        },
        "identity": operand["identity"],
    }
    assert cast(str, operand["identity"]).startswith("sha256:")
    assert admit_resolved_model(
        {
            name: reference[name]
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        }
    ).admitted


def test_resolution_stage_order_is_authoritative_across_independent_consumers(
    tmp_path,
):
    source = _source([_symbol("health", "state")])
    source["package_requirements"][0] = "host.missing"
    source["modules"][0]["imports"][0]["package"] = "host.missing"
    source["modules"][0]["imports"].append(deepcopy(source["modules"][0]["imports"][0]))
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = mutable_authorities()

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, language_bundle)

    assert isinstance(production, Schema2RefusalReport)
    assert production.stage == "static"
    assert tuple(item.code for item in production.diagnostics) == (
        "language.name_ambiguity",
        "language.unresolved_name",
    )
    assert reference == (
        ("language.name_ambiguity", "/modules/0/imports/1/alias"),
        ("language.unresolved_name", "/modules/0/symbols/0/type"),
    )


def test_resolution_step_budget_drives_both_independent_consumers():
    source = _source([_symbol("health", "state")])
    kernel, language_bundle = mutable_authorities()
    language_bundle["resources"]["max_rule_match_steps"] = 1
    vectors = {
        vector["id"]: vector
        for vector in language_bundle["vectors"]
        if vector["id"]
        in {
            "model.accept.resolution-step-boundary",
            "model.refuse.resolution-step-budget",
        }
    }
    vectors["model.accept.resolution-step-boundary"]["input"]["value"] = 1
    vectors["model.refuse.resolution-step-budget"]["input"]["value"] = 2
    _reidentify_language_bundle(language_bundle)
    assert admit_authorities(kernel, language_bundle).admitted

    production = model_module._resolution_diagnostics(
        _production_source_projection(source, kernel, language_bundle),
        _reference_content_identity("model-source-package-v2", source),
        kernel,
        language_bundle,
        projection=project_required_namespace_closure(
            derive_current_namespace_packages(kernel, language_bundle),
            source["package_requirements"],
        ),
        stage="static",
    )
    reference = _reference_check_source(source, kernel, language_bundle)

    assert tuple(item.code for item in production) == ("language.resource_exhausted",)
    assert reference == (("language.resource_exhausted", ""),)


def test_runtime_projection_budget_drives_both_independent_consumers(
    tmp_path, monkeypatch
):
    source = _source([_symbol("health", "state")])
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = mutable_authorities()
    language_bundle["resources"]["max_runtime_projection_steps"] = 1
    vectors = {
        vector["id"]: vector
        for vector in language_bundle["vectors"]
        if vector["id"]
        in {
            "model.accept.runtime-projection-step-boundary",
            "model.refuse.runtime-projection-step-budget",
        }
    }
    vectors["model.accept.runtime-projection-step-boundary"]["input"]["value"] = 1
    vectors["model.refuse.runtime-projection-step-budget"]["input"]["value"] = 2
    _reidentify_language_bundle(language_bundle)
    assert admit_authorities(kernel, language_bundle).admitted
    _inject_authority_context(monkeypatch, kernel, language_bundle)

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, language_bundle)

    assert isinstance(production, Schema2RefusalReport)
    assert tuple(item.code for item in production.diagnostics) == (
        "language.resource_exhausted",
    )
    assert reference == (("language.resource_exhausted", ""),)


def test_runtime_symbol_role_projection_allows_equivalent_modes_within_one_role():
    source = _source([_symbol("health", "state")])
    kernel, language_bundle = mutable_authorities()
    language = language_bundle["language"]
    assignment_policy = language["model_lowerings"][0]["assignment_policy"]
    state = next(row for row in assignment_policy["roles"] if row["role"] == "state")
    model_fixed = next(mode for mode in state["modes"] if mode["id"] == "model-fixed")
    equivalent_mode = deepcopy(model_fixed)
    equivalent_mode["id"] = "state-model-fixed-alias"
    state["modes"].append(equivalent_mode)

    source_schema = next(
        row["schema"]
        for row in language["wire_schemas"]
        if row.get("protocol_role") == "model-source-package"
    )
    bindings = derive_default_source_native_bindings(kernel, language_bundle)
    module_schema = source_schema_member(
        source_schema, bindings.members["source.root.modules"]
    )[1]["items"]
    symbol_schema = source_schema_member(
        module_schema, bindings.members["source.module.symbols"]
    )[1]["items"]
    value_policy_schema = source_schema_member(
        symbol_schema, bindings.members["source.symbol.value_policy"]
    )[1]
    mode_schema = source_schema_member(
        value_policy_schema, bindings.members["source.value_policy.mode"]
    )[1]
    mode_schema["enum"].append(equivalent_mode["id"])

    _reidentify_language_bundle(language_bundle)
    production_admission = admit_authorities(kernel, language_bundle)
    independent_admission = _consumer_b(kernel, language_bundle)
    assert production_admission.admitted, production_admission
    assert independent_admission["admitted"], independent_admission["diagnostics"]

    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext)
    checked = check_model_source_value(source, authority_context=context)
    reference_checked = _reference_check_source(source, kernel, language_bundle)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, ModelSourceContext)

    production = compile_checked_model(checked)
    reference = _reference_semantic_artifacts(reference_checked)
    assert production["rir-semantic-payload"] == reference["rir-semantic-payload"]
    rir = cast(dict[str, Any], production["rir-semantic-payload"])
    assert rir["selected_semantics"]["symbol_role_bindings"] == {
        "input": "input",
        "state": "state",
        "output": "output",
    }
    assert (
        admit_rir(rir, authority_context=context).semantic_identity
        == rir["semantic_identity"]
    )


def test_resolution_law_fields_drive_both_independent_interpreters(tmp_path):
    source = _source([_symbol("health", "state")])
    second_import = deepcopy(source["modules"][0]["imports"][0])
    second_import["alias"] = "quantity_again"
    source["modules"][0]["imports"].append(second_import)
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = mutable_authorities()
    operation = next(
        item
        for item in kernel["meta_format"]["resolution_judgment"]["operations"]
        if item["id"] == "require-unique-import-aliases"
    )
    assert operation["law"] == {
        "operator": "require-unique",
        "relation": "imports",
        "scope": ["module"],
        "key": ["alias"],
        "pointer_field": "alias",
    }
    operation["law"]["key"] = ["package"]

    production = model_module._resolution_diagnostics(
        _production_source_projection(source, kernel, language_bundle),
        _reference_content_identity("model-source-package-v2", source),
        kernel,
        language_bundle,
        projection=project_required_namespace_closure(
            derive_current_namespace_packages(kernel, language_bundle),
            source["package_requirements"],
        ),
        stage="static",
    )
    reference = _reference_check_source(source, kernel, language_bundle)

    assert tuple(item.code for item in production) == ("language.name_ambiguity",)
    assert reference == (("language.name_ambiguity", "/modules/0/imports/1/alias"),)


def test_resolution_relation_recipes_drive_both_independent_interpreters(tmp_path):
    source = _source([_symbol("health", "state")])
    second_import = deepcopy(source["modules"][0]["imports"][0])
    second_import["alias"] = "quantity_again"
    source["modules"][0]["imports"].append(second_import)
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = mutable_authorities()
    profile = language_bundle["language"]["resolution_profiles"][0]
    imports_recipe = next(
        item for item in profile["relation_recipes"] if item["id"] == "imports"
    )
    alias_field = next(
        item for item in imports_recipe["fields"] if item["name"] == "alias"
    )
    assert alias_field["term"] == {
        "root": "binding",
        "binding": "import",
        "path": ["alias"],
    }
    alias_field["term"]["path"] = ["package"]

    production = model_module._resolution_diagnostics(
        _production_source_projection(source, kernel, language_bundle),
        _reference_content_identity("model-source-package-v2", source),
        kernel,
        language_bundle,
        projection=project_required_namespace_closure(
            derive_current_namespace_packages(kernel, language_bundle),
            source["package_requirements"],
        ),
        stage="static",
    )
    reference = _reference_check_source(source, kernel, language_bundle)

    assert tuple(item.code for item in production) == (
        "language.name_ambiguity",
        "language.unresolved_name",
    )
    assert reference == (
        ("language.name_ambiguity", "/modules/0/imports/1/package"),
        ("language.unresolved_name", "/modules/0/symbols/0/type"),
    )


def test_resolved_admission_refuses_reidentified_rir_semantic_closure_drift(tmp_path):
    path = tmp_path / "source.json"
    _write_source(path, _source([_symbol("health", "state")]))
    checked = check_model_source(str(path))
    assert isinstance(checked, CheckedModel)
    artifacts = lower_checked_model(checked)
    semantic_artifacts: dict[str, dict[str, Any]] = {
        name: deepcopy(artifacts[name])
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    }
    rir = semantic_artifacts["rir-semantic-payload"]
    closures = cast(
        list[dict[str, Any]],
        cast(dict[str, Any], rir["selected_semantics"])["package_semantic_closures"],
    )
    unit_definitions = next(
        entry["definitions"]
        for entry in closures[0]["definitions"]
        if entry["authority_path"] == "language.quantity.units"
    )
    unit_definitions[0]["dimension"] = "reidentified-dimension"
    semantic_domain, semantic_projection = _reference_rir_semantic_projection(
        checked.language_bundle,
        rir,
    )
    rir["semantic_identity"] = _reference_content_identity(
        semantic_domain,
        semantic_projection,
    )
    rir["content_identity"] = _reference_content_identity(
        "rir-semantic-payload-v2",
        {key: value for key, value in rir.items() if key != "content_identity"},
    )
    resolved = semantic_artifacts["resolved-model"]
    resolved["rir_content_identity"] = rir["content_identity"]
    resolved["rir_semantic_identity"] = rir["semantic_identity"]
    resolved["content_identity"] = _reference_content_identity(
        "resolved-model-v2",
        {key: value for key, value in resolved.items() if key != "content_identity"},
    )

    result = admit_resolved_model(semantic_artifacts)

    assert result.admitted is False


def test_independent_consumer_refuses_unowned_model_check_semantic_selectors():
    for mutation in (
        "old-selector",
        "old-scope",
        "missing",
        "empty",
        "unknown-leaf",
        "unknown-scope",
        "wildcard-on-object",
        "member-on-array",
        "multiple-member-owners",
    ):
        kernel, language_bundle = mutable_authorities()
        language = language_bundle["language"]
        check = language["model_checks"][0]
        if mutation == "old-selector":
            check["selector"] = check.pop("semantic_selector")
        elif mutation == "old-scope":
            scoped = next(
                item
                for item in language["model_checks"]
                if "semantic_scope_selector" in item
            )
            scoped["scope_selector"] = scoped.pop("semantic_scope_selector")
        elif mutation == "missing":
            del check["semantic_selector"]
        elif mutation == "empty":
            check["semantic_selector"] = []
        elif mutation == "unknown-leaf":
            check["semantic_selector"][-1] = "unknown-member"
        elif mutation == "unknown-scope":
            check["semantic_scope_selector"] = ["unknown-member"]
        elif mutation == "wildcard-on-object":
            check["semantic_selector"] = ["schema_version", "*"]
        elif mutation == "member-on-array":
            check["semantic_selector"] = ["modules", "id"]
        else:
            source_schema = next(
                row["schema"]
                for row in language["wire_schemas"]
                if row.get("protocol_role") == "model-source-package"
            )
            modules = source_schema["properties"]["modules"]
            source_schema["properties"]["duplicate-modules"] = deepcopy(modules)
            source_schema["required"].append("duplicate-modules")
        _reidentify_language_bundle(language_bundle)

        result = _consumer_b(kernel, language_bundle)

        assert not result["admitted"], mutation
        expected = ("static", "kernel.vector_mismatch", "language.definitions")
        if mutation == "multiple-member-owners":
            assert expected in result["diagnostics"]
        else:
            assert result["diagnostics"] == [expected]


def test_model_source_routing_follows_the_selected_ldb_profile_without_host_tokens(
    tmp_path, monkeypatch
):
    original = _source([_symbol("health", "state")])

    def renamed_source(document: dict[str, Any]) -> dict[str, Any]:
        document = deepcopy(document)
        manifest = document.pop("manifest")
        manifest["model_key"] = manifest.pop("id")
        manifest["start_module"] = manifest.pop("entry_module")
        document["header"] = manifest
        document["dependencies"] = document.pop("package_requirements")
        sections = document.pop("modules")
        for section in sections:
            section["module_key"] = section.pop("id")
            uses = section.pop("imports")
            for use in uses:
                use["prefix"] = use.pop("alias")
                use["package_id"] = use.pop("package")
                use["export_name"] = use.pop("symbol")
            section["uses"] = uses
            declarations = section.pop("symbols")
            for declaration in declarations:
                declaration["name"] = declaration.pop("symbol")
                declaration["type_ref"] = declaration.pop("type")
            section["declarations"] = declarations
        document["*"] = sections
        return document

    path = tmp_path / "schema-role-source.json"
    source = renamed_source(original)
    _write_source(path, source)
    kernel, candidate_ldb = mutable_authorities()
    language = candidate_ldb["language"]

    def rename_role_member(
        schema: dict[str, Any],
        target_role: str,
        old: str,
        new: str,
        inherited: str | None = None,
    ) -> None:
        role = schema.get("semantic_role", inherited)
        properties = schema.get("properties", {})
        if role == target_role and old in properties:
            properties[new] = properties.pop(old)
            schema["required"] = [
                new if member == old else member
                for member in schema.get("required", [])
            ]
        for child in properties.values():
            if isinstance(child, dict):
                rename_role_member(child, target_role, old, new)
        items = schema.get("items")
        if isinstance(items, dict):
            rename_role_member(items, target_role, old, new)
        for branch in schema.get("oneOf", []):
            if isinstance(branch, dict):
                rename_role_member(branch, target_role, old, new, role)

    source_schema = next(
        item["schema"]
        for item in language["wire_schemas"]
        if item.get("protocol_role") == "model-source-package"
    )
    for role, old, new in (
        ("source", "manifest", "header"),
        ("source", "package_requirements", "dependencies"),
        ("source", "modules", "*"),
        ("manifest", "id", "model_key"),
        ("manifest", "entry_module", "start_module"),
        ("module", "id", "module_key"),
        ("module", "imports", "uses"),
        ("module", "symbols", "declarations"),
        ("import", "alias", "prefix"),
        ("import", "package", "package_id"),
        ("import", "symbol", "export_name"),
        ("symbol", "symbol", "name"),
        ("symbol", "type", "type_ref"),
    ):
        rename_role_member(source_schema, role, old, new)

    for vector in candidate_ldb["vectors"]:
        fixture = vector.get("source_fixture")
        if not isinstance(fixture, dict):
            continue
        fixture["source"] = renamed_source(fixture["source"])
        if fixture["mode"] == "indexed-repeat":
            fixture["collection_path"] = [
                {
                    "modules": "*",
                    "symbols": "declarations",
                    "symbol": "name",
                    "type": "type_ref",
                }.get(item, item)
                for item in fixture["collection_path"]
            ]
            fixture["index_member"] = "name"
            fixture["template"]["name"] = fixture["template"].pop("symbol")
            fixture["template"]["type_ref"] = fixture["template"].pop("type")
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted
    consumer_b = _consumer_b(kernel, candidate_ldb)
    assert consumer_b["admitted"], consumer_b["diagnostics"]
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)
    checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, candidate_ldb)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, ModelSourceContext)
    assert reference_checked.source == source
    assert reference_checked.source_projection.value == original

    production = lower_checked_model(checked)
    reference = _reference_semantic_artifacts(reference_checked)

    assert all(
        production[name] == reference[name]
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
            "debug-map",
        )
    )
    declarations = cast(
        list[dict[str, Any]],
        production["rir-semantic-payload"]["declarations"],
    )
    declaration = declarations[0]
    assert declaration["symbol"] == "health"
    assert "name" not in declaration

    invalid_domain = deepcopy(source)
    invalid_domain["*"][0]["declarations"][0]["domain"] = {
        "minimum": 2,
        "maximum": 1,
    }
    assert _reference_check_source(invalid_domain, kernel, candidate_ldb) == (
        ("language.invalid_domain", "/*/0/declarations/0/domain"),
    )

    extra_authored_member = deepcopy(source)
    extra_authored_member["*"][0]["declarations"][0]["symbol"] = "health"
    assert _reference_check_source(extra_authored_member, kernel, candidate_ldb) == (
        ("language.source_contract_mismatch", "/*/0/declarations/0/symbol"),
    )

    exhausted = deepcopy(source)
    symbol = exhausted["*"][0]["declarations"][0]
    limit = candidate_ldb["resources"]["max_symbols"]
    exhausted["*"][0]["declarations"] = [
        {**deepcopy(symbol), "name": f"symbol-{index}"} for index in range(limit + 1)
    ]
    assert _reference_check_source(exhausted, kernel, candidate_ldb) == (
        ("language.resource_exhausted", f"/*/0/declarations/{limit}"),
    )


def test_schema_error_mapping_uses_the_complete_ldb_selector_path():
    schema = {
        "type": "object",
        "properties": {
            "metadata": {
                "type": "object",
                "properties": {"unit": {"type": "string"}},
            }
        },
    }
    error = next(
        jsonschema.Draft202012Validator(schema).iter_errors({"metadata": {"unit": 7}})
    )
    _, language_bundle = mutable_authorities()

    code = model_module._schema_error_code(error, language_bundle)

    assert code == "language.source_contract_mismatch"


def test_resolver_implementation_identity_is_receipt_only(tmp_path):
    path = tmp_path / "receipt-only-resolver.json"
    _write_source(path, _source([_symbol("health", "state")]))
    checked = check_model_source(str(path))
    assert isinstance(checked, CheckedModel)

    artifacts = lower_checked_model(checked)

    resolution_profile = cast(
        dict[str, Any], artifacts["package-lock"]["resolution_profile"]
    )
    assert "resolver_identity" not in resolution_profile
    assert (
        artifacts["resolution-receipt"]["resolver"]
        == "gda-balancing.python-exact-resolver-v1"
    )


def test_lowerers_follow_renamed_ldb_rule_and_judgment_tokens_without_host_changes(
    tmp_path,
):
    path = tmp_path / "renamed-authority.json"
    source = _source([_symbol("health", "state"), _symbol("result", "output")])
    source["entrypoints"] = [
        {
            "id": "identity",
            "operation": {"package": "core.quantity", "id": "quantity.identity"},
            "arguments": [
                {
                    "port": "value",
                    "operand": {"kind": "symbol", "module": "main", "symbol": "health"},
                }
            ],
            "result": {"kind": "symbol", "module": "main", "symbol": "result"},
        }
    ]
    _write_source(path, source)
    checked = check_model_source(str(path))
    assert isinstance(checked, CheckedModel)
    candidate_ldb = deepcopy(checked.language_bundle)
    language = candidate_ldb["language"]
    renames: dict[str, str] = {}
    invocation_tokens: dict[str, tuple[str, str]] = {}
    for rule in language["rules"]:
        old_id = rule["id"]
        new_id = f"{old_id}.renamed"
        renames[old_id] = new_id
        rule["id"] = new_id
        rule["judgment"] = f"{rule['judgment']}.renamed"
        invocation_tokens[new_id] = (rule["phase"], rule["judgment"])
    for capability in language["capabilities"]:
        capability["rule"] = renames[capability["rule"]]
    for lowering in language["model_lowerings"]:
        for chain_member in ("rule_chain", "structured_rule_chain"):
            for invocation in lowering[chain_member]:
                invocation["rule"] = renames[invocation["rule"]]
                phase, judgment = invocation_tokens[invocation["rule"]]
                invocation["phase"] = phase
                invocation["judgment"] = judgment
    for operation in language["operations"]:
        operation["rule"] = renames[operation["rule"]]
    for package in language["packages"]:
        package["exports"]["language_rules"] = [
            renames[rule_id] for rule_id in package["exports"]["language_rules"]
        ]
    for vector in candidate_ldb["vectors"]:
        if "rule" not in vector:
            continue
        vector["rule"] = renames[vector["rule"]]
        phase, judgment = invocation_tokens[vector["rule"]]
        vector["input"]["phase"] = phase
        vector["input"]["judgment"] = judgment
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted
    candidate = check_model_source_value(
        checked.source, kernel=checked.kernel, language_bundle=candidate_ldb
    )
    assert isinstance(candidate, CheckedModel)

    artifacts = lower_checked_model(candidate)
    production = artifacts["rir-semantic-payload"]
    reference = _reference_rir(candidate)

    assert production == reference
    selected_semantics = cast(dict[str, Any], production["selected_semantics"])
    operation_projections = cast(list[dict[str, Any]], selected_semantics["operations"])
    assert [row["definition"]["id"] for row in operation_projections] == [
        "quantity.identity",
    ]
    assert operation_projections[0]["definition"]["rule"] == "quantity.lower.renamed"
    assert (
        cast(list[dict[str, Any]], production["entrypoints"])[0]["operation"]["id"]
        == "quantity.identity"
    )
    lock_operations = cast(
        list[dict[str, Any]], artifacts["package-lock"]["operations"]
    )
    assert {item["definition"]["rule"] for item in lock_operations} == {
        "quantity.lower.renamed"
    }


def test_independent_frontends_follow_a_renamed_model_check_reason_without_host_changes(
    tmp_path, monkeypatch
):
    path = tmp_path / "renamed-check-reason.json"
    source = _source([_symbol("same", "state"), _symbol("same", "output")])
    _write_source(path, source)
    old_reason = "model.reason.duplicate-symbol"
    old_diagnostic = "language.duplicate_symbol"
    kernel, candidate_ldb, new_diagnostic = _renamed_reason_authorities(
        old_reason, old_diagnostic
    )
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, candidate_ldb)

    assert isinstance(production, Schema2RefusalReport)
    assert isinstance(reference, tuple)
    assert (
        tuple(item.code for item in production.diagnostics)
        == tuple(code for code, _pointer in reference)
        == (new_diagnostic,)
    )
    assert reference == ((new_diagnostic, "/modules/0/symbols/1/symbol"),)


def test_independent_frontends_follow_a_renamed_resolution_reason_without_host_changes(
    tmp_path, monkeypatch
):
    path = tmp_path / "renamed-resolution-reason.json"
    source = _source([_symbol("health", "state")])
    source["package_requirements"][0] = "host.missing"
    source["modules"][0]["imports"][0]["package"] = "host.missing"
    _write_source(path, source)
    kernel, candidate_ldb, new_diagnostic = _renamed_reason_authorities(
        "model.reason.package-unavailable",
        "language.package_unavailable",
    )
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, candidate_ldb)

    assert isinstance(production, Schema2RefusalReport)
    assert isinstance(reference, tuple)
    assert (
        tuple(item.code for item in production.diagnostics)
        == tuple(code for code, _pointer in reference)
        == (new_diagnostic,)
    )
    assert reference == ((new_diagnostic, "/package_requirements/0"),)


def test_frontend_failure_boundaries_follow_renamed_ldb_diagnostics_without_host_changes(
    tmp_path, monkeypatch
):
    cases = (
        (
            "model.reason.source-too-large",
            "language.source_too_large",
            b" " * (1024 * 1024 + 1),
        ),
        (
            "model.reason.source-parse-failure",
            "language.source_parse_failure",
            b'{"schema_version":"2.0.0",',
        ),
        (
            "model.reason.source-contract-mismatch",
            "language.source_contract_mismatch",
            json.dumps(
                {
                    **_source([_symbol("health", "state")]),
                    "modules": [
                        {
                            **_source([_symbol("health", "state")])["modules"][0],
                            "symbols": [
                                {
                                    **_symbol("health", "state"),
                                    "role": "host-defined-role",
                                }
                            ],
                        }
                    ],
                }
            ).encode(),
        ),
    )
    for index, (reason_id, diagnostic, data) in enumerate(cases):
        kernel, candidate_ldb, renamed = _renamed_reason_authorities(
            reason_id, diagnostic
        )
        _inject_authority_context(monkeypatch, kernel, candidate_ldb)
        path = tmp_path / f"failure-{index}.json"
        path.write_bytes(data)

        result = check_model_source(str(path))

        assert isinstance(result, Schema2RefusalReport)
        assert result.diagnostics[0].code == renamed


def test_resolved_admission_follows_a_renamed_ldb_diagnostic_without_host_changes(
    monkeypatch,
):
    kernel, candidate_ldb, renamed = _renamed_reason_authorities(
        "model.reason.resolved-authority-mismatch",
        "language.resolved_authority_mismatch",
    )
    source = _source([_symbol("health", "state")])
    checked = check_model_source_value(
        source, kernel=kernel, language_bundle=candidate_ldb
    )
    assert isinstance(checked, CheckedModel)
    artifacts = lower_checked_model(checked)
    semantic_artifacts: dict[str, dict[str, Any]] = {
        name: deepcopy(artifacts[name])
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    }
    rir = semantic_artifacts["rir-semantic-payload"]
    cast(list[dict[str, Any]], rir["declarations"])[0]["role"] = "host-defined-role"
    semantic_domain, semantic_projection = _reference_rir_semantic_projection(
        candidate_ldb,
        rir,
    )
    rir["semantic_identity"] = _reference_content_identity(
        semantic_domain,
        semantic_projection,
    )
    semantic_artifacts["rir-semantic-payload"]["content_identity"] = (
        _reference_content_identity(
            "rir-semantic-payload-v2",
            {
                key: value
                for key, value in semantic_artifacts["rir-semantic-payload"].items()
                if key != "content_identity"
            },
        )
    )
    semantic_artifacts["resolved-model"]["rir_content_identity"] = semantic_artifacts[
        "rir-semantic-payload"
    ]["content_identity"]
    semantic_artifacts["resolved-model"]["rir_semantic_identity"] = semantic_artifacts[
        "rir-semantic-payload"
    ]["semantic_identity"]
    semantic_artifacts["resolved-model"]["content_identity"] = (
        _reference_content_identity(
            "resolved-model-v2",
            {
                key: value
                for key, value in semantic_artifacts["resolved-model"].items()
                if key != "content_identity"
            },
        )
    )
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    result = admit_resolved_model(semantic_artifacts)

    assert result.admitted is False
    assert result.diagnostics == (renamed,)
