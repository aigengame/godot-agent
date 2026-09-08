"""Public Formula slots in pure fold steps retain the whole accumulator domain."""

from copy import deepcopy

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from schema2_authority_support import mutable_authorities
from test_schema2_model_cli import _reidentify_language_bundle
from test_current_namespace_public import _PublicCandidate, _members
from test_bounded_fold_public import (
    _source,
    _specification,
    _check,
    _run,
    _admit_artifacts,
)

_OWNER = "standard.conformance.structured"
_MAX = (1 << 63) - 1
_MIN = -(1 << 63)


def _slot_authorities():
    kernel, language = mutable_authorities()
    operations = {row["id"]: row for row in language["language"]["operations"]}
    step = operations["bounded.count-step"]
    scalar = {
        key: deepcopy(value)
        for key, value in step["inputs"][0].items()
        if key not in {"id", "access"}
    }
    step["body"] = [
        {"node": "copy", "target": "bound-count", "value": "count"},
        {"node": "constant", "target": "one", "literal": 1},
        {"node": "add", "target": "next-count", "left": "bound-count", "right": "one"},
    ]
    step["resource_bounds"]["max_steps"] = 3
    step["extensions"] = {
        "standard.formula-slots": [
            {
                "id": "accumulator-policy",
                "context": {"phase": "event"},
                "parameters": [
                    {
                        **scalar,
                        "id": "count",
                        "source": {"kind": "port", "name": "count"},
                    }
                ],
                "result": scalar,
                "permitted_refusals": [],
                "placeholder_index": 0,
                "placeholder_length": 1,
                "resource_bounds": {"max_steps": 1},
                "target": "bound-count",
                "termination_measure": 1,
            }
        ]
    }
    operations["bounded-fold-v1"]["resource_bounds"]["max_steps"] = 56
    for vector in language["vectors"]:
        if vector.get("kind") == "operation-contract" and vector.get("operation") in {
            "bounded.count-step",
            "bounded-fold-v1",
        }:
            value = operations[vector["operation"]]
            for key in vector["probe"]["path"].split("."):
                value = value[key]
            vector["expect"] = deepcopy(value)
    _reidentify_language_bundle(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    return kernel, language


def _slot_source(*, narrow=False):
    source = _source()
    source["entrypoints"][0]["arguments"][-1]["operand"]["value"] = 5
    scalar = {
        "type": "quantity",
        "kind": "scalar",
        "representation": "Int",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0 if narrow else _MIN, "maximum": 0 if narrow else _MAX},
        "numeric_policy": "exact-int64",
    }
    source["modules"][0]["formulas"] = [
        {
            "id": "accumulator-identity",
            "parameters": [{"id": "count", **scalar}],
            "result": scalar,
            "body": {"node": "parameter", "parameter": "count"},
            "expression": "count",
        }
    ]
    source["formula_bindings"] = [
        {
            "site": {
                "kind": "operation-slot",
                "operation": {"package": _OWNER, "id": "bounded.count-step"},
                "slot": "accumulator-policy",
            },
            "formula": {"module": "fold", "id": "accumulator-identity"},
            "arguments": [
                {
                    "parameter": "count",
                    "operand": {"kind": "slot-parameter", "parameter": "count"},
                }
            ],
        }
    ]
    return source


def _build(candidate, source, *, success=True):
    candidate.write_source(source)
    return candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / "build"),
        "--invocation-key",
        "09" * 32,
        success=success,
    )


def test_public_fold_step_executes_bound_formula_for_each_actual_accumulator(tmp_path):
    candidate = _PublicCandidate(tmp_path, authorities=_slot_authorities())
    receipt = _build(candidate, _slot_source())
    artifacts = _members(receipt)
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    step = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["definition"]["id"] == "bounded.count-step"
    )
    assert step["operation_kind"] == "pure-expression"
    assert "standard.snapshot-operands" not in step["extensions"]
    assert step["body"][0] == {
        "node": "copy",
        "target": "bound-count",
        "value": "count",
    }
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    specification = _specification(rir, [1, 2, 3, 4], count=4, order=1234)
    specification["runtime"]["required_evaluator"]["instruction_nodes"].append("copy")
    specification["runtime"]["required_evaluator"]["instruction_nodes"].sort()
    path, _ = _check(candidate, rir_path, specification)
    run = _run(candidate, rir_path, path)
    members = _members(run)
    _admit_artifacts(candidate, rir, specification, members)
    event = members["event-trace"]["events"][0]
    evaluations = event["formula_evaluations"]
    assert [row["arguments"] for row in evaluations] == [
        [{"parameter": "count", "value": value}] for value in range(4)
    ]
    assert [row["result"] for row in evaluations] == list(range(4))
    assert [row["call_path"] for row in evaluations] == [
        f"fold/count-selected/@{index}" for index in range(4)
    ]
    assert event["calls"] == []
    assert {row["name"]: row["value"] for row in event["state_after"]}[
        "selected_count"
    ] == 4
    assert (
        members["snapshot-series"]["snapshots"][-1]["continuation"]["resource_ledger"][
            "node_steps"
        ]
        == 56
    )


def test_fold_formula_parameter_must_cover_later_accumulators_not_only_initial_zero(
    tmp_path,
):
    candidate = _PublicCandidate(tmp_path, authorities=_slot_authorities())
    result = _build(candidate, _slot_source(narrow=True), success=False)
    diagnostic = result["error"]["diagnostics"][0]
    assert diagnostic["code"] == "language.formula_type_mismatch"
    assert diagnostic["primary"]["pointer"] == "/formula_bindings/0/arguments/0/operand"
    assert "concrete call-site domain" in diagnostic["message"]
