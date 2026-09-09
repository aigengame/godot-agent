"""Public concept records pin caller-selected pixels for standalone consumers."""

import hashlib
import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

from PIL import Image

from tests.support import Gda


def _png(path: Path, rgba: tuple[int, int, int, int]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0" + bytes(rgba) * 2))
        + chunk(b"IEND", b"")
    )


def _gda(cwd: Path) -> Gda:
    return Gda(None, godot=None, json_output=True, cwd=cwd)


def _register(cwd: Path, record: str, source: str, name: str) -> dict:
    return _gda(cwd).json(
        "asset-pipeline",
        "prompt-register-output",
        "--record",
        record,
        "--output",
        source,
        "--name",
        name,
        "--caller-declarations",
        json.dumps({"generation_completed": True, "tool": "external-agent"}),
    )["prompt_record"]


def _author_sprite(cwd: Path, handoff: str, output: str) -> dict:
    return _gda(cwd).json(
        "asset-pipeline",
        "concept-author",
        "--handoff",
        handoff,
        "--consumer",
        "sprite-sheet-reference",
        "--output",
        output,
        "--sprite-layout",
        json.dumps(
            {
                "width": 4,
                "height": 2,
                "cell_width": 2,
                "cell_height": 1,
                "frames": 4,
            }
        ),
    )["authoring"]


def test_saved_selection_drives_actual_sprite_pixels_after_move_and_mutation(tmp_path):
    project = tmp_path / "caller-project"
    author = project / "author"
    consumer = project / "consumer"
    records = project / "records"
    author.mkdir(parents=True)
    consumer.mkdir()
    records.mkdir()
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)

    brief_path = author / "brief.json"
    brief_path.write_text(
        json.dumps(
            {
                "use": "sprite",
                "subject": "tiny asymmetric courier",
                "style": "flat readable pixels",
                "views": ["side"],
                "poses": ["idle"],
                "instructions": "Keep the silhouette inside each cell.",
            }
        )
    )
    prepared = _gda(author).json(
        "asset-pipeline",
        "concept-prepare",
        "--brief",
        "brief.json",
        "--record",
        "../records/red-attempt",
        "--producer",
        "external-image-tool",
    )["preparation"]
    assert prepared["brief"]["subject"] == "tiny asymmetric courier"
    assert prepared["prompt"]["record"]["generation_status"] == "unknown"
    assert prepared["prompt"]["handoff"]["action"] == "external_generation_required"

    _gda(consumer).json(
        "asset-pipeline",
        "prompt-revise",
        "--source-record",
        "../records/red-attempt",
        "--record",
        "../records/blue-attempt",
    )
    red_source = author / "red.png"
    blue_source = author / "blue.png"
    _png(red_source, (230, 20, 30, 255))
    _png(blue_source, (20, 40, 230, 255))
    red_record = _register(author, "../records/red-attempt", "red.png", "concept.png")
    blue_record = _register(
        author, "../records/blue-attempt", "blue.png", "concept.png"
    )

    selected = _gda(consumer).json(
        "asset-pipeline",
        "concept-select",
        "--brief-record",
        "../records/red-attempt",
        "--handoff",
        "../records/red-handoff",
        "--candidates",
        json.dumps(
            [
                {"record": "../records/red-attempt", "output": "concept.png"},
                {"record": "../records/blue-attempt", "output": "concept.png"},
            ]
        ),
    )["selection"]
    assert selected["authoring_status"] == "ready"
    assert [item["prompt_record"] for item in selected["selected"]] == [
        str((records / "red-attempt").resolve()),
        str((records / "blue-attempt").resolve()),
    ]
    assert all(item["generation_completed_by_caller"] for item in selected["selected"])

    blue_selected = _gda(author).json(
        "asset-pipeline",
        "concept-select",
        "--brief-record",
        "../records/red-attempt",
        "--handoff",
        "../records/blue-handoff",
        "--candidates",
        json.dumps([{"record": "../records/blue-attempt", "output": "concept.png"}]),
    )["selection"]

    moved = records / "moved-handoff"
    shutil.copytree(records / "red-handoff", moved)
    shutil.rmtree(records / "red-handoff")
    brief_path.write_text("mutated caller source")
    _png(red_source, (5, 5, 5, 255))
    _png(blue_source, (250, 250, 250, 255))
    Path(red_record["outputs"][0]["file"]["path"]).write_bytes(b"mutated candidate")
    Path(blue_record["outputs"][0]["file"]["path"]).write_bytes(b"mutated candidate")

    red_authored = _author_sprite(
        consumer, "../records/moved-handoff", "../records/red-sprites"
    )
    red_artifact = Path(red_authored["artifacts"][0]["path"])
    assert red_authored["reference_loaded"] is True
    assert red_authored["consumed"]["sha256"] == selected["selected"][0]["sha256"]
    assert red_authored["sprite_sheet"] == {
        "width": 4,
        "height": 2,
        "cell_width": 2,
        "cell_height": 1,
        "frames": 4,
    }
    assert red_artifact.read_bytes()
    with Image.open(red_artifact) as image:
        image.load()
        assert image.size == (4, 2)
        assert image.getpixel((0, 0)) == (230, 20, 30, 255)

    # A new explicit selection changes the consumed bytes; the moved handoff stays pinned.
    blue_authored = _author_sprite(
        consumer, "../records/blue-handoff", "../records/blue-sprites"
    )
    blue_artifact = Path(blue_authored["artifacts"][0]["path"])
    assert blue_authored["consumed"]["sha256"] != red_authored["consumed"]["sha256"]
    assert blue_authored["consumed"]["sha256"] == blue_selected["selected"][0]["sha256"]
    assert (
        hashlib.sha256(blue_artifact.read_bytes()).hexdigest()
        != hashlib.sha256(red_artifact.read_bytes()).hexdigest()
    )
    with Image.open(blue_artifact) as image:
        image.load()
        assert image.getpixel((0, 0)) == (20, 40, 230, 255)


