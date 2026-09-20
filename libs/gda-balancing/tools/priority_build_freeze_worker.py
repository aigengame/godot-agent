#!/usr/bin/env python3
"""Generate independent B witnesses and exchange them with installed-wheel A."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import gda_balancing

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


def _prepare(inputs: Path, renamed_case: Path | None) -> None:
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
    if renamed_case is not None:
        supplied = json.loads(renamed_case.read_text())
        required = {
            "authority",
            "kernel",
            "language_bundle",
            "source",
            "mapping",
            "experiments",
        }
        if (
            set(supplied) != required
            or supplied["authority"] != "renamed"
            or not isinstance(supplied["mapping"], dict)
            or not supplied["mapping"]
            or set(supplied["experiments"]) != {"baseline", "variant"}
        ):
            raise ValueError(
                "a renamed case must supply its authored graph, non-empty mapping, "
                "source, and baseline/variant Experiment templates"
            )
        authored["authorities"].append(supplied)
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
        expected_metric = 7 if key[1] == "baseline" else 0
        if samples != {"resolved-power": expected_metric}:
            raise AssertionError(f"unexpected priority result: {samples}")
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

    renamed_present = "renamed" in matrix
    result = {
        "matrix": matrix,
        "a_identity": response["identity"],
        "b_identity": observed_b_identity,
        "a_invocations": response["invocations"],
        "b_package_origin": str(Path(gda_balancing.__file__).resolve()),
        "b_harness_origin": str(Path(__file__).resolve()),
        "b_executable": str(Path(sys.executable).resolve()),
        "b_sys_path": list(sys.path),
        "b_import_origins": sorted(
            {
                str(Path(module.__file__).resolve())
                for module in tuple(sys.modules.values())
                if getattr(module, "__file__", None) and Path(module.__file__).exists()
            }
        ),
        "renamed_case_hook": {
            "status": "exercised" if renamed_present else "awaiting-supplied-case",
            "option": "--renamed-case",
            "contract": (
                "authored Kernel/LDB graph projection, non-empty rename mapping, "
                "renamed Model Source, and baseline/variant Experiment templates"
            ),
        },
    }
    (output / "result.json").write_bytes(_encoded(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("inputs", type=Path)
    prepare.add_argument("--renamed-case", type=Path)
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
        _prepare(args.inputs, args.renamed_case)
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
