"""Admission of resolved Model artifacts against their exact authority."""

from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from gda_balancing.domain.artifacts import (
    _identified_artifact,
    _verify_artifact,
)
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    packaged_authority_context,
)
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
)
from gda_balancing.domain.diagnostics import (
    reason_by_id,
)
from gda_balancing.domain.formula.notation import (
    FormulaNotationRefusal,
    FormulaPairRefusal,
    admit_formula_pair,
    formula_schema_version,
)
from gda_balancing.domain.formula.inference import (
    infer_formula_slot_parameter_contract as _infer_formula_slot_parameter_contract,
)
from gda_balancing.domain.formula.types import (
    formula_contract_contains as _formula_contract_contains,
    formula_contract_from_operation as _formula_contract_from_operation,
    formula_contract_matches as _formula_contract_matches,
    formula_contract_matches_operation as _formula_contract_matches_operation,
)
from gda_balancing.domain.authority.runtime_validation import (
    fixed_operation_value_contract,
    operation_literal_context_contract as _literal_context_contract,
)
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    admit_typed_value,
    language_structured_value_index,
)

from gda_balancing.domain.model._resolution import (
    CheckedModel,
    _formula_contexts,
    _formula_policy,
    _inventory_values,
    _language,
    _model_lowering,
    _operation_formula_slots,
    _operation_reference_node_ids,
    _resolution_profile,
    _selected_resolved_operation_coordinates,
)
from gda_balancing.domain.model._lowering import (
    _RuntimeProjectionResourceExhausted,
    _assignment_policy,
    _assignment_policy_by_role,
    _compile_initialization_programs,
    _composition_policy,
    _exact_operation_coordinate,
    _formula_operation_identity,
    _formula_symbol_dependencies,
    _package_lock,
    _project_concrete_operation_call_closure,
    _reachable_derived_formula_sites,
    _reachable_operation_formula_dependencies,
    _resolved_alias_rows,
    _resolved_call_sites,
    _resolved_event_reference_operand,
    _rir_semantic_identity,
    _runtime_projection,
    _runtime_projection_budget,
    _specialize_operation_formula_slots,
    _symbol_event_payload_contract,
    _symbol_external_fact_contract,
    _symbol_initialization_contract,
    _value_contract_matches,
    _value_policy_is_valid,
)


@dataclass(frozen=True)
class ResolvedModelAdmission:
    admitted: bool
    diagnostics: tuple[str, ...]


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
    if value_type == "canonical-value":
        try:
            canonical_bytes(cast(JsonValue, value))
        except (TypeError, ValueError):
            return False
        return True
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


