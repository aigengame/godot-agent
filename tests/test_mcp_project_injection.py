"""L2 fast tests: gda-mcp injects the resolved project via GDA_PROJECT (#194).

Mechanism D (ADR-0014, corrected): gda-mcp hands the resolved project to gda
through gda's own ``GDA_PROJECT`` env channel (ADR-0006) on the subprocess, not a
``--project`` flag. So project-taking domain commands consume it while meta
commands (``info``) that reject ``--project`` simply ignore the env — gda-mcp
needs zero per-command knowledge.

These assert the *seam* behavior (the subprocess env, the dispatch passthrough),
engine-free. The real MCP -> gda -> engine chain is the L4 e2e gate.
"""

import json
import sys
from pathlib import Path

from gda.mcp.runner import SubprocessGdaRunner
from gda.mcp.server import build_server, dispatch
from tests.mcp_support import FakeGdaRunner, call_tool, gda_result, schema_then
from tests.support import SCENE_CREATE_RESULT


def _project(dir_path: Path) -> Path:
    """Mark ``dir_path`` a Godot project (a ``project.godot`` is all that counts)."""
    (dir_path / "project.godot").write_text("", encoding="utf-8")
    return dir_path

# A tiny stand-in "gda": echoes the GDA_PROJECT the child process actually sees,
# so the test observes the real subprocess environment without spawning gda.
_ECHO_GDA_PROJECT = [
    sys.executable,
    "-c",
    "import os, sys; sys.stdout.write(os.environ.get('GDA_PROJECT', ''))",
]


def test_subprocess_runner_injects_resolved_project_as_gda_project_env(tmp_path):
    runner = SubprocessGdaRunner(command=_ECHO_GDA_PROJECT)
    result = runner.run([], project=tmp_path)
    assert result.stdout == str(tmp_path)


def test_subprocess_runner_leaves_inherited_env_when_no_project(monkeypatch):
    # project=None must not strip an inherited GDA_PROJECT: gda then applies its
    # own ADR-0006 resolution (including surfacing a typed error if it is invalid).
    monkeypatch.setenv("GDA_PROJECT", "/inherited/project")
    runner = SubprocessGdaRunner(command=_ECHO_GDA_PROJECT)
    result = runner.run([], project=None)
    assert result.stdout == "/inherited/project"


def test_dispatch_passes_resolved_project_to_runner(tmp_path):
    runner = FakeGdaRunner(lambda args, stdin: gda_result(stdout="{}"))
    dispatch(runner, ["scene", "create"], {"path": "main.tscn"}, project=tmp_path)
    _args, _stdin, project = runner.calls[-1]
    assert project == tmp_path


def test_dispatch_defaults_to_no_project(tmp_path):
    runner = FakeGdaRunner(lambda args, stdin: gda_result(stdout="{}"))
    dispatch(runner, ["scene", "create"], {"path": "main.tscn"})
    _args, _stdin, project = runner.calls[-1]
    assert project is None


def test_server_resolves_gda_project_env_and_injects_it_on_dispatch(
    tmp_path, monkeypatch
):
    # The full env -> resolve -> inject glue: GDA_PROJECT points at a real project,
    # so every tool call dispatches gda against it (here observed at the seam).
    proj = _project(tmp_path)
    monkeypatch.setenv("GDA_PROJECT", str(proj))
    runner = FakeGdaRunner(
        schema_then(lambda args, stdin: gda_result(json.dumps(SCENE_CREATE_RESULT)))
    )
    server = build_server(runner)

    call_tool(server, "scene_create", {"path": "main.tscn", "root_type": "Node2D"})

    _args, _stdin, project = runner.calls[-1]
    assert project == proj
