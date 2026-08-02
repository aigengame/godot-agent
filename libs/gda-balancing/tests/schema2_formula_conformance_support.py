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


def _authority(language_bundle: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
    return grammar, cast(list[dict[str, Any]], language_bundle["language"]["operations"])


def _identifier(value: Any, grammar: dict[str, Any]) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("identifier is empty")
    if re.fullmatch(cast(str, grammar["bare_identifier_pattern"]), value) and value not in grammar["reserved_identifiers"]:
        return value
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    return quote + value.replace(escape, escape + escape).replace(quote, escape + quote) + quote


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
        coordinate = (operation.get("type", {}).get("package"), operation.get("version"))
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
        if coordinate in selected and operation.get("purity") == "pure" and isinstance(notation, dict):
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
        (cast(str, operation.get("package", "")), cast(str, operation["version"]), cast(str, operation["id"])): notation
        for operation, notation in notations
    }
    if not isinstance(body.get("nodes"), list) or not isinstance(body.get("result"), dict):
        raise ValueError("body is not a Formula program")
    lines: list[str] = []
    for node in cast(list[dict[str, Any]], body["nodes"]):
        kind = node.get("node")
        if kind == "operation-call":
            coordinate = cast(dict[str, Any], node["operation"])
            notation = by_coordinate.get(
                (cast(str, coordinate["package"]), cast(str, coordinate["version"]), cast(str, coordinate["id"]))
            )
            if notation is None:
                raise ValueError("operation notation is unresolved")
            arguments = {row["port"]: row["operand"] for row in node["arguments"]}
            values = [_operand(arguments[port], grammar) for port in notation["ordered_ports"]]
            if notation["kind"] == "infix":
                rhs = f"{values[0]} {notation['token']} {values[1]}"
            else:
                rhs = f"{notation['name']}({', '.join(values)})"
        elif kind == "formula-call":
            coordinate = cast(dict[str, Any], node["formula"])
            name = ".".join((_identifier(coordinate["module"], grammar), _identifier(coordinate["id"], grammar)))
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


def _parse_operand(text: str, grammar: dict[str, Any], locals_: set[str], parameters: set[str]) -> dict[str, JsonValue]:
    text = text.strip()
    if re.fullmatch(r"-?[0-9]+", text):
        return {"kind": "literal", "value": int(text)}
    segments = _split_outside(text, ".", cast(str, grammar["identifier_quote"]), cast(str, grammar["escape_character"]))
    if len(segments) == 2:
        return {"kind": "symbol", "module": _unquote(segments[0], grammar), "symbol": _unquote(segments[1], grammar)}
    name = _unquote(text, grammar)
    if name in locals_:
        return {"kind": "local", "local": name}
    if name in parameters:
        return {"kind": "parameter", "parameter": name}
    raise ValueError("operand name is unresolved")


