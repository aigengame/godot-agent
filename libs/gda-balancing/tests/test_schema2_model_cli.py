"""Public Model compiler tracer for Standard Schema 2.0 (#539)."""

import hashlib
import hmac
import json
import os
import shutil
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import gda_balancing.commands.model as model_command_module
import gda_balancing.schema2.authority as authority_module
import gda_balancing.schema2.bootstrap as bootstrap_module
import gda_balancing.schema2.experiment as experiment_module
import gda_balancing.schema2.model as model_module
import jsonschema
import pytest
from gda_balancing.schema2.bootstrap import admit_authorities
from gda_balancing.schema2.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.schema2.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.schema2.authority_graph import (
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.schema2.surface import descriptor_identity


def _inject_authority_context(monkeypatch, kernel, language_bundle):
    context = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(context, authority_module.AdmittedAuthorityContext)
    monkeypatch.setattr(model_module, "packaged_authority_context", lambda: context)
    return context


def _quantity_symbol(name: str, role: str) -> dict[str, Any]:
    return {
        "symbol": name,
        "type": "quantity",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
        "value_policy": {
            "mode": (
                "model-fixed"
                if role == "constant"
                else "experiment-required"
                if role in {"parameter", "input", "state"}
                else "named-stream"
                if role == "random"
                else "none"
            ),
            **({"value": 1} if role == "constant" else {}),
        },
    }


def _model_source() -> dict[str, Any]:
    roles = (
        "constant",
        "parameter",
        "input",
        "state",
        "derived",
        "output",
        "random",
    )
    return {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "example.quantity-model",
            "version": "1.0.0",
            "entry_module": "main",
        },
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "entrypoints": [],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.1.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": [_quantity_symbol(f"{role}_value", role) for role in roles],
            }
        ],
    }


def _use_derived_value(source: dict[str, Any]) -> None:
    source["entrypoints"] = [
        {
            "id": "formula.identity",
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
                        "module": "main",
                        "symbol": "derived_value",
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]


def _symbols(source: dict[str, Any]) -> list[dict[str, Any]]:
    return source["modules"][0]["symbols"]


def _artifact_directory(receipt: dict[str, Any]):
    return Path(receipt["manifest_locator"]).parent


def _invocation_directory(_parent, invocation_key: str):
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "invocations").glob(
            f"*/{invocation_key}"
        )
    )
    assert len(matches) == 1
    return matches[0]


def _anchor_path(invocation_key: str) -> Path:
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors").glob(
            f"*/{invocation_key}.json"
        )
    )
    assert len(matches) == 1
    return matches[0]