def _resolved_entrypoint_graph_is_admitted(
    kernel: dict[str, Any],
    ldb: dict[str, Any],
    declarations: list[dict[str, Any]],
    selected_semantics: dict[str, Any],
    formulas: list[dict[str, Any]],
    formula_bindings: list[dict[str, Any]],
    entrypoints: Any,
) -> bool:
    """Independently rederive every identity and contract in the resolved call graph."""
    if not isinstance(entrypoints, list):
        return False
    assignment_policy = _assignment_policy(
        _model_lowering(ldb),
        expected_roles=set(
            cast(list[str], ldb["language"]["quantity"]["symbol_roles"])
        ),
    )
    assignment_by_role = _assignment_policy_by_role(assignment_policy)
    if any(
        not _value_policy_is_valid(declaration, assignment_policy)
        for declaration in declarations
    ):
        return False
    package_versions = {
        row["id"]: row["version"]
        for row in cast(list[dict[str, str]], selected_semantics["packages"])
    }
    operations = {
        (
            row["package"],
            package_versions[row["package"]],
            row["definition"]["id"],
        ): row
        for row in cast(list[dict[str, Any]], selected_semantics["operations"])
    }
    declarations_by_symbol = {
        (
            cast(dict[str, str], declaration["resolved_symbol"])["model"],
            cast(dict[str, str], declaration["resolved_symbol"])["module"],
            cast(dict[str, str], declaration["resolved_symbol"])["name"],
        ): declaration
        for declaration in declarations
    }
    formula_dependencies, operation_formula_dependencies = _formula_symbol_dependencies(
        formulas,
        formula_bindings,
    )
    domains = cast(
        dict[str, str],
        kernel["meta_format"]["runtime_program"]["invocation_contract"][
            "identity_domains"
        ],
    )
    structured_authority = language_structured_value_index(ldb, kernel=kernel)
    structured_resource_limit = cast(int, ldb["resources"]["max_rule_match_steps"])
    if any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str)
        for row in entrypoints
    ):
        return False
    ids = cast(list[str], [row["id"] for row in entrypoints])
    if len(ids) != len(entrypoints) or ids != sorted(ids) or len(ids) != len(set(ids)):
        return False
    for entrypoint in entrypoints:
        operation_ref = entrypoint.get("operation")
        if not isinstance(operation_ref, dict) or not all(
            isinstance(operation_ref.get(member), str)
            for member in ("package", "version", "id")
        ):
            return False
        exact_operation_ref = cast(dict[str, str], operation_ref)
        operation_row = operations.get(
            (
                exact_operation_ref["package"],
                exact_operation_ref["version"],
                exact_operation_ref["id"],
            )
        )
        if operation_row is None:
            return False
        exact_operation = _exact_operation_coordinate(operation_row, package_versions)
        if operation_ref != exact_operation:
            return False
        operation = cast(dict[str, Any], operation_row["definition"])
        formal_ports = cast(list[dict[str, Any]], operation["inputs"])
        arguments = entrypoint.get("arguments")
        if not isinstance(arguments, list) or len(arguments) != len(formal_ports):
            return False
        aliases: dict[str, list[tuple[str, str]]] = {}
        scenario_targets: dict[str, dict[str, JsonValue]] = {}
        event_payload_targets: dict[str, dict[str, JsonValue]] = {}
        event_reference_targets: dict[str, dict[str, JsonValue]] = {}
        external_fact_targets: dict[str, dict[str, JsonValue]] = {}
        initializers: dict[str, dict[str, JsonValue]] = {}
        expected_arguments: list[dict[str, JsonValue]] = []

        def record_formula_dependency(
            dependency_symbol: dict[str, JsonValue],
        ) -> bool:
            dependency_key = (
                cast(str, dependency_symbol["model"]),
                cast(str, dependency_symbol["module"]),
                cast(str, dependency_symbol["name"]),
            )
            dependency = declarations_by_symbol.get(dependency_key)
            if dependency is None:
                return False
            dependency_body = cast(
                dict[str, JsonValue],
                {
                    "kind": "symbol",
                    "symbol": dependency_symbol,
                },
            )
            dependency_identity = content_identity(
                domains["actual_operand"],
                dependency_body,
            )
            dependency_target, dependency_initializer = _symbol_initialization_contract(
                dependency,
                assignment_policy,
                dependency_symbol,
                dependency_identity,
            )
            if (
                dependency_target is None
                and dependency_initializer is None
                and dependency.get("role") != "derived"
            ):
                return False
            if dependency_target is not None:
                previous_target = scenario_targets.get(dependency_identity)
                if previous_target is not None and previous_target != dependency_target:
                    return False
                scenario_targets[dependency_identity] = dependency_target
            event_payload_target = _symbol_event_payload_contract(
                dependency,
                assignment_policy,
                dependency_symbol,
                dependency_identity,
            )
            if event_payload_target is not None:
                previous_payload_target = event_payload_targets.get(dependency_identity)
                if (
                    previous_payload_target is not None
                    and previous_payload_target != event_payload_target
                ):
                    return False
                event_payload_targets[dependency_identity] = event_payload_target
            external_fact_target = _symbol_external_fact_contract(
                dependency,
                assignment_policy,
                dependency_symbol,
                dependency_identity,
            )
            if external_fact_target is not None:
                previous_external_target = external_fact_targets.get(
                    dependency_identity
                )
                if (
                    previous_external_target is not None
                    and previous_external_target != external_fact_target
                ):
                    return False
                external_fact_targets[dependency_identity] = external_fact_target
            if dependency_initializer is not None:
                previous_initializer = initializers.get(dependency_identity)
                if (
                    previous_initializer is not None
                    and previous_initializer != dependency_initializer
                ):
                    return False
                initializers[dependency_identity] = dependency_initializer
            return True

        for formal, argument in zip(formal_ports, arguments, strict=True):
            if not isinstance(argument, dict):
                return False
            formal_body = cast(
                JsonValue,
                {"operation": exact_operation, "name": formal["id"]},
            )
            expected_port = {
                "identity": content_identity(domains["formal_port"], formal_body),
                "operation": exact_operation,
                "name": formal["id"],
            }
            operand = argument.get("operand")
            if not isinstance(operand, dict):
                return False
            if operand.get("kind") == "symbol":
                symbol = operand.get("symbol")
                if not isinstance(symbol, dict) or not all(
                    isinstance(symbol.get(member), str)
                    for member in ("model", "module", "name")
                ):
                    return False
                exact_symbol = cast(dict[str, str], symbol)
                declaration = declarations_by_symbol.get(
                    (
                        exact_symbol["model"],
                        exact_symbol["module"],
                        exact_symbol["name"],
                    )
                )
                if declaration is None or not _value_contract_matches(
                    declaration, formal
                ):
                    return False
                access = formal["access"]
                role = cast(str, declaration["role"])
                if access not in assignment_by_role[role]["entrypoint_operand_access"]:
                    return False
                operand_body = cast(
                    dict[str, JsonValue],
                    {"kind": "symbol", "symbol": symbol},
                )
                operand_identity = content_identity(
                    domains["actual_operand"], cast(JsonValue, operand_body)
                )
                expected_operand: dict[str, JsonValue] = {
                    **operand_body,
                    "identity": operand_identity,
                }
                aliases.setdefault(operand_identity, []).append(
                    (cast(str, formal["id"]), access)
                )
                target, initializer = _symbol_initialization_contract(
                    declaration,
                    assignment_policy,
                    cast(dict[str, JsonValue], symbol),
                    operand_identity,
                )
                if target is not None:
                    previous = scenario_targets.get(operand_identity)
                    if previous is not None and previous != target:
                        return False
                    scenario_targets[operand_identity] = target
                event_payload_target = _symbol_event_payload_contract(
                    declaration,
                    assignment_policy,
                    cast(dict[str, JsonValue], symbol),
                    operand_identity,
                )
                if event_payload_target is not None:
                    previous_payload_target = event_payload_targets.get(
                        operand_identity
                    )
                    if (
                        previous_payload_target is not None
                        and previous_payload_target != event_payload_target
                    ):
                        return False
                    event_payload_targets[operand_identity] = event_payload_target
                external_fact_target = _symbol_external_fact_contract(
                    declaration,
                    assignment_policy,
                    cast(dict[str, JsonValue], symbol),
                    operand_identity,
                )
                if external_fact_target is not None:
                    previous_external_target = external_fact_targets.get(
                        operand_identity
                    )
                    if (
                        previous_external_target is not None
                        and previous_external_target != external_fact_target
                    ):
                        return False
                    external_fact_targets[operand_identity] = external_fact_target
                if initializer is not None:
                    previous_initializer = initializers.get(operand_identity)
                    if (
                        previous_initializer is not None
                        and previous_initializer != initializer
                    ):
                        return False
                    initializers[operand_identity] = initializer
                if role == "derived":
                    resolved_key = (
                        exact_symbol["model"],
                        exact_symbol["module"],
                        exact_symbol["name"],
                    )
                    for dependency_symbol in formula_dependencies.get(resolved_key, []):
                        if not record_formula_dependency(dependency_symbol):
                            return False
            elif operand.get("kind") == "literal":
                value = operand.get("value")
                if isinstance(value, dict):
                    try:
                        admitted_value = admit_typed_value(
                            value,
                            authority=structured_authority,
                            resource_limit=structured_resource_limit,
                        )
                    except StructuredValueFault:
                        return False
                    if admitted_value != value:
                        return False
                context_type = _literal_context_contract(
                    value,
                    formal,
                    kernel,
                    selected_semantics,
                )
                if formal["access"] != "read" or context_type is None:
                    return False
                operand_body = {
                    "kind": "literal",
                    "value": value,
                    "context_type": context_type,
                }
                expected_operand = {
                    **operand_body,
                    "identity": content_identity(
                        domains["actual_operand"], cast(JsonValue, operand_body)
                    ),
                }
            elif operand.get("kind") == "event-reference":
                event_reference = _resolved_event_reference_operand(
                    cast(dict[str, Any], operand),
                    formal,
                    kernel,
                    domains,
                )
                if event_reference is None:
                    return False
                expected_operand, operand_identity, reference_contract = event_reference
                aliases.setdefault(operand_identity, []).append(
                    (cast(str, formal["id"]), cast(str, formal["access"]))
                )
                name = cast(str, reference_contract["name"])
                previous_reference = event_reference_targets.get(name)
                if (
                    previous_reference is not None
                    and previous_reference != reference_contract
                ):
                    return False
                event_reference_targets[name] = reference_contract
            else:
                return False
            expected_arguments.append(
                cast(
                    dict[str, JsonValue],
                    {
                        "port": expected_port,
                        "operand": expected_operand,
                        "access": formal["access"],
                    },
                )
            )
        try:
            event_formula_dependencies = _reachable_operation_formula_dependencies(
                (
                    exact_operation["package"],
                    exact_operation["version"],
                    exact_operation["id"],
                ),
                operations,
                operation_formula_dependencies,
                operation_node_ids=_operation_reference_node_ids(kernel),
            )
        except ValueError:
            return False
        if not all(
            record_formula_dependency(dependency_symbol)
            for dependency_symbol in event_formula_dependencies
        ):
            return False
        try:
            expected_aliases = _resolved_alias_rows(operation, aliases)
        except ValueError:
            return False
        if arguments != expected_arguments or entrypoint.get("aliases") != (
            expected_aliases
        ):
            return False
        result = entrypoint.get("result")
        if not isinstance(result, dict):
            return False
        if result.get("kind") == "discard":
            if operation["result"]["discardable"] is not True:
                return False
            result_body = cast(dict[str, JsonValue], {"kind": "discard"})
        elif result.get("kind") == "symbol":
            result_symbol = result.get("symbol")
            if not isinstance(result_symbol, dict) or not all(
                isinstance(result_symbol.get(member), str)
                for member in ("model", "module", "name")
            ):
                return False
            exact_result_symbol = cast(dict[str, str], result_symbol)
            result_declaration = declarations_by_symbol.get(
                (
                    exact_result_symbol["model"],
                    exact_result_symbol["module"],
                    exact_result_symbol["name"],
                )
            )
            if (
                result_declaration is None
                or assignment_by_role[cast(str, result_declaration.get("role"))][
                    "entrypoint_result"
                ]
                is not True
                or not _value_contract_matches(result_declaration, operation["result"])
            ):
                return False
            result_body = cast(
                dict[str, JsonValue],
                {"kind": "symbol", "symbol": result_symbol},
            )
        else:
            return False
        expected_result = {
            **result_body,
            "identity": content_identity(domains["result"], result_body),
        }
        entrypoint_body = cast(
            dict[str, JsonValue],
            {
                "id": entrypoint["id"],
                "operation": exact_operation,
                "arguments": expected_arguments,
                "aliases": cast(JsonValue, expected_aliases),
                "result": expected_result,
                "effects": operation["effects"],
                "refusals": operation["refusals"],
                "resource_bounds": operation["resource_bounds"],
                "scenario_input_contract": {
                    "initializers": sorted(
                        initializers.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    ),
                    "targets": sorted(
                        scenario_targets.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    ),
                },
                "event_local_payload_contract": {
                    "targets": sorted(
                        event_payload_targets.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    ),
                    "event_references": sorted(
                        event_reference_targets.values(),
                        key=lambda row: cast(str, row["name"]),
                    ),
                },
                "external_fact_contract": {
                    "targets": sorted(
                        external_fact_targets.values(),
                        key=lambda row: cast(str, row["target_identity"]),
                    )
                },
            },
        )
        expected_entrypoint = {
            **entrypoint_body,
            "identity": content_identity(domains["entrypoint"], entrypoint_body),
        }
        if entrypoint != expected_entrypoint:
            return False
    return True


