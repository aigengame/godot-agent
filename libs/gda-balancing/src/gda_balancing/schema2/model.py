"""Authority-driven Model Source checking and lowering for Schema 2.0."""

import fcntl
import hashlib
import hmac
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, cast

import jsonschema

from gda_balancing.envelope import UnreadableInputError, UsageError
from gda_balancing.descriptors import ArtifactSetMemberSpec
from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.bootstrap import BOOTSTRAP_REFUSAL_CATALOG, admit_authorities
from gda_balancing.schema2.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bootstrap_refusal,
)

_RESOLVER_IMPLEMENTATION_IDENTITY = "gda-balancing.python-exact-resolver-v1"
_LOWERER_IMPLEMENTATION_IDENTITY = "gda-balancing.python-lowerer-v1"
_STORE_DIRECTORY_ENV = "GDA_BALANCING_STORE_DIR"
_ANCHOR_KEY_ENV = "GDA_BALANCING_ANCHOR_KEY"


def _normalized_absolute_path(value: str) -> Path:
    path = Path(os.path.abspath(os.path.expanduser(value)))
    for alias in (Path("/tmp"), Path("/var")):
        if not alias.is_symlink():
            continue
        try:
            relative = path.relative_to(alias)
        except ValueError:
            continue
        return Path(os.path.realpath(alias)) / relative
    return path


def _model_refusal_catalog() -> tuple[tuple[str, str], ...]:
    """Project the post-admission catalog from the LDB; do not mirror it in host code."""
    _, language_bundle = load_authorities()
    return BOOTSTRAP_REFUSAL_CATALOG + tuple(
        (cast(str, item["code"]), cast(str, item["stage"]))
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
    )


MODEL_REFUSAL_CATALOG = _model_refusal_catalog()


@dataclass(frozen=True)
class CheckedModel:
    source: dict[str, Any]
    source_identity: str
    kernel: dict[str, Any]
    language_bundle: dict[str, Any]


@dataclass(frozen=True)
class ResolvedModelAdmission:
    admitted: bool
    diagnostics: tuple[str, ...]


def _strict_object(data: bytes) -> dict[str, Any]:
    def reject_number(_value: str) -> Any:
        raise ValueError("non-integer number")

    def closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate object key: {key}")
            value[key] = item
        return value

    value = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=closed_object,
        parse_float=reject_number,
        parse_constant=reject_number,
    )
    if not isinstance(value, dict):
        raise ValueError("Model Source Package must be an object")
    canonical_bytes(cast(JsonValue, value))
    return value


def _location(identity: str, pointer: str) -> ArtifactLocation:
    return ArtifactLocation(content_identity=identity, pointer=pointer)


def _refusal(
    code: str,
    identity: str,
    pointer: str,
    message: str,
    language_bundle: dict[str, Any],
) -> Schema2RefusalReport:
    catalog = BOOTSTRAP_REFUSAL_CATALOG + tuple(
        (cast(str, item["code"]), cast(str, item["stage"]))
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
    )
    stage = dict(catalog)[code]
    return Schema2RefusalReport(
        stage=cast(Any, stage),
        diagnostics=(
            Schema2Diagnostic(
                code=code,
                message=message,
                primary=_location(identity, pointer),
            ),
        ),
        truncated=False,
    )


def _bounded_refusal(
    diagnostics: Iterable[Schema2Diagnostic],
    language_bundle: dict[str, Any],
) -> Schema2RefusalReport | None:
    catalog = BOOTSTRAP_REFUSAL_CATALOG + tuple(
        (cast(str, item["code"]), cast(str, item["stage"]))
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
    )
    stages = dict(catalog)
    unique: dict[
        tuple[str, ArtifactLocation, tuple[ArtifactLocation, ...]], Schema2Diagnostic
    ] = {}
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.primary, diagnostic.related)
        unique.setdefault(key, diagnostic)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            item.primary.pointer,
            item.code,
            item.primary.content_identity,
            tuple(
                (related.pointer, related.content_identity) for related in item.related
            ),
        ),
    )
    if not ordered:
        return None
    stage = stages[ordered[0].code]
    if any(stages[item.code] != stage for item in ordered):
        raise ValueError("one refusal report cannot cross refusal stages")
    limit = cast(int, language_bundle["resources"]["max_diagnostics"])
    return Schema2RefusalReport(
        stage=cast(Any, stage),
        diagnostics=tuple(ordered[:limit]),
        truncated=len(ordered) > limit,
    )


def _pointer(parts: Iterable[object]) -> str:
    return "".join(
        "/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts
    )


def _language(language_bundle: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], language_bundle["language"])


def _resolution_profile(
    language_bundle: dict[str, Any],
    profile_id: str | None = None,
) -> dict[str, Any]:
    profiles = cast(
        list[dict[str, Any]], _language(language_bundle)["resolution_profiles"]
    )
    matches = [
        profile
        for profile in profiles
        if (
            profile.get("id") == profile_id
            if profile_id is not None
            else profile.get("default") is True
        )
    ]
    if len(matches) != 1:
        raise ValueError("the admitted tracer requires one selected resolution profile")
    return matches[0]


def _model_lowering(
    language_bundle: dict[str, Any],
    profile_id: str | None = None,
) -> dict[str, Any]:
    profile = _resolution_profile(language_bundle, profile_id)
    lowerings = cast(
        list[dict[str, Any]], _language(language_bundle)["model_lowerings"]
    )
    matches = [
        lowering
        for lowering in lowerings
        if lowering.get("id") == profile["model_lowering"]
        and lowering.get("resolution_profile") == profile["id"]
    ]
    if len(matches) != 1:
        raise ValueError(
            "the admitted resolution profile requires one selected model lowering"
        )
    return matches[0]


def _path_value(root: Any, dotted: str) -> Any:
    value = root
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value


def _selected_values(
    root: Any, selector: list[str], parts: tuple[object, ...] = ()
) -> list[tuple[Any, tuple[object, ...]]]:
    if not selector:
        return [(root, parts)]
    head, *tail = selector
    if head == "*":
        if not isinstance(root, list):
            return []
        return [
            selected
            for index, item in enumerate(root)
            for selected in _selected_values(item, tail, (*parts, index))
        ]
    if not isinstance(root, dict) or head not in root:
        return []
    return _selected_values(root[head], tail, (*parts, head))


def _inventory_values(language_bundle: dict[str, Any], dotted: str) -> list[Any]:
    values: list[Any] = [language_bundle]
    for part in dotted.split("."):
        expanded: list[Any] = []
        for value in values:
            if isinstance(value, dict) and part in value:
                child = value[part]
                expanded.extend(child if isinstance(child, list) else [child])
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and part in item:
                        child = item[part]
                        expanded.extend(child if isinstance(child, list) else [child])
        values = expanded
    return values


