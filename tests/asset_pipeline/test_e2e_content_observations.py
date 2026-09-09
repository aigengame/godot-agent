"""Native disk observations around the public asset-pipeline import window."""

import hashlib
import json
import shutil
import struct
from pathlib import Path

import pytest

from tests.support import Gda

pytestmark = pytest.mark.e2e

TARGET = "res://models/model.glb"
FIXTURES = Path(__file__).with_name("fixtures")


def _glb(path: Path, extent: float) -> None:
    positions = struct.pack("<9f", -extent, 0, 0, extent, 0, 0, 0, extent, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = positions + indices
    binary += b"\0" * (-len(binary) % 4)
    document = {
        "asset": {"version": "2.0", "generator": "gda #889 fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Root", "children": [1]}, {"name": "Body", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [-extent, 0, 0],
                "max": [extent, extent, 0],
            },
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    chunks = (
        struct.pack("<I4s", len(payload), b"JSON")
        + payload
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


def _run(
    project: Path,
    source_root: Path,
    source: str,
    *,
    overwrite: bool = False,
    output: Path | None = None,
    declared: dict[str, str] | None = None,
):
    args = [
        "asset-pipeline",
        "run",
        "--files",
        json.dumps([{"source": source, "target": TARGET}]),
        "--source-root",
        str(source_root),
        "--collect-observations",
    ]
    if overwrite:
        args.append("--overwrite")
    if output is not None:
        args.extend(["--observations-output", str(output)])
    if declared is not None:
        args.extend(["--declared-output-sha256", json.dumps(declared)])
    return Gda(project, json_output=True), args


def _asset(result: dict) -> tuple[dict, dict]:
    observations = result["pipeline"]["content_observations"]
    assert len(observations["assets"]) == 1
    return observations, observations["assets"][0]


def _observed(digest: dict) -> None:
    assert digest["state"] == "observed"
    assert len(digest["sha256"]) == 64
    assert digest["size"] > 0
    assert digest["reason"] is None


def _source_root(project: Path) -> Path:
    root = project.with_name(project.name + "-source")
    root.mkdir()
    return root


def test_cold_import_records_pre_and_post_source_config_and_artifact_facts(
    godot_project, tmp_path
):
    source_root = _source_root(godot_project)
    _glb(source_root / "model.glb", 1.0)
    saved = tmp_path / "observations-output.json"
    run, args = _run(godot_project, source_root, "model.glb", output=saved)

    result = run.json(*args)
    observations, asset = _asset(result)

    assert observations["status"] == "stable"
    assert asset["path"] == TARGET
    _observed(asset["source_before"])
    assert asset["source_after"] == asset["source_before"]
    assert asset["configuration_before"] is None
    _observed(asset["configuration_after"])
    assert asset["import_before"]["cache_status"] == "missing"
    assert asset["import_after"]["cache_status"] == "cached"
    assert asset["artifacts"]
    for artifact in asset["artifacts"]:
        _observed(artifact)
    assert asset["engine"]["major"] >= 4
    assert json.loads(saved.read_text()) == observations


def test_changed_glb_bytes_then_identical_repeat_have_stable_bounded_digests(
    godot_project,
):
    source_root = _source_root(godot_project)
    source = source_root / "model.glb"
    _glb(source, 1.0)
    run, args = _run(godot_project, source_root, "model.glb")
    first, first_asset = _asset(run.json(*args))

    _glb(source, 2.0)
    run, args = _run(godot_project, source_root, "model.glb", overwrite=True)
    second, second_asset = _asset(run.json(*args))
    run, args = _run(godot_project, source_root, "model.glb", overwrite=True)
    repeated, repeated_asset = _asset(run.json(*args))

    assert first["status"] == second["status"] == repeated["status"] == "stable"
    assert (
        first_asset["source_after"]["sha256"] != second_asset["source_after"]["sha256"]
    )
    for field in ("source_after", "configuration_after"):
        assert second_asset[field]["sha256"] == repeated_asset[field]["sha256"]
    assert [item["sha256"] for item in second_asset["artifacts"]] == [
        item["sha256"] for item in repeated_asset["artifacts"]
    ]


def test_config_only_root_scale_change_keeps_source_and_changes_config_digest(
    godot_project,
):
    source_root = _source_root(godot_project)
    _glb(source_root / "model.glb", 1.0)
    run, args = _run(godot_project, source_root, "model.glb")
    _, before = _asset(run.json(*args))

    reimport = run.json(
        "resource",
        "reimport",
        TARGET,
        "--updates-json",
        json.dumps({"nodes/root_scale": 2.0}),
    )
    assert reimport["status"] == "applied"
    run, args = _run(godot_project, source_root, "model.glb", overwrite=True)
    observations, after = _asset(run.json(*args))

    assert observations["status"] == "stable"
    assert before["source_after"]["sha256"] == after["source_after"]["sha256"]
    assert (
        before["configuration_after"]["sha256"]
        != after["configuration_after"]["sha256"]
    )
    assert after["configuration_before"] == after["configuration_after"]


def test_native_configuration_normalization_refuses_then_explicit_file_reuse_succeeds(
    godot_project,
):
    source_root = _source_root(godot_project)
    source = source_root / "model.glb"
    _glb(source, 1.0)
    run, args = _run(godot_project, source_root, "model.glb")
    _asset(run.json(*args))

    fixture = godot_project / "configure_import_for_normalization.gd"
    shutil.copyfile(FIXTURES / fixture.name, fixture)
    run.json("script", "run", f"res://{fixture.name}")
    sidecar = godot_project / "models/model.glb.import"
    configured = sidecar.read_bytes()
    assert b"meshes/generate_lods=false" in configured
    assert b"nodes/root_script" not in configured

    _glb(source, 2.0)
    run, args = _run(godot_project, source_root, "model.glb", overwrite=True)
    first = run.error(*args, code="operation_failed")
    partial = first["partial_result"]
    observations, asset = _asset({"pipeline": partial})

    assert partial["completed"] == [
        "validate",
        "stage",
        "install",
        "import",
        "load",
    ]
    assert partial["failure"] == {
        "stage": "observe",
        "code": "observation_changed",
        "message": (
            "Selected input bytes changed during collection; see "
            "content_observations.changes"
        ),
        "cause": None,
    }
    assert partial["outputs"] == [
        {
            "source": "model.glb",
            "target": TARGET,
            "state": "installed",
            "resize": None,
        }
    ]
    assert partial["production"] is None
    assert partial["cleanup"] is None
    assert observations["status"] == "changed"
    assert asset["source_before"] == asset["source_after"]
    assert observations["changes"] == [
        {
            "before": asset["configuration_before"],
            "after": asset["configuration_after"],
        }
    ]
    assert b"nodes/root_script=null" in sidecar.read_bytes()
    assert "completed stages: validate, stage, install, import, load" in first[
        "message"
    ]
    assert "not its writer or semantic equivalence" in first["message"]
    assert "omit --production" in first["message"]
    assert "can fail if they change again" in first["message"]

    reuse_files = [
        {
            "source": str((godot_project / "models/model.glb").resolve()),
            "target": TARGET,
            "references": [],
        }
    ]
    recovery_run = Gda(
        project=godot_project,
        json_output=True,
        extra_env={"GDA_BLENDER": str(godot_project / "must-not-run-blender")},
    )
    repeated = recovery_run.json(
        "asset-pipeline",
        "run",
        "--files",
        json.dumps(reuse_files),
        "--overwrite",
        "--collect-observations",
        "--declared-output-sha256",
        json.dumps({TARGET: asset["source_after"]["sha256"]}),
    )
    repeated_observations, repeated_asset = _asset(repeated)
    assert repeated["pipeline"]["completed"] == [
        "validate",
        "stage",
        "install",
        "import",
        "load",
        "observe",
    ]
    assert repeated_observations["status"] == "stable"
    assert repeated_asset["source_before"] == repeated_asset["source_after"]
    assert repeated_asset["configuration_before"] == repeated_asset[
        "configuration_after"
    ]


def test_wrong_declared_digest_refuses_before_import_and_retains_pre_facts(
    godot_project,
):
    source_root = _source_root(godot_project)
    source = source_root / "model.glb"
    _glb(source, 1.0)
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    run, args = _run(
        godot_project,
        source_root,
        "model.glb",
        declared={TARGET: "0" * 64},
    )

    error = run.error(*args, code="operation_failed")
    observations, asset = _asset({"pipeline": error["partial_result"]})

    assert actual != "0" * 64
    assert observations["status"] == "incomplete"
    assert observations["declared_output_sha256"] == {TARGET: "0" * 64}
    _observed(asset["source_before"])
    assert asset["source_before"]["sha256"] == actual
    assert asset["source_after"] is None
    assert asset["configuration_before"] is None
    assert asset["import_before"]["cache_status"] == "missing"
    assert asset["import_after"] is None
    assert not (godot_project / "models/model.glb.import").exists()
