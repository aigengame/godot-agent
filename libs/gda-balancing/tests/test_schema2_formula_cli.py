"""Public Formula notation conversion for Standard Schema 2.0 (#606)."""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

import gda_balancing.domain.formula.notation as formula_notation_module
import gda_balancing.interfaces.cli.formula as formula_command_module
import gda_balancing.domain.authority.context as authority_module
import gda_balancing.domain.model._admission as model_admission_module
import gda_balancing.domain.artifacts as artifacts_module
from gda_balancing.domain.formula.notation import admit_formula_pair
from gda_balancing.domain.canonical import JsonValue, content_identity
from schema2_bootstrap_production_support import (
    _refresh_package_closure_and_reidentify,
)
from schema2_formula_conformance_support import admit_pair as independently_admit_pair
from schema2_formula_conformance_support import render_body as independently_render_body


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


def test_contextual_reason_is_independent_of_human_message_wording() -> None:
    error = formula_notation_module._FormulaContextError(
        "model.reason.formula-type-mismatch",
        "This reworded message says unresolved, ambiguous, and duplicate.",
    )

    refusal = formula_notation_module._contextual_refusal(error)

    assert refusal.reason_id == "model.reason.formula-type-mismatch"


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


def _quantity_module(identifier: str) -> dict[str, object]:
    return {
        "id": identifier,
        "imports": [
            {
                "alias": "quantity",
                "package": "core.quantity",
                "version": "2.1.0",
                "symbol": "Quantity",
            }
        ],
    }


def test_formula_render_projects_a_structured_subtraction_program(
    tmp_path: Path, run_cli
) -> None:
    difference_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    cast(dict[str, object], difference_contract["domain"])["minimum"] = -1000
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
                "result": difference_contract,
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
            "result": difference_contract,
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
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    raw_contract = deepcopy(value_contract)
    cast(dict[str, object], raw_contract["domain"])["minimum"] = -1000
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
        "module": _quantity_module("combat"),
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


