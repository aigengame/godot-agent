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

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult
from tests.support import assert_operation_error, minimal_project


def _patch_launch(monkeypatch, result: RunResult) -> list:
    """Replace the deep-module launch with one returning ``result``; record calls.

    ``watch`` is recorded like the rest of the call: ``script run`` always passes one
    (that is what selects the streaming capture, #655), so a test can assert the
    caller's ``--completion-marker`` reached it without spawning an engine.
    """
    calls: list = []

    def fake_launch(binary, args, *, cwd, timeout, timeout_label="Godot", watch=None):
        calls.append((binary, args, cwd, timeout, timeout_label, watch))
        return result

    monkeypatch.setattr("gda.commands.script.launch", fake_launch)
    return calls


def test_clean_run_emits_the_passthrough_result(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
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
        # The stdout cap (#665): a small stream returns verbatim, with the
        # full byte count and the untruncated markers always present.
        "stdout_bytes": 3,
        "stdout_truncated": False,
        "stdout_file": None,
        # A clean run recognizes no script errors, so the #651 diagnostics channel
        # is present but empty — never absent, so an agent can read it unguarded.
        "diagnostics": [],
    }
    # The recipe launched `--path <project> --script <res path>` with cwd=None.
    (_binary, args, cwd, _timeout, _label, _watch) = calls[0]
    assert args == ["--path", str(project), "--script", "res://logic.gd"]
    assert cwd is None


def test_non_zero_script_exit_is_success_process_exits_zero(monkeypatch, tmp_path):
    # THE CRUX at the CLI boundary: a script quit(1) is a SUCCESS — the JSON carries
    # exit_status=1 but the gda PROCESS exits 0 (not an error envelope). This is the
    # one command where success != zero exit_status.
    project = minimal_project(tmp_path)
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
    project = minimal_project(tmp_path)
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

    assert_operation_error(result, "script_failed")


def test_strict_is_reachable_through_params_json(monkeypatch, tmp_path):
    # --strict is a params field, not an argv-only flag (ADR-0015), so gda-mcp and
    # any JSON caller can opt in exactly as argv does.
    project = minimal_project(tmp_path)
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

    assert_operation_error(result, "script_failed")


def test_params_json_drives_the_same_recipe(monkeypatch, tmp_path):
    # --params-json (ADR-0015) must drive the SAME recipe — a regression guard that
    # the generic dispatch hook does not route script run through the wrong runner.
    project = minimal_project(tmp_path)
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
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="ok\n", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", form, "--project", str(project), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["path"] == "res://logic.gd"
    (_binary, args, _cwd, _timeout, _label, _watch) = calls[0]
    assert args == ["--path", str(project), "--script", "res://logic.gd"]


def test_params_json_accepts_the_project_relative_form_too(monkeypatch, tmp_path):
    # ADR-0015: the argv and --params-json paths must agree on the new form as well,
    # since the acceptance rides on the model's shared NormalizedPath plus the one
    # operation-side lift — not on argv-only handling.
    project = minimal_project(tmp_path)
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
    (_binary, args, _cwd, _timeout, _label, _watch) = calls[0]
    assert args[-1] == "res://logic.gd"


@pytest.mark.parametrize(
    "script",
    [
        "/abs/logic.gd",
        "user://x.gd",
        "uid://cabc123",
        "",
        ".",
        "sub/..",
        "~nosuchuser_gda_test/x.gd",
    ],
)
def test_a_non_project_scoped_path_emits_invalid_path_envelope(
    monkeypatch, tmp_path, script
):
    # The refusals that survive #675's widening, at the CLI boundary: absolute,
    # another engine scheme, and a path naming the project root. `""` is the shape a
    # caller actually hits — an unset variable in `gda script run "$SCRIPT"` — which
    # reached the engine and came back a phantom exit-0 success before this guard.
    # These are ADDRESS-FORM refusals; the upward escapes moved to the shared
    # containment code below (#763).
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", script, "--project", str(project), "--json"],
    )

    assert result.exit_code != 0
    err = json.loads(result.stdout)["error"]
    assert err["code"] == "invalid_path"
    assert not calls, "no engine launch on an invalid path"


