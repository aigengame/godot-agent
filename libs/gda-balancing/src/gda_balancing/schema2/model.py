"""Authority-driven Model Source checking and lowering for Schema 2.0."""

import fcntl
import hashlib
import hmac
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterable
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Iterator, TypeAlias, cast

import jsonschema

from gda_balancing.envelope import UnreadableInputError, UsageError
from gda_balancing.path_contracts import reject_input_aliasing
from gda_balancing.descriptors import ArtifactSetMemberSpec
from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.authority_graph import LanguageBundleIndex
from gda_balancing.schema2.bootstrap import (
    BOOTSTRAP_REFUSAL_CATALOG,
    BootstrapAdmission,
    admit_authorities,
)
from gda_balancing.schema2.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
    parse_canonical_object,
)
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bound_diagnostics,
    bootstrap_refusal,
    reason_by_id,
)

_RESOLVER_IMPLEMENTATION_IDENTITY = "gda-balancing.python-exact-resolver-v1"
_LOWERER_IMPLEMENTATION_IDENTITY = "gda-balancing.python-lowerer-v1"
_STORE_DIRECTORY_ENV = "GDA_BALANCING_STORE_DIR"
_ANCHOR_KEY_ENV = "GDA_BALANCING_ANCHOR_KEY"
_RelationBindings: TypeAlias = dict[str, tuple[Any, tuple[object, ...] | None]]


@cache
def _descriptor_language_bundle() -> LanguageBundleIndex:
    """Admit the packaged graph once while assembling static command descriptors."""
    _, language_bundle = load_authorities()
    return language_bundle


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


