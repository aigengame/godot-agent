"""Imported embedded-albedo coverage for static model content (#954)."""

import pytest

from tests.albedo_support import write_albedo_glb
from tests.conftest import project_godot
from tests.support import Gda


pytestmark = pytest.mark.e2e


def test_embedded_albedo_only_change_changes_complete_content_digest(
    tmp_path, monkeypatch
):
    model = tmp_path / "model.glb"
    (tmp_path / "project.godot").write_text(
        project_godot(
            name="gda-embedded-albedo-content",
            extra='[rendering]\nrenderer/rendering_method="gl_compatibility"',
        )
    )
    monkeypatch.setenv("GDA_USER_DATA_ROOT", str(tmp_path / "user-data"))
    run = Gda(tmp_path, json_output=True, timeout=120)

    write_albedo_glb(model, color=(240, 40, 80, 255))
    run.json("resource", "import", "res://model.glb")
    first = run.json("resource", "inspect-model-content", "--path", "res://model.glb")[
        "content"
    ]

    write_albedo_glb(model, color=(20, 170, 230, 255))
    run.json("resource", "import", "res://model.glb")
    second = run.json("resource", "inspect-model-content", "--path", "res://model.glb")[
        "content"
    ]

    assert first["complete"] is True
    assert second["complete"] is True
    assert first["unsupported"] == second["unsupported"] == []
    assert first["omitted"] == second["omitted"] == []
    assert (first["nodes"], first["surfaces"], first["vertices"]) == (
        second["nodes"],
        second["surfaces"],
        second["vertices"],
    )
    assert first["digest"] != second["digest"]
