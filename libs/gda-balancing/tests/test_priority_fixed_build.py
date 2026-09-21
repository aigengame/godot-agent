"""The #878 priority gate runs installed A against an independently frozen B."""

from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

_TOOL = Path(__file__).parents[1] / "tools" / "priority_build_freeze.py"
_SPEC = importlib.util.spec_from_file_location("priority_build_freeze", _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
freeze = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(freeze)


def test_bounded_priority_rename_preserves_ordinary_string_data():
    from priority_extension_proof_support import (
        _rename_experiment_semantics,
        _rename_package_semantics,
        _rename_source_semantics,
    )

    ordinary = {
        "label": "Counter",
        "payload": {"operation": "pass", "type": "Outcome"},
        "metadata": {"package": "game.action", "id": "Counter"},
    }
    package = {
        "exports": {
            "operations": ["open"],
            "nominal_types": ["Counter"],
            "types": [{"id": "Counter"}],
        },
        "semantic_closure": [
            {
                "authority_path": "language.operations",
                "definitions": [{"id": "open", "inputs": [], "body": []}],
            },
            {
                "authority_path": "language.nominal_types",
                "definitions": [{"id": "Counter", "definition": {}}],
            },
        ],
        "ordinary": deepcopy(ordinary),
    }
    model_source = {
        "modules": [
            {
                "imports": [
                    {
                        "alias": "Counter",
                        "package": "game.action",
                        "symbol": "Counter",
                    }
                ],
                "symbols": [{"type": "Counter"}],
            }
        ],
        "entrypoints": [
            {
                "id": "open",
                "operation": {"package": "game.turn", "id": "open"},
            }
        ],
        "ordinary": deepcopy(ordinary),
    }
    experiment = {
        "scenarios": [
            {
                "event_plan": [{"entrypoint": "open", "facts": []}],
                "assignments": [],
            }
        ],
        "ordinary": deepcopy(ordinary),
    }
    _rename_package_semantics(package)
    _rename_source_semantics(model_source)
    _rename_experiment_semantics(experiment)
    assert package["ordinary"] == ordinary
    assert model_source["ordinary"] == ordinary
    assert experiment["ordinary"] == ordinary
    assert package["exports"]["operations"] == ["renamed-open"]
    assert model_source["entrypoints"][0]["operation"]["id"] == "renamed-open"
    assert experiment["scenarios"][0]["event_plan"][0]["entrypoint"] == ("renamed-open")


def test_manifest_refuses_one_byte_change_and_extra_member(tmp_path):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    member = frozen / "driver.py"
    member.write_bytes(b"abc")
    manifest = freeze._snapshot({"b": frozen})
    freeze.verify_manifest(manifest, {"b": frozen})
    member.write_bytes(b"abd")
    with pytest.raises(freeze.FreezeViolation, match="driver.py"):
        freeze.verify_manifest(manifest, {"b": frozen})
    member.write_bytes(b"abc")
    (frozen / "extra.py").write_bytes(b"pass\n")
    with pytest.raises(freeze.FreezeViolation, match="extra.py"):
        freeze.verify_manifest(manifest, {"b": frozen})


def test_direct_wheel_and_independent_b_survive_priority_exchange(tmp_path):
    uv = shutil.which("uv")
    assert uv is not None
    tool = Path(__file__).parents[1] / "tools" / "priority_build_freeze.py"
    proof = tmp_path / "proof"
    result = subprocess.run(
        [sys.executable, str(tool), "--proof-dir", str(proof), "--uv", uv],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=480,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((proof / "receipt.json").read_text())
    assert receipt["pre_post_manifests_equal"]
    assert receipt["build_identities_pre_post_equal"]
    assert "priority_direct_wheel_driver.py" in receipt["single_byte_tamper_refusal"]
    assert set(receipt["matrix"]) == {"original", "renamed"}
    selected = receipt["selected_closure"]
    assert selected["derived_after_build_freeze"] is True
    proof = selected["proof"]
    assert proof["scope"] == (
        "priority selected execution closure and generated 8+6 members"
    )
    assert proof["kernel_unchanged"] is True
    assert selected["mapping_member_count"] == proof["renamed_identity_count"]
    binding = proof["selected_dependency_binding"]
    assert binding["rir_semantic_identity"].startswith("sha256:")
    assert binding["selected_semantics_sha256"].startswith("sha256:")
    assert set(binding["model_artifact_identities"]) == {
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "model-explanation",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    }
    assert set(binding["extension_operation_coordinates"]) == {
        "game.action::renamed-append-counter",
        "game.action::renamed-cancel-reverse-step",
        "game.action::renamed-count-match",
        "game.action::renamed-propose",
        "game.action::renamed-resolve",
        "game.turn::renamed-open",
        "game.turn::renamed-pass",
        "game.turn::renamed-respond",
    }
    assert set(binding["extension_type_coordinates"]) == {
        "game.action::RenamedCounter",
        "game.action::RenamedCounters",
        "game.action::RenamedOutcome",
        "game.action::RenamedPendingIds",
    }
    for authority in ("original", "renamed"):
        for variant, metric in (("baseline", 7), ("variant", 0)):
            case = receipt["matrix"][authority][variant]
            assert case["metric"] == metric
            assert case["model"]["member_count"] == 8
            assert case["model"]["a_admits_b"]
            assert case["model"]["b_admits_a"]
            assert case["runtime"]["member_count"] == 6
            assert case["runtime"]["a_admits_b"]
            assert case["runtime"]["b_admits_a"]
            assert (
                case["boundaries"]
                == receipt["matrix"]["original"][variant]["boundaries"]
            )
    assert [
        row["operation"]
        for row in receipt["matrix"]["original"]["baseline"]["boundaries"]
    ] == ["open", "respond", "respond", "pass", "pass", "resolve"]
    assert [
        row["operation"]
        for row in receipt["matrix"]["original"]["variant"]["boundaries"]
    ] == ["open", "respond", "pass", "pass", "resolve"]
    assert len(receipt["a_invocations"]) == 16
    assert {row["label"].rsplit("/", 1)[-1] for row in receipt["a_invocations"]} == {
        "model-check",
        "model-build",
        "experiment-check",
        "experiment-run",
    }
    assert all(
        row["module_origin_count"] > 0
        and row["all_module_origins_in_site_packages"] is True
        for row in receipt["a_invocations"]
    )
    assert "a_priority_fixture_runtime_sha256" not in receipt
    assert "missing_for_ac2" not in receipt
