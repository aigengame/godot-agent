#!/usr/bin/env python3
"""Generate independent B witnesses and exchange them with installed-wheel A."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import gda_balancing

from priority_extension_proof_support import build_priority_case
from priority_protocol_support import authorities, source, specification
from schema2_model_companions_independent_support import (
    reference_admits_model_artifacts,
    reference_model_artifacts,
    reference_model_producer,
)
from schema2_runtime_independent_support import (
    _build_identity as reference_runtime_build_identity,
    reference_admits_runtime_artifacts,
    reference_runtime_artifacts,
)
from test_schema2_model_lowerer_conformance import (
    ModelSourceContext,
    _reference_check_source,
)


_MODEL_ROLES = {
    "build-receipt",
    "capability-manifest",
    "debug-map",
    "model-explanation",
    "package-lock",
    "resolution-receipt",
    "resolved-model",
    "rir-semantic-payload",
}
_RUNTIME_ROLES = {
    "evaluation-run",
    "evaluator-capability-manifest",
    "event-trace",
    "metric-dataset",
    "resolved-runtime-profile",
    "snapshot-series",
}


def _encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _bundle_payload(bundle: Any) -> dict[str, Any]:
    return {
        "projection": dict(bundle),
        "root": bundle.root,
        "package_releases": bundle.package_releases,
        "package_conformance_vector_sets": (bundle.package_conformance_vector_sets),
        "root_byte_size": bundle.root_byte_size,
        "package_byte_sizes": list(bundle.package_byte_sizes),
        "vector_set_byte_sizes": list(bundle.vector_set_byte_sizes),
    }


def _operation_id(value: str | dict[str, Any], reverse: dict[str, str]) -> str:
    identity = value["id"] if isinstance(value, dict) else value
    return reverse.get(identity, identity)


def _priority_boundary_observation(
    runtime: dict[str, Any], mapping: dict[str, str]
) -> list[dict[str, Any]]:
    """Project the fixed witness's ordered transition and pending-state boundary."""
    reverse = {renamed: original for original, renamed in mapping.items()}
    result: list[dict[str, Any]] = []
    for event in runtime["event-trace"]["events"]:
        if event["operation"] is None:
            continue
        state = {row["name"]: row["value"] for row in event["state_after"]}

        def value(name: str) -> Any:
            member = state[name]
            if isinstance(member, dict) and "type" in member and "value" in member:
                return member["value"]
            return member

        result.append(
            {
                "operation": _operation_id(event["operation"], reverse),
                "ordering_key": event["ordering_key"],
                "call_sequence": [
                    _operation_id(call["operation"], reverse) for call in event["calls"]
                ],
                "scheduled": [
                    {
                        "operation": _operation_id(schedule["operation"], reverse),
                        "ordering_key": schedule["ordering_key"],
                    }
                    for schedule in event["schedules"]
                ],
                "pending_state": [
                    value("root_id"),
                    value("next_id"),
                    value("ids"),
                    [row["target"] for row in value("counters")],
                    value("priority"),
                    value("passes"),
                    value("window_open"),
                    value("canceled_ids"),
                    value("final_power"),
                    value("status"),
                ],
            }
        )
    return result