def test_formula_parse_uses_context_to_distinguish_infix_minus_from_signed_literals(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    result_contract = deepcopy(value_contract)
    result_contract["domain"] = {"minimum": -1000, "maximum": 1000}
    source = tmp_path / "compact-subtraction.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "compact-subtraction",
                    "parameters": [
                        _quantity_contract("left"),
                    ],
                    "result": result_contract,
                    "expression": "let result=left-1;result",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    body = json.loads(stdout)["body"]
    assert body["nodes"][0]["operation"]["id"] == "quantity.subtract"
    assert body["nodes"][0]["arguments"] == [
        {"port": "left", "operand": {"kind": "parameter", "parameter": "left"}},
        {"port": "right", "operand": {"kind": "literal", "value": 1}},
    ]


def test_formula_parse_consumes_declared_infix_precedence_and_associativity(
    tmp_path: Path, run_cli
) -> None:
    result_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    result_contract["domain"] = {"minimum": -2000, "maximum": 1000}
    source = tmp_path / "associative-subtraction.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "associative-subtraction",
                    "parameters": [
                        _quantity_contract("a"),
                        _quantity_contract("b"),
                        _quantity_contract("c"),
                    ],
                    "result": result_contract,
                    "expression": "let result = a - b - c; result",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    output = json.loads(stdout)
    assert [node["id"] for node in output["body"]["nodes"]] == [
        "result__notation_1",
        "result",
    ]
    assert output["body"]["nodes"][0]["arguments"] == [
        {"port": "left", "operand": {"kind": "parameter", "parameter": "a"}},
        {"port": "right", "operand": {"kind": "parameter", "parameter": "b"}},
    ]
    assert output["body"]["nodes"][1]["arguments"] == [
        {
            "port": "left",
            "operand": {"kind": "local", "local": "result__notation_1"},
        },
        {"port": "right", "operand": {"kind": "parameter", "parameter": "c"}},
    ]
    assert output["expression"] == (
        "let result__notation_1 = a - b;\nlet result = result__notation_1 - c;\nresult"
    )


def test_formula_parse_obeys_mutated_package_owned_associativity(
    tmp_path: Path,
    run_cli,
    pristine_authority_context,
    monkeypatch,
) -> None:
    kernel, language_bundle = pristine_authority_context.mutable_pair()
    operation = next(
        row
        for row in language_bundle["language"]["operations"]
        if row["id"] == "quantity.subtract"
    )
    operation["extensions"]["standard.formula-notation"]["associativity"] = "right"
    vector = next(
        row
        for row in language_bundle["vectors"]
        if row["id"] == "formula.notation.quantity.subtract"
    )
    vector["expect"] = deepcopy(operation["extensions"])
    child_vector = next(
        row
        for vector_set in language_bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "core.quantity"
        for row in vector_set["vector_definitions"]
        if row["id"] == vector["id"]
    )
    child_vector["expect"] = deepcopy(operation["extensions"])
    _refresh_package_closure_and_reidentify(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)
    monkeypatch.setattr(
        formula_command_module,
        "packaged_authority_context",
        lambda: drifted,
    )
    result_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    result_contract["domain"] = {"minimum": -1000, "maximum": 2000}
    source = tmp_path / "right-associative-subtraction.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "right-associative-subtraction",
                    "parameters": [
                        _quantity_contract("a"),
                        _quantity_contract("b"),
                        _quantity_contract("c"),
                    ],
                    "result": result_contract,
                    "expression": "let result = a - b - c; result",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    nodes = json.loads(stdout)["body"]["nodes"]
    assert nodes[0]["arguments"] == [
        {"port": "left", "operand": {"kind": "parameter", "parameter": "b"}},
        {"port": "right", "operand": {"kind": "parameter", "parameter": "c"}},
    ]
    assert nodes[1]["arguments"] == [
        {"port": "left", "operand": {"kind": "parameter", "parameter": "a"}},
        {
            "port": "right",
            "operand": {"kind": "local", "local": "result__notation_1"},
        },
    ]


def test_formula_parse_obeys_mutated_package_owned_precedence(
    tmp_path: Path,
    run_cli,
    pristine_authority_context,
    monkeypatch,
) -> None:
    kernel, language_bundle = pristine_authority_context.mutable_pair()
    operation = next(
        row
        for row in language_bundle["language"]["operations"]
        if row["id"] == "quantity.less-than"
    )
    operation["extensions"]["standard.formula-notation"]["precedence"] = 60
    vector = next(
        row
        for row in language_bundle["vectors"]
        if row["id"] == "formula.notation.quantity.less-than"
    )
    vector["expect"] = deepcopy(operation["extensions"])
    child_vector = next(
        row
        for vector_set in language_bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "core.quantity"
        for row in vector_set["vector_definitions"]
        if row["id"] == vector["id"]
    )
    child_vector["expect"] = deepcopy(operation["extensions"])
    _refresh_package_closure_and_reidentify(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)
    monkeypatch.setattr(
        formula_command_module,
        "packaged_authority_context",
        lambda: drifted,
    )
    source = tmp_path / "mutated-precedence.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "mutated-precedence",
                    "parameters": [
                        _quantity_contract("a"),
                        _quantity_contract("b"),
                        _quantity_contract("c"),
                    ],
                    "result": {
                        key: value
                        for key, value in _boolean_contract("result").items()
                        if key != "id"
                    },
                    "expression": "let result = a - b < c; result",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert [row["code"] for row in error["diagnostics"]] == [
        "language.formula_type_mismatch"
    ]


def test_formula_render_refuses_infix_tokens_that_collide_with_grammar(
    tmp_path: Path,
    run_cli,
    pristine_authority_context,
    monkeypatch,
) -> None:
    kernel, language_bundle = pristine_authority_context.mutable_pair()
    operation = next(
        row
        for row in language_bundle["language"]["operations"]
        if row["id"] == "quantity.subtract"
    )
    operation["extensions"]["standard.formula-notation"]["token"] = "="
    vector = next(
        row
        for row in language_bundle["vectors"]
        if row["id"] == "formula.notation.quantity.subtract"
    )
    vector["expect"] = deepcopy(operation["extensions"])
    child_vector = next(
        row
        for vector_set in language_bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "core.quantity"
        for row in vector_set["vector_definitions"]
        if row["id"] == vector["id"]
    )
    child_vector["expect"] = deepcopy(operation["extensions"])
    _refresh_package_closure_and_reidentify(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)
    monkeypatch.setattr(
        formula_command_module,
        "packaged_authority_context",
        lambda: drifted,
    )
    result_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    result_contract["domain"] = {"minimum": -1000, "maximum": 1000}
    source = tmp_path / "colliding-infix.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "colliding-infix",
                    "parameters": [
                        _quantity_contract("left"),
                        _quantity_contract("right"),
                    ],
                    "result": result_contract,
                    "body": {
                        "nodes": [
                            {
                                "id": "result",
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
                                            "parameter": "left",
                                        },
                                    },
                                    {
                                        "port": "right",
                                        "operand": {
                                            "kind": "parameter",
                                            "parameter": "right",
                                        },
                                    },
                                ],
                                "result": result_contract,
                            }
                        ],
                        "result": {"kind": "local", "local": "result"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (2, "")
    assert json.loads(stdout)["error"]["diagnostics"][0]["code"] == (
        "language.source_contract_mismatch"
    )


def test_formula_render_quotes_non_bare_locals_and_renders_literals(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
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
        "module": _quantity_module("combat"),
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
        key: value for key, value in _quantity_contract("result").items() if key != "id"
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
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": {
                    "id": "main",
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
        key: value for key, value in _quantity_contract("result").items() if key != "id"
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
        "module": _quantity_module("combat"),
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


def test_formula_parse_reverse_admits_its_canonical_pair(
    tmp_path: Path, run_cli, monkeypatch
) -> None:
    source = tmp_path / "parse-request.json"
    source.write_text(formula_command_module._VALID_PARSE_REQUEST, encoding="utf-8")
    admitted_pairs: list[dict] = []
    real_admit = formula_notation_module.admit_formula_pair

    def observe_admission(request, authority_context, **kwargs):
        admitted_pairs.append(deepcopy(request))
        return real_admit(request, authority_context, **kwargs)

    monkeypatch.setattr(
        formula_notation_module,
        "admit_formula_pair",
        observe_admission,
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert len(admitted_pairs) == 1
    assert admitted_pairs[0]["formula"]["body"] == result["body"]
    assert admitted_pairs[0]["formula"]["expression"] == result["expression"]


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
        key: value for key, value in _quantity_contract("result").items() if key != "id"
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
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
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
        key: value for key, value in _quantity_contract("result").items() if key != "id"
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
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
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
        key: value for key, value in _quantity_contract("result").items() if key != "id"
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
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": {
                    **_quantity_module("main"),
                    "formulas": [
                        {
                            "id": "inner",
                            "parameters": [_quantity_contract("value")],
                            "result": value_contract,
                            "body": {
                                "node": "parameter",
                                "parameter": "value",
                            },
                            "expression": "value",
                        }
                    ],
                },
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


def test_formula_parse_resolves_a_qualified_formula_call(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
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
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": {
                    **_quantity_module("main"),
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
            "2.4.0",
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
        "version": "1.1.0",
        "bare_identifier_pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
        "identifier_token_pattern": "[A-Za-z_][A-Za-z0-9_]*",
        "integer_literal_pattern": "-?(?:0|[1-9][0-9]*)",
        "whitespace_pattern": "\\s+",
        "signed_integer_context": "operand-position",
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
        "request_identity_domain": "formula-notation-request-v2",
        "max_expression_bytes": 65536,
        "max_group_depth": 1536,
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


def test_standard_compiler_owns_formula_notation_contextual_policy(run_cli) -> None:
    exit_code, stdout, stderr = run_cli(
        [
            "package",
            "get",
            "--id",
            "standard.compiler",
            "--version",
            "1.1.0",
            "--member",
            "release",
        ]
    )

    assert (exit_code, stderr) == (0, "")
    release = json.loads(stdout)
    profile = next(
        definition
        for closure in release["semantic_closure"]
        if closure["authority_path"] == "language.resolution_profiles"
        for definition in closure["definitions"]
        if definition["id"] == "exact-import-resolution-v1"
    )
    conversion = profile["extensions"]["standard.formula"]["notation_conversion"]
    assert conversion["condition_contract"] == "kernel-boolean"
    assert conversion["formula_argument_compatibility"] == "exact-resolved-contract"
    assert conversion["formula_result_compatibility"] == "exact-resolved-contract"
    assert conversion["literal_typing"] == "selected-unique-formal-match"
    assert conversion["literal_result_inference"] == "contextual-anchor"
    assert conversion["operation_argument_compatibility"] == "exact-operation-formal"
    assert conversion["symbol_resolution"] == "exact-module-coordinate"
    assert conversion["infix_parser"] == {
        "algorithm": "shunting-yard",
        "generated_local_separator": "__notation_",
    }
    assert {
        row["node"]: row["rule"] for row in conversion["local_result_inference"]
    } == {
        "add": "closed-interval-add",
        "constant": "literal-closed-interval",
        "copy": "copy-contract",
        "floor-divide": "closed-interval-floor-divide",
        "if": "closed-interval-select",
        "less-than": "declared-result-contract",
        "maximum": "closed-interval-maximum",
        "multiply": "closed-interval-multiply",
        "subtract": "closed-interval-subtract",
    }


@pytest.mark.parametrize(
    ("schema_version", "requirements", "expected_code"),
    [
        ("999.0.0", [], "language.source_contract_mismatch"),
        ("2.0.0", [], "language.unresolved_name"),
    ],
)
def test_formula_parse_requires_exact_schema_and_import_resolution(
    tmp_path: Path,
    run_cli,
    schema_version: str,
    requirements: list[dict[str, str]],
    expected_code: str,
) -> None:
    contract = {
        **{
            key: value
            for key, value in _quantity_contract("value").items()
            if key != "id"
        },
        "type": "ghost",
    }
    source = tmp_path / "unresolved-formula-context.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "package_requirements": requirements,
                "module": {
                    "id": "main",
                    "imports": [
                        {
                            "alias": "ghost",
                            "package": "ghost.package",
                            "version": "9.9.9",
                            "symbol": "Fake",
                        }
                    ],
                },
                "formula": {
                    "id": "identity",
                    "parameters": [{"id": "value", **contract}],
                    "result": contract,
                    "expression": "value",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    assert json.loads(stdout)["error"]["diagnostics"][0]["code"] == expected_code


def test_formula_parse_refuses_a_current_module_that_conflicts_with_its_closure(
    tmp_path: Path, run_cli
) -> None:
    boolean = {
        key: value for key, value in _boolean_contract("flag").items() if key != "id"
    }
    source = tmp_path / "conflicting-module-context.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "modules": [
                    {**_quantity_module("main"), "symbols": [], "formulas": []}
                ],
                "module": {
                    "id": "main",
                    "imports": [
                        {
                            "alias": "ghost",
                            "package": "ghost.package",
                            "version": "9.9.9",
                            "symbol": "Fake",
                        }
                    ],
                },
                "formula": {
                    "id": "identity",
                    "parameters": [{"id": "flag", **boolean}],
                    "result": boolean,
                    "expression": "flag",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    assert json.loads(stdout)["error"]["diagnostics"][0]["code"] == (
        "language.source_contract_mismatch"
    )


def test_formula_parse_resolves_cross_module_formula_calls(
    tmp_path: Path, run_cli
) -> None:
    contract = {
        key: value for key, value in _quantity_contract("value").items() if key != "id"
    }
    inner = {
        "id": "inner",
        "parameters": [{"id": "value", **contract}],
        "result": contract,
        "body": {"node": "parameter", "parameter": "value"},
        "expression": "value",
    }
    modules = [
        {**_quantity_module("aux"), "symbols": [], "formulas": [inner]},
        {**_quantity_module("main"), "symbols": [], "formulas": []},
    ]
    source = tmp_path / "cross-module-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "modules": modules,
                "module": modules[1],
                "formula": {
                    "id": "outer",
                    "parameters": [{"id": "value", **contract}],
                    "result": contract,
                    "expression": "let result = aux.inner(value = value);\nresult",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result["body"]["nodes"][0]["formula"] == {
        "module": "aux",
        "id": "inner",
    }
    pair = json.loads(source.read_text(encoding="utf-8"))
    pair["formula"]["body"] = result["body"]
    pair["formula"]["expression"] = result["expression"]
    context = authority_module.packaged_authority_context()
    assert independently_admit_pair(pair, context.language_bundle)


def test_formula_parse_never_resolves_an_unquoted_kebab_case_local(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    source = tmp_path / "unquoted-kebab-local.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "bad-local-reference",
                    "parameters": [_quantity_contract("base")],
                    "result": value_contract,
                    "expression": (
                        "let `minimum-accuracy` = max(base, 1); minimum-accuracy"
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


@pytest.mark.parametrize(
    "payload",
    (
        b"{",
        b"[]",
        b'{"formula":{},"formula":{}}',
        b'{"value":"\\ud800"}',
    ),
    ids=("malformed", "non-object", "duplicate-key", "lone-surrogate"),
)
def test_formula_conversion_refuses_noncanonical_json_ingress(
    tmp_path: Path, run_cli, payload: bytes
) -> None:
    source = tmp_path / "invalid-request.json"
    source.write_bytes(payload)

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "parse"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.source_parse_failure"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == ""


def test_formula_conversion_refuses_request_bytes_above_the_ingress_bound(
    tmp_path: Path, run_cli
) -> None:
    context = authority_module.packaged_authority_context()
    source = tmp_path / "oversized-request.json"
    source.write_bytes(
        b"{"
        + b" " * cast(int, context.language_bundle["resources"]["max_source_bytes"])
    )

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.source_too_large"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == ""


def test_formula_parse_reports_malformed_notation_as_a_typed_parse_refusal(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    source = tmp_path / "malformed-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
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


def test_formula_parse_reports_invalid_identifier_escape_at_the_parse_stage(
    tmp_path: Path, run_cli
) -> None:
    source = tmp_path / "invalid-identifier-escape.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "invalid-escape",
                    "parameters": [_quantity_contract("value")],
                    "result": {
                        key: value
                        for key, value in _quantity_contract("result").items()
                        if key != "id"
                    },
                    "expression": ("let `invalid\\x` = identity(value); `invalid\\x`"),
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


def test_formula_parse_reports_incompatible_conditional_branches_as_type_mismatch(
    tmp_path: Path, run_cli
) -> None:
    source = tmp_path / "incompatible-conditional.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "incompatible-conditional",
                    "parameters": [
                        _boolean_contract("condition"),
                        _quantity_contract("amount"),
                    ],
                    "result": {
                        key: value
                        for key, value in _quantity_contract("result").items()
                        if key != "id"
                    },
                    "expression": (
                        "let result = if condition then amount else condition; result"
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
        "language.formula_type_mismatch"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"


def test_formula_parse_refuses_a_final_operand_outside_the_result_contract(
    tmp_path: Path, run_cli
) -> None:
    source = tmp_path / "incompatible-result.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": {
                    "id": "main",
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
                    "id": "incompatible-result",
                    "parameters": [_boolean_contract("flag")],
                    "result": {
                        key: value
                        for key, value in _quantity_contract("result").items()
                        if key != "id"
                    },
                    "expression": "flag",
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
        "language.formula_type_mismatch"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"


@pytest.mark.parametrize(
    ("case", "parameters", "result", "expression", "formulas"),
    (
        (
            "operation-port",
            [_boolean_contract("flag")],
            {
                key: value
                for key, value in _boolean_contract("result").items()
                if key != "id"
            },
            "let result = identity(flag); result",
            [],
        ),
        (
            "formula-argument",
            [_boolean_contract("flag")],
            {
                key: value
                for key, value in _quantity_contract("result").items()
                if key != "id"
            },
            "let result = main.helper(value = flag); result",
            [
                {
                    "id": "helper",
                    "parameters": [_quantity_contract("value")],
                    "result": {
                        key: value
                        for key, value in _quantity_contract("result").items()
                        if key != "id"
                    },
                    "body": {"node": "parameter", "parameter": "value"},
                    "expression": "value",
                }
            ],
        ),
        (
            "conditional-condition",
            [_quantity_contract("amount")],
            {
                key: value
                for key, value in _quantity_contract("result").items()
                if key != "id"
            },
            "let result = if amount then amount else amount; result",
            [],
        ),
        (
            "unresolved-symbol",
            [],
            {
                key: value
                for key, value in _quantity_contract("result").items()
                if key != "id"
            },
            "let result = identity(ghost.missing); result",
            [],
        ),
        (
            "literal-out-of-range",
            [],
            {
                key: value
                for key, value in _quantity_contract("result").items()
                if key != "id"
            },
            "let result = identity(9223372036854775808); result",
            [],
        ),
    ),
)
def test_formula_parse_refuses_contextual_type_or_resolution_mismatches(
    tmp_path: Path,
    run_cli,
    case: str,
    parameters: list[dict[str, object]],
    result: dict[str, object],
    expression: str,
    formulas: list[dict[str, object]],
) -> None:
    source = tmp_path / f"{case}.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": {
                    "id": "main",
                    "imports": [
                        {
                            "alias": "quantity",
                            "package": "core.quantity",
                            "version": "2.1.0",
                            "symbol": "Quantity",
                        }
                    ],
                    "formulas": formulas,
                },
                "formula": {
                    "id": case,
                    "parameters": parameters,
                    "result": result,
                    "expression": expression,
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
        (
            "language.unresolved_name"
            if case == "unresolved-symbol"
            else "language.formula_type_mismatch"
        )
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"


def test_formula_parse_reports_ambiguous_selected_package_notation(
    tmp_path: Path,
    run_cli,
    pristine_authority_context,
    monkeypatch,
) -> None:
    kernel, language_bundle = pristine_authority_context.mutable_pair()
    identity = deepcopy(
        next(
            row
            for row in language_bundle["language"]["operations"]
            if row["id"] == "quantity.identity"
        )
    )
    identity["id"] = "game.check.duplicate-identity"
    identity["version"] = "1.0.1"
    identity["vectors"] = []
    language_bundle["language"]["operations"].append(identity)
    language_bundle["language"]["operations"].sort(key=lambda row: row["id"])
    game_check = next(
        row
        for row in language_bundle["language"]["packages"]
        if row["id"] == "game.check"
    )
    game_check["exports"]["operations"].append(identity["id"])
    game_check["exports"]["operations"].sort()
    _refresh_package_closure_and_reidentify(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)
    monkeypatch.setattr(
        formula_command_module,
        "packaged_authority_context",
        lambda: drifted,
    )
    source = tmp_path / "ambiguous-notation.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [
                    {"id": "core.quantity", "version": "2.1.0"},
                    {"id": "game.check", "version": "1.0.1"},
                ],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "ambiguous",
                    "parameters": [_quantity_contract("value")],
                    "result": {
                        key: value
                        for key, value in _quantity_contract("result").items()
                        if key != "id"
                    },
                    "expression": "let result = identity(value); result",
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
        "language.name_ambiguity"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/expression"


def test_formula_render_reports_invalid_notation_port_closure_as_type_mismatch(
    tmp_path: Path, run_cli
) -> None:
    result_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    source = tmp_path / "invalid-port-closure.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "invalid-port-closure",
                    "parameters": [_quantity_contract("value")],
                    "result": result_contract,
                    "body": {
                        "nodes": [
                            {
                                "id": "result",
                                "node": "operation-call",
                                "operation": {
                                    "package": "core.quantity",
                                    "version": "2.1.0",
                                    "id": "quantity.maximum",
                                },
                                "arguments": [
                                    {
                                        "port": "left",
                                        "operand": {
                                            "kind": "parameter",
                                            "parameter": "value",
                                        },
                                    }
                                ],
                                "result": result_contract,
                            }
                        ],
                        "result": {"kind": "local", "local": "result"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.formula_type_mismatch"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == "/formula/body"


def test_formula_render_round_trips_a_body_after_port_reordering(
    tmp_path: Path,
    run_cli,
    pristine_authority_context,
    monkeypatch,
) -> None:
    kernel, language_bundle = pristine_authority_context.mutable_pair()
    operation = next(
        row
        for row in language_bundle["language"]["operations"]
        if row["id"] == "quantity.subtract"
    )
    operation["extensions"]["standard.formula-notation"]["ordered_ports"] = [
        "right",
        "left",
    ]
    vector = next(
        row
        for row in language_bundle["vectors"]
        if row["id"] == "formula.notation.quantity.subtract"
    )
    vector["expect"] = deepcopy(operation["extensions"])
    child_vector = next(
        row
        for vector_set in language_bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "core.quantity"
        for row in vector_set["vector_definitions"]
        if row["id"] == vector["id"]
    )
    child_vector["expect"] = deepcopy(operation["extensions"])
    _refresh_package_closure_and_reidentify(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)
    monkeypatch.setattr(
        formula_command_module,
        "packaged_authority_context",
        lambda: drifted,
    )
    source_value = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    module = source_value["modules"][0]
    formula = next(row for row in module["formulas"] if row["id"] == "mitigated-damage")
    request = {
        "schema_version": source_value["schema_version"],
        "package_requirements": source_value["package_requirements"],
        "module": {"id": module["id"], "imports": module["imports"]},
        "formula": {
            key: value for key, value in formula.items() if key != "expression"
        },
    }
    source = tmp_path / "reordered-ports-render.json"
    source.write_text(json.dumps(request), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["expression"] == (
        "let raw_damage = mitigation - damage_before_defense;\n"
        "let damage = floor_zero(raw_damage);\n"
        "damage"
    )


def test_formula_parse_refuses_expression_bytes_above_the_admitted_limit(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    source = tmp_path / "over-limit-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
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
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    source = tmp_path / "over-token-limit-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
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


def test_formula_parse_handles_deep_grouping_below_the_token_limit(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    depth = 1200
    source = tmp_path / "deep-grouping-formula.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "deep-grouping",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "expression": "(" * depth + "value" + ")" * depth,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["expression"] == "value"


def test_formula_parse_enforces_the_authority_owned_group_depth_bound(
    tmp_path: Path, run_cli
) -> None:
    value_contract = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    depth = 1537
    source = tmp_path / "over-group-depth.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "over-group-depth",
                    "parameters": [_quantity_contract("value")],
                    "result": value_contract,
                    "expression": "(" * depth + "value" + ")" * depth,
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "parse", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.formula_notation_resource_exhausted"
    ]


def test_formula_render_reports_an_unresolved_operation_at_the_body(
    tmp_path: Path, run_cli
) -> None:
    source = tmp_path / "unresolved-operation.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
                "module": _quantity_module("main"),
                "formula": {
                    "id": "unresolved",
                    "parameters": [_quantity_contract("value")],
                    "result": {},
                    "body": {
                        "nodes": [
                            {
                                "id": "result",
                                "node": "operation-call",
                                "operation": {
                                    "package": "core.quantity",
                                    "version": "2.1.0",
                                    "id": "quantity.unknown",
                                },
                                "arguments": [
                                    {
                                        "port": "value",
                                        "operand": {
                                            "kind": "parameter",
                                            "parameter": "value",
                                        },
                                    }
                                ],
                                "result": {},
                            }
                        ],
                        "result": {"kind": "local", "local": "result"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code, stdout, stderr = run_cli(["formula", "render", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.unresolved_name"
    assert diagnostic["primary"]["pointer"] == "/formula/body"


def test_model_check_requires_an_expression_beside_every_formula_body(
    tmp_path: Path, run_cli
) -> None:
    source_value = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    for formula in source_value["modules"][0]["formulas"]:
        formula.pop("expression", None)
    source = tmp_path / "missing-formula-expressions.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostics = json.loads(stdout)["error"]["diagnostics"]
    assert [item["primary"]["pointer"] for item in diagnostics] == [
        "/modules/0/formulas/0/expression",
        "/modules/0/formulas/1/expression",
    ]


def test_model_check_refuses_noncanonical_formula_expression_bytes(
    tmp_path: Path, run_cli
) -> None:
    source_value = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    source_value["modules"][0]["formulas"][0]["expression"] = (
        " let raw_damage = ((damage_before_defense - mitigation)); "
        "let damage = floor_zero(raw_damage); damage "
    )
    source = tmp_path / "noncanonical-formula-expression.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.formula_notation_mismatch"
    ]
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/modules/0/formulas/0/expression"
    )


def test_model_check_refuses_a_canonical_expression_for_a_different_body(
    tmp_path: Path, run_cli
) -> None:
    source_value = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    source_value["modules"][0]["formulas"][0]["expression"] = source_value["modules"][
        0
    ]["formulas"][1]["expression"]
    source = tmp_path / "divergent-formula-expression.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_notation_mismatch"
    assert diagnostic["primary"]["pointer"] == ("/modules/0/formulas/0/expression")


def test_model_build_publishes_paired_formula_surfaces_and_rir_identities(
    tmp_path: Path, run_cli
) -> None:
    source = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "6" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    locators = {
        row["logical_name"]: Path(row["locator"]) for row in receipt["member_locators"]
    }
    rir = json.loads(locators["rir-semantic-payload"].read_text(encoding="utf-8"))
    explanation = json.loads(locators["model-explanation"].read_text(encoding="utf-8"))
    resolved = json.loads(locators["resolved-model"].read_text(encoding="utf-8"))

    source_formulas = {
        row["id"]: row
        for row in json.loads(source.read_text())["modules"][0]["formulas"]
    }
    assert {row["id"]: row["expression"] for row in rir["formulas"]} == {
        identifier: row["expression"] for identifier, row in source_formulas.items()
    }
    assert {
        row["id"]: row["expression"] for row in explanation["formula_explanations"]
    } == {identifier: row["expression"] for identifier, row in source_formulas.items()}
    assert rir["content_identity"].startswith("sha256:")
    assert rir["semantic_identity"].startswith("sha256:")
    assert rir["semantic_identity"] != rir["content_identity"]
    assert resolved["rir_content_identity"] == rir["content_identity"]
    assert resolved["rir_semantic_identity"] == rir["semantic_identity"]
    assert "rir_identity" not in resolved

    context = authority_module.packaged_authority_context()
    tampered_rir = deepcopy(rir)
    tampered_rir["formulas"][0]["expression"] += " "
    contract = artifacts_module._artifact_contract(
        context.language_bundle, "rir-semantic-payload"
    )
    tampered_rir["content_identity"] = content_identity(
        cast(str, contract["identity_domain"]),
        cast(
            JsonValue,
            {
                key: value
                for key, value in tampered_rir.items()
                if key != "content_identity"
            },
        ),
    )
    tampered_resolved = artifacts_module.identified_artifact(
        context.language_bundle,
        "resolved-model",
        {
            "kernel_identity": context.kernel["content_identity"],
            "language_bundle_identity": context.language_bundle["content_identity"],
            "package_lock_identity": json.loads(
                locators["package-lock"].read_text(encoding="utf-8")
            )["content_identity"],
            "rir_content_identity": tampered_rir["content_identity"],
            "rir_semantic_identity": tampered_rir["semantic_identity"],
        },
    )
    assert not model_admission_module.admit_resolved_model(
        {
            "package-lock": json.loads(
                locators["package-lock"].read_text(encoding="utf-8")
            ),
            "rir-semantic-payload": tampered_rir,
            "resolved-model": tampered_resolved,
        },
        authority_context=context,
    ).admitted
    tampered_explanation = deepcopy(explanation)
    tampered_explanation["formula_explanations"][0]["expression"] += " "
    assert not model_admission_module._model_explanation_pairs_are_admitted(
        tampered_explanation,
        rir,
        json.loads(locators["package-lock"].read_text(encoding="utf-8")),
        context,
    )


def test_independent_consumer_mutually_admits_production_formula_pairs() -> None:
    context = authority_module.packaged_authority_context()
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    for module in source["modules"]:
        for formula in module["formulas"]:
            request = {
                "schema_version": source["schema_version"],
                "package_requirements": source["package_requirements"],
                "modules": source["modules"],
                "module": module,
                "formula": formula,
            }
            assert independently_admit_pair(request, context.language_bundle)
            independent_expression = independently_render_body(
                formula["body"], request, context.language_bundle
            )
            independent_pair = deepcopy(request)
            independent_pair["formula"]["expression"] = independent_expression
            admit_formula_pair(independent_pair, context)


def test_independent_consumer_reconstructs_results_without_body_guidance() -> None:
    context = authority_module.packaged_authority_context()
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    module = source["modules"][0]
    formula = next(row for row in module["formulas"] if row["id"] == "mitigated-damage")
    request = {
        "schema_version": source["schema_version"],
        "package_requirements": source["package_requirements"],
        "modules": source["modules"],
        "module": module,
        "formula": deepcopy(formula),
    }
    assert independently_admit_pair(request, context.language_bundle)
    request["formula"]["body"]["nodes"][0]["result"]["domain"] = {
        "minimum": 0,
        "maximum": 0,
    }

    assert not independently_admit_pair(request, context.language_bundle)


def test_independent_consumer_types_zero_node_results() -> None:
    context = authority_module.packaged_authority_context()
    quantity = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    wrong_parameter = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": _quantity_module("main"),
        "formula": {
            "id": "wrong-parameter-result",
            "parameters": [_boolean_contract("flag")],
            "result": quantity,
            "body": {"node": "parameter", "parameter": "flag"},
            "expression": "flag",
        },
    }
    missing_symbol = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": {**_quantity_module("main"), "symbols": []},
        "formula": {
            "id": "missing-symbol-result",
            "parameters": [],
            "result": quantity,
            "body": {
                "nodes": [],
                "result": {"kind": "symbol", "module": "ghost", "symbol": "missing"},
            },
            "expression": "ghost.missing",
        },
    }

    assert not independently_admit_pair(wrong_parameter, context.language_bundle)
    assert not independently_admit_pair(missing_symbol, context.language_bundle)


def test_independent_consumer_enforces_notation_resource_bounds() -> None:
    context = authority_module.packaged_authority_context()
    grammar = next(
        definition["schema"]["$defs"]["formulaNotationGrammar"]["const"]
        for package in context.language_bundle["language"]["packages"]
        if package["id"] == "standard.schema"
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.wire_schemas"
        for definition in closure["definitions"]
        if definition["artifact_kind"] == "model-source-package"
    )
    identifier = "a" * (grammar["max_expression_bytes"] + 1)
    result = {
        key: value for key, value in _quantity_contract("result").items() if key != "id"
    }
    request = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": _quantity_module("main"),
        "formula": {
            "id": "oversized",
            "parameters": [{"id": identifier, **result}],
            "result": result,
            "body": {"node": "parameter", "parameter": identifier},
            "expression": identifier,
        },
    }

    assert not independently_admit_pair(request, context.language_bundle)


def test_independent_consumer_requires_exact_context_and_algorithm(
    pristine_authority_context,
) -> None:
    boolean = {
        key: value for key, value in _boolean_contract("flag").items() if key != "id"
    }
    request = {
        "schema_version": "999.0.0",
        "package_requirements": [],
        "module": {
            "id": "main",
            "imports": [
                {
                    "alias": "ghost",
                    "package": "ghost.package",
                    "version": "9.9.9",
                    "symbol": "Fake",
                }
            ],
        },
        "formula": {
            "id": "identity",
            "parameters": [{"id": "flag", **boolean}],
            "result": boolean,
            "body": {"node": "parameter", "parameter": "flag"},
            "expression": "flag",
        },
    }
    assert not independently_admit_pair(
        request, pristine_authority_context.language_bundle
    )

    kernel, language_bundle = pristine_authority_context.mutable_pair()
    profile = next(
        row
        for row in language_bundle["language"]["resolution_profiles"]
        if row.get("default") is True
    )
    profile["extensions"]["standard.formula"]["notation_conversion"]["infix_parser"][
        "algorithm"
    ] = "ignored-host-algorithm"
    _refresh_package_closure_and_reidentify(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)
    request["schema_version"] = "2.0.0"
    request["module"] = {"id": "main", "imports": []}

    assert not independently_admit_pair(request, drifted.language_bundle)

    kernel, language_bundle = pristine_authority_context.mutable_pair()
    profile = next(
        row
        for row in language_bundle["language"]["resolution_profiles"]
        if row.get("default") is True
    )
    profile["extensions"]["standard.formula"]["notation_conversion"][
        "symbol_resolution"
    ] = "ignored-host-resolution"
    _refresh_package_closure_and_reidentify(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)

    assert not independently_admit_pair(request, drifted.language_bundle)


def test_independent_consumer_covers_every_formula_node_and_operand_kind() -> None:
    context = authority_module.packaged_authority_context()
    quantity = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 1000},
        "numeric_policy": "exact-int64",
    }
    boolean = {
        "type": "Boolean",
        "representation": "Bool",
        "kind": "boolean",
        "unit": "1",
        "domain": {"kind": "boolean"},
        "numeric_policy": "exact-bool",
    }
    helper = {
        "id": "helper",
        "parameters": [{"id": "value", **quantity}],
        "result": quantity,
        "body": {"node": "parameter", "parameter": "value"},
        "expression": "value",
    }
    body = {
        "nodes": [
            {
                "id": "is-small",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.less-than",
                },
                "arguments": [
                    {
                        "port": "left",
                        "operand": {"kind": "parameter", "parameter": "damage"},
                    },
                    {"port": "right", "operand": {"kind": "literal", "value": 1}},
                ],
                "result": boolean,
            },
            {
                "id": "choice",
                "node": "conditional",
                "condition": {"kind": "local", "local": "is-small"},
                "when_true": {"kind": "parameter", "parameter": "damage"},
                "when_false": {"kind": "parameter", "parameter": "fallback"},
            },
            {
                "id": "observed",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.identity",
                },
                "arguments": [
                    {
                        "port": "value",
                        "operand": {
                            "kind": "symbol",
                            "module": "combat",
                            "symbol": "override",
                        },
                    }
                ],
                "result": quantity,
            },
            {
                "id": "forwarded",
                "node": "formula-call",
                "formula": {"module": "combat", "id": "helper"},
                "arguments": [
                    {
                        "parameter": "value",
                        "operand": {"kind": "local", "local": "choice"},
                    }
                ],
            },
        ],
        "result": {"kind": "local", "local": "forwarded"},
    }
    formula = {
        "id": "all-kinds",
        "parameters": [
            {"id": "damage", **quantity},
            {"id": "fallback", **quantity},
        ],
        "result": quantity,
        "body": body,
        "expression": (
            "let `is-small` = damage < 1;\n"
            "let choice = if `is-small` then damage else fallback;\n"
            "let observed = identity(combat.override);\n"
            "let forwarded = combat.helper(value = choice);\n"
            "forwarded"
        ),
    }
    module = {
        "id": "combat",
        "imports": [
            {
                "alias": "quantity",
                "package": "core.quantity",
                "version": "2.1.0",
                "symbol": "Quantity",
            }
        ],
        "symbols": [
            {
                "symbol": "override",
                "role": "parameter",
                **quantity,
                "value_policy": {"mode": "experiment-required"},
            }
        ],
        "formulas": [helper, formula],
    }
    request = {
        "schema_version": "2.0.0",
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "module": module,
        "formula": formula,
    }

    assert independently_admit_pair(request, context.language_bundle)
    admit_formula_pair(request, context)
