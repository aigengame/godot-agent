"""Real windowed acceptance for the isolated three-view model preview (#891)."""

import hashlib
import json
import os
import struct
import zlib
from pathlib import Path
from typing import cast

import pytest
from PIL import Image

from gda.integrations.preview import GdaPreviewHost
from gda_assets.adapters.preview_files import PreviewFiles
from gda_assets.application.preview import preview_asset
from gda_assets.api import PreviewRequest, PreviewSettings
from tests.conftest import project_godot
from tests.support import GODOT, Gda

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX"),
    pytest.mark.xdist_group("windowed"),
]


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xe0\x70\x30\xff"))
        + chunk(b"IEND", b"")
    )


def _asymmetric_glb(path: Path, *, textured: bool = True) -> None:
    positions = struct.pack(
        "<24f",
        2,
        -1,
        10,
        6,
        -1,
        10,
        6,
        2,
        10,
        2,
        2,
        10,
        2,
        -1,
        12,
        6,
        -1,
        12,
        6,
        2,
        12,
        2,
        2,
        12,
    )
    indices = struct.pack(
        "<36H",
        0,
        1,
        2,
        0,
        2,
        3,
        4,
        6,
        5,
        4,
        7,
        6,
        0,
        4,
        5,
        0,
        5,
        1,
        1,
        5,
        6,
        1,
        6,
        2,
        2,
        6,
        7,
        2,
        7,
        3,
        3,
        7,
        4,
        3,
        4,
        0,
    )
    binary = positions + indices
    binary += b"\0" * (-len(binary) % 4)
    image_offset = len(binary)
    image = _png() if textured else b""
    binary += image
    binary += b"\0" * (-len(binary) % 4)
    primitive = {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
    pbr: dict[str, object] = {
        "baseColorFactor": [0.8, 0.4, 0.2, 1.0],
        "metallicFactor": 0.25,
        "roughnessFactor": 0.7,
    }
    document: dict[str, object] = {
        "asset": {"version": "2.0", "generator": "gda #891 native fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "OffsetAsset", "children": [1]},
            {"name": "Body", "mesh": 0},
        ],
        "materials": [{"name": "PreviewMaterial", "pbrMetallicRoughness": pbr}],
        "meshes": [{"name": "AsymmetricBox", "primitives": [primitive]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": [2, -1, 10],
                "max": [6, 2, 12],
            },
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    if textured:
        buffer_views = document["bufferViews"]
        assert isinstance(buffer_views, list)
        buffer_views.append(
            {"buffer": 0, "byteOffset": image_offset, "byteLength": len(image)}
        )
        document["images"] = [{"bufferView": 2, "mimeType": "image/png"}]
        document["textures"] = [{"source": 0}]
        pbr["baseColorTexture"] = {"index": 0}
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    chunks = (
        struct.pack("<I4s", len(payload), b"JSON")
        + payload
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def _foreground_bbox(path: Path) -> tuple[int, int, int, int]:
    with Image.open(path) as image:
        pixels = image.convert("RGB")
        background = cast(tuple[int, int, int], pixels.getpixel((0, 0)))
        foreground = [
            (x, y)
            for y in range(pixels.height)
            for x in range(pixels.width)
            if max(
                abs(a - b)
                for a, b in zip(
                    cast(tuple[int, int, int], pixels.getpixel((x, y))), background
                )
            )
            > 8
        ]
    assert foreground, f"no foreground pixels in {path}"
    xs, ys = zip(*foreground)
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _assert_removed(result: dict) -> None:
    preview = result["preview"]
    assert preview["cleanup"] == {
        "session_stopped": True,
        "project_removed": True,
        "issues": [],
    }
    assert not Path(preview["project"]).exists()


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_public_preview_frames_textured_offset_model_in_three_non_square_views(
    tmp_path, monkeypatch
):
    caller = tmp_path / "caller-project"
    caller.mkdir()
    source = caller / "model.glb"
    output = tmp_path / "captures"
    _asymmetric_glb(source)
    original = source.read_bytes()
    (caller / "project.godot").write_text(
        project_godot(name="preview-caller", extra='run/main_scene="res://keep.tscn"')
    )
    (caller / "keep.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="Keep" type="Node"]\n'
    )
    (caller / "keep.txt").write_text("preserve caller project\n")
    caller_before = {
        path.relative_to(caller): path.read_bytes()
        for path in caller.rglob("*")
        if path.is_file()
    }
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"width": 480, "height": 240, "padding": 1.25}))
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))

    result = Gda(caller, json_output=True, timeout=180).json(
        "asset-pipeline",
        "preview",
        "--path",
        "res://model.glb",
        "--output-dir",
        str(output),
        "--settings",
        str(settings),
        "--frames",
        "8",
        timeout=180,
    )
    preview = result["preview"]

    assert preview["failure"] is None
    assert preview["completed"] == [
        "prepare",
        "import",
        "inspect",
        "framing",
        "start",
        "ready",
        "view.front",
        "view.side",
        "view.three_quarter",
        "performance",
    ]
    assert preview["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert source.read_bytes() == original
    assert {
        path.relative_to(caller): path.read_bytes()
        for path in caller.rglob("*")
        if path.is_file()
    } == caller_before
    assert preview["inspection"]["resource"] == "res://model.glb"
    assert preview["inspection"]["bounds"] == {
        "position": [2.0, -1.0, 10.0],
        "size": [4.0, 3.0, 2.0],
    }
    assert preview["inspection"]["coordinate_space"] == "resource"
    assert preview["inspection"]["geometry"] == "static_mesh_aabb"
    assert preview["session"]["running"] is True
    assert preview["session"]["windowed"] is True
    assert preview["performance_session"] == preview["session"]["session_id"]
    assert preview["performance"]["frames"] == 8
    assert preview["diagnostics"] == {"errors": [], "truncated": False}
    assert [view["state"]["camera"]["name"] for view in preview["views"]] == [
        "front",
        "side",
        "three_quarter",
    ]
    boxes = []
    for index, view in enumerate(preview["views"]):
        state, capture = view["state"], view["capture"]
        assert state["index"] == capture["applied_view"] == index
        assert state["viewport"] == [480, 240]
        assert state["camera"]["target"] == pytest.approx([4.0, 0.5, 11.0])
        assert state["camera"]["size"] > 3.0
        assert state["pose"] == "static_imported"
        assert state["overlays"] == []
        assert capture["receipt"]["session_id"] == preview["session"]["session_id"]
        assert capture["receipt"]["launched_scene"] == "res://preview.tscn"
        image = Path(capture["receipt"]["path"])
        assert image.parent == output.resolve()
        assert _png_size(image) == (480, 240)
        assert (
            hashlib.sha256(image.read_bytes()).hexdigest()
            == capture["receipt"]["sha256"]
        )
        box = _foreground_bbox(image)
        boxes.append(box)
        assert box[0] > 0 and box[1] > 0
        assert box[2] < 480 and box[3] < 240
    front_width, front_height = boxes[0][2] - boxes[0][0], boxes[0][3] - boxes[0][1]
    side_width, side_height = boxes[1][2] - boxes[1][0], boxes[1][3] - boxes[1][1]
    # Independent projection of the known 4x3x2 box: orthographic size is
    # 3 * 1.25 = 3.75; the 2:1 viewport spans 7.5 world units horizontally.
    assert front_width == pytest.approx(4 / 7.5 * 480, abs=18)
    assert front_height == pytest.approx(3 / 3.75 * 240, abs=18)
    assert side_width == pytest.approx(2 / 7.5 * 480, abs=18)
    assert side_height == pytest.approx(3 / 3.75 * 240, abs=18)
    _assert_removed(result)


class _FixtureFiles(PreviewFiles):
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.project: Path | None = None

    def prepare(self, source: Path, output_dir: Path, budget: Path | None):
        self.project, digest = super().prepare(source, output_dir, budget)
        return self.project, digest

    def configure(self, project, settings, cameras) -> None:
        super().configure(project, settings, cameras)
        script = project / "preview.gd"
        text = script.read_text()
        if self.mode == "delayed":
            text = text.replace(
                "\tawait get_tree().process_frame\n\t_apply_view(index)",
                "\tfor ignored in range(60):\n\t\tawait get_tree().process_frame\n\t_apply_view(index)",
            )
        else:
            text = text.replace(
                'FileAccess.get_file_as_string("res://preview.json")', '"not json"'
            )
        script.write_text(text)


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_preview_waits_for_delayed_applied_view_and_then_cleans_up(
    tmp_path, monkeypatch
):
    source = tmp_path / "model.glb"
    _asymmetric_glb(source, textured=False)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    files = _FixtureFiles("delayed")

    result = preview_asset(
        PreviewRequest(
            source,
            tmp_path / "captures",
            PreviewSettings(320, 180, 1.2),
            frames=4,
            timeout=25,
        ),
        host=GdaPreviewHost(str(GODOT)),
        files=files,
    )

    assert result.failure is None
    assert len(result.views) == 3
    # View zero may already be ready from fixture startup; transitions to the
    # other two views must report waiting through the injected frame delay.
    assert all(view.capture.frames_waited > 0 for view in result.views[1:])
    assert result.cleanup.session_stopped and result.cleanup.project_removed
    assert files.project is not None and not files.project.exists()


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_preview_failure_stops_session_and_removes_temporary_project(
    tmp_path, monkeypatch
):
    source = tmp_path / "model.glb"
    _asymmetric_glb(source, textured=False)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    files = _FixtureFiles("invalid")

    result = preview_asset(
        PreviewRequest(
            source,
            tmp_path / "captures",
            PreviewSettings(320, 180, 1.2),
            frames=2,
            timeout=25,
        ),
        host=GdaPreviewHost(str(GODOT)),
        files=files,
    )

    assert result.failure is not None
    assert result.failure.stage == "view.front"
    assert result.cleanup.session_stopped is True
    assert result.cleanup.project_removed is True
    assert files.project is not None and not files.project.exists()


@pytest.mark.usefixtures("windowed_host", "daemon_runtime_dir")
def test_public_preview_compares_native_performance_and_rejects_changed_setup(
    tmp_path, monkeypatch
):
    source = tmp_path / "model.glb"
    _asymmetric_glb(source, textured=False)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"width": 320, "height": 180, "padding": 1.2}))
    changed_settings = tmp_path / "changed-settings.json"
    changed_settings.write_text(
        json.dumps({"width": 400, "height": 180, "padding": 1.2})
    )
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"draw_calls": {"stat": "max", "max": 0}}))
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(None, json_output=True, timeout=180)

    def invoke(output: str, selected_settings: Path, *extra: str) -> dict:
        return run.json(
            "asset-pipeline",
            "preview",
            "--path",
            str(source),
            "--output-dir",
            str(tmp_path / output),
            "--settings",
            str(selected_settings),
            "--frames",
            "4",
            *extra,
            timeout=180,
        )

    first = invoke("first", settings)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(first))
    second = invoke(
        "second", settings, "--baseline", str(baseline), "--budget", str(budget)
    )
    third = invoke("third", changed_settings, "--baseline", str(baseline))

    first_preview = first["preview"]
    second_preview = second["preview"]
    assert first_preview["performance"]["frames"] == 4
    assert first_preview["performance"]["budget"] is None
    assert second_preview["performance"]["frames"] == 4
    assert second_preview["performance"]["passed"] is False
    draw_budget = second_preview["performance"]["budget"]["draw_calls"]
    assert draw_budget["stat"] == "max"
    assert draw_budget["value"] > 0
    assert draw_budget["min"] is None
    assert draw_budget["max"] == 0.0
    assert draw_budget["passed"] is False
    comparison = second_preview["comparison"]
    assert comparison["status"] == "comparable"
    assert comparison["reasons"] == []
    assert set(comparison["changes"]) == {"draw_calls", "fps", "primitives_in_frame"}
    for name, change in comparison["changes"].items():
        assert change["before"] == first_preview["performance"]["stats"][name]
        assert change["after"] == second_preview["performance"]["stats"][name]
        assert change["before_budget"] is None
    assert comparison["changes"]["draw_calls"]["after_budget"] == draw_budget
    assert comparison["changes"]["fps"]["after_budget"] is None
    assert comparison["changes"]["primitives_in_frame"]["after_budget"] is None

    incompatible = third["preview"]["comparison"]
    assert incompatible["status"] == "non_comparable"
    assert incompatible["changes"] == {}
    assert "preview_setup_mismatch" in incompatible["reasons"]
    for result in (first, second, third):
        _assert_removed(result)