def _expected_priority_boundaries(variant: str) -> list[dict[str, Any]]:
    operations = ["open", "respond"]
    states: list[list[Any]] = [
        [1, 1, [], [], 1, 0, 1, [], 0, "pending"],
        [1, 2, [2], [1], 0, 0, 1, [], 0, "pending"],
    ]
    if variant == "variant":
        operations += ["pass", "pass", "resolve"]
        states += [
            [1, 2, [2], [1], 1, 1, 1, [], 0, "pending"],
            [1, 2, [2], [1], 0, 2, 0, [], 0, "pending"],
            [1, 2, [2], [1], 0, 2, 0, [1], 0, "canceled"],
        ]
    else:
        operations += ["respond", "pass", "pass", "resolve"]
        states += [
            [1, 3, [2, 3], [1, 2], 1, 0, 1, [], 0, "pending"],
            [1, 3, [2, 3], [1, 2], 0, 1, 1, [], 0, "pending"],
            [1, 3, [2, 3], [1, 2], 1, 2, 0, [], 0, "pending"],
            [1, 3, [2, 3], [1, 2], 1, 2, 0, [2], 7, "resolved"],
        ]
    final_enqueue = 8 if variant == "variant" else 10
    enqueue_sequences = [*range(1, final_enqueue, 2), final_enqueue]
    logical_times = [*range(len(operations) - 1), 7]
    call_sequences = [
        ["propose"]
        if operation == "open"
        else ["append-counter"]
        if operation == "respond"
        else []
        for operation in operations
    ]
    scheduled = [[] for _ in operations]
    scheduled[-2] = [
        {
            "operation": "resolve",
            "ordering_key": {
                "logical_time": 7,
                "phase": "transition",
                "priority": 0,
                "enqueue_sequence": final_enqueue,
            },
        }
    ]
    return [
        {
            "operation": operation,
            "ordering_key": {
                "logical_time": logical_time,
                "phase": "transition",
                "priority": 0,
                "enqueue_sequence": enqueue_sequence,
            },
            "call_sequence": calls,
            "scheduled": schedules,
            "pending_state": state,
        }
        for operation, logical_time, enqueue_sequence, calls, schedules, state in zip(
            operations,
            logical_times,
            enqueue_sequences,
            call_sequences,
            scheduled,
            states,
            strict=True,
        )
    ]


def _language_bundle(value: dict[str, Any]):
    from gda_balancing.domain.authority.graph import LanguageBundleIndex

    return LanguageBundleIndex(
        value["projection"],
        root=value["root"],
        package_releases=value["package_releases"],
        package_conformance_vector_sets=value["package_conformance_vector_sets"],
        root_byte_size=value["root_byte_size"],
        package_byte_sizes=value["package_byte_sizes"],
        vector_set_byte_sizes=value["vector_set_byte_sizes"],
    )


def _identity() -> dict[str, Any]:
    return {
        "model_producer": reference_model_producer(),
        "runtime_evaluator": reference_runtime_build_identity(),
        "package_origin": str(Path(gda_balancing.__file__).resolve()),
    }


def _prepare(inputs: Path) -> None:
    inputs.mkdir(parents=True, exist_ok=False)
    kernel, language, turn = authorities()
    authored = {
        "authorities": [
            {
                "authority": "original",
                "kernel": kernel,
                "language_bundle": _bundle_payload(language),
                "source": source(turn),
                "mapping": {},
                "experiments": None,
            }
        ]
    }
    (inputs / "authored-cases.json").write_bytes(_encoded(authored))


def _specification(
    authority: dict[str, Any], rir: dict[str, Any], variant: str
) -> dict[str, Any]:
    supplied = authority["experiments"]
    if supplied is None:
        return specification(rir, variant == "variant")
    result = deepcopy(supplied[variant])
    result["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    return result


def _a_exchange(
    a_python: Path,
    a_driver: Path,
    a_site_packages: Path,
    forbidden_source_root: Path,
    request: Path,
    output: Path,
    expected_identity: Path,
) -> dict[str, Any]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONHOME", "PYTHONPATH"}
    }
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "GDA_BALANCING_STORE_DIR": str(output / "store"),
            "GDA_BALANCING_ANCHOR_KEY": "a5" * 32,
        }
    )
    result = subprocess.run(
        [
            str(a_python),
            str(a_driver),
            "exercise",
            "--request",
            str(request),
            "--output",
            str(output),
            "--expected-identity",
            str(expected_identity),
            "--site-packages",
            str(a_site_packages),
            "--forbidden-source-root",
            str(forbidden_source_root),
        ],
        cwd=output.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=420,
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"installed A driver failed ({result.returncode}): "
            f"{result.stdout[-4000:]} {result.stderr[-4000:]}"
        )
    return json.loads((output / "a-response.json").read_text())


