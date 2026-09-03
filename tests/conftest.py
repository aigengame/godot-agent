"""Shared pytest fixtures for gda's test tiers.

``godot_project`` is the reusable e2e scaffold (issue #18): a throwaway Godot
project for slices whose operations act on files inside a project. Later
domain slices (node, script, …) reuse it rather than growing their own.

``_require_godot_engine`` is the single missing-engine gate for the whole e2e
tier (issue #106): any ``e2e``-marked test selected without a resolvable Godot
binary fails loudly here, naming the resolved path, rather than silently
skipping per-module.

``project_godot`` (issue #180) is the single builder for every e2e
``project.godot``. It always disables Godot's default desktop file logging, so
**no** e2e engine launch writes a ``user://logs/godot.log``. Why this matters:
Godot resolves ``user://`` to ``$HOME/Library/Application Support/Godot/
app_userdata/<config/name>/`` and, on desktop, attaches a ``RotatedFileLogger``
that races in ``rotate_file()`` when concurrent launches share one log dir.
Overlapping e2e runs (parallel agents / a CI matrix) then abort with what looks
like ``engine_crashed`` but is purely test-infra contention. Removing the log
write at the source makes the e2e tier reliable by default — no ``fresh-HOME``
workaround needed. The operative key is the **platform override**
``debug/file_logging/enable_file_logging.pc``: the base key defaults to
``false`` but Godot's ``.pc`` feature-tagged override defaults to ``true`` on
desktop and wins at startup (godot ``main/main.cpp``), so disabling the base
alone is a no-op — the ``.pc`` override must be set too. Every e2e test that
needs its own ``project.godot`` must build it through this helper (passing its
extra sections via ``extra``) so the logging stays disabled.
"""

import shutil
import tempfile
from pathlib import Path

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


# Disables Godot's default desktop file logging so an e2e launch writes no
# ``user://logs/godot.log`` (issue #180). The ``.pc`` line is the operative one:
# on desktop the ``.pc`` feature override (default ``true``) wins over the base
# key (default ``false``), so both are set off.
_DEBUG_NO_FILE_LOGGING = """\
[debug]

file_logging/enable_file_logging=false
file_logging/enable_file_logging.pc=false
"""


def project_godot(name: str = "gda-e2e-fixture", extra: str = "") -> str:
    """Build a ``project.godot`` with file logging disabled (issue #180).

    The single source of truth for every e2e ``project.godot``. ``name`` sets
    ``config/name`` (which is also the ``user://`` dir name); ``extra`` appends
    further sections (``[autoload]``, ``run/main_scene``, ``[editor_plugins]``,
    …) verbatim. File logging is always disabled so no e2e launch writes to a
    shared ``user://logs`` dir.
    """
    body = f'config_version=5\n\n[application]\n\nconfig/name="{name}"\n'
    if extra:
        body += "\n" + extra.rstrip("\n") + "\n"
    return body + "\n" + _DEBUG_NO_FILE_LOGGING


# The minimal project.godot a Godot 4 engine accepts as a project root, with
# e2e file logging disabled (issue #180). Built through ``project_godot`` so the
# logging-disable rationale lives in exactly one place.
PROJECT_GODOT = project_godot()

# The live tier's scaffold: a project that names a main scene, and the two main
# scenes its modules run. A live module needs a game to launch, so the eleven
# that launch one (`daemon`, `game`, `input`, `screen`, `perf`, `diag`, `logger`,
# `mcp_live`, `live_number_transport`, `write_value_fidelity` and the harness
# install tests) take the project from here; `daemon`, `perf` and `mcp_live`
# take the node-path scene, `diag` and `logger` the scripted one. The copies
# they carried were one edit away from disagreeing about what "the live fixture
# project" is, so they live here beside the builder that makes them. A module
# whose scene is its own subject (the coloured rect `screen` captures, the bare
# root the harness-install gate watches, the reference graph `project analysis`
# walks) keeps that scene local — it is not a copy of anything.
LIVE_PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

# A main scene with a child node, for a live module that addresses a node path.
LIVE_MAIN_TSCN = (
    "[gd_scene format=3]\n\n"
    '[node name="Main" type="Node2D"]\n\n'
    '[node name="Player" type="Node2D" parent="."]\n'
)

# A main scene that runs `res://main.gd`, for a live module whose subject is what
# the running game PRINTS (the session log, the runtime errors read back).
SCRIPTED_MAIN_TSCN = (
    "[gd_scene load_steps=2 format=3]\n\n"
    '[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
    '[node name="Main" type="Node2D"]\n'
    'script = ExtResource("1")\n'
)


@pytest.fixture
def godot_project(tmp_path):
    """A temp Godot project dir: ``project.godot`` scaffolded, cleanup owned by pytest."""
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    return tmp_path


@pytest.fixture
def daemon_runtime_dir(monkeypatch):
    """A SHORT ``XDG_RUNTIME_DIR`` for tests that bind a real gda-daemon socket (#7).

    A Unix-domain-socket path is bounded by the OS ``sun_path`` limit — **104
    bytes on macOS**, 108 on Linux. pytest's macOS ``tmp_path`` lives under a long
    ``/private/var/folders/...`` prefix, so the daemon's
    ``<runtime>/gda/<hash>.cli.sock`` overflows the limit and ``bind()`` fails (the
    daemon then never becomes ready and ``start`` times out). Any test that starts
    a **real** daemon must therefore point ``XDG_RUNTIME_DIR`` at a SHORT directory
    — ``/tmp`` is short and POSIX-present — NOT ``tmp_path``. This fixture yields
    that dir (and cleans it up); the daemon's discovery (``gda.daemon.discovery``)
    reads ``XDG_RUNTIME_DIR`` and the spawned daemon inherits it.

    Tests that only *derive* socket paths, or that expect NO daemon (so never
    ``bind()``), can keep using ``tmp_path``; only a real bind needs this. UNIX
    only (the whole live stack is — ADR-0021), so use it under an ``os.name ==
    'posix'`` guard.
    """
    runtime = tempfile.mkdtemp(prefix="gda-", dir="/tmp")
    monkeypatch.setenv("XDG_RUNTIME_DIR", runtime)
    yield Path(runtime)
    shutil.rmtree(runtime, ignore_errors=True)


@pytest.fixture
def windowed_host():
    """Gate a test that needs a real windowed engine session (#345, #667).

    A fixture rather than a ``skipif`` marker because the reaction is not uniform: a
    confined run must FAIL, and a ``skipif`` can only skip. The policy itself lives in
    one place (``tests.support.require_windowed_host``), shared with the post-start
    race path so both cannot drift apart again.
    """
    from tests.support import require_windowed_host

    require_windowed_host()
