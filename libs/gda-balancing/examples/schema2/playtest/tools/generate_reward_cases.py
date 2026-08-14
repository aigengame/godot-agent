#!/usr/bin/env python3
"""Generate player-facing Reward Run cases through the public CLI.

This tool deliberately imports no gda-balancing Python module. It runs the same
public Model and Experiment commands that a designer uses, then projects only
the feature values that the Godot product needs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any


PLAYTEST_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parents[4]
EXAMPLE_DIR = PACKAGE_DIR / "examples" / "schema2" / "roguelike-reward-build"
GENERATED_DIR = PLAYTEST_DIR / "generated"

_REWARD_NAMES = {
    "steady_guard": "Iron Guard",
    "volatile_crown": "Storm Crown",
}
_ITEM_NAMES = {
    "starter_blade": "Training Blade",
    **_REWARD_NAMES,
}


def _run_cli(
    cli: str,
    environment: dict[str, str],
    *arguments: str,
) -> dict[str, Any]:
    completed = subprocess.run(
        [cli, *arguments],
        cwd=PACKAGE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"gda-balancing returned invalid JSON for {' '.join(arguments)}:\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        ) from error
    if completed.returncode != 0 or "error" in payload:
        raise RuntimeError(
            f"gda-balancing failed for {' '.join(arguments)}:\n"
            f"{json.dumps(payload, indent=2)}\nstderr: {completed.stderr}"
        )
    return payload


def _members(receipt: dict[str, Any]) -> dict[str, Path]:
    return {
        row["logical_name"]: Path(row["locator"]) for row in receipt["member_locators"]
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fact(event: dict[str, Any], name: str) -> Any:
    row = next(item for item in event["facts"] if item["name"] == name)
    if row["kind"] == "structured":
        return row["value"]["value"]
    return row["integer"]


def _player_case(
    *,
    trial_id: str,
    title: str,
    reference: str,
    trace: dict[str, Any],
) -> dict[str, Any]:
    transitions = [event for event in trace["events"] if event["operation"]]
    reward = _fact(transitions[0], "reward_result")
    build = _fact(transitions[1], "build_result")
    reward_key = reward["selected"]["key"]
    previous_key = build["previous"]["key"]
    selected_key = build["selected"]["key"]
    if reward_key != selected_key:
        raise RuntimeError("Reward and build results disagree on the selected item")
    try:
        reward_name = _REWARD_NAMES[reward_key]
        previous_name = _ITEM_NAMES[previous_key]
    except KeyError as error:
        raise RuntimeError(f"Missing player-facing name for {error.args[0]}") from error
    return {
        "build": {
            "equipped_item": reward_name,
            "power_after": build["power_after"],
            "power_before": build["power_before"],
            "previous_item": previous_name,
        },
        "id": trial_id,
        "playtest_provenance_reference": reference,
        "reward": {
            "key": reward_key,
            "name": reward_name,
            "rarity": reward["rarity"],
        },
        "title": title,
    }


def _copy_member(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _identity(path: Path) -> str:
    return _read_json(path)["content_identity"]


def _artifact(identity: str, locator: str) -> dict[str, str]:
    return {"identity": identity, "locator": locator}


def _generate_into(target: Path, cli: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gda-balancing-playtest-") as temporary:
        temporary_dir = Path(temporary)
        environment = os.environ.copy()
        environment["GDA_BALANCING_STORE_DIR"] = str(temporary_dir / "store")
        environment["GDA_BALANCING_ANCHOR_KEY"] = "a" * 64

        source_path = EXAMPLE_DIR / "model-source.json"
        experiment_path = EXAMPLE_DIR / "experiment.json"
        _run_cli(cli, environment, "model", "check", str(source_path))
        model_receipt = _run_cli(
            cli,
            environment,
            "model",
            "build",
            str(source_path),
            "--out",
            str(temporary_dir / "model"),
            "--invocation-key",
            "c" * 64,
        )
        model_members = _members(model_receipt)

        baseline = _read_json(experiment_path)
        tuned = deepcopy(baseline)
        tuned["id"] = "roguelike.reward-build-feedback.lower-rare-weight"
        next(
            row
            for row in tuned["scenarios"][0]["assignments"]
            if row["target"]["name"] == "rare_weight"
        )["value"] = 2
        tuned_path = temporary_dir / "tuned-experiment.json"
        _write_json(tuned_path, tuned)

        runs: list[dict[str, Any]] = []
        for run_id, title, reference, specification, invocation_key in (
            (
                "trial-one",
                "Trial 1",
                "reward-run-1",
                experiment_path,
                "b" * 64,
            ),
            (
                "trial-two",
                "Trial 2",
                "reward-run-2",
                tuned_path,
                "d" * 64,
            ),
        ):
            _run_cli(cli, environment, "experiment", "check", str(specification))
            receipt = _run_cli(
                cli,
                environment,
                "experiment",
                "run",
                str(specification),
                "--out",
                str(temporary_dir / f"{run_id}-evaluation.json"),
                "--invocation-key",
                invocation_key,
            )
            members = _members(receipt)
            trace = _read_json(members["event-trace"])
            runs.append(
                {
                    "case": _player_case(
                        trial_id=run_id,
                        title=title,
                        reference=reference,
                        trace=trace,
                    ),
                    "members": members,
                    "reference": reference,
                    "specification": specification,
                    "trace": trace,
                }
            )

        _write_json(
            target / "reward_cases.json",
            {
                "schema_version": 1,
                "trials": [run["case"] for run in runs],
            },
        )

        model_evidence = target / "evidence" / "model"
        for name in ("build-receipt", "resolved-model"):
            _copy_member(model_members[name], model_evidence / f"{name}.json")

        provenance_entries: dict[str, Any] = {}
        model_record = _read_json(model_members["build-receipt"])
        for run in runs:
            run_id = run["case"]["id"]
            run_evidence = target / "evidence" / run_id
            members = run["members"]
            for name in (
                "evaluation-run",
                "event-trace",
                "metric-dataset",
                "reproduction-receipt",
            ):
                _copy_member(members[name], run_evidence / f"{name}.json")
            if run_id == "trial-two":
                _copy_member(run["specification"], run_evidence / "experiment.json")

            specification_locator = (
                "../../roguelike-reward-build/experiment.json"
                if run_id == "trial-one"
                else f"evidence/{run_id}/experiment.json"
            )
            provenance_entries[run["reference"]] = {
                "experiment": _artifact(
                    run["trace"]["experiment_identity"], specification_locator
                ),
                "metrics": _artifact(
                    _identity(members["metric-dataset"]),
                    f"evidence/{run_id}/metric-dataset.json",
                ),
                "model": {
                    "build_receipt": _artifact(
                        model_record["content_identity"],
                        "evidence/model/build-receipt.json",
                    ),
                    "resolved_model": _artifact(
                        model_record["resolved_model_identity"],
                        "evidence/model/resolved-model.json",
                    ),
                    "source": _artifact(
                        model_record["source_identity"],
                        "../../roguelike-reward-build/model-source.json",
                    ),
                },
                "rng_observation": _artifact(
                    _identity(members["reproduction-receipt"]),
                    f"evidence/{run_id}/reproduction-receipt.json",
                ),
                "runtime": {
                    "result": _artifact(
                        _identity(members["evaluation-run"]),
                        f"evidence/{run_id}/evaluation-run.json",
                    ),
                    "trace": _artifact(
                        _identity(members["event-trace"]),
                        f"evidence/{run_id}/event-trace.json",
                    ),
                },
            }

        _write_json(
            target / "playtest_provenance.json",
            {"entries": provenance_entries, "schema_version": 1},
        )


def _tree_digest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in a temporary directory and fail if checked-in files differ",
    )
    parser.add_argument(
        "--cli",
        default=os.environ.get("GDA_BALANCING_CLI", "gda-balancing"),
        help="public gda-balancing command to execute",
    )
    arguments = parser.parse_args()
    cli = shutil.which(arguments.cli)
    if cli is None:
        parser.error(f"command not found: {arguments.cli}")

    with tempfile.TemporaryDirectory(prefix="gda-balancing-playtest-output-") as tmp:
        staged = Path(tmp) / "generated"
        _generate_into(staged, cli)
        if arguments.check:
            actual = _tree_digest(GENERATED_DIR)
            expected = _tree_digest(staged)
            if actual != expected:
                missing = sorted(expected.keys() - actual.keys())
                stale = sorted(actual.keys() - expected.keys())
                changed = sorted(
                    key
                    for key in expected.keys() & actual.keys()
                    if expected[key] != actual[key]
                )
                print(
                    json.dumps(
                        {"changed": changed, "missing": missing, "stale": stale},
                        indent=2,
                    )
                )
                return 1
            print(json.dumps({"checked": len(actual), "status": "current"}))
            return 0

        if GENERATED_DIR.exists():
            shutil.rmtree(GENERATED_DIR)
        shutil.copytree(staged, GENERATED_DIR)
        print(json.dumps({"generated": len(_tree_digest(GENERATED_DIR))}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
