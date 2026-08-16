"""Godot project resolution (issue #32).

A scene operation runs against a Godot *project* so that ``res://`` paths and
inter-resource references resolve deterministically. The resolved directory is
handed to the engine as ``--path``; without it the engine's project — hence
``res://`` resolution — would depend on gda's current working directory.

Resolution precedence (highest first), mirroring ``gda.binary``:

1. An explicit path passed by the caller (the ``--project`` flag).
2. The ``GDA_PROJECT`` environment variable.
3. The current working directory.

An explicitly named directory (flag or env) must actually be a Godot project —
hold a ``project.godot`` — or it is a mistake we surface rather than run in the
wrong context. The cwd fallback counts as a project only when it holds the
marker; otherwise resolution yields ``None`` and gda runs *projectless*
(filesystem paths only), the behaviour before project context existed.
"""

import os
from collections.abc import Mapping
from pathlib import Path

GDA_PROJECT_ENV = "GDA_PROJECT"

# The file Godot uses to mark a directory as a project root.
PROJECT_MARKER = "project.godot"


def is_engine_virtual_path(path: str) -> bool:
    """True when ``path`` is an engine-resolved virtual path (``res://``, …).

    ADR-0006's one test for "the engine resolves this against the project, gda
    does not touch it" — ``res://``, ``user://`` and ``uid://`` all carry the
    ``://`` scheme separator, which a filesystem path never does. Owned here, in
    the project-resolution module, and read by both callers of the rule:
    :func:`gda.models.normalize_path` (which passes such a path through
    unexpanded) and :func:`path_outside_project` (which can make no filesystem
    statement about one).
    """
    return "://" in path


def path_outside_project(path: str, project: Path) -> Path | None:
    """The resolved location of ``path`` when it falls OUTSIDE ``project``.

    The containment check behind the "this target does not belong to the
    resolved project" refusal. Returns ``None`` when the path belongs to the
    project — either because it is an engine-virtual path, which by
    construction addresses the project the engine was launched with, or because
    its filesystem location is the project directory or a descendant of it.
    Otherwise it returns that location, so the caller can name *where* the
    target actually is in its diagnostic.

    Both sides are resolved before comparison: a caller's path may be relative
    to the cwd, and ``resolve_project_dir`` returns the directory as it was
    named (``--project /tmp/game``), so comparing raw values would call a
    contained path "outside" whenever a symlink sits on either side — on macOS
    the temp directory alone (``/tmp`` → ``/private/tmp``) is enough.
    ``resolve()`` is non-strict, so a path that does not exist still yields the
    location it would occupy rather than raising.
    """
    if is_engine_virtual_path(path):
        return None
    location = Path(path).expanduser().resolve()
    if location.is_relative_to(project.expanduser().resolve()):
        return None
    return location


def _project_or_raise(raw: str, source: str) -> Path:
    """Expand ``raw`` to a project directory, or raise if it is not one."""
    candidate = Path(raw).expanduser()
    if not (candidate / PROJECT_MARKER).exists():
        raise ValueError(
            f"{source} is not a Godot project (no {PROJECT_MARKER}): {candidate}"
        )
    return candidate


def resolve_project_dir(
    explicit: str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path | None:
    """Resolve the Godot project directory using flag > env > cwd precedence.

    Returns the project root to pass as ``--path``, or ``None`` to run
    projectless. Raises ``ValueError`` if an explicitly named directory (flag
    or env) is empty or is not a Godot project.
    """
    if env is None:
        env = os.environ
    if cwd is None:
        cwd = Path.cwd()

    if explicit is not None:
        # An explicit (even if empty) value is a deliberate choice; an empty
        # one is a mistake we surface rather than silently fall through.
        if not explicit:
            raise ValueError("explicit project path is empty")
        return _project_or_raise(explicit, "--project")

    env_value = env.get(GDA_PROJECT_ENV)
    if env_value:
        return _project_or_raise(env_value, f"${GDA_PROJECT_ENV}")

    cwd = Path(cwd)
    if (cwd / PROJECT_MARKER).exists():
        return cwd
    return None
