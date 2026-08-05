"""Conformance fixtures for the Experiment CLI surface."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from gda_balancing.domain.experiment import derive_scenario_program_requirements
from gda_balancing.interfaces.cli.model_build import (
    ModelBuildInput,
    ModelBuildResult,
    run_model_build,
)
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex


def prepare_valid_experiment(root: Path, token: int) -> str:
    """Materialize conformance from package-owned source and runtime vectors."""
    context = packaged_authority_context()
    language_bundle = cast(LanguageBundleIndex, context.language_bundle)
    vector_set = next(
        row
        for row in language_bundle.package_conformance_vector_sets
        if row["package_id"] == "game.combat" and row["package_version"] == "2.1.0"
    )
    vectors = {row["id"]: row for row in vector_set["vector_definitions"]}
    source_fixture = vectors["game.combat.model-binding.positive"]["source_fixture"]
    runtime_vector = vectors["game.combat.cast.positive"]
    if source_fixture["mode"] != "literal":
        raise RuntimeError("Experiment conformance source fixture is not literal")
    source_value = deepcopy(source_fixture["source"])
    source = root / f"experiment-model-{token}.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    built = run_model_build(
        ModelBuildInput(
            source=str(source),
            out=str(root / f"experiment-model-{token}-out.json"),
            invocation_key=f"{token:064x}",
        )
    )
    if not isinstance(built, ModelBuildResult):
        raise RuntimeError("Experiment conformance prerequisite was refused")
    receipt = built.model_dump(mode="json")

    def member(logical_name: str) -> dict[str, Any]:
        locator = next(
            row["locator"]
            for row in receipt["member_locators"]
            if row["logical_name"] == logical_name
        )
        return json.loads(Path(locator).read_text(encoding="utf-8"))

    build = member("build-receipt")
    lock = member("package-lock")
    resolved = member("resolved-model")
    rir = member("rir-semantic-payload")
    entrypoint = next(
        row
        for row in rir["entrypoints"]
        if row["operation"]["id"] == runtime_vector["operation"]
    )
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in rir["selected_semantics"]["operations"]
    }
    operation = operations[entrypoint["operation"]["id"]]
    rng_algorithm = context.kernel["meta_format"]["runtime_program"]["named_rng"][
        "algorithm"
    ]
    requirements, named_streams = derive_scenario_program_requirements(
        rir,
        entrypoint["id"],
        operation["runtime_profile"],
        rng_algorithm,
    )
    targets_by_port = {
        row["port"]["name"]: row["operand"]["symbol"]
        for row in entrypoint["arguments"]
        if row["operand"]["kind"] == "symbol"
    }
    assigned: dict[tuple[str, str, str], tuple[dict[str, str], int]] = {}
    for value in runtime_vector["input"]["values"]:
        target = targets_by_port[value["name"]]
        key = (target["model"], target["module"], target["name"])
        previous = assigned.get(key)
        if previous is not None and previous[1] != value["value"]:
            raise RuntimeError(
                "Package vector assigns conflicting values to one Model symbol"
            )
        assigned[key] = (target, value["value"])
    assignments = [
        {"target": target, "value": value}
        for target, value in (assigned[key] for key in sorted(assigned))
    ]
    result = entrypoint["result"]
    if result["kind"] != "symbol":
        raise RuntimeError("Experiment conformance entrypoint result is not observable")
    specification = {
        "schema_version": "2.0.0",
        "id": f"{source_value['manifest']['id']}.conformance",
        "version": "1.0.0",
        "kernel_identity": build["kernel_identity"],
        "language_bundle_identity": build["language_bundle_identity"],
        "model": {
            "source_identity": build["source_identity"],
            "build_receipt_identity": build["content_identity"],
            "resolved_model_identity": resolved["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
        },
        "runtime": {
            "profile": operation["runtime_profile"],
            "required_evaluator": requirements,
        },
        "seed": {
            "algorithm": rng_algorithm,
            "value": runtime_vector["input"]["seed"],
        },
        "scenarios": [
            {
                "id": runtime_vector["id"],
                "event_plan": [
                    {
                        "kind": "transition-invocation",
                        "root_event_ref": "conformance-entrypoint",
                        "logical_time": 0,
                        "priority": 0,
                        "entrypoint": entrypoint["id"],
                        "payload": [],
                    }
                ],
                "assignments": assignments,
                "named_streams": named_streams,
                "terminal_condition": {"kind": "event-count", "maximum": 1},
            }
        ],
        "metrics": [
            {
                "id": "damage",
                "kind": "scalar",
                "unit": "1",
                "dimensions": [],
                "window": {"kind": "scenario", "name": "terminal-event"},
                "aggregation": "single",
                "replication": {"unit": "scenario"},
                "missing": "refuse",
                "censoring": "none",
                "observation": {
                    "source": "event",
                    "name": operation["default_outcome"],
                    "member": result["symbol"]["name"],
                },
                "target": {"minimum": 0, "maximum": 1000},
            }
        ],
        "acceptance": {"policy": "all-metrics-within-target"},
    }
    return json.dumps(specification)


def prepare_verdict_experiment(root: Path, token: int) -> str:
    """Materialize a valid Experiment whose metric target is rejected."""
    specification = json.loads(prepare_valid_experiment(root, token))
    specification["metrics"][0]["target"] = {
        "minimum": 1000,
        "maximum": 1000,
    }
    return json.dumps(specification)
