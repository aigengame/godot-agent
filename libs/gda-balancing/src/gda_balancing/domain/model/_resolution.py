"""Authority-driven Model Source checking and exact name resolution."""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias, cast

import jsonschema

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
)
from gda_balancing.domain.authority.admission import (
    BOOTSTRAP_REFUSAL_CATALOG,
)
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    parse_canonical_object,
)
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bound_diagnostics,
    reason_by_id,
    refusal_catalog_for_reasons,
)
from gda_balancing.domain.formula.notation import (
    FormulaPairRefusal,
    admit_formula_pair,
)
from gda_balancing.domain.operation_program import closed_operation_coordinates

_RESOLVER_IMPLEMENTATION_IDENTITY = "gda-balancing.python-exact-resolver-v1"
_RelationBindings: TypeAlias = dict[str, tuple[Any, tuple[object, ...] | None]]


MODEL_INSPECT_REFUSAL_CATALOG = tuple(
    item
    for item in BOOTSTRAP_REFUSAL_CATALOG
    if item[0]
    in {
        "kernel.binding_mismatch",
        "kernel.identity_mismatch",
        "kernel.member_set_mismatch",
    }
)


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


_FORMULA_REASON = {
    "binding-missing": "model.reason.formula-binding-missing",
    "binding-duplicate": "model.reason.formula-binding-duplicate",
    "type-mismatch": "model.reason.formula-type-mismatch",
    "kind-mismatch": "model.reason.formula-kind-mismatch",
    "unit-mismatch": "model.reason.formula-unit-mismatch",
    "numeric-profile-mismatch": "model.reason.formula-numeric-profile-mismatch",
    "purity-mismatch": "model.reason.formula-purity-mismatch",
    "context-mismatch": "model.reason.formula-context-mismatch",
    "unreachable": "model.reason.formula-unreachable",
    "refusal-widening": "model.reason.formula-refusal-widening",
    "resource-exhausted": "model.reason.formula-resource-exhausted",
    "cycle": "model.reason.formula-cycle",
    "notation-mismatch": "model.reason.formula-notation-mismatch",
}


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
    *_FORMULA_REASON.values(),
)
MODEL_REFUSAL_CATALOG = refusal_catalog_for_reasons(MODEL_REFUSAL_REASONS)


@dataclass(frozen=True)
class CheckedModel:
    source: dict[str, Any]
    source_identity: str
    kernel: dict[str, Any]
    language_bundle: dict[str, Any]
    authority_context: AdmittedAuthorityContext | None = None


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


def _formula_policy(language_bundle: dict[str, Any]) -> dict[str, Any]:
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    extensions = profile.get("extensions")
    policy = (
        extensions.get("standard.formula") if isinstance(extensions, dict) else None
    )
    string_members = (
        "module_formulas_member",
        "bindings_member",
        "formula_id_member",
        "formula_parameters_member",
        "formula_result_member",
        "formula_body_member",
        "body_nodes_member",
        "body_result_member",
        "node_id_member",
        "parameter_id_member",
        "binding_arguments_member",
        "binding_parameter_member",
        "binding_operand_member",
        "binding_site_member",
        "binding_formula_member",
        "binding_cardinality",
        "argument_cardinality",
        "argument_order",
        "same_name_capture",
        "declaration_scope",
    )
    list_members = (
        "allowed_binding_sites",
        "allowed_body_nodes",
        "allowed_operand_kinds",
    )
    identity_domains = (
        policy.get("identity_domains") if isinstance(policy, dict) else None
    )
    inline_body_normalizations = (
        policy.get("inline_body_normalizations") if isinstance(policy, dict) else None
    )
    if (
        not isinstance(policy, dict)
        or any(
            not isinstance(policy.get(member), str) or not policy[member]
            for member in string_members
        )
        or any(
            not isinstance(policy.get(member), list)
            or not policy[member]
            or not all(isinstance(item, str) and item for item in policy[member])
            for member in list_members
        )
        or not isinstance(policy.get("first_class_values"), bool)
        or not isinstance(policy.get("dynamic_lookup"), bool)
        or not isinstance(policy.get("max_nodes_per_formula"), int)
        or cast(int, policy["max_nodes_per_formula"]) <= 0
        or not isinstance(policy.get("resource_charge_per_node"), int)
        or cast(int, policy["resource_charge_per_node"]) <= 0
        or not isinstance(inline_body_normalizations, list)
        or not inline_body_normalizations
        or not all(
            isinstance(normalization, dict)
            and set(normalization) == {"node", "parameter_member", "result_kind"}
            and all(
                isinstance(normalization.get(member), str) and normalization[member]
                for member in ("node", "parameter_member", "result_kind")
            )
            for normalization in inline_body_normalizations
        )
        or len(
            {
                cast(str, normalization["node"])
                for normalization in inline_body_normalizations
            }
        )
        != len(inline_body_normalizations)
        or not isinstance(identity_domains, dict)
        or any(
            not isinstance(domain, str) or not domain
            for domain in identity_domains.values()
        )
    ):
        raise ValueError("the admitted resolution profile has no closed Formula policy")
    return cast(dict[str, Any], policy)


