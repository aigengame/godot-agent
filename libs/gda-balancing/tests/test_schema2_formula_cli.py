"""Public Formula notation conversion for Standard Schema 2.0 (#606)."""

import json
from pathlib import Path


def _quantity_contract(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 1000},
        "numeric_policy": "exact-int64",
    }


def _boolean_contract(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "type": "Boolean",
        "representation": "Bool",
        "kind": "boolean",
        "unit": "1",
        "domain": {"kind": "boolean"},
        "numeric_policy": "exact-bool",
    }


def test_formula_render_projects_a_structured_subtraction_program(
    tmp_path: Path, run_cli
) -> None:
    body = {
        "nodes": [
            {
                "id": "difference",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.subtract",
                },
                "arguments": [
                    {
                        "port": "left",
                        "operand": {"kind": "parameter", "parameter": "left"},
                    },
                    {
                        "port": "right",
                        "operand": {"kind": "parameter", "parameter": "right"},
                    },
                ],
                "result": {
                    key: value
                    for key, value in _quantity_contract("result").items()
                    if key != "id"
                },
            }
        ],
        "result": {"kind": "local", "local": "difference"},
    }
    request = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": {
            "id": "combat",
            "imports": [
                {
                    "alias": "quantity",
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "symbol": "Quantity",
                }
            ],
        },
        "formula": {
            "id": "difference",
            "parameters": [
                _quantity_contract("left"),
                _quantity_contract("right"),
            ],
            "result": {
                key: value
                for key, value in _quantity_contract("result").items()
                if key != "id"
            },
            "body": body,
        },
    }
    source = tmp_path / "formula-render.json"
    source.write_text(json.dumps(request), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["body"] == body
    assert result["expression"] == "let difference = left - right;\ndifference"
    assert result["kernel_identity"].startswith("sha256:")
    assert result["language_bundle_identity"].startswith("sha256:")


def test_formula_render_preserves_the_mitigated_damage_program(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    body = {
        "nodes": [
            {
                "id": "raw_damage",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.subtract",
                },
                "arguments": [
                    {
                        "port": "left",
                        "operand": {
                            "kind": "parameter",
                            "parameter": "damage_before_defense",
                        },
                    },
                    {
                        "port": "right",
                        "operand": {
                            "kind": "parameter",
                            "parameter": "mitigation",
                        },
                    },
                ],
                "result": value_contract,
            },
            {
                "id": "damage",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.floor-zero",
                },
                "arguments": [
                    {
                        "port": "value",
                        "operand": {"kind": "local", "local": "raw_damage"},
                    }
                ],
                "result": value_contract,
            },
        ],
        "result": {"kind": "local", "local": "damage"},
    }
    request = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": {"id": "combat", "imports": []},
        "formula": {
            "id": "mitigated-damage",
            "parameters": [
                _quantity_contract("damage_before_defense"),
                _quantity_contract("mitigation"),
            ],
            "result": value_contract,
            "body": body,
        },
    }
    source = tmp_path / "mitigated-damage-render.json"
    source.write_text(json.dumps(request), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["body"] == body
    assert result["expression"] == (
        "let raw_damage = damage_before_defense - mitigation;\n"
        "let damage = floor_zero(raw_damage);\n"
        "damage"
    )


def test_formula_render_quotes_non_bare_locals_and_renders_literals(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    body = {
        "nodes": [
            {
                "id": "minimum-accuracy",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.maximum",
                },
                "arguments": [
                    {
                        "port": "left",
                        "operand": {"kind": "parameter", "parameter": "base"},
                    },
                    {"port": "right", "operand": {"kind": "literal", "value": 1}},
                ],
                "result": value_contract,
            }
        ],
        "result": {"kind": "local", "local": "minimum-accuracy"},
    }
    request = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": {"id": "combat", "imports": []},
        "formula": {
            "id": "effective-accuracy",
            "parameters": [_quantity_contract("base")],
            "result": value_contract,
            "body": body,
        },
    }
    source = tmp_path / "effective-accuracy-render.json"
    source.write_text(json.dumps(request), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["body"] == body
    assert result["expression"] == (
        "let `minimum-accuracy` = max(base, 1);\n`minimum-accuracy`"
    )


def test_formula_render_covers_the_identity_operation(tmp_path: Path, run_cli) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    body = {
        "nodes": [
            {
                "id": "same",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.identity",
                },
                "arguments": [
                    {
                        "port": "value",
                        "operand": {"kind": "parameter", "parameter": "value"},
                    }
                ],
                "result": value_contract,
            }
        ],
        "result": {"kind": "local", "local": "same"},
    }
    source = tmp_path / "identity-render.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "identity",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "body": body,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["expression"] == "let same = identity(value);\nsame"