def _formula_program_graph_is_admitted(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    declarations: list[dict[str, Any]],
    formulas: list[Any],
    bindings: Any,
    entrypoints: Any,
    selected_semantics: Any,
) -> bool:
    try:
        policy = _formula_policy(language_bundle)
        domains = cast(dict[str, str], policy["identity_domains"])
        actual_operand_domain = cast(
            str,
            kernel["meta_format"]["runtime_program"]["invocation_contract"][
                "identity_domains"
            ]["actual_operand"],
        )
        boolean_contract = cast(
            dict[str, Any],
            kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
                "kernel-boolean"
            ],
        )
        boolean_type = cast(dict[str, str], boolean_contract["type"])
        admitted_boolean_contract = {
            "type_identity": {
                "package": boolean_type["package"],
                "version": boolean_type["version"],
                "symbol": boolean_type["id"],
            },
            **{
                member: boolean_contract[member]
                for member in (
                    "representation",
                    "kind",
                    "unit",
                    "domain",
                    "numeric_policy",
                )
            },
        }
        formula_contexts = _formula_contexts(language_bundle)
    except (KeyError, TypeError, ValueError):
        return False
    if (
        not isinstance(bindings, list)
        or not isinstance(entrypoints, list)
        or not isinstance(selected_semantics, dict)
        or not isinstance(selected_semantics.get("operations"), list)
    ):
        return False
    declarations_by_symbol = {
        (
            cast(dict[str, str], declaration["resolved_symbol"])["module"],
            cast(dict[str, str], declaration["resolved_symbol"])["name"],
        ): declaration
        for declaration in declarations
    }
    formulas_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for formula in formulas:
        if (
            not isinstance(formula, dict)
            or set(formula)
            != {
                "module",
                "id",
                "parameters",
                "result",
                "body",
                "expression",
                "closure",
                "identity",
            }
            or not isinstance(formula.get("module"), str)
            or not isinstance(formula.get("id"), str)
            or not isinstance(formula.get("parameters"), list)
            or not isinstance(formula.get("result"), dict)
            or not isinstance(formula.get("body"), dict)
            or not isinstance(formula.get("expression"), str)
            or not isinstance(formula.get("closure"), dict)
        ):
            return False
        formula_body = {
            key: value
            for key, value in formula.items()
            if key not in {"identity", "expression"}
        }
        if formula.get("identity") != content_identity(
            domains["declaration"], cast(JsonValue, formula_body)
        ):
            return False
        parameter_ids = [
            cast(str, parameter.get("id"))
            for parameter in formula["parameters"]
            if isinstance(parameter, dict)
        ]
        if (
            len(parameter_ids) != len(formula["parameters"])
            or parameter_ids != sorted(parameter_ids)
            or len(parameter_ids) != len(set(parameter_ids))
        ):
            return False
        key = (formula["module"], formula["id"])
        if key in formulas_by_key:
            return False
        formulas_by_key[key] = formula
    if list(formulas_by_key) != sorted(formulas_by_key):
        return False

    operations_by_coordinate: dict[tuple[str, str, str], dict[str, Any]] = {
        (
            cast(str, row["package"]),
            cast(str, definition["version"]),
            cast(str, definition["id"]),
        ): cast(dict[str, Any], definition)
        for row in selected_semantics["operations"]
        if isinstance(row, dict)
        and isinstance((definition := row.get("definition")), dict)
        and isinstance(row.get("package"), str)
        and isinstance(definition.get("version"), str)
        and isinstance(definition.get("id"), str)
    }
    dependency_keys: dict[tuple[str, str], list[tuple[str, str]]] = {}
    operation_dependencies_by_key: dict[
        tuple[str, str], list[tuple[str, dict[str, Any]]]
    ] = {}
    formula_operation_roots: set[tuple[str, str, str]] = set()
    concrete_operation_calls: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for key, formula in formulas_by_key.items():
        parameters = {parameter["id"]: parameter for parameter in formula["parameters"]}
        locals_by_id: dict[str, dict[str, Any]] = {}
        nodes = formula["body"].get("nodes")
        result_operand = formula["body"].get("result")
        if (
            set(formula["body"]) != {"nodes", "result"}
            or not isinstance(nodes, list)
            or not isinstance(result_operand, dict)
            or len(nodes) > policy["max_nodes_per_formula"]
        ):
            return False
        dependency_keys[key] = []
        operation_dependencies_by_key[key] = []

        def operand_contract(operand: Any) -> dict[str, Any] | None:
            if not isinstance(operand, dict):
                return None
            body = {
                name: value for name, value in operand.items() if name != "identity"
            }
            if operand.get("identity") != content_identity(
                actual_operand_domain, cast(JsonValue, body)
            ):
                return None
            if operand.get("kind") == "parameter":
                return parameters.get(cast(str, operand.get("parameter")))
            if operand.get("kind") == "local":
                return locals_by_id.get(cast(str, operand.get("local")))
            if operand.get("kind") == "symbol":
                symbol = operand.get("resolved_symbol")
                if not isinstance(symbol, dict):
                    return None
                return declarations_by_symbol.get(
                    (
                        cast(str, symbol.get("module")),
                        cast(str, symbol.get("name")),
                    )
                )
            if operand.get("kind") == "literal":
                return cast(dict[str, Any], formula.get("result"))
            return None

        for node in nodes:
            if not isinstance(node, dict) or node.get("id") in locals_by_id:
                return False
            node_body = {
                name: value for name, value in node.items() if name != "identity"
            }
            if node.get("identity") != content_identity(
                domains["expression_node"], cast(JsonValue, node_body)
            ):
                return False
            if node.get("node") == "formula-call":
                if set(node) != {
                    "id",
                    "node",
                    "formula",
                    "arguments",
                    "result",
                    "identity",
                }:
                    return False
                formula_ref = node.get("formula")
                if not isinstance(formula_ref, dict):
                    return False
                target_key = (
                    cast(str, formula_ref.get("module")),
                    cast(str, formula_ref.get("id")),
                )
                called = formulas_by_key.get(target_key)
                if (
                    called is None
                    or formula_ref.get("identity") != called.get("identity")
                    or node.get("result") != called.get("result")
                ):
                    return False
                called_parameters = {
                    parameter["id"]: parameter for parameter in called["parameters"]
                }
                arguments = node.get("arguments")
                if not isinstance(arguments, list):
                    return False
                argument_ids = [
                    cast(str, argument.get("parameter"))
                    for argument in arguments
                    if isinstance(argument, dict)
                ]
                if (
                    len(argument_ids) != len(arguments)
                    or argument_ids != sorted(argument_ids)
                    or len(argument_ids) != len(set(argument_ids))
                    or set(argument_ids) != set(called_parameters)
                ):
                    return False
                for argument in arguments:
                    if (
                        set(argument) != {"parameter", "operand"}
                        or (contract := operand_contract(argument.get("operand")))
                        is None
                        or not _formula_contract_matches(
                            contract,
                            called_parameters[argument["parameter"]],
                        )
                    ):
                        return False
                dependency_keys[key].append(cast(tuple[str, str], target_key))
            elif node.get("node") == "operation-call":
                if set(node) != {
                    "id",
                    "node",
                    "operation",
                    "arguments",
                    "result",
                    "identity",
                }:
                    return False
                operation_ref = node.get("operation")
                if not isinstance(operation_ref, dict):
                    return False
                coordinate = (
                    cast(str, operation_ref.get("package")),
                    cast(str, operation_ref.get("version")),
                    cast(str, operation_ref.get("id")),
                )
                operation = operations_by_coordinate.get(coordinate)
                if (
                    operation is None
                    or operation.get("purity") != "pure"
                    or operation.get("operation_kind") != "pure-expression"
                    or operation.get("effects") != []
                    or not _formula_contract_matches_operation(
                        cast(dict[str, Any], node["result"]),
                        cast(dict[str, Any], operation["result"]),
                    )
                ):
                    return False
                if operation_ref.get("identity") != _formula_operation_identity(
                    domains, coordinate[0], coordinate[1], coordinate[2]
                ):
                    return False
                ports = {
                    port["id"]: port
                    for port in operation["inputs"]
                    if isinstance(port, dict)
                }
                arguments = node.get("arguments")
                if not isinstance(arguments, list):
                    return False
                port_ids = [
                    cast(str, argument.get("port"))
                    for argument in arguments
                    if isinstance(argument, dict)
                ]
                if (
                    len(port_ids) != len(arguments)
                    or port_ids != sorted(port_ids)
                    or len(port_ids) != len(set(port_ids))
                    or set(port_ids) != set(ports)
                ):
                    return False
                call_arguments: dict[str, dict[str, Any]] = {}
                known_call_arguments: dict[str, Any] = {}
                for argument in arguments:
                    if (
                        set(argument) != {"port", "operand"}
                        or (contract := operand_contract(argument.get("operand")))
                        is None
                    ):
                        return False
                    port_id = cast(str, argument["port"])
                    if not _formula_contract_matches_operation(
                        contract, ports[port_id]
                    ):
                        return False
                    call_arguments[port_id] = contract
                    operand = cast(dict[str, Any], argument["operand"])
                    if operand.get("kind") == "literal":
                        known_call_arguments[port_id] = operand.get("value")
                operation_dependencies_by_key[key].append(
                    (cast(str, operation_ref["identity"]), operation)
                )
                formula_operation_roots.add(coordinate)
                concrete_operation_calls.setdefault(coordinate, []).append(
                    {
                        "arguments": call_arguments,
                        "known_arguments": known_call_arguments,
                        "result": node["result"],
                    }
                )
            elif node.get("node") == "conditional":
                if set(node) != {
                    "id",
                    "node",
                    "condition",
                    "when_true",
                    "when_false",
                    "result",
                    "identity",
                }:
                    return False
                condition_contract = operand_contract(node.get("condition"))
                true_contract = operand_contract(node.get("when_true"))
                false_contract = operand_contract(node.get("when_false"))
                if (
                    condition_contract is None
                    or any(
                        condition_contract.get(member)
                        != admitted_boolean_contract[member]
                        for member in admitted_boolean_contract
                    )
                    or true_contract is None
                    or false_contract is None
                    or not _formula_contract_matches(true_contract, false_contract)
                    or not isinstance(node.get("result"), dict)
                    or not _formula_contract_matches(
                        true_contract,
                        cast(dict[str, Any], node["result"]),
                    )
                ):
                    return False
            else:
                return False
            locals_by_id[cast(str, node["id"])] = cast(dict[str, Any], node["result"])
        result_contract = operand_contract(result_operand)
        if result_contract is None or not _formula_contract_matches(
            result_contract, formula["result"]
        ):
            return False

    visiting: set[tuple[str, str]] = set()
    closed: set[tuple[str, str]] = set()

    def acyclic(key: tuple[str, str]) -> bool:
        if key in visiting:
            return False
        if key in closed:
            return True
        visiting.add(key)
        if not all(acyclic(dependency) for dependency in dependency_keys[key]):
            return False
        visiting.remove(key)
        closed.add(key)
        return True

    if not all(acyclic(key) for key in formulas_by_key):
        return False
    for key, formula in formulas_by_key.items():
        dependency_formulas = [formulas_by_key[item] for item in dependency_keys[key]]
        expected_formula_dependencies = {
            cast(str, dependency["identity"]) for dependency in dependency_formulas
        }
        expected_operation_dependencies: set[str] = set()
        expected_refusals: set[str] = set()
        expected_steps = (
            len(dependency_formulas)
            + sum(
                node.get("node") == "conditional"
                for node in cast(list[dict[str, Any]], formula["body"]["nodes"])
            )
        ) * cast(int, policy["resource_charge_per_node"])
        if cast(dict[str, Any], formula["body"]["result"])["kind"] != "local":
            expected_steps += cast(int, policy["resource_charge_per_node"])
        expected_termination = 1
        for dependency in dependency_formulas:
            closure = cast(dict[str, Any], dependency["closure"])
            expected_formula_dependencies.update(
                cast(list[str], closure["formula_dependencies"])
            )
            expected_operation_dependencies.update(
                cast(list[str], closure["operation_dependencies"])
            )
            expected_refusals.update(cast(list[str], closure["refusals"]))
            expected_steps += cast(
                int, cast(dict[str, Any], closure["resource_charge"])["max_steps"]
            )
            expected_termination = max(
                expected_termination,
                1 + cast(int, closure["termination_measure"]),
            )
        for operation_identity, operation in operation_dependencies_by_key[key]:
            expected_operation_dependencies.add(operation_identity)
            expected_refusals.update(cast(list[str], operation["refusals"]))
            expected_steps += cast(int, policy["resource_charge_per_node"]) + cast(
                int,
                cast(dict[str, Any], operation["resource_bounds"])["max_steps"],
            )
        expected_closure = {
            "formula_dependencies": sorted(expected_formula_dependencies),
            "operation_dependencies": sorted(expected_operation_dependencies),
            "refusals": sorted(expected_refusals),
            "resource_charge": {"max_steps": expected_steps},
            "termination_measure": expected_termination,
        }
        if formula["closure"] != expected_closure:
            return False

    bound_formula_keys: set[tuple[str, str]] = set()
    bound_derived_sites: set[tuple[str, str, str]] = set()
    selected_package_versions = {
        cast(str, row["id"]): cast(str, row["version"])
        for row in cast(list[dict[str, Any]], selected_semantics["packages"])
    }
    selected_slots: dict[
        tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any], str]
    ] = {}
    for entrypoint in cast(list[dict[str, Any]], entrypoints):
        operation_ref = entrypoint.get("operation")
        if not isinstance(operation_ref, dict):
            return False
        coordinate = (
            cast(str, operation_ref.get("package")),
            cast(str, operation_ref.get("version")),
            cast(str, operation_ref.get("id")),
        )
        operation = operations_by_coordinate.get(coordinate)
        arguments = entrypoint.get("arguments")
        if operation is None or not isinstance(arguments, list):
            return False
        call_arguments: dict[str, dict[str, Any]] = {}
        known_call_arguments: dict[str, Any] = {}
        for argument in arguments:
            if not isinstance(argument, dict) or not isinstance(
                argument.get("port"), dict
            ):
                return False
            port_id = cast(str, argument["port"].get("name"))
            operand = argument.get("operand")
            if not isinstance(operand, dict):
                return False
            if operand.get("kind") == "symbol":
                symbol = operand.get("symbol")
                if not isinstance(symbol, dict):
                    return False
                contract = declarations_by_symbol.get(
                    (
                        cast(str, symbol.get("module")),
                        cast(str, symbol.get("name")),
                    )
                )
            elif operand.get("kind") == "literal":
                context_type = operand.get("context_type")
                if not isinstance(context_type, dict):
                    return False
                try:
                    contract = cast(
                        dict[str, Any],
                        _formula_contract_from_operation(context_type),
                    )
                except ValueError:
                    return False
                value = operand.get("value")
                if isinstance(value, int) and not isinstance(value, bool):
                    contract = {
                        **contract,
                        "domain_kind": "closed-interval",
                        "domain": {"minimum": value, "maximum": value},
                    }
                known_call_arguments[port_id] = value
            elif operand.get("kind") == "event-reference":
                event_reference_contract = fixed_operation_value_contract(
                    kernel, "kernel-event-reference"
                )
                if event_reference_contract is None:
                    return False
                contract = cast(
                    dict[str, Any],
                    _formula_contract_from_operation(event_reference_contract),
                )
            else:
                return False
            if not isinstance(contract, dict):
                return False
            call_arguments[port_id] = contract
        concrete_operation_calls.setdefault(coordinate, []).append(
            {
                "arguments": call_arguments,
                "known_arguments": known_call_arguments,
            }
        )
    try:
        concrete_operation_calls = _project_concrete_operation_call_closure(
            operations_by_coordinate,
            concrete_operation_calls,
            kernel,
            language_bundle,
            cast(dict[str, Any], policy["notation_conversion"]),
            declarations_by_symbol,
        )
    except (KeyError, TypeError, ValueError):
        return False
    reachable_operations = _selected_resolved_operation_coordinates(
        cast(list[dict[str, Any]], entrypoints),
        cast(dict[str, Any], selected_semantics),
        _operation_reference_node_ids(kernel),
        formula_operation_roots,
    )
    for operation_row in cast(list[dict[str, Any]], selected_semantics["operations"]):
        package_id = cast(str, operation_row["package"])
        definition = cast(dict[str, Any], operation_row["definition"])
        coordinate = (
            package_id,
            selected_package_versions[package_id],
            cast(str, definition["id"]),
        )
        if coordinate not in reachable_operations:
            continue
        operation_identity = _formula_operation_identity(
            domains, coordinate[0], coordinate[1], coordinate[2]
        )
        for slot in _operation_formula_slots(definition):
            selected_slots[(*coordinate, cast(str, slot["id"]))] = (
                definition,
                slot,
                operation_identity,
            )
    bound_operation_slots: set[tuple[str, str, str, str]] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            return False
        binding_body = {
            key: value for key, value in binding.items() if key != "identity"
        }
        site = binding.get("site")
        formula_ref = binding.get("formula")
        arguments = binding.get("arguments")
        if (
            set(binding) != {"site", "formula", "arguments", "identity"}
            or not isinstance(site, dict)
            or not isinstance(formula_ref, dict)
            or set(formula_ref) != {"module", "id", "identity"}
            or not isinstance(arguments, list)
            or binding.get("identity")
            != content_identity(domains["binding"], cast(JsonValue, binding_body))
        ):
            return False
        site_body = {key: value for key, value in site.items() if key != "identity"}
        if site.get("identity") != content_identity(
            domains["evaluation_site"], cast(JsonValue, site_body)
        ):
            return False
        formula_key = (
            cast(str, formula_ref.get("module")),
            cast(str, formula_ref.get("id")),
        )
        bound_formula = formulas_by_key.get(formula_key)
        if bound_formula is None or formula_ref.get("identity") != bound_formula.get(
            "identity"
        ):
            return False
        parameters = {
            parameter["id"]: parameter for parameter in bound_formula["parameters"]
        }
        argument_ids = [
            cast(str, argument.get("parameter"))
            for argument in arguments
            if isinstance(argument, dict)
        ]
        if (
            len(argument_ids) != len(arguments)
            or argument_ids != sorted(argument_ids)
            or len(argument_ids) != len(set(argument_ids))
            or set(argument_ids) != set(parameters)
        ):
            return False
        if site.get("kind") == "derived-symbol":
            context = site.get("context")
            context_items = (
                tuple(sorted(context.items())) if isinstance(context, dict) else None
            )
            if (
                set(site) != {"kind", "context", "resolved_symbol", "identity"}
                or context_items
                not in {
                    tuple(sorted(formula_contexts["initialization"].items())),
                    tuple(sorted(formula_contexts["event"].items())),
                    tuple(sorted(formula_contexts["observation"].items())),
                }
                or not isinstance(site.get("resolved_symbol"), dict)
            ):
                return False
            resolved_symbol = cast(dict[str, str], site["resolved_symbol"])
            site_key = (
                cast(str, resolved_symbol.get("module")),
                cast(str, resolved_symbol.get("name")),
            )
            context_key = (
                *site_key,
                cast(str, cast(dict[str, Any], context)["phase"]),
            )
            declaration = declarations_by_symbol.get(site_key)
            if (
                declaration is None
                or declaration.get("role") != "derived"
                or context_key in bound_derived_sites
                or not _formula_contract_matches(
                    cast(dict[str, Any], bound_formula["result"]),
                    declaration,
                )
            ):
                return False
            bound_derived_sites.add(context_key)
            for argument in arguments:
                operand = argument.get("operand")
                if (
                    not isinstance(operand, dict)
                    or operand.get("kind") != "symbol"
                    or not isinstance(operand.get("resolved_symbol"), dict)
                ):
                    return False
                operand_body = {
                    key: value for key, value in operand.items() if key != "identity"
                }
                symbol = operand["resolved_symbol"]
                declaration = declarations_by_symbol.get(
                    (
                        cast(str, symbol.get("module")),
                        cast(str, symbol.get("name")),
                    )
                )
                if (
                    operand.get("identity")
                    != content_identity(
                        actual_operand_domain, cast(JsonValue, operand_body)
                    )
                    or declaration is None
                    or not _formula_contract_matches(
                        declaration, parameters[argument["parameter"]]
                    )
                ):
                    return False
        elif site.get("kind") == "operation-slot":
            if (
                set(site) != {"kind", "operation", "slot", "context", "identity"}
                or site.get("context") != formula_contexts["event"]
                or not isinstance(site.get("operation"), dict)
            ):
                return False
            operation_ref = cast(dict[str, Any], site["operation"])
            slot_key = (
                cast(str, operation_ref.get("package")),
                cast(str, operation_ref.get("version")),
                cast(str, operation_ref.get("id")),
                cast(str, site.get("slot")),
            )
            selected_slot = selected_slots.get(slot_key)
            if (
                selected_slot is None
                or slot_key in bound_operation_slots
                or set(operation_ref) != {"package", "version", "id", "identity"}
            ):
                return False
            operation, slot, operation_identity = selected_slot
            if operation_ref.get("identity") != operation_identity:
                return False
            slot_parameters = {
                cast(str, parameter["id"]): parameter
                for parameter in cast(list[dict[str, Any]], slot["parameters"])
            }
            concrete_calls = concrete_operation_calls.get(slot_key[:3], [])
            for argument in arguments:
                operand = argument.get("operand")
                if (
                    not isinstance(operand, dict)
                    or set(operand) != {"kind", "parameter", "identity"}
                    or operand.get("kind") != "slot-parameter"
                    or operand.get("parameter") not in slot_parameters
                ):
                    return False
                operand_body = {
                    key: value for key, value in operand.items() if key != "identity"
                }
                slot_parameter = slot_parameters[cast(str, operand["parameter"])]
                if operand.get("identity") != content_identity(
                    actual_operand_domain, cast(JsonValue, operand_body)
                ) or not _formula_contract_matches_operation(
                    parameters[argument["parameter"]],
                    slot_parameter,
                ):
                    return False
                for call in concrete_calls:
                    try:
                        actual_contract = _infer_formula_slot_parameter_contract(
                            operation,
                            slot_parameter,
                            call,
                            cast(dict[str, Any], policy["notation_conversion"]),
                        )
                    except (KeyError, TypeError, ValueError):
                        return False
                    if not _formula_contract_contains(
                        parameters[argument["parameter"]], actual_contract
                    ):
                        return False
            closure = cast(dict[str, Any], bound_formula["closure"])
            if (
                not _formula_contract_matches_operation(
                    cast(dict[str, Any], bound_formula["result"]),
                    cast(dict[str, Any], slot["result"]),
                )
                or not set(cast(list[str], closure["refusals"]))
                <= set(cast(list[str], slot["permitted_refusals"]))
                or cast(
                    int,
                    cast(dict[str, Any], closure["resource_charge"])["max_steps"],
                )
                > cast(int, slot["resource_bounds"]["max_steps"])
                or cast(int, closure["termination_measure"])
                > cast(int, slot["termination_measure"])
                or operation_identity
                in set(cast(list[str], closure["operation_dependencies"]))
                or any(
                    isinstance(call.get("result"), dict)
                    and not _formula_contract_contains(
                        cast(dict[str, Any], call["result"]),
                        cast(dict[str, Any], bound_formula["result"]),
                    )
                    for call in concrete_calls
                )
            ):
                return False
            bound_operation_slots.add(slot_key)
        else:
            return False
        bound_formula_keys.add(cast(tuple[str, str], formula_key))
    if bound_operation_slots != set(selected_slots):
        return False
    reachable = set(bound_formula_keys)
    pending = list(bound_formula_keys)
    while pending:
        key = pending.pop()
        for dependency in dependency_keys[key]:
            if dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)
    if reachable != set(formulas_by_key):
        return False
    reachable_derived_sites = _reachable_derived_formula_sites(
        declarations_by_symbol,
        cast(list[dict[str, Any]], formulas),
        cast(list[dict[str, Any]], bindings),
        cast(list[dict[str, Any]], entrypoints),
    )
    return bound_derived_sites == {
        (*site, phase)
        for site in reachable_derived_sites
        for phase in ("initialization", "event", "observation")
    }


