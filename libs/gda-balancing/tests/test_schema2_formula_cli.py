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