def test_model_check_accepts_all_quantity_roles_without_publishing(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    before = set(tmp_path.iterdir())

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result == {
        "checked": True,
        "kernel_identity": result["kernel_identity"],
        "language_bundle_identity": result["language_bundle_identity"],
    }
    assert result["kernel_identity"].startswith("sha256:")
    assert result["language_bundle_identity"].startswith("sha256:")
    assert set(tmp_path.iterdir()) == before


def test_model_build_lowers_a_named_formula_bound_to_a_derived_symbol(
    tmp_path, run_cli
):
    source_document = _model_source()
    source_document["modules"][0]["formulas"] = [
        {
            "id": "derive-value",
            "parameters": [
                {
                    "id": "base",
                    "type": "quantity",
                    "representation": "Int",
                    "kind": "scalar",
                    "unit": "1",
                    "domain_kind": "closed-interval",
                    "domain": {"minimum": 0, "maximum": 100},
                    "numeric_policy": "exact-int64",
                }
            ],
            "result": {
                "type": "quantity",
                "representation": "Int",
                "kind": "scalar",
                "unit": "1",
                "domain_kind": "closed-interval",
                "domain": {"minimum": 0, "maximum": 100},
                "numeric_policy": "exact-int64",
            },
            "body": {"node": "parameter", "parameter": "base"},
            "expression": "base",
        }
    ]
    source_document["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "derive-value"},
            "arguments": [
                {
                    "parameter": "base",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    source_document["entrypoints"] = [
        {
            "id": "formula.identity",
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
                        "module": "main",
                        "symbol": "derived_value",
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source = tmp_path / "formula-model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "1" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    published = _artifact_directory(json.loads(stdout))
    rir = json.loads((published / "rir-semantic-payload.json").read_text())
    assert [formula["id"] for formula in rir["formulas"]] == ["derive-value"]
    bindings_by_phase = {
        binding["site"]["context"]["phase"]: binding
        for binding in rir["formula_bindings"]
    }
    assert set(bindings_by_phase) == {"initialization", "observation"}
    assert bindings_by_phase["initialization"]["site"]["context"] == {
        "frame": "pre-snapshot",
        "phase": "initialization",
    }
    assert bindings_by_phase["observation"]["site"]["context"] == {
        "frame": "post-transition-snapshot",
        "phase": "observation",
    }
    assert (
        bindings_by_phase["initialization"]["site"]["identity"]
        != bindings_by_phase["observation"]["site"]["identity"]
    )
    assert len(rir["initialization_programs"]) == 2
    for program in rir["initialization_programs"]:
        phase = program["site"]["context"]["phase"]
        binding = bindings_by_phase[phase]
        assert program["site"] == binding["site"]
        assert program["target"] == {
            "model": "example.quantity-model",
            "module": "main",
            "name": "derived_value",
        }
        assert program["inputs"] == [
            {"name": "base", "operand": binding["arguments"][0]["operand"]}
        ]
        result_name = f"init.{program['site']['identity']}.$result"
        assert program["body"] == [
            {
                "evaluation_site_identity": program["body"][0][
                    "evaluation_site_identity"
                ],
                "instruction": {
                    "node": "copy",
                    "target": result_name,
                    "value": "base",
                },
            }
        ]
        assert program["body"][0]["evaluation_site_identity"].startswith("sha256:")
        assert program["result"] == {"kind": "local", "name": result_name}
        assert program["numeric_policy"] == "exact-int64"
        assert program["resource_bounds"] == {"max_steps": 1}
        assert program["refusals"] == []


def test_formula_parameter_program_refuses_noncanonical_sugar_pair():
    program_source = _model_source()
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    program_source["modules"][0]["formulas"] = [
        {
            "id": "derive-value",
            "parameters": [{"id": "base", **quantity_contract}],
            "result": quantity_contract,
            "body": {
                "nodes": [],
                "result": {"kind": "parameter", "parameter": "base"},
            },
            "expression": "base",
        }
    ]
    program_source["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "derive-value"},
            "arguments": [
                {
                    "parameter": "base",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    _use_derived_value(program_source)
    sugar_source = deepcopy(program_source)
    sugar_source["modules"][0]["formulas"][0]["body"] = {
        "node": "parameter",
        "parameter": "base",
    }

    checked_program = model_module.check_model_source_value(program_source)
    checked_sugar = model_module.check_model_source_value(sugar_source)
    assert isinstance(checked_program, Schema2RefusalReport)
    assert checked_program.stage == "static"
    assert checked_program.diagnostics[0].code == "language.formula_notation_mismatch"
    assert isinstance(checked_program.diagnostics[0].primary, ArtifactLocation)
    assert (
        checked_program.diagnostics[0].primary.pointer
        == "/modules/0/formulas/0/expression"
    )
    assert isinstance(checked_sugar, model_module.CheckedModel)
    policy = model_module._formula_policy(checked_sugar.language_bundle)
    assert policy["inline_body_normalizations"] == [
        {
            "node": "parameter",
            "parameter_member": "parameter",
            "result_kind": "parameter",
        }
    ]


def test_formula_policy_uses_authority_values_without_host_spelling_or_limit_pins():
    _kernel, language_bundle = authority_module.load_authorities()
    candidate = deepcopy(language_bundle)
    profile = next(
        row
        for row in candidate["language"]["resolution_profiles"]
        if row["id"] == "exact-import-resolution-v1"
    )
    policy = profile["extensions"]["standard.formula"]
    policy["body_nodes_member"] = "authority-owned-expressions"
    policy["allowed_body_nodes"] = ["authority-owned-node"]
    policy["max_nodes_per_formula"] = 37
    policy["resource_charge_per_node"] = 41
    policy["identity_domains"]["formula"] = "authority-formula-domain"

    resolved = model_module._formula_policy(candidate)

    assert resolved["body_nodes_member"] == "authority-owned-expressions"
    assert resolved["allowed_body_nodes"] == ["authority-owned-node"]
    assert resolved["max_nodes_per_formula"] == 37
    assert resolved["resource_charge_per_node"] == 41
    assert resolved["identity_domains"]["formula"] == "authority-formula-domain"


def test_model_build_publishes_the_formula_explanation(tmp_path, run_cli):
    source_document = _model_source()
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    source_document["modules"][0]["formulas"] = [
        {
            "id": "derive-value",
            "parameters": [{"id": "base", **quantity_contract}],
            "result": quantity_contract,
            "body": {"node": "parameter", "parameter": "base"},
            "expression": "base",
        }
    ]
    source_document["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "derive-value"},
            "arguments": [
                {
                    "parameter": "base",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    _use_derived_value(source_document)
    source = tmp_path / "formula-explanation-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "f" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    artifact_dir = _artifact_directory(json.loads(stdout))
    explanation = json.loads((artifact_dir / "model-explanation.json").read_text())
    rir = json.loads((artifact_dir / "rir-semantic-payload.json").read_text())
    debug_map = json.loads((artifact_dir / "debug-map.json").read_text())
    build_receipt = json.loads((artifact_dir / "build-receipt.json").read_text())
    assert explanation["artifact_kind"] == "model-explanation"
    assert explanation["rir_identity"] == rir["content_identity"]
    assert explanation["debug_map_identity"] == debug_map["content_identity"]
    assert [row["id"] for row in explanation["formula_explanations"]] == [
        "derive-value"
    ]
    explanation_sites = {
        row["context"]["phase"]: row
        for row in explanation["formula_explanations"][0]["evaluation_sites"]
    }
    bindings_by_phase = {
        row["site"]["context"]["phase"]: row for row in rir["formula_bindings"]
    }
    assert set(explanation_sites) == {"initialization", "observation"}
    for phase, binding in bindings_by_phase.items():
        assert explanation_sites[phase] == {
            "binding_identity": binding["identity"],
            "context": binding["site"]["context"],
            "identity": binding["site"]["identity"],
            "operands": binding["arguments"],
            "result": rir["formulas"][0]["result"],
        }
    identity_operation = next(
        row
        for row in explanation["operation_explanations"]
        if row["id"] == "quantity.identity"
    )
    assert identity_operation["control_nodes"] == ["copy"]
    assert identity_operation["rng_streams"] == []
    assert identity_operation["outcomes"] == []
    assert identity_operation["default_outcome"] is None
    assert (
        build_receipt["model_explanation_identity"] == explanation["content_identity"]
    )
    manifest = json.loads((artifact_dir / "artifact-set-manifest.json").read_text())
    assert "model-explanation" in {
        member["logical_name"] for member in manifest["members"]
    }


def test_model_inspect_retrieves_the_stored_explanation_without_regenerating_it(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "e" * 64,
        ]
    )
    assert (exit_code, stderr) == (0, "")
    artifact_dir = _artifact_directory(json.loads(stdout))
    receipt_path = artifact_dir / "artifact-set-receipt.json"
    explanation_path = artifact_dir / "model-explanation.json"
    expected_bytes = explanation_path.read_bytes()

    def fail_if_regenerated(*_args, **_kwargs):
        raise AssertionError("model inspect must not regenerate an explanation")

    monkeypatch.setattr(model_module, "_model_explanation", fail_if_regenerated)
    inspect_exit, inspect_stdout, inspect_stderr = run_cli(
        [
            "model",
            "inspect",
            str(receipt_path),
            "--format",
            "indented",
        ]
    )

    assert (inspect_exit, inspect_stderr) == (0, "")
    assert inspect_stdout.startswith("{\n  ")
    assert json.loads(inspect_stdout) == json.loads(expected_bytes)
    assert explanation_path.read_bytes() == expected_bytes


def test_model_inspect_accepts_the_public_build_receipt_presentation(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "d" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    receipt = tmp_path / "public-build-receipt.json"
    receipt.write_text(build_stdout, encoding="utf-8")

    inspect_exit, inspect_stdout, inspect_stderr = run_cli(
        ["model", "inspect", str(receipt)]
    )

    assert (inspect_exit, inspect_stderr) == (0, "")
    assert json.loads(inspect_stdout)["artifact_kind"] == "model-explanation"


@pytest.mark.parametrize("anchor_key", [None, "A5" * 32, "a5" * 31, "not-hex"])
def test_model_inspect_preserves_invalid_anchor_configuration_as_usage(
    tmp_path, run_cli, monkeypatch, anchor_key
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "b" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    receipt = tmp_path / "public-build-receipt.json"
    receipt.write_text(build_stdout, encoding="utf-8")
    if anchor_key is None:
        monkeypatch.delenv("GDA_BALANCING_ANCHOR_KEY", raising=False)
    else:
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", anchor_key)

    inspect_exit, inspect_stdout, inspect_stderr = run_cli(
        ["model", "inspect", str(receipt)]
    )

    assert (inspect_exit, inspect_stdout) == (3, "")
    assert json.loads(inspect_stderr)["error"] == {
        "category": "usage",
        "code": "invalid_argument",
        "message": (
            "GDA_BALANCING_ANCHOR_KEY must contain exactly 64 lowercase "
            "hexadecimal digits"
        ),
    }
    assert "invalid_argument" in model_command_module.MODEL_INSPECT.usage_codes


def test_model_inspect_refuses_a_coherently_relocated_publication(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "c" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    committed_dir = _artifact_directory(json.loads(build_stdout))
    relocated_dir = tmp_path / "relocated-publication"
    shutil.copytree(committed_dir, relocated_dir)
    relocated_receipt = json.loads(
        (relocated_dir / "artifact-set-receipt.json").read_text()
    )
    relocated_receipt["manifest_locator"] = str(
        relocated_dir / "artifact-set-manifest.json"
    )
    for locator in relocated_receipt["member_locators"]:
        locator["locator"] = str(relocated_dir / f"{locator['logical_name']}.json")
    receipt_path = relocated_dir / "artifact-set-receipt.json"
    receipt_path.write_bytes(canonical_bytes(relocated_receipt))

    inspect_exit, inspect_stdout, inspect_stderr = run_cli(
        ["model", "inspect", str(receipt_path)]
    )

    assert (inspect_exit, inspect_stderr) == (2, "")
    error = json.loads(inspect_stdout)["error"]
    assert error["stage"] == "ingress"
    assert [item["code"] for item in error["diagnostics"]] == [
        "kernel.binding_mismatch"
    ]


def test_model_inspect_refuses_a_malformed_receipt_without_internal_error(
    tmp_path, run_cli
):
    receipt = tmp_path / "invalid-receipt.json"
    receipt.write_text("{}\n", encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "inspect", str(receipt)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert [item["code"] for item in error["diagnostics"]] == [
        "kernel.identity_mismatch"
    ]


def test_model_build_closes_reachable_formula_calls_before_rir(tmp_path, run_cli):
    source_document = _model_source()
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    source_document["modules"][0]["formulas"] = [
        {
            "id": "inner",
            "parameters": [{"id": "value", **quantity_contract}],
            "result": quantity_contract,
            "body": {"node": "parameter", "parameter": "value"},
            "expression": "value",
        },
        {
            "id": "outer",
            "parameters": [{"id": "value", **quantity_contract}],
            "result": quantity_contract,
            "body": {
                "nodes": [
                    {
                        "id": "inner-call",
                        "node": "formula-call",
                        "formula": {"module": "main", "id": "inner"},
                        "arguments": [
                            {
                                "parameter": "value",
                                "operand": {
                                    "kind": "parameter",
                                    "parameter": "value",
                                },
                            }
                        ],
                    }
                ],
                "result": {"kind": "local", "local": "inner-call"},
            },
            "expression": (
                "let `inner-call` = main.inner(value = value);\n`inner-call`"
            ),
        },
    ]
    source_document["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "outer"},
            "arguments": [
                {
                    "parameter": "value",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    _use_derived_value(source_document)
    source = tmp_path / "formula-call-model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "2" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    published = _artifact_directory(json.loads(stdout))
    rir = json.loads((published / "rir-semantic-payload.json").read_text())
    formulas = {formula["id"]: formula for formula in rir["formulas"]}
    assert set(formulas) == {"inner", "outer"}
    assert formulas["outer"]["body"]["nodes"][0]["formula"] == {
        "module": "main",
        "id": "inner",
        "identity": formulas["inner"]["identity"],
    }
    assert formulas["inner"]["closure"]["resource_charge"] == {"max_steps": 1}
    assert formulas["outer"]["closure"] == {
        "formula_dependencies": [formulas["inner"]["identity"]],
        "operation_dependencies": [],
        "refusals": [],
        "resource_charge": {"max_steps": 2},
        "termination_measure": 2,
    }


def test_model_check_refuses_a_formula_call_cycle_before_hir(tmp_path, run_cli):
    source_document = _model_source()
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }

    def formula(formula_id: str, target: str) -> dict[str, Any]:
        return {
            "id": formula_id,
            "parameters": [{"id": "value", **quantity_contract}],
            "result": quantity_contract,
            "body": {
                "nodes": [
                    {
                        "id": "recursive-call",
                        "node": "formula-call",
                        "formula": {"module": "main", "id": target},
                        "arguments": [
                            {
                                "parameter": "value",
                                "operand": {
                                    "kind": "parameter",
                                    "parameter": "value",
                                },
                            }
                        ],
                    }
                ],
                "result": {"kind": "local", "local": "recursive-call"},
            },
            "expression": (
                f"let `recursive-call` = main.{target}(value = value);\n"
                "`recursive-call`"
            ),
        }

    first = formula("alpha", "beta")
    first["body"] = {"node": "parameter", "parameter": "value"}
    first["expression"] = "value"
    source_document["modules"][0]["formulas"] = [
        first,
        formula("beta", "beta"),
    ]
    source_document["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "beta"},
            "arguments": [
                {
                    "parameter": "value",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    source = tmp_path / "cyclic-formulas.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_cycle"
    assert diagnostic["primary"]["pointer"] == "/modules/0/formulas/1/body"


def test_model_build_closes_a_pure_operation_call_in_a_formula(tmp_path, run_cli):
    source_document = _model_source()
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    source_document["modules"][0]["formulas"] = [
        {
            "id": "through-operation",
            "parameters": [{"id": "value", **quantity_contract}],
            "result": quantity_contract,
            "body": {
                "nodes": [
                    {
                        "id": "identity-call",
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
                                    "kind": "parameter",
                                    "parameter": "value",
                                },
                            }
                        ],
                        "result": quantity_contract,
                    }
                ],
                "result": {"kind": "local", "local": "identity-call"},
            },
            "expression": "let `identity-call` = identity(value);\n`identity-call`",
        }
    ]
    source_document["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "through-operation"},
            "arguments": [
                {
                    "parameter": "value",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    _use_derived_value(source_document)
    source = tmp_path / "formula-operation-call.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "3" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    published = _artifact_directory(json.loads(stdout))
    rir = json.loads((published / "rir-semantic-payload.json").read_text())
    formula = rir["formulas"][0]
    operation = formula["body"]["nodes"][0]["operation"]
    assert {
        "package": operation["package"],
        "version": operation["version"],
        "id": operation["id"],
    } == {
        "package": "core.quantity",
        "version": "2.1.0",
        "id": "quantity.identity",
    }
    assert formula["closure"] == {
        "formula_dependencies": [],
        "operation_dependencies": [operation["identity"]],
        "refusals": [],
        "resource_charge": {"max_steps": 2},
        "termination_measure": 1,
    }


def test_model_check_refuses_scalar_formula_conditionals(tmp_path, run_cli):
    source_document = _model_source()
    contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    source_document["modules"][0]["formulas"] = [
        {
            "id": "choose-value",
            "parameters": [
                {"id": "condition", **contract},
                {"id": "when-false", **contract},
                {"id": "when-true", **contract},
            ],
            "result": contract,
            "body": {
                "nodes": [
                    {
                        "id": "choice",
                        "node": "conditional",
                        "condition": {
                            "kind": "parameter",
                            "parameter": "condition",
                        },
                        "when_true": {
                            "kind": "parameter",
                            "parameter": "when-true",
                        },
                        "when_false": {
                            "kind": "parameter",
                            "parameter": "when-false",
                        },
                    }
                ],
                "result": {"kind": "local", "local": "choice"},
            },
            "expression": (
                "let choice = if condition then `when-true` else `when-false`;\n"
                "choice"
            ),
        }
    ]
    source_document["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "choose-value"},
            "arguments": [
                {
                    "parameter": "condition",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "constant_value",
                    },
                },
                {
                    "parameter": "when-false",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                },
                {
                    "parameter": "when-true",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "parameter_value",
                    },
                },
            ],
        }
    ]
    _use_derived_value(source_document)
    source = tmp_path / "conditional-formula.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_type_mismatch"
    assert diagnostic["primary"]["pointer"] == "/modules/0/formulas/0"


def test_model_build_binds_a_formula_to_an_operation_slot(tmp_path, run_cli):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 200},
        "numeric_policy": "exact-int64",
    }
    source_document["modules"][0]["formulas"] = [
        formula
        for formula in source_document["modules"][0]["formulas"]
        if formula["id"] != "mitigated-damage"
    ] + [
        {
            "id": "mitigated-damage",
            "parameters": [
                {"id": "damage_before_defense", **quantity_contract},
                {"id": "mitigation", **quantity_contract},
            ],
            "result": quantity_contract,
            "body": {
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
                        "result": {
                            **quantity_contract,
                            "domain": {"minimum": -200, "maximum": 200},
                        },
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
                                "operand": {
                                    "kind": "local",
                                    "local": "raw_damage",
                                },
                            },
                        ],
                        "result": quantity_contract,
                    },
                ],
                "result": {"kind": "local", "local": "damage"},
            },
            "expression": (
                "let raw_damage = damage_before_defense - mitigation;\n"
                "let damage = floor_zero(raw_damage);\n"
                "damage"
            ),
        }
    ]
    source_document["formula_bindings"] = [
        binding
        for binding in source_document["formula_bindings"]
        if binding["site"]["kind"] != "operation-slot"
    ] + [
        {
            "site": {
                "kind": "operation-slot",
                "operation": {
                    "package": "game.combat",
                    "version": "2.0.0",
                    "id": "game.combat.damage-v1",
                },
                "slot": "damage-policy",
            },
            "formula": {"module": "combat", "id": "mitigated-damage"},
            "arguments": [
                {
                    "parameter": "damage_before_defense",
                    "operand": {
                        "kind": "slot-parameter",
                        "parameter": "damage_before_defense",
                    },
                },
                {
                    "parameter": "mitigation",
                    "operand": {
                        "kind": "slot-parameter",
                        "parameter": "mitigation",
                    },
                },
            ],
        }
    ]
    source = tmp_path / "operation-slot-formula.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")
    out = tmp_path / "resolved-model.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), stdout
    receipt = json.loads(stdout)
    rir = json.loads(
        (_artifact_directory(receipt) / "rir-semantic-payload.json").read_text(
            encoding="utf-8"
        )
    )
    binding = next(
        row
        for row in rir["formula_bindings"]
        if row["site"]["kind"] == "operation-slot"
    )
    assert binding["site"]["kind"] == "operation-slot"
    assert binding["site"]["operation"] == {
        "package": "game.combat",
        "version": "2.0.0",
        "id": "game.combat.damage-v1",
        "identity": binding["site"]["operation"]["identity"],
    }
    assert binding["site"]["slot"] == "damage-policy"
    assert binding["site"]["context"] == {
        "phase": "event",
        "frame": "pre-event-snapshot",
    }
    assert [row["operand"]["parameter"] for row in binding["arguments"]] == [
        "damage_before_defense",
        "mitigation",
    ]


def test_operation_slot_direct_result_charge_matches_its_lowered_instruction(
    tmp_path, run_cli
):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    formula = next(
        row
        for row in source_document["modules"][0]["formulas"]
        if row["id"] == "mitigated-damage"
    )
    formula["body"] = {
        "node": "parameter",
        "parameter": "damage_before_defense",
    }
    formula["expression"] = "damage_before_defense"
    source = tmp_path / "direct-result-slot-formula.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "direct-result-slot-model"),
            "--invocation-key",
            "8" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, ""), stdout
    rir = json.loads(
        (
            _artifact_directory(json.loads(stdout)) / "rir-semantic-payload.json"
        ).read_text(encoding="utf-8")
    )
    resolved_formula = next(
        row for row in rir["formulas"] if row["id"] == "mitigated-damage"
    )
    damage = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "game.combat.damage-v1"
    )
    slot = damage["extensions"]["standard.formula-slots"][0]
    lowered = damage["body"][slot["placeholder_index"] : slot["placeholder_index"] + 1]

    assert resolved_formula["closure"]["resource_charge"] == {"max_steps": 1}
    assert lowered == [
        {
            "node": "copy",
            "target": slot["target"],
            "value": "damage_before_defense",
        }
    ]


@pytest.mark.parametrize(
    ("mutation", "expected_code", "expected_pointer"),
    (
        (
            "missing-binding",
            "language.formula_binding_missing",
            "/entrypoints/0/operation",
        ),
        (
            "missing-declaration",
            "language.formula_binding_missing",
            "/entrypoints/0/operation",
        ),
        (
            "duplicate-binding",
            "language.formula_binding_duplicate",
            "/formula_bindings/2/site",
        ),
        (
            "duplicate-operation-slot-binding",
            "language.formula_binding_duplicate",
            "/formula_bindings/2/site",
        ),
        (
            "resource-budget",
            "language.formula_resource_exhausted",
            "/formula_bindings/1/formula",
        ),
    ),
)
def test_model_check_refuses_operation_formula_slot_contract_violations(
    mutation, expected_code, expected_pointer, tmp_path, run_cli
):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    if mutation == "missing-binding":
        source_document["formula_bindings"] = []
    elif mutation == "missing-declaration":
        source_document["modules"][0]["formulas"] = []
        source_document["formula_bindings"] = []
    elif mutation == "duplicate-binding":
        source_document["formula_bindings"].append(
            deepcopy(source_document["formula_bindings"][0])
        )
    elif mutation == "duplicate-operation-slot-binding":
        source_document["formula_bindings"].append(
            deepcopy(source_document["formula_bindings"][1])
        )
    else:
        formula = source_document["modules"][0]["formulas"][0]
        result_contract = deepcopy(formula["result"])
        formula["body"]["nodes"].append(
            {
                "id": "over-budget-copy",
                "node": "operation-call",
                "operation": {
                    "package": "core.quantity",
                    "version": "2.1.0",
                    "id": "quantity.identity",
                },
                "arguments": [
                    {
                        "port": "value",
                        "operand": {"kind": "local", "local": "damage"},
                    }
                ],
                "result": result_contract,
            }
        )
        formula["body"]["result"] = {
            "kind": "local",
            "local": "over-budget-copy",
        }
        formula["expression"] = (
            "let raw_damage = damage_before_defense - mitigation;\n"
            "let damage = floor_zero(raw_damage);\n"
            "let `over-budget-copy` = identity(damage);\n"
            "`over-budget-copy`"
        )
    source = tmp_path / f"{mutation}.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == expected_code
    assert diagnostic["primary"]["pointer"] == expected_pointer


def test_model_check_refuses_an_effectful_operation_in_a_formula(tmp_path, run_cli):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    formula = next(
        row
        for row in source_document["modules"][0]["formulas"]
        if row["id"] == "effective-accuracy"
    )
    formula["body"] = {
        "nodes": [
            {
                "id": "effectful-call",
                "node": "operation-call",
                "operation": {
                    "package": "game.combat",
                    "version": "2.0.0",
                    "id": "game.combat.cast-v1",
                },
                "arguments": [],
                "result": deepcopy(formula["result"]),
            }
        ],
        "result": {"kind": "local", "local": "effectful-call"},
    }
    source = tmp_path / "effectful-formula.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_purity_mismatch"
    assert diagnostic["primary"]["pointer"] == "/modules/0/formulas/1"


@pytest.mark.parametrize(
    ("member", "value", "reason_id", "diagnostic"),
    (
        (
            "kind",
            "boolean",
            "model.reason.formula-kind-mismatch",
            "language.formula_kind_mismatch",
        ),
        (
            "unit",
            "turn",
            "model.reason.formula-unit-mismatch",
            "language.formula_unit_mismatch",
        ),
        (
            "numeric_policy",
            "exact-bool",
            "model.reason.formula-numeric-profile-mismatch",
            "language.formula_numeric_profile_mismatch",
        ),
    ),
)
def test_formula_slot_value_axes_have_stable_authority_diagnostics(
    member,
    value,
    reason_id,
    diagnostic,
    tmp_path,
    run_cli,
):
    source_document = _model_source()
    source_document["modules"][0]["formulas"] = [
        {
            "id": "derive-value",
            "parameters": [
                {
                    "id": "base",
                    "type": "quantity",
                    "representation": "Int",
                    "kind": "scalar",
                    "unit": "1",
                    "domain_kind": "closed-interval",
                    "domain": {"minimum": 0, "maximum": 100},
                    "numeric_policy": "exact-int64",
                }
            ],
            "result": {
                "type": "quantity",
                "representation": "Int",
                "kind": "scalar",
                "unit": "1",
                "domain_kind": "closed-interval",
                "domain": {"minimum": 0, "maximum": 100},
                "numeric_policy": "exact-int64",
            },
            "body": {"node": "parameter", "parameter": "base"},
            "expression": "base",
        }
    ]
    source_document["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "derive-value"},
            "arguments": [
                {
                    "parameter": "base",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    _use_derived_value(source_document)
    formula = source_document["modules"][0]["formulas"][0]
    formula["parameters"][0][member] = value
    formula["result"][member] = value
    source = tmp_path / f"formula-{member}-mismatch.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic_row = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic_row["code"] == diagnostic
    assert diagnostic_row["primary"]["pointer"] == "/formula_bindings/0/formula"
    _, language_bundle = authority_module.load_authorities()
    assert (
        model_module.reason_by_id(language_bundle, reason_id)["diagnostic"]
        == diagnostic
    )


@pytest.mark.parametrize(
    ("mutation", "vector_id", "reason_id", "diagnostic", "pointer"),
    (
        (
            "context",
            "formula.refuse.context-mismatch",
            "model.reason.formula-context-mismatch",
            "language.formula_context_mismatch",
            "/formula_bindings/1/site",
        ),
        (
            "refusals",
            "formula.refuse.refusal-widening",
            "model.reason.formula-refusal-widening",
            "language.formula_refusal_widening",
            "/formula_bindings/1/formula",
        ),
    ),
)
def test_formula_slot_authority_drift_reaches_the_public_model_check_refusal(
    mutation,
    vector_id,
    reason_id,
    diagnostic,
    pointer,
    run_cli,
    monkeypatch,
):
    source = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    context = authority_module.packaged_authority_context()
    kernel, language_bundle = context.mutable_pair()
    vector = next(
        item
        for vector_set in language_bundle.package_conformance_vector_sets
        if vector_set["package_id"] == "standard.compiler"
        for item in vector_set["vector_definitions"]
        if item["id"] == vector_id
    )
    damage = next(
        operation
        for operation in language_bundle["language"]["operations"]
        if operation["id"] == "game.combat.damage-v1"
    )
    slot = damage["extensions"]["standard.formula-slots"][0]
    if mutation == "context":
        slot["context"] = {"phase": "event", "frame": "host-owned-frame"}
    else:
        slot["permitted_refusals"] = []
    assert vector == {
        "diagnostic": diagnostic,
        "id": vector_id,
        "input": {"actual": "incompatible", "expected": "compatible"},
        "matched": True,
        "reason": reason_id,
        "stage": "static",
    }
    _reidentify_language_bundle(language_bundle)
    drifted = authority_module.admit_authority_context(kernel, language_bundle)
    assert isinstance(drifted, authority_module.AdmittedAuthorityContext)
    monkeypatch.setattr(
        model_module,
        "packaged_authority_context",
        lambda: drifted,
    )

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    row = json.loads(stdout)["error"]["diagnostics"][0]
    assert row["code"] == diagnostic
    assert row["primary"]["pointer"] == pointer


def test_model_check_points_a_non_first_formula_error_at_its_declaration(
    tmp_path, run_cli
):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    second_formula = source_document["modules"][0]["formulas"][1]
    second_formula["result"]["domain"]["maximum"] = 999
    source = tmp_path / "second-formula-error.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_type_mismatch"
    assert diagnostic["primary"]["pointer"] == "/modules/0/formulas/1"


def test_model_check_points_a_non_first_binding_budget_error_at_its_formula(
    tmp_path, run_cli
):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    formulas = source_document["modules"][0]["formulas"]
    formulas.reverse()
    formula = next(row for row in formulas if row["id"] == "mitigated-damage")
    result_contract = deepcopy(formula["result"])
    formula["body"]["nodes"].append(
        {
            "id": "over-budget-copy",
            "node": "operation-call",
            "operation": {
                "package": "core.quantity",
                "version": "2.1.0",
                "id": "quantity.identity",
            },
            "arguments": [
                {
                    "port": "value",
                    "operand": {"kind": "local", "local": "damage"},
                }
            ],
            "result": result_contract,
        }
    )
    formula["body"]["result"] = {
        "kind": "local",
        "local": "over-budget-copy",
    }
    source = tmp_path / "second-formula-binding-budget.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_resource_exhausted"
    assert diagnostic["primary"]["pointer"] == "/formula_bindings/1/formula"


def test_model_check_refuses_an_event_formula_symbol_absent_before_the_event(
    tmp_path, run_cli
):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    formula = next(
        row
        for row in source_document["modules"][0]["formulas"]
        if row["id"] == "mitigated-damage"
    )
    formula["body"] = {
        "nodes": [],
        "result": {
            "kind": "symbol",
            "module": "combat",
            "symbol": "damage_dealt",
        },
    }
    formula["expression"] = "combat.damage_dealt"
    source = tmp_path / "event-formula-output-symbol.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.source_contract_mismatch"
    assert diagnostic["primary"]["pointer"] == "/entrypoints/0/operation"


def test_model_check_refuses_a_derived_formula_result_outside_its_symbol_contract(
    tmp_path, run_cli
):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    derived = next(
        symbol
        for symbol in source_document["modules"][0]["symbols"]
        if symbol["symbol"] == "effective_accuracy"
    )
    derived["domain"]["maximum"] = 10
    source = tmp_path / "incompatible-derived-result.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_type_mismatch"
    assert diagnostic["primary"]["pointer"] == "/formula_bindings/0/formula"


def test_model_check_refuses_an_unreachable_derived_formula_binding(tmp_path, run_cli):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    module = source_document["modules"][0]
    unused_symbol = deepcopy(
        next(
            symbol
            for symbol in module["symbols"]
            if symbol["symbol"] == "effective_accuracy"
        )
    )
    unused_symbol["symbol"] = "unused_derived"
    module["symbols"].append(unused_symbol)
    unused_formula = deepcopy(
        next(
            formula
            for formula in module["formulas"]
            if formula["id"] == "effective-accuracy"
        )
    )
    unused_formula["id"] = "unused-formula"
    module["formulas"].append(unused_formula)
    unused_binding = deepcopy(source_document["formula_bindings"][0])
    unused_binding["site"]["symbol"] = "unused_derived"
    unused_binding["formula"]["id"] = "unused-formula"
    source_document["formula_bindings"].append(unused_binding)
    source = tmp_path / "unreachable-derived-binding.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_unreachable"
    assert diagnostic["primary"]["pointer"] == "/formula_bindings/2/site"


def test_model_check_refuses_an_unreachable_operation_slot_binding(tmp_path, run_cli):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    source_document["entrypoints"] = [
        {
            "id": "resource.spend",
            "operation": {
                "package": "game.resource",
                "version": "1.0.1",
                "id": "game.resource.spend-v1",
            },
            "arguments": [
                {
                    "port": "resource",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "actor_mana",
                    },
                },
                {
                    "port": "cost",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "action_cost",
                    },
                },
            ],
            "result": {"kind": "discard"},
        }
    ]
    source_document["formula_bindings"] = [
        binding
        for binding in source_document["formula_bindings"]
        if binding["site"]["kind"] == "operation-slot"
    ]
    source = tmp_path / "unreachable-operation-slot-binding.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_unreachable"
    assert diagnostic["primary"]["pointer"] == "/formula_bindings/0/site"


def test_model_check_resolves_capabilities_from_transitive_package_dependencies(
    tmp_path, run_cli
):
    source_document = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["checked"] is True


def test_model_check_rejects_an_invalid_value_policy_on_an_unused_symbol(
    tmp_path, run_cli
):
    source_value = _model_source()
    output = next(
        row for row in source_value["modules"][0]["symbols"] if row["role"] == "output"
    )
    output["value_policy"] = {"mode": "experiment-required"}
    source = tmp_path / "invalid-unused-value-policy.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    diagnostic = json.loads(stdout)["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.source_contract_mismatch"
    assert diagnostic["primary"]["pointer"] == ("/modules/0/symbols/5/value_policy")


def test_model_check_refuses_conflicting_transitive_dependency_versions(
    tmp_path, monkeypatch
):
    kernel, baseline_ldb = authority_module.load_authorities()
    candidate_ldb = deepcopy(baseline_ldb)
    language = candidate_ldb["language"]
    seed = next(
        package
        for package in language["packages"]
        if package["id"] == "standard.compiler"
    )

    def empty_package(
        package_id: str,
        version: str,
        dependencies: list[dict[str, str]],
    ) -> dict[str, Any]:
        package = deepcopy(seed)
        package["id"] = package_id
        package["version"] = version
        package["dependencies"] = {"optional": [], "required": dependencies}
        package["capabilities"] = {"provided": [], "required": []}
        package["exports"] = {name: [] for name in package["exports"]}
        package["profiles"] = {"numeric": [], "resolution": [], "runtime": []}
        package["runtime_semantic_paths"] = ["language.capabilities"]
        for entry in package["semantic_closure"]:
            entry["definitions"] = []
        return package

    added_packages = [
        empty_package("shared.rules", "1.0.0", []),
        empty_package("shared.rules", "2.0.0", []),
        empty_package(
            "genre.parenta",
            "1.0.0",
            [{"id": "shared.rules", "version": "1.0.0"}],
        ),
        empty_package(
            "genre.parentb",
            "1.0.0",
            [{"id": "shared.rules", "version": "2.0.0"}],
        ),
    ]
    language["packages"].extend(added_packages)
    candidate_ldb.package_conformance_vector_sets.extend(
        _package_vector_set(package["id"], package["version"], [])
        for package in added_packages
    )
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)
    source_document = _model_source()
    source_document["package_requirements"].extend(
        [
            {"id": "genre.parenta", "version": "1.0.0"},
            {"id": "genre.parentb", "version": "1.0.0"},
        ]
    )
    source = tmp_path / "conflicting-transitive-versions.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    result = model_module.check_model_source(str(source))

    assert isinstance(result, model_module.Schema2RefusalReport)
    assert result.stage == "resolution"
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "language.resolution_ambiguity"
    ]


def test_in_memory_model_check_reuses_only_a_matching_authority_admission():
    kernel, language_bundle = authority_module.load_authorities()
    admission = admit_authorities(kernel, language_bundle)

    checked = model_module.check_model_source_value(
        _model_source(),
        kernel=kernel,
        language_bundle=language_bundle,
        authority_admission=admission,
    )

    assert isinstance(checked, model_module.CheckedModel)
    mismatched_ldb = deepcopy(language_bundle)
    mismatched_ldb["content_identity"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="another Kernel/LDB pair"):
        model_module.check_model_source_value(
            _model_source(),
            kernel=kernel,
            language_bundle=mismatched_ldb,
            authority_admission=admission,
        )


def test_model_check_runs_the_same_lowering_and_admission_front_end(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    calls = 0
    real_lowerer = model_module.lower_checked_model

    def observed_lowerer(checked):
        nonlocal calls
        calls += 1
        return real_lowerer(checked)

    monkeypatch.setattr(model_command_module, "lower_checked_model", observed_lowerer)

    assert run_cli(["model", "check", str(source)])[0] == 0
    assert calls == 1
    assert set(tmp_path.iterdir()) == {source}


def test_model_check_refuses_an_inverted_quantity_support_interval(tmp_path, run_cli):
    source_document = _model_source()
    _symbols(source_document)[0]["domain"] = {"minimum": 2, "maximum": 1}
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.invalid_domain"
    ]


def test_model_check_reports_all_static_diagnostics_in_canonical_location_order(
    tmp_path, run_cli
):
    source_document = _model_source()
    _symbols(source_document)[0]["kind"] = "unknown-kind"
    _symbols(source_document)[1]["unit"] = "unknown-unit"
    _symbols(source_document)[2]["domain"] = {"minimum": 2, "maximum": 1}
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    ] == [
        ("/modules/0/symbols/0/kind", "language.unknown_kind"),
        ("/modules/0/symbols/1/unit", "language.unknown_unit"),
        ("/modules/0/symbols/2/domain", "language.invalid_domain"),
    ]
    assert error["truncated"] is False


def test_model_check_applies_the_ldb_diagnostic_cap_and_marks_truncation(
    tmp_path, run_cli, monkeypatch
):
    source_document = _model_source()
    for symbol in _symbols(source_document)[:3]:
        symbol["kind"] = "unknown-kind"
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")
    kernel, language_bundle = authority_module.load_authorities()
    candidate_ldb = deepcopy(language_bundle)
    candidate_ldb["resources"]["max_diagnostics"] = 2
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert [item["primary"]["pointer"] for item in error["diagnostics"]] == [
        "/modules/0/symbols/0/kind",
        "/modules/0/symbols/1/kind",
    ]
    assert error["truncated"] is True


def test_symbol_uniqueness_is_scoped_to_each_module_and_locates_the_duplicate(
    tmp_path, run_cli
):
    across_modules = _model_source()
    second_module = deepcopy(across_modules["modules"][0])
    second_module["id"] = "secondary"
    across_modules["modules"].append(second_module)
    accepted = tmp_path / "accepted.json"
    accepted.write_text(json.dumps(across_modules), encoding="utf-8")

    assert run_cli(["model", "check", str(accepted)])[0] == 0

    within_module = _model_source()
    _symbols(within_module).append(deepcopy(_symbols(within_module)[0]))
    refused = tmp_path / "refused.json"
    refused.write_text(json.dumps(within_module), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(refused)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert len(error["diagnostics"]) == 1
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == "language.duplicate_symbol"
    assert diagnostic["primary"]["pointer"] == "/modules/0/symbols/7/symbol"
    assert [item["pointer"] for item in diagnostic["related"]] == [
        "/modules/0/symbols/0/symbol"
    ]


def test_model_check_refuses_a_source_without_a_selected_domain_package(
    tmp_path, run_cli
):
    source_document = _model_source()
    source_document["package_requirements"] = []
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert {
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    } == {
        (
            "/package_requirements",
            "language.source_contract_mismatch",
        ),
        (
            "/modules/0/imports/0/package",
            "language.unresolved_name",
        ),
    }


def test_model_check_classifies_an_unavailable_exact_package_as_resolution(
    tmp_path, run_cli
):
    source_document = _model_source()
    source_document["package_requirements"][0]["version"] = "9.0.0"
    source_document["modules"][0]["imports"][0]["version"] = "9.0.0"
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert [
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    ] == [
        (
            "/package_requirements/0/version",
            "language.package_version_unavailable",
        )
    ]
    assert error["truncated"] is False


def test_model_check_classifies_name_legality_as_static(tmp_path, run_cli):
    duplicate_alias = _model_source()
    duplicate_alias["modules"][0]["imports"].append(
        deepcopy(duplicate_alias["modules"][0]["imports"][0])
    )
    duplicate_path = tmp_path / "duplicate-alias.json"
    duplicate_path.write_text(json.dumps(duplicate_alias), encoding="utf-8")

    unresolved_name = _model_source()
    unresolved_name["modules"][0]["symbols"][0]["type"] = "missing"
    unresolved_path = tmp_path / "unresolved-name.json"
    unresolved_path.write_text(json.dumps(unresolved_name), encoding="utf-8")

    duplicate = run_cli(["model", "check", str(duplicate_path)])
    unresolved = run_cli(["model", "check", str(unresolved_path)])

    assert duplicate[0] == unresolved[0] == 2
    duplicate_error = json.loads(duplicate[1])["error"]
    unresolved_error = json.loads(unresolved[1])["error"]
    assert duplicate_error["stage"] == "static"
    assert duplicate_error["diagnostics"][0]["code"] == "language.name_ambiguity"
    assert duplicate_error["diagnostics"][0]["primary"]["pointer"] == (
        "/modules/0/imports/1/alias"
    )
    assert unresolved_error["stage"] == "static"
    assert unresolved_error["diagnostics"][0]["code"] == "language.unresolved_name"
    assert unresolved_error["diagnostics"][0]["primary"]["pointer"] == (
        "/modules/0/symbols/0/type"
    )


def test_model_check_reports_structural_members_at_the_exact_artifact_pointer(
    tmp_path, run_cli
):
    source_document = _model_source()
    del source_document["modules"][0]["symbols"][0]["unit"]
    source_document["modules"][0]["symbols"][1]["unexpected"] = True
    source = tmp_path / "structural-errors.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [
        (item["primary"]["kind"], item["primary"]["pointer"], item["code"])
        for item in error["diagnostics"]
    ] == [
        (
            "artifact",
            "/modules/0/symbols/0/unit",
            "language.source_contract_mismatch",
        ),
        (
            "artifact",
            "/modules/0/symbols/1/unexpected",
            "language.source_contract_mismatch",
        ),
    ]


def test_model_check_gates_resolution_when_required_top_level_members_are_missing(
    tmp_path, run_cli
):
    source = tmp_path / "structurally-incomplete.json"
    source.write_text('{"schema_version":"2.0.0"}', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert {
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    } == {
        ("/manifest", "language.source_contract_mismatch"),
        ("/package_requirements", "language.source_contract_mismatch"),
        ("/modules", "language.source_contract_mismatch"),
        ("/entrypoints", "language.source_contract_mismatch"),
    }


def test_model_check_reports_source_size_at_ingress(tmp_path, run_cli):
    source = tmp_path / "oversized-source.json"
    source.write_bytes(b" " * (1024 * 1024 + 1))

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert error["diagnostics"][0]["code"] == "language.source_too_large"


def test_model_check_reports_wire_decode_failure_at_parse(tmp_path, run_cli):
    source = tmp_path / "malformed-source.json"
    source.write_text('{"schema_version":"2.0.0",', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "parse"
    assert error["diagnostics"][0]["code"] == "language.source_parse_failure"


@pytest.mark.parametrize("anchor_key", [None, "A5" * 32, "a5" * 31, "not-hex"])
def test_model_build_rejects_invalid_anchor_authentication_configuration_before_publication(
    tmp_path, run_cli, monkeypatch, anchor_key
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    store = tmp_path / "store"
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store))
    if anchor_key is None:
        monkeypatch.delenv("GDA_BALANCING_ANCHOR_KEY", raising=False)
    else:
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", anchor_key)

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    error = json.loads(stderr)["error"]
    assert error == {
        "category": "usage",
        "code": "invalid_argument",
        "message": (
            "GDA_BALANCING_ANCHOR_KEY must contain exactly 64 lowercase "
            "hexadecimal digits"
        ),
    }
    assert not out.exists()
    assert not store.exists()


def test_model_build_validates_anchor_configuration_before_reading_source(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "missing-model-source.json"
    out = tmp_path / "published-model"
    monkeypatch.delenv("GDA_BALANCING_ANCHOR_KEY", raising=False)

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invalid_argument"
    assert not out.exists()


def test_model_build_atomically_publishes_a_framed_typed_artifact_set(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    invocation_key = "a" * 64

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            invocation_key,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    assert receipt["artifact_kind"] == "artifact-set-receipt"
    assert receipt["invocation_key"] == invocation_key
    artifact_dir = _artifact_directory(receipt)
    assert receipt["manifest_locator"] == str(
        artifact_dir / "artifact-set-manifest.json"
    )
    assert receipt["member_locators"] == [
        {
            "logical_name": name,
            "locator": str(artifact_dir / f"{name}.json"),
        }
        for name in (
            "build-receipt",
            "capability-manifest",
            "debug-map",
            "model-explanation",
            "package-lock",
            "resolution-receipt",
            "resolved-model",
            "rir-semantic-payload",
        )
    ]
    assert out.is_file()
    assert json.loads(out.read_text())["artifact_kind"] == "resolved-model"
    assert receipt["content_identity"] == content_identity(
        "artifact-set-receipt-v2",
        {
            key: value
            for key, value in receipt.items()
            if key
            not in {
                "content_identity",
                "manifest_locator",
                "member_locators",
            }
        },
    )

    manifest = json.loads((artifact_dir / "artifact-set-manifest.json").read_text())
    assert manifest["artifact_kind"] == "artifact-set-manifest"
    assert [item["logical_name"] for item in manifest["members"]] == [
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "model-explanation",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    ]
    for member in manifest["members"]:
        assert member["artifact_kind"]
        assert member["wire_schema_identity"].startswith("sha256:")
        path = artifact_dir / f"{member['logical_name']}.json"
        artifact = json.loads(path.read_text())
        assert artifact["content_identity"] == member["content_identity"]
        assert "locator" not in member

    assert (
        json.loads((artifact_dir / "artifact-set-receipt.json").read_text()) == receipt
    )
    assert (artifact_dir / "publication-index.json").is_file()
    assert sorted(path.name for path in artifact_dir.iterdir()) == [
        "artifact-set-manifest.json",
        "artifact-set-receipt.json",
        "build-receipt.json",
        "capability-manifest.json",
        "debug-map.json",
        "model-explanation.json",
        "package-lock.json",
        "publication-index.json",
        "resolution-receipt.json",
        "resolved-model.json",
        "rir-semantic-payload.json",
    ]

    schema_exit, schema_stdout, schema_stderr = run_cli(
        ["schema", "get", "wire-schema"]
    )
    assert (schema_exit, schema_stderr) == (0, "")
    schemas = {
        item["artifact_kind"]: item["schema"]
        for item in json.loads(schema_stdout)["schemas"]
    }
    for member in manifest["members"]:
        schema = schemas[member["artifact_kind"]]
        schema_identity = "sha256:" + schema["$id"].rsplit(":", 1)[-1]
        assert member["wire_schema_identity"] == schema_identity
        jsonschema.validate(
            json.loads((artifact_dir / f"{member['logical_name']}.json").read_text()),
            schema,
        )
    surface = json.loads(run_cli(["manifest"])[1])
    model_build = next(
        row
        for row in surface["commands"]
        if row["group"] == "model" and row["command"] == "build"
    )
    assert model_build["artifact_set"] == [
        {
            "logical_name": item["logical_name"],
            "artifact_kind": item["artifact_kind"],
            "role": (
                "primary" if item["logical_name"] == "resolved-model" else "companion"
            ),
        }
        for item in manifest["members"]
    ]


def test_model_build_descriptor_declares_exactly_one_primary_artifact():
    members = model_command_module.MODEL_BUILD.artifact_set
    assert [member.logical_name for member in members if member.role == "primary"] == [
        "resolved-model"
    ]

    without_primary = tuple(replace(member, role="companion") for member in members)
    with pytest.raises(ValueError, match="exactly one primary"):
        replace(model_command_module.MODEL_BUILD, artifact_set=without_primary)

    multiple_primary = tuple(
        replace(
            member,
            role=(
                "primary"
                if member.logical_name in {"package-lock", "resolved-model"}
                else "companion"
            ),
        )
        for member in members
    )
    with pytest.raises(ValueError, match="exactly one primary"):
        replace(model_command_module.MODEL_BUILD, artifact_set=multiple_primary)


def test_model_publisher_materializes_the_descriptor_declared_primary_member(
    tmp_path, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
    artifact_set = tuple(
        replace(
            member,
            role=("primary" if member.logical_name == "package-lock" else "companion"),
        )
        for member in model_command_module.MODEL_BUILD.artifact_set
    )
    out = tmp_path / "primary.json"

    model_module.publish_model_artifacts(
        checked,
        str(source),
        str(out),
        "b" * 64,
        "sha256:" + "b" * 64,
        artifact_set,
    )

    assert json.loads(out.read_text())["artifact_kind"] == "package-lock"


def test_artifact_set_manifest_identity_is_independent_of_store_and_invocation(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    manifests = []
    receipts = []

    for index in (1, 2):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / f"store-{index}"))
        built = run_cli(
            [
                "model",
                "build",
                str(source),
                "--out",
                str(tmp_path / f"published-{index}.json"),
                "--invocation-key",
                str(index) * 64,
            ]
        )
        assert built[0] == 0
        receipt = json.loads(built[1])
        receipts.append(receipt)
        manifests.append(
            json.loads(
                (
                    _artifact_directory(receipt) / "artifact-set-manifest.json"
                ).read_text()
            )
        )

    assert manifests[0]["members"] == manifests[1]["members"]
    assert manifests[0]["content_identity"] == manifests[1]["content_identity"]
    assert canonical_bytes(manifests[0]) == canonical_bytes(manifests[1])
    assert receipts[0]["member_locators"] != receipts[1]["member_locators"]


def test_model_build_retry_recovers_without_running_the_lowerer(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "b" * 64,
    ]
    first = run_cli(argv)
    assert first[0] == 0

    def lowerer_must_not_run(_checked):
        raise AssertionError("retry executed the lowerer")

    monkeypatch.setattr(model_module, "lower_checked_model", lowerer_must_not_run)
    second = run_cli(argv)

    assert second == first


def test_model_build_retry_can_select_a_new_presentation_without_reexecution(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    first_out = tmp_path / "first.json"
    second_out = tmp_path / "second.json"
    key = "5" * 64
    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(first_out),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0

    def lowerer_must_not_run(_checked):
        raise AssertionError("retry executed the lowerer")

    monkeypatch.setattr(model_module, "lower_checked_model", lowerer_must_not_run)
    second = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(second_out),
            "--invocation-key",
            key,
        ]
    )

    assert second == first
    assert first_out.read_bytes() == second_out.read_bytes()
    assert json.loads(second_out.read_text())["artifact_kind"] == "resolved-model"


def test_model_build_retry_rejects_output_aliases_to_every_committed_publication_file(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    key = "9" * 64
    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "published-model.json"),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    committed = sorted(artifact_dir.iterdir())
    before = {path.name: path.read_bytes() for path in committed}

    for member in committed:
        for alias_kind, out in (
            ("direct", member),
            ("symlink", tmp_path / f"{member.stem}-alias.json"),
        ):
            if alias_kind == "symlink":
                out.symlink_to(member)

            exit_code, stdout, stderr = run_cli(
                [
                    "model",
                    "build",
                    str(source),
                    "--out",
                    str(out),
                    "--invocation-key",
                    key,
                ]
            )

            assert (exit_code, stdout) == (3, "")
            assert json.loads(stderr)["error"]["code"] == "argument_conflict"
            assert {path.name: path.read_bytes() for path in committed} == before
            if alias_kind == "symlink":
                out.unlink()


def test_model_commands_share_the_descriptor_owned_structured_input(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    assert run_cli(
        [
            "model",
            "check",
            "--params-json",
            json.dumps({"source": str(source)}),
        ]
    ) == run_cli(["model", "check", str(source)])

    out = tmp_path / "published-model"
    params = {
        "source": str(source),
        "out": str(out),
        "invocation_key": "b" * 64,
    }
    direct = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "b" * 64,
        ]
    )
    structured = run_cli(["model", "build", "--params-json", json.dumps(params)])
    assert structured == direct


def test_model_build_rejects_invocation_key_reuse_for_changed_input(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    key = "c" * 64
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        key,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    before = {path.name: path.read_bytes() for path in artifact_dir.iterdir()}
    changed = _model_source()
    _symbols(changed)[0]["domain"]["maximum"] = 101
    source.write_text(json.dumps(changed), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invocation_key_conflict"
    assert {path.name: path.read_bytes() for path in artifact_dir.iterdir()} == before


def test_model_build_rejects_changed_input_for_the_same_store_invocation_key_even_when_out_changes(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    key = "8" * 64
    first_parent = tmp_path / "first-store-presentation"
    second_parent = tmp_path / "second-store-presentation"
    first_parent.mkdir()
    second_parent.mkdir()

    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(first_parent / "model.json"),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0
    changed = _model_source()
    _symbols(changed)[0]["domain"]["maximum"] = 101
    source.write_text(json.dumps(changed), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(second_parent / "model.json"),
            "--invocation-key",
            key,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invocation_key_conflict"


def test_model_build_rejects_invocation_key_reuse_after_exact_authority_changes(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    key = "a" * 64
    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "first.json"),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    before = {path.name: path.read_bytes() for path in artifact_dir.iterdir()}

    kernel, language_bundle = authority_module.load_authorities()
    candidate_ldb = deepcopy(language_bundle)
    candidate_ldb["resources"]["max_diagnostics"] -= 1
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "second.json"),
            "--invocation-key",
            key,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invocation_key_conflict"
    assert {path.name: path.read_bytes() for path in artifact_dir.iterdir()} == before
    assert not (tmp_path / "second.json").exists()


def test_model_build_rejects_direct_and_symlink_input_output_aliases(tmp_path, run_cli):
    for suffix, out_factory in (
        ("direct", lambda source: source),
        ("symlink", lambda source: tmp_path / "source-alias.json"),
    ):
        source = tmp_path / f"model-source-{suffix}.json"
        source.write_text(json.dumps(_model_source()), encoding="utf-8")
        before = source.read_bytes()
        out = out_factory(source)
        if suffix == "symlink":
            out.symlink_to(source)

        exit_code, stdout, stderr = run_cli(
            [
                "model",
                "build",
                str(source),
                "--out",
                str(out),
                "--invocation-key",
                ("d" if suffix == "direct" else "e") * 64,
            ]
        )

        assert (exit_code, stdout) == (3, "")
        assert json.loads(stderr)["error"]["code"] == "argument_conflict"
        assert source.read_bytes() == before


def test_model_publisher_rejects_a_known_source_alias_after_the_source_disappears(
    tmp_path, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    source.unlink()
    store = tmp_path / "store"
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store))

    with pytest.raises(model_module.UsageError) as caught:
        model_module.publish_model_artifacts(
            checked,
            str(source),
            str(source),
            "e" * 64,
            descriptor_identity(model_command_module.MODEL_BUILD),
            model_command_module.MODEL_BUILD.artifact_set,
        )

    assert caught.value.code == "argument_conflict"
    assert not source.exists()
    assert not store.exists()


def test_model_build_rejects_a_symlinked_store_ancestor(tmp_path, run_cli, monkeypatch):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    real_store_parent = tmp_path / "real-store-parent"
    real_store_parent.mkdir()
    store_alias = tmp_path / "store-alias"
    store_alias.symlink_to(real_store_parent, target_is_directory=True)
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store_alias / "schema2-store"))
    out = tmp_path / "published-model.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"
    assert not out.exists()


def test_model_build_rejects_every_output_overlap_with_the_reserved_invocation_path(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    store = tmp_path / "store"
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store))
    key = "f" * 64
    descriptor_key = descriptor_identity(model_command_module.MODEL_BUILD).removeprefix(
        "sha256:"
    )
    invocation_path = store / "invocations" / descriptor_key / key
    invocation_path.parent.mkdir(parents=True)

    for out in (
        store,
        store / "invocations",
        invocation_path.parent,
        invocation_path,
        invocation_path / "resolved-model.json",
    ):
        exit_code, stdout, stderr = run_cli(
            [
                "model",
                "build",
                str(source),
                "--out",
                str(out),
                "--invocation-key",
                key,
            ]
        )

        assert (exit_code, stdout) == (3, "")
        assert json.loads(stderr)["error"]["code"] == "argument_conflict"
        assert not invocation_path.exists()


def test_model_build_precommit_fault_leaves_no_visible_or_partial_set(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    descriptor = replace(
        model_command_module.MODEL_BUILD,
        handler=model_command_module.model_build_handler(
            publication_fault="after-member-write"
        ),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "f" * 64,
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not out.exists()
    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    assert not (store / "invocations").exists()
    assert not (store / "anchors").exists()


def test_model_build_explanation_generation_fault_publishes_nothing(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"

    def fail_explanation(*_args, **_kwargs):
        raise RuntimeError("injected Model explanation generation fault")

    monkeypatch.setattr(model_module, "_model_explanation", fail_explanation)

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "9" * 64,
        ]
    )

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not out.exists()
    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    assert not (store / "invocations").exists()
    assert not (store / "anchors").exists()


def test_model_build_explanation_schema_fault_publishes_nothing(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    explanation = model_module._model_explanation

    def generate_invalid_explanation(language_bundle, rir, debug_map):
        valid = explanation(language_bundle, rir, debug_map)
        return model_module._identified_artifact(
            language_bundle,
            "model-explanation",
            {
                "rir_identity": valid["rir_identity"],
                "debug_map_identity": valid["debug_map_identity"],
                "formula_explanations": valid["formula_explanations"],
            },
        )

    monkeypatch.setattr(
        model_module,
        "_model_explanation",
        generate_invalid_explanation,
    )

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not out.exists()
    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    assert not (store / "invocations").exists()
    assert not (store / "anchors").exists()


def test_model_build_postcommit_fault_is_recoverable_by_invocation_key(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "0" * 64,
    ]
    faulting = replace(
        model_command_module.MODEL_BUILD,
        handler=model_command_module.model_build_handler(
            publication_fault="after-commit"
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    artifact_dir = _invocation_directory(tmp_path, "0" * 64)
    assert (artifact_dir / "publication-index.json").is_file()
    assert not out.exists()

    recovered_exit, recovered_stdout, recovered_stderr = run_cli(
        argv, registry=(model_command_module.MODEL_BUILD,)
    )
    assert (recovered_exit, recovered_stderr) == (0, "")
    assert json.loads(recovered_stdout)["invocation_key"] == "0" * 64


def test_model_build_before_anchor_commit_fault_has_no_visible_anchor_and_recovers(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "8" * 64,
    ]
    faulting = replace(
        model_command_module.MODEL_BUILD,
        handler=model_command_module.model_build_handler(
            publication_fault="before-anchor-commit"
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    anchors = Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors"
    assert not anchors.exists() or not list(anchors.rglob("*.json"))
    assert not out.exists()

    recovered_exit, recovered_stdout, recovered_stderr = run_cli(argv)
    assert (recovered_exit, recovered_stderr) == (0, "")
    assert json.loads(recovered_stdout)["invocation_key"] == "8" * 64


def test_publication_anchor_is_authenticated_outside_the_writable_store(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "7" * 64,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    anchor_path = _anchor_path("7" * 64)
    anchor = json.loads(anchor_path.read_text())
    assert anchor["anchor_kind"] == "authenticated-publication-index-v1"
    assert anchor["algorithm"] == "hmac-sha256"
    expected = hmac.new(
        bytes.fromhex(os.environ["GDA_BALANCING_ANCHOR_KEY"]),
        canonical_bytes(anchor["publication_index"]),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(anchor["authentication"], expected)

    anchor["publication_index"]["receipt_identity"] = "sha256:" + "f" * 64
    anchor_path.unlink()
    anchor_path.write_bytes(canonical_bytes(anchor))
    anchor_path.chmod(0o444)
    out.unlink()

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


def test_publication_anchor_fsync_covers_read_only_mode(tmp_path, monkeypatch):
    path = tmp_path / "anchor.json"
    observed: list[tuple[str, int]] = []
    real_fchmod = os.fchmod
    real_fsync = os.fsync

    def record_fchmod(descriptor: int, mode: int) -> None:
        real_fchmod(descriptor, mode)
        observed.append(("fchmod", stat.S_IMODE(os.fstat(descriptor).st_mode)))

    def record_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISREG(mode):
            observed.append(("fsync", stat.S_IMODE(mode)))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fchmod", record_fchmod)
    monkeypatch.setattr(os, "fsync", record_fsync)

    model_module._write_anchor_exclusive(
        path,
        cast(
            dict[str, JsonValue],
            {"content_identity": "sha256:" + "1" * 64},
        ),
        bytes.fromhex(os.environ["GDA_BALANCING_ANCHOR_KEY"]),
    )

    assert observed == [("fchmod", 0o444), ("fsync", 0o444)]


def test_same_invocation_key_concurrent_writers_recover_one_committed_set(
    tmp_path, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    entered_anchor = threading.Event()
    release_anchor = threading.Event()
    second_started = threading.Event()
    real_write_anchor = model_module._write_anchor_exclusive
    calls = 0
    calls_guard = threading.Lock()

    def pause_first_anchor(path, artifact, authentication_key, **kwargs):
        nonlocal calls
        with calls_guard:
            calls += 1
            current = calls
        if current == 1:
            entered_anchor.set()
            assert release_anchor.wait(timeout=10)
        return real_write_anchor(path, artifact, authentication_key, **kwargs)

    monkeypatch.setattr(model_module, "_write_anchor_exclusive", pause_first_anchor)
    key = "6" * 64
    descriptor = descriptor_identity(model_command_module.MODEL_BUILD)

    def publish(out: Path, *, announce: bool = False):
        if announce:
            second_started.set()
        return model_module.publish_model_artifacts(
            checked,
            str(source),
            str(out),
            key,
            descriptor,
            model_command_module.MODEL_BUILD.artifact_set,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(publish, tmp_path / "first.json")
        assert entered_anchor.wait(timeout=10)
        second = executor.submit(
            publish,
            tmp_path / "second.json",
            announce=True,
        )
        assert second_started.wait(timeout=10)
        time.sleep(0.05)
        release_anchor.set()
        first_receipt = first.result(timeout=10)
        second_receipt = second.result(timeout=10)

    assert first_receipt == second_receipt
    assert (tmp_path / "first.json").is_file()
    assert (tmp_path / "second.json").is_file()
    assert _anchor_path(key).is_file()


def test_publication_index_anchor_rejects_a_coherently_reidentified_rewrite(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "9" * 64,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    anchor = _anchor_path("9" * 64)
    anchor_before = anchor.read_bytes()
    assert anchor.stat().st_mode & 0o222 == 0

    rir = json.loads((artifact_dir / "rir-semantic-payload.json").read_text())
    rir["declarations"][0]["domain"]["maximum"] = 99
    _reidentify(rir, "rir-semantic-payload-v2")
    resolved = json.loads((artifact_dir / "resolved-model.json").read_text())
    resolved["rir_identity"] = rir["content_identity"]
    _reidentify(resolved, "resolved-model-v2")
    debug_map = json.loads((artifact_dir / "debug-map.json").read_text())
    debug_map["rir_identity"] = rir["content_identity"]
    _reidentify(debug_map, "debug-map-v2")
    capability_manifest = json.loads(
        (artifact_dir / "capability-manifest.json").read_text()
    )
    capability_manifest["rir_identity"] = rir["content_identity"]
    capability_manifest["resolved_model_identity"] = resolved["content_identity"]
    _reidentify(capability_manifest, "capability-manifest-v2")
    build_receipt = json.loads((artifact_dir / "build-receipt.json").read_text())
    build_receipt["rir_identity"] = rir["content_identity"]
    build_receipt["resolved_model_identity"] = resolved["content_identity"]
    build_receipt["debug_map_identity"] = debug_map["content_identity"]
    build_receipt["capability_manifest_identity"] = capability_manifest[
        "content_identity"
    ]
    _reidentify(build_receipt, "build-receipt-v2")
    for name, artifact in (
        ("rir-semantic-payload", rir),
        ("resolved-model", resolved),
        ("debug-map", debug_map),
        ("capability-manifest", capability_manifest),
        ("build-receipt", build_receipt),
    ):
        (artifact_dir / f"{name}.json").write_bytes(canonical_bytes(artifact))

    manifest = json.loads((artifact_dir / "artifact-set-manifest.json").read_text())
    replacements = {
        "rir-semantic-payload": rir["content_identity"],
        "resolved-model": resolved["content_identity"],
        "debug-map": debug_map["content_identity"],
        "capability-manifest": capability_manifest["content_identity"],
        "build-receipt": build_receipt["content_identity"],
    }
    for member in manifest["members"]:
        if member["logical_name"] in replacements:
            member["content_identity"] = replacements[member["logical_name"]]
    _reidentify(manifest, "artifact-set-manifest-v2")
    (artifact_dir / "artifact-set-manifest.json").write_bytes(canonical_bytes(manifest))
    receipt = json.loads((artifact_dir / "artifact-set-receipt.json").read_text())
    receipt["manifest_identity"] = manifest["content_identity"]
    _reidentify(receipt, "artifact-set-receipt-v2")
    (artifact_dir / "artifact-set-receipt.json").write_bytes(canonical_bytes(receipt))
    index = json.loads((artifact_dir / "publication-index.json").read_text())
    index["receipt_identity"] = receipt["content_identity"]
    _reidentify(index, "publication-index-v2")
    (artifact_dir / "publication-index.json").write_bytes(canonical_bytes(index))
    forged_anchor = json.loads(anchor.read_text())
    forged_anchor["publication_index"] = index
    anchor.unlink()
    anchor.write_bytes(canonical_bytes(forged_anchor))
    anchor.chmod(0o444)
    out.unlink()
    assert anchor.read_bytes() != anchor_before

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


def test_receipt_content_identity_excludes_transport_locators():
    _, language_bundle = authority_module.load_authorities()
    common = {
        "descriptor_identity": "sha256:" + "1" * 64,
        "invocation_key": "2" * 64,
        "manifest_identity": "sha256:" + "3" * 64,
    }
    first = model_module._identified_artifact(
        language_bundle,
        "artifact-set-receipt",
        {
            **common,
            "manifest_locator": "/store-a/manifest.json",
            "member_locators": [
                {"logical_name": "resolved-model", "locator": "/store-a/member.json"}
            ],
        },
    )
    second = model_module._identified_artifact(
        language_bundle,
        "artifact-set-receipt",
        {
            **common,
            "manifest_locator": "/store-b/manifest.json",
            "member_locators": [
                {"logical_name": "resolved-model", "locator": "/store-b/member.json"}
            ],
        },
    )

    assert first["content_identity"] == second["content_identity"]


def test_recovery_rejects_a_symlinked_committed_member(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out_a = tmp_path / "published-a"
    out_b = tmp_path / "published-b"
    argv_a = [
        "model",
        "build",
        str(source),
        "--out",
        str(out_a),
        "--invocation-key",
        "6" * 64,
    ]
    argv_b = [
        "model",
        "build",
        str(source),
        "--out",
        str(out_b),
        "--invocation-key",
        "7" * 64,
    ]
    first_a = run_cli(argv_a)
    first_b = run_cli(argv_b)
    assert first_a[0] == 0
    assert first_b[0] == 0
    artifact_a = _artifact_directory(json.loads(first_a[1]))
    artifact_b = _artifact_directory(json.loads(first_b[1]))
    member = artifact_a / "package-lock.json"
    member.unlink()
    member.symlink_to(artifact_b / "package-lock.json")

    exit_code, stdout, stderr = run_cli(argv_a)

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"


def test_package_lock_closes_the_selected_semantic_graph_without_provenance(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"

    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "1" * 64,
        ]
    )
    assert built[0] == 0
    artifact_dir = _artifact_directory(json.loads(built[1]))

    lock = json.loads((artifact_dir / "package-lock.json").read_text())
    assert [(package["id"], package["version"]) for package in lock["packages"]] == [
        ("core.quantity", "2.1.0"),
        ("standard.compiler", "1.1.0"),
    ]
    assert all(
        set(package)
        == {
            "id",
            "version",
            "content_identity",
            "semantic_identity",
        }
        for package in lock["packages"]
    )
    assert lock["semantic_identity"].startswith("sha256:")
    assert lock["capability_bindings"]
    assert lock["types"]
    assert lock["components"]
    assert lock["conversions"]
    assert lock["operations"]
    assert lock["numeric_profiles"]
    assert lock["runtime_profiles"]
    assert "resolver" not in lock
    assert "compiler" not in lock

    resolution_receipt = json.loads(
        (artifact_dir / "resolution-receipt.json").read_text()
    )
    assert resolution_receipt["resolver"]
    assert resolution_receipt["kernel_identity"].startswith("sha256:")
    assert resolution_receipt["language_bundle_identity"].startswith("sha256:")
    assert resolution_receipt["diagnostics"] == []
    set_receipt = json.loads((artifact_dir / "artifact-set-receipt.json").read_text())
    assert {item["logical_name"] for item in set_receipt["member_locators"]} == {
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "model-explanation",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    }
    rir = json.loads((artifact_dir / "rir-semantic-payload.json").read_text())
    assert all(
        declaration["type_identity"]
        == {
            "package": "core.quantity",
            "version": "2.1.0",
            "symbol": "Quantity",
        }
        for declaration in rir["declarations"]
    )
    assert all(
        declaration["resolved_symbol"]["model"] == "example.quantity-model"
        and declaration["resolved_symbol"]["module"] == "main"
        for declaration in rir["declarations"]
    )


def test_equivalent_source_orderings_share_lock_rir_and_resolved_model_identity(
    tmp_path, run_cli
):
    source_a = _model_source()
    source_b = _model_source()
    _symbols(source_b).reverse()
    outputs = []
    for index, source in enumerate((source_a, source_b), start=2):
        source_path = tmp_path / f"source-{index}.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        out = tmp_path / f"published-{index}"
        built = run_cli(
            [
                "model",
                "build",
                str(source_path),
                "--out",
                str(out),
                "--invocation-key",
                str(index) * 64,
            ]
        )
        assert built[0] == 0
        outputs.append(_artifact_directory(json.loads(built[1])))

    for name in (
        "package-lock.json",
        "rir-semantic-payload.json",
        "resolved-model.json",
    ):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
    assert (outputs[0] / "debug-map.json").read_bytes() != (
        outputs[1] / "debug-map.json"
    ).read_bytes()
    rir = json.loads((outputs[0] / "rir-semantic-payload.json").read_text())
    assert "source_identity" not in rir
    assert "compiler" not in rir
    assert "debug_map_identity" not in rir


def _published_semantic_artifacts(out) -> dict[str, dict]:
    return {
        name: json.loads((out / f"{name}.json").read_text())
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    }


def _reidentify(artifact: dict, domain: str) -> None:
    excluded = (
        {"manifest_locator", "member_locators"}
        if domain == "artifact-set-receipt-v2"
        else set()
    )
    artifact["content_identity"] = content_identity(
        domain,
        {
            key: value
            for key, value in artifact.items()
            if key != "content_identity" and key not in excluded
        },
    )


def _package_vector_set(
    package_id: str,
    package_version: str,
    vectors: list[dict[str, Any]],
) -> dict[str, Any]:
    vector_set = {
        "artifact_kind": "package-conformance-vector-set",
        "package_id": package_id,
        "package_version": package_version,
        "vectors": [vector["id"] for vector in vectors],
        "vector_definitions": deepcopy(vectors),
    }
    _reidentify(vector_set, "package-conformance-vector-set-v2")
    return vector_set


def _reidentify_language_bundle(language_bundle: dict[str, Any]) -> None:
    assert isinstance(language_bundle, LanguageBundleIndex)
    kernel, _ = authority_module.load_authorities()
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]

    def path_values(root: Any, dotted: str) -> list[Any]:
        values = [root]
        for segment in dotted.split("."):
            selected: list[Any] = []
            for value in values:
                if not isinstance(value, dict) or segment not in value:
                    continue
                child = value[segment]
                selected.extend(child if isinstance(child, list) else [child])
            values = selected
        return values

    vector_sets_by_coordinate = {
        (vector_set["package_id"], vector_set["package_version"]): vector_set
        for vector_set in language_bundle.package_conformance_vector_sets
    }
    projected_vectors = {vector["id"]: vector for vector in language_bundle["vectors"]}
    for package in language_bundle["language"]["packages"]:
        for entry, projection in zip(
            package["semantic_closure"], projections, strict=True
        ):
            definitions = path_values(language_bundle, entry["authority_path"])
            owners = path_values(package, projection["owners_path"])
            key_member = projection["key_member"]
            entry["definitions"] = deepcopy(
                [
                    definition
                    for definition in definitions
                    if (
                        definition.get(key_member)
                        if key_member is not None and isinstance(definition, dict)
                        else definition
                    )
                    in owners
                ]
            )
        runtime_paths = set(package["runtime_semantic_paths"])
        package["semantic_identity"] = content_identity(
            "domain-package-semantic-closure-v2",
            cast(
                JsonValue,
                [
                    entry
                    for entry in package["semantic_closure"]
                    if entry["authority_path"] in runtime_paths
                ],
            ),
        )
        vector_set = vector_sets_by_coordinate[(package["id"], package["version"])]
        existing_vectors = {
            vector["id"]: vector for vector in vector_set["vector_definitions"]
        }
        vector_set["vector_definitions"] = [
            deepcopy(projected_vectors.get(vector_id, existing_vectors[vector_id]))
            for vector_id in vector_set["vectors"]
        ]
        _reidentify(vector_set, "package-conformance-vector-set-v2")
        package["conformance_vectors"] = {
            "artifact_kind": vector_set["artifact_kind"],
            "byte_size": len(canonical_bytes(cast(JsonValue, vector_set))),
            "content_identity": vector_set["content_identity"],
        }
        _reidentify(package, "domain-package-release-v2")
    graph_root = getattr(language_bundle, "root", None)
    if isinstance(graph_root, dict):
        members = sorted(
            zip(
                deepcopy(language_bundle["language"]["packages"]),
                deepcopy(language_bundle.package_conformance_vector_sets),
                strict=True,
            ),
            key=lambda member: (member[0]["id"], member[0]["version"]),
        )
        packages = [package for package, _vector_set in members]
        vector_sets = [vector_set for _package, vector_set in members]
        package_sizes = [
            len(canonical_bytes(cast(JsonValue, package))) for package in packages
        ]
        vector_set_sizes = [
            len(canonical_bytes(cast(JsonValue, vector_set)))
            for vector_set in vector_sets
        ]
        graph_root["resources"] = deepcopy(language_bundle["resources"])
        graph_root["package_descriptors"] = [
            {
                "artifact_kind": package["artifact_kind"],
                "byte_size": size,
                "content_identity": package["content_identity"],
                "id": package["id"],
                "version": package["version"],
            }
            for package, size in zip(packages, package_sizes, strict=True)
        ]
        _reidentify(graph_root, "language-definition-bundle-v2")
        language_bundle.root = deepcopy(graph_root)
        language_bundle.package_releases = packages
        language_bundle.package_conformance_vector_sets = vector_sets
        language_bundle.root_byte_size = len(
            canonical_bytes(cast(JsonValue, graph_root))
        )
        language_bundle.package_byte_sizes = tuple(package_sizes)
        language_bundle.vector_set_byte_sizes = tuple(vector_set_sizes)
        rebuilt = derive_language_index(
            graph_root,
            packages,
            vector_sets,
            kernel["admission"]["required_language_members"],
            root_byte_size=language_bundle.root_byte_size,
            package_byte_sizes=package_sizes,
            vector_set_byte_sizes=vector_set_sizes,
            descriptor_order=kernel["meta_format"]["language_bundle"][
                "package_descriptor"
            ]["canonical_order"],
        )
        language_bundle.root = deepcopy(rebuilt.root)
        language_bundle.package_releases = deepcopy(rebuilt.package_releases)
        language_bundle.package_conformance_vector_sets = deepcopy(
            rebuilt.package_conformance_vector_sets
        )
        language_bundle.root_byte_size = rebuilt.root_byte_size
        language_bundle.package_byte_sizes = rebuilt.package_byte_sizes
        language_bundle.vector_set_byte_sizes = rebuilt.vector_set_byte_sizes
        language_bundle.clear()
        language_bundle.update(dict(rebuilt))
        return
    _reidentify(language_bundle, "language-definition-bundle-v2")


def test_resolved_model_admission_rejects_coherently_reidentified_authority_drift(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "3" * 64,
        ]
    )
    assert built[0] == 0
    original = _published_semantic_artifacts(_artifact_directory(json.loads(built[1])))
    assert model_module.admit_resolved_model(original).admitted is True

    def mutate_operation(artifacts):
        artifacts["package-lock"]["operations"][0]["definition"]["id"] = (
            "quantity.reidentified"
        )

    def mutate_diagnostic(artifacts):
        artifacts["package-lock"]["diagnostics"][0] = "language.reidentified"

    def mutate_profile(artifacts):
        artifacts["package-lock"]["runtime_profiles"][0]["id"] = "compile.reidentified"

    def mutate_reason(artifacts):
        artifacts["package-lock"]["diagnostic_reasons"][0]["id"] = (
            "quantity.reason.reidentified"
        )

    for mutate in (
        mutate_operation,
        mutate_diagnostic,
        mutate_profile,
        mutate_reason,
    ):
        artifacts = deepcopy(original)
        mutate(artifacts)
        _reidentify(artifacts["package-lock"], "package-lock-v2")
        artifacts["resolved-model"]["package_lock_identity"] = artifacts[
            "package-lock"
        ]["content_identity"]
        artifacts["resolved-model"]["rir_identity"] = artifacts["rir-semantic-payload"][
            "content_identity"
        ]
        _reidentify(artifacts["resolved-model"], "resolved-model-v2")

        admission = model_module.admit_resolved_model(artifacts)

        assert admission.admitted is False
        assert admission.diagnostics == ("language.resolved_authority_mismatch",)


def test_resolved_model_admission_rejects_coherently_reidentified_invalid_declarations(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "4" * 64,
        ]
    )
    assert built[0] == 0
    original = _published_semantic_artifacts(_artifact_directory(json.loads(built[1])))

    for field, value in (
        ("symbol", "semantically-different"),
        ("role", "host-owned-role"),
        ("kind", "host-owned-kind"),
        ("unit", "host-owned-unit"),
        ("numeric_policy", "host-owned-policy"),
        ("representation", "HostInt"),
        ("domain", {"minimum": 2, "maximum": 1}),
    ):
        artifacts = deepcopy(original)
        artifacts["rir-semantic-payload"]["declarations"][0][field] = value
        _reidentify(artifacts["rir-semantic-payload"], "rir-semantic-payload-v2")
        artifacts["resolved-model"]["rir_identity"] = artifacts["rir-semantic-payload"][
            "content_identity"
        ]
        _reidentify(artifacts["resolved-model"], "resolved-model-v2")

        admission = model_module.admit_resolved_model(artifacts)

        assert admission.admitted is False
        assert admission.diagnostics == ("language.resolved_authority_mismatch",)


def test_resolved_model_admission_requires_the_kernel_boolean_conditional_contract(
    tmp_path, run_cli
):
    source_value = _model_source()
    quantity_contract = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    source_value["modules"][0]["formulas"] = [
        {
            "id": "choose-value",
            "parameters": [
                {"id": "condition", **quantity_contract},
                {"id": "when-false", **quantity_contract},
                {"id": "when-true", **quantity_contract},
            ],
            "result": quantity_contract,
            "body": {"node": "parameter", "parameter": "when-true"},
            "expression": "`when-true`",
        }
    ]
    source_value["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "choose-value"},
            "arguments": [
                {
                    "parameter": "condition",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "constant_value",
                    },
                },
                {
                    "parameter": "when-false",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                },
                {
                    "parameter": "when-true",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "parameter_value",
                    },
                },
            ],
        }
    ]
    _use_derived_value(source_value)
    source = tmp_path / "conditional-admission.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "published-model"),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert built[0] == 0, built
    artifacts = _published_semantic_artifacts(_artifact_directory(json.loads(built[1])))
    assert model_module.admit_resolved_model(artifacts).admitted is True

    kernel, language_bundle = authority_module.load_authorities()
    policy = model_module._formula_policy(language_bundle)
    actual_operand_domain = kernel["meta_format"]["runtime_program"][
        "invocation_contract"
    ]["identity_domains"]["actual_operand"]
    rir = artifacts["rir-semantic-payload"]
    formula = rir["formulas"][0]
    wrong_boolean_domain = {
        "type_identity": {
            "package": "kernel",
            "version": "2.0.0",
            "symbol": "Boolean",
        },
        "representation": "Bool",
        "kind": "boolean",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"kind": "closed-interval", "minimum": 0, "maximum": 1},
        "numeric_policy": "exact-bool",
    }
    condition_parameter = next(
        parameter
        for parameter in formula["parameters"]
        if parameter["id"] == "condition"
    )
    condition_parameter.update(wrong_boolean_domain)
    condition_declaration = next(
        declaration
        for declaration in rir["declarations"]
        if declaration["resolved_symbol"]["name"] == "constant_value"
    )
    condition_declaration.update(wrong_boolean_domain)
    operands = {
        name: {
            **(body := {"kind": "parameter", "parameter": name}),
            "identity": content_identity(actual_operand_domain, cast(JsonValue, body)),
        }
        for name in ("condition", "when-false", "when-true")
    }
    node_body = {
        "id": "choice",
        "node": "conditional",
        "condition": operands["condition"],
        "when_true": operands["when-true"],
        "when_false": operands["when-false"],
        "result": formula["result"],
    }
    node = {
        **node_body,
        "identity": content_identity(
            policy["identity_domains"]["expression_node"], node_body
        ),
    }
    result_body = {"kind": "local", "local": "choice"}
    formula["body"] = {
        "nodes": [node],
        "result": {
            **result_body,
            "identity": content_identity(
                actual_operand_domain, cast(JsonValue, result_body)
            ),
        },
    }
    formula["identity"] = content_identity(
        policy["identity_domains"]["declaration"],
        {key: value for key, value in formula.items() if key != "identity"},
    )
    for binding in rir["formula_bindings"]:
        binding["formula"]["identity"] = formula["identity"]
        binding["identity"] = content_identity(
            policy["identity_domains"]["binding"],
            {key: value for key, value in binding.items() if key != "identity"},
        )
    rir["initialization_programs"] = model_module._compile_initialization_programs(
        rir["selected_semantics"],
        rir["formulas"],
        rir["formula_bindings"],
        policy,
    )

    assert (
        model_module._formula_program_graph_is_admitted(
            kernel,
            language_bundle,
            rir["declarations"],
            rir["formulas"],
            rir["formula_bindings"],
            rir["entrypoints"],
            rir["selected_semantics"],
        )
        is False
    )

    _reidentify(rir, "rir-semantic-payload-v2")
    artifacts["resolved-model"]["rir_identity"] = rir["content_identity"]
    _reidentify(artifacts["resolved-model"], "resolved-model-v2")

    admission = model_module.admit_resolved_model(artifacts)

    assert admission.admitted is False
    assert admission.diagnostics == ("language.resolved_authority_mismatch",)


def test_resolved_model_admission_recomputes_entrypoint_binding_identities(
    tmp_path, run_cli
):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
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
                        "module": "main",
                        "symbol": "parameter_value",
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source = tmp_path / "entrypoint-model-source.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "published-model"),
            "--invocation-key",
            "5" * 64,
        ]
    )
    assert built[0] == 0, built
    artifacts = _published_semantic_artifacts(_artifact_directory(json.loads(built[1])))
    assert model_module.admit_resolved_model(artifacts).admitted is True

    operand = artifacts["rir-semantic-payload"]["entrypoints"][0]["arguments"][0][
        "operand"
    ]
    operand["identity"] = "sha256:" + ("0" * 64)
    _reidentify(artifacts["rir-semantic-payload"], "rir-semantic-payload-v2")
    artifacts["resolved-model"]["rir_identity"] = artifacts["rir-semantic-payload"][
        "content_identity"
    ]
    _reidentify(artifacts["resolved-model"], "resolved-model-v2")

    admission = model_module.admit_resolved_model(artifacts)

    assert admission.admitted is False
    assert admission.diagnostics == ("language.resolved_authority_mismatch",)


@pytest.mark.parametrize(
    "mutation",
    ("missing", "extra", "duplicate", "unknown"),
)
def test_model_entrypoint_arguments_must_exactly_close_formal_ports(
    tmp_path, run_cli, mutation
):
    source_value = _model_source()
    arguments = [
        {
            "port": "value",
            "operand": {
                "kind": "symbol",
                "module": "main",
                "symbol": "parameter_value",
            },
        }
    ]
    if mutation == "missing":
        arguments.clear()
    elif mutation == "extra":
        arguments.append(
            {
                "port": "extra",
                "operand": {"kind": "literal", "value": 1},
            }
        )
    elif mutation == "duplicate":
        arguments.append(deepcopy(arguments[0]))
    else:
        arguments[0]["port"] = "unknown"
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
            "operation": {
                "package": "core.quantity",
                "version": "2.1.0",
                "id": "quantity.identity",
            },
            "arguments": arguments,
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source = tmp_path / f"{mutation}-entrypoint.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    expected_pointer = (
        "/entrypoints/0/arguments"
        if mutation == "missing"
        else "/entrypoints/0/arguments/1/port"
        if mutation in {"extra", "duplicate"}
        else "/entrypoints/0/arguments/0/port"
    )
    assert error["diagnostics"][0]["primary"]["pointer"] == expected_pointer


@pytest.mark.parametrize("role", ("derived", "output", "random"))
def test_model_entrypoint_read_port_rejects_symbols_without_an_input_source(
    tmp_path,
    run_cli,
    role,
):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
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
                        "module": "main",
                        "symbol": f"{role}_value",
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source = tmp_path / f"{role}-operand.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/formula_bindings"
        if role == "derived"
        else "/entrypoints/0/arguments/0/operand"
    )


def test_model_entrypoint_result_reports_the_exact_binding_pointer(tmp_path, run_cli):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
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
                        "module": "main",
                        "symbol": "parameter_value",
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "parameter_value",
            },
        }
    ]
    source = tmp_path / "invalid-entrypoint-result.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == "/entrypoints/0/result"


@pytest.mark.parametrize(
    ("member", "incompatible"),
    (
        (
            "type",
            {"package": "kernel", "version": "2.0.0", "id": "Boolean"},
        ),
        ("representation", "Bool"),
        ("kind", "boolean"),
        ("unit", "incompatible-unit"),
        ("numeric_policy", "exact-bool"),
    ),
)
def test_model_entrypoint_rejects_every_incompatible_formal_value_axis(
    member,
    incompatible,
):
    source = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    selected = deepcopy(cast(dict[str, Any], rir["selected_semantics"]))
    cast_operation = next(
        row["definition"]
        for row in selected["operations"]
        if row["definition"]["id"] == "game.combat.cast-v1"
    )
    accuracy = next(
        port for port in cast_operation["inputs"] if port["id"] == "accuracy"
    )
    accuracy[member] = incompatible

    with pytest.raises(ValueError, match="incompatible"):
        model_module._resolved_entrypoints(
            checked,
            cast(list[dict[str, Any]], rir["declarations"]),
            selected,
        )


def test_model_entrypoint_lowers_an_ldb_typed_integer_literal(tmp_path):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
            "operation": {
                "package": "core.quantity",
                "version": "2.1.0",
                "id": "quantity.identity",
            },
            "arguments": [
                {
                    "port": "value",
                    "operand": {"kind": "literal", "value": 7},
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source = tmp_path / "typed-literal.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    checked = model_module.check_model_source(str(source))

    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    entrypoint = cast(list[dict[str, Any]], rir["entrypoints"])[0]
    operand = cast(dict[str, Any], entrypoint["arguments"][0]["operand"])
    assert operand["value"] == 7
    assert operand["context_type"] == {
        "id": "quantity.dimensionless-int64",
        "type": {
            "package": "core.quantity",
            "version": "2.1.0",
            "id": "Quantity",
        },
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain": {"kind": "actual"},
        "numeric_policy": "exact-int64",
    }


def test_resolved_model_admission_rejects_reidentified_literal_context_tamper(
    tmp_path,
):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
            "operation": {
                "package": "core.quantity",
                "version": "2.1.0",
                "id": "quantity.identity",
            },
            "arguments": [
                {
                    "port": "value",
                    "operand": {"kind": "literal", "value": 7},
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source = tmp_path / "typed-literal-admission.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    artifacts: dict[str, Any] = {
        name: deepcopy(original[name])
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    }
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    entrypoint = cast(dict[str, Any], rir["entrypoints"][0])
    argument = cast(dict[str, Any], entrypoint["arguments"][0])
    operand = cast(dict[str, Any], argument["operand"])
    operand["context_type"]["id"] = "forged.literal-profile"
    _reidentify(rir, "rir-semantic-payload-v2")
    resolved_model = cast(dict[str, Any], artifacts["resolved-model"])
    resolved_model["rir_identity"] = rir["content_identity"]
    _reidentify(resolved_model, "resolved-model-v2")

    admission = model_module.admit_resolved_model(artifacts)

    assert admission.admitted is False
    assert admission.diagnostics == ("language.resolved_authority_mismatch",)


def test_literal_profile_reidentity_changes_rir_semantics(tmp_path, monkeypatch):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
            "operation": {
                "package": "core.quantity",
                "version": "2.1.0",
                "id": "quantity.identity",
            },
            "arguments": [
                {
                    "port": "value",
                    "operand": {"kind": "literal", "value": 7},
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source = tmp_path / "literal-profile-reidentity.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    original_checked = model_module.check_model_source(str(source))
    assert isinstance(original_checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(original_checked)

    kernel, candidate_ldb = deepcopy(authority_module.load_authorities())
    profile = candidate_ldb["language"]["literal_typing_profiles"][0]
    old_id = profile["id"]
    profile["id"] = "quantity.dimensionless-int64-reidentified"
    owner = next(
        package
        for package in candidate_ldb["language"]["packages"]
        if package["id"] == "core.quantity"
    )
    owner["exports"]["literal_typing_profiles"] = [profile["id"]]
    assert old_id != profile["id"]
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    changed_checked = model_module.check_model_source(str(source))
    assert isinstance(changed_checked, model_module.CheckedModel)
    changed = model_module.lower_checked_model(changed_checked)
    changed_rir = cast(dict[str, Any], changed["rir-semantic-payload"])
    changed_entrypoint = cast(dict[str, Any], changed_rir["entrypoints"][0])
    changed_argument = cast(dict[str, Any], changed_entrypoint["arguments"][0])
    changed_operand = cast(dict[str, Any], changed_argument["operand"])

    changed_context_type = cast(dict[str, Any], changed_operand["context_type"])
    assert changed_context_type["id"] == profile["id"]
    assert (
        changed_rir["content_identity"]
        != original["rir-semantic-payload"]["content_identity"]
    )


def test_model_entrypoint_refuses_integer_literal_for_boolean_formal(
    tmp_path,
    run_cli,
):
    source_path = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    source_value = json.loads(source_path.read_text(encoding="utf-8"))
    source_value["formula_bindings"] = [
        binding
        for binding in source_value["formula_bindings"]
        if binding["site"]["kind"] == "operation-slot"
    ]
    source_value["entrypoints"] = [
        {
            "id": "combat.damage",
            "operation": {
                "package": "game.combat",
                "version": "2.0.0",
                "id": "game.combat.damage-v1",
            },
            "arguments": [
                {
                    "port": "base_damage",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "base_damage",
                    },
                },
                {
                    "port": "critical",
                    "operand": {"kind": "literal", "value": 1},
                },
                {
                    "port": "mitigation",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "target_defense",
                    },
                },
                {
                    "port": "target_health",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "target_health",
                    },
                },
            ],
            "result": {
                "kind": "symbol",
                "module": "combat",
                "symbol": "damage_dealt",
            },
        }
    ]
    source = tmp_path / "literal-for-boolean.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/entrypoints/0/arguments/1/operand"
    )


@pytest.mark.parametrize(
    ("member", "value"),
    (
        ("package", "missing.package"),
        ("version", "9.0.0"),
        ("id", "quantity.missing"),
    ),
)
def test_model_entrypoint_refuses_stale_exact_operation_coordinates(
    tmp_path,
    run_cli,
    member,
    value,
):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
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
                        "module": "main",
                        "symbol": "parameter_value",
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    source_value["entrypoints"][0]["operation"][member] = value
    source = tmp_path / f"stale-operation-{member}.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        f"/entrypoints/0/operation/{member}"
    )


def test_symbol_rename_and_binding_change_reidentify_the_resolved_graph(tmp_path):
    def lower(source_value: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
        source = tmp_path / f"{name}.json"
        source.write_text(json.dumps(source_value), encoding="utf-8")
        checked = model_module.check_model_source(str(source))
        assert isinstance(checked, model_module.CheckedModel)
        return cast(
            dict[str, dict[str, Any]], model_module.lower_checked_model(checked)
        )

    baseline = _model_source()
    baseline["entrypoints"] = [
        {
            "id": "quantity.identity",
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
                        "module": "main",
                        "symbol": "parameter_value",
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    renamed = deepcopy(baseline)
    parameter = next(
        row
        for row in renamed["modules"][0]["symbols"]
        if row["symbol"] == "parameter_value"
    )
    parameter["symbol"] = "renamed_parameter"
    renamed["entrypoints"][0]["arguments"][0]["operand"]["symbol"] = "renamed_parameter"
    rebound = deepcopy(baseline)
    rebound["entrypoints"][0]["arguments"][0]["operand"]["symbol"] = "input_value"

    artifacts = {
        name: lower(value, name)
        for name, value in (
            ("baseline", baseline),
            ("renamed", renamed),
            ("rebound", rebound),
        )
    }
    entrypoints = {
        name: value["rir-semantic-payload"]["entrypoints"][0]
        for name, value in artifacts.items()
    }
    assert (
        len(
            {
                entrypoint["arguments"][0]["port"]["identity"]
                for entrypoint in entrypoints.values()
            }
        )
        == 1
    )
    assert (
        len(
            {
                entrypoint["arguments"][0]["operand"]["identity"]
                for entrypoint in entrypoints.values()
            }
        )
        == 3
    )
    assert (
        len(
            {
                value["rir-semantic-payload"]["content_identity"]
                for value in artifacts.values()
            }
        )
        == 3
    )
    assert (
        len(
            {
                value["resolved-model"]["content_identity"]
                for value in artifacts.values()
            }
        )
        == 3
    )


def test_one_operation_can_resolve_at_multiple_sites_with_distinct_bindings():
    source = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    selected = deepcopy(cast(dict[str, Any], rir["selected_semantics"]))
    cast_operation = next(
        row["definition"]
        for row in selected["operations"]
        if row["definition"]["id"] == "game.combat.cast-v1"
    )
    hit_call = next(
        row for row in cast_operation["body"] if row.get("site") == "hit-check"
    )
    second_hit_call = deepcopy(hit_call)
    second_hit_call["site"] = "mitigation-hit-check"
    defense_binding = next(
        row for row in second_hit_call["arguments"] if row["port"] == "defense"
    )
    defense_binding["operand"]["port"] = "damage_mitigation"
    cast_operation["body"].insert(
        cast_operation["body"].index(hit_call) + 1,
        second_hit_call,
    )

    call_sites = cast(
        list[dict[str, Any]],
        model_module._resolved_call_sites(
            checked.kernel,
            selected,
            checked.language_bundle["language"]["model_lowerings"][0][
                "composition_policy"
            ],
        ),
    )
    hit_sites = [
        row for row in call_sites if row["operation"]["id"] == "game.check.hit-v1"
    ]

    assert [row["site"] for row in hit_sites] == [
        "hit-check",
        "mitigation-hit-check",
    ]
    assert len({cast(str, row["identity"]) for row in hit_sites}) == 2
    assert (
        len(
            {
                next(
                    cast(str, argument["operand"]["identity"])
                    for argument in row["arguments"]
                    if argument["port"]["name"] == "defense"
                )
                for row in hit_sites
            }
        )
        == 2
    )


@pytest.mark.parametrize(
    ("member", "hidden_value"),
    (
        ("effects", "hidden.child-effect"),
        ("refusals", "hidden.child-refusal"),
    ),
)
def test_nested_call_rejects_undeclared_child_closure_widening(
    member,
    hidden_value,
):
    source = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    selected = deepcopy(cast(dict[str, Any], rir["selected_semantics"]))
    child = next(
        row["definition"]
        for row in selected["operations"]
        if row["definition"]["id"] == "game.check.hit-v1"
    )
    child[member].append(hidden_value)

    with pytest.raises(ValueError, match="closure exceeds caller declaration"):
        model_module._resolved_call_sites(
            checked.kernel,
            selected,
            checked.language_bundle["language"]["model_lowerings"][0][
                "composition_policy"
            ],
        )


def test_authority_admission_rejects_an_orphan_assignment_mode():
    baseline = model_module.check_model_source_value(_model_source())
    assert isinstance(baseline, model_module.CheckedModel)
    candidate_ldb = deepcopy(baseline.language_bundle)
    assignment_policy = candidate_ldb["language"]["model_lowerings"][0][
        "assignment_policy"
    ]
    parameter = next(
        row for row in assignment_policy["roles"] if row["role"] == "parameter"
    )
    parameter["modes"].append(
        {
            "id": "orphan-source",
            "initialization_source": "execution",
            "value_member": "forbidden",
            "experiment_cardinality": "forbidden",
            "override": False,
        }
    )
    mode_schema = candidate_ldb["language"]["wire_schemas"][0]["schema"]["properties"][
        "modules"
    ]["items"]["properties"]["symbols"]["items"]["properties"]["value_policy"][
        "properties"
    ]["mode"]
    mode_schema["enum"].append("orphan-source")
    _reidentify_language_bundle(candidate_ldb)

    admission = admit_authorities(baseline.kernel, candidate_ldb)

    assert admission.admitted is False
    assert any(
        diagnostic.subject == "language.definitions.assignment-policy"
        for diagnostic in admission.diagnostics
    )


@pytest.mark.parametrize(
    "initialization_source",
    ("named-random-stream", "resolved-model"),
)
def test_assignment_policy_refuses_a_readable_role_mode_without_a_value_producer(
    initialization_source,
):
    baseline = model_module.check_model_source_value(_model_source())
    assert isinstance(baseline, model_module.CheckedModel)
    candidate_ldb = deepcopy(baseline.language_bundle)
    lowering = candidate_ldb["language"]["model_lowerings"][0]
    parameter = next(
        row
        for row in lowering["assignment_policy"]["roles"]
        if row["role"] == "parameter"
    )
    mode = next(row for row in parameter["modes"] if row["id"] == "experiment-required")
    mode.update(
        {
            "initialization_source": initialization_source,
            "value_member": "forbidden",
            "experiment_cardinality": "forbidden",
            "override": False,
        }
    )
    _reidentify_language_bundle(candidate_ldb)

    admission = admit_authorities(baseline.kernel, candidate_ldb)

    assert admission.admitted is False
    assert any(
        diagnostic.subject == "language.definitions.assignment-policy"
        for diagnostic in admission.diagnostics
    )
    with pytest.raises(ValueError, match="total Symbol assignment policy"):
        model_module._assignment_policy(
            lowering,
            expected_roles=set(candidate_ldb["language"]["quantity"]["symbol_roles"]),
        )


@pytest.mark.parametrize(
    ("mutation", "expected_subject"),
    (
        (
            "effect",
            (
                "language.operations.game.combat@2.0.0."
                "game.combat.cast-v1.body.hit-check.effects"
            ),
        ),
        (
            "refusal",
            (
                "language.operations.game.combat@2.0.0."
                "game.combat.cast-v1.body.hit-check.refusals"
            ),
        ),
        (
            "resource",
            (
                "language.operations.game.combat@2.0.0."
                "game.combat.cast-v1.resource_bounds"
            ),
        ),
        (
            "cycle",
            (
                "language.operations.game.check@1.0.1."
                "game.check.hit-v1.body.cycle.operation"
            ),
        ),
        (
            "argument-contract",
            (
                "language.operations.game.combat@2.0.0."
                "game.combat.cast-v1.body.hit-check.arguments"
            ),
        ),
    ),
)
def test_package_admission_closes_every_operation_composition_axis(
    mutation,
    expected_subject,
):
    baseline = model_module.check_model_source_value(
        json.loads(
            (
                Path(__file__).parents[1]
                / "examples/schema2/rpg-combat-cast/model-source.json"
            ).read_text(encoding="utf-8")
        )
    )
    assert isinstance(baseline, model_module.CheckedModel)
    candidate_ldb = deepcopy(baseline.language_bundle)

    def owned_operation(operation_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        projected = next(
            operation
            for operation in candidate_ldb["language"]["operations"]
            if operation["id"] == operation_id
        )
        package = next(
            package
            for package in candidate_ldb["language"]["packages"]
            if operation_id in package["exports"]["operations"]
        )
        closure = next(
            entry["definitions"]
            for entry in package["semantic_closure"]
            if entry["authority_path"] == "language.operations"
        )
        owned = next(
            operation for operation in closure if operation["id"] == operation_id
        )
        return projected, owned

    hit_operations = owned_operation("game.check.hit-v1")
    cast_operations = owned_operation("game.combat.cast-v1")
    if mutation == "effect":
        for operation in hit_operations:
            operation["effects"].append("hidden.child-effect")
    elif mutation == "refusal":
        for operation in hit_operations:
            operation["refusals"].append("hidden.child-refusal")
    elif mutation == "resource":
        for operation in cast_operations:
            operation["resource_bounds"]["max_steps"] = 1
    elif mutation == "argument-contract":
        for operation in hit_operations:
            defense = next(
                port for port in operation["inputs"] if port["id"] == "defense"
            )
            defense["numeric_policy"] = "exact-bool"
    else:
        recursive_body = [
            {
                "node": "invoke",
                "site": "self",
                "operation": {
                    "package": "game.check",
                    "version": "1.0.1",
                    "id": "game.check.hit-v1",
                },
                "arguments": [
                    {
                        "port": "accuracy",
                        "operand": {"kind": "port", "port": "accuracy"},
                    },
                    {
                        "port": "defense",
                        "operand": {"kind": "port", "port": "defense"},
                    },
                ],
                "result": {"kind": "discard"},
                "outcomes": [
                    {
                        "outcome": "hit",
                        "action": {"kind": "continue"},
                    },
                    {
                        "outcome": "miss",
                        "action": {"kind": "continue"},
                    },
                ],
            }
        ]
        for operation in hit_operations:
            operation["body"] = deepcopy(recursive_body)
    _reidentify_language_bundle(candidate_ldb)

    composition_subjects = bootstrap_module._operation_composition_diagnostic_subjects(
        baseline.kernel, candidate_ldb
    )
    admission = admit_authorities(baseline.kernel, candidate_ldb)

    assert expected_subject in composition_subjects
    assert admission.admitted is False


def test_authority_admission_rejects_operation_closure_at_the_package_site():
    baseline = model_module.check_model_source_value(
        json.loads(
            (
                Path(__file__).parents[1]
                / "examples/schema2/rpg-combat-cast/model-source.json"
            ).read_text(encoding="utf-8")
        )
    )
    assert isinstance(baseline, model_module.CheckedModel)
    candidate_ldb = deepcopy(baseline.language_bundle)
    child = next(
        operation
        for operation in candidate_ldb["language"]["operations"]
        if operation["id"] == "game.check.hit-v1"
    )
    child["effects"].append("hidden.child-effect")
    _reidentify_language_bundle(candidate_ldb)

    admission = admit_authorities(baseline.kernel, candidate_ldb)

    assert admission.admitted is False
    assert any(
        diagnostic.subject
        == "language.operations.game.combat@2.0.0.game.combat.cast-v1.body.hit-check.effects"
        for diagnostic in admission.diagnostics
    )


def test_ordered_writable_alias_is_declared_by_the_selected_operation_contract():
    source_value = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )
    baseline = model_module.check_model_source_value(source_value)
    assert isinstance(baseline, model_module.CheckedModel)
    candidate_ldb = deepcopy(baseline.language_bundle)
    assert all(
        operation["alias_policy"]["read_only"] == "share"
        and isinstance(operation["alias_policy"]["writable_groups"], list)
        for operation in candidate_ldb["language"]["operations"]
    )
    damage = next(
        operation
        for operation in candidate_ldb["language"]["operations"]
        if operation["id"] == "game.combat.damage-v1"
    )
    damage["alias_policy"]["writable_groups"] = [
        {
            "ports": ["mitigation", "target_health"],
            "semantics": "operation-body-order",
        }
    ]
    cast_operation = next(
        operation
        for operation in candidate_ldb["language"]["operations"]
        if operation["id"] == "game.combat.cast-v1"
    )
    damage_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "apply-damage"
    )
    mitigation = next(
        argument
        for argument in damage_call["arguments"]
        if argument["port"] == "mitigation"
    )
    mitigation["operand"]["port"] = "target_health"
    _reidentify_language_bundle(candidate_ldb)
    admission = admit_authorities(baseline.kernel, candidate_ldb)
    assert admission.admitted is True

    checked = model_module.check_model_source_value(
        source_value,
        kernel=baseline.kernel,
        language_bundle=candidate_ldb,
        authority_admission=admission,
    )

    assert isinstance(checked, model_module.CheckedModel)
    rir = model_module.lower_checked_model(checked)["rir-semantic-payload"]
    alias = next(
        alias
        for call_site in cast(list[dict[str, Any]], rir["call_sites"])
        if call_site["site"] == "apply-damage"
        for alias in call_site["aliases"]
    )
    assert alias["ports"] == ["mitigation", "target_health"]
    assert alias["policy"] == "operation-body-order"


def test_model_entrypoint_can_explicitly_discard_a_discardable_result(tmp_path):
    example = (
        Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
    )
    source_value = json.loads(example.read_text(encoding="utf-8"))
    source_value["formula_bindings"] = []
    source_value["entrypoints"] = [
        {
            "id": "resource.spend",
            "operation": {
                "package": "game.resource",
                "version": "1.0.1",
                "id": "game.resource.spend-v1",
            },
            "arguments": [
                {
                    "port": "resource",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "actor_mana",
                    },
                },
                {
                    "port": "cost",
                    "operand": {
                        "kind": "symbol",
                        "module": "combat",
                        "symbol": "action_cost",
                    },
                },
            ],
            "result": {"kind": "discard"},
        }
    ]
    source = tmp_path / "discardable-entrypoint.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")

    checked = model_module.check_model_source(str(source))

    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    entrypoints = cast(list[dict[str, Any]], rir["entrypoints"])
    assert entrypoints[0]["result"]["kind"] == "discard"


def test_lowerer_executes_the_admitted_ldb_rule_instead_of_copying_source_fields(
    tmp_path,
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    candidate_ldb = deepcopy(checked.language_bundle)
    rule = next(
        item
        for item in candidate_ldb["language"]["rules"]
        if item["id"] == "quantity.lower"
    )
    rule["conclusion"]["fields"]["role"] = {
        "tag": "literal",
        "value": "lowered-by-ldb",
    }
    vector = next(
        item
        for item in candidate_ldb["vectors"]
        if item["id"] == "quantity.lower.valid"
    )
    vector["expect"]["fields"]["role"] = "lowered-by-ldb"
    candidate_ldb["language"]["quantity"]["symbol_roles"].append("lowered-by-ldb")
    candidate_ldb["language"]["packages"][0]["exports"]["symbol_roles"].append(
        "lowered-by-ldb"
    )
    candidate_ldb["language"]["wire_schemas"][0]["schema"]["properties"]["modules"][
        "items"
    ]["properties"]["symbols"]["items"]["properties"]["role"]["enum"].append(
        "lowered-by-ldb"
    )
    lowering = candidate_ldb["language"]["model_lowerings"][0]
    modes_by_id = {
        mode["id"]: deepcopy(mode)
        for row in lowering["assignment_policy"]["roles"]
        for mode in row["modes"]
    }
    lowering["assignment_policy"]["roles"].append(
        {
            "role": "lowered-by-ldb",
            "modes": [modes_by_id[mode] for mode in sorted(modes_by_id)],
            "entrypoint_operand_access": [],
            "entrypoint_result": False,
            "binding_kind": "internal",
        }
    )
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = model_module.CheckedModel(
        source=checked.source,
        source_identity=checked.source_identity,
        kernel=checked.kernel,
        language_bundle=candidate_ldb,
    )

    artifacts = model_module.lower_checked_model(candidate)

    declarations = cast(
        list[dict[str, Any]], artifacts["rir-semantic-payload"]["declarations"]
    )
    assert {item["role"] for item in declarations} == {"lowered-by-ldb"}


@pytest.mark.parametrize(
    ("old_mode", "authority_mode", "operand_symbol", "expected_contract_member"),
    (
        ("model-fixed", "authority-model-value", "constant_value", "initializers"),
        (
            "experiment-required",
            "authority-scenario-required",
            "parameter_value",
            "targets",
        ),
    ),
)
def test_symbol_assignment_semantics_follow_the_admitted_per_role_mode_contracts(
    old_mode,
    authority_mode,
    operand_symbol,
    expected_contract_member,
):
    source_value = _model_source()
    source_value["entrypoints"] = [
        {
            "id": "quantity.identity",
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
                        "module": "main",
                        "symbol": operand_symbol,
                    },
                }
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "output_value",
            },
        }
    ]
    baseline = model_module.check_model_source_value(source_value)
    assert isinstance(baseline, model_module.CheckedModel)
    candidate_ldb = deepcopy(baseline.language_bundle)
    lowering = candidate_ldb["language"]["model_lowerings"][0]
    assignment_policy = lowering["assignment_policy"]
    for row in assignment_policy["roles"]:
        row["modes"] = [
            {**mode, "id": authority_mode} if mode["id"] == old_mode else mode
            for mode in row["modes"]
        ]
    source_schema = candidate_ldb["language"]["wire_schemas"][0]["schema"]
    mode_schema = source_schema["properties"]["modules"]["items"]["properties"][
        "symbols"
    ]["items"]["properties"]["value_policy"]["properties"]["mode"]
    mode_schema["enum"] = [
        authority_mode if mode == old_mode else mode for mode in mode_schema["enum"]
    ]
    for symbol in _symbols(source_value):
        if symbol["value_policy"]["mode"] == old_mode:
            symbol["value_policy"]["mode"] = authority_mode
    _reidentify_language_bundle(candidate_ldb)
    authority_admission = admit_authorities(baseline.kernel, candidate_ldb)
    assert authority_admission.admitted is True

    checked = model_module.check_model_source_value(
        source_value,
        kernel=baseline.kernel,
        language_bundle=candidate_ldb,
        authority_admission=authority_admission,
    )

    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    entrypoints = cast(list[dict[str, Any]], rir["entrypoints"])
    contract = cast(dict[str, Any], entrypoints[0]["scenario_input_contract"])
    rows = cast(list[dict[str, Any]], contract[expected_contract_member])
    assert len(rows) == 1
    assert rows[0]["target"]["name"] == operand_symbol


def test_rir_identity_binds_the_reachable_selected_runtime_semantics(tmp_path):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    candidate_ldb["language"]["quantity"]["units"][0]["dimension"] = (
        "reidentified-dimension"
    )
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = replace(checked, language_bundle=candidate_ldb)

    mutated = model_module.lower_checked_model(candidate)

    original_lock = original["package-lock"]
    mutated_lock = mutated["package-lock"]
    original_rir = original["rir-semantic-payload"]
    mutated_rir = mutated["rir-semantic-payload"]
    original_selected = cast(dict[str, Any], original_rir["selected_semantics"])
    mutated_selected = cast(dict[str, Any], mutated_rir["selected_semantics"])
    assert original_selected != original_lock["selected_semantics"]
    assert mutated_selected != mutated_lock["selected_semantics"]
    assert [row["definition"]["id"] for row in original_selected["operations"]] == [
        "quantity.floor-zero",
        "quantity.identity",
        "quantity.less-than",
        "quantity.maximum",
        "quantity.subtract",
    ]
    assert original_selected["conversions"] == []
    original_closures = cast(
        list[dict[str, Any]], original_selected["package_semantic_closures"]
    )
    mutated_closures = cast(
        list[dict[str, Any]], mutated_selected["package_semantic_closures"]
    )
    original_units = next(
        entry["definitions"]
        for entry in cast(list[dict[str, Any]], original_closures[0]["definitions"])
        if entry["authority_path"] == "language.quantity.units"
    )
    mutated_units = next(
        entry["definitions"]
        for entry in cast(list[dict[str, Any]], mutated_closures[0]["definitions"])
        if entry["authority_path"] == "language.quantity.units"
    )
    assert original_units[0]["dimension"] == "dimensionless"
    assert mutated_units[0]["dimension"] == "reidentified-dimension"
    assert original_lock["content_identity"] != mutated_lock["content_identity"]
    assert original_rir["content_identity"] != mutated_rir["content_identity"]
    assert "package_lock_semantic_identity" not in original_rir
    assert "semantic_identity" not in original_closures[0]


def _rewrite_formula_expressions(value: Any, old: str, new: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "expression" and isinstance(child, str):
                value[key] = child.replace(old, new)
            else:
                _rewrite_formula_expressions(child, old, new)
    elif isinstance(value, list):
        for child in value:
            _rewrite_formula_expressions(child, old, new)


def _rpg_source_value() -> dict[str, Any]:
    return json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text(encoding="utf-8")
    )


def _check_with_candidate_ldb(
    source: dict[str, Any],
    kernel: dict[str, Any],
    language_bundle: LanguageBundleIndex,
) -> model_module.CheckedModel:
    admission = admit_authorities(kernel, language_bundle)
    assert admission.admitted is True, admission
    checked = model_module.check_model_source_value(
        source,
        kernel=kernel,
        language_bundle=language_bundle,
        authority_admission=admission,
    )
    assert isinstance(checked, model_module.CheckedModel), checked
    return checked


def _mutate_operation_notation(
    language_bundle: LanguageBundleIndex,
    operation_id: str,
    member: str,
    value: Any,
) -> None:
    operation = next(
        row
        for row in language_bundle["language"]["operations"]
        if row["id"] == operation_id
    )
    operation["extensions"]["standard.formula-notation"][member] = value
    vector = next(
        row
        for row in language_bundle["vectors"]
        if row["id"] == f"formula.notation.{operation_id}"
    )
    vector["expect"] = deepcopy(operation["extensions"])


def _locked_package_ids(lowered: dict[str, Any]) -> set[str]:
    lock = cast(dict[str, Any], lowered["package-lock"])
    packages = cast(list[dict[str, Any]], lock["packages"])
    return {cast(str, row["id"]) for row in packages}


def test_selected_notation_mutation_reidentifies_content_not_rir_semantics():
    source = _rpg_source_value()
    baseline = model_module.check_model_source_value(source)
    assert isinstance(baseline, model_module.CheckedModel)
    original = model_module.lower_checked_model(baseline)
    candidate_ldb = cast(
        LanguageBundleIndex, deepcopy(baseline.language_bundle)
    )
    _mutate_operation_notation(
        candidate_ldb,
        "quantity.subtract",
        "token",
        "−",
    )
    _rewrite_formula_expressions(candidate_ldb["vectors"], " - ", " − ")
    _rewrite_formula_expressions(source, " - ", " − ")
    _reidentify_language_bundle(candidate_ldb)
    candidate = _check_with_candidate_ldb(source, baseline.kernel, candidate_ldb)
    mutated = model_module.lower_checked_model(candidate)

    original_core = next(
        row
        for row in baseline.language_bundle["language"]["packages"]
        if row["id"] == "core.quantity"
    )
    mutated_core = next(
        row
        for row in candidate_ldb["language"]["packages"]
        if row["id"] == "core.quantity"
    )
    assert original_core["content_identity"] != mutated_core["content_identity"]
    baseline_ldb = cast(LanguageBundleIndex, baseline.language_bundle)
    assert baseline_ldb.root["content_identity"] != candidate_ldb.root[
        "content_identity"
    ]
    assert original["package-lock"]["content_identity"] != mutated[
        "package-lock"
    ]["content_identity"]
    assert original["rir-semantic-payload"]["content_identity"] != mutated[
        "rir-semantic-payload"
    ]["content_identity"]
    assert original["rir-semantic-payload"]["semantic_identity"] == mutated[
        "rir-semantic-payload"
    ]["semantic_identity"]
    assert original["resolved-model"] != mutated["resolved-model"]
    assert original["build-receipt"] != mutated["build-receipt"]


def test_selected_unreachable_notation_preserves_both_rir_identities():
    source = _rpg_source_value()
    baseline = model_module.check_model_source_value(source)
    assert isinstance(baseline, model_module.CheckedModel)
    original = model_module.lower_checked_model(baseline)
    candidate_ldb = cast(
        LanguageBundleIndex, deepcopy(baseline.language_bundle)
    )
    _mutate_operation_notation(
        candidate_ldb,
        "quantity.identity",
        "name",
        "copy_value",
    )
    _rewrite_formula_expressions(candidate_ldb["vectors"], "identity(", "copy_value(")
    _reidentify_language_bundle(candidate_ldb)
    candidate = _check_with_candidate_ldb(source, baseline.kernel, candidate_ldb)
    mutated = model_module.lower_checked_model(candidate)

    assert original["package-lock"] != mutated["package-lock"]
    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["resolved-model"] != mutated["resolved-model"]
    assert original["capability-manifest"] != mutated["capability-manifest"]
    assert original["build-receipt"] != mutated["build-receipt"]


def test_unselected_resolution_profile_owner_still_reidentifies_lock():
    source = _model_source()
    packaged = model_module.check_model_source_value(source)
    assert isinstance(packaged, model_module.CheckedModel)
    baseline_ldb = cast(
        LanguageBundleIndex, deepcopy(packaged.language_bundle)
    )
    compiler = next(
        row
        for row in baseline_ldb["language"]["packages"]
        if row["id"] == "standard.compiler"
    )
    schema = next(
        row
        for row in baseline_ldb["language"]["packages"]
        if row["id"] == "standard.schema"
    )
    compiler["profiles"]["resolution"].remove("exact-import-resolution-v1")
    schema["profiles"]["resolution"].append("exact-import-resolution-v1")
    _reidentify_language_bundle(baseline_ldb)
    baseline = _check_with_candidate_ldb(source, packaged.kernel, baseline_ldb)
    original = model_module.lower_checked_model(baseline)
    assert "standard.schema" not in _locked_package_ids(original)

    candidate_ldb = cast(LanguageBundleIndex, deepcopy(baseline_ldb))
    profile = next(
        row
        for row in candidate_ldb["language"]["resolution_profiles"]
        if row["id"] == "exact-import-resolution-v1"
    )
    profile["extensions"]["standard.formula"]["max_nodes_per_formula"] += 1
    _reidentify_language_bundle(candidate_ldb)
    candidate = _check_with_candidate_ldb(source, packaged.kernel, candidate_ldb)
    mutated = model_module.lower_checked_model(candidate)

    assert original["package-lock"] != mutated["package-lock"]
    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["resolved-model"] != mutated["resolved-model"]
    assert original["build-receipt"] != mutated["build-receipt"]


def test_unlocked_escaping_authority_changes_rir_content_not_semantics():
    source = _model_source()
    quantity = {
        "type": "quantity",
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }
    local = "escaped`local"
    source["modules"][0]["formulas"] = [
        {
            "id": "derive-value",
            "parameters": [{"id": "base", **quantity}],
            "result": quantity,
            "body": {
                "nodes": [
                    {
                        "id": local,
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
                                    "kind": "parameter",
                                    "parameter": "base",
                                },
                            }
                        ],
                        "result": quantity,
                    }
                ],
                "result": {"kind": "local", "local": local},
            },
            "expression": (
                "let `escaped\\`local` = identity(base);\n`escaped\\`local`"
            ),
        }
    ]
    source["formula_bindings"] = [
        {
            "site": {
                "kind": "derived-symbol",
                "module": "main",
                "symbol": "derived_value",
            },
            "formula": {"module": "main", "id": "derive-value"},
            "arguments": [
                {
                    "parameter": "base",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "input_value",
                    },
                }
            ],
        }
    ]
    _use_derived_value(source)
    baseline = model_module.check_model_source_value(source)
    assert isinstance(baseline, model_module.CheckedModel), baseline
    original = model_module.lower_checked_model(baseline)

    candidate_ldb = cast(
        LanguageBundleIndex, deepcopy(baseline.language_bundle)
    )
    source_schema = next(
        row["schema"]
        for row in candidate_ldb["language"]["wire_schemas"]
        if row["artifact_kind"] == "model-source-package"
    )
    grammar = source_schema["$defs"]["formulaNotationGrammar"]["const"]
    grammar["escape_character"] = "/"
    grammar["escapable_identifier_characters"] = ["`", "/"]
    source["modules"][0]["formulas"][0]["expression"] = (
        "let `escaped/`local` = identity(base);\n`escaped/`local`"
    )
    _reidentify_language_bundle(candidate_ldb)
    candidate = _check_with_candidate_ldb(source, baseline.kernel, candidate_ldb)
    mutated = model_module.lower_checked_model(candidate)

    assert original["package-lock"] == mutated["package-lock"]
    assert original["rir-semantic-payload"]["content_identity"] != mutated[
        "rir-semantic-payload"
    ]["content_identity"]
    assert original["rir-semantic-payload"]["semantic_identity"] == mutated[
        "rir-semantic-payload"
    ]["semantic_identity"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_unselected_pure_operation_notation_preserves_lock_and_rir():
    source = _model_source()
    packaged = model_module.check_model_source_value(source)
    assert isinstance(packaged, model_module.CheckedModel)
    baseline_ldb = cast(
        LanguageBundleIndex, deepcopy(packaged.language_bundle)
    )
    operation = deepcopy(
        next(
            row
            for row in baseline_ldb["language"]["operations"]
            if row["id"] == "quantity.identity"
        )
    )
    operation["id"] = "game.check.unused-identity"
    operation["version"] = "1.0.1"
    operation["vectors"] = []
    operation["extensions"]["standard.formula-notation"][
        "name"
    ] = "unused_identity"
    baseline_ldb["language"]["operations"].append(operation)
    baseline_ldb["language"]["operations"].sort(key=lambda row: row["id"])
    game_check = next(
        row
        for row in baseline_ldb["language"]["packages"]
        if row["id"] == "game.check"
    )
    game_check["exports"]["operations"].append(operation["id"])
    game_check["exports"]["operations"].sort()
    _reidentify_language_bundle(baseline_ldb)
    baseline = _check_with_candidate_ldb(source, packaged.kernel, baseline_ldb)
    original = model_module.lower_checked_model(baseline)
    assert "game.check" not in _locked_package_ids(original)

    candidate_ldb = cast(LanguageBundleIndex, deepcopy(baseline_ldb))
    mutated_operation = next(
        row
        for row in candidate_ldb["language"]["operations"]
        if row["id"] == "game.check.unused-identity"
    )
    mutated_operation["extensions"]["standard.formula-notation"][
        "name"
    ] = "unused_copy"
    _reidentify_language_bundle(candidate_ldb)
    candidate = _check_with_candidate_ldb(source, packaged.kernel, candidate_ldb)
    mutated = model_module.lower_checked_model(candidate)

    assert baseline_ldb.root["content_identity"] != candidate_ldb.root[
        "content_identity"
    ]
    assert original["package-lock"] == mutated["package-lock"]
    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["resolved-model"] != mutated["resolved-model"]
    assert original["build-receipt"] != mutated["build-receipt"]


def test_formula_semantic_body_mutation_changes_both_rir_identities():
    source = _rpg_source_value()
    baseline = model_module.check_model_source_value(source)
    assert isinstance(baseline, model_module.CheckedModel)
    original = model_module.lower_checked_model(baseline)
    formula = next(
        row
        for row in source["modules"][0]["formulas"]
        if row["id"] == "mitigated-damage"
    )
    formula["body"] = {
        "node": "parameter",
        "parameter": "damage_before_defense",
    }
    formula["expression"] = "damage_before_defense"
    candidate = model_module.check_model_source_value(source)
    assert isinstance(candidate, model_module.CheckedModel), candidate
    mutated = model_module.lower_checked_model(candidate)

    assert original["package-lock"] == mutated["package-lock"]
    assert original["rir-semantic-payload"]["content_identity"] != mutated[
        "rir-semantic-payload"
    ]["content_identity"]
    assert original["rir-semantic-payload"]["semantic_identity"] != mutated[
        "rir-semantic-payload"
    ]["semantic_identity"]
    assert original["resolved-model"] != mutated["resolved-model"]
    assert original["build-receipt"] != mutated["build-receipt"]


def test_compile_only_package_authority_does_not_change_rir_semantics(tmp_path):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    candidate_ldb["language"]["model_checks"].reverse()
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = replace(checked, language_bundle=candidate_ldb)

    mutated = model_module.lower_checked_model(candidate)

    original_package = checked.language_bundle["language"]["packages"][0]
    mutated_package = candidate_ldb["language"]["packages"][0]
    assert original_package["semantic_identity"] == mutated_package["semantic_identity"]
    assert original_package["content_identity"] != mutated_package["content_identity"]
    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["package-lock"] != mutated["package-lock"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_vector_only_package_change_reidentifies_exact_wrappers_not_rir(tmp_path):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    original_ldb = cast(LanguageBundleIndex, checked.language_bundle)
    candidate_ldb = cast(LanguageBundleIndex, deepcopy(original_ldb))
    vector_set = next(
        item
        for item in candidate_ldb.package_conformance_vector_sets
        if item["package_id"] == "core.quantity"
    )
    vector_set["vectors"].reverse()
    vector_set["vector_definitions"].reverse()
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = replace(checked, language_bundle=candidate_ldb)

    mutated = model_module.lower_checked_model(candidate)

    original_package = next(
        item
        for item in original_ldb["language"]["packages"]
        if item["id"] == "core.quantity"
    )
    mutated_package = next(
        item
        for item in candidate_ldb["language"]["packages"]
        if item["id"] == "core.quantity"
    )
    assert (
        original_ldb.root["content_identity"] != candidate_ldb.root["content_identity"]
    )
    assert original_package["semantic_identity"] == mutated_package["semantic_identity"]
    assert original_package["content_identity"] != mutated_package["content_identity"]
    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["package-lock"] != mutated["package-lock"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_unreachable_runtime_operation_does_not_change_rir_semantics(tmp_path):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    unreachable = next(
        operation
        for operation in candidate_ldb["language"]["operations"]
        if operation["id"] == "game.combat.cast-v1"
    )
    unreachable["resource_bounds"]["max_steps"] += 1
    resource_vector = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "game.combat.cast.resource-bound"
    )
    resource_vector["expect"] += 1
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = replace(checked, language_bundle=candidate_ldb)

    mutated = model_module.lower_checked_model(candidate)

    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["package-lock"] == mutated["package-lock"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_non_rpg_package_reaches_evaluator_without_kernel_or_host_extension(
    tmp_path, monkeypatch
):
    kernel, baseline_ldb = authority_module.load_authorities()
    candidate_ldb = deepcopy(baseline_ldb)
    language = candidate_ldb["language"]
    package = deepcopy(
        next(item for item in language["packages"] if item["id"] == "standard.compiler")
    )
    package["id"] = "genre.economy"
    package["version"] = "1.0.0"
    package["dependencies"] = {
        "optional": [],
        "required": [
            {"id": "core.quantity", "version": "2.1.0"},
            {"id": "standard.runtime", "version": "1.1.0"},
        ],
    }
    package["capabilities"] = {
        "provided": ["genre.economy.purchase"],
        "required": ["quantity.lower"],
    }
    package["exports"] = {name: [] for name in package["exports"]}
    package["exports"]["operations"] = ["genre.economy.purchase-v1"]
    package["profiles"] = {"numeric": [], "resolution": [], "runtime": []}
    package["runtime_semantic_paths"] = [
        "language.capabilities",
        "language.operations",
    ]
    for entry in package["semantic_closure"]:
        entry["definitions"] = []
    operation = {
        "alias_policy": {"read_only": "share", "writable_groups": []},
        "body": [
            {
                "node": "subtract-state",
                "symbol": "account_balance",
                "value": "price",
            },
            {
                "node": "copy",
                "target": "remaining_balance",
                "value": "account_balance",
            },
        ],
        "default_outcome": "purchase-complete",
        "effects": [
            "event.commit",
            "metric.observe",
            "snapshot.commit",
        ],
        "id": "genre.economy.purchase-v1",
        "inputs": [
            {
                "access": "read-write",
                "domain": {"kind": "actual"},
                "id": "account_balance",
                "kind": "scalar",
                "numeric_policy": "exact-int64",
                "representation": "Int",
                "type": {
                    "id": "Quantity",
                    "package": "core.quantity",
                    "version": "2.1.0",
                },
                "unit": "1",
            },
            {
                "access": "read",
                "domain": {"kind": "actual"},
                "id": "price",
                "kind": "scalar",
                "numeric_policy": "exact-int64",
                "representation": "Int",
                "type": {
                    "id": "Quantity",
                    "package": "core.quantity",
                    "version": "2.1.0",
                },
                "unit": "1",
            },
        ],
        "kind_rules": {"inputs": "preserve", "result": "preserve"},
        "numeric_policy": "exact-int64",
        "operation_kind": "event-program",
        "outcomes": [
            {
                "id": "purchase-complete",
                "kind": "success",
                "state_policy": "commit",
            }
        ],
        "owner_type": "Quantity",
        "purity": "event",
        "refusals": [
            "runtime.reason.step-limit",
            "runtime.reason.numeric-overflow",
        ],
        "resource_bounds": {"max_steps": 2},
        "result": {
            "access": "read",
            "discardable": False,
            "domain": {"kind": "actual"},
            "id": "result",
            "kind": "scalar",
            "numeric_policy": "exact-int64",
            "representation": "Int",
            "source": {"kind": "local", "name": "remaining_balance"},
            "type": {
                "id": "Quantity",
                "package": "core.quantity",
                "version": "2.1.0",
            },
            "unit": "1",
        },
        "rule": "quantity.lower",
        "runtime_profile": "standard.exact-int64-event-v1",
        "unit_rules": {"inputs": "preserve", "result": "preserve"},
        "vectors": [
            "genre.economy.purchase.body",
            "genre.economy.purchase.effects",
            "genre.economy.purchase.outcomes",
            "genre.economy.purchase.resource-bound",
        ],
        "version": "1.0.0",
    }
    vectors = [
        {
            "category": category,
            "expect": (
                operation["resource_bounds"]["max_steps"]
                if member == "resource_bounds.max_steps"
                else operation[member]
            ),
            "id": f"genre.economy.purchase.{vector_id}",
            "kind": "operation-contract",
            "operation": operation["id"],
            "probe": {"path": member},
        }
        for category, vector_id, member in (
            ("positive", "body", "body"),
            ("effects", "effects", "effects"),
            ("outcome", "outcomes", "outcomes"),
            ("resource", "resource-bound", "resource_bounds.max_steps"),
        )
    ]
    language["capabilities"].append(
        {"id": "genre.economy.purchase", "rule": "quantity.lower"}
    )
    language["operations"].append(operation)
    language["packages"].append(package)
    candidate_ldb.package_conformance_vector_sets.append(
        _package_vector_set(package["id"], package["version"], vectors)
    )
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    assert kernel == authority_module.load_authorities()[0]
    assert baseline_ldb == authority_module.load_authorities()[1]

    source_document = _model_source()
    source_document["package_requirements"] = [
        {"id": "core.quantity", "version": "2.1.0"},
        {"id": "genre.economy", "version": "1.0.0"},
    ]
    source_document["modules"][0]["symbols"] = [
        _quantity_symbol("account_balance", "state"),
        _quantity_symbol("price", "parameter"),
        _quantity_symbol("purchase_balance", "output"),
    ]
    source_document["entrypoints"] = [
        {
            "id": "economy.purchase",
            "operation": {
                "package": "genre.economy",
                "version": "1.0.0",
                "id": "genre.economy.purchase-v1",
            },
            "arguments": [
                {
                    "port": "account_balance",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "account_balance",
                    },
                },
                {
                    "port": "price",
                    "operand": {
                        "kind": "symbol",
                        "module": "main",
                        "symbol": "price",
                    },
                },
            ],
            "result": {
                "kind": "symbol",
                "module": "main",
                "symbol": "purchase_balance",
            },
        }
    ]
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)

    package_lock = cast(dict[str, Any], artifacts["package-lock"])
    lock_packages = cast(list[dict[str, Any]], package_lock["packages"])
    assert [package["id"] for package in lock_packages] == [
        "core.quantity",
        "genre.economy",
        "standard.compiler",
        "standard.runtime",
    ]
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    selected = cast(dict[str, Any], rir["selected_semantics"])
    operations = cast(list[dict[str, Any]], selected["operations"])
    assert any(
        row["definition"]["id"] == "genre.economy.purchase-v1" for row in operations
    )
    build_receipt = cast(dict[str, Any], artifacts["build-receipt"])
    resolved_model = cast(dict[str, Any], artifacts["resolved-model"])
    experiment_value = {
        "schema_version": "2.0.0",
        "id": "example.economy.purchase",
        "version": "1.0.0",
        "kernel_identity": kernel["content_identity"],
        "language_bundle_identity": candidate_ldb["content_identity"],
        "model": {
            "source_identity": checked.source_identity,
            "build_receipt_identity": build_receipt["content_identity"],
            "resolved_model_identity": resolved_model["content_identity"],
            "package_lock_identity": package_lock["content_identity"],
            "rir_identity": artifacts["rir-semantic-payload"]["content_identity"],
        },
        "runtime": {
            "profile": "standard.exact-int64-event-v1",
            "required_evaluator": {
                "operation_kinds": ["event-program"],
                "instruction_nodes": ["copy", "subtract-state"],
                "effects": [
                    "event.commit",
                    "metric.observe",
                    "snapshot.commit",
                ],
                "numeric_policies": ["exact-int64"],
                "rng_algorithms": ["splitmix64-v1"],
                "runtime_profiles": ["standard.exact-int64-event-v1"],
            },
        },
        "seed": {"algorithm": "splitmix64-v1", "value": 20260727},
        "external_inputs": [],
        "scenarios": [
            {
                "id": "purchase",
                "entrypoint": "economy.purchase",
                "assignments": [
                    {
                        "target": {
                            "model": "example.quantity-model",
                            "module": "main",
                            "name": "account_balance",
                        },
                        "value": 100,
                    },
                    {
                        "target": {
                            "model": "example.quantity-model",
                            "module": "main",
                            "name": "price",
                        },
                        "value": 25,
                    },
                ],
                "named_streams": [],
                "terminal_condition": {"kind": "event-count", "maximum": 1},
            }
        ],
        "metrics": [
            {
                "id": "remaining_balance",
                "kind": "scalar",
                "unit": "1",
                "dimensions": [],
                "window": {"kind": "scenario", "name": "terminal-event"},
                "aggregation": "single",
                "replication": {"unit": "scenario"},
                "missing": "refuse",
                "censoring": "none",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": "account_balance",
                },
                "target": {"minimum": 75, "maximum": 75},
            }
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }
    experiment = experiment_module.CheckedExperiment(
        value=experiment_value,
        content_identity=experiment_module.experiment_input_identity(experiment_value),
        kernel=kernel,
        language_bundle=candidate_ldb,
        build_receipt=build_receipt,
        package_lock=package_lock,
        resolved_model=resolved_model,
        rir=cast(dict[str, Any], artifacts["rir-semantic-payload"]),
    )
    evaluation = experiment_module.evaluate_experiment(experiment)
    assert isinstance(evaluation, experiment_module.EvaluationArtifacts)
    event_trace = evaluation.members["event-trace"].value
    assert event_trace["events"][0]["operation"] == "genre.economy.purchase-v1"
    assert event_trace["events"][0]["state_after"] == [
        {"name": "account_balance", "value": 75}
    ]
    assert evaluation.members["metric-dataset"].value["samples"][0]["value"] == 75
    host_sources = (
        Path(model_module.__file__),
        Path(model_command_module.__file__),
        Path(experiment_module.__file__),
    )
    assert all("genre.economy" not in path.read_text() for path in host_sources)


@pytest.mark.parametrize(
    "unused_semantics",
    ("domain", "runtime-profile", "capability"),
)
def test_unreachable_package_semantics_do_not_change_rir(
    tmp_path,
    unused_semantics,
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    language = candidate_ldb["language"]
    package = language["packages"][0]
    if unused_semantics == "domain":
        language["quantity"]["domains"].append("unused-domain")
        package["exports"]["domains"].append("unused-domain")
    elif unused_semantics == "runtime-profile":
        language["runtime_profiles"].append(
            {
                "id": "compile.unused",
                "version": "2.0.0",
                "numeric_policy": "exact-int64",
                "evaluation": "declaration-only",
                "effects": [],
                "resource_bounds": {"max_steps": 1},
            }
        )
        package["profiles"]["runtime"].append("compile.unused")
    else:
        language["capabilities"].append(
            {"id": "quantity.unused", "rule": "quantity.lower"}
        )
        package["capabilities"]["provided"].append("quantity.unused")
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True

    mutated = model_module.lower_checked_model(
        replace(checked, language_bundle=candidate_ldb)
    )

    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["package-lock"] != mutated["package-lock"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_resolution_step_exhaustion_is_a_typed_static_refusal(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    kernel, candidate_ldb = deepcopy(authority_module.load_authorities())
    candidate_ldb["resources"]["max_rule_match_steps"] = 1
    boundary = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.accept.resolution-step-boundary"
    )
    successor = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.refuse.resolution-step-budget"
    )
    boundary["input"]["value"] = 1
    successor["input"]["value"] = 2
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.resource_exhausted"
    ]


@pytest.mark.parametrize("command", ("check", "build"))
def test_runtime_projection_step_exhaustion_is_a_typed_static_refusal(
    tmp_path, run_cli, monkeypatch, command
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    kernel, candidate_ldb = deepcopy(authority_module.load_authorities())
    candidate_ldb["resources"]["max_runtime_projection_steps"] = 1
    boundary = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.accept.runtime-projection-step-boundary"
    )
    successor = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.refuse.runtime-projection-step-budget"
    )
    boundary["input"]["value"] = 1
    successor["input"]["value"] = 2
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    _inject_authority_context(monkeypatch, kernel, candidate_ldb)

    output = tmp_path / "published"
    arguments = ["model", command, str(source)]
    if command == "build":
        arguments.extend(
            [
                "--out",
                str(output),
                "--invocation-key",
                "a" * 64,
            ]
        )
    exit_code, stdout, stderr = run_cli(arguments)

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.resource_exhausted"
    ]
    assert not output.exists()