def _formula_graph_is_admitted(
    kernel: dict[str, Any],
    language_bundle: dict[str, Any],
    declarations: list[dict[str, Any]],
    formulas: Any,
    bindings: Any,
    entrypoints: Any,
    selected_semantics: Any,
) -> bool:
    if isinstance(formulas, list) and any(
        isinstance(formula, dict)
        and isinstance(formula.get("body"), dict)
        and "nodes" in formula["body"]
        for formula in formulas
    ):
        return _formula_program_graph_is_admitted(
            kernel,
            language_bundle,
            declarations,
            formulas,
            bindings,
            entrypoints,
            selected_semantics,
        )
    try:
        policy = _formula_policy(language_bundle)
        domains = cast(dict[str, str], policy["identity_domains"])
        actual_operand_domain = cast(
            str,
            kernel["meta_format"]["runtime_program"]["invocation_contract"][
                "identity_domains"
            ]["actual_operand"],
        )
        formula_contexts = _formula_contexts(language_bundle)
    except (KeyError, TypeError, ValueError):
        return False
    if not isinstance(formulas, list) or not isinstance(bindings, list):
        return False
    declarations_by_symbol = {
        (
            cast(dict[str, str], declaration["resolved_symbol"])["module"],
            cast(dict[str, str], declaration["resolved_symbol"])["name"],
        ): declaration
        for declaration in declarations
    }
    formulas_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    formula_identities: set[str] = set()
    for formula in formulas:
        if not isinstance(formula, dict):
            return False
        body = {key: value for key, value in formula.items() if key != "identity"}
        formula_id = formula.get("id")
        module = formula.get("module")
        parameters = formula.get("parameters")
        result = formula.get("result")
        expression = formula.get("body")
        if (
            set(formula) != {"module", "id", "parameters", "result", "body", "identity"}
            or not isinstance(module, str)
            or not isinstance(formula_id, str)
            or not isinstance(parameters, list)
            or not isinstance(result, dict)
            or not isinstance(expression, dict)
            or expression.get("node") != "parameter"
            or set(expression) != {"node", "parameter"}
            or formula.get("identity")
            != content_identity(domains["declaration"], cast(JsonValue, body))
        ):
            return False
        parameter_ids = [
            cast(str, parameter.get("id"))
            for parameter in parameters
            if isinstance(parameter, dict)
        ]
        if (
            len(parameter_ids) != len(parameters)
            or parameter_ids != sorted(parameter_ids)
            or len(parameter_ids) != len(set(parameter_ids))
        ):
            return False
        parameter = next(
            (
                item
                for item in parameters
                if item.get("id") == expression.get("parameter")
            ),
            None,
        )
        if parameter is None or not _formula_contract_matches(parameter, result):
            return False
        key = (module, formula_id)
        identity = cast(str, formula["identity"])
        if key in formulas_by_key or identity in formula_identities:
            return False
        formulas_by_key[key] = formula
        formula_identities.add(identity)
    if list(formulas_by_key) != sorted(formulas_by_key):
        return False

    bound_formula_keys: set[tuple[str, str]] = set()
    bound_sites: set[tuple[str, str, str]] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            return False
        binding_body = {
            key: value for key, value in binding.items() if key != "identity"
        }
        site = binding.get("site")
        formula_ref = binding.get("formula")
        arguments = binding.get("arguments")
        context = site.get("context") if isinstance(site, dict) else None
        context_items = (
            tuple(sorted(context.items())) if isinstance(context, dict) else None
        )
        if (
            set(binding) != {"site", "formula", "arguments", "identity"}
            or not isinstance(site, dict)
            or set(site) != {"kind", "context", "resolved_symbol", "identity"}
            or site.get("kind") != "derived-symbol"
            or context_items
            not in {
                tuple(sorted(formula_contexts["initialization"].items())),
                tuple(sorted(formula_contexts["event"].items())),
                tuple(sorted(formula_contexts["observation"].items())),
            }
            or not isinstance(site.get("resolved_symbol"), dict)
            or not isinstance(formula_ref, dict)
            or set(formula_ref) != {"module", "id", "identity"}
            or not isinstance(arguments, list)
            or binding.get("identity")
            != content_identity(domains["binding"], cast(JsonValue, binding_body))
        ):
            return False
        resolved_symbol = cast(dict[str, str], site["resolved_symbol"])
        site_body = {key: value for key, value in site.items() if key != "identity"}
        if site.get("identity") != content_identity(
            domains["evaluation_site"], cast(JsonValue, site_body)
        ):
            return False
        site_key = (
            cast(str, resolved_symbol.get("module")),
            cast(str, resolved_symbol.get("name")),
        )
        context_key = (
            *site_key,
            cast(str, cast(dict[str, Any], context)["phase"]),
        )
        site_declaration = declarations_by_symbol.get(site_key)
        if (
            site_declaration is None
            or site_declaration.get("role") != "derived"
            or context_key in bound_sites
        ):
            return False
        bound_sites.add(context_key)
        formula_key = (
            cast(str, formula_ref.get("module")),
            cast(str, formula_ref.get("id")),
        )
        formula = formulas_by_key.get(formula_key)
        if (
            formula is None
            or formula_ref.get("identity") != formula.get("identity")
            or not _formula_contract_matches(
                cast(dict[str, Any], formula["result"]),
                site_declaration,
            )
        ):
            return False
        parameters = {
            parameter["id"]: parameter
            for parameter in cast(list[dict[str, Any]], formula["parameters"])
        }
        argument_ids = [
            cast(str, argument.get("parameter"))
            for argument in arguments
            if isinstance(argument, dict)
        ]
        if (
            len(argument_ids) != len(arguments)
            or argument_ids != sorted(argument_ids)
            or len(argument_ids) != len(set(argument_ids))
            or set(argument_ids) != set(parameters)
        ):
            return False
        for argument in cast(list[dict[str, Any]], arguments):
            operand = argument.get("operand")
            if (
                set(argument) != {"parameter", "operand"}
                or not isinstance(operand, dict)
                or set(operand) != {"kind", "resolved_symbol", "identity"}
                or operand.get("kind") != "symbol"
                or not isinstance(operand.get("resolved_symbol"), dict)
            ):
                return False
            operand_body = {
                "kind": "symbol",
                "resolved_symbol": operand["resolved_symbol"],
            }
            operand_symbol = cast(dict[str, str], operand["resolved_symbol"])
            operand_declaration = declarations_by_symbol.get(
                (
                    cast(str, operand_symbol.get("module")),
                    cast(str, operand_symbol.get("name")),
                )
            )
            if (
                operand.get("identity")
                != content_identity(
                    actual_operand_domain, cast(JsonValue, operand_body)
                )
                or operand_declaration is None
                or not _formula_contract_matches(
                    operand_declaration, parameters[argument["parameter"]]
                )
            ):
                return False
        bound_formula_keys.add(cast(tuple[str, str], formula_key))
    if [binding["identity"] for binding in bindings] != sorted(
        binding["identity"] for binding in bindings
    ) or bound_formula_keys != set(formulas_by_key):
        return False
    if not isinstance(entrypoints, list):
        return False
    reachable_derived_sites = _reachable_derived_formula_sites(
        declarations_by_symbol,
        cast(list[dict[str, Any]], formulas),
        cast(list[dict[str, Any]], bindings),
        cast(list[dict[str, Any]], entrypoints),
    )
    return bound_sites == {
        (*site, phase)
        for site in reachable_derived_sites
        for phase in ("initialization", "event", "observation")
    }


