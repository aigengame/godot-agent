"""Standalone public prompt records survive processes, cwd changes, and failure."""

import hashlib
import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

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


def _tree(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _run(cwd: Path) -> Gda:
    return Gda(None, godot=None, json_output=True, cwd=cwd)


def _record(preparation: dict) -> dict:
    return preparation["preparation"]["record"]


def test_prompt_records_are_portable_explicit_attempts_across_processes_and_cwds(
    tmp_path,
):
    project = tmp_path / "git-project"
    author = project / "authoring"
    consumer = project / "consumer"
    records = project / "records"
    author.mkdir(parents=True)
    consumer.mkdir()
    records.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(project)], check=True, capture_output=True
    )
    template = author / "prompt.txt"
    style = author / "style.txt"
    reference = author / "reference.png"
    template.write_text("A ${subject} beside a $$ sign")
    style.write_text("Soft watercolor, no text.\n")
    _png(reference, (220, 40, 30, 255))
    original_reference = reference.read_bytes()
    secret = "must-not-enter-record"

    prepared_a = _run(author).json(
        "asset-pipeline",
        "prompt-prepare",
        "--record",
        "../records/a",
        "--template",
        "prompt.txt",
        "--style",
        "style.txt",
        "--variables",
        json.dumps({"subject": "red fox"}),
        "--reference",
        "reference.png",
        "--producer",
        "external-image-tool",
        "--requested-options",
        json.dumps({"model": "requested-model", "size": "1024x1024", "seed": 7}),
        extra_env={"PROMPT_TEST_SECRET": secret},
    )
    record_a = _record(prepared_a)
    assert record_a["mode"] == "template"
    assert record_a["resolved_prompt"] == (
        "Soft watercolor, no text.\n\nA red fox beside a $ sign"
    )
    assert record_a["generation_status"] == "unknown"
    assert record_a["outputs"] == []
    assert prepared_a["preparation"]["handoff"]["action"] == (
        "external_generation_required"
    )
    assert prepared_a["preparation"]["handoff"]["registration_operation"] == (
        "prompt-register-output"
    )
    assert secret not in json.dumps(prepared_a)

    template.write_text("A ${subject} under moonlight")
    style.write_text("Sharp ink drawing.\n")
    _png(reference, (20, 40, 230, 255))
    prepared_b = _run(consumer).json(
        "asset-pipeline",
        "prompt-prepare",
        "--record",
        "../records/b",
        "--template",
        "../authoring/prompt.txt",
        "--style",
        "../authoring/style.txt",
        "--variables",
        json.dumps({"subject": "blue heron"}),
        "--reference",
        "../authoring/reference.png",
    )
    assert _record(prepared_b)["resolved_prompt"] == (
        "Sharp ink drawing.\n\nA blue heron under moonlight"
    )

    moved_a = records / "moved-a"
    shutil.copytree(records / "a", moved_a)
    shutil.rmtree(records / "a")
    inspected_a = _run(consumer).json(
        "asset-pipeline", "prompt-inspect", "--record", "../records/moved-a"
    )
    frozen = _record(inspected_a)
    assert frozen["record"] == str(moved_a.resolve())
    assert frozen["resolved_prompt"] == record_a["resolved_prompt"]
    assert Path(frozen["resolved_path"]).read_text() == frozen["resolved_prompt"]
    assert Path(frozen["references"][0]["path"]).read_bytes() == original_reference
    assert (
        frozen["references"][0]["sha256"]
        == hashlib.sha256(original_reference).hexdigest()
    )
    assert Path(inspected_a["preparation"]["handoff"]["prompt_path"]).is_relative_to(
        moved_a
    )
    assert all(
        Path(path).is_relative_to(moved_a)
        for path in inspected_a["preparation"]["handoff"]["references"]
    )

    revised = _run(author).json(
        "asset-pipeline",
        "prompt-revise",
        "--source-record",
        "../records/moved-a",
        "--record",
        "../records/revision",
        "--text",
        "A charcoal fox portrait",
        "--remove-style",
        "--variables",
        "{}",
        "--reference",
        "reference.png",
        "--requested-options",
        json.dumps({"quality": "high"}),
    )["revision"]
    revised_record = revised["preparation"]["record"]
    assert revised_record["mode"] == "plain"
    assert revised_record["resolved_prompt"] == "A charcoal fox portrait"
    assert revised_record["revised_from"] == str(moved_a.resolve())
    assert set(revised["changed_fields"]) >= {
        "mode",
        "resolved_prompt",
        "style",
        "references",
        "requested_options",
    }
    assert (
        _record(
            _run(consumer).json(
                "asset-pipeline", "prompt-inspect", "--record", "../records/moved-a"
            )
        )["resolved_prompt"]
        == frozen["resolved_prompt"]
    )

    before_failures = _tree(moved_a)
    missing = _run(consumer).error(
        "asset-pipeline",
        "prompt-register-output",
        "--record",
        "../records/moved-a",
        "--output",
        "missing.png",
        "--name",
        "result.png",
        code="invalid_params",
    )
    assert (
        "unavailable" in missing["message"].lower()
        or "invalid" in missing["message"].lower()
    )
    assert _tree(moved_a) == before_failures
    corrupt = consumer / "corrupt.png"
    corrupt.write_bytes(b"not png")
    _run(consumer).error(
        "asset-pipeline",
        "prompt-register-output",
        "--record",
        "../records/moved-a",
        "--output",
        "corrupt.png",
        "--name",
        "result.png",
        code="invalid_params",
    )
    assert _tree(moved_a) == before_failures

    output = consumer / "generated.png"
    _png(output, (40, 180, 70, 255))
    submitted = frozen["resolved_prompt"] + ", brighter lighting"
    registered = _run(consumer).json(
        "asset-pipeline",
        "prompt-register-output",
        "--record",
        "../records/moved-a",
        "--output",
        "generated.png",
        "--name",
        "result.png",
        "--submitted-prompt",
        submitted,
        "--caller-declarations",
        json.dumps({"tool": "native-agent-tool", "request_id": "unknown"}),
    )["prompt_record"]
    assert registered["generation_status"] == "unknown"
    assert len(registered["outputs"]) == 1
    saved_output = registered["outputs"][0]
    assert saved_output["submitted_prompt"] == submitted
    assert saved_output["submitted_prompt"] != registered["resolved_prompt"]
    assert saved_output["caller_declarations"] == {
        "tool": "native-agent-tool",
        "request_id": "unknown",
    }
    assert saved_output["reported_provider"] is None
    assert saved_output["reported_model"] is None
    assert saved_output["reported_options"] == {}
    assert Path(saved_output["file"]["path"]).read_bytes() == output.read_bytes()
    assert (
        saved_output["file"]["sha256"]
        == hashlib.sha256(output.read_bytes()).hexdigest()
    )

    registered_before_conflict = _tree(moved_a)
    _run(author).error(
        "asset-pipeline",
        "prompt-register-output",
        "--record",
        "../records/moved-a",
        "--output",
        "../consumer/generated.png",
        "--name",
        "result.png",
        code="already_exists",
    )
    assert _tree(moved_a) == registered_before_conflict
    conflict = records / "conflict"
    conflict.mkdir()
    marker = conflict / "keep.txt"
    marker.write_text("caller owned\n")
    _run(author).error(
        "asset-pipeline",
        "prompt-prepare",
        "--record",
        "../records/conflict",
        "--text",
        "must not overwrite",
        code="already_exists",
    )
    assert marker.read_text() == "caller owned\n"