def _exercise(
    inputs: Path,
    output: Path,
    a_python: Path,
    a_driver: Path,
    a_site_packages: Path,
    forbidden_source_root: Path,
) -> dict[str, Any]:
    expected_b_identity = json.loads((inputs / "b-identity.json").read_text())
    observed_b_identity = _identity()
    if observed_b_identity != expected_b_identity:
        raise AssertionError("B build identity changed after the freeze")
    authored_cases = json.loads((inputs / "authored-cases.json").read_text())
    # The caller seals both installed builds and this independent harness before
    # entering exercise. Derive the bounded selected-closure case only after
    # that freeze point.
    renamed_case, selected_closure_proof = build_priority_case(renamed=True)
    if (
        set(renamed_case)
        != {
            "authority",
            "kernel",
            "language_bundle",
            "source",
            "mapping",
            "experiments",
        }
        or renamed_case["authority"] != "renamed"
        or not isinstance(renamed_case["mapping"], dict)
        or not renamed_case["mapping"]
        or set(renamed_case["experiments"]) != {"baseline", "variant"}
    ):
        raise AssertionError("bounded renamed priority case did not close")
    original_case = authored_cases["authorities"][0]
    if _encoded(original_case["kernel"]) != _encoded(renamed_case["kernel"]):
        raise AssertionError("bounded rename changed the Kernel")
    selected_closure_proof["kernel_unchanged"] = True
    authored_cases["authorities"].append(renamed_case)
    request_cases: list[dict[str, Any]] = []
    independent: dict[tuple[str, str], dict[str, Any]] = {}
    for authority in authored_cases["authorities"]:
        kernel = authority["kernel"]
        language = _language_bundle(authority["language_bundle"])
        checked = _reference_check_source(authority["source"], kernel, language)
        if not isinstance(checked, ModelSourceContext):
            raise AssertionError(f"B refused supplied Model Source: {checked}")
        all_b_model = reference_model_artifacts(
            checked, producer=expected_b_identity["model_producer"]
        )
        b_model = {
            role: value
            for role, value in all_b_model.items()
            if role != "model-build-command-input"
        }
        if set(b_model) != _MODEL_ROLES:
            raise AssertionError("B did not generate eight Model artifact members")
        rir = b_model["rir-semantic-payload"]
        for variant in ("baseline", "variant"):
            planned = _specification(authority, rir, variant)
            b_runtime = reference_runtime_artifacts(checked, rir, planned)
            if set(b_runtime) != _RUNTIME_ROLES:
                raise AssertionError("B did not generate six Runtime result members")
            if (
                b_runtime["evaluator-capability-manifest"]["evaluator_build_identity"]
                != expected_b_identity["runtime_evaluator"]
            ):
                raise AssertionError("B Runtime artifact build identity drifted")
            key = (authority["authority"], variant)
            independent[key] = {
                "checked": checked,
                "b_model": b_model,
                "b_runtime": b_runtime,
                "specification": planned,
                "mapping": authority["mapping"],
            }
            request_cases.append(
                {
                    "authority": authority["authority"],
                    "variant": variant,
                    "kernel": kernel,
                    "language_bundle": authority["language_bundle"],
                    "source": authority["source"],
                    "specification": planned,
                    "b_model": b_model,
                    "b_runtime": b_runtime,
                }
            )

    output.mkdir(parents=True, exist_ok=True)
    request = output / "a-request.json"
    request.write_bytes(_encoded({"cases": request_cases}))
    response = _a_exchange(
        a_python,
        a_driver,
        a_site_packages,
        forbidden_source_root,
        request,
        output / "a",
        inputs / "a-identity.json",
    )
    if len(response["cases"]) != len(request_cases):
        raise AssertionError("A response did not cover the complete requested matrix")

    matrix: dict[str, dict[str, Any]] = {}
    for a_case in response["cases"]:
        key = (a_case["authority"], a_case["variant"])
        b_case = independent[key]
        a_model = a_case["model_members"]
        a_runtime = a_case["runtime_members"]
        a_producer = {
            "compiler": a_model["build-receipt"]["compiler"],
            "resolver": a_model["resolution-receipt"]["resolver"],
        }
        a_model_with_input = {
            **a_model,
            "model-build-command-input": reference_model_artifacts(
                b_case["checked"], producer=a_producer
            )["model-build-command-input"],
        }
        b_admits_a_model = reference_admits_model_artifacts(
            a_model_with_input,
            b_case["checked"],
            producer=a_producer,
        )
        b_admits_a_runtime = reference_admits_runtime_artifacts(
            b_case["checked"],
            b_case["b_model"]["rir-semantic-payload"],
            b_case["specification"],
            a_runtime,
        )
        for role in _RUNTIME_ROLES - {"evaluator-capability-manifest"}:
            if b_case["b_runtime"][role] != a_runtime[role]:
                raise AssertionError(f"A/B Runtime payload differs at {role}")
        samples = {
            row["metric"]: row["value"]
            for row in b_case["b_runtime"]["metric-dataset"]["samples"]
        }
        target = b_case["specification"]["metrics"][0]["target"]
        if target["minimum"] != target["maximum"]:
            raise AssertionError("priority proof metric target is not exact")
        expected_metric = target["minimum"]
        expected_metric_id = b_case["specification"]["metrics"][0]["id"]
        if samples != {expected_metric_id: expected_metric}:
            raise AssertionError(f"unexpected priority result: {samples}")
        boundary_observation = _priority_boundary_observation(
            b_case["b_runtime"], b_case["mapping"]
        )
        expected_boundaries = _expected_priority_boundaries(key[1])
        if boundary_observation != expected_boundaries:
            raise AssertionError(f"priority boundary behavior drifted for {key}")
        if not all(
            (
                a_case["a_admits_b_model"],
                a_case["a_admits_b_runtime"],
                b_admits_a_model,
                b_admits_a_runtime,
                a_case["model_check"]["checked"],
                a_case["experiment_check"]["checked"],
            )
        ):
            raise AssertionError(f"A/B mutual admission failed for {key}")
        matrix.setdefault(key[0], {})[key[1]] = {
            "metric": expected_metric,
            "boundaries": boundary_observation,
            "model": {
                "member_count": len(a_model),
                "members": sorted(a_model),
                "a_admits_b": a_case["a_admits_b_model"],
                "b_admits_a": b_admits_a_model,
            },
            "runtime": {
                "member_count": len(a_runtime),
                "members": sorted(a_runtime),
                "a_admits_b": a_case["a_admits_b_runtime"],
                "b_admits_a": b_admits_a_runtime,
            },
        }

    for variant in ("baseline", "variant"):
        if (
            matrix["original"][variant]["boundaries"]
            != matrix["renamed"][variant]["boundaries"]
        ):
            raise AssertionError(
                f"renaming changed the priority boundary behavior for {variant}"
            )

    renamed_mapping = next(
        (
            authority["mapping"]
            for authority in authored_cases["authorities"]
            if authority["authority"] == "renamed"
        ),
        None,
    )
    if not isinstance(renamed_mapping, dict):
        raise AssertionError("renamed case has no serialized mapping")
    import_origins = []
    for module in tuple(sys.modules.values()):
        origin = getattr(module, "__file__", None)
        if isinstance(origin, str) and Path(origin).exists():
            import_origins.append(str(Path(origin).resolve()))
    result = {
        "matrix": matrix,
        "a_identity": response["identity"],
        "b_identity": observed_b_identity,
        "a_invocations": response["invocations"],
        "b_package_origin": str(Path(gda_balancing.__file__).resolve()),
        "b_harness_origin": str(Path(__file__).resolve()),
        "b_executable": str(Path(sys.executable).resolve()),
        "b_sys_path": list(sys.path),
        "b_import_origins": sorted(set(import_origins)),
        "selected_closure": {
            "derived_after_build_freeze": True,
            "proof": selected_closure_proof,
            "mapping_member_count": len(renamed_mapping),
            "mapping_sha256": hashlib.sha256(_encoded(renamed_mapping)).hexdigest(),
        },
    }
    (output / "result.json").write_bytes(_encoded(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("inputs", type=Path)
    identify = subparsers.add_parser("identify")
    identify.add_argument("--output", type=Path, required=True)
    exercise = subparsers.add_parser("exercise")
    exercise.add_argument("inputs", type=Path)
    exercise.add_argument("--output", type=Path, required=True)
    exercise.add_argument("--a-python", type=Path, required=True)
    exercise.add_argument("--a-driver", type=Path, required=True)
    exercise.add_argument("--a-site-packages", type=Path, required=True)
    exercise.add_argument("--forbidden-source-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        _prepare(args.inputs)
    elif args.mode == "identify":
        args.output.write_bytes(_encoded(_identity()))
    else:
        _exercise(
            args.inputs,
            args.output,
            args.a_python,
            args.a_driver,
            args.a_site_packages,
            args.forbidden_source_root,
        )
