"""Native-result admission for the bounded Blender concept consumer."""

import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image
import pytest

from gda_assets.adapters.concept_authoring import BlenderReferenceBlockoutAuthor
from gda_assets.application.ports import PortFailure
from gda_assets.domain.concept import (
    ConceptAuthorRequest,
    ConceptBrief,
    ConceptBriefSnapshot,
    ConceptSelection,
    SelectedConcept,
)


def _selection(root: Path) -> ConceptSelection:
    root.mkdir()
    image = root / "selected.png"
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(image)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    return ConceptSelection(
        1,
        root,
        ConceptBrief("model", "block", "flat", views=("front",)),
        ConceptBriefSnapshot(root / "concept-brief.json", "brief", 1),
        (
            SelectedConcept(
                0,
                "../attempt/prompt.json",
                "selected.png",
                "prompt-sha256",
                image,
                digest,
                image.stat().st_size,
                2,
                2,
                True,
            ),
        ),
    )


@pytest.mark.parametrize("native_result", ["null", "[]", "oversized"])
def test_blender_refuses_non_object_or_oversized_native_result(
    tmp_path, monkeypatch, native_result
):
    selection = _selection(tmp_path / "handoff")
    executable = tmp_path / "blender"
    executable.write_text("fake")
    executable.chmod(0o755)

    def fake_run(argv, **_kwargs):
        request = json.loads(Path(argv[-1]).read_text())
        result = Path(request["result"])
        result.write_text(
            "x" * 131073 if native_result == "oversized" else native_result
        )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PortFailure) as raised:
        BlenderReferenceBlockoutAuthor().author(
            ConceptAuthorRequest(
                selection.handoff,
                "blender-reference-blockout",
                tmp_path / "output",
                blender_executable=executable,
            ),
            selection,
        )

    assert raised.value.code == "concept_author_failed"
    assert "authoring result" in str(raised.value)
