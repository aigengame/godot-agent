#!/usr/bin/env python3
"""Prepare a fixed priority fixture, then exercise independent B and public A."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import gda_balancing

from priority_protocol_support import authorities, source, specification
from schema2_runtime_independent_support import (
    reference_admits_runtime_artifacts,
    reference_runtime_artifacts,
)
from test_current_namespace_public import _PublicCandidate
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_semantic_artifacts,
)


def _encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _members(receipt: dict) -> dict:
    return {
        row["logical_name"]: json.loads(Path(row["locator"]).read_text())
        for row in receipt["member_locators"]
    }


_CLI_COUNT = 0


def _cli(runtime: Path | None, output: Path, *arguments: str) -> dict:
    global _CLI_COUNT
    _CLI_COUNT += 1
    audit = output / f"a-imports-{_CLI_COUNT}.json"
    harness = Path(__file__).parent
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "GDA_BALANCING_STORE_DIR": str(output / "store"),
        "GDA_BALANCING_ANCHOR_KEY": "a5" * 32,
        "GDA_FREEZE_IMPORT_LOG": str(audit),
    }
    if runtime is None:
        env["PYTHONPATH"] = str(harness)
    else:
        env["PYTHONPATH"] = os.pathsep.join((str(runtime), str(harness)))
    result = subprocess.run(
        [sys.executable, "-m", "gda_balancing", *arguments],
        cwd=output,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode or result.stderr:
        raise AssertionError(
            f"public A refused {arguments}: {result.returncode} "
            f"{result.stderr} {result.stdout}"
        )
    observed = json.loads(audit.read_text())
    expected_package = (
        runtime / "gda_balancing"
        if runtime is not None
        else Path(gda_balancing.__file__).parent
    )
    assert Path(observed["package_origin"]).parent == expected_package
    assert observed["executable"] == str(Path(sys.executable).resolve())
    return json.loads(result.stdout)


def _prepare(fixture: Path) -> None:
    kernel, language, turn = authorities()
    candidate = _PublicCandidate(fixture, authorities=(kernel, language))
    authored = source(turn)
    candidate.write_source(authored)
    (fixture / "input-sha256.json").write_bytes(
        _encoded({"source": hashlib.sha256(_encoded(authored)).hexdigest()})
    )
    # A's executable Python is copied from the installed wheel now. The
    # fixture authority is input data, and the whole copy is frozen next.
    installed = Path(gda_balancing.__file__).parent
    copied = candidate.runtime / "gda_balancing"
    for path in installed.rglob("*.py"):
        assert path.read_bytes() == (copied / path.relative_to(installed)).read_bytes()


def _exercise(fixture: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    kernel, language, turn = authorities()
    authored = source(turn)
    expected = json.loads((fixture / "input-sha256.json").read_text())["source"]
    assert hashlib.sha256(_encoded(authored)).hexdigest() == expected
    assert json.loads((fixture / "model-source.json").read_text()) == authored
    context = _reference_check_source(authored, kernel, language)
    assert not isinstance(context, tuple), context
    rir = _reference_semantic_artifacts(context)["rir-semantic-payload"]
    planned = specification(rir, False)

    # B computes all six results before A's model build or runtime is called.
    independent = reference_runtime_artifacts(context, rir, planned)
    assert len(independent) == 6
    runtime = fixture / "runtime"
    build = _cli(
        runtime,
        output,
        "model",
        "build",
        str(fixture / "model-source.json"),
        "--out",
        str(output / "build"),
        "--invocation-key",
        "55" * 32,
    )
    production_rir = _members(build)["rir-semantic-payload"]
    assert production_rir == rir
    rir_path = next(
        row["locator"]
        for row in build["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    spec_path = output / "experiment.json"
    spec_path.write_bytes(_encoded(planned))
    assert _cli(
        runtime, output, "experiment", "check", str(spec_path), "--rir", rir_path
    )["checked"]
    run = _cli(
        runtime,
        output,
        "experiment",
        "run",
        str(spec_path),
        "--rir",
        rir_path,
        "--out",
        str(output / "run"),
        "--invocation-key",
        "56" * 32,
    )
    production = _members(run)
    from gda_balancing.domain.authority.context import admit_authority_context
    from gda_balancing.domain.experiment import check_experiment_value
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from gda_balancing.domain.model import admit_rir

    admitted_context = admit_authority_context(kernel, language)
    assert admitted_context is not None
    admitted_rir = admit_rir(rir, authority_context=admitted_context)
    checked = check_experiment_value(
        planned, admitted_rir, authority_context=admitted_context
    )
    assert validate_experiment_artifact_set(checked, independent)
    assert reference_admits_runtime_artifacts(context, rir, planned, production)
    for name in independent:
        if name != "evaluator-capability-manifest":
            assert independent[name] == production[name], name
    result = {
        "baseline_metric": independent["metric-dataset"]["samples"][0]["value"],
        "a_rir_identity": production_rir["semantic_identity"],
        "b_rir_identity": rir["semantic_identity"],
        "mutual_result_members": sorted(independent),
        "a_admits_b": True,
        "b_admits_a": True,
        "a_package_origin": str(Path(gda_balancing.__file__).resolve()),
        "b_harness_origin": str(Path(__file__).resolve()),
        "b_executable": str(Path(sys.executable).resolve()),
        "b_sys_path": sys.path,
        "b_import_origins": sorted(
            {
                str(Path(module.__file__).resolve())
                for module in tuple(sys.modules.values())
                if getattr(module, "__file__", None) and Path(module.__file__).exists()
            }
        ),
    }
    assert result["baseline_metric"] == 7
    result["direct_wheel"] = _direct_wheel(output / "direct-wheel")
    (output / "result.json").write_bytes(_encoded(result))


def _direct_wheel(output: Path) -> dict:
    """Use packaged authorities and the installed A wheel without an overlay."""
    from schema2_authority_support import mutable_authorities
    from test_bounded_fold_public import _source, _specification
    from gda_balancing.domain.authority.context import admit_authority_context
    from gda_balancing.domain.experiment import check_experiment_value
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from gda_balancing.domain.model import admit_rir

    output.mkdir()
    kernel, language = mutable_authorities()
    authored = _source()
    context = _reference_check_source(authored, kernel, language)
    assert not isinstance(context, tuple), context
    rir = _reference_semantic_artifacts(context)["rir-semantic-payload"]
    planned = _specification(rir, [1, 2, 3, 4])
    independent = reference_runtime_artifacts(context, rir, planned)
    authored_path = output / "model-source.json"
    authored_path.write_bytes(_encoded(authored))
    build = _cli(
        None,
        output,
        "model",
        "build",
        str(authored_path),
        "--out",
        str(output / "build"),
        "--invocation-key",
        "57" * 32,
    )
    assert _members(build)["rir-semantic-payload"] == rir
    rir_path = next(
        row["locator"]
        for row in build["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    spec_path = output / "experiment.json"
    spec_path.write_bytes(_encoded(planned))
    assert _cli(None, output, "experiment", "check", str(spec_path), "--rir", rir_path)[
        "checked"
    ]
    run = _cli(
        None,
        output,
        "experiment",
        "run",
        str(spec_path),
        "--rir",
        rir_path,
        "--out",
        str(output / "run"),
        "--invocation-key",
        "58" * 32,
    )
    production = _members(run)
    admitted_context = admit_authority_context(kernel, language)
    checked = check_experiment_value(
        planned,
        admit_rir(rir, authority_context=admitted_context),
        authority_context=admitted_context,
    )
    assert validate_experiment_artifact_set(checked, independent)
    assert reference_admits_runtime_artifacts(context, rir, planned, production)
    for name in independent:
        if name != "evaluator-capability-manifest":
            assert independent[name] == production[name], name
    samples = {
        row["metric"]: row["value"] for row in independent["metric-dataset"]["samples"]
    }
    assert samples == {"selected_count": 2, "ordered_value": 1234}
    return {
        "a_entrypoint": "installed wheel via python -m gda_balancing; PYTHONPATH only frozen audit hook",
        "a_rir_identity": rir["semantic_identity"],
        "b_rir_identity": rir["semantic_identity"],
        "a_admits_b": True,
        "b_admits_a": True,
        "mutual_result_members": sorted(independent),
        "samples": samples,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "exercise"))
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        _prepare(args.fixture)
    else:
        assert args.output is not None
        _exercise(args.fixture, args.output)
