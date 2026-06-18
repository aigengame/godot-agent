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
from typing import Optional, Protocol

# Override the default ``-m gda`` invocation with an explicit command line.
GDA_BIN_ENV = "GDA_BIN"


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

    def run(self, args: list[str], *, stdin: Optional[str] = None) -> GdaResult: ...


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

    def run(self, args: list[str], *, stdin: Optional[str] = None) -> GdaResult:
        # Capture raw bytes (no ``text=True``) and decode UTF-8 explicitly, like
        # gda's own runner (issue #33): gda emits its ``--json`` result as UTF-8
        # via pydantic, which can carry non-ASCII (e.g. a CJK node name); a
        # locale-based decode would mojibake it on a non-UTF-8 locale.
        proc = subprocess.run(
            [*self.command, *args],
            input=stdin.encode("utf-8") if stdin is not None else None,
            capture_output=True,
        )
        return GdaResult(
            stdout=proc.stdout.decode("utf-8", errors="replace"),
            stderr=proc.stderr.decode("utf-8", errors="replace"),
            returncode=proc.returncode,
        )
