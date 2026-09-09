"""Vector3 examples remain visible in the rendered help (#951)."""

import pytest
from typer.testing import CliRunner

from gda.cli import app
from tests.support import panel_text


@pytest.mark.parametrize("group", ["node", "game"])
def test_get_help_renders_literal_vector3_without_project_or_engine(group, tmp_path):
    result = CliRunner().invoke(
        app,
        [group, "get", "--godot", str(tmp_path / "absent-godot"), "--help"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    text = panel_text(result.stdout)
    assert "[x, y, z]" in text
    assert "rotation" in text and "radians" in text
    if group == "game":
        assert "--property" in text
        assert "position, rotation and scale are explicitly addressable" in text
