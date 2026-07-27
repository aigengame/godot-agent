"""Independent lowerer/consumer conformance for the #539 Model tracer."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import gda_balancing.schema2.model as model_module
import jsonschema
from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.authority_graph import (
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.schema2.bootstrap import admit_authorities
from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.model import (
    CheckedModel,
    admit_resolved_model,
    check_model_source,
    lower_checked_model,
)


class _ReferenceRuntimeProjectionExhausted(Exception):
    pass


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
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _reference_content_identity(domain: str, value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            f"gda-balancing:{domain}:".encode() + _reference_encoded(value)
        ).hexdigest()
    )


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
    }


def _source(symbols: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "example.quantity-model",
            "version": "1.0.0",
            "entry_module": "main",
        },
        "package_requirements": [{"id": "core.quantity", "version": "2.0.0"}],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.0.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": symbols,
            }
        ],
    }


def _write_source(path: Path, source: dict[str, Any]) -> None:
    path.write_text(json.dumps(source), encoding="utf-8")


def _reference_select(root: Any, selector: list[str]) -> list[Any]:
    values = [root]
    for segment in selector:
        selected: list[Any] = []
        for value in values:
            if segment == "*" and isinstance(value, list):
                selected.extend(value)
            elif isinstance(value, dict) and segment in value:
                selected.append(value[segment])
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


def _exact_path(root: Any, dotted: str) -> Any:
    value = root
    for segment in dotted.split("."):
        value = value[segment]
    return value


def _reidentify_language_bundle(language_bundle: dict[str, Any]) -> None:
    assert isinstance(language_bundle, LanguageBundleIndex)
    kernel, _ = load_authorities()
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]
    projections_by_path = {
        projection["authority_path"]: projection for projection in projections
    }
    for package in language_bundle["language"]["packages"]:
        package["vector_definitions"] = [
            deepcopy(
                next(
                    vector
                    for vector in language_bundle["vectors"]
                    if vector["id"] == vector_id
                )
            )
            for vector_id in package["vectors"]
        ]
        for entry in package["semantic_closure"]:
            projection = projections_by_path[entry["authority_path"]]
            definitions = _exact_path(language_bundle, entry["authority_path"])
            owned = _reference_path(package, projection["owners_path"])
            key_member = projection["key_member"]
            entry["definitions"] = deepcopy(
                [
                    definition
                    for definition in definitions
                    if (definition if key_member is None else definition[key_member])
                    in owned
                ]
            )
        runtime_paths = set(package["runtime_semantic_paths"])
        package["semantic_identity"] = _reference_content_identity(
            "domain-package-semantic-closure-v2",
            [
                entry
                for entry in package["semantic_closure"]
                if entry["authority_path"] in runtime_paths
            ],
        )
        package["content_identity"] = _reference_content_identity(
            "domain-package-release-v2",
            {key: value for key, value in package.items() if key != "content_identity"},
        )
    packages = sorted(
        deepcopy(language_bundle["language"]["packages"]),
        key=lambda package: (package["id"], package["version"]),
    )
    member_sizes = [len(_reference_encoded(package)) for package in packages]
    root = deepcopy(language_bundle.root)
    root["resources"] = deepcopy(language_bundle["resources"])
    root["package_descriptors"] = [
        {
            "artifact_kind": package["artifact_kind"],
            "byte_size": size,
            "content_identity": package["content_identity"],
            "id": package["id"],
            "version": package["version"],
        }
        for package, size in zip(packages, member_sizes, strict=True)
    ]
    root["content_identity"] = _reference_content_identity(
        "language-definition-bundle-v2",
        {key: value for key, value in root.items() if key != "content_identity"},
    )
    rebuilt = derive_language_index(
        root,
        packages,
        kernel["admission"]["required_language_members"],
        root_byte_size=len(_reference_encoded(root)),
        member_byte_sizes=member_sizes,
        descriptor_order=kernel["meta_format"]["language_bundle"]["package_descriptor"][
            "canonical_order"
        ],
    )
    language_bundle.root = deepcopy(rebuilt.root)
    language_bundle.package_releases = deepcopy(rebuilt.package_releases)
    language_bundle.root_byte_size = rebuilt.root_byte_size
    language_bundle.member_byte_sizes = rebuilt.member_byte_sizes
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
) -> tuple[str, ...] | CheckedModel:
    """Independently interpret the admitted source schema and model-check relation."""
    language = language_bundle["language"]
    source_schema = next(
        item["schema"]
        for item in language["wire_schemas"]
        if item["artifact_kind"] == "model-source-package"
    )
    schema_errors = sorted(
        jsonschema.Draft202012Validator(source_schema).iter_errors(source),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    reasons = {item["id"]: item for item in language["reasons"]}
    if schema_errors:
        path = tuple(str(part) for part in schema_errors[0].absolute_path)
        for check in language["model_checks"]:
            selector = tuple([*check.get("scope_selector", []), *check["selector"]])
            if len(selector) == len(path) and all(
                expected == "*" or expected == actual
                for expected, actual in zip(selector, path, strict=True)
            ):
                return (reasons[check["reason"]]["diagnostic"],)
        source_contract_reasons = [
            item
            for item in reasons.values()
            if item["stage"] == "static"
            and item["predicate"]["operation"] == "not-equal"
        ]
        assert len(source_contract_reasons) == 1
        return (source_contract_reasons[0]["diagnostic"],)

    diagnostics_by_stage: dict[str, list[str]] = {}
    for check in language["model_checks"]:
        reason = reasons[check["reason"]]
        scopes = (
            _reference_select(source, check["scope_selector"])
            if "scope_selector" in check
            else [source]
        )
        for scope in scopes:
            values = _reference_select(scope, check["selector"])
            if _reference_reason_matches(language_bundle, reason, values):
                diagnostics_by_stage.setdefault(reason["stage"], []).append(
                    reason["diagnostic"]
                )

    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    resource_reasons = [
        reason
        for reason in reasons.values()
        if reason["predicate"].get("limit_path") == "resources.max_rule_match_steps"
    ]
    assert len(resource_reasons) == 1
    resource_diagnostic = resource_reasons[0]["diagnostic"]
    step_limit = language_bundle["resources"]["max_rule_match_steps"]
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
    requirements_member = profile["requirements_member"]
    requirement_package_member = profile["requirement_package_member"]
    requirement_version_member = profile["requirement_version_member"]
    packages_by_coordinate = {
        (package["id"], package["version"]): package for package in available_packages
    }
    selected_packages: dict[str, dict[str, Any]] = {}
    pending = [
        (
            requirement[requirement_package_member],
            requirement[requirement_version_member],
        )
        for requirement in source[requirements_member]
    ]
    while pending:
        coordinate = pending.pop(0)
        package = packages_by_coordinate.get(coordinate)
        if package is None or package["id"] in selected_packages:
            continue
        selected_packages[package["id"]] = package
        for dependency in package["dependencies"]["required"]:
            pending.append((dependency["id"], dependency["version"]))
    selected_package_values = [
        selected_packages[package_id] for package_id in sorted(selected_packages)
    ]

    def read_term(term: dict[str, Any], environment: dict[str, Any]) -> Any:
        if term["root"] == "source":
            value: Any = source
        elif term["root"] == "language":
            value = language
        elif term["root"] == "selected-packages":
            value = selected_package_values
        elif term["root"] == "binding":
            value = environment[term["binding"]]
        else:
            raise AssertionError(
                f"reference consumer observed unknown term root: {term['root']}"
            )
        for segment in term["path"]:
            value = value[segment]
        return value

    try:
        for recipe in profile["relation_recipes"]:
            environments: list[dict[str, Any]] = [{}]
            for binding in recipe["bindings"]:
                next_environments = []
                for environment in environments:
                    candidates = read_term(binding["source"], environment)
                    assert isinstance(candidates, list)
                    for candidate in candidates:
                        consume_base()
                        next_environments.append(
                            {**environment, binding["name"]: candidate}
                        )
                environments = next_environments
            relation_rows = []
            for environment in environments:
                rejected = False
                for predicate in recipe["predicates"]:
                    consume_base()
                    if predicate["operator"] == "equal" and read_term(
                        predicate["left"], environment
                    ) != read_term(predicate["right"], environment):
                        rejected = True
                        break
                if rejected:
                    continue
                values = {}
                for field in recipe["fields"]:
                    consume_base()
                    values[field["name"]] = read_term(field["term"], environment)
                relation_rows.append({"values": values})
            relations[recipe["id"]] = relation_rows
    except BudgetExhausted:
        return (resource_diagnostic,)

    def matches(
        subject: dict[str, Any],
        target: dict[str, Any],
        fields: list[dict[str, str]],
    ) -> bool:
        return all(
            subject["values"][field["subject"]] == target["values"][field["target"]]
            for field in fields
        )

    def law_fails(law: dict[str, Any], consume: Callable[[], None]) -> bool:
        operator = law["operator"]
        if operator == "require-match":
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
                    return True
            return False
        if operator == "require-unique":
            fields = [*law["scope"], *law["key"]]
            keys = []
            for item in relations[law["relation"]]:
                consume()
                keys.append(tuple(item["values"][field] for field in fields))
            return len(keys) != len(set(keys))
        if operator == "require-single-value":
            grouped: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
            for item in relations[law["relation"]]:
                consume()
                group = tuple(
                    item["values"][field] for field in [*law["scope"], *law["group"]]
                )
                value = tuple(item["values"][field] for field in law["value"])
                grouped.setdefault(group, set()).add(value)
            return any(len(values) != 1 for values in grouped.values())
        raise AssertionError(
            f"reference consumer observed unknown resolution law: {operator}"
        )

    resolution_meta = kernel["meta_format"]["resolution_judgment"]
    operations = {item["id"]: item for item in resolution_meta["operations"]}
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
                if operation["stage"] == stage and law_fails(
                    operation["law"], consume_stage
                ):
                    stage_diagnostics.append(reasons[judgment["reason"]]["diagnostic"])
        except BudgetExhausted:
            return (resource_diagnostic,)
        if stage_diagnostics:
            return tuple(dict.fromkeys(stage_diagnostics))
    checked = CheckedModel(
        source=source,
        source_identity=_reference_content_identity(
            profile["source_identity_domain"], source
        ),
        kernel=kernel,
        language_bundle=language_bundle,
    )
    try:
        _reference_semantic_artifacts(checked)
    except _ReferenceRuntimeProjectionExhausted:
        runtime_reasons = [
            reason
            for reason in reasons.values()
            if reason["predicate"].get("limit_path")
            == "resources.max_runtime_projection_steps"
        ]
        assert len(runtime_reasons) == 1
        return (runtime_reasons[0]["diagnostic"],)
    return checked


def _renamed_reason_authorities(
    reason_id: str, diagnostic: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    kernel, candidate_ldb = deepcopy(load_authorities())
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


def _reference_resolved_symbols(checked: CheckedModel) -> list[dict[str, Any]]:
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    requirements = {
        (
            item[profile["requirement_package_member"]],
            item[profile["requirement_version_member"]],
        )
        for item in checked.source[profile["requirements_member"]]
    }
    packages = {(item["id"], item["version"]): item for item in language["packages"]}
    selected_symbols = _reference_select(checked.source, lowering["source_selector"])
    selected_symbol_ids = {id(item) for item in selected_symbols}
    resolved_symbol_ids: set[int] = set()
    model_id = checked.source
    for part in profile["manifest_id_path"].split("."):
        model_id = model_id[part]
    rows = []
    for module in checked.source[profile["modules_member"]]:
        imports = {
            item[profile["import_alias_member"]]: item
            for item in module[profile["imports_member"]]
        }
        for symbol in module[profile["symbols_member"]]:
            if id(symbol) not in selected_symbol_ids:
                continue
            resolved_symbol_ids.add(id(symbol))
            imported = imports[symbol[profile["symbol_type_member"]]]
            package_key = (
                imported[profile["import_package_member"]],
                imported[profile["import_version_member"]],
            )
            assert package_key in requirements
            package = packages[package_key]
            assert imported[profile["import_symbol_member"]] in {
                item["id"] for item in package["exports"]["types"]
            }
            fields = {
                name: value
                for name, value in symbol.items()
                if name
                not in {
                    profile["symbol_name_member"],
                    profile["symbol_type_member"],
                }
            }
            fields[profile["symbol_fact_member"]] = symbol[
                profile["symbol_name_member"]
            ]
            fields["resolved_symbol"] = {
                "model": model_id,
                "module": module[profile["module_id_member"]],
                "name": symbol[profile["symbol_name_member"]],
            }
            fields["type_identity"] = {
                "package": package_key[0],
                "version": package_key[1],
                "symbol": imported[profile["import_symbol_member"]],
            }
            rows.append(fields)
    assert resolved_symbol_ids == selected_symbol_ids
    return sorted(
        rows,
        key=lambda item: (
            item["resolved_symbol"]["model"],
            item["resolved_symbol"]["module"],
            item["resolved_symbol"]["name"],
        ),
    )


def _reference_artifact(
    checked: CheckedModel, artifact_kind: str, payload: dict[str, Any]
) -> dict[str, Any]:
    language = checked.language_bundle["language"]
    contract = next(
        item
        for item in language["artifact_contracts"]
        if item["artifact_kind"] == artifact_kind
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
        "artifact_kind": artifact_kind,
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


def _reference_package_lock(checked: CheckedModel) -> dict[str, Any]:
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    available = {(item["id"], item["version"]): item for item in language["packages"]}
    requirements = sorted(
        [
            {
                "id": item[profile["requirement_package_member"]],
                "version": item[profile["requirement_version_member"]],
            }
            for item in checked.source[profile["requirements_member"]]
        ],
        key=lambda item: (item["id"], item["version"]),
    )
    selected: dict[str, dict[str, Any]] = {}
    pending = list(requirements)
    dependency_edges = []
    while pending:
        requirement = pending.pop(0)
        package = available[(requirement["id"], requirement["version"])]
        previous = selected.get(package["id"])
        if previous is not None:
            assert previous["semantic_identity"] == package["semantic_identity"]
            continue
        selected[package["id"]] = package
        for dependency_constraint in sorted(
            package["dependencies"]["required"],
            key=lambda item: (item["id"], item["version"]),
        ):
            dependency = available[
                (dependency_constraint["id"], dependency_constraint["version"])
            ]
            dependency_edges.append(
                {
                    "from_package": package["id"],
                    "kind": "required",
                    "to_package": dependency["id"],
                    "to_version": dependency["version"],
                }
            )
            pending.append({"id": dependency["id"], "version": dependency["version"]})
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
        return sorted(rows, key=lambda item: item["definition"]["id"])

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
            item["to_version"],
        )
    )
    types = sorted(
        [
            {**exported_type, "package": package["id"]}
            for package in selected_packages
            for exported_type in package["exports"]["types"]
        ],
        key=lambda item: item["id"],
    )
    payload = {
        "resolution_profile": profile,
        "root_requirements": requirements,
        "packages": [
            {
                "id": package["id"],
                "version": package["version"],
                "content_identity": package["content_identity"],
                "semantic_identity": package["semantic_identity"],
            }
            for package in selected_packages
        ],
        "package_semantic_closures": [
            {
                "package": package["id"],
                "semantic_identity": package["semantic_identity"],
                "definitions": [
                    entry
                    for entry in package["semantic_closure"]
                    if entry["authority_path"] in set(package["runtime_semantic_paths"])
                ],
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
                "version": package["version"],
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


def _reference_rir(
    checked: CheckedModel, lock: dict[str, Any] | None = None
) -> dict[str, Any]:
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    if lock is None:
        lock = _reference_package_lock(checked)
    declarations = []
    for symbol in _reference_resolved_symbols(checked):
        fact = {"kind": lowering["initial_fact_kind"], "fields": symbol}
        for invocation in lowering["rule_chain"]:
            fact = _reference_apply(language, invocation, fact)
        declarations.append(fact["fields"])
    return _reference_artifact(
        checked,
        "rir-semantic-payload",
        {
            lowering["output_member"]: declarations,
            "selected_semantics": _reference_runtime_projection(
                checked, lock, declarations, lowering
            ),
        },
    )


def _reference_runtime_projection(
    checked: CheckedModel,
    lock: dict[str, Any],
    declarations: list[dict[str, Any]],
    lowering: dict[str, Any],
) -> dict[str, Any]:
    profile = lowering["runtime_projection"]
    accounting = checked.kernel["meta_format"]["runtime_projection"][
        "resource_accounting"
    ]
    limit = checked.language_bundle["resources"][accounting["limit_member"]]
    steps = 0

    def consume() -> None:
        nonlocal steps
        if steps >= limit:
            raise _ReferenceRuntimeProjectionExhausted
        steps += 1

    def descend(value: Any, path: list[str]) -> Any:
        if not path:
            return value
        return descend(value[path[0]], path[1:])

    catalogs: dict[str, list[tuple[str, str | None, Any]]] = {}
    for specification in profile["collections"]:
        source = specification["source"]
        rows: list[tuple[str, str | None, Any]]
        if source["kind"] == "lock-member":
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
    for seed in profile["seeds"]:
        for declaration in declarations:
            package = descend(declaration, seed["declaration_package_path"])
            for index, row in enumerate(catalogs[seed["collection"]]):
                consume()
                if row[0] != package:
                    continue
                assert seed["operator"] == "declaration-field"
                if descend(row[2], seed["target_path"]) == descend(
                    declaration, seed["declaration_path"]
                ):
                    selected[seed["collection"]].add(index)

    previous = None
    while previous != selected:
        previous = {name: set(indexes) for name, indexes in selected.items()}
        for edge in profile["edges"]:
            for source_index in selected[edge["source_collection"]]:
                consume()
                source = catalogs[edge["source_collection"]][source_index]
                expected = descend(source[2], edge["source_path"])
                for target_index, target in enumerate(
                    catalogs[edge["target_collection"]]
                ):
                    consume()
                    if edge["same_package"] and source[0] != target[0]:
                        continue
                    if descend(target[2], edge["target_path"]) == expected:
                        selected[edge["target_collection"]].add(target_index)

    selected_packages = {
        catalogs[name][index][0]
        for name, indexes in selected.items()
        for index in indexes
    }
    projection: dict[str, Any] = {}
    selected_closure_values: dict[tuple[str, str], list[Any]] = {}
    for specification in profile["collections"]:
        rows = []
        for index, row in enumerate(catalogs[specification["id"]]):
            consume()
            if index in selected[specification["id"]]:
                rows.append(row)
        for package, authority_path, value in rows:
            if authority_path is not None:
                selected_closure_values.setdefault(
                    (package, authority_path), []
                ).append(value)
        member = specification["output_member"]
        if member is None:
            continue
        if specification["output_shape"] == "as-is":
            projection[member] = [row[2] for row in rows]
        elif specification["output_shape"] == "package-definition":
            projection[member] = [
                {"package": row[0], "definition": row[2]} for row in rows
            ]
        else:
            projection[member] = [row[2] for row in rows]

    for output in profile["outputs"]:
        source_rows = lock[output["source_member"]]
        if output["kind"] == "selected-packages":
            values = []
            for row in source_rows:
                consume()
                if row[output["package_member"]] in selected_packages:
                    values.append({member: row[member] for member in output["members"]})
        elif output["kind"] == "selected-semantic-closures":
            values = []
            for closure in source_rows:
                consume()
                package = closure[output["package_member"]]
                if package not in selected_packages:
                    continue
                entries = []
                for entry in closure[output["entries_member"]]:
                    authority_path = entry[output["authority_path_member"]]
                    definitions = selected_closure_values.get((package, authority_path))
                    if definitions:
                        entries.append(
                            {
                                output["authority_path_member"]: authority_path,
                                output["definitions_member"]: definitions,
                            }
                        )
                if entries:
                    values.append(
                        {
                            output["package_member"]: package,
                            output["entries_member"]: entries,
                        }
                    )
        else:
            raise AssertionError(
                f"reference consumer observed unknown projection output: "
                f"{output['kind']}"
            )
        projection[output["output_member"]] = values
    return projection


def _reference_pointer(parts: list[object]) -> str:
    return "".join(
        "/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _reference_debug_map(checked: CheckedModel, rir: dict[str, Any]) -> dict[str, Any]:
    language = checked.language_bundle["language"]
    lowering = _reference_lowering(language)
    profile = next(
        item
        for item in language["resolution_profiles"]
        if item["id"] == lowering["resolution_profile"]
    )
    modules_member = profile["modules_member"]
    symbols_member = profile["symbols_member"]
    module_id_member = profile["module_id_member"]
    symbol_name_member = profile["symbol_name_member"]
    model_id = _exact_path(checked.source, profile["manifest_id_path"])
    pointers = {
        (
            model_id,
            module[module_id_member],
            symbol[symbol_name_member],
        ): [modules_member, module_index, symbols_member, symbol_index]
        for module_index, module in enumerate(checked.source[modules_member])
        for symbol_index, symbol in enumerate(module[symbols_member])
    }
    declarations = rir[lowering["output_member"]]
    return _reference_artifact(
        checked,
        "debug-map",
        {
            "source_identity": checked.source_identity,
            "rir_identity": rir["content_identity"],
            "entries": [
                {
                    "rir_pointer": _reference_pointer(
                        [lowering["output_member"], index]
                    ),
                    "source_pointer": _reference_pointer(
                        pointers[
                            (
                                declaration["resolved_symbol"]["model"],
                                declaration["resolved_symbol"]["module"],
                                declaration["resolved_symbol"]["name"],
                            )
                        ]
                    ),
                }
                for index, declaration in enumerate(declarations)
            ],
        },
    )


def _reference_semantic_artifacts(
    checked: CheckedModel,
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
            "rir_identity": rir["content_identity"],
        },
    )
    return {
        "package-lock": lock,
        "rir-semantic-payload": rir,
        "resolved-model": resolved,
        "debug-map": _reference_debug_map(checked, rir),
    }


def _reference_admits_semantic_artifacts(
    candidate: dict[str, dict[str, Any]], checked: CheckedModel
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
        "packages": [
            {"id": item["id"], "version": item["version"]} for item in lock["packages"]
        ],
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
    kernel, language_bundle = load_authorities()
    vectors = [item for item in language_bundle["vectors"] if "source_fixture" in item]
    vector_ids = {item["id"] for item in vectors}
    package = next(
        package
        for package in language_bundle["language"]["packages"]
        if vector_ids <= set(package["vectors"])
    )
    assert {item["category"] for item in vectors} == {
        "positive",
        "negative",
        "boundary",
        "mutation",
        "semantic-equivalence",
    }
    assert {item["id"] for item in vectors} <= set(package["vectors"])
    assert all(
        entry["authority_path"] != "vectors" for entry in package["semantic_closure"]
    )

    results: dict[str, dict[str, Any] | None] = {}
    diagnostic_stages = {
        item["code"]: item["stage"] for item in language_bundle["diagnostics"]
    }
    output_member = _reference_lowering(language_bundle["language"])["output_member"]
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
            assert isinstance(production_checked, Schema2RefusalReport)
            assert isinstance(reference_checked, tuple)
            production_diagnostics = [
                {"code": item.code, "stage": production_checked.stage}
                for item in production_checked.diagnostics
            ]
            reference_diagnostics = [
                {"code": code, "stage": diagnostic_stages[code]}
                for code in reference_checked
            ]
            assert production_diagnostics == reference_diagnostics
            assert production_diagnostics == expected["diagnostics"]
            assert expected["semantic_artifacts"] is False
            results[vector["id"]] = None
            continue

        assert isinstance(production_checked, CheckedModel)
        assert isinstance(reference_checked, CheckedModel)
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
    kernel, language_bundle = load_authorities()
    checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, language_bundle)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, CheckedModel)

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


def test_resolution_stage_order_is_authoritative_across_independent_consumers(
    tmp_path,
):
    source = _source([_symbol("health", "state")])
    source["package_requirements"][0]["version"] = "9.9.9"
    source["modules"][0]["imports"][0]["version"] = "9.9.9"
    source["modules"][0]["imports"].append(deepcopy(source["modules"][0]["imports"][0]))
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = load_authorities()

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, language_bundle)

    assert isinstance(production, Schema2RefusalReport)
    assert production.stage == "static"
    assert tuple(item.code for item in production.diagnostics) == (
        "language.name_ambiguity",
        "language.unresolved_name",
    )
    assert reference == (
        "language.name_ambiguity",
        "language.unresolved_name",
    )


def test_resolution_step_budget_drives_both_independent_consumers():
    source = _source([_symbol("health", "state")])
    kernel, language_bundle = deepcopy(load_authorities())
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
        source,
        _reference_content_identity("model-source-package-v2", source),
        kernel,
        language_bundle,
        stage="static",
    )
    reference = _reference_check_source(source, kernel, language_bundle)

    assert tuple(item.code for item in production) == ("language.resource_exhausted",)
    assert reference == ("language.resource_exhausted",)


def test_runtime_projection_budget_drives_both_independent_consumers(
    tmp_path, monkeypatch
):
    source = _source([_symbol("health", "state")])
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = deepcopy(load_authorities())
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
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, language_bundle)
    )

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, language_bundle)

    assert isinstance(production, Schema2RefusalReport)
    assert tuple(item.code for item in production.diagnostics) == (
        "language.resource_exhausted",
    )
    assert reference == ("language.resource_exhausted",)


def test_resolution_law_fields_drive_both_independent_interpreters(tmp_path):
    source = _source([_symbol("health", "state")])
    second_import = deepcopy(source["modules"][0]["imports"][0])
    second_import["alias"] = "quantity_again"
    source["modules"][0]["imports"].append(second_import)
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = deepcopy(load_authorities())
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
        source,
        _reference_content_identity("model-source-package-v2", source),
        kernel,
        language_bundle,
        stage="static",
    )
    reference = _reference_check_source(source, kernel, language_bundle)

    assert tuple(item.code for item in production) == ("language.name_ambiguity",)
    assert reference == ("language.name_ambiguity",)


def test_resolution_relation_recipes_drive_both_independent_interpreters(tmp_path):
    source = _source([_symbol("health", "state")])
    second_import = deepcopy(source["modules"][0]["imports"][0])
    second_import["alias"] = "quantity_again"
    source["modules"][0]["imports"].append(second_import)
    path = tmp_path / "source.json"
    _write_source(path, source)
    kernel, language_bundle = deepcopy(load_authorities())
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
        source,
        _reference_content_identity("model-source-package-v2", source),
        kernel,
        language_bundle,
        stage="static",
    )
    reference = _reference_check_source(source, kernel, language_bundle)

    assert tuple(item.code for item in production) == (
        "language.name_ambiguity",
        "language.unresolved_name",
    )
    assert reference == (
        "language.name_ambiguity",
        "language.unresolved_name",
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
    rir["content_identity"] = _reference_content_identity(
        "rir-semantic-payload-v2",
        {key: value for key, value in rir.items() if key != "content_identity"},
    )
    resolved = semantic_artifacts["resolved-model"]
    resolved["rir_identity"] = rir["content_identity"]
    resolved["content_identity"] = _reference_content_identity(
        "resolved-model-v2",
        {key: value for key, value in resolved.items() if key != "content_identity"},
    )

    result = admit_resolved_model(semantic_artifacts)

    assert result.admitted is False


def test_model_source_routing_follows_the_selected_ldb_profile_without_host_tokens(
    tmp_path, monkeypatch
):
    def renamed_source(document: dict[str, Any]) -> dict[str, Any]:
        document = deepcopy(document)
        manifest = document.pop("manifest")
        manifest["model_key"] = manifest.pop("id")
        manifest["start_module"] = manifest.pop("entry_module")
        document["header"] = manifest
        document["dependencies"] = [
            {
                "package_id": item["id"],
                "release": item["version"],
            }
            for item in document.pop("package_requirements")
        ]
        sections = document.pop("modules")
        for section in sections:
            section["module_key"] = section.pop("id")
            uses = section.pop("imports")
            for use in uses:
                use["prefix"] = use.pop("alias")
                use["package_id"] = use.pop("package")
                use["release"] = use.pop("version")
                use["export_name"] = use.pop("symbol")
            section["uses"] = uses
            declarations = section.pop("symbols")
            for declaration in declarations:
                declaration["name"] = declaration.pop("symbol")
                declaration["type_ref"] = declaration.pop("type")
            section["declarations"] = declarations
        document["sections"] = sections
        return document

    path = tmp_path / "profile-routed-source.json"
    source = renamed_source(_source([_symbol("health", "state")]))
    _write_source(path, source)
    kernel, candidate_ldb = deepcopy(load_authorities())
    language = candidate_ldb["language"]
    profile = language["resolution_profiles"][0]
    old_profile_id = profile["id"]
    profile["id"] = "renamed-exact-import-resolution-v1"
    profile_owner = next(
        package
        for package in language["packages"]
        if old_profile_id in package["profiles"]["resolution"]
    )
    profile_owner["profiles"]["resolution"] = [profile["id"]]
    profile["manifest_id_path"] = "header.model_key"
    profile["manifest_entry_module_path"] = "header.start_module"
    profile["requirements_member"] = "dependencies"
    profile["requirement_package_member"] = "package_id"
    profile["requirement_version_member"] = "release"
    profile["modules_member"] = "sections"
    profile["module_id_member"] = "module_key"
    profile["imports_member"] = "uses"
    profile["import_alias_member"] = "prefix"
    profile["import_package_member"] = "package_id"
    profile["import_version_member"] = "release"
    profile["import_symbol_member"] = "export_name"
    profile["symbols_member"] = "declarations"
    profile["symbol_name_member"] = "name"
    profile["symbol_type_member"] = "type_ref"
    profile["symbol_fact_member"] = "symbol"

    def rewrite_relation_term(term: dict[str, Any]) -> None:
        if term["root"] == "source":
            source_paths = {
                ("manifest", "id"): ["header", "model_key"],
                ("manifest", "entry_module"): ["header", "start_module"],
                ("package_requirements",): ["dependencies"],
                ("modules",): ["sections"],
            }
            term["path"] = source_paths.get(tuple(term["path"]), term["path"])
            return
        if term["root"] != "binding":
            return
        field_renames = {
            "requirement": {"id": "package_id", "version": "release"},
            "module": {
                "id": "module_key",
                "imports": "uses",
                "symbols": "declarations",
            },
            "import": {
                "alias": "prefix",
                "package": "package_id",
                "version": "release",
                "symbol": "export_name",
            },
            "symbol": {"symbol": "name", "type": "type_ref"},
        }
        renames = field_renames.get(term["binding"], {})
        term["path"] = [renames.get(segment, segment) for segment in term["path"]]

    for recipe in profile["relation_recipes"]:
        for binding in recipe["bindings"]:
            rewrite_relation_term(binding["source"])
        for predicate in recipe["predicates"]:
            rewrite_relation_term(predicate["left"])
            rewrite_relation_term(predicate["right"])
        for field in recipe["fields"]:
            rewrite_relation_term(field["term"])
    lowering = next(
        item
        for item in language["model_lowerings"]
        if item["id"] == profile["model_lowering"]
    )
    lowering["resolution_profile"] = profile["id"]
    lowering["source_selector"] = ["sections", "*", "declarations", "*"]
    selector_renames = {
        "modules": "sections",
        "symbols": "declarations",
        "symbol": "name",
    }
    for check in language["model_checks"]:
        check["selector"] = [
            selector_renames.get(item, item) for item in check["selector"]
        ]
        if "scope_selector" in check:
            check["scope_selector"] = [
                selector_renames.get(item, item) for item in check["scope_selector"]
            ]
    source_schema = next(
        item["schema"]
        for item in language["wire_schemas"]
        if item["artifact_kind"] == "model-source-package"
    )
    source_schema["properties"]["header"] = source_schema["properties"].pop("manifest")
    source_schema["required"] = [
        "header" if item == "manifest" else item for item in source_schema["required"]
    ]
    header_schema = source_schema["properties"]["header"]
    header_schema["properties"]["model_key"] = header_schema["properties"].pop("id")
    header_schema["properties"]["start_module"] = header_schema["properties"].pop(
        "entry_module"
    )
    header_schema["required"] = [
        {"id": "model_key", "entry_module": "start_module"}.get(item, item)
        for item in header_schema["required"]
    ]
    source_schema["properties"]["dependencies"] = source_schema["properties"].pop(
        "package_requirements"
    )
    source_schema["required"] = [
        "dependencies" if item == "package_requirements" else item
        for item in source_schema["required"]
    ]
    requirement_schema = source_schema["properties"]["dependencies"]["items"]
    requirement_schema["properties"]["package_id"] = requirement_schema[
        "properties"
    ].pop("id")
    requirement_schema["properties"]["release"] = requirement_schema["properties"].pop(
        "version"
    )
    requirement_schema["required"] = ["package_id", "release"]
    source_schema["properties"]["sections"] = source_schema["properties"].pop("modules")
    source_schema["required"] = [
        "sections" if item == "modules" else item for item in source_schema["required"]
    ]
    section_schema = source_schema["properties"]["sections"]["items"]
    section_schema["properties"]["module_key"] = section_schema["properties"].pop("id")
    section_schema["properties"]["uses"] = section_schema["properties"].pop("imports")
    section_schema["properties"]["declarations"] = section_schema["properties"].pop(
        "symbols"
    )
    section_schema["required"] = [
        {
            "id": "module_key",
            "imports": "uses",
            "symbols": "declarations",
        }.get(item, item)
        for item in section_schema["required"]
    ]
    use_schema = section_schema["properties"]["uses"]["items"]
    for old, new in (
        ("alias", "prefix"),
        ("package", "package_id"),
        ("version", "release"),
        ("symbol", "export_name"),
    ):
        use_schema["properties"][new] = use_schema["properties"].pop(old)
    use_schema["required"] = [
        {
            "alias": "prefix",
            "package": "package_id",
            "version": "release",
            "symbol": "export_name",
        }.get(item, item)
        for item in use_schema["required"]
    ]
    declaration_schema = section_schema["properties"]["declarations"]["items"]
    declaration_schema["properties"]["name"] = declaration_schema["properties"].pop(
        "symbol"
    )
    declaration_schema["properties"]["type_ref"] = declaration_schema["properties"].pop(
        "type"
    )
    declaration_schema["required"] = [
        {"symbol": "name", "type": "type_ref"}.get(item, item)
        for item in declaration_schema["required"]
    ]
    for vector in candidate_ldb["vectors"]:
        fixture = vector.get("source_fixture")
        if not isinstance(fixture, dict):
            continue
        fixture["source"] = renamed_source(fixture["source"])
        if fixture["mode"] == "indexed-repeat":
            fixture["collection_path"] = [
                selector_renames.get(item, item) for item in fixture["collection_path"]
            ]
            fixture["index_member"] = "name"
            fixture["template"]["name"] = fixture["template"].pop("symbol")
            fixture["template"]["type_ref"] = fixture["template"].pop("type")
        expect = vector["expect"]
        if expect["outcome"] == "admitted":
            assert expect["lock_oracle"]["resolution_profile"] == old_profile_id
            expect["lock_oracle"]["resolution_profile"] = profile["id"]
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )
    checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, candidate_ldb)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, CheckedModel)

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


def test_rir_output_member_follows_the_ldb_lowering_and_wire_schema(tmp_path):
    path = tmp_path / "renamed-rir-output.json"
    source = _source([_symbol("health", "state")])
    _write_source(path, source)
    kernel, candidate_ldb = deepcopy(load_authorities())
    language = candidate_ldb["language"]
    lowering = _reference_lowering(language)
    lowering["output_member"] = "items"
    rir_schema = next(
        item["schema"]
        for item in language["artifact_wire_schemas"]
        if item["artifact_kind"] == "rir-semantic-payload"
    )
    rir_schema["properties"]["items"] = rir_schema["properties"].pop("declarations")
    rir_schema["required"] = [
        "items" if item == "declarations" else item for item in rir_schema["required"]
    ]
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted
    profile = language["resolution_profiles"][0]
    checked = CheckedModel(
        source=source,
        source_identity=_reference_content_identity(
            profile["source_identity_domain"], source
        ),
        kernel=kernel,
        language_bundle=candidate_ldb,
    )

    production = lower_checked_model(checked)["rir-semantic-payload"]
    reference = _reference_rir(checked)

    assert production == reference
    assert "items" in production
    assert "declarations" not in production


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
    _, language_bundle = load_authorities()

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
    _write_source(path, _source([_symbol("health", "state")]))
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
        for invocation in lowering["rule_chain"]:
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
    candidate = CheckedModel(
        source=checked.source,
        source_identity=checked.source_identity,
        kernel=checked.kernel,
        language_bundle=candidate_ldb,
    )

    artifacts = lower_checked_model(candidate)
    production = artifacts["rir-semantic-payload"]
    reference = _reference_rir(candidate)

    assert production == reference
    selected_semantics = cast(dict[str, Any], production["selected_semantics"])
    operation_projections = cast(list[dict[str, Any]], selected_semantics["operations"])
    assert [row["definition"]["id"] for row in operation_projections] == [
        "quantity.identity"
    ]
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
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, candidate_ldb)

    assert isinstance(production, Schema2RefusalReport)
    assert isinstance(reference, tuple)
    assert (
        tuple(item.code for item in production.diagnostics)
        == reference
        == (new_diagnostic,)
    )


def test_independent_frontends_follow_a_renamed_resolution_reason_without_host_changes(
    tmp_path, monkeypatch
):
    path = tmp_path / "renamed-resolution-reason.json"
    source = _source([_symbol("health", "state")])
    source["package_requirements"][0]["version"] = "9.0.0"
    source["modules"][0]["imports"][0]["version"] = "9.0.0"
    _write_source(path, source)
    kernel, candidate_ldb, new_diagnostic = _renamed_reason_authorities(
        "model.reason.package-version-unavailable",
        "language.package_version_unavailable",
    )
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, candidate_ldb)

    assert isinstance(production, Schema2RefusalReport)
    assert isinstance(reference, tuple)
    assert (
        tuple(item.code for item in production.diagnostics)
        == reference
        == (new_diagnostic,)
    )


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
        monkeypatch.setattr(
            model_module, "load_authorities", lambda: (kernel, candidate_ldb)
        )
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
    profile = candidate_ldb["language"]["resolution_profiles"][0]
    checked = CheckedModel(
        source=source,
        source_identity=_reference_content_identity(
            profile["source_identity_domain"], source
        ),
        kernel=kernel,
        language_bundle=candidate_ldb,
    )
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
    semantic_artifacts["resolved-model"]["rir_identity"] = semantic_artifacts[
        "rir-semantic-payload"
    ]["content_identity"]
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
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    result = admit_resolved_model(semantic_artifacts)

    assert result.admitted is False
    assert result.diagnostics == (renamed,)
