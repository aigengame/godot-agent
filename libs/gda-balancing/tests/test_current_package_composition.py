"""The current package union composes progression and periodic Effects publicly."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from http_service_support import running_execution_http_service


_ROOT = Path(__file__).parents[1]
_EXAMPLE = _ROOT / "examples/schema2/progression-periodic-effect"


def _cli(*arguments: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "gda_balancing", *arguments],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stderr == ""
    return json.loads(result.stdout)


def _members(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        row["logical_name"]: json.loads(Path(row["locator"]).read_text())
        for row in receipt["member_locators"]
    }


@pytest.mark.parametrize(
    ("level", "threshold", "terminal_health"), [(5, 85, 70), (4, 68, 36)]
)
def test_progression_drives_periodic_effect_through_cli_and_http(
    tmp_path: Path, level: int, threshold: int, terminal_health: int
) -> None:
    source = json.loads((_EXAMPLE / "model-source.json").read_text())
    experiment = json.loads((_EXAMPLE / "experiment.json").read_text())
    symbols = {row["symbol"]: row for row in source["modules"][0]["symbols"]}
    assert symbols["magnitude_threshold"]["role"] == "derived"
    assert symbols["magnitude_threshold"]["value_policy"] == {"mode": "none"}
    assert {
        row["target"]["name"] for row in experiment["scenarios"][0]["assignments"]
    } == {"target_health", "level", "damage_per_level"}

    build = _members(
        _cli(
            "model",
            "build",
            str(_EXAMPLE / "model-source.json"),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "01" * 32,
        )
    )["build-receipt"]
    # The maintained source and checked-in Experiment bind exactly; no test-time
    # compatibility rebinding is allowed to hide a stale public example.
    assert experiment["kernel_identity"] == build["kernel_identity"]
    assert experiment["language_bundle_identity"] == build["language_bundle_identity"]
    assert experiment["model"] == {
        key: build["content_identity" if key == "build_receipt_identity" else key]
        for key in experiment["model"]
    }

    for assignment in experiment["scenarios"][0]["assignments"]:
        if assignment["target"]["name"] == "level":
            assignment["value"] = level
    for metric in experiment["metrics"]:
        if metric["id"] == "target_health_remaining":
            metric["target"] = {"minimum": terminal_health, "maximum": terminal_health}
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(experiment))
    cli_artifacts = _members(
        _cli(
            "experiment",
            "run",
            str(path),
            "--out",
            str(tmp_path / "run"),
            "--invocation-key",
            "02" * 32,
        )
    )
    events = [
        event
        for event in cli_artifacts["event-trace"]["events"]
        if event["observation"] is None
    ]
    assert [event["outcome"]["id"] for event in events] == [
        "applied",
        "ticked",
        "ticked",
        "expired",
    ]
    assert {fact["name"]: fact["integer"] for fact in events[0]["facts"]}[
        "magnitude_threshold"
    ] == threshold
    formula = events[0]["formula_evaluations"][0]
    assert {row["parameter"]: row["value"] for row in formula["arguments"]} == {
        "current_value": 100,
        "threshold": threshold,
    }
    assert formula["result"] == 100 - threshold
    assert [
        {row["name"]: row["value"] for row in event["state_after"]}["target_health"]
        for event in events
    ] == [100, threshold, terminal_health, terminal_health]
    samples = cli_artifacts["metric-dataset"]["samples"]
    assert (
        next(
            row["value"]
            for row in samples
            if row["metric"] == "target_health_remaining"
        )
        == terminal_health
    )
    assert all(row["within_target"] for row in samples)

    with running_execution_http_service(
        command_prefix=[sys.executable, "-m", "gda_balancing"],
        cwd=_ROOT,
    ) as service:
        created = service.create_session(source, experiment)
        assert created["outcome"] == "success"
        outcome = service.run(created["session_id"], created["revision_id"])
        assert outcome["outcome"] == "success"
        assert outcome["artifacts"] == cli_artifacts
        assert service.delete_session(created["session_id"])["outcome"] == "success"