def parse_canonical(
    expression: str,
    request: dict[str, Any],
    language_bundle: dict[str, Any],
    reference_body: dict[str, Any],
) -> dict[str, Any]:
    grammar, _operations = _authority(language_bundle)
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    parameters = {row["id"] for row in request["formula"]["parameters"]}
    reference_nodes = {
        row["id"]: row for row in reference_body.get("nodes", []) if isinstance(row, dict)
    }
    lines = expression.split("\n")
    if len(lines) == 1:
        operand = _parse_operand(lines[0], grammar, set(), parameters)
        if operand.get("kind") == "parameter":
            return {"node": "parameter", "parameter": operand["parameter"]}
        return {"nodes": [], "result": operand}
    notations = _selected_notations(request, language_bundle)
    functions = {notation["name"]: (operation, notation) for operation, notation in notations if notation["kind"] == "function"}
    infixes = {notation["token"]: (operation, notation) for operation, notation in notations if notation["kind"] == "infix"}
    locals_: set[str] = set()
    nodes: list[dict[str, Any]] = []
    for line in lines[:-1]:
        if not line.startswith("let ") or not line.endswith(";"):
            raise ValueError("canonical binding line is malformed")
        assignment = _split_outside(line[4:-1], " = ", quote, escape)
        if len(assignment) != 2:
            raise ValueError("canonical binding assignment is malformed")
        local = _unquote(assignment[0], grammar)
        rhs = assignment[1]
        reference = reference_nodes.get(local)
        if reference is None:
            raise ValueError("binding local is absent from the body")
        if rhs.startswith("if "):
            branches = _split_outside(rhs[3:], " then ", quote, escape)
            tails = _split_outside(branches[1], " else ", quote, escape) if len(branches) == 2 else []
            if len(tails) != 2:
                raise ValueError("conditional is malformed")
            node = {
                "id": local,
                "node": "conditional",
                "condition": _parse_operand(branches[0], grammar, locals_, parameters),
                "when_true": _parse_operand(tails[0], grammar, locals_, parameters),
                "when_false": _parse_operand(tails[1], grammar, locals_, parameters),
            }
        elif rhs.endswith(")") and "(" in rhs:
            head, arguments_text = rhs.split("(", 1)
            arguments = _split_outside(arguments_text[:-1], ", ", quote, escape) if arguments_text[:-1] else []
            if head in functions:
                operation, notation = functions[head]
                node = {
                    "id": local,
                    "node": "operation-call",
                    "operation": {"package": reference["operation"]["package"], "version": operation["version"], "id": operation["id"]},
                    "arguments": [
                        {"port": port, "operand": _parse_operand(value, grammar, locals_, parameters)}
                        for port, value in zip(notation["ordered_ports"], arguments, strict=True)
                    ],
                    "result": deepcopy(reference["result"]),
                }
            else:
                coordinate = _split_outside(head, ".", quote, escape)
                if len(coordinate) != 2:
                    raise ValueError("call coordinate is malformed")
                named = [_split_outside(value, " = ", quote, escape) for value in arguments]
                node = {
                    "id": local,
                    "node": "formula-call",
                    "formula": {"module": _unquote(coordinate[0], grammar), "id": _unquote(coordinate[1], grammar)},
                    "arguments": sorted(
                        [
                            {"parameter": _unquote(value[0], grammar), "operand": _parse_operand(value[1], grammar, locals_, parameters)}
                            for value in named
                            if len(value) == 2
                        ],
                        key=lambda row: cast(str, row["parameter"]),
                    ),
                }
        else:
            matches = [token for token in infixes if len(_split_outside(rhs, f" {token} ", quote, escape)) == 2]
            if len(matches) != 1:
                raise ValueError("infix call is unresolved or ambiguous")
            token = matches[0]
            operation, notation = infixes[token]
            values = _split_outside(rhs, f" {token} ", quote, escape)
            node = {
                "id": local,
                "node": "operation-call",
                "operation": {"package": reference["operation"]["package"], "version": operation["version"], "id": operation["id"]},
                "arguments": [
                    {"port": port, "operand": _parse_operand(value, grammar, locals_, parameters)}
                    for port, value in zip(notation["ordered_ports"], values, strict=True)
                ],
                "result": deepcopy(reference["result"]),
            }
        nodes.append(node)
        locals_.add(local)
    return {"nodes": nodes, "result": _parse_operand(lines[-1], grammar, locals_, parameters)}


def admit_pair(request: dict[str, Any], language_bundle: dict[str, Any]) -> bool:
    formula = request.get("formula")
    if not isinstance(formula, dict) or not isinstance(formula.get("body"), dict) or not isinstance(formula.get("expression"), str):
        return False
    body = cast(dict[str, Any], formula["body"])
    expression = cast(str, formula["expression"])
    try:
        rendered = render_body(body, request, language_bundle)
        parsed = parse_canonical(expression, request, language_bundle, body)
    except (KeyError, TypeError, ValueError):
        return False
    return expression == rendered and canonical_bytes(cast(JsonValue, parsed)) == canonical_bytes(cast(JsonValue, body))
