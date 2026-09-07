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
    ("phase", "limit", "committed", "before", "charged"),
    [
        ("initialization", 2, 0, 0, 3),
        ("event", 5, 0, 3, 6),
        ("observation", 20, 1, 19, 22),
    ],
)
def test_public_formula_budget_refusal_preserves_site_frame_and_atomic_prefix(
    tmp_path, run_cli, monkeypatch, phase, limit, committed, before, charged
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
    assert last["before"] == before
    assert last["after"] == before + 3 == charged
    assert charged > limit
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
        assert audit["budget_counters"]["node_steps"] == charged
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


_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1


def _maximum_source(other, *, safe_combat_input=False, eager_underflow=False):
    source = _rpg_model_source()
    module = source["modules"][0]
    bounds = {"minimum": _INT64_MIN, "maximum": _INT64_MAX}
    for symbol in module["symbols"]:
        if symbol["symbol"] in {"accuracy", "effective_accuracy"}:
            symbol["domain"] = dict(bounds)
    formula = next(
        row for row in module["formulas"] if row["id"] == "effective-accuracy"
    )
    formula["parameters"][0]["domain"] = dict(bounds)
    formula["result"]["domain"] = dict(bounds)

    def operation_node(name, operation, left, right, result):
        return {
            "id": name,
            "node": "operation-call",
            "operation": {"package": "core.quantity", "id": operation},
            "arguments": [
                {"port": "left", "operand": left},
                {"port": "right", "operand": right},
            ],
            "result": deepcopy(result),
        }

    base = {"kind": "parameter", "parameter": "base"}
    literal = {"kind": "literal", "value": other}
    maximum = operation_node(
        "maximum", "quantity.maximum", base, literal, formula["result"]
    )
    body = [maximum]
    formula["expression"] = f"let maximum = max(base, {other});\nmaximum"
    if eager_underflow:
        body.insert(
            0,
            operation_node(
                "underflow",
                "quantity.subtract",
                base,
                {"kind": "literal", "value": 1},
                formula["result"],
            ),
        )
        maximum["arguments"] = [
            {"port": "left", "operand": literal},
            {"port": "right", "operand": {"kind": "local", "local": "underflow"}},
        ]
        formula["expression"] = (
            f"let underflow = base - 1;\nlet maximum = max({other}, underflow);\nmaximum"
        )
    formula["body"] = {"nodes": body, "result": {"kind": "local", "local": "maximum"}}
    if safe_combat_input:
        # Keep the full-width maximum observable at every lifecycle phase while
        # preventing the separate hit-score addition from overflowing on MAX.
        safe_symbol = deepcopy(
            next(
                row
                for row in module["symbols"]
                if row["symbol"] == "effective_accuracy"
            )
        )
        safe_symbol["symbol"] = "safe_accuracy"
        safe_symbol["domain"] = dict(bounds)
        module["symbols"].append(safe_symbol)
        safe_formula = deepcopy(formula)
        safe_formula["id"] = "safe-accuracy"
        safe_formula["result"]["domain"] = dict(safe_symbol["domain"])
        safe_formula["body"] = {
            "nodes": [
                operation_node(
                    "safe",
                    "quantity.minimum",
                    base,
                    {"kind": "literal", "value": 85},
                    safe_formula["result"],
                )
            ],
            "result": {"kind": "local", "local": "safe"},
        }
        safe_formula["expression"] = "let safe = min(base, 85);\nsafe"
        module["formulas"].append(safe_formula)
        source["formula_bindings"].append(
            {
                "site": {
                    "kind": "derived-symbol",
                    "module": "combat",
                    "symbol": "safe_accuracy",
                },
                "formula": {"module": "combat", "id": "safe-accuracy"},
                "arguments": [
                    {
                        "parameter": "base",
                        "operand": {
                            "kind": "symbol",
                            "module": "combat",
                            "symbol": "effective_accuracy",
                        },
                    }
                ],
            }
        )
        for entrypoint in source["entrypoints"]:
            for argument in entrypoint["arguments"]:
                if argument["operand"].get("symbol") == "effective_accuracy":
                    argument["operand"]["symbol"] = "safe_accuracy"
    return source


def _maximum_specification(receipt, value):
    specification = _experiment(build_receipt=receipt, base_damage=24)
    next(
        row
        for row in specification["scenarios"][0]["assignments"]
        if row["target"]["name"] == "accuracy"
    )["value"] = value
    for metric in specification["metrics"]:
        metric["target"] = {"minimum": 0, "maximum": 1000}
    return specification


@pytest.mark.parametrize(
    ("value", "other", "expected"),
    [
        (_INT64_MIN, _INT64_MAX, _INT64_MAX),
        (_INT64_MAX, _INT64_MIN, _INT64_MAX),
        (_INT64_MIN, _INT64_MIN, _INT64_MIN),
        (_INT64_MAX, _INT64_MAX, _INT64_MAX),
    ],
    ids=["less", "greater", "equal-min", "equal-max"],
)
def test_public_composed_maximum_extrema_in_all_formula_phases_and_cache(
    tmp_path, run_cli, monkeypatch, value, other, expected
):
    receipt, rir_path, rir = _build(
        tmp_path, run_cli, _maximum_source(other, safe_combat_input=True)
    )
    specification = _maximum_specification(receipt, value)
    if expected == _INT64_MIN:
        # A miss has no cast-resolved damage observation. Select the terminal
        # snapshot and assert the committed miss directly below.
        specification["metrics"] = [
            row
            for row in specification["metrics"]
            if row["observation"]["source"] == "snapshot"
        ]
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
        assert len(events) == 1
        assert events[0]["outcome"]["id"] == (
            "miss" if expected == _INT64_MIN else "cast-resolved"
        )
        assert events[0]["state_after"] == [
            {"name": "actor_mana", "value": 30 if expected == _INT64_MIN else 22},
            {"name": "target_health", "value": 100 if expected == _INT64_MIN else 82},
        ]
        frames = {
            "initialization": _initial_frame(rir, specification),
            "event": events[0]["snapshot_before_identity"],
            "observation": events[0]["snapshot_after_identity"],
        }
        assert len(calls) == 6
        for name, result in (
            ("effective_accuracy", expected),
            ("safe_accuracy", min(expected, 85)),
        ):
            selected = [
                call for call in calls if call["program"]["target"]["name"] == name
            ]
            assert [call["phase"] for call in selected] == [
                "initialization",
                "event",
                "observation",
            ]
            for call in selected:
                program = call["program"]
                assert program in rir["initialization_programs"]
                assert [row["instruction"]["node"] for row in program["body"]] == [
                    "less-than",
                    "if",
                    "copy",
                ]
                assert program["resource_bounds"]["max_steps"] == 3
                assert call["after"] - call["before"] == 3
                assert call["value"] == result
                assert call["frame"] == frames[call["phase"]]
                assert call["cache_growth"] == (0 if prewarm else 1)
        expected_metrics = {
            "target_health_remaining": 100 if expected == _INT64_MIN else 82
        }
        if expected != _INT64_MIN:
            expected_metrics["damage_dealt"] = 18
        assert {
            row["metric"]: row["value"] for row in members["metric-dataset"]["samples"]
        } == expected_metrics
    assert results[0] == results[1]


@pytest.mark.parametrize(
    ("phase", "before", "charged"),
    [("initialization", 0, 3), ("event", 3, 6), ("observation", 29, 32)],
)
@pytest.mark.parametrize("offset", [-1, 0, 1], ids=["below", "at", "above"])
def test_public_composed_maximum_charges_at_each_phase_budget_boundary(
    tmp_path, run_cli, monkeypatch, phase, before, charged, offset
):
    limit = charged + offset
    monkeypatch.setattr(authority, "_PACKAGED_CONTEXT", _limited_context(limit))
    receipt, rir_path, rir = _build(tmp_path, run_cli, _maximum_source(1))
    specification = _maximum_specification(receipt, 85)
    spec_path = _write_specification(tmp_path, run_cli, rir_path, specification)
    calls = _observe_programs(monkeypatch)
    code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path)
    assert stderr == ""
    target = next(call for call in calls if call["phase"] == phase)
    program = target["program"]
    assert [row["instruction"]["node"] for row in program["body"]] == [
        "less-than",
        "if",
        "copy",
    ]
    assert program["resource_bounds"]["max_steps"] == 3
    assert target["before"] == before
    assert target["after"] == charged == before + 3
    if offset < 0:
        fault = target["fault"]
        assert fault.signal == "step-limit"
        assert fault.program == program["identity"]
        assert fault.evaluation_site_identity == program["site"]["identity"]
        assert fault.frame_identity == target["frame"]
    else:
        assert "fault" not in target
        assert target["value"] == 85

    if phase == "observation" and offset >= 0:
        assert code == 0, stdout
        members = _members(json.loads(stdout))
        snapshots = members["snapshot-series"]["snapshots"]
        assert snapshots[-1]["continuation"]["resource_ledger"]["node_steps"] == charged
        frame = next(
            row for row in snapshots if row["snapshot_identity"] == target["frame"]
        )
        assert frame["continuation"]["resource_ledger"]["node_steps"] == before
        event = next(
            row
            for row in members["event-trace"]["events"]
            if row["observation"] is None
        )
        assert target["frame"] == event["snapshot_after_identity"]
        assert {
            row["metric"]: row["value"] for row in members["metric-dataset"]["samples"]
        } == {"damage_dealt": 18, "target_health_remaining": 82}
        return

    # At/above the initialization or Event Formula bound, the selected program
    # succeeds; the same global budget still refuses a later unit of work.
    assert code == 2, stdout
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == "runtime.step_limit_exceeded"
    if phase == "initialization" and offset < 0:
        assert target["frame"] == _initial_frame(rir, specification)
        assert diagnostic["primary"]["identity"] == program["site"]["identity"]
        assert diagnostic["related"][0]["identity"] == target["frame"]
        assert "terminal_audit" not in error
        assert not (tmp_path / "run-02").exists()
        return

    members = _members(error["terminal_audit"])
    audit = members["runtime-terminal-audit"]
    committed = int(phase == "observation")
    assert len(audit["committed_trace_prefix"]) == committed
    assert audit["last_snapshot_record"]["index"] == committed
    assert audit["last_snapshot_record"]["values"] == [
        {"name": "actor_mana", "value": 22 if committed else 30},
        {"name": "target_health", "value": 82 if committed else 100},
    ]
    assert audit["rollback"] == {
        "committed": False,
        "state_before": audit["last_snapshot_record"]["values"],
        "state_after": audit["last_snapshot_record"]["values"],
    }
    if offset < 0:
        assert audit["budget_counters"]["node_steps"] == charged
        assert audit["last_snapshot_identity"] == target["frame"]
        assert (
            audit["refusing_event"]["evaluation_site_identity"]
            == program["site"]["identity"]
        )
    elif phase == "initialization":
        later = calls[-1]
        assert later["phase"] == "event"
        assert later["before"] == 3
        assert later["after"] == 6
        assert later["fault"].signal == "step-limit"
        assert audit["budget_counters"]["node_steps"] == 6
        assert (
            audit["refusing_event"]["evaluation_site_identity"]
            == later["program"]["site"]["identity"]
        )
    else:
        assert audit["budget_counters"]["node_steps"] == limit + 1
        assert audit["refusing_event"]["evaluation_site_identity"] is None


