"""The #878 priority gate runs installed A against an independently frozen B."""

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
    assert set(receipt["matrix"]) == {"original"}
    assert receipt["renamed_case_hook"]["status"] == "awaiting-supplied-case"
    for variant, metric in (("baseline", 7), ("variant", 0)):
        case = receipt["matrix"]["original"][variant]
        assert case["metric"] == metric
        assert case["model"]["member_count"] == 8
        assert case["model"]["a_admits_b"]
        assert case["model"]["b_admits_a"]
        assert case["runtime"]["member_count"] == 6
        assert case["runtime"]["a_admits_b"]
        assert case["runtime"]["b_admits_a"]
    assert len(receipt["a_invocations"]) == 8
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
