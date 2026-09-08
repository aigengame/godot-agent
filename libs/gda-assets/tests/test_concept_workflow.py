from pathlib import Path
import json
import shutil

from PIL import Image
import pytest

from gda_assets.adapters.concept_files import ConceptFiles
from gda_assets.api import (
    ConceptAuthorRequest,
    ConceptCandidate,
    ConceptPrepareRequest,
    ConceptSelectRequest,
    PromptOutputRequest,
    prepare_concept,
    register_prompt_output,
    select_concept,
)
from gda_assets.application.concept import author_concept
from gda_assets.application.ports import PortFailure


def _brief(path: Path, *, use: str = "model") -> None:
    path.write_text(
        json.dumps(
            {
                "use": use,
                "subject": "fox courier",
                "style": "ink wash",
                "views": ["front", "side"],
                "poses": [],
                "instructions": "Keep the silhouette clear.",
            }
        )
    )


def _png(path: Path, color: str) -> bytes:
    Image.new("RGB", (4, 3), color).save(path)
    return path.read_bytes()


def _candidate(
    tmp_path: Path, name: str, color: str, *, completed: bool, use: str = "model"
):
    brief = tmp_path / f"{name}-brief.json"
    record = tmp_path / f"{name}-record"
    image = tmp_path / f"{name}.png"
    _brief(brief, use=use)
    prepare_concept(ConceptPrepareRequest(brief, record, producer="imagegen"))
    _png(image, color)
    register_prompt_output(
        PromptOutputRequest(
            record,
            image,
            f"{name}.png",
            caller_declarations={"generation_completed": completed},
        )
    )
    return record, image


def test_prepare_saves_brief_and_keeps_generation_unknown(tmp_path):
    brief = tmp_path / "brief.json"
    record = tmp_path / "attempt"
    _brief(brief)

    result = prepare_concept(
        ConceptPrepareRequest(
            brief, record, producer="imagegen", requested_options={"size": "1024x1024"}
        )
    )

    assert result.prompt.handoff.action == "external_generation_required"
    assert result.prompt.record.generation_status == "unknown"
    assert result.brief_snapshot.path == record / "concept-brief.json"
    assert result.brief_snapshot.path.is_file()
    assert "Subject: fox courier" in result.prompt.record.resolved_prompt


def test_brief_unknown_field_is_rejected_before_prompt_record_creation(tmp_path):
    brief = tmp_path / "brief.json"
    record = tmp_path / "attempt"
    _brief(brief)
    value = json.loads(brief.read_text())
    value["instruction"] = "Keep red eyes"
    brief.write_text(json.dumps(value))

    with pytest.raises(PortFailure) as failure:
        prepare_concept(ConceptPrepareRequest(brief, record))

    assert failure.value.code == "invalid_concept"
    assert not record.exists()


def test_select_pins_only_ordered_completed_candidates_and_survives_move(tmp_path):
    red_record, red_source = _candidate(tmp_path, "red", "red", completed=True)
    blue_record, _ = _candidate(tmp_path, "blue", "blue", completed=True)
    handoff = tmp_path / "handoff"

    selection = select_concept(
        ConceptSelectRequest(
            red_record,
            handoff,
            (ConceptCandidate(blue_record, "blue.png"),),
        )
    )
    selected_bytes = selection.selected[0].path.read_bytes()
    _png(red_source, "green")
    shutil.rmtree(red_record)
    shutil.rmtree(blue_record)
    moved = tmp_path / "moved-handoff"
    handoff.rename(moved)

    loaded = ConceptFiles().load_handoff(moved)

    assert loaded.selected[0].output == "blue.png"
    assert loaded.selected[0].path.read_bytes() == selected_bytes
    assert len(loaded.selected[0].resolved_prompt_sha256) == 64
    assert loaded.authoring_status == "ready"
    assert "self-contained" in loaded.limitations[0]


def test_unknown_completion_stops_before_handoff_creation(tmp_path):
    record, _ = _candidate(tmp_path, "unknown", "red", completed=False)
    handoff = tmp_path / "handoff"

    with pytest.raises(PortFailure) as failure:
        select_concept(
            ConceptSelectRequest(
                record,
                handoff,
                (ConceptCandidate(record, "unknown.png"),),
            )
        )

    assert failure.value.code == "concept_candidate_incomplete"
    assert "caller-declared" in str(failure.value)
    assert not handoff.exists()


class _AuthorSpy:
    def __init__(self):
        self.called = False

    def author(self, request, selection):
        self.called = True
        raise AssertionError("test spy has no authoring result")


def test_invalid_author_request_stops_before_consumer(tmp_path):
    record, _ = _candidate(tmp_path, "ready", "red", completed=True, use="sprite")
    handoff = tmp_path / "handoff"
    select_concept(
        ConceptSelectRequest(record, handoff, (ConceptCandidate(record, "ready.png"),))
    )
    spy = _AuthorSpy()

    with pytest.raises(PortFailure, match="requires a sheet layout"):
        author_concept(
            ConceptAuthorRequest(
                handoff, "sprite-sheet-reference", tmp_path / "output"
            ),
            files=ConceptFiles(),
            author=spy,
        )

    assert spy.called is False
    assert not (tmp_path / "output").exists()


def test_tampered_completion_or_selected_bytes_invalidates_handoff(tmp_path):
    record, _ = _candidate(tmp_path, "ready", "red", completed=True)
    handoff = tmp_path / "handoff"
    selection = select_concept(
        ConceptSelectRequest(record, handoff, (ConceptCandidate(record, "ready.png"),))
    )
    data = json.loads((handoff / "handoff.json").read_text())
    data["selected"][0]["generation_completed_by_caller"] = False
    (handoff / "handoff.json").write_text(json.dumps(data))
    with pytest.raises(PortFailure) as failure:
        ConceptFiles().load_handoff(handoff)
    assert failure.value.code == "invalid_concept_handoff"

    data["selected"][0]["generation_completed_by_caller"] = True
    original_width = data["selected"][0]["width"]
    data["selected"][0]["width"] = original_width + 1
    (handoff / "handoff.json").write_text(json.dumps(data))
    with pytest.raises(PortFailure, match="changed"):
        ConceptFiles().load_handoff(handoff)

    data["selected"][0]["width"] = original_width
    (handoff / "handoff.json").write_text(json.dumps(data))
    selection.selected[0].path.write_bytes(b"changed")
    with pytest.raises(PortFailure):
        ConceptFiles().load_handoff(handoff)
