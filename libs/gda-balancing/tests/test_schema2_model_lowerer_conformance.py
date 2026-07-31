"""Independent lowerer/consumer conformance for the #539 Model tracer."""

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import gda_balancing.schema2.model as model_module
import jsonschema
from gda_balancing.schema2.authority import (
    AdmittedAuthorityContext,
    admit_authority_context,
    load_authorities,
)
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


def _inject_authority_context(monkeypatch, kernel, language_bundle):
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext)
    monkeypatch.setattr(model_module, "packaged_authority_context", lambda: context)
    return context


class _ReferenceRuntimeProjectionExhausted(Exception):
    pass


class _ReferenceEntrypointError(ValueError):
    def __init__(self, pointer: str, message: str):
        super().__init__(message)
        self.pointer = pointer


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
            "version": "1.0.0",
            "entry_module": "main",
        },
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "entrypoints": [],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.1.0",
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
    vector_sets_by_coordinate = {
        (vector_set["package_id"], vector_set["package_version"]): vector_set
        for vector_set in language_bundle.package_conformance_vector_sets
    }
    projected_vectors = {vector["id"]: vector for vector in language_bundle["vectors"]}
    for package in language_bundle["language"]["packages"]:
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
        vector_set = vector_sets_by_coordinate[(package["id"], package["version"])]
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
        key=lambda member: (member[0]["id"], member[0]["version"]),
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
            "version": package["version"],
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
) -> tuple[tuple[str, str], ...] | CheckedModel:
    """Independently interpret the admitted source schema and model-check relation."""
    language = language_bundle["language"]
    source_schema = next(
        item["schema"]
        for item in language["wire_schemas"]
        if item["artifact_kind"] == "model-source-package"
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
    if schema_errors:
        path = tuple(str(part) for part in schema_errors[0].absolute_path)
        for check in language["model_checks"]:
            selector = tuple([*check.get("scope_selector", []), *check["selector"]])
            if len(selector) == len(path) and all(
                expected == "*" or expected == actual
                for expected, actual in zip(selector, path, strict=True)
            ):
                return (
                    (
                        reasons[check["reason"]]["diagnostic"],
                        _reference_pointer(list(path)),
                    ),
                )
        return (
            (
                reasons[profile["structural_reason"]]["diagnostic"],
                _reference_pointer(list(path)),
            ),
        )

    diagnostics_by_stage: dict[str, list[tuple[str, str]]] = {}
    for check in language["model_checks"]:
        reason = reasons[check["reason"]]
        scopes = (
            _reference_select_with_paths(source, check["scope_selector"])
            if "scope_selector" in check
            else [(source, ())]
        )
        for scope, scope_path in scopes:
            selected = _reference_select_with_paths(
                scope,
                check["selector"],
                scope_path,
            )
            values = [value for value, _path in selected]
            code = reason["diagnostic"]
            if check["mode"] == "each":
                diagnostics_by_stage.setdefault(reason["stage"], []).extend(
                    (code, _reference_pointer(list(path)))
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
                        (code, _reference_pointer(list(path)))
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
                    else tuple(check["selector"])
                )
            else:
                location = selected[0][1] if selected else tuple(check["selector"])
            diagnostics_by_stage.setdefault(reason["stage"], []).append(
                (code, _reference_pointer(list(location)))
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

    def read_term(
        term: dict[str, Any],
        environment: dict[str, tuple[Any, tuple[object, ...] | None]],
    ) -> tuple[Any, tuple[object, ...] | None]:
        if term["root"] == "source":
            value: Any = source
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
        for segment in term["path"]:
            value = value[segment]
            if pointer is not None:
                pointer = (*pointer, segment)
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
                        pointers[field["name"]] = _reference_pointer(list(pointer))
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
        if operator == "require-single-value":
            grouped: dict[
                tuple[str, ...],
                tuple[tuple[str, ...], dict[str, Any]],
            ] = {}
            failures = []
            for item in relations[law["relation"]]:
                consume()
                group = tuple(
                    item["values"][field] for field in [*law["scope"], *law["group"]]
                )
                value = tuple(item["values"][field] for field in law["value"])
                previous = grouped.get(group)
                if previous is None:
                    grouped[group] = (value, item)
                elif previous[0] != value:
                    failures.append((item, previous[1]))
            return failures
        raise AssertionError(
            f"reference consumer observed unknown resolution law: {operator}"
        )

    resolution_meta = kernel["meta_format"]["resolution_judgment"]
    operations = {item["id"]: item for item in resolution_meta["operations"]}

    def resolution_pointer(code: str) -> str:
        if code == "language.package_version_unavailable":
            for index, requirement in enumerate(source[requirements_member]):
                coordinate = (
                    requirement[requirement_package_member],
                    requirement[requirement_version_member],
                )
                if coordinate not in packages_by_coordinate:
                    return _reference_pointer(
                        [requirements_member, index, requirement_version_member]
                    )
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
        return ((runtime_reasons[0]["diagnostic"], ""),)
    except _ReferenceEntrypointError as error:
        return (
            (
                reasons[profile["structural_reason"]]["diagnostic"],
                error.pointer,
            ),
        )
    except _ReferenceFormulaError as error:
        return ((reasons[error.reason_id]["diagnostic"], error.pointer),)
    except (KeyError, ValueError) as error:
        pointer = (
            "/formula_bindings"
            if "formula" in str(error).lower() or "binding" in str(error).lower()
            else "/entrypoints"
        )
        return ((reasons[profile["structural_reason"]]["diagnostic"], pointer),)
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
            "version": imported["version"],
            "symbol": imported["symbol"],
        }
    }


