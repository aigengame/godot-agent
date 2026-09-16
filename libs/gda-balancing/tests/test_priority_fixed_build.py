"""The #878 fixed-build prerequisite runs from frozen wheel and B files."""

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


def test_fixed_wheel_and_complete_b_harness_survive_public_exchange(tmp_path):
    uv = shutil.which("uv")
    assert uv is not None
    tool = Path(__file__).parents[1] / "tools" / "priority_build_freeze.py"
    proof = tmp_path / "proof"
    result = subprocess.run(
        [sys.executable, str(tool), "--proof-dir", str(proof), "--uv", uv],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=460,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((proof / "receipt.json").read_text())
    assert receipt["pre_post_manifests_equal"]
    assert "priority_build_freeze_worker.py" in receipt["single_byte_tamper_refusal"]
    assert receipt["baseline"]["baseline_metric"] == 7
    assert receipt["baseline"]["a_admits_b"]
    assert receipt["baseline"]["b_admits_a"]
    assert receipt["baseline"]["direct_wheel"]["samples"] == {
        "ordered_value": 1234,
        "selected_count": 2,
    }
    assert len(receipt["a_public_processes"]) == 6
    assert (
        len(
            [
                row
                for row in receipt["a_public_processes"]
                if "/site-packages/gda_balancing/" in row["package_origin"]
            ]
        )
        == 3
    )
