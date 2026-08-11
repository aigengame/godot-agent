"""Template admission-profile validation under the admitted LDB."""

from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.template_contract import (
    TEMPLATE_ARGUMENT_TYPES,
    TEMPLATE_PRIMITIVE_CHARGES,
    TEMPLATE_PRIMITIVE_EVALUATIONS,
    TEMPLATE_PRIMITIVE_RESULT_EFFECTS,
    TEMPLATE_RESOURCE_ACCOUNTING,
    TEMPLATE_SELECTOR_CONTRACT,
)
from gda_balancing.domain.authority.contract_validation import _exact_path_value


def _template_selector_is_closed(
    value: Any,
    roots: set[str],
    roles: set[str],
) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != {"root", "name", "path"}
        or not isinstance(value.get("root"), str)
        or value["root"] not in roots
        or not isinstance(value.get("name"), str)
        or not isinstance(value.get("path"), list)
        or not all(isinstance(part, str) and part for part in value["path"])
    ):
        return False
    return value["root"] != "role" or value["name"] in roles


def _template_primitive_argument_is_closed(
    value: Any,
    contract: dict[str, Any],
    *,
    argument_types: dict[str, dict[str, Any]],
    roots: set[str],
    roles: set[str],
    produced_derived: set[str],
    result_members: set[str],
) -> bool:
    kind = contract["kind"]
    if kind == "selector":
        return _template_selector_is_closed(value, roots, roles)
    if kind == "non-empty-list":
        item = contract.get("item")
        item_contract = argument_types.get(item) if isinstance(item, str) else None
        return (
            isinstance(value, list)
            and bool(value)
            and item_contract is not None
            and all(
                _template_primitive_argument_is_closed(
                    item,
                    item_contract,
                    argument_types=argument_types,
                    roots=roots,
                    roles=roles,
                    produced_derived=produced_derived,
                    result_members=result_members,
                )
                for item in value
            )
        )
    if kind == "role-name":
        return isinstance(value, str) and value in roles
    if kind == "string-list":
        return (
            isinstance(value, list)
            and (contract.get("empty") is True or bool(value))
            and all(isinstance(part, str) and part for part in value)
        )
    if kind == "string":
        return isinstance(value, str) and (contract.get("empty") is True or bool(value))
    if kind == "derived-name":
        return (
            isinstance(value, str)
            and bool(value)
            and (contract.get("fresh") is not True or value not in produced_derived)
        )
    if kind == "model-fact-bindings":
        return (
            isinstance(value, list)
            and (contract.get("cardinality") != "one-or-more" or bool(value))
            and all(
                isinstance(binding, dict)
                and set(binding) == {"result", "source"}
                and isinstance(binding.get("source"), str)
                and binding["source"] in result_members
                and isinstance(binding.get("result"), str)
                and bool(binding["result"])
                and binding["result"] not in produced_derived
                for binding in value
            )
            and len({binding["source"] for binding in value}) == len(value)
            and len({binding["result"] for binding in value}) == len(value)
        )
    if kind == "enum":
        return value in contract.get("values", [])
    if kind == "canonical-json":
        try:
            canonical_bytes(cast(JsonValue, value))
        except (TypeError, ValueError, UnicodeEncodeError):
            return False
        return True
    return False


def _template_primitive_arguments_are_closed(
    arguments: dict[str, Any],
    primitive: dict[str, Any],
    argument_types: dict[str, dict[str, Any]],
    *,
    roots: set[str],
    roles: set[str],
    produced_derived: set[str],
) -> bool:
    declared = primitive.get("argument_types")
    result_members = primitive.get("result_members", [])
    return (
        isinstance(declared, dict)
        and isinstance(result_members, list)
        and set(arguments) == set(primitive.get("argument_members", []))
        and all(
            isinstance(type_id, str)
            and type_id in argument_types
            and _template_primitive_argument_is_closed(
                arguments[name],
                argument_types[type_id],
                argument_types=argument_types,
                roots=roots,
                roles=roles,
                produced_derived=produced_derived,
                result_members=set(result_members),
            )
            for name, type_id in declared.items()
        )
    )