def _reference_formula_contract_matches_operation(
    formula_contract: dict[str, Any],
    operation_contract: dict[str, Any],
) -> bool:
    formula_type = formula_contract["type_identity"]
    operation_type = operation_contract["type"]
    return formula_type == {
        "package": operation_type["package"],
        "version": operation_type["version"],
        "symbol": operation_type["id"],
    } and all(
        formula_contract[member] == operation_contract[member]
        for member in ("representation", "kind", "unit", "numeric_policy")
    )


def _reference_selected_operation_coordinates(
    checked: CheckedModel,
    lock: dict[str, Any],
) -> set[tuple[str, str, str]]:
    package_versions = {row["id"]: row["version"] for row in lock["packages"]}
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
            row["definition"]["id"],
        ): row["definition"]
        for row in lock["operations"]
    }
    selected = {
        (
            entrypoint["operation"]["package"],
            entrypoint["operation"]["version"],
            entrypoint["operation"]["id"],
        )
        for entrypoint in checked.source.get("entrypoints", [])
    }
    if any(coordinate not in operations for coordinate in selected):
        return set(operations)
    pending = list(selected)
    while pending:
        operation = operations.get(pending.pop())
        if operation is None:
            continue
        for instruction in operation.get("body", []):
            if instruction.get("node") != "invoke":
                continue
            dependency = (
                instruction["operation"]["package"],
                instruction["operation"]["version"],
                instruction["operation"]["id"],
            )
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return selected


