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

Since #802 the authority owns the **decision** as well as the primitives:
:func:`containment_violation` is the whole ordered composition — normalize the
project, ask ownership, ask containment, report whichever half fired with its
coordinates. The ENVELOPES stay with the taxonomy: `gda.errors.containment_refusal`
maps the decision to the two refusals, so a command module states only WHICH
target it is asking about while the dependency direction stays
``errors -> foundation`` (ADR-0040 §5; #807 review — the composition briefly
lived here whole and needed a deferred ``gda.errors`` import to hide the
inverted edge).
"""

import os
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
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
ENGINE_VIRTUAL_PREFIXES = (RES_PREFIX, "user://", "uid://")


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

    - **scheme extraction** (4153-4168: the FIRST ``://`` is taken, and it becomes
      the "drive" only if everything before it is ASCII alphanumeric — the engine
      does not go looking for a later one) — reproduced NARROWLY, for an exact
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
        if not path.startswith(RES_PREFIX):
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


def _within(child: Path, parent: Path) -> bool:
    """Is ``child`` at or under ``parent``, by EITHER reading?

    The same two readings :func:`path_outside_project` consults, and for the same
    reason: the lexical one answers "was this addressed through that tree", the
    resolved one answers "are these the same place under two spellings". Either
    saying yes is enough.
    """
    if child == parent or parent in child.parents:
        return True
    resolved_child = child.resolve()
    resolved_parent = parent.resolve()
    return (
        resolved_child == resolved_parent or resolved_parent in resolved_child.parents
    )


def _anchored_target(path: str, project: Path | None) -> Path:
    """Where ``path`` addresses a file, in filesystem terms.

    ONE anchoring rule for the two things that need it after containment or
    ownership has refused — the walk :func:`owning_project` starts from, and the
    location :func:`target_location` reports — so a refusal can never name a
    different file from the one that was checked. It mirrors
    :func:`path_outside_project`'s own branching: a ``res://`` address is anchored
    in the resolved namespace (the only project it can mean), and everything else
    is anchored the way the engine anchors it (:func:`project_anchored`), or at the
    invoker's cwd when no project resolved.
    """
    if project is None:
        return _expand_user(Path(path))
    if path.startswith(RES_PREFIX):
        return _expand_user(project) / canonical_res_path(path)[len(RES_PREFIX) :]
    return project_anchored(path, project)


def target_location(path: str, project: Path | None) -> Path:
    """Where a refused target really is — for the message and the typed evidence.

    The resolved location of :func:`_anchored_target`, so the coordinate a caller
    walks up from names a real place rather than the spelling it was refused
    under. Called only after a refusal, and only for the address forms the two
    refusing checks actually look at (``res://`` and filesystem paths); the other
    engine schemes never reach a refusal that needs a location.
    """
    return _anchored_target(path, project).resolve()


def owner_relative_target(path: str, project: Path | None, owner: Path) -> str:
    """How the caller re-addresses ``path`` against ``owner`` (#799 review).

    The refusal :func:`owning_project` produces has to be ACTIONABLE, and naming
    the owner alone is not: a relative target anchors at the resolved project
    (:func:`project_anchored`), so re-issuing the same spelling under the owner's
    ``--project`` reaches a file that is not there (``path_not_found``), and the
    absolute location the refusal reports as evidence is a form ``script run``
    structurally refuses (ADR-0031's one-address model). The one spelling all
    three refusing commands accept is the target's path RELATIVE to the project
    named, so that is what this computes and the message states.

    The reading is LEXICAL on both sides, and that is not a shortcut — it is the
    only reading that is total. :func:`owning_project` walks the caller's own
    spelling, so the owner it returns is always a lexical ancestor of the lexical
    target and this subtraction cannot fail. The resolved pair CAN fail: a file
    link inside a nested project points its resolved location outside the resolved
    owner, and the spelling that works there is still the link's own. Lexical is
    also what the engine reads — it walks the project directory — so the result is
    the address the engine resolves to the same file.

    ``owner`` must be the value :func:`owning_project` returned for the same
    ``path`` and ``project``; the totality argument above is about exactly that
    pair. Forward slashes, so the spelling is portable to the caller's next
    invocation on any platform.
    """
    target = _lexical_abs(_anchored_target(path, project))
    return target.relative_to(_lexical_abs(owner)).as_posix()


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

    **Asked only of a target INSIDE the resolved tree.** Ownership is the second
    half of one question, not a rival to the first: a target that is not in the
    resolved project at all — an escaping ``res://`` remainder, a path that climbs
    out, the project directory named as a target — returns ``None`` here and is
    :func:`path_outside_project`'s to refuse. Without that bound the walk would
    start OUTSIDE the tree and could name some unrelated ancestor project as the
    "owner" of a target whose real problem is that it escaped.

    **The walk is LEXICAL, the bound is BOTH readings.** It reads the caller's own
    spelling (:func:`_lexical_abs`, symlinks preserved) upward from the target,
    because following symlinks would refuse the monorepo shared-addon layout
    :func:`path_outside_project` deliberately accepts: ``game/addons/lib`` linked
    to ``../../libs/lib`` resolves into a tree whose own ``project.godot`` has
    nothing to do with this call, while the engine — walking the project directory
    — reads the file as ``res://addons/lib/…`` and compiles it against ``game``.
    But the STOP test also consults the resolved reading, for the same reason
    :func:`path_outside_project` always does: the project and the target may be
    spelled through different-but-equal paths (on macOS ``/tmp`` →
    ``/private/tmp`` alone is enough), and a purely lexical stop would walk past
    the resolved project, find its marker, and refuse a correct call by naming the
    very project the caller passed.

    With no project resolved there is nothing to stop at, so the walk runs to the
    filesystem root: a projectless run of a file that DOES have an owner is the
    other GDA-DF-035 reading, and it produced the same false ``res://`` cascade
    with no project to attribute it to.

    A ``user://`` or ``uid://`` address has no project-tree position to walk from
    and is left alone, as everywhere else. A ``res://`` address is anchored in the
    resolved namespace first — that is the only project it can mean — so it is
    walked exactly like the project-relative spelling of the same file.
    """
    if is_engine_virtual_path(path) and not path.startswith(RES_PREFIX):
        return None
    if project is None:
        start = _lexical_abs(_anchored_target(path, None)).parent
        stop = stop_resolved = None
    else:
        stop = _lexical_abs(_expand_user(project))
        start = _lexical_abs(_anchored_target(path, project)).parent
        if not _within(start, stop):
            # The target is not a FILE in the resolved tree — an escaping res://
            # remainder, a path that climbs out, or the project directory itself
            # spelled as a target (``""``, ``.``, ``sub/..``), whose parent is
            # already above the stop. Ownership has nothing to say about any of
            # them, and walking upward from outside the tree would answer a
            # question nobody asked: it would name some ancestor project as the
            # "owner" of a target whose real problem is that it escaped, or of the
            # resolved project itself. Containment is the check for those, and it
            # runs next.
            return None
        stop_resolved = stop.resolve()
    # The resolved half of the stop test is per-ancestor, and `resolve()` is itself
    # O(depth), so the walk is O(depth^2) syscalls — and #663 makes it per batch
    # entry. Measured on macOS APFS (200-call mean): 0.07 ms at depth 1, 1.04 ms at
    # 20, 7.2 ms at 60, 27.3 ms at 120 (#799 review). It stands as written: a real
    # project layout is single-digit depth, where the cost is under a tenth of a
    # millisecond against a headless launch of hundreds, and resolving `start` once
    # and walking the two chains in lockstep would buy that back by keeping two
    # chains in step through the case the double reading exists FOR — a symlink,
    # where the resolved chain is not the lexical one's image. Revisit if a
    # measurement, not a shape, says so.
    for directory in (start, *start.parents):
        if stop is not None and (
            directory == stop or directory.resolve() == stop_resolved
        ):
            return None
        if (directory / PROJECT_MARKER).exists():
            return directory
    return None


def project_absolute(project: Path) -> Path:
    """``project`` as an absolute directory, still spelled the caller's way (#738).

    ONE coordinate system for both sides of every containment comparison. A
    project may arrive relative — ``--project game`` is resolved to a directory,
    not to an absolute one (:func:`resolve_project_dir`) — and a relative root met
    an absolute candidate on :func:`path_outside_project`'s lexical fallback,
    where ``relative_to`` raised a bare ``ValueError`` instead of answering.
    Anchoring at the cwd is the right anchor because that is where a relative
    ``--project`` was typed.

    Symlinks are deliberately NOT followed: the two readings
    :func:`path_outside_project` and :func:`owning_project` make are theirs to
    make, and pre-resolving here would take the lexical one away from them. ``~``
    is expanded the module's total way (:func:`_expand_user`), so an unresolvable
    ``~user`` stays literal rather than raising out of a containment check.

    Written for ``resource import``'s asset gate and adopted by
    :func:`containment_violation` as the decision's own normalization (#802); the
    asset gate still calls it directly because it also maps an accepted path back
    onto ``res://`` afterwards, which needs the same absolute root.
    """
    absolute = _expand_user(project)
    if not absolute.is_absolute():
        absolute = Path.cwd() / absolute
    return absolute


@dataclass(frozen=True)
class ForeignOwnerViolation:
    """The ownership half of the containment decision: a nearer project owns it."""

    location: Path
    owner: Path
    root: Path | None
    owner_relative: str


@dataclass(frozen=True)
class OutsideRootViolation:
    """The containment half of the decision: the target escapes the root."""

    outside: Path
    root: Path


def containment_violation(
    target: str, project: Path | None
) -> ForeignOwnerViolation | OutsideRootViolation | None:
    """The ordered containment decision for ``target`` under ``project`` (#802).

    The one question "does this target belong to the resolved project?", asked in
    one order, answered with the fired half and its coordinates — no envelope is
    built here. `gda.errors.containment_refusal` maps the decision to the two
    refusals and is what the three commands call (``script validate`` per batch
    entry, ``script run`` for its entry script, ``resource import`` per asset);
    until #802 each wrote this composition by hand, so the ordering rule, the four
    coordinates and the ``.resolve()`` discipline were interface cost every one of
    them paid. They had drifted twice already (#763's postmortem, then #799's),
    which is why the cross-gate consistency test exists; it now guards the gate's
    output rather than being the only thing holding three copies together.

    **Ordering: ownership first, containment second.** A real precedence rule, not
    only a choice of wording, because the two halves CAN both fire on one target:
    their bounds differ. :func:`owning_project` stops its walk by :func:`_within`,
    which consults the lexical spelling unconditionally, while
    :func:`path_outside_project` WITHHOLDS the lexical reading when either side
    carries a ``..``. A file symlinked into the project from a tree that is itself
    a project, addressed with a ``..``, therefore satisfies the walk's bound and
    the containment refusal at once — the monorepo shared-addon layout
    :func:`path_outside_project` exists for, plus a ``..`` in the spelling.
    Ownership wins because it is the more specific diagnosis — it names the
    project that CAN serve the call and the spelling to address the target by, so
    following the sentence verbatim works — while containment can only say "not
    here, and I found no owner to send you to". Swapping the two loses the
    actionable half on exactly that layout, so the order is pinned by a test of
    its own (#807 review) and not by this paragraph alone. Ownership is also the
    only half a PROJECTLESS call can make: with no root there is nothing to be
    outside OF, so containment is skipped and a standalone file that no
    ``project.godot`` claims is served, as ADR-0006's projectless fallback
    promises.

    **Normalization: the project is cwd-absolutized** (:func:`project_absolute`),
    the form ``resource import`` adopted in #738 — the checks read the project as
    SPELLED (the double reading is theirs to make) but they must read it in one
    coordinate system, or a relative ``--project`` meets an absolute candidate on
    the lexical fallback. The refusals report it RESOLVED, which is what
    ``FailureEvidence.project_root`` publishes: "in its resolved form — the same
    value a successful result reports".

    ``target`` is the caller's own spelling in any form the command accepts —
    ``res://`` address, project-relative path, or absolute path — because
    :func:`_anchored_target` anchors each of them the way the engine would.
    ``project`` is the already-resolved directory (resolution stays CLI-side,
    ADR-0006); ``None`` means projectless.
    """
    if project is None:
        anchor = root = None
    else:
        anchor = project_absolute(project)
        root = anchor.resolve()
    owner = owning_project(target, anchor)
    if owner is not None:
        return ForeignOwnerViolation(
            location=target_location(target, anchor),
            owner=owner.resolve(),
            root=root,
            owner_relative=owner_relative_target(target, anchor, owner),
        )
    # `root` is set exactly when `anchor` is; both are named so the narrowing stays
    # local to the branch that uses them.
    if anchor is not None and root is not None:
        outside = path_outside_project(target, anchor)
        if outside is not None:
            return OutsideRootViolation(outside=outside, root=root)
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


# --- The main-scene precondition for a live session launch (#829) -------------

MAIN_SCENE_UNDEFINED = "live_main_scene_undefined"
MAIN_SCENE_UNRESOLVED = "live_main_scene_unresolved"

# Godot's project data directory, where the engine keeps the UID cache it resolves
# a `uid://` main scene through: `.godot/` by default, `godot/` when the project
# opts out of the hidden name (`application/config/use_hidden_project_data_directory`).
_PROJECT_DATA_DIRS = (".godot", "godot")
_UID_CACHE = "uid_cache.bin"


@dataclass(frozen=True)
class MainSceneUnrunnable:
    """The refusal for a session launch whose main scene cannot be run (#829).

    ``code`` is the :term:`Gda error code` — :data:`MAIN_SCENE_UNDEFINED` when the
    project declares no main scene, :data:`MAIN_SCENE_UNRESOLVED` when it declares a
    ``uid://`` one the engine could not resolve because the project was never
    imported — and ``reason`` the caller-first sentence both refusal sites relay
    verbatim (the optional ``daemon start`` fail-fast and the daemon's
    authoritative launch boundary), so the two never disagree about what was found
    or what to do.
    """

    code: str
    reason: str


def _section_name(line: str) -> str | None:
    """The section a ``[name]`` line opens, with a trailing ``;``/``#`` comment ignored."""
    if not line.startswith("["):
        return None
    close = line.find("]")
    if close < 0:
        return None
    rest = line[close + 1 :].strip()
    if rest and not rest.startswith((";", "#")):
        return None
    return line[1:close].strip()


def _read_main_scene(project: Path) -> str | None:
    """The ``application/run/main_scene`` value in ``project.godot``.

    A minimal read of Godot's ``ConfigFile`` text: sections are ``[name]`` lines
    (a trailing comment allowed), keys are ``key=value`` lines inside them, and the
    main-scene value is a quoted string (``"res://main.tscn"`` or ``"uid://..."``).
    A non-empty base key or a non-empty feature-tagged override
    (``run/main_scene.<feature>``) counts as a declared scene — the engine reads the
    setting with a matching override applied over the base, and this check must
    never refuse a project the engine would run. No ``[application]`` section or no key reads as ``""`` —
    undefined, which is what the engine would conclude too. A file gda cannot READ
    or DECODE is ``None``: that is not a verdict about the scene, and the step that
    next touches the file (the harness install) reports the failure as its own.
    """
    try:
        text = (project / PROJECT_MARKER).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    section = ""
    base: str | None = None
    override = ""
    for raw in text.splitlines():
        line = raw.strip()
        opened = _section_name(line)
        if opened is not None:
            section = opened
            continue
        if section != "application" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key == "run/main_scene":
            base = value
        elif key.startswith("run/main_scene.") and value and not override:
            override = value
    # A matching feature override beats the base key in the engine, so a declared
    # override counts even beside an EMPTY base key; a declared base key counts
    # even beside an empty override.
    return base or override


def _uid_cache_present(project: Path) -> bool:
    return any(
        (project / data_dir / _UID_CACHE).is_file() for data_dir in _PROJECT_DATA_DIRS
    )


def main_scene_unrunnable(
    project: Path, scene: str | None
) -> MainSceneUnrunnable | None:
    """The pre-launch verdict for a live session: ``None`` when it has a scene to run.

    Godot started on the GAME path with no ``--scene``/``--script`` prints
    ``Can't run project: no main scene defined`` when ``application/run/main_scene``
    is empty, and ``Main scene's path could not be resolved from UID`` when it is a
    ``uid://`` the engine has no UID cache for (``main/main.cpp``: the cache file
    under the project data directory does not exist — a fresh clone, since Godot
    4.4 writes the setting as a UID and ``.godot/`` is normally ignored). Either
    way it then calls ``OS::alert()`` unconditionally — on macOS a native modal that
    ignores ``--headless`` and blocks the process until it is dismissed or killed
    (#829). Every gda headless operation names a script, an import or an export, so
    only a session launch can reach that path: this is the one check the two launch
    sites share (the ``daemon start`` fail-fast and the daemon's authoritative
    launch boundary), decided from the project files alone, without spawning. A
    ``--scene`` selector makes the main scene irrelevant, so it wins.
    """
    if scene:
        return None
    main_scene = _read_main_scene(project)
    if main_scene is None:
        return None
    if main_scene == "":
        return MainSceneUnrunnable(
            MAIN_SCENE_UNDEFINED,
            "the project defines no main scene to run: `application/run/main_scene` "
            f"is empty in {project / PROJECT_MARKER} and no --scene selector was "
            "given. Set it (`gda project set application/run/main_scene --value "
            "res://<scene>.tscn`) or start with `gda daemon start --scene "
            "<res://path|uid://...>` (after `gda daemon stop` if a daemon is "
            "running); Godot would otherwise refuse to run the project and, on "
            "macOS, block on a native alert even under --headless",
        )
    if main_scene.startswith("uid://") and not _uid_cache_present(project):
        return MainSceneUnrunnable(
            MAIN_SCENE_UNRESOLVED,
            f"the project's main scene is {main_scene!r} but the engine has no UID "
            "cache to resolve it through (no uid_cache.bin under the project data "
            "directory — the project has not been imported on this checkout). Run "
            "the import pass once (`gda resource import <any res:// asset>`, or open "
            "the project in the editor), or start with `gda daemon start --scene "
            "<res://path>` (after `gda daemon stop` if a daemon is running); Godot "
            "would otherwise refuse to run the project and, on macOS, block on a "
            "native alert even under --headless",
        )
    return None
