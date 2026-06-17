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


@pytest.fixture
def godot_project(tmp_path):
    """A temp Godot project dir: ``project.godot`` scaffolded, cleanup owned by pytest."""
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    return tmp_path