def refusal_catalog_for_stages(
    stages: frozenset[str],
    language_bundle: dict[str, Any] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Project only the LDB refusals reachable by one command family."""
    if language_bundle is None:
        language_bundle = _descriptor_language_bundle()
    return BOOTSTRAP_REFUSAL_CATALOG + tuple(
        (cast(str, item["code"]), cast(str, item["stage"]))
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
        if item.get("stage") in stages
    )


def refusal_catalog_for_reasons(
    reason_ids: Iterable[str],
    language_bundle: dict[str, Any] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Project one command's reachable semantic reasons through the current LDB."""
    if language_bundle is None:
        language_bundle = _descriptor_language_bundle()
    requested = tuple(reason_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("a command refusal catalog cannot contain duplicate reasons")
    reasons = {
        cast(str, item["id"]): item
        for item in cast(list[dict[str, Any]], language_bundle["language"]["reasons"])
    }
    diagnostics = {
        cast(str, item["code"]): cast(str, item["stage"])
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
    }
    missing = [reason_id for reason_id in requested if reason_id not in reasons]
    if missing:
        raise ValueError(
            "command refusal catalog references unknown LDB reasons: "
            + ", ".join(missing)
        )
    projected: list[tuple[str, str]] = []
    for reason_id in requested:
        reason = reasons[reason_id]
        code = cast(str, reason["diagnostic"])
        stage = cast(str, reason["stage"])
        if diagnostics.get(code) != stage:
            raise ValueError(
                f"LDB reason {reason_id} does not match its diagnostic declaration"
            )
        pair = (code, stage)
        if pair not in projected:
            projected.append(pair)
    return BOOTSTRAP_REFUSAL_CATALOG + tuple(projected)


MODEL_REFUSAL_REASONS = (
    "model.reason.source-too-large",
    "model.reason.source-parse-failure",
    "model.reason.source-contract-mismatch",
    "quantity.reason.invalid-domain",
    "quantity.reason.unknown-kind",
    "quantity.reason.unknown-unit",
    "model.reason.duplicate-symbol",
    "quantity.reason.resource-exhausted",
    "model.reason.resolution-resource-exhausted",
    "model.reason.runtime-projection-resource-exhausted",
    "model.reason.unresolved-name",
    "model.reason.name-ambiguity",
    "model.reason.package-version-unavailable",
    "model.reason.resolution-ambiguity",
)
MODEL_REFUSAL_CATALOG = refusal_catalog_for_reasons(MODEL_REFUSAL_REASONS)


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


@dataclass(frozen=True)
class PublicationMember:
    """One pre-admitted value and its descriptor-visible artifact metadata."""

    value: dict[str, Any]
    artifact_kind: str
    wire_schema_identity: str
    content_identity: str


@dataclass(frozen=True)
class RecoveredArtifactSet:
    """One authenticated committed outcome recovered without recomputation."""

    receipt: dict[str, JsonValue]
    artifact_set: tuple[ArtifactSetMemberSpec, ...]
    artifacts: dict[str, dict[str, Any]]


class _ResolutionResourceExhausted(Exception):
    """The admitted resolution-step budget was exhausted."""


@dataclass
class _ResolutionBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise _ResolutionResourceExhausted
        self.used += 1


class _RuntimeProjectionResourceExhausted(Exception):
    """The admitted runtime-projection budget was exhausted."""


@dataclass
class _RuntimeProjectionBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise _RuntimeProjectionResourceExhausted
        self.used += 1


def _strict_object(data: bytes) -> dict[str, Any]:
    return parse_canonical_object(
        data,
        artifact_name="Model Source Package",
    )


def _location(identity: str, pointer: str) -> ArtifactLocation:
    return ArtifactLocation(content_identity=identity, pointer=pointer)


def _diagnostic_stages(language_bundle: dict[str, Any]) -> dict[str, str]:
    return {
        cast(str, item["code"]): cast(str, item["stage"])
        for item in cast(list[dict[str, Any]], language_bundle["diagnostics"])
    }


def _refusal(
    code: str,
    identity: str,
    pointer: str,
    message: str,
    language_bundle: dict[str, Any],
) -> Schema2RefusalReport:
    stage = _diagnostic_stages(language_bundle)[code]
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
    stages = _diagnostic_stages(language_bundle)
    ordered, truncated = bound_diagnostics(
        diagnostics,
        cast(int, language_bundle["resources"]["max_diagnostics"]),
    )
    if not ordered:
        return None
    stage = stages[ordered[0].code]
    if any(stages[item.code] != stage for item in ordered):
        raise ValueError("one refusal report cannot cross refusal stages")
    return Schema2RefusalReport(
        stage=cast(Any, stage),
        diagnostics=ordered,
        truncated=truncated,
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
            reason_by_id(
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
        reason_by_id(
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
    budget: _ResolutionBudget,
) -> dict[str, list[dict[str, Any]]]:
    language = _language(language_bundle)
    available_packages = cast(list[dict[str, Any]], language["packages"])
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    by_coordinate = {
        (package["id"], package["version"]): package for package in available_packages
    }
    selected_packages: dict[str, dict[str, Any]] = {}
    pending = [
        (
            requirement[requirement_package_member],
            requirement[requirement_version_member],
        )
        for requirement in cast(list[dict[str, str]], source[requirements_member])
    ]
    while pending:
        coordinate = pending.pop(0)
        package = by_coordinate.get(coordinate)
        if package is None or package["id"] in selected_packages:
            continue
        selected_packages[package["id"]] = package
        for dependency in cast(
            list[dict[str, str]], package["dependencies"]["required"]
        ):
            pending.append((dependency["id"], dependency["version"]))
    selected_package_values = [
        selected_packages[package_id] for package_id in sorted(selected_packages)
    ]

    def evaluate_term(
        term: dict[str, Any],
        bindings: _RelationBindings,
    ) -> tuple[Any, tuple[object, ...] | None]:
        root = term["root"]
        if root == "source":
            value: Any = source
            pointer: tuple[object, ...] | None = ()
        elif root == "language":
            value = language
            pointer = None
        elif root == "selected-packages":
            value = selected_package_values
            pointer = None
        elif root == "binding":
            value, pointer = bindings[term["binding"]]
        else:
            raise ValueError(f"unknown admitted relation term root: {root}")
        for segment in cast(list[str], term["path"]):
            value = value[segment]
            if pointer is not None:
                pointer = (*pointer, segment)
        return value, pointer

    relations: dict[str, list[dict[str, Any]]] = {}
    for recipe in cast(list[dict[str, Any]], profile["relation_recipes"]):
        environments: list[_RelationBindings] = [{}]
        for binding in cast(list[dict[str, Any]], recipe["bindings"]):
            expanded: list[_RelationBindings] = []
            for environment in environments:
                values, pointer = evaluate_term(binding["source"], environment)
                if not isinstance(values, list):
                    raise ValueError("admitted relation binding source is not a list")
                for index, value in enumerate(values):
                    budget.consume()
                    expanded.append(
                        {
                            **environment,
                            binding["name"]: (
                                value,
                                (*pointer, index) if pointer is not None else None,
                            ),
                        }
                    )
            environments = expanded
        rows: list[dict[str, Any]] = []
        for environment in environments:
            rejected = False
            for predicate in cast(list[dict[str, Any]], recipe["predicates"]):
                budget.consume()
                if predicate["operator"] == "equal" and canonical_bytes(
                    evaluate_term(predicate["left"], environment)[0]
                ) != canonical_bytes(evaluate_term(predicate["right"], environment)[0]):
                    rejected = True
                    break
            if rejected:
                continue
            values: dict[str, str] = {}
            pointers: dict[str, str] = {}
            for field in cast(list[dict[str, Any]], recipe["fields"]):
                budget.consume()
                value, pointer = evaluate_term(field["term"], environment)
                if not isinstance(value, str):
                    raise ValueError("admitted relation field did not produce a string")
                values[field["name"]] = value
                if field["pointer"]:
                    if pointer is None:
                        raise ValueError(
                            "admitted relation pointer has no source location"
                        )
                    pointers[field["name"]] = _pointer(pointer)
            rows.append({"values": values, "pointers": pointers})
        relations[recipe["id"]] = rows
    return relations


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
    budget: _ResolutionBudget,
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    operator = law["operator"]
    if operator == "require-match":
        failures: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for subject in relations[law["subject_relation"]]:
            budget.consume()
            guard = law.get("guard")
            if isinstance(guard, dict):
                guarded = []
                for target in relations[guard["target_relation"]]:
                    budget.consume()
                    if _law_matches(subject, target, guard["match"]):
                        guarded.append(target)
                if guard["cardinality"] == "exactly-one" and len(guarded) != 1:
                    continue
            matches = []
            for target in relations[law["target_relation"]]:
                budget.consume()
                if _law_matches(subject, target, law["match"]):
                    matches.append(target)
            if law["cardinality"] == "exactly-one" and len(matches) != 1:
                failures.append((subject, None))
        return failures
    if operator == "require-unique":
        unique_first: dict[tuple[str, ...], dict[str, Any]] = {}
        failures = []
        fields = [*law["scope"], *law["key"]]
        for item in relations[law["relation"]]:
            budget.consume()
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
            budget.consume()
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
    resource_reason = _unique_reason(
        language_bundle,
        stage="static",
        operation="greater-than",
        limit_path="resources.max_rule_match_steps",
    )
    budget = _ResolutionBudget(
        cast(
            int,
            _path_value(
                language_bundle,
                cast(str, resource_reason["predicate"]["limit_path"]),
            ),
        )
    )
    diagnostics: list[Schema2Diagnostic] = []
    try:
        relations = _resolution_relations(source, language_bundle, profile, budget)
        for judgment in cast(list[dict[str, Any]], profile["judgment_chain"]):
            operation_spec = operation_specs[judgment["operation"]]
            if operation_spec["stage"] != stage:
                continue
            law = cast(dict[str, Any], operation_spec["law"])
            pointer_field = cast(str, law["pointer_field"])
            reason = reasons[judgment["reason"]]
            for item, previous in _resolution_law_failures(law, relations, budget):
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
    except _ResolutionResourceExhausted:
        return [
            Schema2Diagnostic(
                code=cast(str, resource_reason["diagnostic"]),
                message="Model Source resolution exhausted its admitted step budget",
                primary=_location(source_identity, ""),
            )
        ]
    return diagnostics


def check_model_source(path: str) -> CheckedModel | Schema2RefusalReport:
    """Admit and check one Model Source Package without publishing artifacts."""
    try:
        data = Path(path).read_bytes()
    except OSError as err:
        raise UnreadableInputError(f"cannot read input document: {path}") from err

    return _check_model_source_bytes(data)


def check_model_source_value(
    source: dict[str, Any],
    *,
    kernel: dict[str, Any] | None = None,
    language_bundle: dict[str, Any] | None = None,
    authority_admission: BootstrapAdmission | None = None,
) -> CheckedModel | Schema2RefusalReport:
    """Admit an in-memory Model Source through the same authority path as a file."""
    try:
        data = canonical_bytes(cast(JsonValue, source))
    except (TypeError, ValueError, UnicodeEncodeError):
        data = b"null\n"
    return _check_model_source_bytes(
        data,
        kernel=kernel,
        language_bundle=language_bundle,
        authority_admission=authority_admission,
    )


def _check_model_source_bytes(
    data: bytes,
    *,
    kernel: dict[str, Any] | None = None,
    language_bundle: dict[str, Any] | None = None,
    authority_admission: BootstrapAdmission | None = None,
) -> CheckedModel | Schema2RefusalReport:
    if (kernel is None) != (language_bundle is None):
        raise ValueError("Kernel and LDB must be supplied together")
    if kernel is None or language_bundle is None:
        kernel, language_bundle = load_authorities()
    ldb = language_bundle
    admission = authority_admission or admit_authorities(kernel, ldb)
    if admission.kernel_identity != kernel.get(
        "content_identity"
    ) or admission.language_bundle_identity != ldb.get("content_identity"):
        raise ValueError("authority admission belongs to another Kernel/LDB pair")
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
    static_diagnostics = [
        *structural_diagnostics,
        *_model_check_diagnostics(source, source_identity, ldb),
    ]
    resolution_contract = cast(
        dict[str, Any],
        cast(dict[str, Any], kernel["meta_format"])["resolution_judgment"],
    )
    for stage in cast(list[str], resolution_contract["stage_order"]):
        diagnostics = list(static_diagnostics) if stage == "static" else []
        try:
            diagnostics.extend(
                _resolution_diagnostics(
                    source,
                    source_identity,
                    kernel,
                    ldb,
                    stage=stage,
                )
            )
        except (KeyError, TypeError, ValueError):
            if not structural_diagnostics:
                raise
        refusal = _bounded_refusal(diagnostics, ldb)
        if refusal is not None:
            return refusal
    try:
        _resolved_source_symbols(source, ldb)
    except (KeyError, TypeError, ValueError) as err:
        source_contract_reason = reason_by_id(
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
    checked = CheckedModel(
        source=source,
        source_identity=source_identity,
        kernel=kernel,
        language_bundle=ldb,
    )
    try:
        lock, declarations, admitted_lowering, _source_rows = _lowering_inputs(checked)
        _runtime_projection(
            lock,
            declarations,
            admitted_lowering,
            _runtime_projection_budget(kernel, ldb),
        )
    except _RuntimeProjectionResourceExhausted:
        resource_reason = _unique_reason(
            ldb,
            stage="static",
            operation="greater-than",
            limit_path="resources.max_runtime_projection_steps",
        )
        return _refusal(
            cast(str, resource_reason["diagnostic"]),
            source_identity,
            "",
            "Model Source runtime projection exhausted its admitted step budget",
            ldb,
        )
    return checked


def checked_model_template_facts(checked: CheckedModel) -> dict[str, JsonValue]:
    """Project generic graph facts consumed by Template admission profiles."""
    lowering = _model_lowering(checked.language_bundle)
    profile = _resolution_profile(
        checked.language_bundle, cast(str, lowering["resolution_profile"])
    )
    requirements_member = cast(str, profile["requirements_member"])
    requirement_package_member = cast(str, profile["requirement_package_member"])
    requirement_version_member = cast(str, profile["requirement_version_member"])
    root_requirements = [
        {
            "id": item[requirement_package_member],
            "version": item[requirement_version_member],
        }
        for item in cast(list[dict[str, str]], checked.source[requirements_member])
    ]
    lock = _package_lock(checked)
    resolved_packages = [
        {
            "id": item["id"],
            "version": item["version"],
            "content_identity": item["content_identity"],
        }
        for item in cast(list[dict[str, JsonValue]], lock["packages"])
    ]
    source_symbols = []
    for fields, _pointer in _resolved_source_symbols(
        checked.source, checked.language_bundle
    ):
        resolved = cast(dict[str, str], fields["resolved_symbol"])
        source_symbols.append(
            {
                **fields,
                "id": f"{resolved['module']}.{resolved['name']}",
            }
        )
    return {
        "root_requirements": cast(JsonValue, root_requirements),
        "resolved_packages": cast(JsonValue, resolved_packages),
        "source_symbols": cast(JsonValue, source_symbols),
    }


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
    language = _language(language_bundle)
    schemas = [
        item["schema"]
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for item in cast(list[dict[str, Any]], language[collection])
        if item["artifact_kind"] == artifact_kind
    ]
    if len(schemas) != 1:
        raise ValueError(f"wire schema is not unique: {artifact_kind}")
    contracts = [
        item
        for item in cast(list[dict[str, Any]], language["artifact_contracts"])
        if item["artifact_kind"] == artifact_kind
    ]
    if len(contracts) > 1:
        raise ValueError(f"artifact contract is not unique: {artifact_kind}")
    domain = (
        cast(str, contracts[0]["wire_schema_identity_domain"])
        if contracts
        else f"{artifact_kind}-wire-schema-v2"
    )
    schema = cast(dict[str, Any], schemas[0])
    body = {key: value for key, value in schema.items() if key != "$id"}
    return content_identity(domain, cast(JsonValue, body))


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


def identified_artifact(
    language_bundle: dict[str, Any],
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Construct and schema-admit one LDB-owned content-addressed artifact."""
    return _identified_artifact(language_bundle, artifact_kind, payload)


def verify_artifact(value: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    """Re-admit one content-addressed artifact against the exact LDB."""
    return _verify_artifact(value, language_bundle)


def find_published_artifact(
    content_identity_value: str,
    artifact_kind: str,
    language_bundle: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve one exact artifact through authenticated committed publications.

    Locators remain transport facts: callers bind semantic identities, while
    this local-store adapter discovers a locator and then revalidates the
    authenticated publication frame, artifact schema, and content hash.
    """
    anchors = _store_root() / "anchors"
    if not anchors.exists():
        return None
    authentication_key = publication_authentication_key()
    matches: list[dict[str, Any]] = []
    for anchor_path in sorted(anchors.glob("*/*.json")):
        if anchor_path.is_symlink() or not anchor_path.is_file():
            continue
        try:
            index = _verified_anchor(anchor_path, authentication_key)
            if (
                not _verify_artifact(index, language_bundle)
                or not isinstance(index.get("descriptor_identity"), str)
                or not isinstance(index.get("invocation_key"), str)
            ):
                continue
            invocation_path = _store_invocation_path(
                cast(str, index["descriptor_identity"]),
                cast(str, index["invocation_key"]),
            )
            committed_index = _read_canonical_artifact(
                invocation_path / "publication-index.json"
            )
            if committed_index != index:
                continue
            manifest = _read_canonical_artifact(
                invocation_path / "artifact-set-manifest.json"
            )
            if not _verify_artifact(manifest, language_bundle):
                continue
            members = manifest.get("members")
            if not isinstance(members, list):
                continue
            for member in members:
                if (
                    not isinstance(member, dict)
                    or member.get("artifact_kind") != artifact_kind
                    or member.get("content_identity") != content_identity_value
                    or not isinstance(member.get("logical_name"), str)
                ):
                    continue
                artifact = _read_canonical_artifact(
                    invocation_path / f"{member['logical_name']}.json"
                )
                if (
                    _verify_artifact(artifact, language_bundle)
                    and artifact.get("artifact_kind") == artifact_kind
                    and artifact.get("content_identity") == content_identity_value
                ):
                    matches.append(artifact)
        except (OSError, RuntimeError, UsageError, ValueError):
            continue
    if not matches:
        return None
    canonical = canonical_bytes(cast(JsonValue, matches[0]))
    if any(canonical_bytes(cast(JsonValue, item)) != canonical for item in matches[1:]):
        raise RuntimeError("one content identity resolved to different artifacts")
    return matches[0]


def wire_schema_identity(language_bundle: dict[str, Any], artifact_kind: str) -> str:
    """Derive one artifact's wire-schema identity from the exact LDB."""
    return _wire_schema_identity_for_kind(language_bundle, artifact_kind)


def artifact_wire_schema(
    language_bundle: dict[str, Any], artifact_kind: str
) -> dict[str, object]:
    """Return an isolated copy of one exact LDB-owned artifact schema."""
    return cast(
        dict[str, object], deepcopy(_artifact_schema(language_bundle, artifact_kind))
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
        for dependency_constraint in sorted(
            package["dependencies"]["required"],
            key=lambda item: (item["id"], item["version"]),
        ):
            dependency = available.get(
                (
                    dependency_constraint["id"],
                    dependency_constraint["version"],
                )
            )
            if dependency is None:
                raise ValueError("required dependency coordinate is unavailable")
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
            cast(str, edge["to_version"]),
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


def _runtime_projection(
    lock: dict[str, Any],
    declarations: list[dict[str, Any]],
    lowering: dict[str, Any],
    budget: _RuntimeProjectionBudget,
) -> dict[str, Any]:
    """Project only declaration-reachable runtime semantics from a Package Lock."""
    profile = cast(dict[str, Any], lowering["runtime_projection"])

    def path_value(root: Any, path: list[str]) -> Any:
        value = root
        for segment in path:
            if not isinstance(value, dict) or segment not in value:
                raise ValueError(
                    "runtime projection path is outside its admitted value"
                )
            value = value[segment]
        return value

    catalogs: dict[str, list[dict[str, Any]]] = {}
    for collection in cast(list[dict[str, Any]], profile["collections"]):
        source = cast(dict[str, Any], collection["source"])
        rows: list[dict[str, Any]] = []
        if source["kind"] == "lock-member":
            values = lock[source["member"]]
            if not isinstance(values, list):
                raise ValueError("runtime projection lock member is not a list")
            for value in values:
                budget.consume()
                rows.append(
                    {
                        "package": path_value(value, source["package_path"]),
                        "authority_path": None,
                        "value": value,
                    }
                )
        elif source["kind"] == "semantic-closure":
            for closure in cast(
                list[dict[str, Any]], lock["package_semantic_closures"]
            ):
                entries = [
                    entry
                    for entry in cast(list[dict[str, Any]], closure["definitions"])
                    if entry["authority_path"] == source["authority_path"]
                ]
                if len(entries) > 1:
                    raise ValueError(
                        "runtime projection semantic-closure source is not unique"
                    )
                if not entries:
                    continue
                for value in cast(list[Any], entries[0]["definitions"]):
                    budget.consume()
                    rows.append(
                        {
                            "package": closure["package"],
                            "authority_path": source["authority_path"],
                            "value": value,
                        }
                    )
        else:
            raise ValueError("unknown admitted runtime projection collection source")
        catalogs[collection["id"]] = rows

    selected: dict[str, set[int]] = {collection_id: set() for collection_id in catalogs}
    for seed in cast(list[dict[str, Any]], profile["seeds"]):
        collection_id = cast(str, seed["collection"])
        catalog = catalogs[collection_id]
        for declaration in declarations:
            package = path_value(
                declaration,
                cast(list[str], seed["declaration_package_path"]),
            )
            if seed["operator"] != "declaration-field":
                raise ValueError("unknown admitted runtime projection seed operator")
            expected = path_value(
                declaration, cast(list[str], seed["declaration_path"])
            )
            matches = [
                index
                for index, row in enumerate(catalog)
                if (
                    budget.consume() is None
                    and (not seed["same_package"] or row["package"] == package)
                    and canonical_bytes(
                        path_value(
                            row["value"],
                            cast(list[str], seed["target_path"]),
                        )
                    )
                    == canonical_bytes(expected)
                )
            ]
            if not matches:
                raise ValueError("runtime projection seed did not resolve")
            selected[collection_id].update(matches)

    changed = True
    while changed:
        changed = False
        for edge in cast(list[dict[str, Any]], profile["edges"]):
            if edge["operator"] != "equal":
                raise ValueError("unknown admitted runtime projection edge operator")
            source_id = cast(str, edge["source_collection"])
            target_id = cast(str, edge["target_collection"])
            targets = catalogs[target_id]
            for source_index in tuple(selected[source_id]):
                budget.consume()
                source_row = catalogs[source_id][source_index]
                source_value = path_value(
                    source_row["value"], cast(list[str], edge["source_path"])
                )
                matches = [
                    target_index
                    for target_index, target_row in enumerate(targets)
                    if (
                        budget.consume() is None
                        and (
                            not edge["same_package"]
                            or target_row["package"] == source_row["package"]
                        )
                    )
                    and canonical_bytes(
                        path_value(
                            target_row["value"],
                            cast(list[str], edge["target_path"]),
                        )
                    )
                    == canonical_bytes(source_value)
                ]
                if not matches:
                    source_label = (
                        source_row["value"].get("id")
                        if isinstance(source_row["value"], dict)
                        else None
                    )
                    raise ValueError(
                        "runtime projection edge did not resolve: "
                        f"{source_id}->{target_id} for "
                        f"{source_label or f'{source_id}[{source_index}]'}"
                    )
                previous_count = len(selected[target_id])
                selected[target_id].update(matches)
                changed = changed or len(selected[target_id]) != previous_count

    selected_packages = {
        row["package"]
        for collection_id, indexes in selected.items()
        for index, row in enumerate(catalogs[collection_id])
        if index in indexes
    }
    projection: dict[str, Any] = {}
    closure_values: dict[tuple[str, str], list[Any]] = {}
    for collection in cast(list[dict[str, Any]], profile["collections"]):
        collection_id = cast(str, collection["id"])
        rows = [
            row
            for index, row in enumerate(catalogs[collection_id])
            if budget.consume() is None and index in selected[collection_id]
        ]
        for row in rows:
            authority_path = row["authority_path"]
            if isinstance(authority_path, str):
                closure_values.setdefault(
                    (cast(str, row["package"]), authority_path), []
                ).append(row["value"])
        output_member = collection["output_member"]
        if output_member is None:
            continue
        shape = collection["output_shape"]
        if shape == "as-is":
            projected_values: list[Any] = [row["value"] for row in rows]
        elif shape == "package-definition":
            projected_values = [
                {
                    "package": cast(str, row["package"]),
                    "definition": row["value"],
                }
                for row in rows
            ]
        elif shape == "definition":
            projected_values = [row["value"] for row in rows]
        else:
            raise ValueError("unknown admitted runtime projection output shape")
        projection[cast(str, output_member)] = projected_values

    for output in cast(list[dict[str, Any]], profile["outputs"]):
        source_rows = lock[output["source_member"]]
        if not isinstance(source_rows, list):
            raise ValueError("runtime projection output source is not a list")
        kind = output["kind"]
        if kind == "selected-packages":
            output_values: list[Any] = [
                {
                    member: cast(dict[str, Any], row)[member]
                    for member in cast(list[str], output["members"])
                }
                for row in source_rows
                if (
                    budget.consume() is None
                    and cast(dict[str, Any], row)[output["package_member"]]
                    in selected_packages
                )
            ]
        elif kind == "selected-semantic-closures":
            output_values = []
            for closure in cast(list[dict[str, Any]], source_rows):
                budget.consume()
                package = cast(str, closure[output["package_member"]])
                if package not in selected_packages:
                    continue
                entries = []
                for entry in cast(
                    list[dict[str, Any]], closure[output["entries_member"]]
                ):
                    authority_path = cast(str, entry[output["authority_path_member"]])
                    definitions = closure_values.get((package, authority_path))
                    if definitions:
                        entries.append(
                            {
                                output["authority_path_member"]: authority_path,
                                output["definitions_member"]: definitions,
                            }
                        )
                if entries:
                    output_values.append(
                        {
                            output["package_member"]: package,
                            output["entries_member"]: entries,
                        }
                    )
        else:
            raise ValueError("unknown admitted runtime projection output kind")
        projection[cast(str, output["output_member"])] = output_values
    return projection


def _runtime_projection_budget(
    kernel: dict[str, Any], language_bundle: dict[str, Any]
) -> _RuntimeProjectionBudget:
    meta_format = cast(dict[str, Any], kernel["meta_format"])
    runtime_contract = cast(dict[str, Any], meta_format["runtime_projection"])
    accounting = cast(dict[str, Any], runtime_contract["resource_accounting"])
    limit_member = cast(str, accounting["limit_member"])
    resources = cast(dict[str, Any], language_bundle["resources"])
    return _RuntimeProjectionBudget(cast(int, resources[limit_member]))


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
            reason_by_id(
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
    try:
        expected_runtime_projection = _runtime_projection(
            lock,
            cast(list[dict[str, JsonValue]], declarations),
            lowering,
            _runtime_projection_budget(kernel, ldb),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        _RuntimeProjectionResourceExhausted,
    ):
        return ResolvedModelAdmission(False, diagnostic)
    if (
        lock != expected_lock
        or rir.get("selected_semantics") != expected_runtime_projection
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


def _lowering_inputs(
    checked: CheckedModel,
) -> tuple[
    dict[str, Any],
    list[dict[str, JsonValue]],
    dict[str, Any],
    list[tuple[dict[str, Any], tuple[object, ...]]],
]:
    lock = _package_lock(checked)
    language = _language(checked.language_bundle)
    lowering = _model_lowering(checked.language_bundle)
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
    return lock, declarations, lowering, source_rows


def lower_checked_model(checked: CheckedModel) -> dict[str, dict[str, JsonValue]]:
    """Lower one checked source to the semantic and provenance artifacts."""
    admission = admit_authorities(checked.kernel, checked.language_bundle)
    if not admission.admitted:
        raise ValueError("lowerer received authorities that failed admission")
    lock, declarations, lowering, source_rows = _lowering_inputs(checked)
    profile = _resolution_profile(
        checked.language_bundle, cast(str, lowering["resolution_profile"])
    )
    output_member = cast(str, lowering["output_member"])
    rir = _identified_artifact(
        checked.language_bundle,
        "rir-semantic-payload",
        {
            output_member: cast(JsonValue, declarations),
            "selected_semantics": cast(
                JsonValue,
                _runtime_projection(
                    lock,
                    declarations,
                    lowering,
                    _runtime_projection_budget(checked.kernel, checked.language_bundle),
                ),
            ),
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
    capability_manifest = _capability_manifest(
        lock, rir, resolved, checked.language_bundle
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


def _capability_manifest(
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


def publication_authentication_key() -> bytes:
    encoded = os.environ.get(_ANCHOR_KEY_ENV)
    if (
        encoded is None
        or len(encoded) != 64
        or encoded.lower() != encoded
        or any(character not in "0123456789abcdef" for character in encoded)
    ):
        raise UsageError(
            "invalid_argument",
            f"{_ANCHOR_KEY_ENV} must contain exactly 64 lowercase hexadecimal digits",
        )
    return bytes.fromhex(encoded)


def _authenticated_anchor(
    index: dict[str, JsonValue],
    authentication_key: bytes,
) -> dict[str, JsonValue]:
    authentication = hmac.new(
        authentication_key,
        canonical_bytes(cast(JsonValue, index)),
        hashlib.sha256,
    ).hexdigest()
    return {
        "anchor_kind": "authenticated-publication-index-v1",
        "algorithm": "hmac-sha256",
        "publication_index": cast(JsonValue, index),
        "authentication": authentication,
    }


def _verified_anchor(path: Path, authentication_key: bytes) -> dict[str, Any]:
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
        authentication_key,
        canonical_bytes(cast(JsonValue, index)),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(authentication, expected):
        raise RuntimeError("committed publication anchor authentication is invalid")
    return index


def _write_anchor_exclusive(
    path: Path,
    artifact: dict[str, JsonValue],
    authentication_key: bytes,
    *,
    before_commit: bool = False,
) -> None:
    data = canonical_bytes(
        cast(JsonValue, _authenticated_anchor(artifact, authentication_key))
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
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
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    authentication_key: bytes,
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
    anchor = _verified_anchor(anchor_path, authentication_key)
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
    if artifacts["capability-manifest"] != _capability_manifest(
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
    kernel_identity = kernel["content_identity"]
    expected_build_bindings = {
        "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
        "source_identity": source_identity,
        "kernel_identity": kernel_identity,
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
        or resolution_receipt.get("kernel_identity") != kernel_identity
        or resolution_receipt.get("language_bundle_identity")
        != language_bundle["content_identity"]
        or resolution_receipt.get("package_lock_identity") != lock["content_identity"]
        or resolution_receipt.get("diagnostics") != []
    ):
        raise RuntimeError("committed provenance artifacts have invalid bindings")
    _materialize_primary(out_path, artifacts[_primary_artifact_name(artifact_set)])
    return cast(dict[str, JsonValue], receipt)


def publish_artifact_set(
    artifacts: dict[str, PublicationMember],
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    member_validator: Callable[[str, dict[str, Any]], bool],
    publication_fault: str | None = None,
    *,
    authentication_key: bytes | None = None,
) -> dict[str, JsonValue]:
    """Atomically publish a pre-admitted heterogeneous Schema 2.x artifact set.

    Model build owns its semantic recovery audit separately.  This entry point
    serves descriptor-owned sets whose primary value is not itself a runtime
    artifact, while retaining the same invocation lock, authenticated anchor,
    immutable manifest, retry, and all-or-nothing publication protocol.
    """
    if publication_fault not in {
        None,
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
        "after-commit",
    }:
        raise ValueError("unknown publication fault")
    if authentication_key is None:
        authentication_key = publication_authentication_key()
    declared = {member.logical_name: member.artifact_kind for member in artifact_set}
    if set(artifacts) != set(declared) or any(
        artifacts[name].artifact_kind != kind for name, kind in declared.items()
    ):
        raise RuntimeError("prepared output does not match the descriptor artifact set")
    if not all(member_validator(name, artifacts[name].value) for name in artifacts):
        raise RuntimeError("prepared output failed artifact-schema admission")

    out_path = _normalized_absolute_path(out)
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    if lock_path.is_symlink():
        raise UsageError(
            "argument_conflict", "Invocation-key lock must not be a symlink"
        )
    with _invocation_lock(lock_path):
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
            raise UsageError(
                "unwritable_output", f"cannot write output directory: {out_path}"
            )
        if out_path.is_symlink():
            raise UsageError("argument_conflict", "--out must not be a symlink")
        _assert_ancestor_chain_without_symlink(invocation_path)
        if invocation_path.is_symlink():
            raise UsageError(
                "argument_conflict",
                "Invocation-key publication must not be a symlink",
            )
        if invocation_path.exists() and not anchor_path.exists():
            _assert_directory_without_symlink(invocation_path)
            shutil.rmtree(invocation_path)
            _fsync_directory(invocation_path.parent)
        if invocation_path.exists():
            return _recover_generic_publication(
                invocation_path,
                out_path,
                invocation_key,
                descriptor_identity,
                command_input_identity,
                language_bundle,
                artifact_set,
                artifacts,
                member_validator,
                authentication_key,
            )
        if out_path.exists():
            raise UsageError("unwritable_output", f"output already exists: {out_path}")
        return _commit_generic_publication(
            invocation_path,
            anchor_path,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            language_bundle,
            artifact_set,
            artifacts,
            member_validator,
            authentication_key,
            publication_fault,
        )


def recover_committed_artifact_set(
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    candidate_sets: tuple[tuple[ArtifactSetMemberSpec, ...], ...],
    member_validator: Callable[[str, dict[str, Any]], bool],
    *,
    authentication_key: bytes | None = None,
) -> RecoveredArtifactSet | None:
    """Recover one committed producing outcome before its producer reruns."""
    if authentication_key is None:
        authentication_key = publication_authentication_key()
    invocation_path = _store_invocation_path(descriptor_identity, invocation_key)
    anchor_path = _store_anchor_path(descriptor_identity, invocation_key)
    if not invocation_path.exists() or not anchor_path.exists():
        return None
    out_path = _normalized_absolute_path(out)
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    with _invocation_lock(lock_path):
        if not invocation_path.exists() or not anchor_path.exists():
            return None
        manifest = _read_canonical_artifact(
            invocation_path / "artifact-set-manifest.json"
        )
        if not _verify_artifact(manifest, language_bundle):
            raise RuntimeError("committed artifact-set manifest failed revalidation")
        rows = manifest.get("members")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError("committed artifact-set manifest is malformed")
        signature = [
            (row.get("logical_name"), row.get("artifact_kind")) for row in rows
        ]
        matching_sets = [
            candidate
            for candidate in candidate_sets
            if signature
            == [(member.logical_name, member.artifact_kind) for member in candidate]
        ]
        if len(matching_sets) != 1:
            raise RuntimeError(
                "committed artifact set does not name one descriptor outcome"
            )
        artifact_set = matching_sets[0]
        artifacts: dict[str, dict[str, Any]] = {}
        expected: dict[str, PublicationMember] = {}
        for member, row in zip(artifact_set, rows, strict=True):
            artifact = _read_canonical_artifact(
                invocation_path / f"{member.logical_name}.json"
            )
            if (
                not _verify_artifact(artifact, language_bundle)
                or not member_validator(member.logical_name, artifact)
                or artifact.get("artifact_kind") != member.artifact_kind
                or artifact.get("content_identity") != row.get("content_identity")
                or artifact.get("wire_schema_identity")
                != row.get("wire_schema_identity")
            ):
                raise RuntimeError("committed artifact-set member failed revalidation")
            artifacts[member.logical_name] = artifact
            expected[member.logical_name] = PublicationMember(
                value=artifact,
                artifact_kind=member.artifact_kind,
                wire_schema_identity=cast(str, artifact["wire_schema_identity"]),
                content_identity=cast(str, artifact["content_identity"]),
            )
        receipt = _recover_generic_publication(
            invocation_path,
            out_path,
            invocation_key,
            descriptor_identity,
            command_input_identity,
            language_bundle,
            artifact_set,
            expected,
            member_validator,
            authentication_key,
        )
        return RecoveredArtifactSet(
            receipt=receipt,
            artifact_set=artifact_set,
            artifacts=artifacts,
        )


def _recover_generic_publication(
    invocation_path: Path,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    expected_artifacts: dict[str, PublicationMember],
    member_validator: Callable[[str, dict[str, Any]], bool],
    authentication_key: bytes,
) -> dict[str, JsonValue]:
    """Authenticate and re-admit every member before replaying a committed set."""
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
    anchor = _verified_anchor(anchor_path, authentication_key)
    index = _read_canonical_artifact(invocation_path / "publication-index.json")
    if (
        not _verify_artifact(index, language_bundle)
        or index != anchor
        or index.get("descriptor_identity") != descriptor_identity
        or index.get("invocation_key") != invocation_key
    ):
        raise RuntimeError("committed publication index identity is invalid")
    if index.get("command_input_identity") != command_input_identity:
        raise UsageError(
            "invocation_key_conflict",
            "Invocation key is already bound to a different canonical input",
        )

    receipt = _read_canonical_artifact(invocation_path / "artifact-set-receipt.json")
    manifest = _read_canonical_artifact(invocation_path / "artifact-set-manifest.json")
    if (
        not _verify_artifact(receipt, language_bundle)
        or receipt.get("content_identity") != index.get("receipt_identity")
        or not _verify_artifact(manifest, language_bundle)
        or manifest.get("content_identity") != receipt.get("manifest_identity")
    ):
        raise RuntimeError("committed artifact-set framing failed revalidation")
    expected_names = [member.logical_name for member in artifact_set]
    members = manifest.get("members")
    if (
        not isinstance(members, list)
        or [item.get("logical_name") for item in members if isinstance(item, dict)]
        != expected_names
    ):
        raise RuntimeError("committed artifact-set manifest is incomplete")
    for row in members:
        if not isinstance(row, dict):
            raise RuntimeError("committed artifact-set manifest member is malformed")
        name = row.get("logical_name")
        if not isinstance(name, str) or name not in expected_artifacts:
            raise RuntimeError("committed artifact-set manifest member is unknown")
        expected = expected_artifacts[name]
        artifact = _read_canonical_artifact(invocation_path / f"{name}.json")
        if (
            artifact != expected.value
            or not member_validator(name, artifact)
            or row.get("artifact_kind") != expected.artifact_kind
            or row.get("wire_schema_identity") != expected.wire_schema_identity
            or row.get("content_identity") != expected.content_identity
        ):
            raise RuntimeError("committed artifact-set member failed revalidation")
    expected_locators = [
        {
            "logical_name": name,
            "locator": str((invocation_path / f"{name}.json").absolute()),
        }
        for name in expected_names
    ]
    if (
        receipt.get("descriptor_identity") != descriptor_identity
        or receipt.get("invocation_key") != invocation_key
        or receipt.get("manifest_locator")
        != str((invocation_path / "artifact-set-manifest.json").absolute())
        or receipt.get("member_locators") != expected_locators
    ):
        raise RuntimeError("committed artifact-set receipt has invalid bindings")
    primary = _primary_artifact_name(artifact_set)
    _materialize_primary(out_path, expected_artifacts[primary].value)
    return cast(dict[str, JsonValue], receipt)


def _commit_generic_publication(
    invocation_path: Path,
    anchor_path: Path,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    command_input_identity: str,
    language_bundle: dict[str, Any],
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    artifacts: dict[str, PublicationMember],
    member_validator: Callable[[str, dict[str, Any]], bool],
    authentication_key: bytes,
    publication_fault: str | None,
) -> dict[str, JsonValue]:
    descriptor_parent = invocation_path.parent
    store_root = _store_root()
    created_directories: list[Path] = []
    for directory in (
        store_root,
        store_root / "invocations",
        descriptor_parent,
        store_root / "anchors",
        anchor_path.parent,
    ):
        existed = directory.exists()
        _ensure_directory_chain(directory)
        if not existed:
            created_directories.append(directory)
    members = [
        {
            "logical_name": member.logical_name,
            "artifact_kind": artifacts[member.logical_name].artifact_kind,
            "wire_schema_identity": artifacts[member.logical_name].wire_schema_identity,
            "content_identity": artifacts[member.logical_name].content_identity,
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
        language_bundle,
        "artifact-set-manifest",
        {
            "frame": "typed-logical-member-map-v1",
            "members": cast(JsonValue, members),
        },
    )
    receipt = _identified_artifact(
        language_bundle,
        "artifact-set-receipt",
        {
            "descriptor_identity": descriptor_identity,
            "invocation_key": invocation_key,
            "manifest_identity": manifest["content_identity"],
            "manifest_locator": str(
                (invocation_path / "artifact-set-manifest.json").absolute()
            ),
            "member_locators": cast(JsonValue, member_locators),
        },
    )
    index = _identified_artifact(
        language_bundle,
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
    committed = False
    try:
        for index_value, member in enumerate(artifact_set):
            name = member.logical_name
            _write_json(stage / f"{name}.json", artifacts[name].value)
            if publication_fault == "after-member-write" and index_value == 0:
                raise RuntimeError("injected publication fault after member write")
        framing = {
            "artifact-set-manifest": manifest,
            "artifact-set-receipt": receipt,
            "publication-index": index,
        }
        for name, artifact in framing.items():
            _write_json(stage / f"{name}.json", artifact)
        for name, member in artifacts.items():
            staged = _read_canonical_artifact(stage / f"{name}.json")
            if staged != member.value or not member_validator(name, staged):
                raise RuntimeError("staged artifact verification failed")
        for name, artifact in framing.items():
            staged = _read_canonical_artifact(stage / f"{name}.json")
            if staged != artifact or not _verify_artifact(staged, language_bundle):
                raise RuntimeError("staged artifact verification failed")
        _fsync_directory(stage)
        if publication_fault == "before-commit":
            raise RuntimeError("injected publication fault before commit")
        if invocation_path.exists() or invocation_path.is_symlink():
            raise RuntimeError("Invocation-key publication appeared before commit")
        os.replace(stage, invocation_path)
        committed = True
        _fsync_directory(descriptor_parent)
        _write_anchor_exclusive(
            anchor_path,
            index,
            authentication_key,
            before_commit=publication_fault == "before-anchor-commit",
        )
        anchored = True
        if publication_fault == "after-commit":
            raise RuntimeError("injected publication fault after commit")
        primary = _primary_artifact_name(artifact_set)
        _materialize_primary(out_path, artifacts[primary].value)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        if (
            committed
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


def publish_model_artifacts(
    checked: CheckedModel,
    source_path: str,
    out: str,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    publication_fault: str | None = None,
    *,
    authentication_key: bytes | None = None,
) -> dict[str, JsonValue]:
    """Serialize one invocation key before inspecting or changing its publication."""
    if authentication_key is None:
        authentication_key = publication_authentication_key()
    out_path = _normalized_absolute_path(out)
    reject_input_aliasing(out_path, source_path, input_is_known_path=True)
    lock_path = _store_lock_path(descriptor_identity, invocation_key)
    _ensure_directory_chain(lock_path.parent)
    if lock_path.is_symlink():
        raise UsageError(
            "argument_conflict", "Invocation-key lock must not be a symlink"
        )
    with _invocation_lock(lock_path):
        return _publish_model_artifacts_locked(
            checked,
            out_path,
            invocation_key,
            descriptor_identity,
            artifact_set,
            authentication_key,
            publication_fault,
        )


def _publish_model_artifacts_locked(
    checked: CheckedModel,
    out_path: Path,
    invocation_key: str,
    descriptor_identity: str,
    artifact_set: tuple[ArtifactSetMemberSpec, ...],
    authentication_key: bytes,
    publication_fault: str | None = None,
) -> dict[str, JsonValue]:
    """Atomically publish one complete build set while its invocation lock is held."""
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
        raise UsageError(
            "unwritable_output", f"cannot write output directory: {out_path}"
        )
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
            checked.kernel,
            checked.language_bundle,
            artifact_set,
            authentication_key,
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
    publication_artifacts = {
        name: PublicationMember(
            value=cast(dict[str, Any], artifact),
            artifact_kind=cast(str, artifact["artifact_kind"]),
            wire_schema_identity=cast(str, artifact["wire_schema_identity"]),
            content_identity=cast(str, artifact["content_identity"]),
        )
        for name, artifact in artifacts.items()
    }
    return _commit_generic_publication(
        invocation_path,
        anchor_path,
        out_path,
        invocation_key,
        descriptor_identity,
        command_input_identity,
        checked.language_bundle,
        artifact_set,
        publication_artifacts,
        lambda _name, value: _verify_artifact(value, checked.language_bundle),
        authentication_key,
        publication_fault,
    )