def _reference_formulas_and_bindings(
    checked: CheckedModel,
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
    policy = profile["extensions"]["standard.formula"]
    domains = policy["identity_domains"]
    formula_profiles = [
        runtime["extensions"]["standard.formula"]["contexts"]
        for runtime in language["runtime_profiles"]
        if "standard.formula" in runtime.get("extensions", {})
    ]
    assert len(formula_profiles) == 1
    formula_contexts = {
        context["phase"]: {
            "phase": context["phase"],
            "frame": context["frame"],
        }
        for context in formula_profiles[0]
    }
    assert set(formula_contexts) == {"initialization", "event", "observation"}
    actual_operand_domain = checked.kernel["meta_format"]["runtime_program"][
        "invocation_contract"
    ]["identity_domains"]["actual_operand"]
    declarations_by_source = {
        (
            declaration["resolved_symbol"]["module"],
            declaration["resolved_symbol"]["name"],
        ): declaration
        for declaration in declarations
    }
    prototypes: dict[tuple[str, str], dict[str, Any]] = {}
    dependencies: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for module in checked.source[profile["modules_member"]]:
        module_id = module[profile["module_id_member"]]
        imports = {
            item[profile["import_alias_member"]]: {
                "package": item[profile["import_package_member"]],
                "version": item[profile["import_version_member"]],
                "symbol": item[profile["import_symbol_member"]],
            }
            for item in module[profile["imports_member"]]
        }
        for source_formula in module.get("formulas", []):
            key = (module_id, source_formula["id"])
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
                "source_body": source_formula["body"],
            }
            dependencies[key] = [
                (node["formula"]["module"], node["formula"]["id"])
                for node in source_formula["body"]["nodes"]
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

    package_versions = {row["id"]: row["version"] for row in lock["packages"]}
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
            row["definition"]["id"],
        ): row["definition"]
        for row in lock["operations"]
    }

    def operation_identity(coordinate: tuple[str, str, str]) -> str:
        return _reference_content_identity(
            domains["operation"],
            {
                "package": coordinate[0],
                "version": coordinate[1],
                "id": coordinate[2],
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
                    source_node["operation"]["version"],
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
                            if item["minimum"]
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
                        "version": coordinate[1],
                        "id": coordinate[2],
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
            "identity": _reference_content_identity(
                domains["declaration"],
                formula_body,
            ),
        }

    source_bindings = checked.source.get("formula_bindings", [])
    selected_keys = {
        (binding["formula"]["module"], binding["formula"]["id"])
        for binding in source_bindings
    }
    binding_pointers = {
        (binding["formula"]["module"], binding["formula"]["id"]): (
            f"/formula_bindings/{index}/formula"
        )
        for index, binding in enumerate(source_bindings)
    }
    pending = list(selected_keys)
    while pending:
        key = pending.pop()
        if key not in resolved:
            raise _ReferenceFormulaError(
                "model.reason.formula-binding-missing",
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
    )
    for row in lock["operations"]:
        coordinate = (
            row["package"],
            package_versions[row["package"]],
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
    bound_slots: set[tuple[str, str, str, str]] = set()
    for binding_index, source_binding in enumerate(source_bindings):
        formula_key = (
            source_binding["formula"]["module"],
            source_binding["formula"]["id"],
        )
        if formula_key not in resolved:
            raise _ReferenceFormulaError(
                "model.reason.formula-binding-missing",
                f"/formula_bindings/{binding_index}/formula",
                "Formula binding names no declaration",
            )
        formula = resolved[formula_key]
        if source_binding["site"]["kind"] == "operation-slot":
            source_operation = source_binding["site"]["operation"]
            key = (
                source_operation["package"],
                source_operation["version"],
                source_operation["id"],
                source_binding["site"]["slot"],
            )
            if key not in slots or key in bound_slots:
                raise _ReferenceFormulaError(
                    (
                        "model.reason.formula-binding-duplicate"
                        if key in bound_slots
                        else "model.reason.formula-unreachable"
                    ),
                    f"/formula_bindings/{binding_index}/site",
                    "Formula binding site is not one unique selected Operation slot",
                )
            slot, operation_identity_value = slots[key]
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
                        "version": key[1],
                        "id": key[2],
                        "identity": operation_identity_value,
                    },
                    "slot": key[3],
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
                for phase in ("initialization", "observation")
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
            "model.reason.formula-binding-missing",
            "/entrypoints/0/operation",
            "every selected Operation Formula slot requires exactly one binding",
        )
    return formulas, bindings