def test_formula_parse_canonicalizes_whitespace_and_redundant_parentheses(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    raw_contract = json.loads(json.dumps(value_contract))
    raw_contract["domain"] = {"minimum": -1000, "maximum": 1000}
    expected_body = {
        "nodes": [
            {
                "id": "raw_damage",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.subtract",
                },
                "arguments": [
                    {
                        "port": "left",
                        "operand": {
                            "kind": "parameter",
                            "parameter": "damage_before_defense",
                        },
                    },
                    {
                        "port": "right",
                        "operand": {
                            "kind": "parameter",
                            "parameter": "mitigation",
                        },
                    },
                ],
                "result": raw_contract,
            },
            {
                "id": "damage",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.floor-zero",
                },
                "arguments": [
                    {
                        "port": "value",
                        "operand": {"kind": "local", "local": "raw_damage"},
                    }
                ],
                "result": value_contract,
            },
        ],
        "result": {"kind": "local", "local": "damage"},
    }
    request = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": {"id": "combat", "imports": []},
        "formula": {
            "id": "mitigated-damage",
            "parameters": [
                _quantity_contract("damage_before_defense"),
                _quantity_contract("mitigation"),
            ],
            "result": value_contract,
            "expression": (
                " let raw_damage = ((damage_before_defense - mitigation)); "
                "let damage=floor_zero(((raw_damage))); damage "
            ),
        },
    }
    source = tmp_path / "mitigated-damage-parse.json"
    source.write_text(json.dumps(request), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["body"] == expected_body
    assert result["expression"] == (
        "let raw_damage = damage_before_defense - mitigation;\n"
        "let damage = floor_zero(raw_damage);\n"
        "damage"
    )


def test_formula_render_then_parse_preserves_the_committed_formula_bodies(
    tmp_path: Path, run_cli
) -> None:
    model_source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    module = model_source["modules"][0]
    for formula in module["formulas"]:
        render_request = {
            "schema_version": model_source["schema_version"],
            "package_requirements": model_source["package_requirements"],
            "module": {"id": module["id"], "imports": module["imports"]},
            "formula": formula,
        }
        render_source = tmp_path / f"{formula['id']}-render.json"
        render_source.write_text(json.dumps(render_request), encoding="utf-8")
        render_exit, render_stdout, render_stderr = run_cli(
            ["formula", "render", str(render_source)]
        )
        assert (render_exit, render_stderr) == (0, "")

        parse_request = json.loads(json.dumps(render_request))
        parse_request["formula"].pop("body")
        parse_request["formula"]["expression"] = json.loads(render_stdout)["expression"]
        parse_source = tmp_path / f"{formula['id']}-parse.json"
        parse_source.write_text(json.dumps(parse_request), encoding="utf-8")

        parse_exit, parse_stdout, parse_stderr = run_cli(
            ["formula", "parse", str(parse_source)]
        )

        assert (parse_exit, parse_stderr) == (0, "")
        assert json.loads(parse_stdout)["body"] == formula["body"]


def test_formula_render_projects_conditionals_without_losing_branch_identity(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    body = {
        "nodes": [
            {
                "id": "choice",
                "node": "conditional",
                "condition": {"kind": "parameter", "parameter": "condition"},
                "when_true": {"kind": "parameter", "parameter": "when-true"},
                "when_false": {"kind": "parameter", "parameter": "when-false"},
            }
        ],
        "result": {"kind": "local", "local": "choice"},
    }
    source = tmp_path / "conditional-render.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "choose",
                    "parameters": [
                        _boolean_contract("condition"),
                        _quantity_contract("when-false"),
                        _quantity_contract("when-true"),
                    ],
                    "result": value_contract,
                    "body": body,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["body"] == body
    assert result["expression"] == (
        "let choice = if condition then `when-true` else `when-false`;\nchoice"
    )


def test_formula_parse_reconstructs_a_conditional_node(tmp_path: Path, run_cli) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    expected_body = {
        "nodes": [
            {
                "id": "choice",
                "node": "conditional",
                "condition": {"kind": "parameter", "parameter": "condition"},
                "when_true": {"kind": "parameter", "parameter": "when-true"},
                "when_false": {"kind": "parameter", "parameter": "when-false"},
            }
        ],
        "result": {"kind": "local", "local": "choice"},
    }
    source = tmp_path / "conditional-parse.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "choose",
                    "parameters": [
                        _boolean_contract("condition"),
                        _quantity_contract("when-false"),
                        _quantity_contract("when-true"),
                    ],
                    "result": value_contract,
                    "expression": (
                        "let choice = if condition then `when-true` "
                        "else `when-false`; choice"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["body"] == expected_body


def test_formula_render_uses_qualified_formula_calls_and_named_arguments(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    body = {
        "nodes": [
            {
                "id": "inner_call",
                "node": "formula-call",
                "formula": {"module": "main", "id": "inner"},
                "arguments": [
                    {
                        "parameter": "value",
                        "operand": {"kind": "parameter", "parameter": "value"},
                    }
                ],
            }
        ],
        "result": {"kind": "local", "local": "inner_call"},
    }
    source = tmp_path / "formula-call-render.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "outer",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "body": body,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["body"] == body
    assert result["expression"] == (
        "let inner_call = main.inner(value = value);\ninner_call"
    )


def test_formula_parse_resolves_a_qualified_formula_call(tmp_path: Path, run_cli) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    expected_body = {
        "nodes": [
            {
                "id": "inner_call",
                "node": "formula-call",
                "formula": {"module": "main", "id": "inner"},
                "arguments": [
                    {
                        "parameter": "value",
                        "operand": {"kind": "parameter", "parameter": "value"},
                    }
                ],
            }
        ],
        "result": {"kind": "local", "local": "inner_call"},
    }
    source = tmp_path / "formula-call-parse.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {
                    "id": "main",
                    "imports": [],
                    "formulas": [
                        {
                            "id": "inner",
                            "parameters": [_quantity_contract("value")],
                            "result": value_contract,
                            "body": {"node": "parameter", "parameter": "value"},
                        }
                    ],
                },
                "formula": {
                    "id": "outer",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "expression": (
                        "let inner_call = main.inner(value = value); inner_call"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["body"] == expected_body


def test_standard_schema_owns_the_closed_formula_notation_grammar(run_cli) -> None:
    exit_code, stdout, stderr = run_cli(
        [
            "package",
            "get",
            "--id",
            "standard.schema",
            "--version",
            "2.1.0",
            "--member",
            "release",
        ]
    )

    assert (exit_code, stderr) == (0, "")
    release = json.loads(stdout)
    source_schema = next(
        definition["schema"]
        for closure in release["semantic_closure"]
        if closure["authority_path"] == "language.wire_schemas"
        for definition in closure["definitions"]
        if definition["artifact_kind"] == "model-source-package"
    )
    grammar = source_schema["$defs"]["formulaNotationGrammar"]["const"]
    assert grammar == {
        "version": "1.0.0",
        "bare_identifier_pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
        "reserved_identifiers": ["else", "if", "let", "then"],
        "identifier_quote": "`",
        "escape_character": "\\",
        "escapable_identifier_characters": ["`", "\\"],
        "group_delimiters": ["(", ")"],
        "binding_keyword": "let",
        "conditional_keywords": ["if", "then", "else"],
        "binding_terminator": ";",
        "argument_separator": ",",
        "named_argument_operator": "=",
        "coordinate_separator": ".",
        "max_expression_bytes": 65536,
        "max_tokens": 4096,
    }
    notation_schema = source_schema["$defs"]["formulaOperationNotation"]
    assert notation_schema["oneOf"][0]["required"] == [
        "kind",
        "token",
        "ordered_ports",
        "precedence",
        "associativity",
    ]
    assert notation_schema["oneOf"][1]["required"] == [
        "kind",
        "name",
        "ordered_ports",
    ]


def test_formula_parse_never_resolves_an_unquoted_kebab_case_local(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    source = tmp_path / "unquoted-kebab-local.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "bad-local-reference",
                    "parameters": [_quantity_contract("base")],
                    "result": value_contract,
                    "expression": (
                        "let `minimum-accuracy` = max(base, 1); "
                        "minimum-accuracy"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.unresolved_name"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"


def test_formula_parse_reports_malformed_notation_as_a_typed_parse_refusal(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    source = tmp_path / "malformed-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "malformed",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "expression": "let result = floor_zero(value; result",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "parse"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.formula_notation_parse_failure"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"


def test_formula_parse_refuses_expression_bytes_above_the_admitted_limit(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    source = tmp_path / "over-limit-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "over-limit",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "expression": "value" + " " * 65532,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "parse"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.formula_notation_resource_exhausted"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"


def test_formula_parse_refuses_tokens_above_the_admitted_limit(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value
        for key, value in _quantity_contract("result").items()
        if key != "id"
    }
    source = tmp_path / "over-token-limit-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"}
                ],
                "module": {"id": "main", "imports": []},
                "formula": {
                    "id": "over-token-limit",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "expression": "(" * 2048 + "value" + ")" * 2048,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "parse"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.formula_notation_resource_exhausted"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"
