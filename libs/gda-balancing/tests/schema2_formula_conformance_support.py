"""Independent Formula-notation consumer for cross-implementation conformance.

This module deliberately does not import the production formula_notation module.
It projects the sealed Standard Schema grammar and Package-owned Operation notation,
then implements its own canonical renderer and line-oriented canonical parser.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, cast

import jsonschema

from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from schema2_bootstrap_conformance_support import (
    _consumer_b_inline_parameter_operand,
    _consumer_b_value_matches,
)


def _source_definition(language_bundle: dict[str, Any]) -> dict[str, Any]:
    schemas = [
        definition
        for package in language_bundle["language"]["packages"]
        for closure in package["semantic_closure"]
        if closure.get("authority_path") == "language.wire_schemas"
        for definition in closure["definitions"]
        if definition.get("protocol_role") == "model-source-package"
    ]
    if len(schemas) != 1:
        raise ValueError("independent consumer found no unique Model Source schema")
    return schemas[0]


def _source_schema(language_bundle: dict[str, Any]) -> dict[str, Any]:
    return _source_definition(language_bundle)["schema"]


def _authority(
    language_bundle: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grammar = _source_definition(language_bundle).get("formula_grammar")
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


def _formula_policy(
    language_bundle: dict[str, Any], *, kernel: dict[str, Any]
) -> dict[str, Any]:
    policy = _resolution_profile(language_bundle)["formula_resolution"]
    contract = kernel["meta_format"]["language_definitions"]["collections"][
        "resolution_profiles"
    ]["field_types"]["formula_resolution"]
    if not _consumer_b_value_matches(policy, contract, language_bundle):
        raise ValueError("independent consumer found no Formula policy")
    return policy


def _inline_source_parameter(
    policy: dict[str, Any], kernel: dict[str, Any]
) -> tuple[str, str, str]:
    kind, reference = _consumer_b_inline_parameter_operand(kernel["meta_format"])
    rows = policy["inline_body_normalizations"]
    if (
        len(rows) != 1
        or set(rows[0]) != {"parameter_member"}
        or not isinstance(rows[0]["parameter_member"], str)
        or not rows[0]["parameter_member"]
        or rows[0]["parameter_member"] == "node"
    ):
        raise ValueError("independent inline Formula selector is ambiguous")
    return kind, reference, rows[0]["parameter_member"]


def normalize_source_body(
    body: dict[str, Any], language_bundle: dict[str, Any], *, kernel: dict[str, Any]
) -> dict[str, Any]:
    """Independently adapt the declared Source field to the fixed operand role."""
    policy = _formula_policy(language_bundle, kernel=kernel)
    kind, reference, source_member = _inline_source_parameter(policy, kernel)
    if "node" not in body:
        return deepcopy(body)
    if (
        body.get("node") != kind
        or set(body) != {"node", source_member}
        or not isinstance(body[source_member], str)
        or not body[source_member]
    ):
        raise ValueError("independent inline Formula body is malformed")
    return {
        policy["body_nodes_member"]: [],
        policy["body_result_member"]: {"kind": kind, reference: body[source_member]},
    }


def _validate_context(
    request: dict[str, Any], language_bundle: dict[str, Any], *, kernel: dict[str, Any]
) -> list[dict[str, Any]]:
    language = language_bundle["language"]
    profile = _resolution_profile(language_bundle)
    source_schema = _source_schema(language_bundle)
    schema_version = source_schema["properties"][profile["schema_version_member"]][
        "const"
    ]
    if request.get("schema_version") != schema_version:
        raise ValueError("independent Formula source schema version is unavailable")
    import_schema = source_schema["properties"][profile["modules_member"]]["items"][
        "properties"
    ][profile["imports_member"]]["items"]
    import_validator = jsonschema.Draft202012Validator(source_schema).evolve(
        schema=import_schema
    )
    requirements = request.get("package_requirements")
    if not isinstance(requirements, list):
        raise ValueError("independent Formula requirements are malformed")
    requirement_keys: set[str] = set()
    for requirement in requirements:
        if (
            not isinstance(requirement, str)
            or not requirement
            or requirement in requirement_keys
        ):
            raise ValueError(
                "independent Formula requirement is malformed or duplicate"
            )
        requirement_keys.add(requirement)
    packages = {row["id"]: row for row in language["packages"]}
    if any(key not in packages for key in requirement_keys):
        raise ValueError("independent Formula requirement is unresolved")
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
    formula_member = _formula_policy(language_bundle, kernel=kernel)[
        "module_formulas_member"
    ]
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
            if not import_validator.is_valid(imported):
                raise ValueError("independent Formula import is malformed")
            alias = imported.get(profile["import_alias_member"])
            package_key = imported.get(profile["import_package_member"])
            symbol = imported.get(profile["import_symbol_member"])
            if (
                not isinstance(alias, str)
                or alias in aliases
                or not isinstance(package_key, str)
                or not isinstance(symbol, str)
            ):
                raise ValueError("independent Formula import is malformed or ambiguous")
            aliases.add(alias)
            package = packages.get(package_key)
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
    request: dict[str, Any], language_bundle: dict[str, Any], kernel: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    notation_validator = jsonschema.Draft202012Validator(
        _source_definition(language_bundle)["operation_notation_schema"]
    )
    operation_source = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["source_notation"]["operation_source"]
    selected = set(request.get("package_requirements", []))
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for package in language_bundle["language"]["packages"]:
        if package["id"] not in selected:
            continue
        for entry in package["semantic_closure"]:
            if entry["authority_path"] != operation_source["authority_path"]:
                continue
            for operation in entry["definitions"]:
                notation = operation.get("extensions", {}).get(
                    operation_source["extension_member"]
                )
                if operation.get("purity") == "pure" and isinstance(notation, dict):
                    if not notation_validator.is_valid(notation):
                        raise ValueError(
                            "Operation notation violates its selected schema"
                        )
                    rows.append(({**operation, "package": package["id"]}, notation))
    return rows


def render_body(
    body: dict[str, Any],
    request: dict[str, Any],
    language_bundle: dict[str, Any],
    *,
    kernel: dict[str, Any],
) -> str:
    _validate_context(request, language_bundle, kernel=kernel)
    grammar, _operations = _authority(language_bundle)
    body = normalize_source_body(body, language_bundle, kernel=kernel)
    notations = _selected_notations(request, language_bundle, kernel)
    by_coordinate = {
        (
            cast(str, operation.get("package", "")),
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
        lines.append(
            f"{grammar['binding_keyword']} {_identifier(node['id'], grammar)} = {rhs};"
        )
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
    contract: dict[str, Any], imports: dict[str, tuple[str, str]]
) -> tuple[str, str] | None:
    alias = contract.get("type")
    if alias == "Boolean":
        return "kernel", "Boolean"
    return imports.get(alias) if isinstance(alias, str) else None


def _operation_contract_matches(
    contract: dict[str, Any] | None,
    formal: dict[str, Any],
    imports: dict[str, tuple[str, str]],
) -> bool:
    if contract is None:
        return True
    formal_type = formal.get("type")
    return (
        isinstance(formal_type, dict)
        and _contract_type_identity(contract, imports)
        == (
            formal_type.get("package"),
            formal_type.get("id"),
        )
        and all(
            contract.get(member) == formal.get(member)
            for member in ("representation", "kind", "unit", "numeric_policy")
        )
    )


def _formula_contract_matches(
    actual: dict[str, Any] | None,
    actual_imports: dict[str, tuple[str, str]],
    expected: dict[str, Any],
    expected_imports: dict[str, tuple[str, str]],
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
    source_imports: dict[str, tuple[str, str]],
    target_imports: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    identity = _contract_type_identity(contract, source_imports)
    if identity == ("kernel", "Boolean"):
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
    kernel: dict[str, Any],
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
            for _operation, notation in _selected_notations(
                request, language_bundle, kernel
            )
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


def _boolean_formula_contract(kernel: dict[str, Any]) -> dict[str, Any]:
    fixed = kernel["meta_format"]["runtime_program"]["fixed_value_contracts"][
        "kernel-boolean"
    ]
    return {
        "type": "Boolean",
        **{
            member: deepcopy(fixed[member])
            for member in ("representation", "kind", "unit", "numeric_policy", "domain")
        },
    }


def _infer_result(
    operation: dict[str, Any],
    ports: list[str],
    contracts: list[dict[str, Any] | None],
    fallback: dict[str, Any],
    policy: dict[str, Any],
    boolean_contract: dict[str, Any],
    *,
    operations: dict[tuple[str, str], dict[str, Any]],
    kernel: dict[str, Any],
    imports: dict[str, tuple[str, str]],
    stack: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    coordinate = (cast(str, operation.get("package")), cast(str, operation.get("id")))
    if coordinate in stack:
        raise ValueError("independent Formula operation graph is recursive")
    if (
        operation.get("purity") != "pure"
        or operation.get("operation_kind") != "pure-expression"
    ):
        raise ValueError("independent Formula Operation is not a pure expression")
    actuals = dict(zip(ports, contracts, strict=True))
    canonical_ports = [
        cast(str, formal["id"])
        for formal in cast(list[dict[str, Any]], operation.get("inputs", []))
    ]
    if set(actuals) != set(canonical_ports) or len(actuals) != len(canonical_ports):
        raise ValueError("independent Formula Operation inputs are unresolved")
    ports = canonical_ports
    contracts = [actuals[port] for port in ports]
    anchor = next((row for row in contracts if isinstance(row, dict)), fallback)
    values = {
        port: deepcopy(contract or anchor)
        for port, contract in zip(ports, contracts, strict=True)
    }
    port_values = deepcopy(values)
    produced_locals: set[str] = set()
    results_by_site: dict[str, dict[str, Any]] = {}
    seen_sites: set[str] = set()
    rules = policy.get("local_result_inference")
    if not isinstance(rules, list):
        raise ValueError("independent result policy is malformed")
    by_node = {
        row.get("node"): row
        for row in rules
        if isinstance(row, dict) and isinstance(row.get("node"), str)
    }
    runtime = kernel["meta_format"]["runtime_program"]
    invocation = runtime["invocation_contract"]
    source_shapes = invocation["result_source_shapes"]
    invocation_nodes = {
        row["id"]
        for row in runtime["nodes"]
        if row.get("semantics", {}).get("operator") == "invoke-operation"
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

    comparisons: dict[str, tuple[str, str]] = {}

    def possible_branch(condition: str, selected: str, truth: bool):
        selected_bounds = interval(values[selected])
        assert selected_bounds is not None
        operands = comparisons.get(condition)
        if operands is None:
            return selected_bounds
        x, y = operands
        a, b = interval(values[x]), interval(values[y])
        if a is None or b is None:
            return selected_bounds
        if x == y:
            return None if truth else selected_bounds
        # Enumerate extremal feasible pairs of the rectangle intersected with
        # x < y (or x >= y), using mathematical integers at strict endpoints.
        xs = {a[0], a[1], max(a[0], b[0]), min(a[1], b[1] - 1)}
        ys = {b[0], b[1], min(b[1], a[1]), max(b[0], a[0] + 1)}
        pairs = [
            (u, v)
            for u in xs
            for v in ys
            if a[0] <= u <= a[1] and b[0] <= v <= b[1] and (u < v) is truth
        ]
        if not pairs:
            return None
        if selected not in operands:
            return selected_bounds
        selected_values = [pair[0 if selected == x else 1] for pair in pairs]
        return min(selected_values), max(selected_values)

    body = operation.get("body")
    if not isinstance(body, list):
        raise ValueError("independent inference Operation body is malformed")
    for instruction in body:
        if not isinstance(instruction, dict):
            raise ValueError("independent inference instruction is malformed")
        if instruction.get("node") in invocation_nodes:
            reference = instruction.get("operation")
            child_coordinate: tuple[str, str] | None = None
            if (
                isinstance(reference, dict)
                and set(reference) == {"package", "id"}
                and isinstance(reference.get("package"), str)
                and isinstance(reference.get("id"), str)
            ):
                child_coordinate = (reference["package"], reference["id"])
            child = (
                operations.get(child_coordinate)
                if child_coordinate is not None
                else None
            )
            if (
                child is None
                or child.get("purity") != "pure"
                or child.get("operation_kind") != "pure-expression"
            ):
                raise ValueError("independent nested Operation is unresolved")
            site = instruction.get("site")
            if not isinstance(site, str) or not site or site in seen_sites:
                raise ValueError("independent nested Operation site is unresolved")
            seen_sites.add(site)
            child_ports = [
                cast(str, formal["id"])
                for formal in cast(list[dict[str, Any]], child.get("inputs", []))
            ]
            formals = {
                cast(str, formal["id"]): formal
                for formal in cast(list[dict[str, Any]], child.get("inputs", []))
            }
            arguments = instruction.get("arguments")
            if (
                not isinstance(arguments, list)
                or [
                    argument.get("port") if isinstance(argument, dict) else None
                    for argument in arguments
                ]
                != child_ports
            ):
                raise ValueError(
                    "independent nested Operation arguments are unresolved"
                )
            child_contracts: list[dict[str, Any] | None] = []
            for argument in arguments:
                operand = argument.get("operand")
                kind = operand.get("kind") if isinstance(operand, dict) else None
                actual = None
                if isinstance(operand, dict) and kind in {"port", "local"}:
                    member = cast(str, kind)
                    name = operand.get(member)
                    if isinstance(name, str):
                        actual = values.get(name)
                elif isinstance(operand, dict) and kind == "literal":
                    value = operand.get("literal")
                    if isinstance(value, int) and not isinstance(value, bool):
                        actual = with_interval(anchor, (value, value))
                formal = formals[cast(str, argument["port"])]
                if actual is None or not _operation_contract_matches(
                    actual, formal, imports
                ):
                    raise ValueError(
                        "independent nested Operation operand is incompatible"
                    )
                child_contracts.append(deepcopy(actual))
            child_result = _infer_result(
                child,
                child_ports,
                child_contracts,
                fallback,
                policy,
                boolean_contract,
                operations=operations,
                kernel=kernel,
                imports=imports,
                stack=(*stack, coordinate),
            )
            binding = instruction.get("result")
            if not isinstance(binding, dict):
                raise ValueError("independent nested Operation result is unresolved")
            binding_kind = binding.get("kind")
            if binding_kind == "local":
                name = binding.get("name")
                if (
                    set(binding) != {"kind", "name"}
                    or not isinstance(name, str)
                    or not name
                    or name in values
                ):
                    raise ValueError(
                        "independent nested Operation result is unresolved"
                    )
                values[name] = child_result
                produced_locals.add(name)
            elif binding_kind == "operation-result":
                if set(binding) != {"kind"}:
                    raise ValueError(
                        "independent nested Operation result is unresolved"
                    )
                results_by_site[site] = child_result
            elif binding_kind == "discard":
                if (
                    set(binding) != {"kind"}
                    or child.get("result", {}).get("discardable") is not True
                ):
                    raise ValueError(
                        "independent nested Operation result is not discardable"
                    )
            else:
                raise ValueError("independent nested Operation result is unresolved")
            continue
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
        if target in values:
            raise ValueError("independent inference target is ambiguous")
        comparisons = {
            name: pair
            for name, pair in comparisons.items()
            if name != target and target not in pair
        }
        rule_id = rule.get("rule")
        if rule_id == "literal-closed-interval":
            literal = instruction.get(rule["literal_member"])
            if not isinstance(literal, int) or isinstance(literal, bool):
                raise ValueError("independent literal inference is malformed")
            values[target] = with_interval(anchor, (literal, literal))
        elif rule_id == "copy-contract":
            copied = instruction.get(rule["source_member"])
            if not isinstance(copied, str) or copied not in values:
                raise ValueError("independent inference operand is unresolved")
            values[target] = deepcopy(values[copied])
            if copied in comparisons:
                comparisons[target] = comparisons[copied]
        elif rule_id == "closed-interval-less-than":
            operands = tuple(instruction.get(m) for m in rule["operand_members"])
            if not all(isinstance(name, str) and name in values for name in operands):
                raise ValueError("independent inference operand is unresolved")
            comparisons[target] = cast(tuple[str, str], operands)
            values[target] = deepcopy(boolean_contract)
        elif rule_id in {
            "closed-interval-add",
            "closed-interval-floor-divide",
            "closed-interval-multiply",
            "closed-interval-select",
            "closed-interval-subtract",
        }:
            operand_names = tuple(
                instruction.get(member) for member in rule["operand_members"]
            )
            if not all(
                isinstance(name, str) and name in values for name in operand_names
            ):
                raise ValueError("independent inference operand is unresolved")
            left_name, right_name = cast(tuple[str, str], operand_names)
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
                branches = [
                    bounds
                    for selected, truth in ((left_name, True), (right_name, False))
                    if (
                        bounds := possible_branch(
                            instruction["condition"], selected, truth
                        )
                    )
                    is not None
                ]
                if not branches:
                    raise ValueError("independent selection has no possible result")
                values[target] = with_interval(
                    left,
                    (
                        min(pair[0] for pair in branches),
                        max(pair[1] for pair in branches),
                    ),
                )
        else:
            raise ValueError("independent inference rule is unknown")
        produced_locals.add(target)
    result = operation["result"]
    source = result.get("source") if isinstance(result, dict) else None
    source_kind = source.get("kind") if isinstance(source, dict) else None
    shape = source_shapes.get(source_kind) if isinstance(source_kind, str) else None
    if (
        not isinstance(source, dict)
        or not isinstance(shape, list)
        or set(source) != set(shape)
    ):
        raise ValueError("independent result source is malformed")
    if source_kind == "local":
        name = source.get("name")
        if name not in produced_locals:
            raise ValueError("independent local result producer is unresolved")
        return deepcopy(values[cast(str, name)])
    if source_kind == "port":
        name = source.get("name")
        if name not in port_values:
            raise ValueError("independent port result producer is unresolved")
        return deepcopy(port_values[cast(str, name)])
    if source_kind == "operation-result":
        site = source.get("site")
        if site not in results_by_site:
            raise ValueError("independent Operation result producer is unresolved")
        return deepcopy(results_by_site[cast(str, site)])
    if source_kind == "unit":
        raise ValueError("independent Formula Operation result is not scalar")
    raise ValueError("independent result source kind is unresolved")


def parse_canonical(
    expression: str,
    request: dict[str, Any],
    language_bundle: dict[str, Any],
    *,
    kernel: dict[str, Any],
) -> dict[str, Any]:
    grammar, _operations = _authority(language_bundle)
    formula_policy = _formula_policy(language_bundle, kernel=kernel)
    policy = formula_policy["notation_conversion"]
    modules = _validate_context(request, language_bundle, kernel=kernel)
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
                imported["symbol"],
            )
            for imported in row["imports"]
        }
        for row in modules
    }
    imports = imports_by_module[module_id]
    selected_packages = set(request["package_requirements"])
    packages_by_id = {
        package["id"]: package for package in language_bundle["language"]["packages"]
    }
    pending = list(selected_packages)
    while pending:
        package_id = pending.pop()
        package = packages_by_id.get(package_id)
        if package is None:
            raise ValueError("independent Formula package requirement is unresolved")
        for dependency in package["dependencies"]["required"]:
            if dependency not in selected_packages:
                selected_packages.add(dependency)
                pending.append(dependency)
    operations = {
        (package["id"], definition["id"]): {
            **definition,
            "package": package["id"],
        }
        for package in language_bundle["language"]["packages"]
        if package["id"] in selected_packages
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.operations"
        for definition in closure["definitions"]
    }
    symbols: dict[tuple[str, str], dict[str, Any]] = {}
    declarations: dict[
        tuple[str, str], tuple[dict[str, Any], dict[str, tuple[str, str]]]
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
        expression, grammar, request, language_bundle, kernel
    )
    if token_count > grammar["max_tokens"]:
        raise ValueError("independent Formula expression exceeds its token bound")
    if group_depth > grammar["max_group_depth"]:
        raise ValueError("independent Formula expression exceeds its group-depth bound")
    if len(lines) - 1 > formula_policy["max_nodes_per_formula"]:
        raise ValueError("independent Formula expression exceeds its node bound")
    notations = _selected_notations(request, language_bundle, kernel)
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
        if set(ports) != set(formals) or len(formals) != len(operation["inputs"]):
            raise ValueError("independent Operation port contract is incompatible")
        typed_operands = []
        for port, (operand, contract) in zip(ports, operands, strict=True):
            if contract is None and operand.get("kind") == "literal":
                literal = operand.get("value")
                matches = [
                    row
                    for row in language_bundle["language"]["literal_typing_profiles"]
                    if isinstance(literal, int)
                    and not isinstance(literal, bool)
                    and row.get("source_kind") == "integer"
                    and isinstance(row.get("minimum"), int)
                    and isinstance(row.get("maximum"), int)
                    and row["minimum"] <= literal <= row["maximum"]
                    and row.get("type") == formals[port].get("type")
                    and all(
                        row.get(member) == formals[port].get(member)
                        for member in (
                            "representation",
                            "kind",
                            "unit",
                            "domain",
                            "numeric_policy",
                        )
                    )
                ]
                aliases = [
                    alias
                    for alias, coordinate in imports.items()
                    if len(matches) == 1
                    and coordinate
                    == (matches[0]["type"]["package"], matches[0]["type"]["id"])
                ]
                if len(matches) != 1 or len(aliases) != 1:
                    raise ValueError(
                        "independent Operation literal contract is incompatible"
                    )
                # Generic actual formals retain the existing contextual anchor.
                # Only an explicit interval owner narrows a literal operand.
                if matches[0]["domain"].get("kind") == "closed-interval":
                    contract = {
                        "type": aliases[0],
                        **{
                            member: deepcopy(matches[0][member])
                            for member in (
                                "representation",
                                "kind",
                                "unit",
                                "numeric_policy",
                            )
                        },
                        "domain_kind": "closed-interval",
                        "domain": {"minimum": literal, "maximum": literal},
                    }
            if not _operation_contract_matches(contract, formals[port], imports):
                raise ValueError("independent Operation port contract is incompatible")
            typed_operands.append((operand, contract))
        result = _infer_result(
            operation,
            ports,
            [contract for _operand, contract in typed_operands],
            _source_contract(request["formula"]["result"]),
            policy,
            _boolean_formula_contract(kernel),
            operations=operations,
            kernel=kernel,
            imports=imports,
        )
        return (
            {
                "id": local,
                "node": "operation-call",
                "operation": {
                    "package": operation["package"],
                    "id": operation["id"],
                },
                "arguments": sorted(
                    [
                        {"port": port, "operand": operand}
                        for port, (operand, _contract) in zip(
                            ports, typed_operands, strict=True
                        )
                    ],
                    key=lambda argument: cast(str, argument["port"]),
                ),
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
        parameter_kind, parameter_reference, source_member = _inline_source_parameter(
            formula_policy, kernel
        )
        if operand.get("kind") == parameter_kind:
            return {"node": parameter_kind, source_member: operand[parameter_reference]}
        return {"nodes": [], "result": operand}

    for line in lines[:-1]:
        binding_prefix = grammar["binding_keyword"] + " "
        if not line.startswith(binding_prefix) or not line.endswith(";"):
            raise ValueError("canonical binding line is malformed")
        assignment = _split_outside(
            line[len(binding_prefix) : -1], " = ", quote, escape
        )
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
                != ("kernel", "Boolean")
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
    if not _formula_contract_matches(
        result_contract,
        imports,
        _source_contract(request["formula"]["result"]),
        imports,
    ):
        raise ValueError("independent Formula result contract is incompatible")
    return {
        "nodes": nodes,
        "result": result_operand,
    }


def admit_pair(
    request: dict[str, Any], language_bundle: dict[str, Any], *, kernel: dict[str, Any]
) -> bool:
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
        rendered = render_body(body, request, language_bundle, kernel=kernel)
        parsed = parse_canonical(expression, request, language_bundle, kernel=kernel)
    except (KeyError, TypeError, ValueError):
        return False
    return expression == rendered and canonical_bytes(
        cast(JsonValue, parsed)
    ) == canonical_bytes(cast(JsonValue, body))
