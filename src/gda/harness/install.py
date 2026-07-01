"""Install / uninstall the gda harness autoload in a project (ADR-0018).

``gda daemon start`` performs this **one-time, install-time write** (never a
per-launch mutation, which would race a concurrent editor and corrupt config):
it materializes the bundled harness under ``res://addons/`` and ensures its
``[autoload]`` entry in ``project.godot``. It is idempotent and order-preserving,
and reports whether it changed anything (``installed_harness``).

The write is Python-side because it happens *before* any engine session exists.
It mirrors the autoload semantics ``operations.gd`` uses for ``project
add-autoload`` (issue #119): the value is the ``res://`` path prefixed with ``*``
(the enabled-singleton form).

**Version self-sync (#225, D1).** ``_materialize`` prepends a leading GDScript
comment header ``# gda-harness-version: <N>`` (sourced from ``HARNESS_VERSION``,
NOT the package version — the harness changes far less often than ``gda`` ships).
Because that header is part of the materialized content, the version check **falls
out of the existing content-compare**: a mismatch re-materializes, a match is a
no-op (never an unconditional overwrite, which would bump mtime and trip the
concurrent-editor prompt). ``installed_harness_version`` reads the header back.

**Paired uninstall (#225, D2).** ``uninstall_harness`` removes the ``[autoload]``
entry **first**, then deletes the files — so a mid-failure leaves only a harmless
stray inert ``.gd``, never a dangling autoload pointing at a missing script (which an
exported game logs ``ERR_CONTINUE`` and skips at startup — error spam, not a hard
crash; ADR-0028). It is idempotent: a no-op success when the harness is not installed
(mirrors ``daemon stop``).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The autoload name and the res:// location the bundled harness is installed to.
HARNESS_AUTOLOAD_NAME = "GdaHarness"
HARNESS_RES_DIR = "addons/gda_harness"
HARNESS_FILE = "gda_harness.gd"
HARNESS_RES_PATH = f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}"

# Bumped when the bundled harness changes; the daemon self-syncs the installed
# copy to it (#225). The installed copy declares its version in a leading header
# (`# gda-harness-version: <N>`); a mismatch re-materializes via the content
# compare. NOT the package version — the harness changes far less often.
HARNESS_VERSION = "4"

_VERSION_HEADER_PREFIX = "# gda-harness-version:"
_AUTOLOAD_HEADER = "[autoload]"
_BUNDLED_HARNESS = Path(__file__).parent / HARNESS_FILE


@dataclass(frozen=True)
class HarnessInstall:
    """The outcome of an ``install_harness`` call (#225).

    ``changed`` is the existing ``installed_harness`` signal the daemon reports —
    True iff the file was (re)materialized OR the autoload entry was added/repointed.
    ``synced`` is True ONLY when an **already-installed** harness was rewritten to a
    new version/body (a stale→current resync — the ``harness_synced`` the daemon
    reports). A first install is NOT a sync: it is already visible via ``changed`` /
    ``installed_harness``, so ``synced`` stays False there. ``version`` is the
    version now installed on disk.
    """

    changed: bool
    synced: bool
    version: str


@dataclass(frozen=True)
class HarnessUninstall:
    """The outcome of an ``uninstall_harness`` call (#225).

    ``removed`` is True iff anything was removed (the autoload entry and/or the
    files); False is the idempotent no-op when the harness was not installed.
    """

    removed: bool


def _autoload_line() -> str:
    # Enabled-singleton form: the res:// path prefixed with "*" (issue #119).
    return f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"'


def _version_header() -> str:
    return f"{_VERSION_HEADER_PREFIX} {HARNESS_VERSION}"


def _materialized_content() -> str:
    """The exact bytes the installed harness should hold: version header + body."""
    return f"{_version_header()}\n{_BUNDLED_HARNESS.read_text(encoding='utf-8')}"


def _harness_dest(project: Path) -> Path:
    return project / HARNESS_RES_DIR / HARNESS_FILE


def installed_harness_version(project: Path) -> Optional[str]:
    """The version declared in the installed harness's header, or None if absent.

    Reads the leading ``# gda-harness-version: <N>`` comment ``_materialize``
    prepends. Returns None when no harness file is installed or its header is
    missing/unrecognized (treated as a mismatch -> re-materialize).
    """
    dest = _harness_dest(project)
    if not dest.exists():
        return None
    first = dest.read_text(encoding="utf-8").splitlines()[:1]
    if first and first[0].startswith(_VERSION_HEADER_PREFIX):
        return first[0][len(_VERSION_HEADER_PREFIX) :].strip()
    return None


def _materialize(project: Path) -> bool:
    """Write the bundled harness under res://addons; True iff it changed on disk.

    The destination content is the version header + the bundled body, so a version
    bump (or a body change) is a content difference — re-materialize only then,
    never unconditionally (an mtime bump would trip the concurrent-editor prompt).
    """
    dest = _harness_dest(project)
    content = _materialized_content()
    if dest.exists() and dest.read_text(encoding="utf-8") == content:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return True


def _ensure_autoload(text: str) -> tuple[str, bool]:
    """Ensure the harness autoload line is present in ``[autoload]``; (text, changed).

    The "already present" decision is scoped to the ``[autoload]`` section: only an
    EXACT GdaHarness line *inside* ``[autoload]`` is a no-op. There is no global
    early return on the line appearing anywhere in the file, so a same-named key in
    another section is never consulted, re-pointed, or removed (PR #247 review).
    """
    line = _autoload_line()
    lines = text.splitlines()
    trailing = "\n" if text.endswith("\n") else ""

    # Re-point an existing GdaHarness entry, or insert a fresh one — both scoped to
    # the [autoload] section, so a same-named key in another section is never
    # touched (PR #247 review; symmetric with _remove_autoload).
    section: Optional[str] = None
    autoload_header_index: Optional[int] = None
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        section = _section_of(stripped, section)
        if section != _AUTOLOAD_HEADER:
            continue
        if stripped == _AUTOLOAD_HEADER:
            if autoload_header_index is None:
                autoload_header_index = i
        elif stripped.startswith(f"{HARNESS_AUTOLOAD_NAME}="):
            # A GdaHarness entry inside [autoload]: a no-op when already exact,
            # otherwise re-point it in place.
            if stripped == line:
                return text, False
            lines[i] = line
            return "\n".join(lines) + trailing, True

    # An existing [autoload] section with no GdaHarness entry — insert right after
    # its header, preserving any sibling autoloads.
    if autoload_header_index is not None:
        lines.insert(autoload_header_index + 1, line)
        return "\n".join(lines) + trailing, True

    # No [autoload] section — append one at EOF (sections may appear in any order).
    base = text if text.endswith("\n") else text + "\n"
    return f"{base}\n{_AUTOLOAD_HEADER}\n\n{line}\n", True


def install_harness(project: Path) -> HarnessInstall:
    """Idempotently install the harness autoload into ``project`` (#225).

    Returns a :class:`HarnessInstall`: ``changed`` (the ``installed_harness`` the
    daemon reports — ``True`` on a first install or a re-materialize/re-point),
    ``synced`` (``True`` only when an **already-installed** harness was rewritten to
    a new version/body — the ``harness_synced`` the daemon reports), and the
    ``version`` now on disk.
    """
    existed = _harness_dest(project).exists()
    materialized = _materialize(project)
    project_godot = project / "project.godot"
    text = project_godot.read_text(encoding="utf-8")
    new_text, autoload_added = _ensure_autoload(text)
    if autoload_added:
        project_godot.write_text(new_text, encoding="utf-8")
    return HarnessInstall(
        changed=materialized or autoload_added,
        # A *resync*, not a first install: the file must have already existed AND
        # been rewritten (stale version/body → current). A first install rewrites
        # too, but is reported by ``changed`` / ``installed_harness`` (PR #247 review).
        synced=existed and materialized,
        version=HARNESS_VERSION,
    )


def _section_of(stripped: str, current: Optional[str]) -> Optional[str]:
    """The active INI section after a stripped line, or ``current`` if unchanged.

    A section header is ``[name]``; any other line leaves the section as-is. Used to
    scope harness-key edits to ``[autoload]`` so a same-named key in another section
    of ``project.godot`` is never touched (PR #247 review).
    """
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped
    return current


def _remove_autoload(text: str) -> tuple[str, bool]:
    """Drop the harness autoload line from ``project.godot`` text; (text, changed).

    Removes only the ``GdaHarness=...`` line **inside the ``[autoload]`` section**,
    leaving the section header and any sibling autoloads intact (the inverse of
    ``_ensure_autoload``). A same-named key in another section is left untouched.
    """
    lines = text.splitlines()
    section: Optional[str] = None
    kept: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        section = _section_of(stripped, section)
        if section == _AUTOLOAD_HEADER and stripped.startswith(
            f"{HARNESS_AUTOLOAD_NAME}="
        ):
            continue  # drop the autoload entry only
        kept.append(raw)
    if len(kept) == len(lines):
        return text, False
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(kept) + trailing, True


def _remove_files(project: Path) -> bool:
    """Delete the materialized harness file (and its now-empty addon dir); changed?"""
    dest = _harness_dest(project)
    removed = dest.exists()
    dest.unlink(missing_ok=True)
    addon_dir = project / HARNESS_RES_DIR
    if addon_dir.is_dir() and not any(addon_dir.iterdir()):
        addon_dir.rmdir()
    return removed


def uninstall_harness(project: Path) -> HarnessUninstall:
    """Idempotently remove the harness autoload and files from ``project`` (#225).

    Crash-safe ordering (ADR-0018, D2): strip the ``[autoload]`` entry **first**
    (a single atomic ``write_text``), then delete the files — so a mid-failure
    leaves only a harmless stray inert ``.gd``, never a dangling autoload pointing
    at a missing script (which an exported game logs ``ERR_CONTINUE`` and skips at
    startup — error spam, not a hard crash; ADR-0028). Returns a
    :class:`HarnessUninstall`; ``removed`` is ``False`` (a no-op success) when
    nothing is installed (mirrors ``daemon stop``).
    """
    project_godot = project / "project.godot"
    autoload_removed = False
    if project_godot.exists():
        text = project_godot.read_text(encoding="utf-8")
        new_text, autoload_removed = _remove_autoload(text)
        if autoload_removed:
            project_godot.write_text(new_text, encoding="utf-8")
    files_removed = _remove_files(project)
    return HarnessUninstall(removed=autoload_removed or files_removed)