def test_native_preview_waits_after_captures_before_sampling(tmp_path, monkeypatch):
    import time
    from gda.integrations.preview import GdaGodotPreviewPort

    source = tmp_path / "model.glb"
    _asymmetric_glb(source, textured=False)
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    moments = {}

    class TimedPort(GdaGodotPreviewPort):
        def warmup(self, seconds):
            moments["before"] = time.monotonic()
            super().warmup(seconds)
            moments["after"] = time.monotonic()

        def performance(self, frames, *, budget):
            moments["sample"] = time.monotonic()
            return super().performance(frames, budget=budget)

    result = preview_asset(
        PreviewRequest(
            source,
            tmp_path / "captures",
            settings=PreviewSettings(width=320, height=180),
            frames=4,
            warmup_seconds=0.25,
        ),
        host=lambda project: TimedPort(project),
        files=PreviewFiles(),
    )
    assert result.failure is None, result.failure
    assert moments["after"] - moments["before"] >= 0.25
    assert moments["sample"] >= moments["after"]
    assert result.request.warmup_seconds == 0.25 and "warmup" in result.completed
    assert result.performance is not None and len(result.performance.samples) == 4
    assert result.cleanup.session_stopped and result.cleanup.project_removed
    assert result.project is not None
    assert not result.cleanup.issues and not Path(result.project).exists()