def test_public_composed_maximum_eager_operand_overflow_precedes_snapshot_zero(
    tmp_path, run_cli, monkeypatch
):
    receipt, rir_path, rir = _build(
        tmp_path, run_cli, _maximum_source(_INT64_MAX, eager_underflow=True)
    )
    specification = _maximum_specification(receipt, _INT64_MIN)
    spec_path = _write_specification(tmp_path, run_cli, rir_path, specification)
    calls = _observe_programs(monkeypatch)
    code, stdout, stderr = _run(tmp_path, run_cli, spec_path, rir_path)
    assert (code, stderr) == (2, ""), stdout
    assert len(calls) == 1
    call = calls[0]
    program = call["program"]
    assert call["phase"] == "initialization"
    assert [row["instruction"]["node"] for row in program["body"]] == [
        "subtract",
        "copy",
        "less-than",
        "if",
        "copy",
    ]
    assert program["resource_bounds"]["max_steps"] == 5
    assert call["before"] == 0
    assert call["after"] == 5
    fault = call["fault"]
    assert fault.signal == "numeric-overflow"
    assert fault.program == program["identity"]
    assert (
        fault.evaluation_site_identity == program["body"][0]["evaluation_site_identity"]
    )
    assert fault.frame_identity == call["frame"] == _initial_frame(rir, specification)
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == "runtime.numeric_overflow"
    assert diagnostic["primary"]["identity"] == fault.evaluation_site_identity
    assert diagnostic["related"][0]["identity"] == fault.frame_identity
    assert "terminal_audit" not in error
    assert not (tmp_path / "run-02").exists()
