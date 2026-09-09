"""A real windowed same-path model refresh through the public asset pipeline."""

import json
import os
import struct
import zlib
from pathlib import Path

import pytest

from tests.conftest import project_godot
from tests.support import Gda, assert_windowed_ok

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
    pytest.mark.xdist_group("windowed"),
]

MODEL = "res://model.glb"
SCENE = "res://test.tscn"
NODE = "/root/Test/Model"


def _glb(
    path: Path, *, interior_x: float, metallic: float, textured: bool = False
) -> None:
    """Write equal-topology fixtures whose sampled content differs."""
    coordinates = (
        -1.0,
        -1.0,
        0.0,
        1.0,
        -1.0,
        0.0,
        1.0,
        1.0,
        0.0,
        -1.0,
        1.0,
        0.0,
        interior_x,
        0.0,
        0.0,
    )
    positions = struct.pack("<15f", *coordinates)
    indices = struct.pack("<12H", 0, 1, 4, 1, 2, 4, 2, 3, 4, 3, 0, 4)
    binary = positions + indices
    binary += b"\0" * (-len(binary) % 4)
    image_offset = len(binary)
    if textured:

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            )

        image = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff\xff"))
            + chunk(b"IEND", b"")
        )
        binary += image
        binary += b"\0" * (-len(binary) % 4)
    document = {
        "asset": {"version": "2.0", "generator": "gda runtime refresh fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "AssetRoot", "children": [1]}, {"name": "Body", "mesh": 0}],
        "materials": [
            {
                "name": "BodyMaterial",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.25, 0.55, 0.85, 1.0],
                    "metallicFactor": metallic,
                    "roughnessFactor": 0.6,
                },
            }
        ],
        "meshes": [
            {
                "name": "BodyMesh",
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
                ],
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 5,
                "type": "VEC3",
                "min": [-1.0, -1.0, 0.0],
                "max": [1.0, 1.0, 0.0],
            },
            {"bufferView": 1, "componentType": 5123, "count": 12, "type": "SCALAR"},
        ],
    }
    if textured:
        document["bufferViews"].append(
            {"buffer": 0, "byteOffset": image_offset, "byteLength": len(image)}
        )
        document["images"] = [{"bufferView": 2, "mimeType": "image/png"}]
        document["textures"] = [{"source": 0}]
        document["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {
            "index": 0
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


def _fixture(project: Path, source: Path) -> None:
    project.mkdir()
    source.mkdir()
    _glb(source / "a.glb", interior_x=-0.2, metallic=0.1)
    _glb(source / "b.glb", interior_x=0.35, metallic=0.9)
    _glb(source / "material.glb", interior_x=-0.2, metallic=0.9)
    _glb(source / "vertex.glb", interior_x=0.35, metallic=0.1)
    _glb(source / "textured.glb", interior_x=-0.2, metallic=0.1, textured=True)
    _glb(project / "wrong.glb", interior_x=0.0, metallic=0.5)
    _glb(project / "old.glb", interior_x=-0.2, metallic=0.1)
    (project / "project.godot").write_text(
        project_godot(
            name="gda-runtime-refresh-e2e",
            extra=(
                'run/main_scene="res://test.tscn"\n\n'
                "[display]\n\nwindow/size/viewport_width=160\n"
                "window/size/viewport_height=120\n\n"
                '[rendering]\n\nrenderer/rendering_method="gl_compatibility"'
            ),
        ),
        encoding="utf-8",
    )
    (project / "test.tscn").write_text(
        "[gd_scene load_steps=2 format=3]\n\n"
        '[ext_resource type="Script" path="res://startup.gd" id="1"]\n\n'
        '[node name="Test" type="Node3D"]\nscript = ExtResource("1")\n\n'
        '[node name="Camera3D" type="Camera3D" parent="."]\n'
        "position = Vector3(0, 0, 4)\n",
        encoding="utf-8",
    )
    (project / "startup.gd").write_text(
        "extends Node3D\n\n"
        "func _ready():\n"
        '\t_add_model("res://model.glb", "Model")\n'
        '\t_add_model("res://wrong.glb", "WrongModel")\n\n'
        '\tif FileAccess.file_exists("res://replace_mesh_on_start.flag"):\n'
        "\t\t_replace_model_mesh($Model)\n\n"
        "func _add_model(path: String, model_name: String):\n"
        "\tvar packed := load(path) as PackedScene\n"
        "\tvar model := packed.instantiate()\n"
        "\tmodel.name = model_name\n"
        "\tadd_child(model)\n\n"
        "func _replace_model_mesh(model: Node):\n"
        '\tvar donor := (load("res://old.glb") as PackedScene).instantiate()\n'
        '\tvar targets := model.find_children("*", "MeshInstance3D", true, false)\n'
        '\tvar donors := donor.find_children("*", "MeshInstance3D", true, false)\n'
        "\tassert(targets.size() == 1 and donors.size() == 1)\n"
        "\t(targets[0] as MeshInstance3D).mesh = (donors[0] as MeshInstance3D).mesh\n"
        "\tdonor.free()\n",
        encoding="utf-8",
    )


def _handoff_args(
    source_root: Path, source: str, *, refresh: dict | None = None
) -> list[str]:
    args = [
        "asset-pipeline",
        "run",
        "--files",
        json.dumps([{"source": source, "target": MODEL}]),
        "--source-root",
        str(source_root),
        "--overwrite",
    ]
    if refresh is not None:
        args += ["--refresh", json.dumps(refresh)]
    return args


def _run_handoff(run: Gda, source_root: Path, source: str, *, refresh=None) -> dict:
    return run.json(*_handoff_args(source_root, source, refresh=refresh), timeout=180)


def _assert_complete(sample: dict) -> str:
    content = sample["content"]
    assert content["measurement"] == "godot-static-model-content-v2"
    assert content.get("engine") or content.get("engine_version")
    assert content["complete"] is True
    assert content["unsupported"] == []
    assert content["omitted"] == []
    assert content["nodes"] >= 2
    assert content["surfaces"] == 1
    assert content["vertices"] >= 5
    assert len(content["digest"]) == 64
    return content["digest"]


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_refresh_replaces_stale_same_path_instance_and_captures_new_session(
    tmp_path, monkeypatch
):
    project, source = tmp_path / "project", tmp_path / "source"
    _fixture(project, source)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(project, json_output=True, timeout=180)
    capture = tmp_path / "refreshed.png"
    try:
        _run_handoff(run, source, "a.glb")
        started = assert_windowed_ok(run("daemon", "start", "--windowed"))
        assert started.returncode == 0, started.stdout + started.stderr
        run.json("daemon", "wait-ready", "--timeout", "25")
        live_a = run.json("game", "inspect-model-content", "--node", NODE)
        digest_a = _assert_complete(live_a)
        session_a = live_a["session_id"]

        _run_handoff(run, source, "b.glb")
        imported_b = run.json("resource", "inspect-model-content", "--path", MODEL)
        digest_b = _assert_complete(imported_b)
        stale_a = run.json("game", "inspect-model-content", "--node", NODE)
        assert digest_b != digest_a
        assert _assert_complete(stale_a) == digest_a
        assert stale_a["session_id"] == session_a

        result = _run_handoff(
            run,
            source,
            "b.glb",
            refresh={
                "path": MODEL,
                "scene": SCENE,
                "node": NODE,
                "windowed": True,
                "capture_output": str(capture),
            },
        )
        refreshed = result["pipeline"]["refresh"]
        assert refreshed["status"] == "verified"
        assert refreshed["runtime_state_preserved"] is False
        assert refreshed["comparison"] == {"status": "match", "reasons": []}
        assert refreshed["before"]["session_id"] == session_a
        assert refreshed["ready_session"]["session_id"] != session_a
        assert (
            refreshed["after"]["session_id"] == refreshed["ready_session"]["session_id"]
        )
        assert _assert_complete(refreshed["imported"]) == digest_b
        assert _assert_complete(refreshed["instance"]) == digest_b
        assert refreshed["instance"]["scene_file_path"] == MODEL
        receipt = refreshed["capture"]
        assert receipt["session_id"] == refreshed["instance"]["session_id"]
        assert receipt["launched_scene"] == SCENE
        assert receipt["engine_frame"] > refreshed["instance"]["engine_frame"]
        assert len(receipt["sha256"]) == 64
        assert capture.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        run("daemon", "stop")


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
@pytest.mark.parametrize("variant", ["material.glb", "vertex.glb"])
def test_refresh_digest_detects_each_admitted_material_or_geometry_change(
    tmp_path, monkeypatch, variant
):
    project, source = tmp_path / "project", tmp_path / "source"
    _fixture(project, source)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(project, json_output=True, timeout=180)
    try:
        _run_handoff(run, source, "a.glb")
        baseline = run.json("resource", "inspect-model-content", "--path", MODEL)
        baseline_digest = _assert_complete(baseline)
        result = _run_handoff(
            run,
            source,
            variant,
            refresh={
                "path": MODEL,
                "scene": SCENE,
                "node": NODE,
                "windowed": True,
            },
        )
        refresh = result["pipeline"]["refresh"]
        imported_digest = _assert_complete(refresh["imported"])
        instance_digest = _assert_complete(refresh["instance"])
        assert refresh["status"] == "verified"
        assert refresh["comparison"] == {"status": "match", "reasons": []}
        assert imported_digest == instance_digest
        assert imported_digest != baseline_digest
        assert refresh["imported"]["content"]["engine"].startswith("4.6.")
    finally:
        run("daemon", "stop")


def test_native_sampler_marks_unsupported_and_bounded_samples_incomplete(tmp_path):
    project, source = tmp_path / "project", tmp_path / "source"
    _fixture(project, source)
    run = Gda(project, json_output=True, timeout=180)

    _run_handoff(run, source, "textured.glb")
    unsupported = run.json("resource", "inspect-model-content", "--path", MODEL)
    assert unsupported["content"]["complete"] is False
    assert unsupported["content"]["digest"] is None
    assert unsupported["content"]["unsupported"]

    _run_handoff(run, source, "a.glb")
    bounded = run.json(
        "resource", "inspect-model-content", "--path", MODEL, "--max-vertices", "1"
    )
    assert bounded["content"]["complete"] is False
    assert bounded["content"]["digest"] is None
    assert bounded["content"]["omitted"]


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_refresh_rejects_same_path_instance_whose_mesh_was_replaced_at_startup(
    tmp_path, monkeypatch
):
    project, source = tmp_path / "project", tmp_path / "source"
    _fixture(project, source)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(project, json_output=True, timeout=180)
    try:
        _run_handoff(run, source, "b.glb")
        assert_windowed_ok(run("daemon", "start", "--windowed"))
        run.json("daemon", "wait-ready", "--timeout", "25")
        before = run.json("daemon", "status")
        (project / "replace_mesh_on_start.flag").touch()

        error = run.error(
            *_handoff_args(
                source,
                "b.glb",
                refresh={
                    "path": MODEL,
                    "scene": SCENE,
                    "node": NODE,
                    "windowed": True,
                },
            ),
            code="operation_failed",
            timeout=180,
        )
        refresh = error["partial_result"]["refresh"]
        assert error["partial_result"]["failure"]["code"] == "refresh_mismatch"
        assert refresh["status"] == "mismatch"
        assert refresh["comparison"]["status"] == "mismatch"
        assert refresh["imported"]["path"] == MODEL
        assert refresh["instance"]["node"] == NODE
        assert refresh["instance"]["scene_file_path"] == MODEL
        assert _assert_complete(refresh["imported"]) != _assert_complete(
            refresh["instance"]
        )
        assert refresh["before"]["session_id"] == before["session_id"]
        assert refresh["ready_session"]["session_id"] != before["session_id"]
        assert refresh["after"]["running"] is True
        assert refresh["after"]["session_id"] == refresh["ready_session"]["session_id"]
        assert refresh["runtime_state_preserved"] is False
    finally:
        run("daemon", "stop")


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
@pytest.mark.parametrize("node", ["/root/Test/WrongModel", "/root/Test/Missing"])
def test_refresh_refuses_wrong_source_or_missing_instance(tmp_path, monkeypatch, node):
    project, source = tmp_path / "project", tmp_path / "source"
    _fixture(project, source)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(project, json_output=True, timeout=180)
    try:
        _run_handoff(run, source, "a.glb")
        args = _handoff_args(
            source,
            "b.glb",
            refresh={
                "path": MODEL,
                "scene": SCENE,
                "node": node,
                "windowed": True,
            },
        )
        if node.endswith("Missing"):
            process = run(*args, timeout=180)
            assert process.returncode != 0, process.stdout + process.stderr
            error = json.loads(process.stdout)["error"]
            assert error["category"] == "live"
            assert error["code"] == "live_node_not_found"
        else:
            error = run.error(*args, code="operation_failed", timeout=180)
        refresh = error["partial_result"]["refresh"]
        assert refresh["status"] in {"mismatch", "incomplete"}
        assert refresh["runtime_state_preserved"] is False
        if node.endswith("WrongModel"):
            assert error["partial_result"]["failure"]["code"] == "refresh_mismatch"
            assert refresh["instance"]["scene_file_path"] == "res://wrong.glb"
            assert refresh["comparison"]["status"] == "mismatch"
        else:
            assert error["partial_result"]["failure"]["code"] == "live_node_not_found"
            assert refresh["instance"] is None
            assert refresh["status"] == "incomplete"
    finally:
        run("daemon", "stop")
