"""Game-local pytest fixtures for Panda Adventure.

The repo-root ``tests/conftest.py`` does not apply to this subtree (the root
``testpaths`` excludes the game dir), so this re-provides the bits the game's
tests need:

- an **engine gate** (``engine`` marker) that *fails loudly* — not skips — when
  no Godot binary resolves, reusing gda's resolver. Distinct from the daemon
  ``e2e`` tier: the data-seam round-trip drives a one-shot ``gda`` headless op and
  needs the engine, yet runs in the fast (``not e2e``) tier.
- a ``gda`` fixture: a project-scoped ``gda <args> --project <GAME_DIR>`` runner
  whose stdout the caller parses (modeled on gda's own e2e helper + support.py).
- ``scripts/`` on ``sys.path`` so tests can ``import build_config``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary

# This subproject's root (== the Godot project's res://) and its tooling dir.
GAME_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = GAME_DIR / "scripts"

# Make the Python build tooling importable by name (e.g. ``import build_config``).
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Resolve gda as the MODULE in *this* interpreter's env (same-environment
# resolution, per support.py / ADR-0011), never a PATH-resolved global.
GDA_CMD = [sys.executable, "-m", "gda"]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "engine: needs a real Godot engine (fails loudly if missing); fast tier, "
        "not the daemon e2e tier",
    )


@pytest.fixture(autouse=True)
def _require_godot_engine(request: pytest.FixtureRequest) -> None:
    """Fail any selected ``engine``-marked test loudly when no Godot resolves.

    Keyed on the ``engine`` marker (a no-op otherwise). The binary is resolved
    here, not at import time, so a runtime ``$GDA_GODOT`` override is honored and
    a missing engine is a loud failure, not a silent skip.
    """
    if request.node.get_closest_marker("engine") is None:
        return
    godot = resolve_godot_binary()
    if not godot.exists():
        pytest.fail(
            f"engine tests need a real Godot engine, but none was found at {godot}. "
            f"Install Godot at that path or set ${GODOT_BIN_ENV} to a 4.4+ binary."
        )


@pytest.fixture
def gda():
    """A project-scoped ``gda`` runner bound to this game's ``res://``.

    Returns a callable ``gda(*args) -> CompletedProcess`` that runs
    ``python -m gda <args> --project <GAME_DIR>`` and captures text output; the
    caller parses ``stdout`` (a single JSON object when invoked with ``--json``)
    and branches on ``returncode``. ``GDA_GODOT`` is inherited from the
    environment.
    """

    def _gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--project", str(GAME_DIR)],
            capture_output=True,
            text=True,
        )

    return _gda
