"""Independent Operation execution adapter for development conformance."""

import hashlib
from collections.abc import Mapping
from typing import Any, cast

OperationCoordinate = tuple[str, str, str]


def _operation_coordinate(reference: dict[str, Any]) -> OperationCoordinate:
    return (
        cast(str, reference["package"]),
        cast(str, reference["version"]),
        cast(str, reference["id"]),
    )


def _reference_compare(comparison: str, left: int, right: int) -> bool:
    if comparison == "greater-than-or-equal":
        return left >= right
    if comparison == "less-than":
        return left < right
    if comparison == "less-than-or-equal":
        return left <= right
    raise AssertionError(f"unsupported comparison in authority: {comparison}")


def reference_rng_draw(
    contract: dict[str, Any],
    seed: int,
    stream: str,
    minimum: int,
    maximum: int,
    states: dict[str, int],
    indices: dict[str, int],
) -> dict[str, Any]:
    mask = (1 << contract["word_bits"]) - 1
    if stream not in states:
        derivation = contract["stream_derivation"]
        digest = hashlib.sha256(
            stream.encode(contract["stream_name_encoding"])
        ).digest()
        digest_slice = derivation["digest_slice"]
        start = digest_slice["offset"]
        end = start + digest_slice["length"]
        states[stream] = (
            seed
            + int.from_bytes(
                digest[start:end],
                derivation["byte_order"],
            )
        ) & mask
        indices[stream] = 0
    transition = contract["state_transition"]
    state = (states[stream] + int(transition["increment_hex"], 16)) & mask
    states[stream] = state
    candidate = state
    for step in transition["mix_steps"]:
        candidate ^= candidate >> step["xor_shift_right"]
        if "multiply_hex" in step:
            candidate = (candidate * int(step["multiply_hex"], 16)) & mask
    index = indices[stream]
    indices[stream] = index + 1
    value = minimum + candidate % (maximum - minimum + 1)
    candidate_width = contract["candidate_encoding"]["width_bits"] // 4
    return {
        "stream": stream,
        "index": index,
        "candidate_hex": f"{candidate:0{candidate_width}x}",
        "accepted": True,
        "minimum": minimum,
        "maximum": maximum,
        "value": value,
    }


