"""Development adapter from Package operation vectors to the production Runtime."""

from __future__ import annotations

from typing import Any, cast

from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.canonical import JsonValue, content_identity
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import (
    CheckedExperiment,
    derive_scenario_program_requirements,
)
from gda_balancing.domain.formula.notation import render_formula_body
from gda_balancing.domain.model import CheckedModel, check_model_source_value
from gda_balancing.domain.model import compile_checked_model
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    RuntimeRefusalOutcome,
    evaluate_experiment,
)


def _type_coordinate(contract: dict[str, Any]) -> tuple[str, str, str]:
    type_identity = contract.get("type")
    if not isinstance(type_identity, dict) or not all(
        isinstance(type_identity.get(member), str)
        for member in ("package", "version", "id")
    ):
        raise ValueError("operation vector uses an unimportable port type")
    return (
        cast(str, type_identity["package"]),
        cast(str, type_identity["version"]),
        cast(str, type_identity["id"]),
    )


def _model_symbol(
    name: str,
    contract: dict[str, Any],
    *,
    alias: str,
    role: str,
    minimum: int,
    maximum: int,
) -> dict[str, Any]:
    symbol = {
        "symbol": name,
        "type": alias,
        "role": role,
        "value_policy": {"mode": "none" if role == "output" else "experiment-required"},
    }
    if contract.get("value_kind") == "nominal-structured":
        return symbol
    if (
        contract.get("kind") != "scalar"
        or contract.get("representation") != "Int"
        or contract.get("numeric_policy") != "exact-int64"
    ):
        raise ValueError("operation vector adapter requires scalar or structured ports")
    return symbol | {
        "representation": "Int",
        "kind": "scalar",
        "unit": contract["unit"],
        "domain_kind": "closed-interval",
        "domain": {"minimum": minimum, "maximum": maximum},
        "numeric_policy": "exact-int64",
    }


def _operation_owner(language: dict[str, Any], operation_id: str) -> tuple[str, str]:
    owners = [
        (package["id"], package["version"])
        for package in language["packages"]
        if operation_id in package["exports"]["operations"]
    ]
    if len(owners) != 1:
        raise ValueError("operation vector owner is not unique")
    return cast(tuple[str, str], owners[0])


def _formula_contract(
    contract: dict[str, Any],
    aliases: dict[tuple[str, str, str], str],
    *,
    minimum: int,
    maximum: int,
) -> dict[str, Any]:
    coordinate = _type_coordinate(contract)
    if (
        contract.get("kind") != "scalar"
        or contract.get("representation") != "Int"
        or contract.get("numeric_policy") != "exact-int64"
    ):
        raise ValueError("operation Formula slot is not exact-int64 scalar")
    return {
        "type": aliases[coordinate],
        "representation": "Int",
        "kind": "scalar",
        "unit": contract["unit"],
        "domain_kind": "closed-interval",
        "domain": {"minimum": minimum, "maximum": maximum},
        "numeric_policy": "exact-int64",
    }


