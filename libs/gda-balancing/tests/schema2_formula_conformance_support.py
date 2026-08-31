"""Independent Formula-notation consumer for cross-implementation conformance.

This module deliberately does not import the production formula_notation module.
It projects the sealed Standard Schema grammar and Package-owned Operation notation,
then implements its own canonical renderer and line-oriented canonical parser.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes


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


def _resolution_profile(language_bundle: dict[str, Any]) -> dict[str, Any]:
    profiles = [
        row
        for row in language_bundle["language"]["resolution_profiles"]
        if row.get("default") is True
    ]
    if len(profiles) != 1:
        raise ValueError("independent consumer found no default resolution profile")
    return profiles[0]


def _formula_policy(language_bundle: dict[str, Any]) -> dict[str, Any]:
    policy = (
        _resolution_profile(language_bundle)
        .get("extensions", {})
        .get("standard.formula")
    )
    if not isinstance(policy, dict):
        raise ValueError("independent consumer found no Formula policy")
    return policy


def _conversion_policy(language_bundle: dict[str, Any]) -> dict[str, Any]:
    policy = _formula_policy(language_bundle).get("notation_conversion")
    infix_parser = policy.get("infix_parser") if isinstance(policy, dict) else None
    if (
        not isinstance(policy, dict)
        or policy.get("condition_contract") != "kernel-boolean"
        or policy.get("formula_argument_compatibility") != "exact-resolved-contract"
        or policy.get("formula_result_compatibility") != "exact-resolved-contract"
        or policy.get("literal_typing") != "selected-unique-formal-match"
        or policy.get("literal_result_inference") != "contextual-anchor"
        or policy.get("operation_argument_compatibility") != "exact-operation-formal"
        or policy.get("symbol_resolution") != "exact-module-coordinate"
        or not isinstance(infix_parser, dict)
        or infix_parser.get("algorithm") != "shunting-yard"
        or not isinstance(infix_parser.get("generated_local_separator"), str)
        or not infix_parser["generated_local_separator"]
    ):
        raise ValueError("independent consumer found no notation conversion policy")
    return policy


def _validate_context(
    request: dict[str, Any], language_bundle: dict[str, Any]
) -> list[dict[str, Any]]:
    language = language_bundle["language"]
    profile = _resolution_profile(language_bundle)
    schema_versions = [
        definition.get("schema", {})
        .get("properties", {})
        .get("schema_version", {})
        .get("const")
        for package in language["packages"]
        if package.get("id") == "standard.schema"
        for closure in package["semantic_closure"]
        if closure.get("authority_path") == "language.wire_schemas"
        for definition in closure["definitions"]
        if definition.get("artifact_kind") == "model-source-package"
    ]
    if len(schema_versions) != 1 or request.get("schema_version") != schema_versions[0]:
        raise ValueError("independent Formula source schema version is unavailable")
    requirements = request.get(profile["requirements_member"])
    if not isinstance(requirements, list):
        raise ValueError("independent Formula requirements are malformed")
    requirement_keys: set[tuple[str, str]] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise ValueError("independent Formula requirement is malformed")
        key = (
            requirement.get(profile["requirement_package_member"]),
            requirement.get(profile["requirement_version_member"]),
        )
        if not all(isinstance(item, str) for item in key) or key in requirement_keys:
            raise ValueError(
                "independent Formula requirement is malformed or duplicate"
            )
        requirement_keys.add(cast(tuple[str, str], key))
    packages = {(row["id"], row["version"]): row for row in language["packages"]}
    if any(key not in packages for key in requirement_keys):
        raise ValueError("independent Formula requirement is unresolved")
    if len({package for package, _version in requirement_keys}) != len(
        requirement_keys
    ):
        raise ValueError("independent Formula requirement version is ambiguous")
    current_module = request.get("module")
    modules = request.get("modules", [current_module])
    if not isinstance(current_module, dict) or not isinstance(modules, list):
        raise ValueError("independent Formula module closure is malformed")
    modules_by_id: dict[str, dict[str, Any]] = {}
    for module in modules:
        module_id = (
            module.get(profile["module_id_member"])
            if isinstance(module, dict)
            else None
        )
        if not isinstance(module_id, str) or module_id in modules_by_id:
            raise ValueError("independent Formula module closure is ambiguous")
        modules_by_id[module_id] = module
    current_id = current_module.get(profile["module_id_member"])
    if not isinstance(current_id, str) or current_id not in modules_by_id:
        raise ValueError("independent current module is outside its closure")
    closure_module = modules_by_id[current_id]
    formula_member = _formula_policy(language_bundle)["module_formulas_member"]
    for member in (
        profile["imports_member"],
        profile["symbols_member"],
        formula_member,
    ):
        if member in current_module and current_module[member] != closure_module.get(
            member, []
        ):
            raise ValueError("independent current module conflicts with its closure")
    for module in modules:
        imports = module.get(profile["imports_member"])
        if not isinstance(imports, list):
            raise ValueError("independent Formula imports are malformed")
        aliases: set[str] = set()
        for imported in imports:
            if not isinstance(imported, dict):
                raise ValueError("independent Formula import is malformed")
            alias = imported.get(profile["import_alias_member"])
            package_key = (
                imported.get(profile["import_package_member"]),
                imported.get(profile["import_version_member"]),
            )
            symbol = imported.get(profile["import_symbol_member"])
            if (
                not isinstance(alias, str)
                or alias in aliases
                or not all(isinstance(item, str) for item in package_key)
                or not isinstance(symbol, str)
            ):
                raise ValueError("independent Formula import is malformed or ambiguous")
            aliases.add(alias)
            package = packages.get(cast(tuple[str, str], package_key))
            exported_types = (
                {
                    row.get("id")
                    for row in package.get("exports", {}).get("types", [])
                    if isinstance(row, dict)
                }
                if isinstance(package, dict)
                else set()
            )
            if package_key not in requirement_keys or symbol not in exported_types:
                raise ValueError("independent Formula import is unresolved")
    return modules


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


def _formula_contract_matches(
    actual: dict[str, Any] | None,
    actual_imports: dict[str, tuple[str, str, str]],
    expected: dict[str, Any],
    expected_imports: dict[str, tuple[str, str, str]],
) -> bool:
    return (
        actual is not None
        and _contract_type_identity(actual, actual_imports)
        == _contract_type_identity(expected, expected_imports)
        and all(
            actual.get(member) == expected.get(member)
            for member in (
                "representation",
                "kind",
                "unit",
                "domain_kind",
                "domain",
                "numeric_policy",
            )
        )
    )


def _rebase_contract(
    contract: dict[str, Any],
    source_imports: dict[str, tuple[str, str, str]],
    target_imports: dict[str, tuple[str, str, str]],
) -> dict[str, Any]:
    identity = _contract_type_identity(contract, source_imports)
    if identity == ("kernel", "2.0.0", "Boolean"):
        alias = "Boolean"
    else:
        aliases = [
            name
            for name, coordinate in target_imports.items()
            if coordinate == identity
        ]
        if len(aliases) != 1:
            raise ValueError("independent Formula result type is unresolved")
        alias = aliases[0]
    rebased = deepcopy(contract)
    rebased["type"] = alias
    return rebased


def _notation_resource_usage(
    expression: str,
    grammar: dict[str, Any],
    request: dict[str, Any],
    language_bundle: dict[str, Any],
) -> tuple[int, int]:
    punctuation = {
        *cast(list[str], grammar["group_delimiters"]),
        cast(str, grammar["named_argument_operator"]),
        cast(str, grammar["binding_terminator"]),
        cast(str, grammar["argument_separator"]),
        cast(str, grammar["coordinate_separator"]),
    }
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    operators = sorted(
        (
            cast(str, notation["token"])
            for _operation, notation in _selected_notations(request, language_bundle)
            if notation.get("kind") == "infix"
        ),
        key=len,
        reverse=True,
    )
    whitespace = re.compile(cast(str, grammar["whitespace_pattern"]))
    identifier = re.compile(cast(str, grammar["identifier_token_pattern"]))
    integer = re.compile(cast(str, grammar["integer_literal_pattern"]))
    open_group, close_group = cast(list[str], grammar["group_delimiters"])
    index = 0
    count = 0
    depth = 0
    maximum_depth = 0
    while index < len(expression):
        skipped = whitespace.match(expression, index)
        if skipped is not None:
            index = skipped.end()
            continue
        character = expression[index]
        if character == quote:
            index += 1
            while index < len(expression) and expression[index] != quote:
                if expression[index] == escape:
                    index += 1
                index += 1
            if index >= len(expression):
                raise ValueError("independent quoted identifier is malformed")
            index += 1
        elif character in punctuation:
            index += 1
            if character == open_group:
                depth += 1
                maximum_depth = max(maximum_depth, depth)
            elif character == close_group:
                depth -= 1
        else:
            matched = integer.match(expression, index) or identifier.match(
                expression, index
            )
            if matched is not None:
                index = matched.end()
            else:
                operator = next(
                    (
                        token
                        for token in operators
                        if expression.startswith(token, index)
                    ),
                    None,
                )
                if operator is None:
                    raise ValueError("independent Formula token is unresolved")
                index += len(operator)
        count += 1
    if depth != 0:
        raise ValueError("independent Formula grouping is unbalanced")
    return count, maximum_depth


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
        elif rule_id in {
            "closed-interval-add",
            "closed-interval-floor-divide",
            "closed-interval-maximum",
            "closed-interval-multiply",
            "closed-interval-select",
            "closed-interval-subtract",
        }:
            left_name, right_name = [
                instruction[member] for member in rule["operand_members"]
            ]
            left, right = values[left_name], values[right_name]
            left_bounds, right_bounds = interval(left), interval(right)
            if left_bounds is None or right_bounds is None:
                values[target] = deepcopy(left)
            elif rule_id == "closed-interval-add":
                values[target] = with_interval(
                    left,
                    (
                        left_bounds[0] + right_bounds[0],
                        left_bounds[1] + right_bounds[1],
                    ),
                )
            elif rule_id == "closed-interval-subtract":
                values[target] = with_interval(
                    left,
                    (
                        left_bounds[0] - right_bounds[1],
                        left_bounds[1] - right_bounds[0],
                    ),
                )
            elif rule_id == "closed-interval-multiply":
                products = tuple(
                    left_value * right_value
                    for left_value in left_bounds
                    for right_value in right_bounds
                )
                values[target] = with_interval(left, (min(products), max(products)))
            elif rule_id == "closed-interval-floor-divide":
                if right_bounds[0] <= 0:
                    raise ValueError(
                        "independent floor-divide divisor domain is not positive"
                    )
                quotients = tuple(
                    left_value // right_value
                    for left_value in left_bounds
                    for right_value in right_bounds
                )
                values[target] = with_interval(left, (min(quotients), max(quotients)))
            elif rule_id == "closed-interval-select":
                values[target] = with_interval(
                    left,
                    (
                        min(left_bounds[0], right_bounds[0]),
                        max(left_bounds[1], right_bounds[1]),
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
    formula_policy = _formula_policy(language_bundle)
    modules = _validate_context(request, language_bundle)
    quote = cast(str, grammar["identifier_quote"])
    escape = cast(str, grammar["escape_character"])
    parameters = {
        row["id"]: _source_contract(row) for row in request["formula"]["parameters"]
    }
    module = request["module"]
    module_id = module["id"]
    imports_by_module = {
        row["id"]: {
            imported["alias"]: (
                imported["package"],
                imported["version"],
                imported["symbol"],
            )
            for imported in row["imports"]
        }
        for row in modules
    }
    imports = imports_by_module[module_id]
    symbols: dict[tuple[str, str], dict[str, Any]] = {}
    declarations: dict[
        tuple[str, str], tuple[dict[str, Any], dict[str, tuple[str, str, str]]]
    ] = {}
    for module_row in modules:
        declaration_module = module_row["id"]
        for row in module_row.get("symbols", []):
            resolved = row.get("resolved_symbol")
            coordinate = (
                (resolved["module"], resolved["name"])
                if isinstance(resolved, dict)
                else (declaration_module, row["symbol"])
            )
            symbols[coordinate] = _rebase_contract(
                _source_contract(row),
                imports_by_module[declaration_module],
                imports,
            )
        for row in module_row.get("formulas", []):
            declarations[(declaration_module, row["id"])] = (
                row,
                imports_by_module[declaration_module],
            )
    lines = expression.split("\n")
    if len(expression.encode("utf-8")) > grammar["max_expression_bytes"]:
        raise ValueError("independent Formula expression exceeds its byte bound")
    token_count, group_depth = _notation_resource_usage(
        expression, grammar, request, language_bundle
    )
    if token_count > grammar["max_tokens"]:
        raise ValueError("independent Formula expression exceeds its token bound")
    if group_depth > grammar["max_group_depth"]:
        raise ValueError("independent Formula expression exceeds its group-depth bound")
    if len(lines) - 1 > formula_policy["max_nodes_per_formula"]:
        raise ValueError("independent Formula expression exceeds its node bound")
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

    if len(lines) == 1:
        operand, result_contract = typed_operand(lines[0])
        expected = _source_contract(request["formula"]["result"])
        if result_contract is None and operand.get("kind") == "literal":
            value = operand.get("value")
            domain = expected.get("domain")
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not isinstance(domain, dict)
                or not isinstance(domain.get("minimum"), int)
                or not isinstance(domain.get("maximum"), int)
                or not domain["minimum"] <= value <= domain["maximum"]
            ):
                raise ValueError("independent literal result is incompatible")
            result_contract = expected
        if result_contract != expected:
            raise ValueError("independent Formula result contract is incompatible")
        if operand.get("kind") == "parameter":
            return {"node": "parameter", "parameter": operand["parameter"]}
        return {"nodes": [], "result": operand}

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
                resolved_declaration = declarations.get(
                    (_unquote(coordinate[0], grammar), _unquote(coordinate[1], grammar))
                )
                if resolved_declaration is None:
                    raise ValueError("independent Formula coordinate is unresolved")
                declaration, declaration_imports = resolved_declaration
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
                    not _formula_contract_matches(
                        contract,
                        imports,
                        expected_parameters[parameter],
                        declaration_imports,
                    )
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
                result_contract = _rebase_contract(
                    _source_contract(declaration["result"]),
                    declaration_imports,
                    imports,
                )
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
