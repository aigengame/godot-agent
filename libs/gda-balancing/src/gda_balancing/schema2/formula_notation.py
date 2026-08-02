"""Authority-driven canonical Formula notation conversion."""

from __future__ import annotations

import re
from typing import Any, cast

from gda_balancing.schema2.authority import AdmittedAuthorityContext

_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_IDENTIFIERS = frozenset({"else", "if", "let", "then"})


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
