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

It is also ADR-0006's **path authority**, and since #763 that is one answer
rather than three. :func:`path_outside_project` decides whether a target belongs
to the resolved project — for a filesystem path and for a ``res://`` address
alike — and every command gate that asks the question calls it (or, where the
gate runs before project resolution, its lexical half
:func:`res_escape_remainder`). The ``res://`` primitives those readings are built
on, :func:`canonical_res_path` and :func:`res_escape_remainder`, live here too:
they are pure lexical address rules, so they belong beside
:data:`ENGINE_VIRTUAL_PREFIXES` and :func:`_lexical_abs` rather than in the
stderr parser that first needed one (:mod:`gda.script_errors`, now a consumer).
"""

import os
import posixpath
from collections.abc import Mapping
from pathlib import Path

GDA_PROJECT_ENV = "GDA_PROJECT"

# The file Godot uses to mark a directory as a project root.
PROJECT_MARKER = "project.godot"


# The ``res://`` scheme prefix — the project's own virtual namespace, and the one
# scheme this module reads STRUCTURALLY (canonicalizing it, and asking whether an
# address stays inside it). Public because every consumer of the two functions
# below slices it off or lifts onto it.
RES_PREFIX = "res://"

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
    (which still makes no FILESYSTEM statement about a well-formed one, but for
    a ``res://`` spelling specifically checks it for a lexical escape of the
    project namespace, #762 — a ``user://``/``uid://`` spelling stays inside by
    construction, unchanged).
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


def _expand_user(path: Path) -> Path:
    """``Path.expanduser()``, total: an unresolvable ``~user`` stays literal.

    ``expanduser`` raises ``RuntimeError`` for a ``~unknownuser/…`` prefix it
    cannot resolve. The shared normalizer deliberately passes such a path
    through unchanged (#699 — bash treats an unresolvable ``~user`` as a
    literal name), so the containment layer must be total the same way: the
    literal path simply will not exist, and the consumer reports that
    structurally instead of a RuntimeError escaping as a traceback.
    """
    try:
        return path.expanduser()
    except RuntimeError:
        return path


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
    target = _expand_user(Path(path))
    if target.is_absolute():
        return target
    return _expand_user(project) / target


def canonical_res_path(path: str) -> str:
    """The canonical lexical form of a ``res://`` address (#651 review claim 1).

    ONE resource identity, used on both sides of every comparison and for the argv
    gda hands the engine. Godot canonicalizes internally before it reports a path,
    so ``res://dir/../bad.gd`` comes back as ``res://bad.gd``; comparing the
    engine's spelling against the caller's raw one missed the match and let a
    failed run report success.

    Purely lexical — no filesystem access — so it is safe on a path that does not
    exist, which is exactly the missing-entry-script case. A non-``res://`` string
    is returned unchanged: this normalizes an address, it does not validate one.

    It lives HERE, beside :func:`is_engine_virtual_path` and
    :func:`path_outside_project`, because it is a pure lexical ``res://``
    primitive and this module is ADR-0006's path authority (#763). It was written
    in :mod:`gda.script_errors` for that module's own engine-spelling comparison
    and grew a second consumer, which left the authority importing from a stderr
    parser; the dependency now runs the other way and the parser is one consumer
    among several.

    **Against ``String::simplify_path``** (``core/string/ustring.cpp:4149-4233``,
    Godot ``4.6-stable-3260-g070dc9897e``), the engine function every ``res://``
    address passes through before the engine resolves or reports it
    (``ProjectSettings::localize_path``, ``core/config/project_settings.cpp:158``).
    Which of its steps this reproduces, in the engine's own order:

    - **scheme extraction** (4153-4168: first ``://`` whose prefix is all ASCII
      alphanumerics becomes the "drive") — reproduced NARROWLY, for an exact
      ``res://`` prefix only. The engine's other two drive branches (network share,
      Windows ``C:``) are deliberately NOT reproduced: they are unreachable once the
      scheme branch matched, and a non-``res://`` string leaves here untouched anyway.
    - **``\\`` → ``/`` across the whole remainder** (4192) — reproduced, and it must
      run BEFORE the leading-slash strip below, exactly as the engine runs it before
      its own empty-segment split: ``res://\\a.gd`` folds to ``res://a.gd``, which is
      no longer possible once the strip has already passed over a backslash. Without
      this step ``res://..\\outside.gd`` read as an ordinary in-project filename
      while the engine loaded the file one directory ABOVE the project and reported
      it back as ``res://../outside.gd`` (#762).
    - **repeated-``//`` collapse and ``split("/", false)``** (4193-4201) — reproduced
      by the leading-slash strip plus ``posixpath.normpath``, which collapses runs of
      separators and drops a trailing one. The strip is what covers POSIX's one
      divergence: it gives exactly two leading slashes a special meaning (``//a``
      stays ``//a``), so ``res:////a.gd`` would otherwise stay uncanonicalized.
    - **``.``/``..`` collapse with the leading-``..`` strip DISABLED for ``res://``**
      (4204-4221) — reproduced: ``normpath`` on a RELATIVE remainder keeps a leading
      ``..`` for the same reason the engine keeps it (``absolute_path`` is forced
      false for a ``res://`` address at 4204), and that is what lets a caller of
      this function see an escape at all rather than have it silently swallowed.
    - **the join** (4223-4232) — reproduced INCLUDING the empty case, which is
      the parity gap #766 documented and #763 closes: when every segment
      collapses away the engine joins an empty vector and yields the bare
      ``res://``, while ``normpath`` yields ``.``. ``res://a/..`` therefore
      canonicalized here to ``res://.`` — a second spelling of the project root
      that each consumer had to know about (``script run``'s gate carried a
      two-member root set for it). One root spelling now leaves this function,
      the engine's own.
    """
    if not path.startswith(RES_PREFIX):
        return path
    remainder = path[len(RES_PREFIX) :].replace("\\", "/").lstrip("/")
    if not remainder:
        return RES_PREFIX
    collapsed = posixpath.normpath(remainder)
    # normpath("") is ".", so the empty case is handled above rather than here;
    # a remainder whose segments all cancel collapses TO "." and is the root the
    # engine spells `res://`.
    if collapsed == ".":
        return RES_PREFIX
    return RES_PREFIX + collapsed


def res_escape_remainder(path: str) -> str | None:
    """The canonical remainder of a ``res://`` address when it escapes upward, else ``None`` (#762).

    The ONE lexical reading of "does this ``res://`` spelling stay inside the
    project's namespace" (#763). :func:`canonical_res_path` first folds ``\\`` to
    ``/`` and collapses ``.``/``..`` segments exactly as the engine does — its
    docstring is where that correspondence to ``String::simplify_path`` is
    audited step by step — and then this reads what is left: an exact ``..`` or a
    leading ``../`` means the address is still climbing above the namespace root
    AFTER that collapsing, which is genuinely outside. The fold is what makes
    ``res://..\\outside.gd`` reach this test as the escape the engine treats it as,
    rather than as an in-project filename (PR #766 review). Anything else is not
    an escape, including a ``res://foo/../bar.gd`` spelling — it collapses to
    ``res://bar.gd``, net-inside — and a filename that merely STARTS with two dots
    (``res://..foo.gd`` names a real file, not a traversal; the test is the first
    PATH SEGMENT, not a string prefix).

    Two callers, and the split between them is about what each one HAS, not about
    what each one decides: :func:`path_outside_project` (below) is the answer for
    anyone holding a resolved project, and ``script run``'s pre-launch address
    gate calls this directly because it runs BEFORE project resolution and has
    only the spelling. Both get the same verdict from the same rule; before #763
    each command carried its own (``resource import`` refused any literal ``..``,
    net-inside or not, and read ``\\`` as a filename character).
    """
    remainder = canonical_res_path(path)[len(RES_PREFIX) :]
    if remainder == ".." or remainder.startswith("../"):
        return remainder
    return None


def path_outside_project(path: str, project: Path) -> Path | None:
    """The location of ``path`` when it falls OUTSIDE ``project``.

    THE containment check behind the "this target does not belong to the
    resolved project" refusal — one answer for every command that asks (#763).
    Returns ``None`` when the path belongs to the project, and otherwise the
    target's real location, so the caller can name *where* it actually is in its
    diagnostic (and carry it as typed evidence).

    Callers: ``script validate``'s recipe, ``resource import``'s asset gate, and
    — through :func:`res_escape_remainder`, the lexical half, because it runs
    before project resolution — ``script run``'s pre-launch address gate. Each
    used to carry its own rule and they disagreed: ``resource import`` refused
    any literal ``..`` even when it collapsed back inside, and read ``\\`` as a
    filename character rather than the separator the engine folds.

    A ``res://`` address is checked LEXICALLY against the namespace it names,
    rather than trusted by construction: :func:`res_escape_remainder`
    canonicalizes it the way the engine does and refuses one that still steps
    above the namespace root after that collapsing (``res://../outside.gd``).
    gda still makes no FILESYSTEM statement about a well-formed ``res://``
    path — it is the engine's own launch ``--path`` that owns resolving one,
    and this check never touches the filesystem to decide — but a spelling
    that lexically escapes the namespace is not well-formed, and admitting it
    here defeated the very refusal this function exists to make (#762). The
    other two engine-virtual schemes are unaffected and stay inside by
    construction: ``user://`` addresses the engine's own data directory, not a
    child of the project tree, and ``uid://`` is an opaque identifier with no
    path structure to escape through.

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
        if not path.startswith("res://"):
            return None
        escape = res_escape_remainder(path)
        if escape is None:
            return None
        return (_expand_user(project) / escape).resolve()
    root = _expand_user(project)
    candidate = project_anchored(path, project)
    location = candidate.resolve()
    if location.is_relative_to(root.resolve()):
        return None
    if not _has_dotdot(candidate) and not _has_dotdot(root):
        if _lexical_abs(candidate).is_relative_to(_lexical_abs(root)):
            return None
    return location


def owning_project(path: str, project: Path | None) -> Path | None:
    """The Godot project that owns ``path``, when it is NOT ``project`` (#697).

    The second half of "does this target belong to the resolved project", and the
    half :func:`path_outside_project` structurally cannot answer: a target can sit
    squarely INSIDE the resolved project's tree and still be owned by a nearer
    ``project.godot``, and then every ``res://`` reference the target itself makes
    resolves against a root that is not its own. That is dogfooding GDA-DF-035 —
    the same file reads ``valid`` or ``invalid`` depending only on which ancestor
    was named — and #695 pinned it as a deliberate scope line waiting on this
    decision.

    Returns the owning project's directory, or ``None`` when the resolved project
    IS the owner (or nothing above the target claims it). ADR-0006's 2026-08-31
    amendment is what makes the difference between this and the derivation that
    ADR was right to reject: gda never RESOLVES to what it finds here. The
    resolved project stays the one ``--project``/``$GDA_PROJECT``/cwd named, one
    call still has exactly one root, and a batch spanning several owners still
    reports one verdict. The owner is reported so the caller can re-issue with it,
    never adopted.

    **The walk is LEXICAL and bounded.** It reads the caller's own spelling
    (:func:`_lexical_abs`, symlinks preserved) upward from the target, and stops
    at the resolved project — which is exactly where ownership stops being in
    question. Following symlinks instead would refuse the monorepo shared-addon
    layout :func:`path_outside_project` deliberately accepts: ``game/addons/lib``
    linked to ``../../libs/lib`` resolves into a tree whose own ``project.godot``
    has nothing to do with this call, while the engine — walking the project
    directory — reads the file as ``res://addons/lib/…`` and compiles it against
    ``game``. With no project resolved there is nothing to stop at, so the walk
    runs to the filesystem root: a projectless run of a file that DOES have an
    owner is the other GDA-DF-035 reading, and it produced the same false
    ``res://`` cascade with no project to attribute it to.

    A ``user://`` or ``uid://`` address has no project-tree position to walk from
    and is left alone, as everywhere else. A ``res://`` address is anchored in the
    resolved namespace first — that is the only project it can mean — so it is
    walked exactly like the project-relative spelling of the same file.
    """
    if project is None:
        if is_engine_virtual_path(path):
            return None
        start = _lexical_abs(_expand_user(Path(path))).parent
        stop = None
    else:
        stop = _lexical_abs(_expand_user(project))
        if path.startswith(RES_PREFIX):
            remainder = canonical_res_path(path)[len(RES_PREFIX) :]
            if not remainder:
                return None
            start = _lexical_abs(stop / remainder).parent
        elif is_engine_virtual_path(path):
            return None
        else:
            start = _lexical_abs(project_anchored(path, project)).parent
    for directory in (start, *start.parents):
        if directory == stop:
            return None
        if (directory / PROJECT_MARKER).exists():
            return directory
    return None


def _project_or_raise(raw: str, source: str) -> Path:
    """Expand ``raw`` to a project directory, or raise if it is not one."""
    candidate = _expand_user(Path(raw))
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