@pytest.mark.parametrize("script", ["..", "../outside.gd", "res://../outside.gd"])
def test_an_escaping_path_emits_the_shared_containment_code(
    monkeypatch, tmp_path, script
):
    # #763 at the CLI boundary: an upward escape is the SAME condition
    # `script validate` and `resource import` refuse, so it reports the same code —
    # one containment answer instead of a per-command spelling. It stays a
    # pre-launch refusal, and it names no resolved root, because this whole path
    # edge is decided ahead of the projectless check (ADR-0031).
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        ["script", "run", script, "--project", str(project), "--json"],
    )

    err = assert_operation_error(result, "target_outside_project")
    assert "evidence" not in err
    assert not calls, "no engine launch on an escaping path"


def test_a_tilde_path_is_refused_as_the_absolute_path_it_means(monkeypatch, tmp_path):
    # The shared NormalizedPath is what makes this honest (#675): `~/logic.gd` expands
    # to an absolute path and is refused as one, instead of being lifted into a
    # nonsense `res://~/logic.gd` naming a directory called `~` inside the project.
    project = minimal_project(tmp_path)
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


@pytest.mark.parametrize("channel", ["argv", "params-json"])
def test_an_unexpandable_tilde_keeps_the_structured_refusal(
    monkeypatch, tmp_path, channel
):
    # Base parity, on BOTH input channels (#699 / external review). Giving
    # `ScriptRunParams.path` the shared NormalizedPath sent `~nosuchuser/x.gd` into
    # `Path.expanduser()`, which raises RuntimeError — a bare traceback and exit 1,
    # where the base branch returned this structured invalid_path envelope. The
    # normalizer is total now, so the path arrives unexpanded and the command's own
    # gate refuses it exactly as before.
    #
    # Both channels because they FAIL DIFFERENTLY: --params-json wraps model
    # construction (it would have reported invalid_params), while the argv body builds
    # the model directly and had nothing to catch the raise at all.
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))
    tilde = "~nosuchuser_gda_test/x.gd"
    argv = ["script", "run"]
    argv += (
        [tilde] if channel == "argv" else ["--params-json", json.dumps({"path": tilde})]
    )

    result = CliRunner().invoke(app, [*argv, "--project", str(project), "--json"])

    err = assert_operation_error(result, "invalid_path")
    # The message names the path the caller gave, tilde intact.
    assert tilde in err["message"]
    assert not calls, "no engine launch on an invalid path"


# --- #655: the two new options at the CLI boundary. The classification behind them
# lives in ``tests/script/test_script_run_operation.py``; what only shows here is that argv
# and ``--params-json`` reach the same place (ADR-0015) and that a nonsensical value
# is a usage error rather than a launch.