def test_invalid_or_incomplete_selection_never_creates_author_output(tmp_path):
    cwd = tmp_path / "caller"
    cwd.mkdir()
    brief = cwd / "brief.json"
    brief.write_text(
        json.dumps(
            {
                "use": "sprite",
                "subject": "marker",
                "style": "flat",
                "views": ["front"],
                "poses": [],
                "instructions": "",
            }
        )
    )
    _gda(cwd).json(
        "asset-pipeline",
        "concept-prepare",
        "--brief",
        "brief.json",
        "--record",
        "attempt",
    )
    candidate = cwd / "candidate.png"
    _png(candidate, (200, 30, 40, 255))
    _gda(cwd).json(
        "asset-pipeline",
        "prompt-register-output",
        "--record",
        "attempt",
        "--output",
        "candidate.png",
        "--name",
        "candidate.png",
    )
    _gda(cwd).error(
        "asset-pipeline",
        "concept-select",
        "--brief-record",
        "attempt",
        "--handoff",
        "unknown-handoff",
        "--candidates",
        json.dumps([{"record": "attempt", "output": "candidate.png"}]),
        code="invalid_params",
    )
    assert not (cwd / "unknown-handoff").exists()

    _gda(cwd).json(
        "asset-pipeline",
        "prompt-register-output",
        "--record",
        "attempt",
        "--output",
        "candidate.png",
        "--name",
        "completed.png",
        "--caller-declarations",
        json.dumps({"generation_completed": True}),
    )
    _gda(cwd).json(
        "asset-pipeline",
        "concept-select",
        "--brief-record",
        "attempt",
        "--handoff",
        "valid-handoff",
        "--candidates",
        json.dumps([{"record": "attempt", "output": "completed.png"}]),
    )

    malformed = cwd / "malformed-handoff"
    malformed.mkdir()
    (malformed / "handoff.json").write_text("not json")
    absent_output = cwd / "malformed-output"
    _gda(cwd).error(
        "asset-pipeline",
        "concept-author",
        "--handoff",
        "malformed-handoff",
        "--consumer",
        "sprite-sheet-reference",
        "--output",
        "malformed-output",
        "--sprite-layout",
        json.dumps(
            {"width": 2, "height": 1, "cell_width": 2, "cell_height": 1, "frames": 1}
        ),
        code="invalid_params",
    )
    assert not absent_output.exists()

    empty_handoff = cwd / "empty-handoff"
    shutil.copytree(cwd / "valid-handoff", empty_handoff)
    manifest = json.loads((empty_handoff / "handoff.json").read_text())
    manifest["selected"] = []
    (empty_handoff / "handoff.json").write_text(json.dumps(manifest))
    no_selection_output = cwd / "no-selection-output"
    _gda(cwd).error(
        "asset-pipeline",
        "concept-author",
        "--handoff",
        "empty-handoff",
        "--consumer",
        "sprite-sheet-reference",
        "--output",
        "no-selection-output",
        "--sprite-layout",
        json.dumps(
            {"width": 2, "height": 1, "cell_width": 2, "cell_height": 1, "frames": 1}
        ),
        code="invalid_params",
    )
    assert not no_selection_output.exists()
