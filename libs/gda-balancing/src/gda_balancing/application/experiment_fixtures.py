"""Author Experiment conformance fixtures from admitted package vectors."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from gda_balancing.application.model_build import (
    MODEL_BUILD_ARTIFACT_SET,
    ModelBuildReceipt,
    build_model,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes
from gda_balancing.domain.experiment import derive_scenario_program_requirements
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex


def _prepare_experiment(
    root: Path,
    token: int,
    *,
    model_build_descriptor_identity: str,
    runtime_refusal: bool,
) -> str:
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
    if runtime_refusal:
        target_defense = next(
            row
            for module in source_value["modules"]
            for row in module["symbols"]
            if row["symbol"] == "target_defense"
        )
        target_defense["domain"]["minimum"] = -(1 << 63)
    source = root / f"experiment-model-{token}.json"
    source.write_text(json.dumps(source_value), encoding="utf-8")
    built = build_model(
        str(source),
        str(root / f"experiment-model-{token}-out.json"),
        f"{token:064x}",
        model_build_descriptor_identity,
        MODEL_BUILD_ARTIFACT_SET,
    )
    if not isinstance(built, ModelBuildReceipt):
        raise RuntimeError("Experiment conformance prerequisite was refused")
    receipt = built.root
    (root / f"experiment-model-{token}-receipt.json").write_bytes(
        canonical_bytes(cast(JsonValue, receipt))
    )

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
    if runtime_refusal:
        target_defense_assignment = next(
            row for row in assignments if row["target"]["name"] == "target_defense"
        )
        target_defense_assignment["value"] = -(1 << 63)
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


def prepare_valid_experiment(
    root: Path,
    token: int,
    *,
    model_build_descriptor_identity: str,
) -> str:
    """Materialize one Experiment that completes successfully."""
    return _prepare_experiment(
        root,
        token,
        model_build_descriptor_identity=model_build_descriptor_identity,
        runtime_refusal=False,
    )


def prepare_runtime_refusal_experiment(
    root: Path,
    token: int,
    *,
    model_build_descriptor_identity: str,
) -> str:
    """Materialize one Experiment that refuses after runtime dispatch."""
    return _prepare_experiment(
        root,
        token,
        model_build_descriptor_identity=model_build_descriptor_identity,
        runtime_refusal=True,
    )


def prepare_verdict_experiment(
    root: Path,
    token: int,
    *,
    model_build_descriptor_identity: str,
) -> str:
    """Materialize a valid Experiment whose metric target is rejected."""
    specification = json.loads(
        prepare_valid_experiment(
            root,
            token,
            model_build_descriptor_identity=model_build_descriptor_identity,
        )
    )
    specification["metrics"][0]["target"] = {
        "minimum": 1000,
        "maximum": 1000,
    }
    return json.dumps(specification)
