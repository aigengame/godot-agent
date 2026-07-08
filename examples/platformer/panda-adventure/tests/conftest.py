"""Game-local pytest fixtures for Panda Adventure.

The repo-root ``tests/conftest.py`` does not apply to this subtree (the root
``testpaths`` excludes the game dir), so this re-provides the bits the game's
tests need:

- an **engine gate** (``engine`` or ``e2e`` marker) that *fails loudly* — not
  skips — when no Godot binary resolves, reusing gda's resolver. The ``engine``
  tier is the fast one (the data-seam round-trip + logic seam drive one-shot
  ``gda``/``godot`` headless calls); the ``e2e`` tier is the daemon live loop.
- a ``gda`` fixture: a project-scoped ``gda <args> --project <GAME_DIR>`` runner
  whose stdout the caller parses (modeled on gda's own e2e helper + support.py).
- ``daemon_runtime_dir``: a SHORT ``XDG_RUNTIME_DIR`` so a real daemon's UDS
  ``sun_path`` does not overflow ``bind()`` (copied from the main repo's conftest).
- ``scripts/`` on ``sys.path`` so tests can ``import build_config``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from gda.binary import GODOT_BIN_ENV, resolve_godot_binary

# This subproject's root (== the Godot project's res://) and its tooling dirs.
GAME_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = GAME_DIR / "scripts"
# The Tool Script framework home (gADR-0011); ``tools/`` on the path makes each
# pipeline package importable by name (e.g. ``import balancing``), the same way
# ``scripts/`` is for ``build_config``.
TOOLS_DIR = GAME_DIR / "tools"

# Make the Python build tooling importable by name (e.g. ``import build_config``).
for _tooling in (SCRIPTS_DIR, TOOLS_DIR):
    if str(_tooling) not in sys.path:
        sys.path.insert(0, str(_tooling))

# Resolve gda as the MODULE in *this* interpreter's env (same-environment
# resolution, per support.py / ADR-0011), never a PATH-resolved global.
GDA_CMD = [sys.executable, "-m", "gda"]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "engine: needs a real Godot engine (fails loudly if missing); fast tier, "
        "not the daemon e2e tier",
    )
    # The asset pipeline's live acquire tier (gADR-0014): a real network fetch
    # (search-download) or a real image-gen API call (generation). Deselected in
    # CI (network, API keys, cost) and run on demand; the fast suite mocks the
    # acquire boundary instead. Registered here (the game's marker home) like the
    # engine tier, since this subproject has no pyproject of its own.
    config.addinivalue_line(
        "markers",
        "acquire_live: needs a live network / image-gen API (asset pipeline "
        "acquire); deselected in CI, run on demand",
    )


@pytest.fixture(autouse=True)
def _require_godot_engine(request: pytest.FixtureRequest) -> None:
    """Fail any selected ``engine``/``e2e`` test loudly when no Godot resolves.

    Keyed on the ``engine`` or ``e2e`` marker (a no-op otherwise) — both tiers
    drive a real engine. The binary is resolved here, not at import time, so a
    runtime ``$GDA_GODOT`` override is honored and a missing engine is a loud
    failure, not a silent skip.
    """
    is_e2e = request.node.get_closest_marker("e2e") is not None
    if not is_e2e and request.node.get_closest_marker("engine") is None:
        return
    # The headless (`engine`) tier needs Godot 4.4+; the live daemon (`e2e`) tier
    # needs 4.6+ (ADR-0021). Name the right floor so a too-old engine is diagnosable.
    floor = "4.6+ (the live/daemon tier)" if is_e2e else "4.4+ (the headless tier)"
    godot = resolve_godot_binary()
    if not godot.exists():
        pytest.fail(
            f"engine tests need a real Godot engine, but none was found at {godot}. "
            f"Install Godot at that path or set ${GODOT_BIN_ENV} to a {floor} binary."
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


@pytest.fixture
def daemon_runtime_dir(monkeypatch):
    """A SHORT ``XDG_RUNTIME_DIR`` for tests that bind a real gda-daemon socket.

    Copied from the main repo's ``tests/conftest.py``: a Unix-domain-socket path
    is bounded by the OS ``sun_path`` limit (104 bytes on macOS), and pytest's
    macOS ``tmp_path`` lives under a long ``/private/var/folders/...`` prefix, so
    the daemon's ``<runtime>/gda/<hash>.cli.sock`` overflows it and ``bind()``
    fails (the daemon never becomes ready and ``start`` times out). Point
    ``XDG_RUNTIME_DIR`` at a SHORT ``/tmp`` dir instead; the spawned daemon
    inherits it. UNIX only (the whole live stack is — guard with ``os.name``).
    """
    runtime = tempfile.mkdtemp(prefix="gda-", dir="/tmp")
    monkeypatch.setenv("XDG_RUNTIME_DIR", runtime)
    yield Path(runtime)
    shutil.rmtree(runtime, ignore_errors=True)