def _operation_formula_slots(
    operation: dict[str, Any],
) -> list[dict[str, Any]]:
    extensions = operation.get("extensions")
    slots = (
        extensions.get("standard.formula-slots")
        if isinstance(extensions, dict)
        else None
    )
    if slots is None:
        return []
    if not isinstance(slots, list) or not all(isinstance(slot, dict) for slot in slots):
        raise ValueError("Operation Formula slot extension is not a list")
    return cast(list[dict[str, Any]], slots)


def _formula_contexts(language_bundle: dict[str, Any]) -> dict[str, dict[str, str]]:
    profiles = cast(
        list[dict[str, Any]], _language(language_bundle)["runtime_profiles"]
    )
    candidates: list[dict[str, dict[str, str]]] = []
    for profile in profiles:
        extensions = profile.get("extensions")
        formula = (
            extensions.get("standard.formula") if isinstance(extensions, dict) else None
        )
        contexts = formula.get("contexts") if isinstance(formula, dict) else None
        if not isinstance(contexts, list):
            continue
        by_phase: dict[str, dict[str, str]] = {}
        for context in contexts:
            if not isinstance(context, dict):
                continue
            phase = context.get("phase")
            frame = context.get("frame")
            if isinstance(phase, str) and isinstance(frame, str):
                by_phase[phase] = {"phase": phase, "frame": frame}
        candidates.append(by_phase)
    if len(candidates) != 1 or set(candidates[0]) != {
        "initialization",
        "event",
        "observation",
    }:
        raise ValueError("the admitted Runtime profile has no unique Formula contexts")
    return candidates[0]


def _operation_reference_node_ids(kernel: dict[str, Any]) -> set[str]:
    """Project Operation-valued instruction nodes from the admitted Kernel."""
    return {
        cast(str, node["id"])
        for node in cast(
            list[dict[str, Any]],
            kernel["meta_format"]["runtime_program"]["nodes"],
        )
        if "operation" in cast(list[str], node["required_members"])
    }


def _selected_source_operation_coordinates(
    source: dict[str, Any],
    lock: dict[str, Any],
    operation_node_ids: set[str],
    additional_roots: set[tuple[str, str, str]] | None = None,
) -> set[tuple[str, str, str]]:
    """Close the exact Operation-valued graph from authored entrypoints."""
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], lock["packages"])
    }
    operations = {
        (
            cast(str, row["package"]),
            package_versions[cast(str, row["package"])],
            cast(str, cast(dict[str, Any], row["definition"])["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in cast(list[dict[str, Any]], lock["operations"])
    }
    selected = {
        (
            cast(str, operation["package"]),
            cast(str, operation["version"]),
            cast(str, operation["id"]),
        )
        for entrypoint in cast(list[dict[str, Any]], source.get("entrypoints", []))
        if isinstance((operation := entrypoint.get("operation")), dict)
    }
    selected.update(additional_roots or set())
    if any(coordinate not in operations for coordinate in selected):
        # Exact Operation-resolution diagnostics own precedence over Formula
        # reachability when an authored root coordinate cannot resolve.
        return set(operations)
    return closed_operation_coordinates(selected, operations, operation_node_ids)


def _selected_resolved_operation_coordinates(
    entrypoints: list[dict[str, Any]],
    selected_semantics: dict[str, Any],
    operation_node_ids: set[str],
    additional_roots: set[tuple[str, str, str]] | None = None,
) -> set[tuple[str, str, str]]:
    """Close Operation-valued instructions from all admitted roots."""
    package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], selected_semantics["packages"])
    }
    operations = {
        (
            cast(str, row["package"]),
            package_versions[cast(str, row["package"])],
            cast(str, cast(dict[str, Any], row["definition"])["id"]),
        ): cast(dict[str, Any], row["definition"])
        for row in cast(list[dict[str, Any]], selected_semantics["operations"])
    }
    selected = {
        (
            cast(str, operation["package"]),
            cast(str, operation["version"]),
            cast(str, operation["id"]),
        )
        for entrypoint in entrypoints
        if isinstance((operation := entrypoint.get("operation")), dict)
    }
    selected.update(additional_roots or set())
    return closed_operation_coordinates(selected, operations, operation_node_ids)