def _reference_fact_rows(values: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in sorted(values):
        value = values[name]
        if isinstance(value, bool):
            rows.append({"name": name, "kind": "boolean", "boolean": value})
        elif not isinstance(value, int):
            rows.append({"name": name, "kind": "structured", "value": value})
        else:
            rows.append({"name": name, "kind": "integer", "integer": value})
    return rows


class _ReferenceRuntimeRefusal(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.operation: str | None = None
        self.call_path: str | None = None
        self.call_site_identity: str | None = None


def reference_execute_event(
    kernel: dict[str, Any],
    operation: dict[str, Any],
    operations: Mapping[Any, dict[str, Any]],
    scenario: dict[str, Any],
    *,
    seed: int,
    state_names: set[str] | None = None,
    resolved_entrypoint: dict[str, Any] | None = None,
    resolved_declarations: list[dict[str, Any]] | None = None,
    resolved_call_sites: list[dict[str, Any]] | None = None,
    resolved_initialization_programs: list[dict[str, Any]] | None = None,
    language_bundle: dict[str, Any] | None = None,
    root_operation_coordinate: OperationCoordinate | None = None,
) -> dict[str, Any]:
    runtime = kernel["meta_format"]["runtime_program"]
    numeric = runtime["numeric"]
    nodes = {row["id"]: row for row in runtime["nodes"]}
    variables: dict[str | tuple[str, str, str], Any]
    state_targets: set[str | tuple[str, str, str]]
    display_names: dict[str | tuple[str, str, str], str]
    if resolved_entrypoint is not None:
        assert resolved_declarations is not None
        declarations = {
            (
                row["resolved_symbol"]["model"],
                row["resolved_symbol"]["module"],
                row["resolved_symbol"]["name"],
            ): row
            for row in resolved_declarations
        }
        variables = {
            (
                row["target"]["model"],
                row["target"]["module"],
                row["target"]["name"],
            ): row["value"]
            for row in resolved_entrypoint["scenario_input_contract"]["initializers"]
        }
        variables.update(
            {
                (
                    row["target"]["model"],
                    row["target"]["module"],
                    row["target"]["name"],
                ): row["value"]
                for row in scenario["assignments"]
            }
        )
        pending_programs = list(resolved_initialization_programs or [])
        reachable_formula_targets = {
            (
                operand["symbol"]["model"],
                operand["symbol"]["module"],
                operand["symbol"]["name"],
            )
            for binding in resolved_entrypoint["arguments"]
            if (operand := binding["operand"])["kind"] == "symbol"
        }
        while True:
            previous_target_count = len(reachable_formula_targets)
            for program in pending_programs:
                target = program["target"]
                target_coordinate = (
                    target["model"],
                    target["module"],
                    target["name"],
                )
                if target_coordinate not in reachable_formula_targets:
                    continue
                reachable_formula_targets.update(
                    (
                        operand["resolved_symbol"]["model"],
                        operand["resolved_symbol"]["module"],
                        operand["resolved_symbol"]["name"],
                    )
                    for row in program["inputs"]
                    if (operand := row["operand"])["kind"] != "literal"
                )
            if len(reachable_formula_targets) == previous_target_count:
                break
        pending_programs = [
            program
            for program in pending_programs
            if (
                program["target"]["model"],
                program["target"]["module"],
                program["target"]["name"],
            )
            in reachable_formula_targets
        ]
        while pending_programs:
            progressed = False
            for program in list(pending_programs):
                values: dict[str, int] = {}
                ready = True
                for row in program["inputs"]:
                    operand = row["operand"]
                    if operand["kind"] == "literal":
                        values[row["name"]] = operand["value"]
                        continue
                    symbol = operand["resolved_symbol"]
                    coordinate = (
                        symbol["model"],
                        symbol["module"],
                        symbol["name"],
                    )
                    if coordinate not in variables:
                        ready = False
                        break
                    values[row["name"]] = variables[coordinate]
                if not ready:
                    continue
                for row in program["body"]:
                    instruction = row["instruction"]
                    node = instruction["node"]
                    if node == "constant":
                        result = instruction["literal"]
                    elif node == "copy":
                        result = values[instruction["value"]]
                    elif node == "add":
                        result = (
                            values[instruction["left"]] + values[instruction["right"]]
                        )
                    elif node == "subtract":
                        result = (
                            values[instruction["left"]] - values[instruction["right"]]
                        )
                    elif node == "multiply":
                        result = (
                            values[instruction["left"]] * values[instruction["right"]]
                        )
                    elif node == "maximum":
                        result = max(
                            values[instruction["left"]],
                            values[instruction["right"]],
                        )
                    else:
                        assert node == "if"
                        result = values[
                            instruction[
                                "when_true"
                                if values[instruction["condition"]]
                                else "when_false"
                            ]
                        ]
                    assert numeric["minimum"] <= result <= numeric["maximum"]
                    values[instruction["target"]] = result
                target = program["target"]
                result_source = program["result"]
                variables[(target["model"], target["module"], target["name"])] = values[
                    result_source["name"]
                ]
                pending_programs.remove(program)
                progressed = True
            assert progressed
        state_targets = {
            coordinate
            for coordinate, declaration in declarations.items()
            if declaration["role"] == "state"
        }
        display_names = {
            coordinate: declaration["resolved_symbol"]["name"]
            for coordinate, declaration in declarations.items()
        }
    else:
        assert state_names is not None
        legacy_variables: dict[str, Any] = {
            row["name"]: row["value"] for row in scenario["values"]
        }
        variables = cast(
            dict[str | tuple[str, str, str], Any],
            legacy_variables,
        )
        state_targets = set(state_names)
        display_names = {name: name for name in legacy_variables}
    cells = {name: {"value": value} for name, value in variables.items()}
    state_cells = {name: cells[name] for name in state_targets if name in cells}
    declared_domains_by_cell = (
        {
            id(cells[coordinate]): declaration["domain"]
            for coordinate, declaration in declarations.items()
            if coordinate in state_cells
            and declaration["domain_kind"] == "closed-interval"
        }
        if resolved_entrypoint is not None
        else {}
    )
    before = {name: cell["value"] for name, cell in state_cells.items()}
    rng_states: dict[str, int] = {}
    rng_indices: dict[str, int] = {}
    draws: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    call_sites = {
        (row["parent_operation"]["id"], row["site"]): row
        for row in (resolved_call_sites or [])
    }
    language = (
        language_bundle.get("language") if isinstance(language_bundle, dict) else None
    )
    nominal_types = {
        (row["package"], row["version"], row["id"]): row
        for row in (
            language.get("nominal_types", []) if isinstance(language, dict) else []
        )
        if isinstance(row, dict)
        and all(
            isinstance(row.get(member), str) for member in ("package", "version", "id")
        )
    }
    constructors = {
        row["id"]: row
        for row in (
            language.get("constructors", []) if isinstance(language, dict) else []
        )
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    structured_operations = [
        row
        for row in (
            language.get("structured_operations", [])
            if isinstance(language, dict)
            else []
        )
        if isinstance(row, dict)
    ]

    def structural(type_expression: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        definition = type_expression
        constructor = None
        if isinstance(type_expression, dict) and set(type_expression) >= {
            "id",
            "package",
            "version",
        }:
            nominal = nominal_types[
                (
                    type_expression["package"],
                    type_expression["version"],
                    type_expression["id"],
                )
            ]
            definition = nominal["definition"]
            constructor = constructors[nominal["constructor"]]
        if not isinstance(definition, dict):
            raise AssertionError("structured type is not admitted")
        if constructor is None:
            matches = [
                candidate
                for candidate in constructors.values()
                if candidate.get("value_rule", {}).get("definition_kind")
                == definition.get("kind")
            ]
            assert len(matches) == 1
            constructor = matches[0]
        return definition, constructor

    def structured_law(type_expression: Any, operator: str) -> dict[str, Any]:
        _definition, constructor = structural(type_expression)
        matches = [
            row["law"]
            for row in structured_operations
            if row.get("owner_constructor") == constructor["id"]
            and row.get("law", {}).get("operator") == operator
        ]
        assert len(matches) == 1
        return matches[0]

    def structured_lookup(envelope: Any, key: Any) -> dict[str, Any]:
        assert isinstance(envelope, dict) and set(envelope) == {"type", "value"}
        definition, constructor = structural(envelope["type"])
        selected_law = structured_law(envelope["type"], "bounded-lookup")
        rule = constructor["value_rule"]
        if selected_law["selector"] == "static-field":
            field = next(
                row
                for row in definition[rule["fields_member"]]
                if row[rule["field_name_member"]] == key
            )
            result_type = field[rule["field_type_member"]]
            result_value = envelope["value"][key]
        else:
            assert selected_law["selector"] == "local-index"
            result_type = definition[rule["element_member"]]
            result_value = envelope["value"][key]
        if isinstance(result_type, dict) and result_type.get("kind") == "nominal":
            result_type = {
                member: result_type[member] for member in ("id", "package", "version")
            }
        return {"type": result_type, "value": result_value}

    def structured_is_empty(envelope: Any) -> bool:
        assert isinstance(envelope, dict) and set(envelope) == {"type", "value"}
        definition, constructor = structural(envelope["type"])
        selected_law = structured_law(envelope["type"], "collection-is-empty")
        assert constructor["value_rule"]["operator"] == "bounded-list"
        assert selected_law["result_contract"] == "kernel-boolean"
        assert definition["kind"] == "list"
        return not envelope["value"]

    def exact(value: int, target: dict[str, Any] | None = None) -> int:
        if not numeric["minimum"] <= value <= numeric["maximum"]:
            raise _ReferenceRuntimeRefusal("runtime.numeric_overflow")
        domain = (
            declared_domains_by_cell.get(id(target)) if target is not None else None
        )
        if domain is not None and not domain["minimum"] <= value <= domain["maximum"]:
            raise _ReferenceRuntimeRefusal("runtime.numeric_overflow")
        return value

    def execute(
        selected_coordinate: OperationCoordinate,
        selected: dict[str, Any],
        arguments: dict[str, dict[str, Any]],
        stack: tuple[OperationCoordinate, ...] = (),
        path: tuple[str, ...] = (),
    ) -> tuple[str, Any]:
        assert selected_coordinate not in stack
        locals_: dict[str, dict[str, Any]] = {}
        operation_results: dict[str, Any] = {}
        frame_cells = {id(cell): cell for cell in arguments.values()}
        snapshot = {key: cell["value"] for key, cell in frame_cells.items()}
        outcome = selected["default_outcome"]

        def cell(name: str) -> dict[str, Any]:
            if name in locals_:
                return locals_[name]
            return arguments[name]

        def write_local(name: str, value: Any) -> None:
            locals_[name] = {"value": value}

        def project_integer(value: Any) -> int | None:
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if (
                isinstance(value, dict)
                and isinstance(value.get("value"), int)
                and not isinstance(value["value"], bool)
            ):
                return value["value"]
            return None

        def integer(value: Any) -> int:
            projected = project_integer(value)
            assert projected is not None
            return projected

        try:
            for instruction in selected["body"]:
                node = nodes[instruction["node"]]
                assert set(instruction) == set(node["required_members"])
                semantics = node["semantics"]
                operator = semantics["operator"]
                if operator == "invoke-operation":
                    child_coordinate = _operation_coordinate(instruction["operation"])
                    child = operations.get(child_coordinate)
                    if child is None:
                        child = operations[instruction["operation"]["id"]]
                    child_arguments: dict[str, dict[str, Any]] = {}
                    for binding in instruction["arguments"]:
                        operand = binding["operand"]
                        if operand["kind"] == "port":
                            actual = arguments[operand["port"]]
                        elif operand["kind"] == "local":
                            actual = locals_[operand["local"]]
                        else:
                            actual = {"value": operand["literal"]}
                        child_arguments[binding["port"]] = actual
                    try:
                        child_outcome, child_result = execute(
                            child_coordinate,
                            child,
                            child_arguments,
                            (*stack, selected_coordinate),
                            (*path, instruction["site"]),
                        )
                    except _ReferenceRuntimeRefusal as refusal:
                        if resolved_call_sites is not None:
                            refusal.call_site_identity = call_sites[
                                (selected["id"], instruction["site"])
                            ]["identity"]
                        raise
                    if resolved_call_sites is not None:
                        call_site = call_sites[(selected["id"], instruction["site"])]
                        outcome_row = next(
                            row
                            for row in call_site["outcomes"]
                            if row["outcome"] == child_outcome
                        )
                        calls.append(
                            {
                                "call_site_identity": call_site["identity"],
                                "site": "/".join((*path, instruction["site"])),
                                "operation": call_site["operation"],
                                "outcome": {
                                    "id": child_outcome,
                                    "identity": outcome_row["identity"],
                                },
                                "arguments": [
                                    {
                                        "formal_port_identity": row["port"]["identity"],
                                        "actual_operand_identity": row["operand"][
                                            "identity"
                                        ],
                                    }
                                    for row in call_site["arguments"]
                                ],
                                "result_identity": call_site["result"]["identity"],
                            }
                        )
                    result_binding = instruction["result"]
                    if result_binding["kind"] == "local":
                        write_local(result_binding["name"], child_result)
                    elif result_binding["kind"] == "operation-result":
                        operation_results[instruction["site"]] = child_result
                    action = next(
                        row["action"]
                        for row in instruction["outcomes"]
                        if row["outcome"] == child_outcome
                    )
                    if action["kind"] == "propagate":
                        outcome = action["outcome"]
                        break
                    continue
                if operator == "gameplay-precondition":
                    if not _reference_compare(
                        semantics["comparison"],
                        integer(cell(instruction["left"])["value"]),
                        integer(cell(instruction["right"])["value"]),
                    ):
                        outcome = instruction["outcome"]
                        break
                elif operator == "typed-require":
                    if (
                        cell(instruction["condition"])["value"]
                        != instruction["expected"]
                    ):
                        refusal_reference = semantics["refusal_reference"]
                        raise _ReferenceRuntimeRefusal(
                            instruction[refusal_reference["instruction_member"]]
                        )
                elif operator == "guarded-outcome-block":
                    if cell(instruction["condition"])["value"]:
                        unit_contract = runtime["fixed_value_contracts"]["kernel-unit"]
                        guarded = {
                            "body": instruction["body"],
                            "default_outcome": instruction["outcome"],
                            "effects": selected["effects"],
                            "id": selected["id"],
                            "inputs": [],
                            "outcomes": list(selected["outcomes"]),
                            "refusals": selected["refusals"],
                            "resource_bounds": selected["resource_bounds"],
                            "result": {
                                **unit_contract,
                                "access": "read",
                                "discardable": True,
                                "id": "result",
                                "source": {"kind": "unit"},
                            },
                        }
                        execute(
                            selected_coordinate,
                            guarded,
                            {**arguments, **locals_},
                            stack,
                            path,
                        )
                        outcome = instruction["outcome"]
                        break
                elif operator == "named-integer-draw":
                    draw = reference_rng_draw(
                        runtime["named_rng"],
                        seed,
                        instruction["stream"],
                        instruction["minimum"],
                        instruction["maximum"],
                        rng_states,
                        rng_indices,
                    )
                    draws.append(draw)
                    write_local(instruction["target"], draw["value"])
                elif operator == "typed-literal":
                    write_local(instruction["target"], instruction["literal"])
                elif operator == "copy-value":
                    write_local(
                        instruction["target"],
                        cell(instruction["value"])["value"],
                    )
                elif operator == "bounded-lookup":
                    key = instruction["key"]
                    container = cell(instruction["value"])["value"]
                    selector = structured_law(container["type"], "bounded-lookup")[
                        "selector"
                    ]
                    if selector == "local-index":
                        key = locals_[key]["value"]
                    write_local(
                        instruction["target"],
                        structured_lookup(container, key),
                    )
                elif operator == "canonical-equal":
                    left = cell(instruction["left"])["value"]
                    right = cell(instruction["right"])["value"]
                    left_integer = project_integer(left)
                    right_integer = project_integer(right)
                    if isinstance(left, bool) and isinstance(right, bool):
                        equal = left == right
                    elif isinstance(left, bool) or isinstance(right, bool):
                        raise AssertionError(
                            "admitted equality operands used different representations"
                        )
                    elif left_integer is not None and right_integer is not None:
                        if isinstance(left, dict) and isinstance(right, dict):
                            assert left["type"] == right["type"]
                        equal = left_integer == right_integer
                    else:
                        assert isinstance(left, dict) and isinstance(right, dict)
                        assert left["type"] == right["type"]
                        equal = left["value"] == right["value"]
                    write_local(
                        instruction["target"],
                        equal,
                    )
                elif operator == "collection-is-empty":
                    write_local(
                        instruction["target"],
                        structured_is_empty(cell(instruction["value"])["value"]),
                    )
                elif operator in {
                    "integer-add",
                    "integer-subtract",
                    "integer-multiply",
                    "integer-maximum",
                }:
                    left = integer(cell(instruction["left"])["value"])
                    right = integer(cell(instruction["right"])["value"])
                    result = {
                        "integer-add": lambda: left + right,
                        "integer-subtract": lambda: left - right,
                        "integer-multiply": lambda: left * right,
                        "integer-maximum": lambda: max(left, right),
                    }[operator]()
                    write_local(instruction["target"], exact(result))
                elif operator == "integer-compare":
                    write_local(
                        instruction["target"],
                        _reference_compare(
                            semantics["comparison"],
                            integer(cell(instruction["left"])["value"]),
                            integer(cell(instruction["right"])["value"]),
                        ),
                    )
                elif operator == "select-value":
                    choice = (
                        instruction["when_true"]
                        if cell(instruction["condition"])["value"]
                        else instruction["when_false"]
                    )
                    write_local(instruction["target"], cell(choice)["value"])
                elif operator == "state-integer-subtract":
                    target = arguments[instruction["symbol"]]
                    target["value"] = exact(
                        target["value"] - cell(instruction["value"])["value"],
                        target,
                    )
                elif operator == "state-write":
                    target = arguments[instruction["symbol"]]
                    value = cell(instruction["value"])["value"]
                    if (
                        isinstance(target["value"], int)
                        and not isinstance(target["value"], bool)
                        and isinstance(value, dict)
                        and set(value) == {"type", "value"}
                    ):
                        value = value["value"]
                    target["value"] = (
                        exact(value, target)
                        if isinstance(value, int) and not isinstance(value, bool)
                        else value
                    )
                else:
                    raise AssertionError(
                        f"unsupported operator in authority: {operator}"
                    )
        except _ReferenceRuntimeRefusal as refusal:
            for key, value in snapshot.items():
                frame_cells[key]["value"] = value
            if refusal.operation is None:
                refusal.operation = selected["id"]
                refusal.call_path = "/".join(path)
            raise

        outcome_definition = next(
            row for row in selected["outcomes"] if row["id"] == outcome
        )
        if outcome_definition["state_policy"] == "rollback":
            for key, value in snapshot.items():
                frame_cells[key]["value"] = value
        source = selected["result"]["source"]
        if outcome_definition["kind"] != "success":
            result = None
        elif source["kind"] == "local":
            result = locals_[source["name"]]["value"]
        elif source["kind"] == "port":
            result = arguments[source["name"]]["value"]
        elif source["kind"] == "operation-result":
            result = operation_results[source["site"]]
        else:
            assert source["kind"] == "unit"
            result = None
        return outcome, result

    if resolved_entrypoint is None:
        root_arguments = [
            {
                "port": port["id"],
                "operand": {"kind": "symbol", "symbol": port["id"]},
            }
            for port in operation["inputs"]
        ]
        root_frame = {
            row["port"]: cells[row["operand"]["symbol"]] for row in root_arguments
        }
    else:
        root_frame = {}
        for argument in resolved_entrypoint["arguments"]:
            operand = argument["operand"]
            if operand["kind"] == "symbol":
                symbol = operand["symbol"]
                coordinate = (
                    symbol["model"],
                    symbol["module"],
                    symbol["name"],
                )
                actual = cells[coordinate]
            else:
                actual = {"value": operand["value"]}
            root_frame[argument["port"]["name"]] = actual
    try:
        selected_root_coordinate = root_operation_coordinate or (
            "",
            cast(str, operation.get("version", "")),
            cast(str, operation["id"]),
        )
        outcome, result = execute(
            selected_root_coordinate,
            operation,
            root_frame,
            path=((resolved_entrypoint["id"],) if resolved_entrypoint else ()),
        )
    except _ReferenceRuntimeRefusal as refusal:
        return {
            "refusal": {
                "reason": refusal.reason,
                "operation": refusal.operation,
                "call_path": refusal.call_path,
                "call_site_identity": refusal.call_site_identity,
            },
            "state_before": [
                {"name": display_names[name], "value": before[name]}
                for name in sorted(before)
            ],
            "state_after": [
                {
                    "name": display_names[name],
                    "value": state_cells[name]["value"],
                }
                for name in sorted(state_cells)
            ],
        }
    outcome_definition = next(
        row for row in operation["outcomes"] if row["id"] == outcome
    )
    if (
        resolved_entrypoint is not None
        and resolved_entrypoint["result"]["kind"] == "symbol"
        and outcome_definition["kind"] == "success"
    ):
        symbol = resolved_entrypoint["result"]["symbol"]
        coordinate = (symbol["model"], symbol["module"], symbol["name"])
        cells[coordinate] = {"value": result}
        display_names[coordinate] = symbol["name"]
    if outcome_definition["state_policy"] == "rollback":
        for name, value in before.items():
            state_cells[name]["value"] = value
    facts: dict[str, Any] = {
        display_names[name]: cell["value"] for name, cell in cells.items()
    }
    event = {
        "operation": operation["id"],
        "outcome": {
            "id": outcome,
            "kind": outcome_definition["kind"],
        },
        "facts": _reference_fact_rows(facts),
        "state_before": [
            {"name": display_names[name], "value": before[name]}
            for name in sorted(before)
        ],
        "state_after": [
            {
                "name": display_names[name],
                "value": state_cells[name]["value"],
            }
            for name in sorted(state_cells)
        ],
        "rng_draws": draws,
        "schedules": [],
        "cancellations": [],
    }
    if resolved_entrypoint is None:
        event["result"] = result
    if resolved_entrypoint is not None:
        event["entrypoint"] = {
            "id": resolved_entrypoint["id"],
            "identity": resolved_entrypoint["identity"],
        }
        event["calls"] = calls
    return event