def _notation_operand_projection(operand: dict[str, Any]) -> dict[str, JsonValue]:
    kind = operand.get("kind")
    if kind == "symbol" and isinstance(operand.get("resolved_symbol"), dict):
        resolved = cast(dict[str, Any], operand["resolved_symbol"])
        return {
            "kind": "symbol",
            "module": cast(str, resolved["module"]),
            "symbol": cast(str, resolved["name"]),
        }
    members = {
        "parameter": "parameter",
        "local": "local",
        "literal": "value",
    }
    member = members.get(cast(str, kind))
    if member is None:
        raise ValueError("RIR Formula operand has no notation projection")
    return {"kind": cast(str, kind), member: cast(JsonValue, operand[member])}


def _rir_notation_body_projection(body: dict[str, Any]) -> dict[str, JsonValue]:
    nodes = body.get("nodes")
    result = body.get("result")
    if not isinstance(nodes, list) or not isinstance(result, dict):
        raise ValueError("RIR Formula body has no program projection")
    if (
        not nodes
        and result.get("kind") == "parameter"
        and isinstance(result.get("parameter"), str)
    ):
        return {
            "node": "parameter",
            "parameter": cast(str, result["parameter"]),
        }
    projected_nodes: list[dict[str, JsonValue]] = []
    for node in cast(list[dict[str, Any]], nodes):
        kind = node.get("node")
        projected: dict[str, JsonValue] = {
            "id": cast(str, node["id"]),
            "node": cast(str, kind),
        }
        if kind == "operation-call":
            operation = cast(dict[str, Any], node["operation"])
            projected["operation"] = {
                "package": cast(str, operation["package"]),
                "version": cast(str, operation["version"]),
                "id": cast(str, operation["id"]),
            }
            projected["arguments"] = cast(
                JsonValue,
                [
                    {
                        "port": cast(str, argument["port"]),
                        "operand": _notation_operand_projection(
                            cast(dict[str, Any], argument["operand"])
                        ),
                    }
                    for argument in cast(list[dict[str, Any]], node["arguments"])
                ],
            )
            projected["result"] = cast(JsonValue, node["result"])
        elif kind == "formula-call":
            formula = cast(dict[str, Any], node["formula"])
            projected["formula"] = {
                "module": cast(str, formula["module"]),
                "id": cast(str, formula["id"]),
            }
            projected["arguments"] = cast(
                JsonValue,
                [
                    {
                        "parameter": cast(str, argument["parameter"]),
                        "operand": _notation_operand_projection(
                            cast(dict[str, Any], argument["operand"])
                        ),
                    }
                    for argument in cast(list[dict[str, Any]], node["arguments"])
                ],
            )
        elif kind == "conditional":
            for member in ("condition", "when_true", "when_false"):
                projected[member] = _notation_operand_projection(
                    cast(dict[str, Any], node[member])
                )
        else:
            raise ValueError("RIR Formula node has no notation projection")
        projected_nodes.append(projected)
    return {
        "nodes": cast(JsonValue, projected_nodes),
        "result": _notation_operand_projection(result),
    }


