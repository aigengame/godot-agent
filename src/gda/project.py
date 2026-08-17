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


# The engine-resolved virtual path schemes ADR-0006 names. An exact prefix set,
# NOT a "contains ://" test: a colon is a legal POSIX filename character, so
# `/work/outside://deck.gd` is an ordinary — and ordinarily *outside* —
# filesystem path that a substring test would wave through as virtual.
ENGINE_VIRTUAL_PREFIXES = ("res://", "user://", "uid://")


def is_engine_virtual_path(path: str) -> bool:
    """True when ``path`` is an engine-resolved virtual path (``res://``, …).

    ADR-0006's one test for "the engine resolves this against the project, gda
    does not touch it", decided by the documented scheme PREFIXES
    (:data:`ENGINE_VIRTUAL_PREFIXES`) rather than by looking for ``://``
    anywhere in the string. Owned here, in the project-resolution module, and
    read by both callers of the rule: :func:`gda.models.normalize_path` (which
    passes such a path through unexpanded) and :func:`path_outside_project`
    (which can make no filesystem statement about one).
    """
    return path.startswith(ENGINE_VIRTUAL_PREFIXES)


def _lexical_abs(path: Path) -> Path:
    """``path`` made absolute and ``..``-free WITHOUT following symlinks.

    ``os.path.abspath`` is by definition ``normpath(join(os.getcwd(), path))``:
    it anchors a relative path at the cwd and collapses ``..`` textually, so a
    symlink on the way keeps the spelling the caller used. That is the opposite
    of ``Path.resolve()``, and both readings are needed — see
    :func:`path_outside_project`.
    """
    return Path(os.path.abspath(path))


def _has_dotdot(path: Path) -> bool:
    """True when ``path``'s spelling contains a ``..`` traversal component."""
    return ".." in path.parts


def project_anchored(path: str, project: Path) -> Path:
    """``path`` as the ENGINE will address it under ``--path project``.

    A relative filesystem path is anchored at the PROJECT, not at gda's cwd,
    because that is what the engine does: launched with ``--path <project>``, a
    one-shot op that opens ``deck.gd`` opens ``<project>/deck.gd`` regardless of
    where gda was invoked (verified against the engine). It is also what the
    README promises — point gda at a project once and relative paths resolve
    inside it. An absolute path is already fully addressed and is returned
    unchanged; ``~`` is expanded either way.

    The single anchoring rule, so the containment check and the engine cannot
    disagree about which file a relative argument names.
    """
    target = Path(path).expanduser()
    if target.is_absolute():
        return target
    return project.expanduser() / target


def path_outside_project(path: str, project: Path) -> Path | None:
    """The location of ``path`` when it falls OUTSIDE ``project``.

    The containment check behind the "this target does not belong to the
    resolved project" refusal. Returns ``None`` when the path belongs to the
    project, and otherwise the target's real location, so the caller can name
    *where* it actually is in its diagnostic.

    An engine-virtual path is inside by construction: it addresses the project
    the engine was launched with, and gda can make no filesystem statement
    about one.

    A filesystem path is first anchored the way the engine will address it
    (:func:`project_anchored`), then read in up to two ways — it belongs to the
    project when EITHER says so, because a symlink makes the two answer
    different, equally true questions:

    - **Resolved** (``Path.resolve()``, symlinks followed): "are these two
      spellings the same place?" The project may be named by one spelling and
      the target by another — on macOS the temp directory alone (``/tmp`` →
      ``/private/tmp``) is enough — and only this reading sees through that.
      Always consulted.
    - **Lexical** (:func:`_lexical_abs`, symlinks preserved): "did the caller
      address this file through the project's own tree?" A monorepo that links
      a shared library into the project (``game/addons/lib -> ../../libs/lib``)
      answers yes, and so does the engine — Godot walks the project directory
      and follows that link, so the file really is in the project's ``res://``
      namespace. Refusing it on its ``resolve()``d location would reject a call
      that works, in a message naming a path the caller never typed.

    The lexical reading is only sound while no ``..`` is in play, so it is
    consulted ONLY when neither the anchored candidate nor the project spelling
    carries a ``..`` component. A ``..`` that follows a symlink collapses
    textually to a place the filesystem never visits — ``game/pivot/../deck.gd``
    with ``game/pivot -> ../outside/deep`` reads as ``game/deck.gd`` lexically
    while really naming ``outside/deck.gd`` — so trusting the lexical reading
    there would accept a target that is genuinely outside. Without a ``..``, a
    symlink can only redirect *downward* from a path that does start inside the
    project, which is the legitimate case above. When the guard withholds the
    lexical reading, containment falls back to the resolved reading alone: a
    symlinked-in file addressed with a ``..`` in its path is refused, and the
    caller can name it without the ``..``.

    ``resolve()`` is non-strict, so a path that does not exist still yields the
    location it would occupy rather than raising.
    """
    if is_engine_virtual_path(path):
        return None
    root = project.expanduser()
    candidate = project_anchored(path, project)
    location = candidate.resolve()
    if location.is_relative_to(root.resolve()):
        return None
    if not _has_dotdot(candidate) and not _has_dotdot(root):
        if _lexical_abs(candidate).is_relative_to(_lexical_abs(root)):
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