def _template_primitive_evaluation_is_closed(
    primitive: dict[str, Any],
) -> bool:
    """Close the Schema-major host primitive vocabulary without owning profiles."""
    primitive_id = primitive.get("id")
    return isinstance(primitive_id, str) and primitive.get(
        "evaluation"
    ) == TEMPLATE_PRIMITIVE_EVALUATIONS.get(primitive_id)


def _template_admission_profiles_are_closed(
    language_bundle: dict[str, Any],
    meta_format: dict[str, Any],
) -> bool:
    language = language_bundle.get("language")
    contract = meta_format.get("template_admission")
    if not isinstance(language, dict) or not isinstance(contract, dict):
        return False
    if (
        set(contract)
        != {
            "closed",
            "operations",
            "primitive_spec",
            "resource_accounting",
            "role_contract",
            "selector",
        }
        or contract.get("closed") is not True
    ):
        return False
    selector_contract = contract.get("selector")
    accounting = contract.get("resource_accounting")
    operations = contract.get("operations")
    role_contract = contract.get("role_contract")
    primitive_spec = contract.get("primitive_spec")
    if (
        not isinstance(selector_contract, dict)
        or selector_contract != TEMPLATE_SELECTOR_CONTRACT
        or not isinstance(accounting, dict)
        or accounting != TEMPLATE_RESOURCE_ACCOUNTING
        or not isinstance(operations, list)
        or not operations
        or not isinstance(primitive_spec, dict)
        or role_contract
        != {
            "cardinalities": ["exactly-one", "one-or-more"],
            "identifier": "non-empty-string",
        }
    ):
        return False
    role_cardinalities = cast(dict[str, Any], role_contract)["cardinalities"]
    roots = set(cast(list[str], selector_contract["roots"]))
    if (
        set(primitive_spec)
        != {
            "argument_types",
            "canonical_equality",
            "closed",
            "evaluation_order",
            "primitives",
            "version",
        }
        or primitive_spec.get("closed") is not True
        or primitive_spec.get("version") != "template-graph-primitives-v1"
        or primitive_spec.get("evaluation_order") != "profile-order-first-failure"
        or primitive_spec.get("canonical_equality") != "kernel-canonical-bytes"
        or not isinstance(primitive_spec.get("argument_types"), list)
        or not isinstance(primitive_spec.get("primitives"), list)
    ):
        return False
    argument_type_rows = cast(list[Any], primitive_spec["argument_types"])
    if argument_type_rows != TEMPLATE_ARGUMENT_TYPES:
        return False
    argument_types: dict[str, dict[str, Any]] = {}
    allowed_type_members = {
        "cardinality",
        "empty",
        "fresh",
        "id",
        "item",
        "kind",
        "values",
    }
    for row in argument_type_rows:
        if (
            not isinstance(row, dict)
            or not set(row) <= allowed_type_members
            or set(row) < {"id", "kind"}
            or not isinstance(row.get("id"), str)
            or not row["id"]
            or row["id"] in argument_types
            or row.get("kind")
            not in {
                "canonical-json",
                "derived-name",
                "enum",
                "model-fact-bindings",
                "non-empty-list",
                "role-name",
                "selector",
                "string",
                "string-list",
            }
        ):
            return False
        argument_types[row["id"]] = row
    charge_events = {
        row["event"] for row in cast(list[dict[str, str]], accounting["charge_rules"])
    }
    primitive_rows = cast(list[Any], primitive_spec["primitives"])
    primitives_by_id: dict[str, dict[str, Any]] = {}
    evaluation_kinds: set[str] = set()
    for primitive in primitive_rows:
        if (
            not isinstance(primitive, dict)
            or set(primitive)
            not in (
                {
                    "argument_members",
                    "argument_types",
                    "charges",
                    "evaluation",
                    "failure",
                    "id",
                    "result_effect",
                },
                {
                    "argument_members",
                    "argument_types",
                    "charges",
                    "evaluation",
                    "failure",
                    "id",
                    "result_effect",
                    "result_members",
                },
            )
            or not isinstance(primitive.get("id"), str)
            or not primitive["id"]
            or primitive["id"] in primitives_by_id
            or not isinstance(primitive.get("argument_members"), list)
            or not primitive["argument_members"]
            or len(primitive["argument_members"])
            != len(set(primitive["argument_members"]))
            or not isinstance(primitive.get("argument_types"), dict)
            or set(primitive["argument_types"]) != set(primitive["argument_members"])
            or any(
                type_id not in argument_types
                for type_id in primitive["argument_types"].values()
            )
            or primitive.get("result_effect")
            not in {"bind-derived", "bind-model-facts", "preserve-graph"}
            or primitive.get("failure")
            != {"mode": "judgment-diagnostic", "short_circuit": True}
            or not isinstance(primitive.get("charges"), list)
            or "judgment" not in primitive["charges"]
            or len(primitive["charges"]) != len(set(primitive["charges"]))
            or not set(primitive["charges"]) <= charge_events
            or not isinstance(primitive.get("evaluation"), dict)
            or not isinstance(primitive["evaluation"].get("kind"), str)
            or primitive["evaluation"]["kind"] in evaluation_kinds
            or not _template_primitive_evaluation_is_closed(primitive)
        ):
            return False
        result_members = primitive.get("result_members")
        evaluation_kind = primitive["evaluation"]["kind"]
        if (
            (primitive["result_effect"] == "bind-model-facts")
            != (result_members is not None)
            or (
                result_members is not None
                and (
                    not isinstance(result_members, list)
                    or not result_members
                    or len(result_members) != len(set(result_members))
                    or not all(
                        isinstance(member, str) and member for member in result_members
                    )
                )
            )
            or primitive["result_effect"]
            != TEMPLATE_PRIMITIVE_RESULT_EFFECTS.get(evaluation_kind)
            or primitive["charges"] != TEMPLATE_PRIMITIVE_CHARGES.get(evaluation_kind)
            or (
                evaluation_kind == "model-source-admission"
                and result_members
                != ["root_requirements", "resolved_packages", "source_symbols"]
            )
        ):
            return False
        primitives_by_id[primitive["id"]] = primitive
        evaluation_kinds.add(primitive["evaluation"]["kind"])
    if not primitives_by_id:
        return False
    operations_by_id: dict[str, dict[str, Any]] = {}
    for operation in operations:
        if (
            not isinstance(operation, dict)
            or set(operation)
            != {
                "effects",
                "id",
                "input",
                "law",
                "refusals",
                "resources",
                "result",
            }
            or not isinstance(operation.get("id"), str)
            or operation["id"] in operations_by_id
            or operation.get("input") != {"fact_kind": "template-graph"}
            or operation.get("result") != {"fact_kind": "template-graph"}
            or operation.get("effects") != []
            or operation.get("refusals") != ["reason-bound-diagnostic"]
            or not isinstance(operation.get("resources"), list)
            or "max_template_admission_steps" not in operation["resources"]
        ):
            return False
        law = operation.get("law")
        if (
            not isinstance(law, dict)
            or set(law) != {"operator", "primitive"}
            or law.get("operator") != operation["id"]
            or law.get("primitive") not in primitives_by_id
        ):
            return False
        operations_by_id[operation["id"]] = operation
    profiles = language.get("template_admission_profiles")
    diagnostics = {
        item.get("code")
        for item in cast(list[dict[str, Any]], language_bundle.get("diagnostics", []))
        if isinstance(item, dict)
    }
    if not isinstance(profiles, list) or len(profiles) != 1:
        return False
    profile = profiles[0]
    if not isinstance(profile, dict) or set(profile) != {
        "id",
        "judgments",
        "max_steps_path",
        "member_identity_domain",
        "member_roles",
        "resource_diagnostic",
        "structural_diagnostic",
    }:
        return False
    role_rows = profile.get("member_roles")
    judgments = profile.get("judgments")
    standalone_schema_kinds = {
        row.get("artifact_kind")
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for row in cast(list[dict[str, Any]], language.get(collection, []))
        if isinstance(row, dict) and "wire_schema_identity_domain" in row
    }
    artifact_schema_kinds = {
        row.get("artifact_kind")
        for row in cast(list[dict[str, Any]], language.get("artifact_contracts", []))
        if isinstance(row, dict)
    }
    schema_kinds = standalone_schema_kinds | artifact_schema_kinds
    if (
        not isinstance(role_rows, list)
        or not role_rows
        or not standalone_schema_kinds.isdisjoint(artifact_schema_kinds)
        or len({row.get("role") for row in role_rows if isinstance(row, dict)})
        != len(role_rows)
        or len({row.get("member_kind") for row in role_rows if isinstance(row, dict)})
        != len(role_rows)
        or any(
            not isinstance(row, dict)
            or set(row) != {"cardinality", "member_kind", "required_operations", "role"}
            or row.get("cardinality") not in role_cardinalities
            or not isinstance(row.get("role"), str)
            or not row["role"]
            or not isinstance(row.get("member_kind"), str)
            or not row["member_kind"]
            or row["member_kind"] not in schema_kinds
            or not isinstance(row.get("required_operations"), list)
            or any(
                operation not in operations_by_id
                for operation in row.get("required_operations", [])
            )
            or len(row.get("required_operations", []))
            != len(set(row.get("required_operations", [])))
            for row in role_rows
        )
        or not isinstance(judgments, list)
        or not judgments
        or not isinstance(profile.get("member_identity_domain"), str)
        or not profile["member_identity_domain"]
        or profile.get("max_steps_path") != accounting.get("limit_path")
        or profile.get("resource_diagnostic") != accounting.get("exhaustion_diagnostic")
        or profile.get("resource_diagnostic") not in diagnostics
        or profile.get("structural_diagnostic") not in diagnostics
    ):
        return False
    roles = {
        row["role"]
        for row in role_rows
        if isinstance(row, dict) and isinstance(row.get("role"), str)
    }
    model_source_roles = {
        row["role"]
        for row in role_rows
        if isinstance(row, dict)
        and row.get("member_kind") == "model-source-package"
        and isinstance(row.get("role"), str)
    }
    resolution_profiles = language.get("resolution_profiles")
    default_source_domains = (
        {
            row.get("source_identity_domain")
            for row in resolution_profiles
            if isinstance(row, dict)
            and row.get("default") is True
            and isinstance(row.get("source_identity_domain"), str)
            and row["source_identity_domain"]
        }
        if isinstance(resolution_profiles, list)
        else set()
    )
    if len(model_source_roles) != 1 or len(default_source_domains) != 1:
        return False
    try:
        limit = _exact_path_value(language_bundle, profile["max_steps_path"])
    except (KeyError, TypeError):
        return False
    if (
        not limit[0]
        or not isinstance(limit[1], int)
        or isinstance(limit[1], bool)
        or limit[1] < 1
    ):
        return False
    judgment_ids: set[str] = set()
    consulted_operations: set[str] = set()
    consulted_primitives: set[str] = set()
    role_operations: set[tuple[str, str]] = set()
    produced_derived: set[str] = set()
    model_source_identity_domains: set[str] = set()
    selector_members = {"inventory", "left", "right", "selector", "source", "target"}
    for judgment in judgments:
        if (
            not isinstance(judgment, dict)
            or set(judgment) != {"arguments", "diagnostic", "id", "operation"}
            or not isinstance(judgment.get("id"), str)
            or not judgment["id"]
            or judgment["id"] in judgment_ids
            or judgment.get("diagnostic") not in diagnostics
            or judgment.get("operation") not in operations_by_id
            or not isinstance(judgment.get("arguments"), dict)
        ):
            return False
        operation = operations_by_id[judgment["operation"]]
        law = cast(dict[str, Any], operation["law"])
        primitive = primitives_by_id[law["primitive"]]
        arguments = cast(dict[str, Any], judgment["arguments"])
        if not _template_primitive_arguments_are_closed(
            arguments,
            primitive,
            argument_types,
            roots=roots,
            roles=roles,
            produced_derived=produced_derived,
        ):
            return False
        if primitive["evaluation"]["kind"] == "content-identity":
            selector = arguments.get("selector")
            if (
                isinstance(selector, dict)
                and selector.get("root") == "role"
                and selector.get("name") in model_source_roles
                and isinstance(arguments.get("identity_domain"), str)
            ):
                model_source_identity_domains.add(arguments["identity_domain"])
        selectors: list[dict[str, Any]] = []
        for name, value in arguments.items():
            if name in selector_members:
                if not _template_selector_is_closed(value, roots, roles):
                    return False
                selectors.append(value)
            if name == "selectors":
                if (
                    not isinstance(value, list)
                    or not value
                    or not all(
                        _template_selector_is_closed(item, roots, roles)
                        for item in value
                    )
                ):
                    return False
                selectors.extend(value)
            if name.endswith("_path") and (
                not isinstance(value, list)
                or not all(isinstance(part, str) and part for part in value)
            ):
                return False
        for selector in selectors:
            if selector["root"] == "role":
                role_operations.add((selector["name"], judgment["operation"]))
            if (
                selector["root"] == "derived"
                and selector["name"] not in produced_derived
            ):
                return False
        if arguments.get("relation") not in {None, "equal", "subset"}:
            return False
        if arguments.get("outcome") not in {None, "admitted", "refused"}:
            return False
        role = arguments.get("role")
        if role is not None:
            if not isinstance(role, str) or role not in roles:
                return False
            role_operations.add((role, judgment["operation"]))
        evaluation = cast(dict[str, Any], primitive["evaluation"])
        if evaluation["kind"] == "model-source-admission":
            bindings = arguments.get("fact_bindings")
            result_members = primitive.get("result_members")
            if (
                not isinstance(bindings, list)
                or not bindings
                or not isinstance(result_members, list)
                or any(
                    not isinstance(binding, dict)
                    or set(binding) != {"result", "source"}
                    or binding.get("source") not in result_members
                    or not isinstance(binding.get("result"), str)
                    or not binding["result"]
                    for binding in bindings
                )
                or len({binding["source"] for binding in bindings}) != len(bindings)
                or len({binding["result"] for binding in bindings}) != len(bindings)
                or any(binding["result"] in produced_derived for binding in bindings)
            ):
                return False
            produced_derived.update(binding["result"] for binding in bindings)
        if evaluation["kind"] in {
            "concatenate-selections",
            "content-identity",
        }:
            result = arguments.get("result")
            if (
                not isinstance(result, str)
                or not result
                or result in produced_derived
                or (
                    evaluation["kind"] == "content-identity"
                    and (
                        not isinstance(arguments.get("identity_domain"), str)
                        or not arguments["identity_domain"]
                    )
                )
            ):
                return False
            produced_derived.add(result)
        judgment_ids.add(judgment["id"])
        consulted_operations.add(judgment["operation"])
        consulted_primitives.add(law["primitive"])
    required_role_operations = {
        (row["role"], operation)
        for row in role_rows
        if isinstance(row, dict)
        for operation in row["required_operations"]
    }
    return (
        consulted_operations == set(operations_by_id)
        and consulted_primitives == set(primitives_by_id)
        and required_role_operations <= role_operations
        and model_source_identity_domains == default_source_domains
    )
