"""Install the gda harness autoload into a project (ADR-0018).

``gda daemon start`` performs this **one-time, install-time write** (never a
per-launch mutation, which would race a concurrent editor and corrupt config):
it materializes the bundled harness under ``res://addons/`` and ensures its
``[autoload]`` entry in ``project.godot``. It is idempotent and order-preserving,
and reports whether it changed anything (``installed_harness``).

The write is Python-side because it happens *before* any engine session exists.
It mirrors the autoload semantics ``operations.gd`` uses for ``project
add-autoload`` (issue #119): the value is the ``res://`` path prefixed with ``*``
(the enabled-singleton form). Version self-sync and paired uninstall are #225.
"""

from pathlib import Path

# The autoload name and the res:// location the bundled harness is installed to.
HARNESS_AUTOLOAD_NAME = "GdaHarness"
HARNESS_RES_DIR = "addons/gda_harness"
HARNESS_FILE = "gda_harness.gd"
HARNESS_RES_PATH = f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}"

# Bumped when the bundled harness changes; the daemon self-syncs the installed
# copy to it (#225). Unused by the install logic now — only re-materialize on a
# content difference — but the anchor lives here for #225.
HARNESS_VERSION = "0"

_AUTOLOAD_HEADER = "[autoload]"
_BUNDLED_HARNESS = Path(__file__).parent / HARNESS_FILE


def _autoload_line() -> str:
    # Enabled-singleton form: the res:// path prefixed with "*" (issue #119).
    return f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"'


def _materialize(project: Path) -> bool:
    """Write the bundled harness under res://addons; True iff it changed on disk."""
    dest = project / HARNESS_RES_DIR / HARNESS_FILE
    bundled = _BUNDLED_HARNESS.read_text(encoding="utf-8")
    if dest.exists() and dest.read_text(encoding="utf-8") == bundled:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(bundled, encoding="utf-8")
    return True


def _ensure_autoload(text: str) -> tuple[str, bool]:
    """Ensure the harness autoload line is present; return (text, changed)."""
    line = _autoload_line()
    if line in text:
        return text, False

    lines = text.splitlines()
    trailing = "\n" if text.endswith("\n") else ""

    # A GdaHarness entry pointing somewhere else — re-point it in place.
    for i, raw in enumerate(lines):
        if raw.strip().startswith(f"{HARNESS_AUTOLOAD_NAME}="):
            lines[i] = line
            return "\n".join(lines) + trailing, True

    # An existing [autoload] section — insert right after its header, preserving
    # any sibling autoloads.
    for i, raw in enumerate(lines):
        if raw.strip() == _AUTOLOAD_HEADER:
            lines.insert(i + 1, line)
            return "\n".join(lines) + trailing, True

    # No [autoload] section — append one at EOF (sections may appear in any order).
    base = text if text.endswith("\n") else text + "\n"
    return f"{base}\n{_AUTOLOAD_HEADER}\n\n{line}\n", True


def install_harness(project: Path) -> bool:
    """Idempotently install the harness autoload into ``project``.

    Returns whether anything changed (the ``installed_harness`` the daemon
    reports): ``True`` on a first install or a re-materialize/re-point, ``False``
    when the harness file and the autoload entry are already in place.
    """
    materialized = _materialize(project)
    project_godot = project / "project.godot"
    text = project_godot.read_text(encoding="utf-8")
    new_text, autoload_added = _ensure_autoload(text)
    if autoload_added:
        project_godot.write_text(new_text, encoding="utf-8")
    return materialized or autoload_added
