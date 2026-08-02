"""Independent Formula-notation consumer for cross-implementation conformance.

This module deliberately does not import the production formula_notation module.
It projects the sealed Standard Schema grammar and Package-owned Operation notation,
then implements its own canonical renderer and line-oriented canonical parser.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, cast

from gda_balancing.schema2.canonical import JsonValue, canonical_bytes


def _authority(
    language_bundle: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grammar: dict[str, Any] | None = None
    for package in cast(list[dict[str, Any]], language_bundle["language"]["packages"]):
        if package.get("id") != "standard.schema":
            continue
        for closure in cast(list[dict[str, Any]], package["semantic_closure"]):
            if closure.get("authority_path") != "language.wire_schemas":
                continue
            for definition in cast(list[dict[str, Any]], closure["definitions"]):
                if definition.get("artifact_kind") != "model-source-package":
                    continue
                definitions = definition["schema"].get("$defs", {})
                grammar = definitions.get("formulaNotationGrammar", {}).get("const")
    if not isinstance(grammar, dict):
        raise ValueError("independent consumer found no Formula grammar")
    return grammar, cast(
        list[dict[str, Any]], language_bundle["language"]["operations"]
    )


def _conversion_policy(language_bundle: dict[str, Any]) -> dict[str, Any]:
    profiles = [
        row
        for row in language_bundle["language"]["resolution_profiles"]
        if row.get("default") is True
    ]
    if len(profiles) != 1:
        raise ValueError("independent consumer found no default resolution profile")
    policy = (
        profiles[0]
        .get("extensions", {})
        .get("standard.formula", {})
        .get("notation_conversion")
    )
    if not isinstance(policy, dict):
        raise ValueError("independent consumer found no notation conversion policy")
    return policy


def _identifier(value: Any, grammar: dict[str, Any]) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("identifier is empty")
    if (
        re.fullmatch(cast(str, grammar["bare_identifier_pattern"]), value)
        and value not in grammar["reserved_identifiers"]
    ):
        return value
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    return (
        quote
        + value.replace(escape, escape + escape).replace(quote, escape + quote)
        + quote
    )


def _operand(value: Any, grammar: dict[str, Any]) -> str:
    if not isinstance(value, dict):
        raise ValueError("operand is not an object")
    kind = value.get("kind")
    if kind in {"parameter", "local"}:
        return _identifier(value[kind], grammar)
    if kind == "literal" and isinstance(value.get("value"), int):
        return str(value["value"])
    if kind == "symbol":
        resolved = value.get("resolved_symbol")
        if isinstance(resolved, dict):
            module, symbol = resolved.get("module"), resolved.get("name")
        else:
            module, symbol = value.get("module"), value.get("symbol")
        return cast(str, grammar["coordinate_separator"]).join(
            (_identifier(module, grammar), _identifier(symbol, grammar))
        )
    raise ValueError("operand kind is not admitted")


def _selected_notations(
    request: dict[str, Any], language_bundle: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    _grammar, operations = _authority(language_bundle)
    selected = {
        (row.get("id"), row.get("version"))
        for row in request.get("package_requirements", [])
        if isinstance(row, dict)
    }
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for operation in operations:
        coordinate = (
            operation.get("type", {}).get("package"),
            operation.get("version"),
        )
        package = operation.get("package")
        if not isinstance(package, str):
            package = next(
                (
                    cast(str, owner["id"])
                    for owner in language_bundle["language"]["packages"]
                    if any(
                        closure.get("authority_path") == "language.operations"
                        and operation in closure.get("definitions", [])
                        for closure in owner["semantic_closure"]
                    )
                ),
                "",
            )
        coordinate = (package, operation.get("version"))
        notation = operation.get("extensions", {}).get("standard.formula-notation")
        if (
            coordinate in selected
            and operation.get("purity") == "pure"
            and isinstance(notation, dict)
        ):
            rows.append(({**operation, "package": package}, notation))
    return rows


def render_body(
    body: dict[str, Any], request: dict[str, Any], language_bundle: dict[str, Any]
) -> str:
    grammar, _operations = _authority(language_bundle)
    if set(body) == {"node", "parameter"} and body.get("node") == "parameter":
        return _identifier(body["parameter"], grammar)
    notations = _selected_notations(request, language_bundle)
    by_coordinate = {
        (
            cast(str, operation.get("package", "")),
            cast(str, operation["version"]),
            cast(str, operation["id"]),
        ): notation
        for operation, notation in notations
    }
    if not isinstance(body.get("nodes"), list) or not isinstance(
        body.get("result"), dict
    ):
        raise ValueError("body is not a Formula program")
    lines: list[str] = []
    for node in cast(list[dict[str, Any]], body["nodes"]):
        kind = node.get("node")
        if kind == "operation-call":
            coordinate = cast(dict[str, Any], node["operation"])
            notation = by_coordinate.get(
                (
                    cast(str, coordinate["package"]),
                    cast(str, coordinate["version"]),
                    cast(str, coordinate["id"]),
                )
            )
            if notation is None:
                raise ValueError("operation notation is unresolved")
            arguments = {row["port"]: row["operand"] for row in node["arguments"]}
            values = [
                _operand(arguments[port], grammar) for port in notation["ordered_ports"]
            ]
            if notation["kind"] == "infix":
                rhs = f"{values[0]} {notation['token']} {values[1]}"
            else:
                rhs = f"{notation['name']}({', '.join(values)})"
        elif kind == "formula-call":
            coordinate = cast(dict[str, Any], node["formula"])
            name = ".".join(
                (
                    _identifier(coordinate["module"], grammar),
                    _identifier(coordinate["id"], grammar),
                )
            )
            arguments = sorted(
                (
                    _identifier(row["parameter"], grammar),
                    _operand(row["operand"], grammar),
                )
                for row in node["arguments"]
            )
            rhs = f"{name}({', '.join(f'{key} = {value}' for key, value in arguments)})"
        elif kind == "conditional":
            rhs = (
                f"if {_operand(node['condition'], grammar)} then "
                f"{_operand(node['when_true'], grammar)} else {_operand(node['when_false'], grammar)}"
            )
        else:
            raise ValueError("node kind is not admitted")
        lines.append(f"let {_identifier(node['id'], grammar)} = {rhs};")
    lines.append(_operand(body["result"], grammar))
    return "\n".join(lines)


def _split_outside(text: str, delimiter: str, quote: str, escape: str) -> list[str]:
    rows: list[str] = []
    start = 0
    depth = 0
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted and char == escape:
            index += 2
            continue
        if char == quote:
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        elif not quoted and depth == 0 and text.startswith(delimiter, index):
            rows.append(text[start:index])
            start = index + len(delimiter)
            index = start
            continue
        index += 1
    rows.append(text[start:])
    return rows


def _unquote(text: str, grammar: dict[str, Any]) -> str:
    text = text.strip()
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    if text.startswith(quote) and text.endswith(quote):
        value = text[1:-1]
        output: list[str] = []
        index = 0
        while index < len(value):
            if value[index] == escape:
                index += 1
            output.append(value[index])
            index += 1
        return "".join(output)
    if not re.fullmatch(cast(str, grammar["bare_identifier_pattern"]), text):
        raise ValueError("bare identifier is malformed")
    return text


def _parse_operand(
    text: str, grammar: dict[str, Any], locals_: set[str], parameters: set[str]
) -> dict[str, JsonValue]:
    text = text.strip()
    if re.fullmatch(cast(str, grammar["integer_literal_pattern"]), text):
        return {"kind": "literal", "value": int(text)}
    segments = _split_outside(
        text,
        cast(str, grammar["coordinate_separator"]),
        cast(str, grammar["identifier_quote"]),
        cast(str, grammar["escape_character"]),
    )
    if len(segments) == 2:
        return {
            "kind": "symbol",
            "module": _unquote(segments[0], grammar),
            "symbol": _unquote(segments[1], grammar),
        }
    name = _unquote(text, grammar)
    if name in locals_:
        return {"kind": "local", "local": name}
    if name in parameters:
        return {"kind": "parameter", "parameter": name}
    raise ValueError("operand name is unresolved")


def _source_contract(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(child)
        for key, child in value.items()
        if key not in {"id", "resolved_symbol", "role", "symbol", "value_policy"}
    }


def _contract_type_identity(
    contract: dict[str, Any], imports: dict[str, tuple[str, str, str]]
) -> tuple[str, str, str] | None:
    alias = contract.get("type")
    if alias == "Boolean":
        return "kernel", "2.0.0", "Boolean"
    return imports.get(alias) if isinstance(alias, str) else None


def _operation_contract_matches(
    contract: dict[str, Any] | None,
    formal: dict[str, Any],
    imports: dict[str, tuple[str, str, str]],
) -> bool:
    if contract is None:
        return True
    formal_type = formal.get("type")
    return (
        isinstance(formal_type, dict)
        and _contract_type_identity(contract, imports)
        == (
            formal_type.get("package"),
            formal_type.get("version"),
            formal_type.get("id"),
        )
        and all(
            contract.get(member) == formal.get(member)
            for member in ("representation", "kind", "unit", "numeric_policy")
        )
    )


def _declared_result_contract(
    operation: dict[str, Any],
    imports: dict[str, tuple[str, str, str]],
) -> dict[str, Any]:
    result = operation.get("result")
    result_type = result.get("type") if isinstance(result, dict) else None
    if not isinstance(result, dict) or not isinstance(result_type, dict):
        raise ValueError("independent result declaration is malformed")
    coordinate = (
        result_type.get("package"),
        result_type.get("version"),
        result_type.get("id"),
    )
    aliases = [alias for alias, identity in imports.items() if identity == coordinate]
    if coordinate == ("kernel", "2.0.0", "Boolean"):
        type_alias = "Boolean"
    elif len(aliases) == 1:
        type_alias = aliases[0]
    else:
        raise ValueError("independent result type is unresolved")
    return {
        "type": type_alias,
        **{
            member: deepcopy(result[member])
            for member in (
                "representation",
                "kind",
                "unit",
                "domain_kind",
                "domain",
                "numeric_policy",
            )
            if member in result
        },
    }


def _infer_result(
    operation: dict[str, Any],
    ports: list[str],
    contracts: list[dict[str, Any] | None],
    fallback: dict[str, Any],
    imports: dict[str, tuple[str, str, str]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    anchor = next((row for row in contracts if isinstance(row, dict)), fallback)
    values = {
        port: deepcopy(contract or anchor)
        for port, contract in zip(ports, contracts, strict=True)
    }
    rules = policy.get("local_result_inference")
    if not isinstance(rules, list):
        raise ValueError("independent result policy is malformed")
    by_node = {
        row.get("node"): row
        for row in rules
        if isinstance(row, dict) and isinstance(row.get("node"), str)
    }

    def interval(contract: dict[str, Any]) -> tuple[int, int] | None:
        domain = contract.get("domain")
        if (
            contract.get("domain_kind") != "closed-interval"
            or not isinstance(domain, dict)
            or not isinstance(domain.get("minimum"), int)
            or not isinstance(domain.get("maximum"), int)
        ):
            return None
        return cast(int, domain["minimum"]), cast(int, domain["maximum"])

    def with_interval(
        contract: dict[str, Any], bounds: tuple[int, int]
    ) -> dict[str, Any]:
        projected = deepcopy(contract)
        projected["domain_kind"] = "closed-interval"
        projected["domain"] = {
            "minimum": max(bounds[0], -(2**63)),
            "maximum": min(bounds[1], 2**63 - 1),
        }
        return projected

    for instruction in operation.get("body", []):
        rule = (
            by_node.get(instruction.get("node"))
            if isinstance(instruction, dict)
            else None
        )
        target_member = rule.get("target_member") if isinstance(rule, dict) else None
        target = (
            instruction.get(target_member) if isinstance(target_member, str) else None
        )
        if not isinstance(rule, dict) or not isinstance(target, str):
            raise ValueError("independent inference instruction is unresolved")
        rule_id = rule.get("rule")
        if rule_id == "literal-closed-interval":
            literal = instruction.get(rule["literal_member"])
            if not isinstance(literal, int):
                raise ValueError("independent literal inference is malformed")
            values[target] = with_interval(anchor, (literal, literal))
        elif rule_id == "copy-contract":
            values[target] = deepcopy(values[instruction[rule["source_member"]]])
        elif rule_id in {"closed-interval-maximum", "closed-interval-subtract"}:
            left_name, right_name = [
                instruction[member] for member in rule["operand_members"]
            ]
            left, right = values[left_name], values[right_name]
            left_bounds, right_bounds = interval(left), interval(right)
            if left_bounds is None or right_bounds is None:
                values[target] = deepcopy(left)
            elif rule_id == "closed-interval-subtract":
                values[target] = with_interval(
                    left,
                    (
                        left_bounds[0] - right_bounds[1],
                        left_bounds[1] - right_bounds[0],
                    ),
                )
            else:
                values[target] = with_interval(
                    left,
                    (
                        max(left_bounds[0], right_bounds[0]),
                        max(left_bounds[1], right_bounds[1]),
                    ),
                )
        elif rule_id == "declared-result-contract":
            values[target] = _declared_result_contract(operation, imports)
        else:
            raise ValueError("independent inference rule is unknown")
    result = operation["result"]
    source_policy = policy["operation_result_source"]
    source = result[source_policy["source_member"]]
    if source.get("kind") != source_policy["kind"]:
        raise ValueError("independent result source kind is malformed")
    return values[source[source_policy["name_member"]]]


def parse_canonical(
    expression: str,
    request: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, Any]:
    grammar, _operations = _authority(language_bundle)
    policy = _conversion_policy(language_bundle)
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    parameters = {
        row["id"]: _source_contract(row) for row in request["formula"]["parameters"]
    }
    module = request["module"]
    module_id = module["id"]
    imports = {
        row["alias"]: (row["package"], row["version"], row["symbol"])
        for row in module["imports"]
    }
    symbols: dict[tuple[str, str], dict[str, Any]] = {}
    for row in module.get("symbols", []):
        resolved = row.get("resolved_symbol")
        coordinate = (
            (resolved["module"], resolved["name"])
            if isinstance(resolved, dict)
            else (module_id, row["symbol"])
        )
        symbols[coordinate] = _source_contract(row)
    declarations = {(module_id, row["id"]): row for row in module.get("formulas", [])}
    lines = expression.split("\n")
    if len(lines) == 1:
        operand = _parse_operand(lines[0], grammar, set(), set(parameters))
        if operand.get("kind") == "parameter":
            return {"node": "parameter", "parameter": operand["parameter"]}
        return {"nodes": [], "result": operand}
    notations = _selected_notations(request, language_bundle)
    functions = {
        notation["name"]: (operation, notation)
        for operation, notation in notations
        if notation["kind"] == "function"
    }
    infixes = {
        notation["token"]: (operation, notation)
        for operation, notation in notations
        if notation["kind"] == "infix"
    }
    locals_: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []

    def typed_operand(text: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        operand = _parse_operand(text, grammar, set(locals_), set(parameters))
        kind = operand["kind"]
        if kind == "parameter":
            return operand, parameters[operand["parameter"]]
        if kind == "local":
            return operand, locals_[cast(str, operand["local"])]
        if kind == "symbol":
            contract = symbols.get(
                (cast(str, operand["module"]), cast(str, operand["symbol"]))
            )
            if contract is None:
                raise ValueError("independent Symbol contract is unresolved")
            return operand, contract
        return operand, None

    def operation_node(
        local: str,
        operation: dict[str, Any],
        notation: dict[str, Any],
        values: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ports = cast(list[str], notation["ordered_ports"])
        if len(ports) != len(values):
            raise ValueError("independent Operation arity is malformed")
        operands = [typed_operand(value) for value in values]
        formals = {row["id"]: row for row in operation["inputs"]}
        if set(ports) != set(formals) or any(
            not _operation_contract_matches(contract, formals[port], imports)
            for port, (_operand, contract) in zip(ports, operands, strict=True)
        ):
            raise ValueError("independent Operation port contract is incompatible")
        result = _infer_result(
            operation,
            ports,
            [contract for _operand, contract in operands],
            _source_contract(request["formula"]["result"]),
            imports,
            policy,
        )
        return (
            {
                "id": local,
                "node": "operation-call",
                "operation": {
                    "package": operation["package"],
                    "version": operation["version"],
                    "id": operation["id"],
                },
                "arguments": [
                    {"port": port, "operand": operand}
                    for port, (operand, _contract) in zip(ports, operands, strict=True)
                ],
                "result": result,
            },
            result,
        )

    for line in lines[:-1]:
        if not line.startswith("let ") or not line.endswith(";"):
            raise ValueError("canonical binding line is malformed")
        assignment = _split_outside(line[4:-1], " = ", quote, escape)
        if len(assignment) != 2:
            raise ValueError("canonical binding assignment is malformed")
        local = _unquote(assignment[0], grammar)
        rhs = assignment[1]
        if local in locals_ or local in parameters:
            raise ValueError("independent binding local is ambiguous")
        if rhs.startswith("if "):
            branches = _split_outside(rhs[3:], " then ", quote, escape)
            tails = (
                _split_outside(branches[1], " else ", quote, escape)
                if len(branches) == 2
                else []
            )
            if len(tails) != 2:
                raise ValueError("conditional is malformed")
            condition, condition_contract = typed_operand(branches[0])
            when_true, true_contract = typed_operand(tails[0])
            when_false, false_contract = typed_operand(tails[1])
            if (
                condition_contract is None
                or _contract_type_identity(condition_contract, imports)
                != ("kernel", "2.0.0", "Boolean")
                or true_contract is None
                or true_contract != false_contract
            ):
                raise ValueError("independent conditional contract is incompatible")
            node = {
                "id": local,
                "node": "conditional",
                "condition": condition,
                "when_true": when_true,
                "when_false": when_false,
            }
            result_contract = deepcopy(true_contract)
        elif rhs.endswith(")") and "(" in rhs:
            head, arguments_text = rhs.split("(", 1)
            arguments = (
                _split_outside(arguments_text[:-1], ", ", quote, escape)
                if arguments_text[:-1]
                else []
            )
            if head in functions:
                operation, notation = functions[head]
                node, result_contract = operation_node(
                    local, operation, notation, arguments
                )
            else:
                coordinate = _split_outside(head, ".", quote, escape)
                if len(coordinate) != 2:
                    raise ValueError("call coordinate is malformed")
                named = [
                    _split_outside(value, " = ", quote, escape) for value in arguments
                ]
                declaration = declarations.get(
                    (_unquote(coordinate[0], grammar), _unquote(coordinate[1], grammar))
                )
                if declaration is None:
                    raise ValueError("independent Formula coordinate is unresolved")
                expected_parameters = {
                    row["id"]: _source_contract(row)
                    for row in declaration["parameters"]
                }
                parsed_arguments = {
                    _unquote(value[0], grammar): typed_operand(value[1])
                    for value in named
                    if len(value) == 2
                }
                if set(parsed_arguments) != set(expected_parameters) or any(
                    contract != expected_parameters[parameter]
                    for parameter, (_operand, contract) in parsed_arguments.items()
                ):
                    raise ValueError("independent Formula argument is incompatible")
                node = {
                    "id": local,
                    "node": "formula-call",
                    "formula": {
                        "module": _unquote(coordinate[0], grammar),
                        "id": _unquote(coordinate[1], grammar),
                    },
                    "arguments": sorted(
                        [
                            {
                                "parameter": parameter,
                                "operand": operand,
                            }
                            for parameter, (
                                operand,
                                _contract,
                            ) in parsed_arguments.items()
                        ],
                        key=lambda row: cast(str, row["parameter"]),
                    ),
                }
                result_contract = _source_contract(declaration["result"])
        else:
            matches = [
                token
                for token in infixes
                if len(_split_outside(rhs, f" {token} ", quote, escape)) == 2
            ]
            if len(matches) != 1:
                raise ValueError("infix call is unresolved or ambiguous")
            token = matches[0]
            operation, notation = infixes[token]
            values = _split_outside(rhs, f" {token} ", quote, escape)
            node, result_contract = operation_node(local, operation, notation, values)
        nodes.append(node)
        locals_[local] = result_contract
    result_operand, result_contract = typed_operand(lines[-1])
    if result_contract != _source_contract(request["formula"]["result"]):
        raise ValueError("independent Formula result contract is incompatible")
    return {
        "nodes": nodes,
        "result": result_operand,
    }


def admit_pair(request: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    formula = request.get("formula")
    if (
        not isinstance(formula, dict)
        or not isinstance(formula.get("body"), dict)
        or not isinstance(formula.get("expression"), str)
    ):
        return False
    body = cast(dict[str, Any], formula["body"])
    expression = cast(str, formula["expression"])
    try:
        rendered = render_body(body, request, language_bundle)
        parsed = parse_canonical(expression, request, language_bundle)
    except (KeyError, TypeError, ValueError):
        return False
    return expression == rendered and canonical_bytes(
        cast(JsonValue, parsed)
    ) == canonical_bytes(cast(JsonValue, body))
