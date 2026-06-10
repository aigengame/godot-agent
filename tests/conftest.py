"""Shared pytest fixtures for gda's test tiers.

``godot_project`` is the reusable e2e scaffold (issue #18): a throwaway Godot
project for slices whose operations act on files inside a project. Later
domain slices (node, script, …) reuse it rather than growing their own.
"""

import pytest

# The minimal project.godot a Godot 4 engine accepts as a project root.
PROJECT_GODOT = """\
config_version=5

[application]

config/name="gda-e2e-fixture"
"""


@pytest.fixture
def godot_project(tmp_path):
    """A temp Godot project dir: ``project.godot`` scaffolded, cleanup owned by pytest."""
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    return tmp_path