def _formula_pairs_are_admitted(
    formulas: object,
    declarations: object,
    requirements: object,
    authority_context: AdmittedAuthorityContext,
) -> bool:
    if (
        not isinstance(formulas, list)
        or not isinstance(declarations, list)
        or not isinstance(requirements, list)
    ):
        return False
    by_module: dict[str, list[dict[str, Any]]] = {}
    for formula in formulas:
        if not isinstance(formula, dict) or not isinstance(formula.get("module"), str):
            return False
        by_module.setdefault(cast(str, formula["module"]), []).append(formula)
    declaration_modules = {
        cast(str, declaration["resolved_symbol"]["module"])
        for declaration in declarations
        if isinstance(declaration, dict)
        and isinstance(declaration.get("resolved_symbol"), dict)
        and isinstance(declaration["resolved_symbol"].get("module"), str)
    }
    modules = [
        {
            "id": module_id,
            "imports": [],
            "symbols": [
                declaration
                for declaration in declarations
                if isinstance(declaration, dict)
                and isinstance(declaration.get("resolved_symbol"), dict)
                and declaration["resolved_symbol"].get("module") == module_id
            ],
            "formulas": by_module.get(module_id, []),
        }
        for module_id in sorted(set(by_module) | declaration_modules)
    ]
    try:
        for module in modules:
            module_formulas = cast(list[dict[str, Any]], module["formulas"])
            for formula in module_formulas:
                body = formula.get("body")
                if not isinstance(body, dict):
                    return False
                admit_formula_pair(
                    {
                        "schema_version": formula_schema_version(authority_context),
                        "package_requirements": requirements,
                        "modules": modules,
                        "module": module,
                        "formula": formula,
                    },
                    authority_context,
                    canonical_body=cast(
                        dict[str, Any], _rir_notation_body_projection(body)
                    ),
                )
    except (
        FormulaPairRefusal,
        FormulaNotationRefusal,
        KeyError,
        TypeError,
        ValueError,
    ):
        return False
    return True


