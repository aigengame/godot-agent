#!/usr/bin/env python3
"""Run priority witnesses through an installed wheel and injected authorities."""

from __future__ import annotations

import argparse
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import sys
from typing import Any

import gda_balancing
from gda_balancing.domain.artifacts import (
    artifacts_by_protocol_role,
    verify_artifact,
)
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.experiment import check_experiment_value
from gda_balancing.domain.experiment_artifacts import (
    validate_experiment_artifact_set,
)
from gda_balancing.domain.model import AdmittedRir, admit_resolved_model, admit_rir
from gda_balancing.domain.model._lowering import _LOWERER_IMPLEMENTATION_IDENTITY
from gda_balancing.domain.model._resolution import _RESOLVER_IMPLEMENTATION_IDENTITY
from gda_balancing.domain.runtime.projections import evaluator_build_identity
from gda_balancing.interfaces.cli.dispatch import dispatch
from gda_balancing.interfaces.cli.experiment_check import experiment_check_descriptor
from gda_balancing.interfaces.cli.experiment_run import experiment_run_descriptor
from gda_balancing.interfaces.cli.model_build import model_build_descriptor
from gda_balancing.interfaces.cli.model_check import model_check_descriptor


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


def _language_bundle(value: dict[str, Any]) -> LanguageBundleIndex:
    return LanguageBundleIndex(
        value["projection"],
        root=value["root"],
        package_releases=value["package_releases"],
        package_conformance_vector_sets=value["package_conformance_vector_sets"],
        root_byte_size=value["root_byte_size"],
        package_byte_sizes=value["package_byte_sizes"],
        vector_set_byte_sizes=value["vector_set_byte_sizes"],
    )


def _identity() -> dict[str, str]:
    return {
        "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
        "resolver": _RESOLVER_IMPLEMENTATION_IDENTITY,
        "evaluator": evaluator_build_identity(),
        "package_origin": str(Path(gda_balancing.__file__).resolve()),
    }


def _gda_module_origins(package_root: Path) -> list[str]:
    origins = sorted(
        {
            str(Path(module.__file__).resolve())
            for name, module in tuple(sys.modules.items())
            if (name == "gda_balancing" or name.startswith("gda_balancing."))
            and getattr(module, "__file__", None)
        }
    )
    outside = [
        origin for origin in origins if not Path(origin).is_relative_to(package_root)
    ]
    if outside:
        raise AssertionError(f"A imported outside installed site-packages: {outside}")
    return origins


def _members(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["logical_name"]: json.loads(Path(row["locator"]).read_text())
        for row in receipt["member_locators"]
    }


