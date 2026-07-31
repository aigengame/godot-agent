"""The single subprocess seam gda-mcp runs ``gda`` through (ADR-0011).

One low-level seam: given an argv tail (and optional stdin), it spawns the
installed ``gda`` and returns the *raw* ``{stdout, stderr, returncode}`` —
unparsed. BOTH startup dump-introspection (``gda schema``) and per-tool dispatch
(``gda <group> <command> --params-json -``) go through it, so the success/error
mapping lives ABOVE the seam and is unit-testable by injecting a fake (Design
decision 2). Keeping the seam raw mirrors gda's own ``RunResult`` discipline one
layer down.

The binary is ``[sys.executable, "-m", "gda"]`` — the exact gda paired with the
running gda-mcp (same distribution, the ``[mcp]`` extra), NOT a PATH lookup that
could resolve a *wrong global* ``gda`` (Design decision 3; the PR #196 review
lesson, ``shutil.which`` deliberately rejected). An optional ``$GDA_BIN`` env var
overrides it for deployments that need a specific command line.
"""

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from gda.mcp.project_context import GDA_PROJECT_ENV

# Override the default ``-m gda`` invocation with an explicit command line.
GDA_BIN_ENV = "GDA_BIN"

# The exit code synthesized when the gda command itself cannot be launched (the
# binary is missing / not executable) — the shell "command not found" convention,
# matching gda's own runner (gda.exit_codes.EXIT_NOT_FOUND). The value only has to
# be non-zero for the layer above to treat it as a failure; 127 keeps it legible.
_LAUNCH_FAILURE_EXIT = 127


@dataclass(frozen=True)
class GdaResult:
    """The raw outcome of one ``gda`` subprocess run — unparsed (ADR-0011)."""

    stdout: str
    stderr: str
    returncode: int


class GdaRunner(Protocol):
    """Runs ``gda`` with an argv tail and optional stdin, returns raw output.

    A Protocol so fast tests inject a fake seam (mirroring gda's own
    ``FakeRunner``, one layer up) and exercise the whole introspect/dispatch +
    result/error mapping engine-free.
    """

    def run(
        self,
        args: list[str],
        *,
        stdin: Optional[str] = None,
        project: Optional[Path] = None,
    ) -> GdaResult: ...


def gda_command() -> list[str]:
    """The base argv that invokes gda (Design decision 3).

    ``$GDA_BIN`` (shell-split) when set, else ``[sys.executable, "-m", "gda"]`` —
    the same interpreter running gda-mcp, so gda-mcp and gda are guaranteed the
    one distribution rather than whatever ``gda`` a PATH search might surface.
    """
    override = os.environ.get(GDA_BIN_ENV)
    if override:
        return shlex.split(override)
    return [sys.executable, "-m", "gda"]


@dataclass(frozen=True)
class SubprocessGdaRunner:
    """The real :class:`GdaRunner`: spawns ``gda`` as a one-shot subprocess."""

    command: list[str]

    @classmethod
    def default(cls) -> "SubprocessGdaRunner":
        """Build the runner from the resolved :func:`gda_command`."""
        return cls(command=gda_command())

    def run(
        self,
        args: list[str],
        *,
        stdin: Optional[str] = None,
        project: Optional[Path] = None,
    ) -> GdaResult:
        # Hand the resolved project to gda through its own ``GDA_PROJECT`` channel
        # (ADR-0006), not a ``--project`` flag: meta commands (``info``) that
        # reject ``--project`` simply ignore the env, so gda-mcp injects uniformly
        # with no per-command knowledge (ADR-0014, mechanism D). ``project=None``
        # leaves the inherited environment untouched — an explicit-but-invalid
        # ``GDA_PROJECT`` then reaches gda, which surfaces its own typed error for
        # project-taking commands.
        env: Optional[dict[str, str]] = None
        if project is not None:
            env = {**os.environ, GDA_PROJECT_ENV: str(project)}
        # Capture raw bytes (no ``text=True``) and decode UTF-8 explicitly, like
        # gda's own runner (issue #33): gda emits its ``--json`` result as UTF-8
        # via pydantic, which can carry non-ASCII (e.g. a CJK node name); a
        # locale-based decode would mojibake it on a non-UTF-8 locale.
        try:
            proc = subprocess.run(
                [*self.command, *args],
                input=stdin.encode("utf-8") if stdin is not None else None,
                capture_output=True,
                env=env,
            )
        except OSError as exc:
            # The gda command itself could not be launched — e.g. a ``$GDA_BIN``
            # override pointing at a missing / non-executable path. Mirror gda's
            # own runner (gda.runner.launch): never let the OSError escape;
            # synthesize a non-zero raw result so the layer above turns it into a
            # structured ``is_error`` (ADR-0011's "can't-run" edge, synthesized by
            # gda-mcp) rather than a traceback crossing the MCP boundary.
            return GdaResult(
                stdout="",
                stderr=f"gda could not be launched: {self.command!r} ({exc})",
                returncode=_LAUNCH_FAILURE_EXIT,
            )
        return GdaResult(
            stdout=proc.stdout.decode("utf-8", errors="replace"),
            stderr=proc.stderr.decode("utf-8", errors="replace"),
            returncode=proc.returncode,
        )
