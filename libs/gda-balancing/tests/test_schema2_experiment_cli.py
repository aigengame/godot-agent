"""Public RPG Experiment tracer for Standard Schema 2.0 (#540)."""

import json
from pathlib import Path
from typing import Any

from gda_balancing.schema2.canonical import content_identity


def _rpg_value(name: str, role: str) -> dict[str, Any]:
    return {
        "symbol": name,
        "type": "rpg",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 1000},
        "numeric_policy": "exact-int64",
    }


def _rpg_model_source() -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "example.rpg-combat-cast",
            "version": "1.0.0",
            "entry_module": "combat",
        },
        "package_requirements": [
            {"id": "core.quantity", "version": "2.0.0"},
            {"id": "game.rpg", "version": "1.0.0"},
        ],
        "modules": [
            {
                "id": "combat",
                "imports": [
                    {
                        "alias": "rpg",
                        "package": "game.rpg",
                        "version": "1.0.0",
                        "symbol": "RpgValue",
                    }
                ],
                "symbols": [
                    _rpg_value("actor_mana", "state"),
                    _rpg_value("action_cost", "parameter"),
                    _rpg_value("accuracy", "parameter"),
                    _rpg_value("base_damage", "parameter"),
                    _rpg_value("critical_threshold", "parameter"),
                    _rpg_value("target_defense", "input"),
                    _rpg_value("target_health", "state"),
                ],
            }
        ],
    }


def _member(receipt: dict[str, Any], logical_name: str) -> dict[str, Any]:
    locator = next(
        item["locator"]
        for item in receipt["member_locators"]
        if item["logical_name"] == logical_name
    )
    return json.loads(Path(locator).read_text(encoding="utf-8"))


def _experiment(
    *,
    kernel_identity: str,
    language_bundle_identity: str,
    source_identity: str,
    build_receipt: dict[str, Any],
    base_damage: int,
) -> dict[str, Any]:
    resolved = _member(build_receipt, "resolved-model")
    package_lock = _member(build_receipt, "package-lock")
    rir = _member(build_receipt, "rir-semantic-payload")
    build_record = _member(build_receipt, "build-receipt")
    return {
        "schema_version": "2.0.0",
        "id": "example.rpg-combat-cast.one-action",
        "version": "1.0.0",
        "kernel_identity": kernel_identity,
        "language_bundle_identity": language_bundle_identity,
        "model": {
            "source_identity": source_identity,
            "build_receipt_identity": build_record["content_identity"],
            "resolved_model_identity": resolved["content_identity"],
            "package_lock_identity": package_lock["content_identity"],
            "rir_identity": rir["content_identity"],
        },
        "runtime": {
            "profile": "rpg.exact-int64-event-v1",
            "required_evaluator": {
                "operation_kinds": ["event-program"],
                "instruction_nodes": [
                    "add",
                    "constant",
                    "draw",
                    "if",
                    "less-than-or-equal",
                    "maximum",
                    "multiply",
                    "precondition-greater-than-or-equal",
                    "subtract",
                    "subtract-state",
                ],
                "effects": [
                    "event.commit",
                    "metric.observe",
                    "rng.named-stream",
                    "snapshot.commit",
                ],
                "numeric_policies": ["exact-int64"],
                "rng_algorithms": ["splitmix64-v1"],
            },
        },
        "seed": {"algorithm": "splitmix64-v1", "value": 20260726},
        "external_inputs": [],
        "scenarios": [
            {
                "id": "one-cast",
                "operation": "rpg.combat.cast-v1",
                "values": [
                    {"name": "actor_mana", "value": 30},
                    {"name": "action_cost", "value": 8},
                    {"name": "accuracy", "value": 85},
                    {"name": "base_damage", "value": base_damage},
                    {"name": "critical_threshold", "value": 0},
                    {"name": "target_defense", "value": 6},
                    {"name": "target_health", "value": 100},
                ],
                "named_streams": ["critical", "hit"],
                "terminal_condition": {"kind": "event-count", "maximum": 1},
            }
        ],
        "metrics": [
            {
                "id": "damage_dealt",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "event",
                    "name": "cast-resolved",
                    "member": "damage",
                },
                "target": {"minimum": 1, "maximum": 1000},
            },
            {
                "id": "target_health_remaining",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": "target_health",
                },
                "target": {"minimum": 0, "maximum": 99},
            },
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }


def test_public_rpg_tuning_loop_changes_trace_and_metric_explainably(tmp_path, run_cli):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    model_out = tmp_path / "resolved-model.json"

    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(model_out),
            "--invocation-key",
            "1" * 64,
        ]
    )

    assert (build_exit, build_stderr) == (0, ""), (
        build_stdout,
        build_stderr,
    )
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    source_identity = content_identity("model-source-package-v2", source_value)
    first_spec = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=source_identity,
        build_receipt=build_receipt,
        base_damage=24,
    )
    first_path = tmp_path / "experiment-24.json"
    first_path.write_text(json.dumps(first_spec), encoding="utf-8")

    check_exit, check_stdout, check_stderr = run_cli(
        ["experiment", "check", str(first_path)]
    )

    assert (check_exit, check_stderr) == (0, ""), check_stdout
    assert json.loads(check_stdout)["checked"] is True

    first_exit, first_stdout, first_stderr = run_cli(
        [
            "experiment",
            "run",
            str(first_path),
            "--out",
            str(tmp_path / "evaluation-24.json"),
            "--invocation-key",
            "2" * 64,
        ]
    )

    assert (first_exit, first_stderr) == (0, "")
    first_receipt = json.loads(first_stdout)
    first_trace = _member(first_receipt, "event-trace")
    first_metrics = _member(first_receipt, "metric-dataset")
    assert first_trace["events"][0]["operation"] == "rpg.combat.cast-v1"
    assert (
        next(
            item["integer"]
            for item in first_trace["events"][0]["facts"]
            if item["name"] == "base_damage"
        )
        == 24
    )
    first_damage = next(
        sample["value"]
        for sample in first_metrics["samples"]
        if sample["metric"] == "damage_dealt"
    )

    tuned_spec = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=source_identity,
        build_receipt=build_receipt,
        base_damage=40,
    )
    tuned_path = tmp_path / "experiment-40.json"
    tuned_path.write_text(json.dumps(tuned_spec), encoding="utf-8")
    tuned_exit, tuned_stdout, tuned_stderr = run_cli(
        [
            "experiment",
            "run",
            str(tuned_path),
            "--out",
            str(tmp_path / "evaluation-40.json"),
            "--invocation-key",
            "3" * 64,
        ]
    )

    assert (tuned_exit, tuned_stderr) == (0, "")
    tuned_receipt = json.loads(tuned_stdout)
    tuned_trace = _member(tuned_receipt, "event-trace")
    tuned_metrics = _member(tuned_receipt, "metric-dataset")
    tuned_damage = next(
        sample["value"]
        for sample in tuned_metrics["samples"]
        if sample["metric"] == "damage_dealt"
    )
    assert (
        next(
            item["integer"]
            for item in tuned_trace["events"][0]["facts"]
            if item["name"] == "base_damage"
        )
        == 40
    )
    assert tuned_damage > first_damage
    assert (
        tuned_trace["content_identity"] != first_trace["content_identity"]
        and tuned_metrics["content_identity"] != first_metrics["content_identity"]
    )


def test_completed_negative_judgment_publishes_only_typed_verdict_set(
    tmp_path, run_cli
):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "4" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["metrics"][0]["target"] = {"minimum": 100, "maximum": 1000}
    spec_path = tmp_path / "negative-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(tmp_path / "negative-evaluation.json"),
            "--invocation-key",
            "5" * 64,
        ]
    )

    assert (exit_code, stderr) == (1, "")
    result = json.loads(stdout)
    assert result["outcome"] == "rejected"
    assert result["failed_metrics"] == ["damage_dealt"]
    receipt = result["artifact_set"]
    logical_names = {item["logical_name"] for item in receipt["member_locators"]}
    assert logical_names == {
        "evaluator-capability-manifest",
        "event-trace",
        "experiment-verdict",
        "metric-dataset",
        "reproduction-receipt",
        "resolved-runtime-profile",
        "snapshot-series",
    }
    assert "evaluation-run" not in logical_names
    verdict = _member(receipt, "experiment-verdict")
    assert verdict["outcome"] == "rejected"
    assert verdict["failed_metrics"] == ["damage_dealt"]


def test_evaluation_refusal_publishes_no_completed_outcome_artifacts(tmp_path, run_cli):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
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
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["metrics"][0]["observation"]["member"] = "missing_damage"
    spec_path = tmp_path / "unevaluable-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    out = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(out),
            "--invocation-key",
            "7" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "evaluation"
    assert [item["code"] for item in error["diagnostics"]] == [
        "rpg.evaluation_observation_unavailable"
    ]
    assert not out.exists()
    assert "artifact_set" not in error


def test_runtime_refusal_publishes_only_complete_terminal_audit_set(tmp_path, run_cli):
    source_value = _rpg_model_source()
    source = tmp_path / "rpg-model.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    build_exit, build_stdout, build_stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "8" * 64,
        ]
    )
    assert (build_exit, build_stderr) == (0, "")
    build_receipt = json.loads(build_stdout)
    build_record = _member(build_receipt, "build-receipt")
    specification = _experiment(
        kernel_identity=build_record["kernel_identity"],
        language_bundle_identity=build_record["language_bundle_identity"],
        source_identity=content_identity("model-source-package-v2", source_value),
        build_receipt=build_receipt,
        base_damage=24,
    )
    specification["runtime"]["required_evaluator"]["instruction_nodes"].append(
        "host-call"
    )
    spec_path = tmp_path / "runtime-refusal-experiment.json"
    spec_path.write_text(json.dumps(specification), encoding="utf-8")
    out = tmp_path / "runtime-terminal-audit.json"

    exit_code, stdout, stderr = run_cli(
        [
            "experiment",
            "run",
            str(spec_path),
            "--out",
            str(out),
            "--invocation-key",
            "9" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "runtime"
    assert [item["code"] for item in error["diagnostics"]] == [
        "rpg.runtime_capability_unsupported"
    ]
    receipt = error["terminal_audit"]
    logical_names = {item["logical_name"] for item in receipt["member_locators"]}
    assert logical_names == {
        "evaluator-capability-manifest",
        "reproduction-receipt",
        "resolved-runtime-profile",
        "runtime-terminal-audit",
    }
    assert not logical_names & {
        "evaluation-run",
        "experiment-verdict",
        "metric-dataset",
        "snapshot-series",
    }
    audit = _member(receipt, "runtime-terminal-audit")
    assert audit["committed_trace_prefix"] == []
    assert audit["refusing_event"] == {
        "index": 0,
        "operation": "rpg.combat.cast-v1",
        "reason": "rpg.runtime_capability_unsupported",
    }
    assert audit["rollback"]["committed"] is False
    assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
    assert audit["diagnostic"]["stage"] == "runtime"
    assert out.exists()
