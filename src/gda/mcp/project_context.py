"""gda-mcp server project-context resolution (issue #194, ADR-0014).

gda-mcp is a long-lived server serving many calls; it resolves ONE target Godot
project for the server and hands it to its ``gda`` subprocesses. Resolution is by
an **agent-neutral portable precedence** (cwd is unreliable across MCP clients),
first hit wins:

1. an explicit ``GDA_PROJECT`` in the server's environment,
2. the MCP ``roots/list`` the client advertises,
3. the process cwd, as a last-resort fallback.

The precedence names only agent-neutral primitives — gda's own env, the MCP
protocol's own workspace signal, and cwd. No agent-specific env var appears here;
per-agent config is the registration recipes' concern (ADR-0013), not the core.

This module owns only the *pure* resolution (``env``/``roots``/``cwd`` in, a
project dir or ``None`` out). The resolved dir reaches ``gda`` through gda's own
``GDA_PROJECT`` channel (ADR-0006) — set on the subprocess env — so meta commands
(``info``), which never inherit a project (#670), ignore it while domain commands
consume it, with no per-command knowledge in gda-mcp.

Per ADR-0011 gda-mcp imports no gda internal symbol; the ``GDA_PROJECT`` name and
the ``project.godot`` marker are part of the public ABI, defined locally here.
"""

from pathlib import Path
from typing import Mapping, Optional, Sequence

# Public ABI, redefined locally rather than imported from gda (ADR-0011).
GDA_PROJECT_ENV = "GDA_PROJECT"
PROJECT_MARKER = "project.godot"


def _is_project(path: Path) -> bool:
    """Whether ``path`` is a Godot project root (holds a ``project.godot``)."""
    return (path / PROJECT_MARKER).exists()


def resolve_project_dir(
    env: Mapping[str, str], roots: Sequence[str], cwd: Path
) -> Optional[Path]:
    """Resolve the server's target project by the ADR-0014 precedence."""
    gda_project = env.get(GDA_PROJECT_ENV)
    if gda_project:
        # An explicitly pinned GDA_PROJECT is strict (ADR-0006): if it is not a
        # real project we do NOT silently fall through to a roots/cwd candidate.
        # Resolve None and inject nothing — gda inherits the explicit GDA_PROJECT
        # and surfaces its own typed error for project-taking commands, while
        # meta commands (info), which never inherit a project, ignore it.
        #
        # The expansion is TOTAL: `Path.expanduser()` raises `RuntimeError` for a
        # `~unknownuser/…` prefix this host cannot resolve, which killed the
        # resolution outright (#988). Such a value names no home, so it is kept as
        # the caller wrote it — the same rule `gda.project.expand_user` states for
        # gda's own path options, written out here rather than imported, as
        # ADR-0011 requires of every name this module shares with gda. The literal
        # then either IS a project on disk or is not, and the strict path above
        # decides; either way gda gets the last word.
        try:
            candidate = Path(gda_project).expanduser()
        except RuntimeError:
            candidate = Path(gda_project)
        return candidate if _is_project(candidate) else None

    for root in roots:
        candidate = Path(root)
        if _is_project(candidate):
            return candidate

    return cwd if _is_project(cwd) else None