def _invoke(
    registry: tuple[Any, ...],
    arguments: list[str],
    *,
    label: str,
    package_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = dispatch(arguments, stdout, stderr, registry=registry)
    if exit_code != 0 or stderr.getvalue():
        raise AssertionError(
            f"installed A refused {label}: {exit_code} "
            f"{stderr.getvalue()} {stdout.getvalue()}"
        )
    module_origins = _gda_module_origins(package_root)
    audit = {
        "label": label,
        "executable": str(Path(sys.executable).resolve()),
        "package_origin": str(Path(gda_balancing.__file__).resolve()),
        "module_origin_count": len(module_origins),
        "module_origins_sha256": hashlib.sha256(_encoded(module_origins)).hexdigest(),
        "all_module_origins_in_site_packages": True,
        "sys_path": list(sys.path),
    }
    return json.loads(stdout.getvalue()), audit


def _admit_b_model(
    context: AdmittedAuthorityContext,
    artifacts: dict[str, dict[str, Any]],
) -> bool:
    by_role = artifacts_by_protocol_role(context.language_bundle, artifacts)
    if set(by_role) != _MODEL_ROLES or not all(
        verify_artifact(value, context.language_bundle) for value in by_role.values()
    ):
        return False
    return admit_resolved_model(
        {
            role: by_role[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted


def _admit_b_runtime(
    context: AdmittedAuthorityContext,
    rir: dict[str, Any],
    specification: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> bool:
    if set(artifacts) != _RUNTIME_ROLES:
        return False
    program = admit_rir(rir, authority_context=context)
    if not isinstance(program, AdmittedRir):
        return False
    checked = check_experiment_value(specification, program, authority_context=context)
    return validate_experiment_artifact_set(checked, artifacts)


def _exercise(
    request_path: Path,
    output: Path,
    expected_identity_path: Path,
    site_packages: Path,
    forbidden_source_root: Path,
) -> dict[str, Any]:
    expected_identity = json.loads(expected_identity_path.read_text())
    observed_identity = _identity()
    if observed_identity != expected_identity:
        raise AssertionError("installed A build identity changed after the freeze")
    package_root = (site_packages / "gda_balancing").resolve()
    if Path(gda_balancing.__file__).resolve().parent != package_root:
        raise AssertionError("A package did not load from the installed wheel")
    if any(
        Path(entry).resolve().is_relative_to(forbidden_source_root.resolve())
        for entry in sys.path
        if entry
    ):
        raise AssertionError("A search path contains the source checkout")

    request = json.loads(request_path.read_text())
    output.mkdir(parents=True, exist_ok=True)
    audits: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for case_index, case in enumerate(request["cases"]):
        context = admit_authority_context(
            case["kernel"], _language_bundle(case["language_bundle"])
        )
        if not isinstance(context, AdmittedAuthorityContext):
            raise AssertionError(f"A refused external authority: {context}")

        def provider(selected: AdmittedAuthorityContext = context):
            return selected

        registry = (
            model_check_descriptor(provider),
            model_build_descriptor(provider),
            experiment_check_descriptor(provider),
            experiment_run_descriptor(provider),
        )
        case_dir = output / f"{case_index:02d}-{case['authority']}-{case['variant']}"
        case_dir.mkdir()
        source_path = case_dir / "model-source.json"
        source_path.write_bytes(_encoded(case["source"]))
        model_check, audit = _invoke(
            registry,
            ["model", "check", str(source_path)],
            label=f"{case['authority']}/{case['variant']}/model-check",
            package_root=package_root,
        )
        audits.append(audit)
        build, audit = _invoke(
            registry,
            [
                "model",
                "build",
                str(source_path),
                "--out",
                str(case_dir / "build"),
                "--invocation-key",
                f"{case_index + 1:02x}" * 32,
            ],
            label=f"{case['authority']}/{case['variant']}/model-build",
            package_root=package_root,
        )
        audits.append(audit)
        model_members = artifacts_by_protocol_role(
            context.language_bundle, _members(build)
        )
        if set(model_members) != _MODEL_ROLES:
            raise AssertionError("A Model build did not publish eight protocol members")
        rir_path = next(
            Path(row["locator"])
            for row in build["member_locators"]
            if row["logical_name"] == "rir-semantic-payload"
        )
        specification_path = case_dir / "experiment.json"
        specification_path.write_bytes(_encoded(case["specification"]))
        experiment_check, audit = _invoke(
            registry,
            [
                "experiment",
                "check",
                str(specification_path),
                "--rir",
                str(rir_path),
            ],
            label=f"{case['authority']}/{case['variant']}/experiment-check",
            package_root=package_root,
        )
        audits.append(audit)
        run, audit = _invoke(
            registry,
            [
                "experiment",
                "run",
                str(specification_path),
                "--rir",
                str(rir_path),
                "--out",
                str(case_dir / "run"),
                "--invocation-key",
                f"{case_index + 129:02x}" * 32,
            ],
            label=f"{case['authority']}/{case['variant']}/experiment-run",
            package_root=package_root,
        )
        audits.append(audit)
        runtime_members = _members(run)
        if set(runtime_members) != _RUNTIME_ROLES:
            raise AssertionError(
                "A Experiment run did not publish six protocol members"
            )
        if (
            model_members["build-receipt"]["compiler"] != expected_identity["compiler"]
            or model_members["resolution-receipt"]["resolver"]
            != expected_identity["resolver"]
            or runtime_members["evaluator-capability-manifest"][
                "evaluator_build_identity"
            ]
            != expected_identity["evaluator"]
        ):
            raise AssertionError("A artifact build identities changed after the freeze")
        results.append(
            {
                "authority": case["authority"],
                "variant": case["variant"],
                "model_check": model_check,
                "model_build": build,
                "model_members": model_members,
                "experiment_check": experiment_check,
                "experiment_run": run,
                "runtime_members": runtime_members,
                "a_admits_b_model": _admit_b_model(context, case["b_model"]),
                "a_admits_b_runtime": _admit_b_runtime(
                    context,
                    case["b_model"]["rir-semantic-payload"],
                    case["specification"],
                    case["b_runtime"],
                ),
            }
        )
    response = {
        "identity": observed_identity,
        "invocations": audits,
        "cases": results,
    }
    (output / "a-response.json").write_bytes(_encoded(response))
    return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    identify = subparsers.add_parser("identify")
    identify.add_argument("--output", type=Path, required=True)
    exercise = subparsers.add_parser("exercise")
    exercise.add_argument("--request", type=Path, required=True)
    exercise.add_argument("--output", type=Path, required=True)
    exercise.add_argument("--expected-identity", type=Path, required=True)
    exercise.add_argument("--site-packages", type=Path, required=True)
    exercise.add_argument("--forbidden-source-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "identify":
        args.output.write_bytes(_encoded(_identity()))
    else:
        os.environ.setdefault("GDA_BALANCING_ANCHOR_KEY", "a5" * 32)
        os.environ.setdefault("GDA_BALANCING_STORE_DIR", str(args.output / "store"))
        _exercise(
            args.request,
            args.output,
            args.expected_identity,
            args.site_packages,
            args.forbidden_source_root,
        )
