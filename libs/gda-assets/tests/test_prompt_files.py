from pathlib import Path
import os

from PIL import Image
import pytest

from gda_assets.api import (
    PromptOutputRequest,
    PromptPrepareRequest,
    PromptRevisionRequest,
    inspect_prompt,
    prepare_prompt,
    register_prompt_output,
    revise_prompt,
)
from gda_assets.application.ports import PortFailure


def _png(path: Path, color: str) -> bytes:
    Image.new("RGB", (3, 2), color).save(path)
    return path.read_bytes()


def test_prepare_snapshots_template_style_reference_and_inspects_from_other_cwd(
    tmp_path,
):
    template = tmp_path / "template.txt"
    style = tmp_path / "style.txt"
    reference = tmp_path / "reference.png"
    template.write_text("A $subject at ${place}")
    style.write_text("watercolor")
    original_png = _png(reference, "red")
    record_path = tmp_path / "records" / "attempt-a"

    prepared = prepare_prompt(
        PromptPrepareRequest(
            record_path,
            template=template,
            style=style,
            variables={"subject": "fox", "place": "dawn"},
            references=(reference,),
            producer="native-image-tool",
            requested_options={"size": "1024x1024", "quality": "high"},
        )
    )
    template.write_text("changed $subject at $place")
    style.write_text("changed")
    _png(reference, "blue")
    second = prepare_prompt(
        PromptPrepareRequest(
            tmp_path / "records" / "attempt-b",
            template=template,
            style=style,
            variables={"subject": "owl", "place": "night"},
            references=(reference,),
        )
    )
    relocated = tmp_path / "relocated-attempt-a"
    record_path.rename(relocated)
    previous = Path.cwd()
    os.chdir(tmp_path.parent)
    try:
        inspected = inspect_prompt(relocated)
    finally:
        os.chdir(previous)

    assert prepared.handoff.action == "external_generation_required"
    assert prepared.handoff.generation_status == "unknown"
    assert inspected.record.resolved_prompt == "watercolor\n\nA fox at dawn"
    assert inspected.record.references[0].path.read_bytes() == original_png
    assert second.record.references[0].path.read_bytes() != original_png
    assert second.record.resolved_prompt == "changed\n\nchanged owl at night"
    assert inspected.handoff.references == (inspected.record.references[0].path,)
    assert inspected.record.template is not None
    assert not inspected.record.template.path.is_relative_to(Path.cwd())


def test_destination_conflict_and_missing_inputs_fail_without_replacing_record(
    tmp_path,
):
    record = tmp_path / "attempt"
    prepare_prompt(PromptPrepareRequest(record, text="first"))

    with pytest.raises(PortFailure) as conflict:
        prepare_prompt(PromptPrepareRequest(record, text="second"))
    assert conflict.value.code == "destination_conflict"
    assert inspect_prompt(record).record.resolved_prompt == "first"

    missing = tmp_path / "missing"
    with pytest.raises(PortFailure) as invalid:
        prepare_prompt(
            PromptPrepareRequest(
                missing, template=tmp_path / "absent.txt", variables={"x": "y"}
            )
        )
    assert invalid.value.code == "invalid_prompt"
    assert not missing.exists()


def test_revision_uses_saved_inputs_and_reports_only_semantic_changes(tmp_path):
    template = tmp_path / "template.txt"
    style = tmp_path / "style.txt"
    template.write_text("$subject")
    style.write_text("graphite")
    original = prepare_prompt(
        PromptPrepareRequest(
            tmp_path / "a",
            template=template,
            style=style,
            variables={"subject": "fox"},
        )
    )
    template.write_text("external drift")
    style.write_text("external drift")

    revision = revise_prompt(
        PromptRevisionRequest(
            original.record.record,
            tmp_path / "b",
            variables={"subject": "wolf"},
        )
    )

    assert revision.preparation.record.resolved_prompt == "graphite\n\nwolf"
    assert revision.changed_fields == ("variables", "resolved_prompt")
    assert (
        inspect_prompt(original.record.record).record.resolved_prompt
        == "graphite\n\nfox"
    )


def test_registration_is_separate_local_association_and_preserves_base_record(tmp_path):
    record_path = tmp_path / "attempt"
    prepare_prompt(
        PromptPrepareRequest(
            record_path, text="prepared", requested_options={"seed": 7}
        )
    )
    base_json = (record_path / "record.json").read_bytes()
    output = tmp_path / "result.png"
    output_bytes = _png(output, "green")

    registered = register_prompt_output(
        PromptOutputRequest(
            record_path,
            output,
            "candidate.png",
            submitted_prompt="actually submitted",
            caller_declarations={"generation_completed": True, "tool": "imagegen"},
            reported_provider="provider-a",
            reported_model="model-b",
            reported_options={"quality": "high"},
        )
    )

    assert (record_path / "record.json").read_bytes() == base_json
    assert registered.generation_status == "unknown"
    assert registered.outputs[0].file.path.read_bytes() == output_bytes
    assert registered.outputs[0].caller_declarations["generation_completed"] is True
    assert registered.outputs[0].reported_provider == "provider-a"
    assert registered.requested_options == {"seed": 7}
    assert inspect_prompt(record_path).record.outputs == registered.outputs


def test_invalid_registration_preserves_prompt_and_existing_outputs(tmp_path):
    record = tmp_path / "attempt"
    prepare_prompt(PromptPrepareRequest(record, text="prompt"))
    invalid = tmp_path / "bad.png"
    invalid.write_text("not png")

    with pytest.raises(PortFailure) as failure:
        register_prompt_output(PromptOutputRequest(record, invalid, "bad.png"))

    assert failure.value.code == "invalid_prompt"
    assert inspect_prompt(record).record.outputs == ()
    assert not (record / "outputs" / "bad.png").exists()


def test_registration_limit_refuses_next_output_and_keeps_record_readable(tmp_path):
    record = tmp_path / "attempt"
    prepare_prompt(PromptPrepareRequest(record, text="prompt"))
    image = tmp_path / "image.png"
    Image.new("RGB", (1, 1), "blue").save(image)
    for index in range(64):
        register_prompt_output(PromptOutputRequest(record, image, f"{index}.png"))

    with pytest.raises(PortFailure, match="at most 64"):
        register_prompt_output(PromptOutputRequest(record, image, "overflow.png"))

    assert len(inspect_prompt(record).record.outputs) == 64
    assert not (record / "outputs" / "overflow.png").exists()


def test_invalid_output_directory_fails_without_modifying_existing_file(tmp_path):
    record = tmp_path / "attempt"
    prepare_prompt(PromptPrepareRequest(record, text="prompt"))
    (record / "outputs").write_bytes(b"existing project file")
    image = tmp_path / "image.png"
    Image.new("RGB", (1, 1), "blue").save(image)

    with pytest.raises(PortFailure, match="output directory"):
        register_prompt_output(PromptOutputRequest(record, image, "image.png"))

    assert (record / "outputs").read_bytes() == b"existing project file"
