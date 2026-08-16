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
* the install kind — a built ``wheel`` (no source checkout) or an ``editable``
  install, read from the PEP 610 ``direct_url.json`` the installer recorded, since
  the version string alone cannot tell them apart and ``pip show`` is unavailable
  in a ``uv`` environment;
* for an editable install, the source checkout: its root, its Git revision, and
  whether the working tree is dirty — the three facts GDA-DF-043 needed;
* the Godot binary ``gda`` would use, resolved from the same flag/env precedence
  as every command.

**It never launches Godot.** The motivating environment is a restricted profile
where an engine spawn crashes, which is exactly when provenance matters most — so
the engine VERSION (which only a running engine reports) is left ``None`` with a
stated reason, rather than making the preflight depend on the thing it is meant to
diagnose. Reading the Git revision does run ``git``; that is a different process
from the one under suspicion, and it degrades to ``None`` when unavailable.

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
from enum import Enum
from importlib.metadata import Distribution, PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import url2pathname

from pydantic import BaseModel, Field

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
    """

    WHEEL = "wheel"
    EDITABLE = "editable"


class SourceCheckout(BaseModel):
    """The working tree an editable install imports from.

    ``revision``/``dirty`` are ``None`` when they cannot be resolved — no ``git``
    on ``PATH``, the root is not inside a repository, or the call failed or timed
    out. ``dirty`` counts untracked files as dirty, because an untracked module in
    the checkout is still code the editable install can import.
    """

    root: str
    revision: Optional[str] = None
    dirty: Optional[bool] = None


class GodotProvenance(BaseModel):
    """The engine side of the provenance, resolved WITHOUT launching Godot.

    ``binary`` is the path the same precedence every command uses (``--godot`` →
    ``$GDA_GODOT`` → the built-in default) would resolve; it is reported as
    resolved, not checked for existence, because probing the file is a different
    question from "which engine would this gda use". ``version`` stays ``None``
    unless the version is obtainable without a launch — it is not today, so
    ``version_unavailable_reason`` says so.
    """

    binary: str
    version: Optional[str] = None
    version_unavailable_reason: Optional[str] = None


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
    install_kind: InstallKind = Field(
        description="Whether gda was installed as a built wheel or as an editable "
        "install importing from a source checkout."
    )
    source: Optional[SourceCheckout] = Field(
        default=None,
        description="The source checkout an editable install imports from; null "
        "for a wheel (no checkout) and for an editable install whose recorded "
        "location is not a resolvable local path.",
    )
    godot: GodotProvenance = Field(
        description="The engine gda would use, resolved without launching it."
    )


def read_direct_url(distribution: str = DISTRIBUTION) -> Optional[dict[str, Any]]:
    """Return the PEP 610 ``direct_url.json`` record of ``distribution``.

    The one seam through which install provenance enters this module. Returns
    ``None`` when the distribution is not installed, when the installer wrote no
    record (the ordinary case for an index install), or when the record is
    unreadable or not a JSON object — every one of which means "nothing to
    disclose", not an error worth failing a preflight over.
    """
    try:
        dist = Distribution.from_name(distribution)
        raw = dist.read_text("direct_url.json")
    except (PackageNotFoundError, OSError):
        return None
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _is_editable(direct_url: Optional[dict[str, Any]]) -> bool:
    """Whether the recorded install is editable (PEP 610 ``dir_info.editable``)."""
    if direct_url is None:
        return False
    dir_info = direct_url.get("dir_info")
    return isinstance(dir_info, dict) and bool(dir_info.get("editable"))


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


def _git_output(source_root: Path, *args: str) -> Optional[str]:
    """Run ``git -C <source_root> <args>`` and return stdout, or ``None``.

    ``None`` for every way the answer can be unavailable — ``git`` missing, the
    root not being a repository, a non-zero exit, or the timeout — so a caller
    reports "not resolvable" instead of guessing. ``-C`` gives the usual Git
    meaning of "the repository containing this directory", so a source root nested
    below the repository root still resolves.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _source_checkout(source_root: Path) -> SourceCheckout:
    """Describe ``source_root`` as a checkout, resolving Git state when possible."""
    revision = _git_output(source_root, "rev-parse", "HEAD")
    status = _git_output(source_root, "status", "--porcelain")
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


def build_version_provenance() -> VersionProvenance:
    """Build the ``gda --version --json`` payload; never launches Godot."""
    direct_url = read_direct_url()
    source_root = _recorded_source_root(direct_url)
    editable = _is_editable(direct_url)
    return VersionProvenance(
        gda_version=package_version(DISTRIBUTION),
        executable=_running_executable(),
        interpreter=sys.executable,
        install_kind=InstallKind.EDITABLE if editable else InstallKind.WHEEL,
        # A wheel has no checkout to report; an editable install whose recorded
        # origin is not a local directory has one we cannot name, and both are
        # honestly `null` rather than a fabricated path.
        source=_source_checkout(source_root)
        if editable and source_root is not None
        else None,
        godot=GodotProvenance(
            binary=str(resolve_godot_binary()),
            version=None,
            version_unavailable_reason=GODOT_VERSION_NEEDS_A_LAUNCH,
        ),
    )


def render_version_line() -> str:
    """The human one-liner ``gda --version`` prints without ``--json``."""
    return f"gda {package_version(DISTRIBUTION)}"