def test_timeout_reaches_the_launch_from_argv(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "res://logic.gd",
            "--timeout",
            "9.5",
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    (_binary, _args, _cwd, timeout, _label, _watch) = calls[0]
    assert timeout == 9.5


def test_timeout_and_marker_reach_the_launch_through_params_json(monkeypatch, tmp_path):
    # ADR-0015: both are params fields, so a JSON/MCP caller opts in exactly as argv
    # does — a fixed ceiling with no JSON route would leave gda-mcp on the old defect.
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "--params-json",
            '{"path": "res://logic.gd", "timeout": 9.5, '
            '"completion_marker": "SUITE DONE"}',
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    (_binary, _args, _cwd, timeout, _label, watch) = calls[0]
    assert timeout == 9.5
    # The marker reached the watch the streaming capture consults.
    assert watch is not None
    # Asserted through the watch's BEHAVIOUR rather than its internals: an error
    # attributable to the entry followed by a full silence window now asks for the
    # run to end — which an undeclared marker never would.
    entry_error = (
        "SCRIPT ERROR: Invalid call. Nonexistent function 'boom' in base 'Nil'.\n"
        "          at: _initialize (res://logic.gd:3)\n"
    )
    assert not watch.observe(stdout="", stderr=entry_error, elapsed=0.1)
    assert watch.observe(stdout="", stderr="", elapsed=99.0)


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_a_non_positive_timeout_is_a_usage_error_not_a_launch(
    monkeypatch, tmp_path, timeout
):
    # A zero or negative ceiling would end every run instantly. It is refused before
    # any spawn — as a usage error on argv, where Click's exit 2 is the ergonomic
    # answer, mirroring how `script set` handles a contradictory edit.
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "res://logic.gd",
            "--timeout",
            timeout,
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert not calls, "a rejected --timeout must never reach the launch"


def test_a_non_positive_timeout_is_structured_through_params_json(
    monkeypatch, tmp_path
):
    # The same rule on the JSON path surfaces as the structured `invalid_params`
    # envelope rather than a Click usage error, because the model enforces it
    # (ADR-0015) — one rule, two idiomatic reports.
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "--params-json",
            '{"path": "res://logic.gd", "timeout": 0}',
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert not calls


def test_an_empty_completion_marker_is_refused(monkeypatch, tmp_path):
    # An empty marker would match every line, disarming the abort while looking
    # declared — the same class of mistake as an empty --godot, so it is refused
    # rather than silently ignored.
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "res://logic.gd",
            "--completion-marker",
            "",
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert not calls


@pytest.mark.parametrize("value", ["inf", "Infinity", "-inf", "nan", "1e400"])
def test_a_non_finite_timeout_is_refused_on_argv(monkeypatch, tmp_path, value):
    # A ceiling of `inf` passes a bare `> 0` test and then makes `elapsed >= timeout`
    # unsatisfiable, so the run gda promised to BOUND would never be bounded — the
    # exact opposite of what the option is for, and reached by an ordinary CLI string
    # because Click parses these through float(). `nan` fails the same way, comparing
    # false against everything. `1e400` overflows to inf without ever spelling it.
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "res://logic.gd",
            "--timeout",
            value,
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert not calls, "a non-finite --timeout must never reach the launch"


@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN", "1e400"])
def test_a_non_finite_timeout_is_refused_through_params_json(
    monkeypatch, tmp_path, literal
):
    # The same rule on the JSON route, where it is even easier to reach: Python's JSON
    # decoder accepts the `Infinity`/`NaN` extensions, and a plain overflowing literal
    # needs no extension at all. Enforced by the shared params model, so it surfaces as
    # the structured `invalid_params` envelope (ADR-0015).
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "--params-json",
            '{"path": "res://logic.gd", "timeout": ' + literal + "}",
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert not calls, "a non-finite timeout must never reach the launch"


@pytest.mark.parametrize("marker", ["", " ", "\t", "\n"])
def test_a_blank_completion_marker_is_refused_on_argv(monkeypatch, tmp_path, marker):
    # The marker is compared as a stripped whole LINE, so a blank one would equal every
    # blank line the run prints and arm the abort on nothing. Refused rather than
    # silently ignored — the same treatment an empty --godot gets.
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "res://logic.gd",
            "--completion-marker",
            marker,
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert result.exit_code == 2, result.stdout + result.stderr
    assert not calls


def test_a_blank_completion_marker_is_refused_through_params_json(
    monkeypatch, tmp_path
):
    project = minimal_project(tmp_path)
    calls = _patch_launch(monkeypatch, RunResult(stdout="", stderr="", exit_code=0))

    result = CliRunner().invoke(
        app,
        # fmt: off
        [
            "script",
            "run",
            "--params-json",
            '{"path": "res://logic.gd", "completion_marker": "  "}',
            "--project",
            str(project),
            "--json",
        ],
        # fmt: on
    )

    assert json.loads(result.stdout)["error"]["code"] == "invalid_params"
    assert not calls
