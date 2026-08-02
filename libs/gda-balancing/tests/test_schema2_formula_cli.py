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
