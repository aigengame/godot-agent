"""Real CLI Formula lifecycle calls reach the production value-program evaluator."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

import gda_balancing.domain.authority.context as authority
import gda_balancing.domain.runtime.execution as runtime
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from schema2_authority_support import mutable_authorities
from test_schema2_model_cli import _reidentify_language_bundle
from test_schema2_experiment_cli import (
    _experiment,
    _rpg_model_source,
)


_EXAMPLE = Path(__file__).parents[1] / "examples/schema2/progression-periodic-effect"


def _members(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        row["logical_name"]: json.loads(Path(row["locator"]).read_bytes())
        for row in receipt["member_locators"]
    }


def _build(tmp_path, run_cli, source: dict[str, Any] | None = None):
    source_path = _EXAMPLE / "model-source.json"
    if source is not None:
        source_path = tmp_path / "source.json"
        source_path.write_text(json.dumps(source))
    code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source_path),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "01" * 32,
        ]
    )
    assert (code, stderr) == (0, ""), stdout
    receipt = json.loads(stdout)
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    return receipt, rir_path, _members(receipt)["rir-semantic-payload"]


def _write_specification(tmp_path, run_cli, rir_path, value):
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(value))
    code, stdout, stderr = run_cli(
        ["experiment", "check", str(path), "--rir", rir_path]
    )
    assert (code, stderr) == (0, ""), stdout
    assert json.loads(stdout)["checked"] is True
    return path


def _run(tmp_path, run_cli, spec_path, rir_path, key="02"):
    return run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--rir",
            rir_path,
            "--out",
            str(tmp_path / f"run-{key}"),
            "--invocation-key",
            key * 32,
        ]
    )


def _observe_programs(monkeypatch, *, prewarm=False):
    evaluate = getattr(runtime, "_evaluate_formula_program")
    calls = []

    def observed(program, input_values, **kwargs):
        assert program["body"], "an empty coordinator call is not Formula execution"
        assert program["site"]["context"]["phase"] == kwargs["phase"]
        assert program["identity"].startswith("sha256:")
        assert all(
            row["evaluation_site_identity"].startswith("sha256:")
            for row in program["body"]
        )
        cache = kwargs["cache"]
        assert isinstance(cache, dict)
        # Instrumented cache-hit condition: evaluate the exact request once to
        # populate the real cache, then let the ordinary call consume that hit.
        # Only the ordinary call's charged result is returned to the caller.
        if prewarm:
            evaluate(program, input_values, **kwargs)
        record = {
            "program": program,
            "inputs": dict(input_values),
            "phase": kwargs["phase"],
            "frame": kwargs["frame_identity"],
            "before": kwargs["consumed_steps"],
            "limit": kwargs["runtime_limit"],
            "cache_before": len(cache),
        }
        calls.append(record)
        try:
            result = evaluate(program, input_values, **kwargs)
        except runtime._InitializationProgramFault as fault:
            record["fault"] = fault
            record["after"] = fault.consumed_steps
            raise
        record.update(
            value=result.value,
            after=result.consumed_steps,
            cache_growth=len(cache) - record["cache_before"],
        )
        return result

    monkeypatch.setattr(runtime, "_evaluate_formula_program", observed)
    return calls


def _initial_frame(rir, specification):
    values = {
        canonical_bytes(row["target"]): row["value"]
        for row in rir["entrypoints"][0]["scenario_input_contract"]["initializers"]
    }
    scenario = specification["scenarios"][0]
    values.update(
        {
            canonical_bytes(row["target"]): row["value"]
            for row in scenario["assignments"]
        }
    )
    return content_identity(
        "initialization-frame-v2",
        {
            "token": {"scenario": scenario["id"], "snapshot_index": 0},
            "values": [
                {"symbol": key.decode().rstrip("\n"), "value": value}
                for key, value in sorted(values.items())
            ],
        },
    )


def test_public_nonempty_formula_phases_preserve_frames_charge_and_cached_results(
    tmp_path, run_cli, monkeypatch
):
    _receipt, rir_path, rir = _build(tmp_path, run_cli)
    specification = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    assert specification["model"] == {"rir_semantic_identity": rir["semantic_identity"]}
    spec_path = _write_specification(tmp_path, run_cli, rir_path, specification)
    results = []
    for prewarm, key in ((False, "02"), (True, "03")):
        with monkeypatch.context() as scoped:
            calls = _observe_programs(scoped, prewarm=prewarm)
            code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path, key)
        assert (code, stderr) == (0, ""), stdout
        members = _members(json.loads(stdout))
        results.append(members)
        events = [
            row
            for row in members["event-trace"]["events"]
            if row["observation"] is None
        ]
        assert [row["outcome"]["id"] for row in events] == [
            "applied",
            "ticked",
            "ticked",
            "expired",
        ]
        assert [row["phase"] for row in calls] == [
            "initialization",
            "event",
            "observation",
            "event",
            "observation",
            "event",
            "observation",
            "event",
            "observation",
        ]
        assert calls[0]["frame"] == _initial_frame(rir, specification)
        for phase, member in (
            ("event", "snapshot_before_identity"),
            ("observation", "snapshot_after_identity"),
        ):
            assert [row["frame"] for row in calls if row["phase"] == phase] == [
                row[member] for row in events
            ]
        programs = {row["identity"]: row for row in rir["initialization_programs"]}
        assert {row["program"]["identity"] for row in calls} == set(programs)
        for call in calls:
            program = call["program"]
            assert program == programs[program["identity"]]
            assert len(program["body"]) == 2
            assert program["resource_bounds"]["max_steps"] == 3
            assert call["after"] - call["before"] == 3
            assert call["inputs"] == {"damage_per_level": 17, "level": 5}
            assert call["value"] == 85
            assert call["cache_growth"] == (0 if prewarm else 1)
        assert {
            row["metric"]: row["value"] for row in members["metric-dataset"]["samples"]
        } == {
            "target_health_remaining": 70,
            "effect_active_terminal": 0,
            "effect_instance_id_terminal": 1507657888,
        }
    # The controlled cache-hit run must retain every semantic AND producer member.
    # This in-memory observation changes no producer source bytes.
    assert results[0] == results[1]


def _limited_context(limit):
    kernel, bundle = mutable_authorities()
    profile = next(
        row
        for row in bundle["language"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    profile["resource_bounds"]["max_node_steps"] = limit
    _reidentify_language_bundle(bundle)
    context = authority.admit_authority_context(kernel, bundle)
    assert isinstance(context, authority.AdmittedAuthorityContext), context
    return context


@pytest.mark.parametrize(
    ("phase", "limit", "committed"),
    [
        ("initialization", 2, 0),
        ("event", 5, 0),
        ("observation", 20, 1),
    ],
)
def test_public_formula_budget_refusal_preserves_site_frame_and_atomic_prefix(
    tmp_path, run_cli, monkeypatch, phase, limit, committed
):
    # Inject an actually admitted authority value at the normal context owner;
    # no checked RIR or Runtime policy is replaced after admission.
    monkeypatch.setattr(authority, "_PACKAGED_CONTEXT", _limited_context(limit))
    _receipt, rir_path, rir = _build(tmp_path, run_cli)
    specification = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    specification["model"] = {"rir_semantic_identity": rir["semantic_identity"]}
    spec_path = _write_specification(tmp_path, run_cli, rir_path, specification)
    calls = _observe_programs(monkeypatch)
    code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path)
    assert (code, stderr) == (2, ""), stdout
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    last = calls[-1]
    fault = last["fault"]
    assert last["phase"] == phase
    assert fault.signal == "step-limit"
    assert fault.program == last["program"]["identity"]
    assert fault.evaluation_site_identity == last["program"]["site"]["identity"]
    assert fault.frame_identity == last["frame"]
    assert last["after"] == last["before"] + 3 == limit + 1
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == "runtime.step_limit_exceeded"
    if phase == "initialization":
        assert diagnostic["primary"] == {
            "kind": "runtime",
            "subject": "formula-evaluation-site",
            "identity": fault.evaluation_site_identity,
        }
        assert last["frame"] == _initial_frame(rir, specification)
        assert diagnostic["related"][0] == {
            "kind": "runtime",
            "subject": "initialization-frame",
            "identity": last["frame"],
        }
        assert "terminal_audit" not in error
        assert not (tmp_path / "run-02").exists()
    else:
        members = _members(error["terminal_audit"])
        assert set(members) == {
            "evaluator-capability-manifest",
            "resolved-runtime-profile",
            "runtime-terminal-audit",
        }
        audit = members["runtime-terminal-audit"]
        assert diagnostic["primary"] == {
            "kind": "artifact",
            "content_identity": audit["experiment_identity"],
            "pointer": "/scenarios/0/entrypoint",
        }
        assert [row["outcome"]["id"] for row in audit["committed_trace_prefix"]] == (
            ["applied"] if committed else []
        )
        assert audit["last_snapshot_record"]["values"] == [
            {"name": "effect_active", "value": committed},
            {
                "name": "effect_instance_id",
                "value": 1507657888 if committed else 0,
            },
            {"name": "target_health", "value": 100},
        ]
        assert audit["last_snapshot_identity"] == last["frame"]
        assert audit["last_snapshot_record"]["index"] == committed
        assert audit["rollback"] == {
            "committed": False,
            "state_before": audit["last_snapshot_record"]["values"],
            "state_after": audit["last_snapshot_record"]["values"],
        }
        assert audit["budget_counters"]["node_steps"] == limit + 1
        assert (
            audit["refusing_event"]["evaluation_site_identity"]
            == fault.evaluation_site_identity
        )


def test_public_numeric_formula_refusal_uses_the_real_instruction_site_before_snapshot_zero(
    tmp_path, run_cli, monkeypatch
):
    source = _rpg_model_source()
    bounds = {"minimum": -(1 << 63), "maximum": (1 << 63) - 1}
    for symbol in source["modules"][0]["symbols"]:
        if symbol["symbol"] in {"accuracy", "effective_accuracy"}:
            symbol["domain"] = dict(bounds)
    formula = next(
        row
        for row in source["modules"][0]["formulas"]
        if row["id"] == "effective-accuracy"
    )
    formula["parameters"][0]["domain"] = dict(bounds)
    formula["result"]["domain"] = dict(bounds)
    formula["body"] = {
        "nodes": [
            {
                "id": "underflow",
                "node": "operation-call",
                "operation": {"package": "core.quantity", "id": "quantity.subtract"},
                "arguments": [
                    {
                        "port": "left",
                        "operand": {"kind": "parameter", "parameter": "base"},
                    },
                    {"port": "right", "operand": {"kind": "literal", "value": 1}},
                ],
                "result": deepcopy(formula["result"]),
            }
        ],
        "result": {"kind": "local", "local": "underflow"},
    }
    formula["expression"] = "let underflow = base - 1;\nunderflow"
    receipt, rir_path, rir = _build(tmp_path, run_cli, source)
    specification = _experiment(build_receipt=receipt, base_damage=24)
    next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "accuracy"
    )["value"] = bounds["minimum"]
    spec_path = _write_specification(tmp_path, run_cli, rir_path, specification)
    calls = _observe_programs(monkeypatch)
    code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path)
    assert (code, stderr) == (2, ""), stdout
    assert len(calls) == 1
    call = calls[0]
    program = next(
        row
        for row in rir["initialization_programs"]
        if row["site"]["context"]["phase"] == "initialization"
        and row["target"]["name"] == "effective_accuracy"
    )
    fault = call["fault"]
    assert call["phase"] == "initialization"
    assert call["program"] == program
    assert fault.signal == "numeric-overflow"
    assert fault.evaluation_site_identity == next(
        row["evaluation_site_identity"]
        for row in program["body"]
        if row["instruction"]["node"] == "subtract"
    )
    assert fault.frame_identity == _initial_frame(rir, specification)
    assert call["after"] == program["resource_bounds"]["max_steps"]
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == "runtime.numeric_overflow"
    assert diagnostic["primary"] == {
        "kind": "runtime",
        "subject": "formula-evaluation-site",
        "identity": fault.evaluation_site_identity,
    }
    assert diagnostic["related"][0] == {
        "kind": "runtime",
        "subject": "initialization-frame",
        "identity": fault.frame_identity,
    }
    assert "terminal_audit" not in error
    assert not (tmp_path / "run-02").exists()
