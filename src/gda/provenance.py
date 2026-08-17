"""The structured install provenance behind ``gda --version --json`` (#659).

A long agent run needs to record WHICH ``gda`` produced its evidence. Dogfooding
found two ways that failed: ``gda --version`` printed one human line an evidence
collector had to parse (GDA-DF-018), and the ``gda`` a ``PATH`` lookup resolved
turned out to be an *editable* install whose source checkout changed revision
mid-run, with nothing in the output to disclose it (GDA-DF-043).

So this module answers "which gda is running, and where did it come from" as one
model:

* the installed ``gda`` version, the executable that ran, and the interpreter
  running it;
* the directory the ``gda`` package was actually IMPORTED from — the one field
  read from the loaded module rather than from installer metadata, so a
  ``sys.path`` shadow cannot leave the rest of the payload confidently wrong;
* the install kind — a built ``wheel`` (no source checkout), an ``editable``
  install, or ``unknown``, read from the PEP 610 ``direct_url.json`` the installer
  recorded, since the version string alone cannot tell them apart and ``pip show``
  is unavailable in a ``uv`` environment;
* for an editable install, the source checkout: its root, its Git revision, and
  whether the working tree is dirty — the three facts GDA-DF-043 needed;
* the Godot binary ``gda`` would use, resolved without launching it.

A note on ``unknown``: "no record at all" and "a record I could not read" lead to
OPPOSITE conclusions, so the read seam keeps them apart in three arms
(:class:`RecordState`) instead of one nullable answer. Only "no record" — how an
ordinary index install looks — implies a wheel. A record that is present but
malformed, present but saying nothing, or that could not be retrieved at all means
the install could be either, and a preflight built to prevent false provenance must
not answer a question it cannot answer. All three yield ``unknown``, never a
confident ``wheel``, and none of them fails the preflight: the payload is still
emitted, reporting everything it does know.

**It never launches Godot.** The motivating environment is a restricted profile
where an engine spawn crashes, which is exactly when provenance matters most — so
the engine version key is OMITTED, with a stated reason in its place, rather than
making the preflight depend on the thing it is meant to diagnose. Reading the Git
revision does run ``git``; that is a different process
from the one under suspicion, it degrades to ``None`` when unavailable, and it runs
with the inherited repository-redirect variables stripped (:data:`GIT_REDIRECT_ENV`)
so a gda called from inside another repository's hook cannot be handed that
repository's revision.

There is deliberately no schema or protocol version here: ``gda`` has none, and
inventing one would create a contract nothing else honors.

The whole payload is built by :func:`build_version_provenance`, kept free of the
CLI so a later self-diagnosis command (#670) can embed it without re-deriving any
of it.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from importlib.metadata import Distribution, PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import url2pathname

from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer

from gda.binary import resolve_godot_binary

# The distribution name to introspect — this package's own.
DISTRIBUTION = "gda"

# How long a provenance ``git`` call may take before it is treated as
# unresolvable. Generous for a local repository, bounded so a wedged ``git`` (a
# stale index lock, a network-backed filesystem) cannot hang a preflight whose
# whole point is to run when the environment is already unhealthy.
GIT_TIMEOUT_SECONDS = 5.0

# Why the engine version is absent. Stated in the payload rather than silently
# omitted, so a reader can tell "not detected" from "not detectable here".
GODOT_VERSION_NEEDS_A_LAUNCH = (
    "the engine reports its version only from a running process, and this surface "
    "never launches Godot; run `gda info --json` for it"
)


class InstallKind(str, Enum):
    """How the running ``gda`` was installed.

    ``WHEEL`` is any built, non-editable install (from an index, or from a local
    wheel or source directory): the code that runs is a copy, so there is no
    source checkout to report. ``EDITABLE`` is an install that imports straight
    out of a working tree (``pip install -e`` / ``uv sync``), so the code that runs
    can change without the version changing — the case GDA-DF-043 hit.

    ``UNKNOWN`` is the answer whenever gda cannot READ the install metadata as the
    shape PEP 610 defines — whether the record is off-spec, says nothing at all, or
    could not be retrieved. It is not a third kind of install; it is the refusal to
    guess between the other two. A record gda could not read, reported as ``WHEEL``,
    would tell a reader "immutable copy, nothing can change under you" about an
    install that may well be editable — precisely the false provenance this surface
    exists to prevent. Only ONE observation earns ``WHEEL``: the installer recorded
    no direct-URL origin at all, which is what an ordinary index install looks like.
    """

    WHEEL = "wheel"
    EDITABLE = "editable"
    UNKNOWN = "unknown"


class RecordState(str, Enum):
    """Whether the running ``gda``'s PEP 610 install record could be read at all.

    Three arms, kept apart because collapsing any two of them is how the payload
    starts lying. ``ABSENT`` is the reader saying "no such file" — the shape of an
    ordinary index install, and the ONLY arm that safely implies a built wheel.
    ``PRESENT`` carries the bytes, whatever they say, for the classifier to judge.
    ``UNREADABLE`` is a record gda failed to retrieve: not evidence of a wheel, and
    not a reason to fail a preflight either.
    """

    ABSENT = "absent"
    PRESENT = "present"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class DirectUrlRecord:
    """A PEP 610 ``direct_url.json`` as far as it could be read, unjudged.

    ``text`` is the raw document and is set only on :attr:`RecordState.PRESENT` —
    handed over verbatim, whitespace-only included. A record that exists but says
    nothing is *off-spec*, not absent, and blanking it at the read seam is one of
    the two ways a damaged editable install used to be reported as a wheel.
    """

    state: RecordState
    text: Optional[str] = None


@dataclass(frozen=True)
class InstallOrigin:
    """What the PEP 610 record says about where the running ``gda`` came from.

    ``source_root`` is set only for an ``EDITABLE`` install whose recorded origin
    names a local directory — so a caller reads the checkout off this one field
    without re-deciding whether a checkout applies.
    """

    kind: InstallKind
    source_root: Optional[Path] = None


class SourceCheckout(BaseModel):
    """The working tree an editable install imports from.

    ``revision``/``dirty`` are ``None`` when they cannot be resolved — no ``git``
    on ``PATH``, the root is not inside a repository, or the call failed or timed
    out. ``dirty`` counts untracked files as dirty, because an untracked module in
    the checkout is still code the editable install can import — and it counts them
    regardless of the repository's ``status.showUntrackedFiles`` setting, which
    would otherwise let a config choice hide exactly that code.

    These stay explicit ``null`` rather than omitted keys (unlike
    ``GodotProvenance.version``): here the null IS the finding — gda looked at a
    named checkout and could not resolve its state — while an omitted key would
    read as "not applicable".
    """

    root: str
    revision: Optional[str] = None
    dirty: Optional[bool] = None


class GodotProvenance(BaseModel):
    """The engine side of the provenance, resolved WITHOUT launching Godot.

    ``binary`` is what ``$GDA_GODOT`` → the built-in default resolves to. That is
    the whole precedence reachable here: ``--godot`` is a per-COMMAND option, and
    this surface is the root, which has none — so the reported path is the engine a
    command with no ``--godot`` would use, and an explicit flag on a later command
    still overrides it. It is reported as resolved, not checked for existence,
    because probing the file is a different question from "which engine would this
    gda use".

    ``version`` appears ONLY when the version is obtainable without a launch — it
    is not today — and is otherwise OMITTED, with ``version_unavailable_reason`` in
    its place; the reason is likewise omitted once a version is present. That is
    #659's contract ("only when obtainable, otherwise omitted with a stated
    reason") and it follows the omitted-never-null convention gda uses elsewhere:
    a null would claim gda looked and found nothing, when in fact it declined to
    look. Exactly one of the two keys is present at any time.
    """

    binary: str
    version: Optional[str] = None
    version_unavailable_reason: Optional[str] = None

    @model_serializer(mode="wrap")
    def _omit_the_inapplicable_key(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        # A ``None`` on this model means "does not apply", not "looked and found
        # nothing", so the key is dropped rather than serialized as null. ``binary``
        # is required and never None, so this only ever affects the version pair.
        return {key: value for key, value in handler(self).items() if value is not None}


class VersionProvenance(BaseModel):
    """The ``gda --version --json`` payload: which ``gda`` ran, and from where."""

    gda_version: str = Field(description="The installed gda distribution version.")
    executable: str = Field(
        description="The absolute path of the gda entry point that is running "
        "(the console script, or the __main__ module under `python -m gda`)."
    )
    interpreter: str = Field(
        description="The absolute path of the Python interpreter running gda."
    )
    package_path: str = Field(
        description="The absolute directory the running gda PACKAGE was imported "
        "from. Every other field here is read from distribution metadata; this one "
        "is read from the loaded module, so a mismatch between them (a PYTHONPATH "
        "or sys.path shadow) is visible instead of silent."
    )
    install_kind: InstallKind = Field(
        description="Whether gda was installed as a built wheel or as an editable "
        "install importing from a source checkout — or `unknown` when the install "
        "metadata exists but cannot be read, in which case gda refuses to guess "
        "between the two rather than claiming the immutable one."
    )
    source: Optional[SourceCheckout] = Field(
        default=None,
        description="The source checkout an editable install imports from; null "
        "for a wheel (no checkout), for an unknown install kind, and for an "
        "editable install whose recorded location is not a resolvable local path.",
    )
    godot: GodotProvenance = Field(
        description="The engine gda would use, resolved without launching it."
    )


def read_direct_url_record(distribution: str = DISTRIBUTION) -> DirectUrlRecord:
    """Read ``distribution``'s PEP 610 ``direct_url.json`` WITHOUT judging it.

    The one seam through which install provenance enters this module. It reports
    which of :class:`RecordState`'s three arms happened and flattens none of them:
    only a reader that says "no such file" is ``ABSENT``; any content — including
    whitespace — is ``PRESENT`` and travels on to :func:`classify_install`; a reader
    that raises is ``UNREADABLE``.

    A distribution that is not installed is ``UNREADABLE``, not ``ABSENT``: gda did
    not learn that no record exists, it failed to look. (It cannot be observed in
    practice, because :func:`build_version_provenance` reads the version from the
    same metadata and would fail first — but classifying a metadata failure onto the
    one arm that implies a wheel would be wrong on principle.)

    One hole this seam cannot see: ``importlib.metadata`` suppresses some of its own
    read failures — notably ``PermissionError`` — and returns ``None``, which is
    indistinguishable here from a missing file. That case still reports ``wheel``.
    """
    try:
        dist = Distribution.from_name(distribution)
        raw = dist.read_text("direct_url.json")
    except (PackageNotFoundError, OSError):
        return DirectUrlRecord(RecordState.UNREADABLE)
    if raw is None:
        return DirectUrlRecord(RecordState.ABSENT)
    return DirectUrlRecord(RecordState.PRESENT, raw)


def classify_install(record: DirectUrlRecord) -> InstallOrigin:
    """Decide the install kind (and the checkout, if any) from a PEP 610 record.

    Pure, so every branch is testable without an installer. The rule it enforces is
    that exactly one observation may produce a confident ``WHEEL`` — the installer
    recorded no direct-URL origin (``ABSENT``) — and one may produce ``EDITABLE``: a
    readable record whose ``dir_info.editable`` is the boolean ``true``. Everything
    else is ``UNKNOWN``: a record gda could not retrieve, unparseable JSON (a
    whitespace-only document included), a non-object document, a non-object
    ``dir_info``, or an ``editable`` that is not the boolean the spec types it as.
    PEP 610 says an absent ``editable`` defaults to false, so that stays a wheel.
    """
    if record.state is RecordState.UNREADABLE:
        return InstallOrigin(InstallKind.UNKNOWN)
    if record.state is RecordState.ABSENT:
        return InstallOrigin(InstallKind.WHEEL)
    try:
        # A `PRESENT` record always carries its text; an empty or whitespace-only
        # document fails to parse here, which is the intended `UNKNOWN`.
        parsed = json.loads(record.text or "")
    except json.JSONDecodeError:
        return InstallOrigin(InstallKind.UNKNOWN)
    if not isinstance(parsed, dict):
        return InstallOrigin(InstallKind.UNKNOWN)
    if "dir_info" not in parsed:
        # A direct-URL install of an archive or a VCS clone: built, and what runs is
        # a copy, so there is no checkout to report.
        return InstallOrigin(InstallKind.WHEEL)
    dir_info = parsed["dir_info"]
    if not isinstance(dir_info, dict):
        return InstallOrigin(InstallKind.UNKNOWN)
    editable = dir_info.get("editable", False)
    if editable is False:
        return InstallOrigin(InstallKind.WHEEL)
    if editable is not True:
        # Truthiness is not the test: `"editable": "false"` and `"editable": 1` are
        # both outside the spec, and guessing which side they fall on is how a
        # mutable checkout gets reported as an immutable copy.
        return InstallOrigin(InstallKind.UNKNOWN)
    return InstallOrigin(InstallKind.EDITABLE, _recorded_source_root(parsed))


def _recorded_source_root(direct_url: Optional[dict[str, Any]]) -> Optional[Path]:
    """The local directory a PEP 610 record points at, if it names one.

    PEP 610 records the origin as a URL; only a ``file:`` URL names a directory on
    this machine, so anything else yields ``None`` and the checkout is reported as
    unresolvable rather than guessed at.
    """
    if direct_url is None:
        return None
    url = direct_url.get("url")
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    path = url2pathname(parsed.path)
    return Path(path) if path else None


# Git environment variables that redirect git at a repository OTHER than the one
# ``-C`` names — ``$GIT_DIR`` in particular WINS over ``-C``. gda is invoked from
# exactly the places that set them (a git hook, ``git rebase --exec``, ``git bisect
# run``, a CI wrapper), where inheriting them would make this surface report another
# repository's HEAD as this checkout's revision: a ``root`` and a ``revision`` from
# different trees, silently, which is worse than the ``None`` this module promises
# when an answer is unavailable. So they are dropped for the provenance calls.
GIT_REDIRECT_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
)


def _git_env() -> dict[str, str]:
    """The environment the provenance ``git`` calls run in."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_REDIRECT_ENV}
    # A read-only preflight must never take (or wait on) the agent's own
    # `index.lock`: `git status` would otherwise refresh the index on disk.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _git_output(source_root: Path, *args: str) -> Optional[str]:
    """Run ``git -C <source_root> <args>`` and return stdout, or ``None``.

    ``None`` for every way the answer can be unavailable — ``git`` missing, the
    root not being a repository, a non-zero exit, or the timeout — so a caller
    reports "not resolvable" instead of guessing. ``-C`` gives the usual Git
    meaning of "the repository containing this directory", so a source root nested
    below the repository root still resolves — and :func:`_git_env` makes ``-C``
    the only thing that decides which repository is read.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _source_checkout(source_root: Path) -> SourceCheckout:
    """Describe ``source_root`` as a checkout, resolving Git state when possible."""
    revision = _git_output(source_root, "rev-parse", "HEAD")
    # `--untracked-files=all` on the command line, not left to the repository's
    # `status.showUntrackedFiles`: with that set to `no`, an untracked module sitting
    # in the checkout — importable by the editable install, and therefore code that
    # can run — would leave `dirty` reading false. The flag makes the answer a
    # property of the tree rather than of someone's git config.
    status = _git_output(source_root, "status", "--porcelain", "--untracked-files=all")
    return SourceCheckout(
        root=str(source_root),
        revision=revision.strip() if revision else None,
        dirty=None if status is None else bool(status.strip()),
    )


def _running_executable() -> str:
    """The absolute path of the ``gda`` entry point that is running.

    ``sys.argv[0]`` is what actually started this process — the console script the
    ``PATH`` lookup resolved, or the ``__main__`` module under ``python -m gda`` —
    which is the fact GDA-DF-043 needed and which ``shutil.which("gda")`` would
    only re-guess. Symlinks are left unresolved: the path that ran is the honest
    answer, and resolving it would hide a shim.
    """
    raw = sys.argv[0] if sys.argv and sys.argv[0] else sys.executable
    return os.path.abspath(raw)


def _imported_package_path() -> str:
    """The directory the running ``gda`` package was IMPORTED from.

    Every other field is read from distribution metadata, which describes what an
    installer recorded — not what Python actually loaded. A ``sys.path`` shadow (a
    ``PYTHONPATH`` entry, a ``gda`` directory in the cwd) makes a wheel install
    truthfully report ``wheel`` while the code that ran is a mutable source tree.
    This module lives INSIDE the package, so its own ``__file__`` is that code's
    address, and reporting it makes ``install_kind`` falsifiable rather than
    something a reader has to take on trust.
    """
    return os.path.abspath(os.path.dirname(__file__))


def build_version_provenance() -> VersionProvenance:
    """Build the ``gda --version --json`` payload; never launches Godot."""
    origin = classify_install(read_direct_url_record())
    return VersionProvenance(
        gda_version=package_version(DISTRIBUTION),
        executable=_running_executable(),
        interpreter=sys.executable,
        package_path=_imported_package_path(),
        install_kind=origin.kind,
        # `source_root` is set only when the origin is an editable install naming a
        # local directory — a wheel has no checkout, an unknown kind has none gda
        # will vouch for, and an editable install recorded at a non-local URL has one
        # that cannot be named. All three are honestly `null`, not a fabricated path.
        source=_source_checkout(origin.source_root)
        if origin.source_root is not None
        else None,
        godot=GodotProvenance(
            binary=str(resolve_godot_binary()),
            # No version, so the key is omitted and the reason takes its place.
            version=None,
            version_unavailable_reason=GODOT_VERSION_NEEDS_A_LAUNCH,
        ),
    )


def render_version_line() -> str:
    """The human one-liner ``gda --version`` prints without ``--json``."""
    return f"gda {package_version(DISTRIBUTION)}"