def _reference_specialize_formula_slots(
    selected_semantics: dict[str, Any],
    formulas: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    specialized = deepcopy(selected_semantics)
    package_versions = {row["id"]: row["version"] for row in specialized["packages"]}
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
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
                called = operations[
                    (
                        operation_ref["package"],
                        operation_ref["version"],
                        operation_ref["id"],
                    )
                ]
                child_values = {
                    argument["port"]: runtime_operand(
                        argument["operand"],
                        parameter_sources,
                        local_sources,
                        snapshot_sources,
                    )
                    for argument in node["arguments"]
                }
                result_source = called["result"]["source"]
                result_name = result_source.get("name")
                for index, child in enumerate(called["body"]):
                    child_target = (
                        target
                        if child.get("target") == result_name
                        else f"{prefix}.{node_id}.{index}"
                    )
                    if child["node"] == "constant":
                        compiled = {
                            "node": "constant",
                            "target": child_target,
                            "literal": child["literal"],
                        }
                    elif child["node"] == "copy":
                        compiled = {
                            "node": "copy",
                            "target": child_target,
                            "value": reference(child_values[child["value"]]),
                        }
                    elif child["node"] in {
                        "add",
                        "maximum",
                        "multiply",
                        "subtract",
                    }:
                        compiled = {
                            "node": child["node"],
                            "target": child_target,
                            "left": reference(child_values[child["left"]]),
                            "right": reference(child_values[child["right"]]),
                        }
                    else:
                        assert child["node"] == "if"
                        compiled = {
                            "node": "if",
                            "target": child_target,
                            "condition": reference(child_values[child["condition"]]),
                            "when_true": reference(child_values[child["when_true"]]),
                            "when_false": reference(child_values[child["when_false"]]),
                        }
                    instructions.append(compiled)
                    child_values[child["target"]] = {
                        "kind": "local",
                        "local": child_target,
                    }
                called_result = child_values[result_name]
                if called_result != {"kind": "local", "local": target}:
                    instructions.append(
                        {
                            "node": "copy",
                            "target": target,
                            "value": reference(called_result),
                        }
                    )
                instructions.append({"node": "copy", "target": target, "value": target})
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
        tuple[str, str, str],
        list[tuple[int, int, list[dict[str, Any]], str]],
    ] = {}
    snapshot_sources_by_operation: dict[
        tuple[str, str, str],
        dict[str, dict[str, Any]],
    ] = {}
    for binding in bindings:
        site = binding["site"]
        if site["kind"] != "operation-slot":
            continue
        operation_ref = site["operation"]
        coordinate = (
            operation_ref["package"],
            operation_ref["version"],
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
    checked: CheckedModel,
) -> list[dict[str, Any]]:
    """Independently compile derived bindings to generic value programs."""
    package_versions = {
        row["id"]: row["version"] for row in selected_semantics["packages"]
    }
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
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
    domains = profile["extensions"]["standard.formula"]["identity_domains"]
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
                    operation = operations[
                        (
                            operation_ref["package"],
                            operation_ref["version"],
                            operation_ref["id"],
                        )
                    ]
                    values = {
                        argument["port"]: source(
                            argument["operand"], parameters, locals_, prefix
                        )
                        for argument in node["arguments"]
                    }
                    for index, instruction in enumerate(operation["body"]):
                        child_target = f"{target}.{index}"

                        def child_reference(member: str) -> str:
                            return reference(values[instruction[member]])

                        child_node = instruction["node"]
                        if child_node == "constant":
                            compiled = {
                                "node": child_node,
                                "target": child_target,
                                "literal": instruction["literal"],
                            }
                        elif child_node == "copy":
                            compiled = {
                                "node": child_node,
                                "target": child_target,
                                "value": child_reference("value"),
                            }
                        elif child_node in {
                            "add",
                            "maximum",
                            "multiply",
                            "subtract",
                        }:
                            compiled = {
                                "node": child_node,
                                "target": child_target,
                                "left": child_reference("left"),
                                "right": child_reference("right"),
                            }
                        else:
                            assert child_node == "if"
                            compiled = {
                                "node": child_node,
                                "target": child_target,
                                "condition": child_reference("condition"),
                                "when_true": child_reference("when_true"),
                                "when_false": child_reference("when_false"),
                            }
                        emit(compiled, site_identity)
                        values[instruction["target"]] = {
                            "kind": "local",
                            "name": child_target,
                        }
                    result = operation["result"]["source"]
                    assert result["kind"] in {"local", "port"}
                    emit(
                        {
                            "node": "copy",
                            "target": target,
                            "value": reference(values[result["name"]]),
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
        assert len(body) == max_steps
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
    formulas, formula_bindings = _reference_formulas_and_bindings(
        checked,
        declarations,
        lock,
    )
    selected_semantics = _reference_runtime_projection(
        checked, lock, declarations, lowering
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
    )
    return _reference_artifact(
        checked,
        "rir-semantic-payload",
        {
            lowering["output_member"]: declarations,
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
                lowering,
            ),
            "selected_semantics": selected_semantics,
        },
    )


def _reference_exact_operation(
    operation_row: dict[str, Any],
    package_versions: dict[str, str],
) -> dict[str, str]:
    package = operation_row["package"]
    return {
        "package": package,
        "version": package_versions[package],
        "id": operation_row["definition"]["id"],
    }


def _reference_value_contract_matches(
    declaration: dict[str, Any],
    contract: dict[str, Any],
) -> bool:
    expected_type = contract["type"]
    return declaration["type_identity"] == {
        "package": expected_type["package"],
        "version": expected_type["version"],
        "symbol": expected_type["id"],
    } and all(
        declaration[member] == contract[member]
        for member in ("representation", "kind", "unit", "numeric_policy")
    )


def _reference_literal_context(
    value: Any,
    formal: dict[str, Any],
    checked: CheckedModel,
    selected_semantics: dict[str, Any],
) -> dict[str, Any] | None:
    if (
        type(value) is not int
        or checked.kernel["meta_format"]["literal_typing"]["selection"]
        != "unique-formal-match"
    ):
        return None
    profiles = [
        row["definition"] for row in selected_semantics["literal_typing_profiles"]
    ]
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
    checked: CheckedModel,
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
    package_versions = {
        row["id"]: row["version"] for row in selected_semantics["packages"]
    }
    operation_rows = selected_semantics["operations"]
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
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
    assert policy["duplicate_actual_policy"] == "collapse"
    assert policy["scenario_target_cardinality"] == "one-per-resolved-actual"
    resolved_entrypoints = []
    seen: set[str] = set()
    for entrypoint_index, source_entrypoint in enumerate(checked.source["entrypoints"]):
        pointer = f"/entrypoints/{entrypoint_index}"
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
                operation_ref["version"],
                operation_ref["id"],
            )
        )
        if operation_row is None:
            selected_version = package_versions.get(operation_ref["package"])
            member = (
                "package"
                if selected_version is None
                else "version"
                if selected_version != operation_ref["version"]
                else "id"
            )
            raise _ReferenceEntrypointError(
                f"{pointer}/operation/{member}",
                "entrypoint Operation is not selected",
            )
        operation = operation_row["definition"]
        exact_operation = _reference_exact_operation(operation_row, package_versions)
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
    checked: CheckedModel,
    selected_semantics: dict[str, Any],
    lowering: dict[str, Any],
) -> list[dict[str, Any]]:
    composition_policy = lowering["composition_policy"]
    effect_policy = composition_policy["effects"]
    refusal_policy = composition_policy["refusals"]
    resource_policy = composition_policy["resources"]
    package_versions = {
        row["id"]: row["version"] for row in selected_semantics["packages"]
    }
    operation_rows = selected_semantics["operations"]
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
            row["definition"]["id"],
        ): row
        for row in operation_rows
    }
    domains = checked.kernel["meta_format"]["runtime_program"]["invocation_contract"][
        "identity_domains"
    ]
    rows = []
    cache: dict[tuple[str, str, str], tuple[set[str], set[str], int]] = {}

    def close(
        operation_row: dict[str, Any],
        stack: tuple[tuple[str, str, str], ...],
    ) -> tuple[set[str], set[str], int]:
        parent_ref = _reference_exact_operation(operation_row, package_versions)
        parent_key = (
            parent_ref["package"],
            parent_ref["version"],
            parent_ref["id"],
        )
        if parent_key in stack:
            raise ValueError("Operation call graph contains a cycle")
        if parent_key in cache:
            return cache[parent_key]
        operation = operation_row["definition"]
        parent_ports = {row["id"]: row for row in operation["inputs"]}
        parent_outcomes = {row["id"] for row in operation.get("outcomes", [])}
        local_contracts: dict[str, dict[str, Any]] = {}
        effects = set(operation["effects"])
        refusals = set(operation["refusals"])
        charge = 0
        seen_sites: set[str] = set()
        for order, instruction in enumerate(operation["body"]):
            charge += 1
            if instruction["node"] != "invoke":
                continue
            site = instruction["site"]
            if site in seen_sites:
                raise ValueError("duplicate nested call site")
            seen_sites.add(site)
            child_ref = instruction["operation"]
            child_row = operations.get(
                (
                    child_ref["package"],
                    child_ref["version"],
                    child_ref["id"],
                )
            )
            if child_row is None:
                raise ValueError("nested Operation is not selected")
            child = child_row["definition"]
            exact_child = _reference_exact_operation(child_row, package_versions)
            child_ports = child["inputs"]
            authored_arguments = instruction["arguments"]
            if [row["port"] for row in authored_arguments] != [
                row["id"] for row in child_ports
            ]:
                raise ValueError("nested arguments do not close formal ports")
            aliases: dict[str, list[tuple[str, str]]] = {}
            arguments = []
            for formal, authored in zip(child_ports, authored_arguments, strict=True):
                formal_body = {"operation": exact_child, "name": formal["id"]}
                operand = authored["operand"]
                if operand["kind"] == "port":
                    contract = parent_ports.get(operand["port"])
                    if (
                        contract is None
                        or not _reference_operation_contract_matches(contract, formal)
                        or (
                            formal["access"] in {"read-write", "write"}
                            and contract["access"] not in {"read-write", "write"}
                        )
                    ):
                        raise ValueError("nested port operand is incompatible")
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
                    contract = local_contracts.get(operand["local"])
                    if (
                        contract is None
                        or formal["access"] != "read"
                        or not _reference_operation_contract_matches(contract, formal)
                    ):
                        raise ValueError("nested local operand is incompatible")
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
            if authored_result["kind"] == "discard":
                if child["result"]["discardable"] is not True:
                    raise ValueError("required nested result is discarded")
            elif authored_result["kind"] == "local":
                name = authored_result["name"]
                if name in local_contracts:
                    raise ValueError("nested result local is repeated")
                local_contracts[name] = child["result"]
            elif authored_result["kind"] == "operation-result":
                if not _reference_operation_contract_matches(
                    child["result"], operation["result"]
                ):
                    raise ValueError("nested result is incompatible")
            else:
                raise ValueError("unknown nested result binding")
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
            if [row["outcome"] for row in authored_outcomes] != [
                row["id"] for row in child["outcomes"]
            ]:
                raise ValueError("nested outcome mapping is not exhaustive")
            outcomes = []
            for mapping in authored_outcomes:
                action = mapping["action"]
                if (
                    action["kind"] == "propagate"
                    and action["outcome"] not in parent_outcomes
                ):
                    raise ValueError("nested outcome is not admitted by caller")
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
            child_effects, child_refusals, child_charge = close(
                child_row, (*stack, parent_key)
            )
            if effect_policy["containment"] == (
                "callee-subset-of-caller-declaration"
            ) and not child_effects <= set(operation["effects"]):
                raise ValueError("nested effect closure exceeds caller declaration")
            if refusal_policy["containment"] == (
                "callee-subset-of-caller-declaration"
            ) and not child_refusals <= set(operation["refusals"]):
                raise ValueError("nested refusal closure exceeds caller declaration")
            if effect_policy["aggregation"] == "union":
                effects.update(child_effects)
            if refusal_policy["aggregation"] == "union":
                refusals.update(child_refusals)
            if resource_policy["aggregation"] == "sum":
                charge += child_charge
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
        if (
            resource_policy["containment"] == "transitive-charge-within-caller-bound"
            and charge > operation["resource_bounds"]["max_steps"]
        ):
            raise ValueError("transitive resource charge exceeds caller bound")
        cache[parent_key] = effects, refusals, charge
        return effects, refusals, charge

    for operation_row in sorted(
        operation_rows,
        key=lambda row: (row["package"], row["definition"]["id"]),
    ):
        close(operation_row, ())
    return sorted(
        rows,
        key=lambda row: (
            row["parent_operation"]["package"],
            row["parent_operation"]["id"],
            row["order"],
        ),
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
    formula_pointers = {
        (module[module_id_member], formula["id"]): [
            modules_member,
            module_index,
            "formulas",
            formula_index,
        ]
        for module_index, module in enumerate(checked.source[modules_member])
        for formula_index, formula in enumerate(module.get("formulas", []))
    }
    declaration_entries = [
        {
            "rir_pointer": _reference_pointer([lowering["output_member"], index]),
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
    ]
    formula_entries = [
        {
            "rir_pointer": _reference_pointer(["formulas", index]),
            "source_pointer": _reference_pointer(
                formula_pointers[(formula["module"], formula["id"])]
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
        "game.combat.model-binding.contract-stale-version",
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
    owner_coordinates = {
        (owners[0]["package_id"], owners[0]["package_version"])
        for owners in vector_owners.values()
    }
    packages = [
        package
        for package in language_bundle["language"]["packages"]
        if (package["id"], package["version"]) in owner_coordinates
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
            assert isinstance(production_checked, Schema2RefusalReport), vector["id"]
            assert isinstance(reference_checked, tuple), vector["id"]
            production_diagnostics = [
                {
                    "code": item.code,
                    "stage": production_checked.stage,
                    "pointer": item.primary.pointer,
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
        "id": "quantity.dimensionless-int64",
        "kind": "scalar",
        "numeric_policy": "exact-int64",
        "representation": "Int",
        "type": {
            "id": "Quantity",
            "package": "core.quantity",
            "version": "2.1.0",
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


def test_independent_lowerers_close_the_rpg_entrypoint_and_nested_call_graph():
    path = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    source = cast(
        dict[str, Any],
        json.loads(path.read_text(encoding="utf-8")),
    )
    kernel, language_bundle = load_authorities()
    checked = check_model_source(str(path))
    reference_checked = _reference_check_source(source, kernel, language_bundle)
    assert isinstance(checked, CheckedModel)
    assert isinstance(reference_checked, CheckedModel)

    production = lower_checked_model(checked)
    reference = _reference_semantic_artifacts(reference_checked)

    assert production["rir-semantic-payload"] == reference["rir-semantic-payload"]
    rir = reference["rir-semantic-payload"]
    assert len(cast(list[Any], rir["entrypoints"])) == 1
    assert len(cast(list[Any], rir["call_sites"])) == 4
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
    kernel, candidate_ldb = deepcopy(load_authorities())
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
            "id": "quantity.dimensionless-int64",
            "kind": "scalar",
            "numeric_policy": "exact-int64",
            "representation": "Int",
            "type": {
                "id": "Quantity",
                "package": "core.quantity",
                "version": "2.1.0",
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
        ("language.name_ambiguity", "/modules/0/imports/1/alias"),
        ("language.unresolved_name", "/modules/0/symbols/0/type"),
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
    assert reference == (("language.resource_exhausted", ""),)


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
    _inject_authority_context(monkeypatch, kernel, language_bundle)

    production = check_model_source(str(path))
    reference = _reference_check_source(source, kernel, language_bundle)

    assert isinstance(production, Schema2RefusalReport)
    assert tuple(item.code for item in production.diagnostics) == (
        "language.resource_exhausted",
    )
    assert reference == (("language.resource_exhausted", ""),)


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
    assert reference == (("language.name_ambiguity", "/modules/0/imports/1/alias"),)


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
        if (
            vector.get("kind") == "package-contract"
            and vector.get("probe") == {"path": "profiles.resolution"}
            and vector.get("expect") == [old_profile_id]
        ):
            vector["expect"] = [profile["id"]]
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
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)
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
        "quantity.floor-zero",
        "quantity.identity",
        "quantity.maximum",
        "quantity.subtract",
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
    source["package_requirements"][0]["version"] = "9.0.0"
    source["modules"][0]["imports"][0]["version"] = "9.0.0"
    _write_source(path, source)
    kernel, candidate_ldb, new_diagnostic = _renamed_reason_authorities(
        "model.reason.package-version-unavailable",
        "language.package_version_unavailable",
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
    assert reference == ((new_diagnostic, "/package_requirements/0/version"),)


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
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    result = admit_resolved_model(semantic_artifacts)

    assert result.admitted is False
    assert result.diagnostics == (renamed,)
