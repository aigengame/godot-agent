"""Shared pytest fixtures for gda's test tiers.

``godot_project`` is the reusable e2e scaffold (issue #18): a throwaway Godot
project for slices whose operations act on files inside a project. Later
domain slices (node, script, …) reuse it rather than growing their own.

``_require_godot_engine`` is the single missing-engine gate for the whole e2e
tier (issue #106): any ``e2e``-marked test selected without a resolvable Godot
binary fails loudly here, naming the resolved path, rather than silently
skipping per-module.
"""

import pytest

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary


@pytest.fixture(autouse=True)
def _require_godot_engine(request):
    """Fail any selected e2e test loudly when no Godot engine resolves.

    Keyed on the ``e2e`` marker, so it is a no-op for the fake-based S2/S3
    tiers. The binary is resolved here (not at import time) so a runtime
    ``$GDA_GODOT`` override is honored, and a missing engine is a loud failure
    instead of a silent skip — the e2e tier is a mandatory local gate.
    """
    if request.node.get_closest_marker("e2e") is None:
        return
    godot = resolve_godot_binary()
    if not godot.exists():
        pytest.fail(
            f"e2e tests need a real Godot engine, but none was found at {godot}. "
            f"Install Godot at that path or set ${GODOT_BIN_ENV} to a 4.4+ binary."
        )


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