def _reason_matches(
    reason: dict[str, Any], values: list[Any], language_bundle: dict[str, Any]
) -> bool:
    predicate = cast(dict[str, Any], reason["predicate"])
    operation = predicate["operation"]
    if operation == "not-member":
        inventory = _inventory_values(
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
        encoded = [canonical_bytes(cast(JsonValue, value)) for value in values]
        return len(encoded) != len(set(encoded))
    if operation == "greater-than":
        limit = _path_value(language_bundle, cast(str, predicate["limit_path"]))
        return len(values) > limit
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
    raise ValueError(f"unknown admitted reason operation: {operation}")


def _unique_reason(
    language_bundle: dict[str, Any],
    *,
    stage: str,
    operation: str,
    limit_path: str | None = None,
) -> dict[str, Any]:
    matches = []
    for reason in cast(list[dict[str, Any]], _language(language_bundle)["reasons"]):
        predicate = cast(dict[str, Any], reason["predicate"])
        if reason["stage"] != stage or predicate["operation"] != operation:
            continue
        if limit_path is not None and predicate.get("limit_path") != limit_path:
            continue
        matches.append(reason)
    if len(matches) != 1:
        raise ValueError(
            "the admitted Model Source boundary requires one matching diagnostic reason"
        )
    return matches[0]


def _reason_by_id(language_bundle: dict[str, Any], reason_id: str) -> dict[str, Any]:
    matches = [
        reason
        for reason in cast(list[dict[str, Any]], _language(language_bundle)["reasons"])
        if reason["id"] == reason_id
    ]
    if len(matches) != 1:
        raise ValueError(f"admitted reason is not unique: {reason_id}")
    return matches[0]


def _model_check_diagnostics(
    source: dict[str, Any],
    source_identity: str,
    language_bundle: dict[str, Any],
) -> list[Schema2Diagnostic]:
    language = _language(language_bundle)
    reasons = {
        item["id"]: item for item in cast(list[dict[str, Any]], language["reasons"])
    }
    diagnostics: list[Schema2Diagnostic] = []
    for check in cast(list[dict[str, Any]], language["model_checks"]):
        reason = reasons[check["reason"]]
        scopes = (
            _selected_values(
                source,
                cast(list[str], check["scope_selector"]),
            )
            if "scope_selector" in check
            else [(source, ())]
        )
        for scope, scope_path in scopes:
            selected = _selected_values(
                scope,
                cast(list[str], check["selector"]),
                scope_path,
            )
            values = [value for value, _ in selected]
            diagnostic_code = cast(str, reason["diagnostic"])
            message = f"Model Source failed admitted check {check['id']}"
            mode = check["mode"]
            if mode == "each":
                diagnostics.extend(
                    Schema2Diagnostic(
                        code=diagnostic_code,
                        message=message,
                        primary=_location(source_identity, _pointer(path)),
                    )
                    for value, path in selected
                    if _reason_matches(reason, [value], language_bundle)
                )
                continue
            if not _reason_matches(reason, values, language_bundle):
                continue
            operation = reason["predicate"]["operation"]
            if mode == "all" and operation == "has-duplicate":
                first_paths: dict[bytes, tuple[object, ...]] = {}
                for value, path in selected:
                    encoded = canonical_bytes(cast(JsonValue, value))
                    if encoded not in first_paths:
                        first_paths[encoded] = path
                        continue
                    diagnostics.append(
                        Schema2Diagnostic(
                            code=diagnostic_code,
                            message=message,
                            primary=_location(source_identity, _pointer(path)),
                            related=(
                                _location(
                                    source_identity,
                                    _pointer(first_paths[encoded]),
                                ),
                            ),
                        )
                    )
                continue
            if mode == "count":
                limit_path = cast(str, reason["predicate"]["limit_path"])
                limit = cast(int, _path_value(language_bundle, limit_path))
                location = (
                    selected[limit][1]
                    if len(selected) > limit
                    else tuple(check["selector"])
                )
            else:
                location = selected[0][1] if selected else tuple(check["selector"])
            diagnostics.append(
                Schema2Diagnostic(
                    code=diagnostic_code,
                    message=message,
                    primary=_location(source_identity, _pointer(location)),
                )
            )
    return diagnostics


def _schema_error_code(
    error: jsonschema.ValidationError, language_bundle: dict[str, Any]
) -> str:
    if error.validator in {
        "additionalProperties",
        "required",
        "type",
        "unevaluatedProperties",
    }:
        profile = _resolution_profile(language_bundle)
        return cast(
            str,
            _reason_by_id(
                language_bundle,
                cast(str, profile["structural_reason"]),
            )["diagnostic"],
        )
    path = tuple(str(part) for part in error.absolute_path)
    language = _language(language_bundle)
    reasons = {
        item["id"]: item for item in cast(list[dict[str, Any]], language["reasons"])
    }
    for check in cast(list[dict[str, Any]], language["model_checks"]):
        selector = tuple(
            [
                *cast(list[str], check.get("scope_selector", [])),
                *cast(list[str], check["selector"]),
            ]
        )
        if len(selector) == len(path) and all(
            expected == "*" or expected == actual
            for expected, actual in zip(selector, path, strict=True)
        ):
            return cast(str, reasons[check["reason"]]["diagnostic"])
    return cast(
        str,
        _reason_by_id(
            language_bundle,
            cast(str, _resolution_profile(language_bundle)["structural_reason"]),
        )["diagnostic"],
    )


def _schema_error_diagnostics(
    error: jsonschema.ValidationError,
    source_identity: str,
    language_bundle: dict[str, Any],
) -> list[Schema2Diagnostic]:
    code = _schema_error_code(error, language_bundle)
    base = tuple(error.absolute_path)
    pointers: list[tuple[object, ...]] = []
    if error.validator == "required" and isinstance(error.instance, dict):
        required = error.validator_value
        if isinstance(required, list):
            pointers = [
                (*base, member)
                for member in sorted(set(required) - set(error.instance))
            ]
    elif error.validator in {
        "additionalProperties",
        "unevaluatedProperties",
    } and isinstance(error.instance, dict):
        schema = error.schema
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        if isinstance(properties, dict):
            pointers = [
                (*base, member)
                for member in sorted(set(error.instance) - set(properties))
            ]
    if not pointers:
        pointers = [base]
    return [
        Schema2Diagnostic(
            code=code,
            message=error.message,
            primary=_location(source_identity, _pointer(pointer)),
        )
        for pointer in pointers
    ]


def _resolution_relations(
    source: dict[str, Any],
    language_bundle: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    language = _language(language_bundle)
    modules_member = cast(str, profile["modules_member"])
    module_id_member = cast(str, profile["module_id_member"])
    imports_member = cast(str, profile["imports_member"])
    symbols_member = cast(str, profile["symbols_member"])
    alias_member = cast(str, profile["import_alias_member"])
    package_member = cast(str, profile["import_package_member"])
    version_member = cast(str, profile["import_version_member"])
    import_symbol_member = cast(str, profile["import_symbol_member"])
    source_type_member = cast(str, profile["symbol_type_member"])
    source_symbol_member = cast(str, profile["symbol_name_member"])
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    modules = cast(list[dict[str, Any]], source[modules_member])
    requirements = cast(list[dict[str, str]], source[requirements_member])
    packages = cast(list[dict[str, Any]], language["packages"])
    model_id = cast(str, _path_value(source, cast(str, profile["manifest_id_path"])))

    def row(
        values: dict[str, str], pointers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return {"values": values, "pointers": pointers or {}}

    requirement_rows = [
        row(
            {
                "package": item[requirement_package_member],
                "version": item[requirement_version_member],
            },
            {
                "package": _pointer(
                    (requirements_member, index, requirement_package_member)
                ),
                "version": _pointer(
                    (requirements_member, index, requirement_version_member)
                ),
            },
        )
        for index, item in enumerate(requirements)
    ]
    package_rows = [
        row({"package": cast(str, item["id"]), "version": cast(str, item["version"])})
        for item in packages
    ]
    module_rows: list[dict[str, Any]] = []
    import_rows: list[dict[str, Any]] = []
    symbol_rows: list[dict[str, Any]] = []
    for module_index, module in enumerate(modules):
        module_id = cast(str, module[module_id_member])
        module_rows.append(
            row(
                {"module": module_id},
                {"module": _pointer((modules_member, module_index, module_id_member))},
            )
        )
        for import_index, item in enumerate(
            cast(list[dict[str, str]], module[imports_member])
        ):
            import_rows.append(
                row(
                    {
                        "module": module_id,
                        "alias": item[alias_member],
                        "package": item[package_member],
                        "version": item[version_member],
                        "import_symbol": item[import_symbol_member],
                    },
                    {
                        "alias": _pointer(
                            (
                                modules_member,
                                module_index,
                                imports_member,
                                import_index,
                                alias_member,
                            )
                        ),
                        "package": _pointer(
                            (
                                modules_member,
                                module_index,
                                imports_member,
                                import_index,
                                package_member,
                            )
                        ),
                        "version": _pointer(
                            (
                                modules_member,
                                module_index,
                                imports_member,
                                import_index,
                                version_member,
                            )
                        ),
                        "import_symbol": _pointer(
                            (
                                modules_member,
                                module_index,
                                imports_member,
                                import_index,
                                import_symbol_member,
                            )
                        ),
                    },
                )
            )
        for symbol_index, symbol in enumerate(
            cast(list[dict[str, Any]], module[symbols_member])
        ):
            symbol_rows.append(
                row(
                    {
                        "model": model_id,
                        "module": module_id,
                        "symbol": cast(str, symbol[source_symbol_member]),
                        "type_alias": cast(str, symbol[source_type_member]),
                    },
                    {
                        "symbol": _pointer(
                            (
                                modules_member,
                                module_index,
                                symbols_member,
                                symbol_index,
                                source_symbol_member,
                            )
                        ),
                        "type_alias": _pointer(
                            (
                                modules_member,
                                module_index,
                                symbols_member,
                                symbol_index,
                                source_type_member,
                            )
                        ),
                    },
                )
            )
    exported_type_rows = [
        row(
            {
                "package": cast(str, package["id"]),
                "version": cast(str, package["version"]),
                "symbol": cast(str, exported["id"]),
            }
        )
        for package in packages
        for exported in cast(list[dict[str, Any]], package["exports"]["types"])
    ]
    requirement_keys = {
        (
            item[requirement_package_member],
            item[requirement_version_member],
        )
        for item in requirements
    }
    selected_packages = [
        package
        for package in packages
        if (package["id"], package["version"]) in requirement_keys
    ]
    dependency_rows = [
        row(
            {
                "owner": cast(str, package["id"]),
                "dependency": cast(str, dependency),
            }
        )
        for package in selected_packages
        for dependency in cast(list[str], package["dependencies"]["required"])
    ]
    required_capability_rows = [
        row(
            {
                "package": cast(str, package["id"]),
                "capability": cast(str, capability),
            }
        )
        for package in selected_packages
        for capability in cast(list[str], package["capabilities"]["required"])
    ]
    provided_capability_rows = [
        row(
            {
                "package": cast(str, package["id"]),
                "capability": cast(str, capability),
            }
        )
        for package in selected_packages
        for capability in cast(list[str], package["capabilities"]["provided"])
    ]
    return {
        "requirements": requirement_rows,
        "packages": package_rows,
        "modules": module_rows,
        "imports": import_rows,
        "symbols": symbol_rows,
        "exported_types": exported_type_rows,
        "manifest_entry": [
            row(
                {
                    "module": cast(
                        str,
                        _path_value(
                            source,
                            cast(str, profile["manifest_entry_module_path"]),
                        ),
                    )
                },
                {
                    "module": "/"
                    + cast(str, profile["manifest_entry_module_path"]).replace(".", "/")
                },
            )
        ],
        "selected_dependencies": dependency_rows,
        "required_capabilities": required_capability_rows,
        "provided_capabilities": provided_capability_rows,
    }


def _law_matches(
    subject: dict[str, Any],
    target: dict[str, Any],
    fields: list[dict[str, str]],
) -> bool:
    return all(
        subject["values"][field["subject"]] == target["values"][field["target"]]
        for field in fields
    )


def _resolution_law_failures(
    law: dict[str, Any],
    relations: dict[str, list[dict[str, Any]]],
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    operator = law["operator"]
    if operator == "require-match":
        failures: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for subject in relations[law["subject_relation"]]:
            guard = law.get("guard")
            if isinstance(guard, dict):
                guarded = [
                    target
                    for target in relations[guard["target_relation"]]
                    if _law_matches(subject, target, guard["match"])
                ]
                if guard["cardinality"] == "exactly-one" and len(guarded) != 1:
                    continue
            matches = [
                target
                for target in relations[law["target_relation"]]
                if _law_matches(subject, target, law["match"])
            ]
            if law["cardinality"] == "exactly-one" and len(matches) != 1:
                failures.append((subject, None))
        return failures
    if operator == "require-unique":
        unique_first: dict[tuple[str, ...], dict[str, Any]] = {}
        failures = []
        fields = [*law["scope"], *law["key"]]
        for item in relations[law["relation"]]:
            key = tuple(item["values"][field] for field in fields)
            previous = unique_first.get(key)
            if previous is None:
                unique_first[key] = item
            else:
                failures.append((item, previous))
        return failures
    if operator == "require-single-value":
        group_first: dict[tuple[str, ...], tuple[tuple[str, ...], dict[str, Any]]] = {}
        failures = []
        for item in relations[law["relation"]]:
            group = tuple(
                item["values"][field] for field in [*law["scope"], *law["group"]]
            )
            value = tuple(item["values"][field] for field in law["value"])
            previous = group_first.get(group)
            if previous is None:
                group_first[group] = (value, item)
            elif previous[0] != value:
                failures.append((item, previous[1]))
        return failures
    raise ValueError(f"unknown admitted resolution law operator: {operator}")


def _resolution_diagnostics(
    source: dict[str, Any],
    source_identity: str,
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    *,
    stage: str,
) -> list[Schema2Diagnostic]:
    language = _language(language_bundle)
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    reasons = {
        item["id"]: item for item in cast(list[dict[str, Any]], language["reasons"])
    }
    resolution_contract = cast(
        dict[str, Any],
        cast(dict[str, Any], kernel["meta_format"])["resolution_judgment"],
    )
    operation_specs = {
        item["id"]: item
        for item in cast(list[dict[str, Any]], resolution_contract["operations"])
    }
    relations = _resolution_relations(source, language_bundle, profile)
    diagnostics: list[Schema2Diagnostic] = []
    for judgment in cast(list[dict[str, Any]], profile["judgment_chain"]):
        operation_spec = operation_specs[judgment["operation"]]
        if operation_spec["stage"] != stage:
            continue
        law = cast(dict[str, Any], operation_spec["law"])
        pointer_field = cast(str, law["pointer_field"])
        reason = reasons[judgment["reason"]]
        for item, previous in _resolution_law_failures(law, relations):
            pointer = cast(dict[str, str], item["pointers"]).get(pointer_field, "")
            related = (
                (
                    _location(
                        source_identity,
                        cast(dict[str, str], previous["pointers"]).get(
                            pointer_field, ""
                        ),
                    ),
                )
                if previous is not None
                else ()
            )
            diagnostics.append(
                Schema2Diagnostic(
                    code=cast(str, reason["diagnostic"]),
                    message=(
                        f"Model Source failed resolution judgment {judgment['id']}"
                    ),
                    primary=_location(source_identity, pointer),
                    related=related,
                )
            )
    return diagnostics


def check_model_source(path: str) -> CheckedModel | Schema2RefusalReport:
    """Admit and check one Model Source Package without publishing artifacts."""
    try:
        data = Path(path).read_bytes()
    except OSError as err:
        raise UnreadableInputError(f"cannot read input document: {path}") from err

    kernel, ldb = load_authorities()
    admission = admit_authorities(kernel, ldb)
    if not admission.admitted:
        return bootstrap_refusal(admission)
    source_size_reason = _unique_reason(
        ldb,
        stage="ingress",
        operation="greater-than",
        limit_path="resources.max_source_bytes",
    )
    max_source_bytes = _path_value(
        ldb, cast(str, source_size_reason["predicate"]["limit_path"])
    )
    if len(data) > max_source_bytes:
        return _refusal(
            cast(str, source_size_reason["diagnostic"]),
            "unidentified",
            "",
            "Model Source Package exceeds the admitted byte bound",
            ldb,
        )
    try:
        source = _strict_object(data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as err:
        parse_reason = _unique_reason(
            ldb,
            stage="parse",
            operation="not-equal",
        )
        return _refusal(
            cast(str, parse_reason["diagnostic"]),
            "unidentified",
            "",
            f"Model Source Package is outside canonical JSON: {err}",
            ldb,
        )

    lowering = _model_lowering(ldb)
    profile = _resolution_profile(ldb, cast(str, lowering["resolution_profile"]))
    source_identity = content_identity(
        cast(str, profile["source_identity_domain"]), cast(JsonValue, source)
    )
    language = _language(ldb)
    source_schema = next(
        item["schema"]
        for item in cast(list[dict[str, Any]], language["wire_schemas"])
        if item["artifact_kind"] == "model-source-package"
    )
    errors = sorted(
        jsonschema.Draft202012Validator(source_schema).iter_errors(source),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    structural_diagnostics = [
        diagnostic
        for error in errors
        for diagnostic in _schema_error_diagnostics(error, source_identity, ldb)
    ]
    structural_diagnostics.extend(
        _model_check_diagnostics(source, source_identity, ldb)
    )
    resolution_contract = cast(
        dict[str, Any],
        cast(dict[str, Any], kernel["meta_format"])["resolution_judgment"],
    )
    for stage in cast(list[str], resolution_contract["stage_order"]):
        diagnostics = list(structural_diagnostics) if stage == "static" else []
        diagnostics.extend(
            _resolution_diagnostics(
                source,
                source_identity,
                kernel,
                ldb,
                stage=stage,
            )
        )
        refusal = _bounded_refusal(diagnostics, ldb)
        if refusal is not None:
            return refusal
    try:
        _resolved_source_symbols(source, ldb)
    except (KeyError, TypeError, ValueError) as err:
        source_contract_reason = _reason_by_id(
            ldb,
            cast(str, profile["structural_reason"]),
        )
        return _refusal(
            cast(str, source_contract_reason["diagnostic"]),
            source_identity,
            "",
            f"Model Source name resolution failed: {err}",
            ldb,
        )
    return CheckedModel(
        source=source,
        source_identity=source_identity,
        kernel=kernel,
        language_bundle=ldb,
    )


def _artifact_contract(
    language_bundle: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    matches = [
        item
        for item in cast(
            list[dict[str, Any]], _language(language_bundle)["artifact_contracts"]
        )
        if item["artifact_kind"] == artifact_kind
    ]
    if len(matches) != 1:
        raise ValueError(f"artifact contract is not unique: {artifact_kind}")
    return matches[0]


def _artifact_schema(
    language_bundle: dict[str, Any], artifact_kind: str
) -> dict[str, Any]:
    contract = _artifact_contract(language_bundle, artifact_kind)
    matches = [
        item["schema"]
        for item in cast(
            list[dict[str, Any]], _language(language_bundle)["artifact_wire_schemas"]
        )
        if item["artifact_kind"] == contract["schema_kind"]
    ]
    if len(matches) != 1:
        raise ValueError(f"artifact wire schema is not unique: {artifact_kind}")
    return cast(dict[str, Any], matches[0])


def _wire_schema_identity_for_kind(
    language_bundle: dict[str, Any], artifact_kind: str
) -> str:
    contract = _artifact_contract(language_bundle, artifact_kind)
    schema = _artifact_schema(language_bundle, artifact_kind)
    body = {key: value for key, value in schema.items() if key != "$id"}
    return content_identity(
        cast(str, contract["wire_schema_identity_domain"]), cast(JsonValue, body)
    )


def _identified_artifact(
    language_bundle: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    contract = _artifact_contract(language_bundle, artifact_kind)
    body = cast(
        dict[str, JsonValue],
        {
            "artifact_kind": artifact_kind,
            "artifact_version": "2.0.0",
            "wire_schema_identity": _wire_schema_identity_for_kind(
                language_bundle, artifact_kind
            ),
            **payload,
        },
    )
    excluded = set(cast(list[str], contract["identity_excluded_members"]))
    identity_body = {key: value for key, value in body.items() if key not in excluded}
    artifact = {
        **body,
        "content_identity": content_identity(
            cast(str, contract["identity_domain"]), cast(JsonValue, identity_body)
        ),
    }
    jsonschema.Draft202012Validator(
        _artifact_schema(language_bundle, artifact_kind)
    ).validate(artifact)
    return artifact


def _verify_artifact(value: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    artifact_kind = value.get("artifact_kind")
    if not isinstance(artifact_kind, str):
        return False
    try:
        contract = _artifact_contract(language_bundle, artifact_kind)
        schema = _artifact_schema(language_bundle, artifact_kind)
        jsonschema.Draft202012Validator(schema).validate(value)
    except (KeyError, TypeError, ValueError, jsonschema.ValidationError):
        return False
    if value.get("wire_schema_identity") != _wire_schema_identity_for_kind(
        language_bundle, artifact_kind
    ):
        return False
    excluded = set(cast(list[str], contract["identity_excluded_members"]))
    body = {
        key: item
        for key, item in value.items()
        if key != "content_identity" and key not in excluded
    }
    return value.get("content_identity") == content_identity(
        cast(str, contract["identity_domain"]), cast(JsonValue, body)
    )


def _resolved_source_symbols(
    source: dict[str, Any], language_bundle: dict[str, Any]
) -> list[tuple[dict[str, Any], tuple[object, ...]]]:
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    language = _language(language_bundle)
    model_id = _path_value(source, cast(str, profile["manifest_id_path"]))
    modules_member = cast(str, profile["modules_member"])
    module_id_member = cast(str, profile["module_id_member"])
    imports_member = cast(str, profile["imports_member"])
    symbols_member = cast(str, profile["symbols_member"])
    alias_member = cast(str, profile["import_alias_member"])
    package_member = cast(str, profile["import_package_member"])
    version_member = cast(str, profile["import_version_member"])
    import_symbol_member = cast(str, profile["import_symbol_member"])
    source_symbol_member = cast(str, profile["symbol_name_member"])
    fact_symbol_member = cast(str, profile["symbol_fact_member"])
    source_type_member = cast(str, profile["symbol_type_member"])
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    requirements = {
        (
            item[requirement_package_member],
            item[requirement_version_member],
        )
        for item in cast(list[dict[str, str]], source[requirements_member])
    }
    packages = {
        (item["id"], item["version"]): item
        for item in cast(list[dict[str, Any]], language["packages"])
    }
    selected_source_rows = {
        pointer: value
        for value, pointer in _selected_values(
            source, cast(list[str], lowering["source_selector"])
        )
    }
    rows: list[tuple[dict[str, Any], tuple[object, ...]]] = []
    resolved_source_pointers: set[tuple[object, ...]] = set()
    module_ids: set[str] = set()
    resolved_names: set[tuple[str, str, str]] = set()
    for module_index, module in enumerate(
        cast(list[dict[str, Any]], source[modules_member])
    ):
        module_id = cast(str, module[module_id_member])
        if module_id in module_ids:
            raise ValueError(f"duplicate module id: {module_id}")
        module_ids.add(module_id)
        imports: dict[str, dict[str, str]] = {}
        for item in cast(list[dict[str, str]], module[imports_member]):
            alias = item[alias_member]
            if alias in imports:
                raise ValueError(f"duplicate import alias: {alias}")
            package_key = (item[package_member], item[version_member])
            if package_key not in requirements:
                raise ValueError(f"import is not declared as a requirement: {alias}")
            package = packages.get(package_key)
            if package is None:
                raise ValueError(f"import package release is unavailable: {alias}")
            exported_types = {
                exported["id"]
                for exported in cast(list[dict[str, Any]], package["exports"]["types"])
            }
            if item[import_symbol_member] not in exported_types:
                raise ValueError(f"imported type is not exported: {alias}")
            imports[alias] = item
        for symbol_index, source_symbol in enumerate(
            cast(list[dict[str, Any]], module[symbols_member])
        ):
            source_pointer = (
                modules_member,
                module_index,
                symbols_member,
                symbol_index,
            )
            if source_pointer not in selected_source_rows:
                continue
            if selected_source_rows[source_pointer] is not source_symbol:
                raise ValueError("model lowering source selection was ambiguous")
            resolved_source_pointers.add(source_pointer)
            alias = source_symbol[source_type_member]
            imported = imports.get(alias)
            if imported is None:
                raise ValueError(f"symbol type alias is unresolved: {alias}")
            name = cast(str, source_symbol[source_symbol_member])
            resolved_symbol = {
                "model": model_id,
                "module": module_id,
                "name": name,
            }
            resolved_key = (model_id, module_id, name)
            if resolved_key in resolved_names:
                raise ValueError(f"duplicate resolved symbol: {name}")
            resolved_names.add(resolved_key)
            fields = {
                key: value
                for key, value in source_symbol.items()
                if key not in {source_symbol_member, source_type_member}
            }
            fields[fact_symbol_member] = name
            fields["resolved_symbol"] = resolved_symbol
            fields["type_identity"] = {
                "package": imported[package_member],
                "version": imported[version_member],
                "symbol": imported[import_symbol_member],
            }
            rows.append(
                (
                    fields,
                    source_pointer,
                )
            )
    if set(selected_source_rows) != resolved_source_pointers:
        raise ValueError(
            "model lowering source selector is outside the resolution profile"
        )
    entry_module = _path_value(source, cast(str, profile["manifest_entry_module_path"]))
    if entry_module not in module_ids:
        raise ValueError("manifest entry_module does not name a module")
    return sorted(
        rows,
        key=lambda item: (
            item[0]["resolved_symbol"]["model"],
            item[0]["resolved_symbol"]["module"],
            item[0]["resolved_symbol"]["name"],
        ),
    )


def _package_lock(checked: CheckedModel) -> dict[str, JsonValue]:
    language = _language(checked.language_bundle)
    lowering = _model_lowering(checked.language_bundle)
    profile = _resolution_profile(
        checked.language_bundle, cast(str, lowering["resolution_profile"])
    )
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    available = {
        (item["id"], item["version"]): item
        for item in cast(list[dict[str, Any]], language["packages"])
    }
    requirements = sorted(
        [
            {
                "id": item[requirement_package_member],
                "version": item[requirement_version_member],
            }
            for item in cast(list[dict[str, str]], checked.source[requirements_member])
        ],
        key=lambda item: (item["id"], item["version"]),
    )
    selected: dict[str, dict[str, Any]] = {}
    pending = list(requirements)
    dependency_edges: list[dict[str, JsonValue]] = []
    while pending:
        requirement = pending.pop(0)
        package = available.get((requirement["id"], requirement["version"]))
        if package is None:
            raise ValueError("an admitted source requirement has no exact package")
        previous = selected.get(package["id"])
        if previous is not None:
            if previous["semantic_identity"] != package["semantic_identity"]:
                raise ValueError("one package id resolved to conflicting releases")
            continue
        selected[package["id"]] = package
        for dependency_id in sorted(package["dependencies"]["required"]):
            candidates = [
                candidate
                for (candidate_id, _version), candidate in available.items()
                if candidate_id == dependency_id
            ]
            if len(candidates) != 1:
                raise ValueError("required dependency does not resolve uniquely")
            dependency = candidates[0]
            dependency_edges.append(
                {
                    "from_package": package["id"],
                    "kind": "required",
                    "to_package": dependency["id"],
                }
            )
            pending.append({"id": dependency["id"], "version": dependency["version"]})

    selected_packages = [selected[name] for name in sorted(selected)]

    def package_definitions(package: dict[str, Any], authority_path: str) -> list[Any]:
        matches = [
            entry["definitions"]
            for entry in cast(list[dict[str, Any]], package["semantic_closure"])
            if entry["authority_path"] == authority_path
        ]
        if len(matches) != 1 or not isinstance(matches[0], list):
            raise ValueError(f"package semantic closure is missing {authority_path}")
        return cast(list[Any], matches[0])

    def runtime_semantic_closure(
        package: dict[str, Any],
    ) -> list[dict[str, JsonValue]]:
        runtime_paths = set(cast(list[str], package["runtime_semantic_paths"]))
        return [
            cast(dict[str, JsonValue], entry)
            for entry in cast(list[dict[str, Any]], package["semantic_closure"])
            if entry["authority_path"] in runtime_paths
        ]

    providers: dict[str, str] = {}
    for package in selected_packages:
        for capability in package["capabilities"]["provided"]:
            if capability in providers:
                raise ValueError("selected capability has multiple providers")
            providers[capability] = package["id"]
    for package in selected_packages:
        for capability in package["capabilities"]["required"]:
            if capability not in providers:
                raise ValueError("selected capability has no provider")

    def exported(collection: str) -> list[dict[str, JsonValue]]:
        rows: list[dict[str, JsonValue]] = []
        for package in selected_packages:
            definitions = {
                item["id"]: item
                for item in cast(
                    list[dict[str, Any]],
                    package_definitions(package, f"language.{collection}"),
                )
            }
            for identity in package["exports"][collection]:
                rows.append(
                    {
                        "definition": cast(JsonValue, definitions[identity]),
                        "package": package["id"],
                    }
                )
        return sorted(
            rows, key=lambda item: cast(dict[str, Any], item["definition"])["id"]
        )

    numeric_definitions = {
        item["id"]: item
        for package in selected_packages
        for item in cast(
            list[dict[str, Any]],
            package_definitions(package, "language.quantity.numeric_policies"),
        )
    }
    runtime_definitions = {
        item["id"]: item
        for package in selected_packages
        for item in cast(
            list[dict[str, Any]],
            package_definitions(package, "language.runtime_profiles"),
        )
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
    selected_diagnostics = sorted(
        {
            code
            for package in selected_packages
            for code in package["exports"]["diagnostics"]
        }
    )
    selected_reasons = sorted(
        [
            reason
            for package in selected_packages
            for reason in cast(
                list[dict[str, JsonValue]],
                package_definitions(package, "language.reasons"),
            )
            if reason["diagnostic"] in selected_diagnostics
        ],
        key=lambda item: cast(str, item["id"]),
    )
    dependency_edges.sort(
        key=lambda edge: (
            cast(str, edge["from_package"]),
            cast(str, edge["to_package"]),
        )
    )
    selected_types: list[dict[str, JsonValue]] = [
        {**cast(dict[str, JsonValue], exported_type), "package": package["id"]}
        for package in selected_packages
        for exported_type in package["exports"]["types"]
    ]
    selected_types.sort(key=lambda item: cast(str, item["id"]))
    body = cast(
        dict[str, JsonValue],
        {
            "resolution_profile": cast(JsonValue, profile),
            "root_requirements": cast(JsonValue, requirements),
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
                    "definitions": runtime_semantic_closure(package),
                }
                for package in selected_packages
            ],
            "dependency_edges": cast(JsonValue, dependency_edges),
            "capability_bindings": [
                {"capability": capability, "provider_package": providers[capability]}
                for capability in sorted(providers)
            ],
            "types": cast(JsonValue, selected_types),
            "components": cast(JsonValue, exported("components")),
            "conversions": cast(JsonValue, exported("conversions")),
            "operations": cast(JsonValue, exported("operations")),
            "numeric_profiles": cast(
                JsonValue, [numeric_definitions[name] for name in numeric_profiles]
            ),
            "runtime_profiles": cast(
                JsonValue, [runtime_definitions[name] for name in runtime_profiles]
            ),
            "diagnostics": selected_diagnostics,
            "diagnostic_reasons": cast(JsonValue, selected_reasons),
            "language_rules": sorted(
                {
                    rule
                    for package in selected_packages
                    for rule in package["exports"]["language_rules"]
                }
            ),
        },
    )
    semantic_projection: dict[str, JsonValue] = {
        "packages": [
            {
                "id": package["id"],
                "version": package["version"],
                "semantic_identity": package["semantic_identity"],
            }
            for package in selected_packages
        ],
        "package_semantic_closures": cast(JsonValue, body["package_semantic_closures"]),
        "capability_bindings": cast(JsonValue, body["capability_bindings"]),
        "types": cast(JsonValue, body["types"]),
        "components": cast(JsonValue, body["components"]),
        "conversions": cast(JsonValue, body["conversions"]),
        "operations": cast(JsonValue, body["operations"]),
        "numeric_profiles": cast(JsonValue, body["numeric_profiles"]),
        "runtime_profiles": cast(JsonValue, body["runtime_profiles"]),
    }
    body["selected_semantics"] = cast(JsonValue, semantic_projection)
    body["semantic_identity"] = content_identity(
        "package-lock-selected-semantics-v2",
        cast(JsonValue, semantic_projection),
    )
    return _identified_artifact(checked.language_bundle, "package-lock", body)


def _apply_language_rule(
    language: dict[str, Any],
    *,
    rule_id: str,
    phase: str,
    judgment: str,
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply the Kernel's exact select-bind-substitute rule mechanics."""
    candidates = [
        rule
        for rule in cast(list[dict[str, Any]], language["rules"])
        if rule["id"] == rule_id
        and rule["phase"] == phase
        and rule["judgment"] == judgment
        and len(rule["premises"]) == len(facts)
        and all(
            premise["fact_kind"] == fact["kind"]
            for premise, fact in zip(rule["premises"], facts, strict=True)
        )
    ]
    if len(candidates) != 1:
        raise ValueError("language rule selection was not unique")
    rule = candidates[0]
    bindings: dict[str, Any] = {}
    for premise, fact in zip(rule["premises"], facts, strict=True):
        for variable, field in premise["bind"].items():
            value = fact["fields"][field]
            if variable in bindings and bindings[variable] != value:
                raise ValueError("language rule binding conflicted")
            bindings[variable] = value
    fields: dict[str, Any] = {}
    for name, term in rule["conclusion"]["fields"].items():
        if term["tag"] == "literal":
            fields[name] = term["value"]
        elif term["tag"] == "variable" and term["name"] in bindings:
            fields[name] = bindings[term["name"]]
        else:
            raise ValueError("language rule term could not be substituted")
    return {"kind": rule["conclusion"]["fact_kind"], "fields": fields}


def _value_matches_fact_contract(
    value: Any, contract: dict[str, Any], language_bundle: dict[str, Any]
) -> bool:
    if "const" in contract:
        return type(value) is type(contract["const"]) and value == contract["const"]
    if "enum" in contract:
        return isinstance(contract["enum"], list) and value in contract["enum"]
    value_type = contract.get("type")
    if value_type == "non-empty-string":
        return isinstance(value, str) and bool(value)
    if value_type == "inventory-member":
        return value in _inventory_values(language_bundle, cast(str, contract["path"]))
    if value_type == "closed-int64-interval":
        return (
            isinstance(value, dict)
            and set(value) == {"minimum", "maximum"}
            and isinstance(value["minimum"], int)
            and not isinstance(value["minimum"], bool)
            and isinstance(value["maximum"], int)
            and not isinstance(value["maximum"], bool)
            and -(2**63) <= value["minimum"] <= value["maximum"] <= 2**63 - 1
        )
    if value_type == "closed-object":
        required = contract.get("required_members")
        field_types = contract.get("field_types")
        return (
            isinstance(value, dict)
            and isinstance(required, list)
            and isinstance(field_types, dict)
            and set(value) == set(required)
            and all(
                _value_matches_fact_contract(
                    value[name],
                    cast(dict[str, Any], field_types[name]),
                    language_bundle,
                )
                for name in required
            )
        )
    return False


def _fact_is_admitted(
    fact: dict[str, Any], kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> bool:
    fact_authority = cast(dict[str, Any], kernel["meta_format"]["fact"])
    schemas = {
        item["kind"]: item["field_contract"]
        for item in cast(list[dict[str, Any]], fact_authority["schemas"])
    }
    kind = fact.get("kind")
    fields = fact.get("fields")
    field_contracts = cast(dict[str, dict[str, Any]], fact_authority["field_contracts"])
    if (
        set(fact) != set(fact_authority["required_members"])
        or not isinstance(kind, str)
        or kind not in schemas
        or not isinstance(fields, dict)
    ):
        return False
    contract = field_contracts[schemas[kind]]
    if not (
        set(fields) == set(contract)
        and all(
            _value_matches_fact_contract(fields[name], field_contract, language_bundle)
            for name, field_contract in contract.items()
        )
    ):
        return False
    language = _language(language_bundle)
    rules = {
        rule["id"]: rule
        for rule in cast(list[dict[str, Any]], language["rules"])
        if isinstance(rule.get("id"), str)
    }
    for lowering in cast(list[dict[str, Any]], language["model_lowerings"]):
        chain = lowering.get("rule_chain")
        if not isinstance(chain, list) or not chain:
            return False
        terminal = chain[-1]
        rule = rules.get(terminal.get("rule")) if isinstance(terminal, dict) else None
        conclusion = rule.get("conclusion") if isinstance(rule, dict) else None
        if not isinstance(conclusion, dict) or conclusion.get("fact_kind") != kind:
            continue
        equalities = lowering.get("output_equalities")
        if not isinstance(equalities, list):
            return False
        for equality in equalities:
            if not isinstance(equality, dict):
                return False
            values: list[Any] = []
            for path in (equality.get("left"), equality.get("right")):
                if (
                    not isinstance(path, list)
                    or not path
                    or not all(isinstance(segment, str) for segment in path)
                ):
                    return False
                value: Any = fields
                for segment in path:
                    if not isinstance(value, dict) or segment not in value:
                        return False
                    value = value[segment]
                values.append(value)
            try:
                if canonical_bytes(values[0]) != canonical_bytes(values[1]):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def admit_resolved_model(
    artifacts: dict[str, dict[str, Any]],
) -> ResolvedModelAdmission:
    """Admit a semantic artifact trio against the exact packaged authorities."""
    kernel, ldb = load_authorities()
    authority_admission = admit_authorities(kernel, ldb)
    if not authority_admission.admitted:
        return ResolvedModelAdmission(
            False,
            tuple(item.code for item in authority_admission.diagnostics),
        )
    lowering = _model_lowering(ldb)
    diagnostic = (
        cast(
            str,
            _reason_by_id(
                ldb,
                cast(str, lowering["admission_reason"]),
            )["diagnostic"],
        ),
    )
    if set(artifacts) != {
        "package-lock",
        "rir-semantic-payload",
        "resolved-model",
    }:
        return ResolvedModelAdmission(False, diagnostic)
    lock = artifacts["package-lock"]
    rir = artifacts["rir-semantic-payload"]
    resolved = artifacts["resolved-model"]
    if not all(_verify_artifact(item, ldb) for item in (lock, rir, resolved)):
        return ResolvedModelAdmission(False, diagnostic)
    root_requirements = lock.get("root_requirements")
    output_member = cast(str, lowering["output_member"])
    declarations = rir.get(output_member)
    if not isinstance(root_requirements, list) or not isinstance(declarations, list):
        return ResolvedModelAdmission(False, diagnostic)
    profile = _resolution_profile(ldb, cast(str, lowering["resolution_profile"]))
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    synthetic = CheckedModel(
        source={
            requirements_member: [
                {
                    requirement_package_member: item["id"],
                    requirement_version_member: item["version"],
                }
                for item in root_requirements
            ]
        },
        source_identity="unbound-for-semantic-admission",
        kernel=kernel,
        language_bundle=ldb,
    )
    try:
        expected_lock = _package_lock(synthetic)
    except (KeyError, TypeError, ValueError, jsonschema.ValidationError):
        return ResolvedModelAdmission(False, diagnostic)
    if (
        lock != expected_lock
        or rir.get("selected_semantics") != lock.get("selected_semantics")
        or rir.get("package_lock_semantic_identity") != lock.get("semantic_identity")
    ):
        return ResolvedModelAdmission(False, diagnostic)
    language = _language(ldb)
    rules = {rule["id"]: rule for rule in cast(list[dict[str, Any]], language["rules"])}
    try:
        terminal_rule = lowering["rule_chain"][-1]["rule"]
        terminal_kind = rules[terminal_rule]["conclusion"]["fact_kind"]
    except (KeyError, IndexError, TypeError):
        return ResolvedModelAdmission(False, diagnostic)
    resolved_keys: list[tuple[str, str, str]] = []
    package_versions = {
        item["id"]: item["version"]
        for item in cast(list[dict[str, Any]], lock["packages"])
    }
    selected_types = {
        (item["package"], package_versions[item["package"]], item["id"])
        for item in cast(list[dict[str, Any]], lock["types"])
    }
    for item in declarations:
        if not isinstance(item, dict) or not _fact_is_admitted(
            {"kind": terminal_kind, "fields": item}, kernel, ldb
        ):
            return ResolvedModelAdmission(False, diagnostic)
        resolved_symbol = cast(dict[str, str], item["resolved_symbol"])
        resolved_keys.append(
            (
                resolved_symbol["model"],
                resolved_symbol["module"],
                resolved_symbol["name"],
            )
        )
        type_identity = cast(dict[str, str], item["type_identity"])
        if (
            type_identity["package"],
            type_identity["version"],
            type_identity["symbol"],
        ) not in selected_types:
            return ResolvedModelAdmission(False, diagnostic)
    if resolved_keys != sorted(resolved_keys) or len(resolved_keys) != len(
        set(resolved_keys)
    ):
        return ResolvedModelAdmission(False, diagnostic)
    expected_resolved = _identified_artifact(
        ldb,
        "resolved-model",
        {
            "kernel_identity": cast(str, kernel["content_identity"]),
            "language_bundle_identity": cast(str, ldb["content_identity"]),
            "package_lock_identity": cast(str, lock["content_identity"]),
            "rir_identity": cast(str, rir["content_identity"]),
        },
    )
    if resolved != expected_resolved:
        return ResolvedModelAdmission(False, diagnostic)
    return ResolvedModelAdmission(True, ())


def lower_checked_model(checked: CheckedModel) -> dict[str, dict[str, JsonValue]]:
    """Lower one checked source to the semantic and provenance artifacts."""
    admission = admit_authorities(checked.kernel, checked.language_bundle)
    if not admission.admitted:
        raise ValueError("lowerer received authorities that failed admission")
    lock = _package_lock(checked)
    language = _language(checked.language_bundle)
    lowering = _model_lowering(checked.language_bundle)
    profile = _resolution_profile(
        checked.language_bundle, cast(str, lowering["resolution_profile"])
    )
    source_rows = _resolved_source_symbols(checked.source, checked.language_bundle)
    declarations: list[dict[str, JsonValue]] = []
    for fields, _source_pointer in source_rows:
        fact = {
            "kind": lowering["initial_fact_kind"],
            "fields": fields,
        }
        for invocation in cast(list[dict[str, str]], lowering["rule_chain"]):
            fact = _apply_language_rule(
                language,
                rule_id=invocation["rule"],
                phase=invocation["phase"],
                judgment=invocation["judgment"],
                facts=[fact],
            )
        declarations.append(cast(dict[str, JsonValue], fact["fields"]))
    output_member = cast(str, lowering["output_member"])
    rir = _identified_artifact(
        checked.language_bundle,
        "rir-semantic-payload",
        {
            output_member: cast(JsonValue, declarations),
            "selected_semantics": cast(JsonValue, lock["selected_semantics"]),
            "package_lock_semantic_identity": cast(str, lock["semantic_identity"]),
        },
    )
    resolved = _identified_artifact(
        checked.language_bundle,
        "resolved-model",
        {
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
        },
    )
    debug_map = _identified_artifact(
        checked.language_bundle,
        "debug-map",
        {
            "source_identity": checked.source_identity,
            "rir_identity": rir["content_identity"],
            "entries": [
                {
                    "rir_pointer": _pointer((output_member, index)),
                    "source_pointer": _pointer(source_rows[index][1]),
                }
                for index in range(len(declarations))
            ],
        },
    )
    resolution_receipt = _identified_artifact(
        checked.language_bundle,
        "resolution-receipt",
        {
            "resolver": _RESOLVER_IMPLEMENTATION_IDENTITY,
            "resolution_profile": cast(str, profile["id"]),
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "diagnostics": [],
        },
    )
    capability_manifest = _identified_artifact(
        checked.language_bundle,
        "capability-manifest",
        {
            "resolved_model_identity": resolved["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
            "packages": [
                {
                    "id": item["id"],
                    "version": item["version"],
                    "content_identity": item["content_identity"],
                }
                for item in cast(list[dict[str, str]], lock["packages"])
            ],
            "capability_bindings": cast(JsonValue, lock["capability_bindings"]),
            "types": cast(JsonValue, lock["types"]),
            "components": cast(JsonValue, lock["components"]),
            "conversions": cast(JsonValue, lock["conversions"]),
            "operations": cast(JsonValue, lock["operations"]),
            "numeric_profiles": cast(JsonValue, lock["numeric_profiles"]),
            "runtime_profiles": cast(JsonValue, lock["runtime_profiles"]),
            "language_rules": cast(JsonValue, lock["language_rules"]),
        },
    )
    build_receipt = _identified_artifact(
        checked.language_bundle,
        "build-receipt",
        {
            "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
            "resolved_model_identity": resolved["content_identity"],
            "capability_manifest_identity": capability_manifest["content_identity"],
            "debug_map_identity": debug_map["content_identity"],
            "resolution_receipt_identity": resolution_receipt["content_identity"],
        },
    )
    return {
        "package-lock": lock,
        "rir-semantic-payload": rir,
        "resolved-model": resolved,
        "capability-manifest": capability_manifest,
        "debug-map": debug_map,
        "resolution-receipt": resolution_receipt,
        "build-receipt": build_receipt,
    }


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    data = canonical_bytes(cast(JsonValue, value))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_canonical_artifact(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise UsageError(
                "argument_conflict",
                f"publication members must not be symlinks: {path.name}",
            )
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(
                f"committed publication member is not a regular file: {path.name}"
            )
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read()
        value = _strict_object(data)
    except UsageError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as err:
        raise RuntimeError(
            f"committed publication member is unreadable: {path.name}"
        ) from err
    if data != canonical_bytes(cast(JsonValue, value)):
        raise RuntimeError(
            f"committed publication member is not canonical: {path.name}"
        )
    return value


def _assert_directory_without_symlink(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as err:
        raise RuntimeError(f"publication directory is unavailable: {path}") from err
    if stat.S_ISLNK(metadata.st_mode):
        raise UsageError(
            "argument_conflict", f"publication directory must not be a symlink: {path}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"publication path is not a directory: {path}")


def _expected_capability_manifest(
    lock: dict[str, Any],
    rir: dict[str, Any],
    resolved: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, JsonValue]:
    return _identified_artifact(
        language_bundle,
        "capability-manifest",
        {
            "resolved_model_identity": cast(str, resolved["content_identity"]),
            "package_lock_identity": cast(str, lock["content_identity"]),
            "rir_identity": cast(str, rir["content_identity"]),
            "packages": [
                {
                    "id": item["id"],
                    "version": item["version"],
                    "content_identity": item["content_identity"],
                }
                for item in cast(list[dict[str, str]], lock["packages"])
            ],
            "capability_bindings": cast(JsonValue, lock["capability_bindings"]),
            "types": cast(JsonValue, lock["types"]),
            "components": cast(JsonValue, lock["components"]),
            "conversions": cast(JsonValue, lock["conversions"]),
            "operations": cast(JsonValue, lock["operations"]),
            "numeric_profiles": cast(JsonValue, lock["numeric_profiles"]),
            "runtime_profiles": cast(JsonValue, lock["runtime_profiles"]),
            "language_rules": cast(JsonValue, lock["language_rules"]),
        },
    )


def _store_root() -> Path:
    configured = os.environ.get(_STORE_DIRECTORY_ENV)
    if configured:
        return _normalized_absolute_path(configured)
    state_home = os.environ.get("XDG_STATE_HOME")
    base = (
        _normalized_absolute_path(state_home)
        if state_home
        else Path.home() / ".local" / "state"
    )
    return base / "gda-balancing" / "store-v2"


def _store_invocation_path(descriptor_identity: str, invocation_key: str) -> Path:
    if not descriptor_identity.startswith("sha256:"):
        raise ValueError("descriptor identity is not content addressed")
    descriptor_key = descriptor_identity.removeprefix("sha256:")
    return _store_root() / "invocations" / descriptor_key / invocation_key


def _store_anchor_path(descriptor_identity: str, invocation_key: str) -> Path:
    if not descriptor_identity.startswith("sha256:"):
        raise ValueError("descriptor identity is not content addressed")
    descriptor_key = descriptor_identity.removeprefix("sha256:")
    return _store_root() / "anchors" / descriptor_key / f"{invocation_key}.json"


def _store_lock_path(descriptor_identity: str, invocation_key: str) -> Path:
    if not descriptor_identity.startswith("sha256:"):
        raise ValueError("descriptor identity is not content addressed")
    descriptor_key = descriptor_identity.removeprefix("sha256:")
    return _store_root() / "locks" / descriptor_key / f"{invocation_key}.lock"


def _anchor_authentication_key() -> bytes:
    encoded = os.environ.get(_ANCHOR_KEY_ENV)
    if (
        encoded is None
        or len(encoded) != 64
        or encoded.lower() != encoded
        or any(character not in "0123456789abcdef" for character in encoded)
    ):
        raise RuntimeError(
            f"{_ANCHOR_KEY_ENV} must contain exactly 64 lowercase hexadecimal digits"
        )
    return bytes.fromhex(encoded)


def _authenticated_anchor(
    index: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    authentication = hmac.new(
        _anchor_authentication_key(),
        canonical_bytes(cast(JsonValue, index)),
        hashlib.sha256,
    ).hexdigest()
    return {
        "anchor_kind": "authenticated-publication-index-v1",
        "algorithm": "hmac-sha256",
        "publication_index": cast(JsonValue, index),
        "authentication": authentication,
    }


def _verified_anchor(path: Path) -> dict[str, Any]:
    envelope = _read_canonical_artifact(path)
    if set(envelope) != {
        "anchor_kind",
        "algorithm",
        "publication_index",
        "authentication",
    }:
        raise RuntimeError("committed publication anchor envelope is malformed")
    index = envelope.get("publication_index")
    authentication = envelope.get("authentication")
    if (
        envelope.get("anchor_kind") != "authenticated-publication-index-v1"
        or envelope.get("algorithm") != "hmac-sha256"
        or not isinstance(index, dict)
        or not isinstance(authentication, str)
    ):
        raise RuntimeError("committed publication anchor envelope is malformed")
    expected = hmac.new(
        _anchor_authentication_key(),
        canonical_bytes(cast(JsonValue, index)),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(authentication, expected):
        raise RuntimeError("committed publication anchor authentication is invalid")
    return index


def _write_anchor_exclusive(
    path: Path,
    artifact: dict[str, JsonValue],
    *,
    before_commit: bool = False,
) -> None:
    data = canonical_bytes(cast(JsonValue, _authenticated_anchor(artifact)))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
        if before_commit:
            raise RuntimeError("injected publication fault before anchor commit")
        try:
            os.link(temporary, path)
        except OSError as err:
            raise RuntimeError(
                "publication anchor already exists or is unwritable"
            ) from err
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _invocation_lock(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("invocation-key lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _primary_artifact_name(
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> str:
    primary = [
        member.logical_name for member in artifact_set if member.role == "primary"
    ]
    if len(primary) != 1:
        raise ValueError("artifact set must declare exactly one primary member")
    return primary[0]


def _assert_ancestor_chain_without_symlink(path: Path) -> None:
    for candidate in reversed((path, *path.parents)):
        if not candidate.exists() and not candidate.is_symlink():
            continue
        try:
            metadata = candidate.lstat()
        except OSError as err:
            raise RuntimeError(
                f"cannot inspect publication path ancestor: {candidate}"
            ) from err
        if stat.S_ISLNK(metadata.st_mode):
            raise UsageError(
                "argument_conflict",
                f"publication path ancestors must not be symlinks: {candidate}",
            )


def _ensure_directory_chain(path: Path) -> None:
    _assert_ancestor_chain_without_symlink(path)
    missing = [
        candidate
        for candidate in reversed((path, *path.parents))
        if not candidate.exists()
    ]
    for directory in missing:
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        else:
            _fsync_directory(directory.parent)
    _assert_directory_without_symlink(path)


def _materialize_primary(out_path: Path, resolved: dict[str, Any]) -> None:
    data = canonical_bytes(cast(JsonValue, resolved))
    if out_path.is_symlink():
        raise UsageError("argument_conflict", "--out must not be a symlink")
    if out_path.exists():
        try:
            metadata = out_path.lstat()
            existing = out_path.read_bytes()
        except OSError as err:
            raise UsageError(
                "unwritable_output", f"cannot inspect output: {out_path}"
            ) from err
        if not stat.S_ISREG(metadata.st_mode):
            raise UsageError(
                "unwritable_output", f"output is not a regular file: {out_path}"
            )
        if existing == data:
            return
        raise UsageError(
            "unwritable_output", f"output already contains different bytes: {out_path}"
        )
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{out_path.name}.", dir=out_path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if out_path.is_symlink() or out_path.exists():
            raise UsageError(
                "unwritable_output", f"output appeared during publication: {out_path}"
            )
        os.replace(temporary, out_path)
        _fsync_directory(out_path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _recover_publication(
    invocation_path: Path,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    source_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
) -> dict[str, JsonValue]:
    member_files = {
        member.logical_name: f"{member.logical_name}.json" for member in artifact_set
    }
    expected_names = [member.logical_name for member in artifact_set]
    member_kinds = {
        member.logical_name: member.artifact_kind for member in artifact_set
    }
    _assert_directory_without_symlink(invocation_path)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    _assert_ancestor_chain_without_symlink(anchor_path)
    try:
        anchor_metadata = anchor_path.lstat()
    except OSError as err:
        raise RuntimeError("committed publication anchor is unavailable") from err
    if (
        not stat.S_ISREG(anchor_metadata.st_mode)
        or stat.S_IMODE(anchor_metadata.st_mode) & 0o222
    ):
        raise RuntimeError("committed publication anchor trust boundary is invalid")
    anchor = _verified_anchor(anchor_path)
    index = _read_canonical_artifact(invocation_path / "publication-index.json")
    if not _verify_artifact(index, language_bundle) or index != anchor:
        raise RuntimeError("committed publication index identity is invalid")
    if index.get("descriptor_identity") != descriptor_identity:
        raise RuntimeError("publication index belongs to another command")
    if index.get("invocation_key") != invocation_key:
        raise RuntimeError("publication index belongs to another invocation")
    if index.get("command_input_identity") != command_input_identity:
        raise UsageError(
            "invocation_key_conflict",
            "Invocation key is already bound to a different canonical input",
        )

    receipt = _read_canonical_artifact(invocation_path / "artifact-set-receipt.json")
    if not _verify_artifact(receipt, language_bundle) or receipt.get(
        "content_identity"
    ) != index.get("receipt_identity"):
        raise RuntimeError(
            "committed artifact-set receipt does not match its index anchor"
        )
    if (
        receipt.get("descriptor_identity") != descriptor_identity
        or receipt.get("invocation_key") != invocation_key
        or receipt.get("manifest_locator")
        != str((invocation_path / "artifact-set-manifest.json").absolute())
        or receipt.get("member_locators")
        != [
            {
                "logical_name": logical_name,
                "locator": str(
                    (invocation_path / member_files[logical_name]).absolute()
                ),
            }
            for logical_name in expected_names
        ]
    ):
        raise RuntimeError("committed artifact-set receipt has invalid bindings")
    manifest = _read_canonical_artifact(invocation_path / "artifact-set-manifest.json")
    if not _verify_artifact(manifest, language_bundle) or manifest.get(
        "content_identity"
    ) != receipt.get("manifest_identity"):
        raise RuntimeError("committed artifact-set manifest does not match its receipt")
    members = manifest.get("members")
    if (
        not isinstance(members, list)
        or [item.get("logical_name") for item in members if isinstance(item, dict)]
        != expected_names
    ):
        raise RuntimeError("committed artifact-set manifest is incomplete")
    artifacts: dict[str, dict[str, Any]] = {}
    for member in members:
        if not isinstance(member, dict):
            raise RuntimeError("committed artifact-set manifest member is malformed")
        logical_name = member.get("logical_name")
        if not isinstance(logical_name, str) or logical_name not in member_files:
            raise RuntimeError("committed artifact-set manifest member is unknown")
        expected_path = invocation_path / member_files[logical_name]
        artifact = _read_canonical_artifact(expected_path)
        if (
            not _verify_artifact(artifact, language_bundle)
            or artifact.get("content_identity") != member.get("content_identity")
            or artifact.get("artifact_kind") != member.get("artifact_kind")
            or artifact.get("artifact_kind") != member_kinds[logical_name]
            or artifact.get("wire_schema_identity")
            != member.get("wire_schema_identity")
        ):
            raise RuntimeError("committed artifact-set member failed revalidation")
        artifacts[logical_name] = artifact
    semantic_artifacts = {
        name: artifacts[name]
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    }
    if not admit_resolved_model(semantic_artifacts).admitted:
        raise RuntimeError("committed Resolved Model failed exact-authority admission")
    lock = artifacts["package-lock"]
    rir = artifacts["rir-semantic-payload"]
    resolved = artifacts["resolved-model"]
    if artifacts["capability-manifest"] != _expected_capability_manifest(
        lock, rir, resolved, language_bundle
    ):
        raise RuntimeError("committed Capability manifest is not an exact projection")
    build_receipt = artifacts["build-receipt"]
    debug_map = artifacts["debug-map"]
    resolution_receipt = artifacts["resolution-receipt"]
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    expected_build_bindings = {
        "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
        "source_identity": source_identity,
        "kernel_identity": load_authorities()[0]["content_identity"],
        "language_bundle_identity": language_bundle["content_identity"],
        "package_lock_identity": lock["content_identity"],
        "rir_identity": rir["content_identity"],
        "resolved_model_identity": resolved["content_identity"],
        "capability_manifest_identity": artifacts["capability-manifest"][
            "content_identity"
        ],
        "debug_map_identity": debug_map["content_identity"],
        "resolution_receipt_identity": resolution_receipt["content_identity"],
    }
    if any(
        build_receipt.get(key) != value
        for key, value in expected_build_bindings.items()
    ):
        raise RuntimeError("committed build receipt has invalid bindings")
    if (
        debug_map.get("source_identity") != source_identity
        or debug_map.get("rir_identity") != rir["content_identity"]
        or resolution_receipt.get("resolver") != _RESOLVER_IMPLEMENTATION_IDENTITY
        or resolution_receipt.get("resolution_profile") != profile["id"]
        or resolution_receipt.get("source_identity") != source_identity
        or resolution_receipt.get("kernel_identity")
        != load_authorities()[0]["content_identity"]
        or resolution_receipt.get("language_bundle_identity")
        != language_bundle["content_identity"]
        or resolution_receipt.get("package_lock_identity") != lock["content_identity"]
        or resolution_receipt.get("diagnostics") != []
    ):
        raise RuntimeError("committed provenance artifacts have invalid bindings")
    _materialize_primary(out_path, artifacts[_primary_artifact_name(artifact_set)])
    return cast(dict[str, JsonValue], receipt)


def publish_model_artifacts(
    checked: CheckedModel,
    source_path: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    publication_fault: str | None = None,
) -> dict[str, JsonValue]:
    """Serialize one invocation key before inspecting or changing its publication."""
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    if lock_path.is_symlink():
        raise UsageError(
            "argument_conflict", "Invocation-key lock must not be a symlink"
        )
    with _invocation_lock(lock_path):
        return _publish_model_artifacts_locked(
            checked,
            source_path,
            out,
            invocation_key,
            descriptor_identity,
            artifact_set,
            publication_fault,
        )


def _publish_model_artifacts_locked(
    checked: CheckedModel,
    source_path: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    publication_fault: str | None = None,
) -> dict[str, JsonValue]:
    """Atomically publish one complete build set while its invocation lock is held."""
    out_path = _normalized_absolute_path(out)
    if os.path.realpath(source_path) == os.path.realpath(out_path):
        raise UsageError(
            "argument_conflict", "--out must not resolve to the input path"
        )
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    if (
        out_path == invocation_path
        or invocation_path in out_path.parents
        or out_path in invocation_path.parents
    ):
        raise UsageError(
            "argument_conflict",
            "--out must not overlap the Invocation-key publication path",
        )
    parent = out_path.parent
    _assert_ancestor_chain_without_symlink(parent)
    if parent.is_symlink() or not parent.is_dir():
        raise UsageError("unwritable_output", f"cannot write output directory: {out}")
    if out_path.is_symlink():
        raise UsageError("argument_conflict", "--out must not be a symlink")
    command_input = _identified_artifact(
        checked.language_bundle,
        "model-build-command-input",
        {
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
        },
    )
    command_input_identity = cast(str, command_input["content_identity"])
    _assert_ancestor_chain_without_symlink(invocation_path)
    if invocation_path.is_symlink():
        raise UsageError(
            "argument_conflict", "Invocation-key publication must not be a symlink"
        )
    if invocation_path.exists() and not anchor_path.exists():
        _assert_directory_without_symlink(invocation_path)
        shutil.rmtree(invocation_path)
        _fsync_directory(invocation_path.parent)
    if invocation_path.exists():
        return _recover_publication(
            invocation_path,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            checked.source_identity,
            checked.language_bundle,
            artifact_set,
        )
    if out_path.exists():
        raise UsageError("unwritable_output", f"output already exists: {out_path}")

    artifacts = lower_checked_model(checked)
    semantic_admission = admit_resolved_model(
        {
            name: cast(dict[str, Any], artifacts[name])
            for name in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
            )
        }
    )
    if not semantic_admission.admitted:
        raise RuntimeError("lowerer produced a Resolved Model that failed admission")
    declared = {member.logical_name: member.artifact_kind for member in artifact_set}
    if set(artifacts) != set(declared) or any(
        artifacts[name]["artifact_kind"] != declared[name] for name in artifacts
    ):
        raise RuntimeError("lowerer output does not match the descriptor artifact set")
    if not all(
        _verify_artifact(cast(dict[str, Any], artifact), checked.language_bundle)
        for artifact in artifacts.values()
    ):
        raise RuntimeError("lowerer output failed artifact-schema admission")
    descriptor_parent = invocation_path.parent
    store_root = _store_root()
    store_invocations = store_root / "invocations"
    store_anchors = store_root / "anchors"
    anchor_parent = anchor_path.parent
    created_directories: list[Path] = []
    for directory in (
        store_root,
        store_invocations,
        descriptor_parent,
        store_anchors,
        anchor_parent,
    ):
        existed = directory.exists()
        _ensure_directory_chain(directory)
        if not existed:
            created_directories.append(directory)

    members = [
        {
            "logical_name": member.logical_name,
            "artifact_kind": member.artifact_kind,
            "wire_schema_identity": cast(
                str, artifacts[member.logical_name]["wire_schema_identity"]
            ),
            "content_identity": cast(
                str, artifacts[member.logical_name]["content_identity"]
            ),
        }
        for member in artifact_set
    ]
    member_locators = [
        {
            "logical_name": member.logical_name,
            "locator": str(
                (invocation_path / f"{member.logical_name}.json").absolute()
            ),
        }
        for member in artifact_set
    ]
    manifest = _identified_artifact(
        checked.language_bundle,
        "artifact-set-manifest",
        {
            "frame": "typed-logical-member-map-v1",
            "members": cast(JsonValue, members),
        },
    )
    manifest_locator = str((invocation_path / "artifact-set-manifest.json").absolute())
    receipt = _identified_artifact(
        checked.language_bundle,
        "artifact-set-receipt",
        {
            "descriptor_identity": descriptor_identity,
            "invocation_key": invocation_key,
            "manifest_identity": manifest["content_identity"],
            "manifest_locator": manifest_locator,
            "member_locators": cast(JsonValue, member_locators),
        },
    )
    index = _identified_artifact(
        checked.language_bundle,
        "publication-index",
        {
            "adapter": "local-filesystem-directory-rename-v1",
            "descriptor_identity": descriptor_identity,
            "invocation_key": invocation_key,
            "command_input_identity": command_input_identity,
            "receipt_identity": receipt["content_identity"],
        },
    )

    stage = Path(tempfile.mkdtemp(prefix=f".{invocation_key}.", dir=descriptor_parent))
    anchored = False
    committed_by_this_attempt = False
    try:
        for member_index, member in enumerate(artifact_set):
            name = member.logical_name
            _write_json(stage / f"{name}.json", artifacts[name])
            if publication_fault == "after-member-write" and member_index == 0:
                raise RuntimeError("injected publication fault after member write")
        _write_json(stage / "artifact-set-manifest.json", manifest)
        _write_json(stage / "artifact-set-receipt.json", receipt)
        _write_json(stage / "publication-index.json", index)
        for artifact_name, artifact in {
            **artifacts,
            "artifact-set-manifest": manifest,
            "artifact-set-receipt": receipt,
            "publication-index": index,
        }.items():
            staged = _read_canonical_artifact(stage / f"{artifact_name}.json")
            if staged != artifact or not _verify_artifact(
                staged, checked.language_bundle
            ):
                raise RuntimeError("staged artifact verification failed")
        _fsync_directory(stage)
        if publication_fault == "before-commit":
            raise RuntimeError("injected publication fault before commit")
        if invocation_path.exists() or invocation_path.is_symlink():
            raise RuntimeError("Invocation-key publication appeared before commit")
        os.replace(stage, invocation_path)
        committed_by_this_attempt = True
        _fsync_directory(descriptor_parent)
        _write_anchor_exclusive(
            anchor_path,
            index,
            before_commit=publication_fault == "before-anchor-commit",
        )
        anchored = True
        if publication_fault == "after-commit":
            raise RuntimeError("injected publication fault after commit")
        _materialize_primary(out_path, artifacts[_primary_artifact_name(artifact_set)])
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if (
            committed_by_this_attempt
            and not anchored
            and invocation_path.exists()
            and not anchor_path.exists()
        ):
            shutil.rmtree(invocation_path)
            _fsync_directory(invocation_path.parent)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    return receipt