def _reachable_operations(
    root: dict[str, Any], operations: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(operation: dict[str, Any], body: list[dict[str, Any]]) -> None:
        if operation["id"] not in seen:
            seen.add(operation["id"])
            selected.append(operation)
        for instruction in body:
            if instruction["node"] == "guard-block":
                visit(operation, cast(list[dict[str, Any]], instruction["body"]))
            elif instruction["node"] in {"invoke", "schedule"}:
                visit(
                    operations[instruction["operation"]["id"]],
                    operations[instruction["operation"]["id"]]["body"],
                )

    visit(root, cast(list[dict[str, Any]], root["body"]))
    return selected


def _formula_sources(
    context: AdmittedAuthorityContext,
    root: dict[str, Any],
    aliases: dict[tuple[str, str, str], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    language = cast(dict[str, Any], context.language_bundle["language"])
    operations = {row["id"]: row for row in language["operations"]}
    runtime = cast(dict[str, Any], context.kernel["meta_format"]["runtime_program"])
    numeric = cast(dict[str, int], runtime["numeric"])
    expression_operations: list[dict[str, Any]] = []
    for operation in operations.values():
        body = operation.get("body")
        result = operation.get("result")
        if (
            operation.get("operation_kind") == "pure-expression"
            and isinstance(body, list)
            and len(body) == 1
            and isinstance(body[0], dict)
            and isinstance(result, dict)
            and result.get("source") == {"kind": "local", "name": body[0].get("target")}
        ):
            expression_operations.append(operation)
        elif (
            operation.get("operation_kind") == "pure-expression"
            and isinstance(body, list)
            and body
            and isinstance(result, dict)
            and isinstance(result.get("source"), dict)
            and result["source"].get("kind") == "local"
        ):
            expression_operations.append(operation)
    expression_operations.sort(
        key=lambda operation: (-len(operation["body"]), operation["id"].encode("utf-8"))
    )
    formulas: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for operation in _reachable_operations(root, operations):
        slots = operation.get("extensions", {}).get("standard.formula-slots", [])
        for slot in slots:
            parameters = {
                row["id"]: row for row in cast(list[dict[str, Any]], slot["parameters"])
            }
            constants: dict[str, int] = {}
            nodes: list[dict[str, Any]] = []
            start = cast(int, slot["placeholder_index"])
            end = start + cast(int, slot["placeholder_length"])
            placeholder = operation["body"][start:end]
            position = 0
            while position < len(placeholder):
                matches: list[tuple[dict[str, Any], dict[str, str]]] = []
                for candidate in expression_operations:
                    template = candidate["body"]
                    actual = placeholder[position : position + len(template)]
                    if len(actual) != len(template):
                        continue
                    formals = {row["id"] for row in candidate["inputs"]}
                    references: dict[str, str] = {}
                    matched = True
                    for template_node, actual_node in zip(
                        template, actual, strict=True
                    ):
                        if set(template_node) != set(actual_node):
                            matched = False
                            break
                        for member, template_value in template_node.items():
                            actual_value = actual_node[member]
                            if member == "node" or not isinstance(template_value, str):
                                if template_value != actual_value:
                                    matched = False
                                    break
                            elif template_value in references:
                                if references[template_value] != actual_value:
                                    matched = False
                                    break
                            elif template_value in formals or member == "target":
                                if not isinstance(actual_value, str):
                                    matched = False
                                    break
                                references[template_value] = actual_value
                            elif template_value != actual_value:
                                matched = False
                                break
                        if not matched:
                            break
                    result_source = candidate["result"]["source"]
                    if (
                        matched
                        and all(formal in references for formal in formals)
                        and references.get(result_source["name"])
                        == actual[-1].get("target")
                    ):
                        matches.append((candidate, references))
                if len(matches) != 1:
                    raise ValueError(
                        "operation Formula placeholder has no unique expression Operation"
                    )
                expression_operation, references = matches[0]
                arguments = []
                for formal in expression_operation["inputs"]:
                    name = formal["id"]
                    reference = references[name]
                    if reference in parameters:
                        operand = {"kind": "parameter", "parameter": reference}
                    elif reference in constants:
                        operand = {"kind": "literal", "value": constants[reference]}
                    else:
                        operand = {"kind": "local", "local": reference}
                    arguments.append({"port": name, "operand": operand})
                nodes.append(
                    {
                        "id": references[
                            expression_operation["result"]["source"]["name"]
                        ],
                        "node": "operation-call",
                        "operation": {
                            "package": _operation_owner(
                                language, expression_operation["id"]
                            )[0],
                            "version": expression_operation["version"],
                            "id": expression_operation["id"],
                        },
                        "arguments": arguments,
                        "result": _formula_contract(
                            expression_operation["result"],
                            aliases,
                            minimum=(
                                0
                                if any(
                                    row.get("node") == "maximum"
                                    and any(
                                        constant.get("node") == "constant"
                                        and constant.get("literal") == 0
                                        and constant.get("target")
                                        in {row.get("left"), row.get("right")}
                                        for constant in expression_operation["body"]
                                    )
                                    for row in expression_operation["body"]
                                )
                                else -numeric["maximum"]
                            ),
                            maximum=numeric["maximum"],
                        ),
                    }
                )
                position += len(expression_operation["body"])
            body = {
                "nodes": nodes,
                "result": {"kind": "local", "local": slot["target"]},
            }
            formula_id = f"{operation['id']}.{slot['id']}"
            formulas.append(
                {
                    "id": formula_id,
                    "parameters": [
                        {
                            "id": parameter["id"],
                            **_formula_contract(
                                parameter,
                                aliases,
                                minimum=0,
                                maximum=numeric["maximum"],
                            ),
                        }
                        for parameter in parameters.values()
                    ],
                    "result": _formula_contract(
                        slot["result"],
                        aliases,
                        minimum=0,
                        maximum=numeric["maximum"],
                    ),
                    "body": body,
                    "expression": render_formula_body(body, context),
                }
            )
            owner = _operation_owner(language, operation["id"])
            bindings.append(
                {
                    "site": {
                        "kind": "operation-slot",
                        "operation": {
                            "package": owner[0],
                            "version": owner[1],
                            "id": operation["id"],
                        },
                        "slot": slot["id"],
                    },
                    "formula": {"module": "vector", "id": formula_id},
                    "arguments": [
                        {
                            "parameter": parameter,
                            "operand": {
                                "kind": "slot-parameter",
                                "parameter": parameter,
                            },
                        }
                        for parameter in parameters
                    ],
                }
            )
    return formulas, bindings


def _candidate_model_source(
    context: AdmittedAuthorityContext,
    operation: dict[str, Any],
    vector: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    language = cast(dict[str, Any], context.language_bundle["language"])
    runtime = cast(dict[str, Any], context.kernel["meta_format"]["runtime_program"])
    numeric = cast(dict[str, int], runtime["numeric"])
    operation_owner = _operation_owner(language, cast(str, operation["id"]))
    quantity_coordinate = ("core.quantity", "2.1.0", "Quantity")
    contracts = [*operation["inputs"], operation["result"]]
    coordinates = sorted(
        {*(_type_coordinate(contract) for contract in contracts), quantity_coordinate},
        key=lambda row: tuple(member.encode("utf-8") for member in row),
    )
    aliases = {
        coordinate: f"type-{index}" for index, coordinate in enumerate(coordinates)
    }
    imports = [
        {
            "alias": aliases[coordinate],
            "package": coordinate[0],
            "version": coordinate[1],
            "symbol": coordinate[2],
        }
        for coordinate in coordinates
    ]
    symbols = [
        _model_symbol(
            cast(str, contract["id"]),
            contract,
            alias=aliases[_type_coordinate(contract)],
            role="state" if contract["access"] == "read-write" else "input",
            minimum=numeric["minimum"],
            maximum=numeric["maximum"],
        )
        for contract in operation["inputs"]
    ]
    result_name = "operation_result"
    symbols.append(
        _model_symbol(
            result_name,
            operation["result"],
            alias=aliases[_type_coordinate(operation["result"])],
            role="output",
            minimum=numeric["minimum"],
            maximum=numeric["maximum"],
        )
    )
    symbols.append(
        _model_symbol(
            "harness_metric",
            {
                "kind": "scalar",
                "numeric_policy": "exact-int64",
                "representation": "Int",
                "type": {
                    "package": quantity_coordinate[0],
                    "version": quantity_coordinate[1],
                    "id": quantity_coordinate[2],
                },
                "unit": "1",
            },
            alias=aliases[quantity_coordinate],
            role="state",
            minimum=numeric["minimum"],
            maximum=numeric["maximum"],
        )
    )
    manifest_id = "standard.conformance.operation-execution-model"
    formulas, formula_bindings = _formula_sources(context, operation, aliases)
    requirements = sorted(
        {operation_owner, quantity_coordinate[:2]},
        key=lambda row: tuple(member.encode("utf-8") for member in row),
    )
    return (
        (
            {
                "schema_version": "2.0.0",
                "manifest": {
                    "id": manifest_id,
                    "version": "1.0.0",
                    "entry_module": "vector",
                },
                "package_requirements": [
                    {"id": package, "version": version}
                    for package, version in requirements
                ],
                "entrypoints": [
                    {
                        "id": vector["id"],
                        "operation": {
                            "package": operation_owner[0],
                            "version": operation_owner[1],
                            "id": operation["id"],
                        },
                        "arguments": [
                            {
                                "port": contract["id"],
                                "operand": {
                                    "kind": "symbol",
                                    "module": "vector",
                                    "symbol": contract["id"],
                                },
                            }
                            for contract in operation["inputs"]
                        ],
                        "result": {
                            "kind": "symbol",
                            "module": "vector",
                            "symbol": result_name,
                        },
                    }
                ],
                "modules": [
                    {
                        "id": "vector",
                        "imports": imports,
                        "symbols": symbols,
                        **({"formulas": formulas} if formulas else {}),
                    }
                ],
                **({"formula_bindings": formula_bindings} if formula_bindings else {}),
            }
        ),
        result_name,
    )


def _checked_vector_experiment(
    context: AdmittedAuthorityContext,
    operation: dict[str, Any],
    vector: dict[str, Any],
) -> tuple[CheckedExperiment, str]:
    source, result_name = _candidate_model_source(context, operation, vector)
    checked_model = check_model_source_value(source, authority_context=context)
    if not isinstance(checked_model, CheckedModel):
        diagnostics = (
            [
                diagnostic.model_dump(mode="json")
                for diagnostic in checked_model.diagnostics
            ]
            if isinstance(checked_model, Schema2RefusalReport)
            else []
        )
        raise ValueError(
            f"operation vector model failed candidate admission: {diagnostics}"
        )
    artifacts = compile_checked_model(checked_model)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    profile = cast(str, operation["runtime_profile"])
    rng_algorithm = cast(
        str,
        context.kernel["meta_format"]["runtime_program"]["named_rng"]["algorithm"],
    )
    requirements, named_streams = derive_scenario_program_requirements(
        rir,
        cast(str, vector["id"]),
        profile,
        rng_algorithm,
    )
    values = {row["name"]: row["value"] for row in vector["input"]["values"]}
    assignments = [
        {
            "target": {
                "model": source["manifest"]["id"],
                "module": "vector",
                "name": contract["id"],
            },
            "value": values[contract["id"]],
        }
        for contract in operation["inputs"]
    ]
    assignments.append(
        {
            "target": {
                "model": source["manifest"]["id"],
                "module": "vector",
                "name": "harness_metric",
            },
            "value": 0,
        }
    )
    build = cast(dict[str, Any], artifacts["build-receipt"])
    specification = {
        "schema_version": "2.0.0",
        "id": f"operation-execution.{vector['id']}",
        "version": "1.0.0",
        "kernel_identity": context.kernel["content_identity"],
        "language_bundle_identity": context.language_bundle["content_identity"],
        "model": {
            "source_identity": checked_model.source_identity,
            "build_receipt_identity": build["content_identity"],
            "resolved_model_identity": build["resolved_model_identity"],
            "package_lock_identity": build["package_lock_identity"],
            "rir_identity": build["rir_identity"],
        },
        "runtime": {"profile": profile, "required_evaluator": requirements},
        "seed": {
            "algorithm": rng_algorithm,
            "value": vector["input"]["seed"],
        },
        "scenarios": [
            {
                "id": "vector",
                "assignments": assignments,
                "event_plan": [
                    {
                        "kind": "transition-invocation",
                        "root_event_ref": "vector",
                        "logical_time": 0,
                        "priority": 0,
                        "entrypoint": vector["id"],
                        "payload": [],
                    }
                ],
                "named_streams": named_streams,
                "terminal_condition": {"kind": "event-count", "maximum": 1},
            }
        ],
        "metrics": [
            {
                "id": "harness_metric",
                "kind": "scalar",
                "unit": "1",
                "dimensions": [],
                "window": {"kind": "scenario", "name": "terminal-event"},
                "aggregation": "single",
                "replication": {"unit": "scenario"},
                "missing": "refuse",
                "censoring": "none",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": "harness_metric",
                },
                "target": {"minimum": 0, "maximum": 0},
            }
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }
    return (
        CheckedExperiment(
            value=specification,
            content_identity=content_identity(
                "experiment-specification-v2", cast(JsonValue, specification)
            ),
            kernel=cast(dict[str, Any], context.kernel),
            language_bundle=cast(dict[str, Any], context.language_bundle),
            build_receipt=build,
            package_lock=cast(dict[str, Any], artifacts["package-lock"]),
            resolved_model=cast(dict[str, Any], artifacts["resolved-model"]),
            rir=rir,
            authority_context=context,
        ),
        result_name,
    )


def _fact_value(row: dict[str, Any]) -> JsonValue:
    if row["kind"] == "integer":
        return cast(JsonValue, row["integer"])
    if row["kind"] == "boolean":
        return cast(JsonValue, row["boolean"])
    if row["kind"] == "structured":
        return cast(JsonValue, row["value"])
    raise ValueError("operation vector result fact has an unsupported kind")


def evaluate_operation_execution_vector(
    context: AdmittedAuthorityContext,
    vector: dict[str, Any],
) -> dict[str, JsonValue]:
    """Execute one admitted Package vector through the production evaluator."""
    operations = {
        row["id"]: row for row in context.language_bundle["language"]["operations"]
    }
    operation = operations.get(vector.get("operation"))
    if operation is None or vector.get("kind") != "operation-execution":
        raise ValueError("operation execution vector target is unavailable")
    checked, result_name = _checked_vector_experiment(context, operation, vector)
    evaluation = evaluate_experiment(checked)
    state_names = [
        row["id"] for row in operation["inputs"] if row["access"] == "read-write"
    ]
    if isinstance(evaluation, RuntimeRefusalOutcome):
        diagnostic = evaluation.report.diagnostics[0].code
        reasons = [
            reason["id"]
            for reason in context.language_bundle["language"]["reasons"]
            if reason.get("diagnostic") == diagnostic
            and reason.get("id") in operation["refusals"]
        ]
        if len(reasons) != 1:
            raise ValueError("operation vector refusal reason is not unique")
        return {
            "completion": {"kind": "refusal", "reason": reasons[0]},
            "result": {"kind": "not-produced"},
            "rng_draws": [],
            "state_after": [
                {"name": name, "value": evaluation.state_after[name]}
                for name in state_names
            ],
        }
    if isinstance(evaluation, Schema2RefusalReport):
        raise ValueError("operation vector failed before production dispatch")
    if not isinstance(evaluation, EvaluationArtifacts):
        raise TypeError("operation vector returned an unknown production result")
    trace = evaluation.members["event-trace"].value
    event = next(row for row in trace["events"] if row["observation"] is None)
    outcome = event["outcome"]
    result: dict[str, JsonValue] = {"kind": "not-produced"}
    if outcome["kind"] == "success":
        result_fact = next(row for row in event["facts"] if row["name"] == result_name)
        result = {"kind": "value", "value": _fact_value(result_fact)}
    state_after = {row["name"]: row["value"] for row in event["state_after"]}
    return {
        "completion": {"kind": "outcome", "id": outcome["id"]},
        "result": result,
        "rng_draws": [
            {
                member: draw[member]
                for member in ("candidate_hex", "index", "stream", "value")
            }
            for draw in event["rng_draws"]
        ],
        "state_after": [
            {"name": name, "value": state_after[name]} for name in state_names
        ],
    }
