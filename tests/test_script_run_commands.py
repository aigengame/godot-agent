"""S3: gda script run through the full CLI pipeline against a fake launch (issue #343).

``script run`` is the third execution shape (ADR-0031): a user-script passthrough
run, fulfilled by the CLI-side recipe ``run_script_run_operation`` rather than the
operations.gd sentinel. The engine-touching step is the deep-module
:func:`gda.runner.launch`, which these tests replace with a canned
:class:`~gda.runner.RunResult` (patched at ``gda.commands.script.launch``), so the full
Typer → recipe → classify → JSON/emit pipeline runs engine-free.

They pin the two behaviors that only show at the CLI boundary: a clean engine exit
emits the SUCCESS result AND the process exits 0 — even when the script's own
``exit_status`` is non-zero (the ADR-0031 crux) — while the pre-run ABI edges emit
the uniform Error envelope. The ``--params-json`` case guards that it drives the
SAME recipe (ADR-0015), not the wrong runner.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult


def _patch_launch(monkeypatch, result: RunResult) -> list:
    """Replace the deep-module launch with one returning ``result``; record calls."""
    calls: list = []

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot"):
        calls.append((binary, args, cwd, timeout, timeout_label))
        return result

    monkeypatch.setattr("gda.commands.script.launch", fake_launch)
    return calls


def _project(tmp_path: Path) -> Path:
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return tmp_path


def test_clean_run_emits_the_passthrough_result(monkeypatch, tmp_path):
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="hi\n", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", "res://logic.gd", "--project", str(project), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data == {
        # The canonical res:// address of what ran (#675) — present on every success
        # result, whichever of the two accepted forms the caller used.
        "path": "res://logic.gd",
        "exit_status": 0,
        "stdout": "hi\n",
        "stderr": "",
        # A clean run recognizes no script errors, so the #651 diagnostics channel
        # is present but empty — never absent, so an agent can read it unguarded.
        "diagnostics": [],
    }
    # The recipe launched `--path <project> --script <res path>` with cwd=None.
    (_binary, args, cwd, _timeout, _label) = calls[0]
    assert args == ["--path", str(project), "--script", "res://logic.gd"]
    assert cwd is None


def test_non_zero_script_exit_is_success_process_exits_zero(monkeypatch, tmp_path):
    # THE CRUX at the CLI boundary: a script quit(1) is a SUCCESS — the JSON carries
    # exit_status=1 but the gda PROCESS exits 0 (not an error envelope). This is the
    # one command where success != zero exit_status.
    project = _project(tmp_path)
    _patch_launch(monkeypatch, RunResult(stdout="fail\n", stderr="", exit_code=1))

    result = CliRunner().invoke(
        app,
        ["script", "run", "res://logic.gd", "--project", str(project), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert "error" not in data
    assert data["exit_status"] == 1
    assert data["stdout"] == "fail\n"


def test_strict_makes_the_process_exit_the_registered_operation_code(
    monkeypatch, tmp_path
):
    # #651 at the CLI boundary: with --strict a quit(1) is observable WITHOUT parsing
    # the JSON — the process exits 4, the registered operation code. Not 1: the
    # child's own status is never propagated verbatim, or a script's quit(3) would
    # alias EXIT_VERSION and a quit(124) the runner's timeout.
    project = _project(tmp_path)
    _patch_launch(monkeypatch, RunResult(stdout="fail\n", stderr="", exit_code=1))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "run",
            "res://logic.gd",
            "--strict",
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 4, result.stdout + result.stderr
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "script_failed"
    assert err["category"] == "operation"


def test_strict_is_reachable_through_params_json(monkeypatch, tmp_path):
    # --strict is a params field, not an argv-only flag (ADR-0015), so gda-mcp and
    # any JSON caller can opt in exactly as argv does.
    project = _project(tmp_path)
    _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=2))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "run",
            "--params-json",
            '{"path": "res://logic.gd", "strict": true}',
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 4, result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]["code"] == "script_failed"


def test_params_json_drives_the_same_recipe(monkeypatch, tmp_path):
    # --params-json (ADR-0015) must drive the SAME recipe — a regression guard that
    # the generic dispatch hook does not route script run through the wrong runner.
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="ok\n", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "run",
            "--params-json",
            '{"path": "res://logic.gd"}',
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["exit_status"] == 0
    assert calls, "the launch seam was never reached via --params-json"


@pytest.mark.parametrize("form", ["logic.gd", "res://logic.gd"])
def test_both_path_forms_are_accepted_at_the_cli(monkeypatch, tmp_path, form):
    # AC of #675 at the CLI boundary: ONE script-path representation now serves both
    # `script validate` and `script run`. Whichever form the caller types, the launch
    # gets the canonical res:// address and the result reports it back.
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="ok\n", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", form, "--project", str(project), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["path"] == "res://logic.gd"
    (_binary, args, _cwd, _timeout, _label) = calls[0]
    assert args == ["--path", str(project), "--script", "res://logic.gd"]


def test_params_json_accepts_the_project_relative_form_too(monkeypatch, tmp_path):
    # ADR-0015: the argv and --params-json paths must agree on the new form as well,
    # since the acceptance rides on the model's shared NormalizedPath plus the one
    # operation-side lift — not on argv-only handling.
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="ok\n", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        [
            "script",
            "run",
            "--params-json",
            '{"path": "logic.gd"}',
            "--project",
            str(project),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["path"] == "res://logic.gd"
    (_binary, args, _cwd, _timeout, _label) = calls[0]
    assert args[-1] == "res://logic.gd"


def test_absolute_path_emits_invalid_path_envelope(monkeypatch, tmp_path):
    # The one path form still refused (#675 narrowed the edge): an absolute path is
    # outside the --project context, so it is a structured envelope before any launch.
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", "/abs/logic.gd", "--project", str(project), "--json"],
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"
    assert not calls, "no engine launch on an invalid path"


def test_a_tilde_path_is_refused_as_the_absolute_path_it_means(monkeypatch, tmp_path):
    # The shared NormalizedPath is what makes this honest (#675): `~/logic.gd` expands
    # to an absolute path and is refused as one, instead of being lifted into a
    # nonsense `res://~/logic.gd` naming a directory called `~` inside the project.
    project = _project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", "~/logic.gd", "--project", str(project), "--json"],
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"
    assert "res://~" not in err["message"]
    assert not calls


def test_no_resolved_project_emits_project_not_found(monkeypatch, tmp_path):
    # No --project and a projectless cwd → structured project_not_found, before any
    # launch. chdir into a dir with no project.godot to make resolution yield None.
    projectless = tmp_path / "empty"
    projectless.mkdir()
    monkeypatch.chdir(projectless)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["script", "run", "res://logic.gd", "--json"])

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "project_not_found"
    assert not calls


def test_explicit_bad_project_is_structured_not_a_traceback(monkeypatch, tmp_path):
    # An EXPLICIT --project that is not a Godot project makes resolve_project_dir RAISE
    # ValueError — which the recipe must convert to the SAME structured project_not_found
    # the None case yields, never letting the raise escape as a traceback (ADR-0031 /
    # #343 AC). The projectless-cwd None guard alone would MISS this raise path.
    not_a_project = tmp_path / "not-a-godot-project"
    not_a_project.mkdir()  # exists, but has no project.godot
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", "res://logic.gd", "--project", str(not_a_project), "--json"],
    )

    assert result.exit_code != 0
    # A structured envelope on stdout, NOT a Rich/Python traceback.
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "project_not_found"
    assert not calls, "no engine launch when the project cannot resolve"


def test_bad_gda_project_env_is_structured_not_a_traceback(monkeypatch, tmp_path):
    # The same raise path via $GDA_PROJECT (env precedence, not the --project flag):
    # an env pointing at a non-project also raises ValueError and must yield the
    # structured project_not_found envelope, not a traceback.
    not_a_project = tmp_path / "env-not-a-project"
    not_a_project.mkdir()
    monkeypatch.setenv("GDA_PROJECT", str(not_a_project))
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(app, ["script", "run", "res://logic.gd", "--json"])

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "project_not_found"
    assert not calls
