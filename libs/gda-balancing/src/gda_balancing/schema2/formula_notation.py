"""Authority-driven canonical Formula notation conversion."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.schema2.authority import AdmittedAuthorityContext

_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_IDENTIFIERS = frozenset({"else", "if", "let", "then"})


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    offset: int


@dataclass(frozen=True)
class _OperationNotation:
    coordinate: tuple[str, str, str]
    declaration: dict[str, Any]
    notation: dict[str, Any]


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Formula notation requires a non-empty identifier")
    if _BARE_IDENTIFIER.fullmatch(value) and value not in _RESERVED_IDENTIFIERS:
        return value
    return "`" + value.replace("\\", "\\\\").replace("`", "\\`") + "`"


def _operation_catalog(
    authority_context: AdmittedAuthorityContext,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    catalog: dict[tuple[str, str, str], dict[str, Any]] = {}
    packages = cast(
        list[dict[str, Any]], authority_context.language_bundle["language"]["packages"]
    )
    for package in packages:
        package_id = cast(str, package["id"])
        version = cast(str, package["version"])
        for closure in cast(list[dict[str, Any]], package["semantic_closure"]):
            if closure.get("authority_path") != "language.operations":
                continue
            for operation in cast(list[dict[str, Any]], closure["definitions"]):
                catalog[(package_id, version, cast(str, operation["id"]))] = operation
    return catalog


def _selected_operation_notations(
    request: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
) -> tuple[_OperationNotation, ...]:
    requirements = request.get("package_requirements")
    if not isinstance(requirements, list):
        raise ValueError("Formula context has no package requirements")
    selected = {
        (item.get("id"), item.get("version"))
        for item in requirements
        if isinstance(item, dict)
    }
    declarations: list[_OperationNotation] = []
    for coordinate, operation in _operation_catalog(authority_context).items():
        if coordinate[:2] not in selected or operation.get("purity") != "pure":
            continue
        extensions = operation.get("extensions")
        notation = (
            extensions.get("standard.formula-notation")
            if isinstance(extensions, dict)
            else None
        )
        if isinstance(notation, dict):
            declarations.append(_OperationNotation(coordinate, operation, notation))
    return tuple(declarations)


def _lex(expression: str, operator_tokens: tuple[str, ...]) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    ordered_operators = sorted(operator_tokens, key=len, reverse=True)
    while index < len(expression):
        character = expression[index]
        if character.isspace():
            index += 1
            continue
        if character in "()=;,.":
            tokens.append(_Token(character, character, index))
            index += 1
            continue
        if character == "`":
            start = index
            index += 1
            quoted_chars: list[str] = []
            while index < len(expression) and expression[index] != "`":
                if expression[index] == "\\":
                    index += 1
                    if index >= len(expression) or expression[index] not in {"`", "\\"}:
                        raise ValueError(
                            f"invalid quoted identifier escape at byte {index}"
                        )
                quoted_chars.append(expression[index])
                index += 1
            if index >= len(expression):
                raise ValueError(f"unterminated quoted identifier at byte {start}")
            index += 1
            tokens.append(_Token("identifier", "".join(quoted_chars), start))
            continue
        if character.isdigit() or (
            character == "-"
            and index + 1 < len(expression)
            and expression[index + 1].isdigit()
        ):
            start = index
            index += 1
            while index < len(expression) and expression[index].isdigit():
                index += 1
            tokens.append(_Token("integer", expression[start:index], start))
            continue
        identifier = re.match(r"[A-Za-z_][A-Za-z0-9_]*", expression[index:])
        if identifier is not None:
            identifier_value = identifier.group(0)
            tokens.append(_Token("identifier", identifier_value, index))
            index += len(identifier_value)
            continue
        operator = next(
            (token for token in ordered_operators if expression.startswith(token, index)),
            None,
        )
        if operator is not None:
            tokens.append(_Token("operator", operator, index))
            index += len(operator)
            continue
        raise ValueError(f"unexpected Formula notation token at byte {index}")
    tokens.append(_Token("eof", "", len(expression)))
    return tokens


class _FormulaParser:
    def __init__(
        self,
        expression: str,
        request: dict[str, Any],
        authority_context: AdmittedAuthorityContext,
    ) -> None:
        self.request = request
        formula = request.get("formula")
        if not isinstance(formula, dict):
            raise ValueError("Formula parse request has no declaration context")
        self.formula = formula
        parameters = formula.get("parameters")
        if not isinstance(parameters, list):
            raise ValueError("Formula declaration has no parameter context")
        self.contracts: dict[str, dict[str, Any]] = {
            cast(str, item["id"]): deepcopy(item)
            for item in parameters
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for contract in self.contracts.values():
            contract.pop("id", None)
        self.locals: dict[str, dict[str, Any]] = {}
        self.notations = _selected_operation_notations(request, authority_context)
        operators = tuple(
            cast(str, item.notation["token"])
            for item in self.notations
            if item.notation.get("kind") == "infix"
            and isinstance(item.notation.get("token"), str)
        )
        self.tokens = _lex(expression, operators)
        self.index = 0

    def current(self) -> _Token:
        return self.tokens[self.index]

    def take(self, kind: str, value: str | None = None) -> _Token:
        token = self.current()
        if token.kind != kind or (value is not None and token.value != value):
            expected = value if value is not None else kind
            raise ValueError(
                f"expected {expected!r} at byte {token.offset}, got {token.value!r}"
            )
        self.index += 1
        return token

    def operation_for(self, *, kind: str, spelling: str) -> _OperationNotation:
        matches = [
            item
            for item in self.notations
            if item.notation.get("kind") == kind
            and item.notation.get("token" if kind == "infix" else "name") == spelling
        ]
        if len(matches) != 1:
            raise ValueError(f"Formula notation {spelling!r} is unresolved or ambiguous")
        return matches[0]

    def operand(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        token = self.current()
        if token.kind == "integer":
            self.index += 1
            return {"kind": "literal", "value": int(token.value)}, None
        if token.kind != "identifier":
            raise ValueError(f"expected Formula operand at byte {token.offset}")
        self.index += 1
        segments = [token.value]
        while self.current().kind == ".":
            self.index += 1
            segments.append(self.take("identifier").value)
        if len(segments) == 1 and segments[0] in self.locals:
            return (
                {"kind": "local", "local": segments[0]},
                self.locals[segments[0]],
            )
        if len(segments) == 1 and segments[0] in self.contracts:
            return (
                {"kind": "parameter", "parameter": segments[0]},
                self.contracts[segments[0]],
            )
        if len(segments) == 2:
            return (
                {"kind": "symbol", "module": segments[0], "symbol": segments[1]},
                None,
            )
        raise ValueError(f"Formula name {'.'.join(segments)!r} is unresolved")

    def parenthesized_operand(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if self.current().kind != "(":
            return self.operand()
        self.index += 1
        parsed = self.parenthesized_operand()
        self.take(")")
        return parsed

    def right_hand_side(self, local: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if (
            self.current().kind == "identifier"
            and self.tokens[self.index + 1].kind == "("
        ):
            name = self.take("identifier").value
            operation = self.operation_for(kind="function", spelling=name)
            self.take("(")
            operands: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
            if self.current().kind != ")":
                operands.append(self.parenthesized_operand())
                while self.current().kind == ",":
                    self.index += 1
                    operands.append(self.parenthesized_operand())
            self.take(")")
            return self.operation_node(local, operation, operands)
        self.take_parentheses_before_expression()
        left = self.parenthesized_operand()
        operator = self.take("operator").value
        right = self.parenthesized_operand()
        self.take_parentheses_after_expression()
        return self.operation_node(
            local,
            self.operation_for(kind="infix", spelling=operator),
            [left, right],
        )

    def take_parentheses_before_expression(self) -> None:
        self.expression_parentheses = 0
        while self.current().kind == "(":
            self.index += 1
            self.expression_parentheses += 1

    def take_parentheses_after_expression(self) -> None:
        for _ in range(self.expression_parentheses):
            self.take(")")

    def operation_node(
        self,
        local: str,
        operation: _OperationNotation,
        operands: list[tuple[dict[str, Any], dict[str, Any] | None]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ports = operation.notation.get("ordered_ports")
        if not isinstance(ports, list) or len(ports) != len(operands):
            raise ValueError("Formula call does not totally bind notation ports")
        inferred = next((contract for _operand, contract in operands if contract), None)
        result = deepcopy(inferred or self.formula.get("result"))
        if not isinstance(result, dict):
            raise ValueError("Formula local result cannot be inferred")
        node = {
            "id": local,
            "node": "operation-call",
            "operation": {
                "package": operation.coordinate[0],
                "version": operation.coordinate[1],
                "id": operation.coordinate[2],
            },
            "arguments": [
                {"port": port, "operand": operand}
                for port, (operand, _contract) in zip(ports, operands, strict=True)
            ],
            "result": result,
        }
        return node, result

    def parse(self) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        while self.current().kind == "identifier" and self.current().value == "let":
            self.index += 1
            local = self.take("identifier").value
            if local in self.locals or local in self.contracts:
                raise ValueError("Formula local identity is duplicate or captures a parameter")
            self.take("=")
            node, contract = self.right_hand_side(local)
            self.take(";")
            nodes.append(node)
            self.locals[local] = contract
        result, _contract = self.parenthesized_operand()
        self.take("eof")
        if not nodes and result.get("kind") == "parameter":
            return {"node": "parameter", "parameter": result["parameter"]}
        return {"nodes": nodes, "result": result}


def parse_formula_expression(
    request: dict[str, Any],
    authority_context: AdmittedAuthorityContext,
) -> dict[str, Any]:
    """Parse one contextual expression into a canonical structured Formula body."""
    formula = request.get("formula")
    expression = formula.get("expression") if isinstance(formula, dict) else None
    if not isinstance(expression, str):
        raise ValueError("Formula parse request has no expression")
    return _FormulaParser(expression, request, authority_context).parse()


def _render_operand(operand: object) -> str:
    if not isinstance(operand, dict):
        raise ValueError("Formula notation operand must be an object")
    kind = operand.get("kind")
    if kind == "parameter":
        return _identifier(operand.get("parameter"))
    if kind == "local":
        return _identifier(operand.get("local"))
    if kind == "symbol":
        return ".".join(
            (_identifier(operand.get("module")), _identifier(operand.get("symbol")))
        )
    if kind == "literal" and isinstance(operand.get("value"), int):
        return str(operand["value"])
    raise ValueError("Formula notation operand kind is not admitted")


def _render_operation_call(
    node: dict[str, Any],
    catalog: dict[tuple[str, str, str], dict[str, Any]],
) -> str:
    coordinate = node.get("operation")
    if not isinstance(coordinate, dict):
        raise ValueError("Formula operation call has no exact coordinate")
    operation = catalog.get(
        (
            cast(str, coordinate.get("package")),
            cast(str, coordinate.get("version")),
            cast(str, coordinate.get("id")),
        )
    )
    if operation is None or operation.get("purity") != "pure":
        raise ValueError("Formula operation call is unresolved or effectful")
    extensions = operation.get("extensions")
    notation = (
        extensions.get("standard.formula-notation")
        if isinstance(extensions, dict)
        else None
    )
    if not isinstance(notation, dict):
        raise ValueError("Formula operation has no admitted notation declaration")
    arguments = node.get("arguments")
    ordered_ports = notation.get("ordered_ports")
    if not isinstance(arguments, list) or not isinstance(ordered_ports, list):
        raise ValueError("Formula notation has no total ordered port mapping")
    by_port = {
        argument.get("port"): argument.get("operand")
        for argument in arguments
        if isinstance(argument, dict)
    }
    if set(by_port) != set(ordered_ports) or len(by_port) != len(arguments):
        raise ValueError("Formula operation arguments do not match notation ports")
    rendered = [_render_operand(by_port[port]) for port in ordered_ports]
    if notation.get("kind") == "infix" and len(rendered) == 2:
        token = notation.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("Formula infix notation has no token")
        return f"{rendered[0]} {token} {rendered[1]}"
    if notation.get("kind") == "function":
        name = notation.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Formula function notation has no name")
        return f"{name}({', '.join(rendered)})"
    raise ValueError("Formula notation declaration kind is not admitted")


def render_formula_body(
    body: object,
    authority_context: AdmittedAuthorityContext,
) -> str:
    """Render one structured Formula body from sealed operation notation."""
    if not isinstance(body, dict):
        raise ValueError("Formula body must be an object")
    if set(body) == {"node", "parameter"} and body.get("node") == "parameter":
        return _identifier(body.get("parameter"))
    nodes = body.get("nodes")
    result = body.get("result")
    if not isinstance(nodes, list) or not isinstance(result, dict):
        raise ValueError("Formula body is not an admitted program")
    catalog = _operation_catalog(authority_context)
    lines: list[str] = []
    seen_locals: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or node.get("node") != "operation-call":
            raise ValueError("Formula node has no admitted renderer")
        local = node.get("id")
        if not isinstance(local, str) or local in seen_locals:
            raise ValueError("Formula local identities must be unique")
        seen_locals.add(local)
        lines.append(
            f"let {_identifier(local)} = {_render_operation_call(node, catalog)};"
        )
    lines.append(_render_operand(result))
    return "\n".join(lines)