def model_source_identity_domain(language_bundle: dict[str, Any]) -> str:
    """Return the single admitted Model Source identity authority."""
    domain = _resolution_profile(language_bundle).get("source_identity_domain")
    if not isinstance(domain, str) or not domain:
        raise ValueError(
            "the admitted resolution profile has no source identity domain"
        )
    return domain


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


def _formula_pair_diagnostics(
    source: dict[str, Any],
    source_identity: str,
    authority_context: AdmittedAuthorityContext,
) -> list[Schema2Diagnostic]:
    diagnostics: list[Schema2Diagnostic] = []
    requirements = source.get("package_requirements")
    modules = source.get("modules")
    if not isinstance(requirements, list) or not isinstance(modules, list):
        return diagnostics
    for module_index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        formulas = module.get("formulas", [])
        if not isinstance(formulas, list):
            continue
        module_context = {
            "id": module.get("id"),
            "imports": module.get("imports"),
            "symbols": module.get("symbols"),
            "formulas": formulas,
        }
        for formula_index, formula in enumerate(formulas):
            if not isinstance(formula, dict):
                continue
            try:
                admit_formula_pair(
                    {
                        "schema_version": source.get("schema_version"),
                        "package_requirements": requirements,
                        "modules": modules,
                        "module": module_context,
                        "formula": formula,
                    },
                    authority_context,
                )
            except FormulaPairRefusal as err:
                reason = reason_by_id(authority_context.language_bundle, err.reason_id)
                diagnostics.append(
                    Schema2Diagnostic(
                        code=cast(str, reason["diagnostic"]),
                        message=err.message,
                        primary=_location(
                            source_identity,
                            (
                                f"/modules/{module_index}/formulas/"
                                f"{formula_index}/{err.member}"
                            ),
                        ),
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


def _schema_error_pointer_count(error: jsonschema.ValidationError) -> int:
    if error.validator == "required" and isinstance(error.instance, dict):
        required = error.validator_value
        if isinstance(required, list):
            return max(1, len(set(required) - set(error.instance)))
    if error.validator in {
        "additionalProperties",
        "unevaluatedProperties",
    } and isinstance(error.instance, dict):
        schema = error.schema
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        if isinstance(properties, dict):
            return max(1, len(set(error.instance) - set(properties)))
    return 1


def _preferred_schema_errors(
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
    selected = min(
        branches.values(),
        key=lambda items: (
            sum(_schema_error_pointer_count(item) for item in items),
            tuple(str(item.schema_path) for item in items),
        ),
    )
    return [
        preferred for child in selected for preferred in _preferred_schema_errors(child)
    ]


def _schema_error_diagnostics(
    error: jsonschema.ValidationError,
    source_identity: str,
    language_bundle: dict[str, Any],
) -> list[Schema2Diagnostic]:
    error_path = tuple(error.absolute_path)
    if (
        error.validator in {"oneOf", "anyOf"}
        and error.context
        and len(error_path) >= 2
        and error_path[-2] == "symbols"
    ):
        return [
            diagnostic
            for preferred in _preferred_schema_errors(error)
            for diagnostic in _schema_error_diagnostics(
                preferred,
                source_identity,
                language_bundle,
            )
        ]
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
    selected_packages: dict[tuple[str, str], dict[str, Any]] = {}
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
        if package is None or coordinate in selected_packages:
            continue
        selected_packages[coordinate] = package
        for dependency in cast(
            list[dict[str, str]], package["dependencies"]["required"]
        ):
            pending.append((dependency["id"], dependency["version"]))
    selected_package_values = [
        selected_packages[coordinate] for coordinate in sorted(selected_packages)
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