def _rir_formula_pairs_are_admitted(
    rir: dict[str, Any],
    lock: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
) -> bool:
    output_member = _model_lowering(authority_context.language_bundle).get(
        "output_member"
    )
    return _formula_pairs_are_admitted(
        rir.get("formulas"),
        rir.get(output_member) if isinstance(output_member, str) else None,
        lock.get("root_requirements"),
        authority_context,
    )


def _model_explanation_pairs_are_admitted(
    explanation: dict[str, Any],
    rir: dict[str, Any],
    lock: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
) -> bool:
    output_member = _model_lowering(authority_context.language_bundle).get(
        "output_member"
    )
    return _formula_pairs_are_admitted(
        explanation.get("formula_explanations"),
        rir.get(output_member) if isinstance(output_member, str) else None,
        lock.get("root_requirements"),
        authority_context,
    )


def admit_resolved_model(
    artifacts: dict[str, dict[str, Any]],
    *,
    authority_context: AdmittedAuthorityContext | None = None,
) -> ResolvedModelAdmission:
    """Admit a semantic artifact trio against the exact packaged authorities."""
    context = authority_context or packaged_authority_context()
    kernel = context.kernel
    ldb = context.language_bundle
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
    try:
        if rir.get("semantic_identity") != _rir_semantic_identity(
            ldb, cast(dict[str, JsonValue], rir)
        ):
            return ResolvedModelAdmission(False, diagnostic)
    except (KeyError, TypeError, ValueError):
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
        authority_context=context,
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
        expected_initialization_programs = _compile_initialization_programs(
            expected_runtime_projection,
            cast(list[dict[str, JsonValue]], rir.get("formulas")),
            cast(list[dict[str, JsonValue]], rir.get("formula_bindings")),
            _formula_policy(ldb),
        )
        expected_runtime_projection = _specialize_operation_formula_slots(
            expected_runtime_projection,
            cast(list[dict[str, JsonValue]], rir.get("formulas")),
            cast(list[dict[str, JsonValue]], rir.get("formula_bindings")),
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
        or rir.get("initialization_programs") != expected_initialization_programs
    ):
        return ResolvedModelAdmission(False, diagnostic)
    language = _language(ldb)
    rules = {rule["id"]: rule for rule in cast(list[dict[str, Any]], language["rules"])}
    try:
        terminal_kinds = {
            "quantity": rules[lowering["rule_chain"][-1]["rule"]]["conclusion"][
                "fact_kind"
            ],
            "nominal-structured": rules[lowering["structured_rule_chain"][-1]["rule"]][
                "conclusion"
            ]["fact_kind"],
        }
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
        terminal_kind = terminal_kinds[
            "nominal-structured"
            if isinstance(item, dict) and item.get("value_kind") == "nominal-structured"
            else "quantity"
        ]
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
    try:
        if not _formula_graph_is_admitted(
            kernel,
            ldb,
            cast(list[dict[str, Any]], declarations),
            rir.get("formulas"),
            rir.get("formula_bindings"),
            rir.get("entrypoints"),
            rir.get("selected_semantics"),
        ):
            return ResolvedModelAdmission(False, diagnostic)
        if not _rir_formula_pairs_are_admitted(rir, lock, context):
            return ResolvedModelAdmission(False, diagnostic)
        if not _resolved_entrypoint_graph_is_admitted(
            kernel,
            ldb,
            cast(list[dict[str, Any]], declarations),
            cast(dict[str, Any], expected_runtime_projection),
            cast(list[dict[str, Any]], rir.get("formulas")),
            cast(list[dict[str, Any]], rir.get("formula_bindings")),
            rir.get("entrypoints"),
        ):
            return ResolvedModelAdmission(False, diagnostic)
        if rir.get("call_sites") != _resolved_call_sites(
            kernel,
            cast(dict[str, Any], expected_runtime_projection),
            _composition_policy(_model_lowering(ldb)),
        ):
            return ResolvedModelAdmission(False, diagnostic)
    except (KeyError, TypeError, ValueError):
        return ResolvedModelAdmission(False, diagnostic)
    expected_resolved = _identified_artifact(
        ldb,
        "resolved-model",
        {
            "kernel_identity": cast(str, kernel["content_identity"]),
            "language_bundle_identity": cast(str, ldb["content_identity"]),
            "package_lock_identity": cast(str, lock["content_identity"]),
            "rir_content_identity": cast(str, rir["content_identity"]),
            "rir_semantic_identity": cast(str, rir["semantic_identity"]),
        },
    )
    if resolved != expected_resolved:
        return ResolvedModelAdmission(False, diagnostic)
    return ResolvedModelAdmission(True, ())
