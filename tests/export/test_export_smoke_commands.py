"""S3: the ``gda export smoke`` command surface, engine-free (ADR-0042, #979).

What the operation does is asserted in
``tests/export/test_export_smoke_operation.py``; what the COMMAND publishes is
asserted here — its argv form, its projectlessness, the two input channels
(ADR-0015), the rendered and JSON results, and the negative gate on its own
public surfaces. The launch seam is patched on the module, so the full
Typer → recipe → classify → emit pipeline runs without an engine.
"""

import json
import stat
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.export import (
    EXPORT_RUN_COMMAND,
    EXPORT_SMOKE_COMMAND,
    ExportSmokeResult,
)
from gda.error_codes import ERROR_CODE_BY_CODE
from gda.runner import RunResult
from tests.support import panel_text, plain_text, usage_error_text

# The keys `export smoke`'s success result publishes, in the order it publishes
# them: the two addresses it adds, then the completed-run half it shares with
# `script run` (`gda.completed_run`). Spelled out rather than derived, because
# this IS the contract a consuming agent reads — and because the negative gate
# below is only as strong as this list is exact.
SMOKE_RESULT_KEYS = [
    "artifact",
    "executable",
    "exit_status",
    "stdout",
    "stderr",
    "stdout_bytes",
    "stdout_truncated",
    "stdout_file",
    "diagnostics",
]

SMOKE_INPUT_KEYS = {"artifact", "args", "quit_after", "timeout", "strict"}


def runnable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class StubLaunch:
    """A ``gda.commands.export.launch`` stand-in returning one canned run."""

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def __call__(self, binary, args, **kwargs):
        self.calls.append((binary, args, kwargs))
        return self.result


def invoke(monkeypatch, argv, *, result: RunResult | None = None, env=None):
    stub = StubLaunch(result or RunResult(stdout="", stderr="", exit_code=0))
    monkeypatch.setattr("gda.commands.export.launch", stub)
    return CliRunner().invoke(app, argv, env=env or {}), stub


# --- The argv form and the two input channels --------------------------------


def test_the_artifact_is_the_positional_argument(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")

    result, stub = invoke(
        monkeypatch,
        ["export", "smoke", str(artifact), "--json"],
        result=RunResult(stdout="hi\n", stderr="", exit_code=0),
    )

    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert list(data) == SMOKE_RESULT_KEYS
    assert data["artifact"] == str(artifact)
    assert data["executable"] == str(artifact)
    assert data["stdout"] == "hi\n"


def test_repeated_arg_options_reach_the_game_in_order(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")

    _result, stub = invoke(
        monkeypatch,
        [
            "export",
            "smoke",
            str(artifact),
            "--arg",
            "one",
            "--arg",
            "two",
            "--json",
        ],
    )

    assert stub.calls[0][1] == ["--", "one", "two"]


def test_quit_after_is_placed_before_the_separator_from_argv(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")

    _result, stub = invoke(
        monkeypatch,
        ["export", "smoke", str(artifact), "--quit-after", "30", "--json"],
    )

    assert stub.calls[0][1] == ["--quit-after", "30", "--"]


def test_params_json_drives_the_same_path_as_argv(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")
    params = json.dumps(
        {"artifact": str(artifact), "args": ["one"], "quit_after": 4, "strict": False}
    )

    result, stub = invoke(
        monkeypatch,
        ["export", "smoke", "--params-json", params, "--json"],
    )

    assert result.exit_code == 0, result.stdout
    assert stub.calls[0][1] == ["--quit-after", "4", "--", "one"]


def test_a_negative_quit_after_is_a_usage_error(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")

    result, stub = invoke(
        monkeypatch, ["export", "smoke", str(artifact), "--quit-after", "-1", "--json"]
    )

    assert "greater than or equal to 0" in usage_error_text(result)
    assert not stub.calls


def test_a_non_finite_timeout_is_a_usage_error(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")

    result, stub = invoke(
        monkeypatch, ["export", "smoke", str(artifact), "--timeout", "inf", "--json"]
    )

    assert result.exit_code == 2
    assert not stub.calls


def test_a_strict_failure_is_the_operation_envelope(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")

    result, _stub = invoke(
        monkeypatch,
        ["export", "smoke", str(artifact), "--strict", "--json"],
        result=RunResult(stdout="", stderr="", exit_code=2),
    )

    assert result.exit_code == 4, result.stdout
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "smoke_failed"
    assert error["category"] == "operation"
    assert error["evidence"]["exit_status"] == 2


def test_the_human_rendering_leads_with_the_executable_and_the_status(
    monkeypatch, tmp_path
):
    artifact = runnable(tmp_path / "game")

    result, _stub = invoke(
        monkeypatch,
        ["export", "smoke", str(artifact)],
        result=RunResult(stdout="hello\n", stderr="", exit_code=3),
    )

    assert result.exit_code == 0, result.stdout
    lines = plain_text(result.stdout).splitlines()
    assert lines[0] == f"executable: {artifact}"
    assert lines[1] == "exit_status: 3"
    assert "hello" in result.stdout


# --- Projectless (ADR-0042) --------------------------------------------------


def test_the_command_refuses_project_as_an_unknown_option(monkeypatch, tmp_path):
    artifact = runnable(tmp_path / "game")

    result, stub = invoke(
        monkeypatch,
        ["export", "smoke", str(artifact), "--project", str(tmp_path), "--json"],
    )

    # Refused by the parser and reported through the shared Error envelope (#685),
    # so an agent reads the refusal as a code rather than as a usage panel.
    assert result.exit_code == 2
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "unknown_option"
    assert error["category"] == "usage"
    assert "--project" in error["message"]
    assert not stub.calls


def test_an_unusable_inherited_project_cannot_make_the_command_fail(
    monkeypatch, tmp_path
):
    # `inherits_project=False` in one observable sentence: a $GDA_PROJECT that would
    # be `project_not_found` for any domain command is simply never read here.
    artifact = runnable(tmp_path / "game")

    result, _stub = invoke(
        monkeypatch,
        ["export", "smoke", str(artifact), "--json"],
        env={"GDA_PROJECT": str(tmp_path / "not-a-project")},
    )

    assert result.exit_code == 0, result.stdout


def test_a_relative_artifact_resolves_against_the_invocation_cwd(monkeypatch, tmp_path):
    # Through the real argv path: BOTH addresses come back absolute, because the
    # params model makes the artifact absolute before it is resolved (#403) and the
    # executable is derived from that value. A relative `executable` is unusable to
    # any consumer that is not standing in the invocation cwd — an MCP caller
    # included, whose runner sets the subprocess cwd (#979 review, P2-1).
    (tmp_path / "build").mkdir()
    artifact = runnable(tmp_path / "build" / "game")
    monkeypatch.chdir(tmp_path)

    result, stub = invoke(monkeypatch, ["export", "smoke", "build/game", "--json"])

    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["artifact"] == str(artifact)
    assert Path(data["executable"]).is_absolute()
    assert data["executable"] == str(artifact)
    assert stub.calls[0][0] == artifact


def test_a_relative_artifact_refusal_names_the_absolute_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    result, stub = invoke(
        monkeypatch, ["export", "smoke", "build/never-exported", "--json"]
    )

    assert result.exit_code == 4, result.stdout
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "export_artifact_not_found"
    assert str(tmp_path / "build" / "never-exported") in error["message"]
    assert not stub.calls


def test_the_two_artifact_refusals_reach_the_cli(monkeypatch, tmp_path):
    result, _stub = invoke(
        monkeypatch, ["export", "smoke", str(tmp_path / "gone"), "--json"]
    )
    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "export_artifact_not_found"

    (tmp_path / "dir").mkdir()
    result, _stub = invoke(
        monkeypatch, ["export", "smoke", str(tmp_path / "dir"), "--json"]
    )
    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "export_artifact_not_runnable"


# --- Self-description --------------------------------------------------------


def test_the_schema_publishes_the_input_output_and_the_artifact_smoke_kind():
    result = CliRunner().invoke(app, ["export", "smoke", "--schema"])

    assert result.exit_code == 0, result.stdout
    schema = json.loads(result.stdout)
    assert set(schema["input"]["properties"]) == SMOKE_INPUT_KEYS
    assert list(schema["output"]["properties"]) == SMOKE_RESULT_KEYS
    assert schema["kind"] == "artifact_smoke"
    # The shared bounded-stdout truth table comes with the base (#748 review).
    assert "allOf" in schema["output"]
    # The uniform failure envelope, unchanged: this command adds no error shape,
    # so the envelope still $refs the ONE shared GdaError (ADR-0004).
    assert schema["error"]["properties"]["error"] == {"$ref": "#/$defs/GdaError"}
    assert "evidence" in schema["error"]["$defs"]["GdaError"]["properties"]


def test_the_help_states_the_bounded_support_and_the_two_gotchas():
    # The README scope rule's content, in the command's own help: what it accepts,
    # where the evidence comes from, and the two things a caller must not read into
    # `--quit-after` / `--timeout` (#979 AC).
    result = CliRunner().invoke(app, ["export", "smoke", "--help"])

    assert result.exit_code == 0
    text = panel_text(result.stdout)
    assert ".app" in text and "execute" in text
    assert "macOS only" in text
    assert "Linux and Windows" in text
    assert "asserts nothing about the game" in text
    assert "hard bound" in text


def test_the_three_codes_are_registered_operation_codes_at_exit_four():
    for code in (
        "export_artifact_not_found",
        "export_artifact_not_runnable",
        "smoke_failed",
    ):
        spec = ERROR_CODE_BY_CODE[code]
        assert spec.category.value == "operation", code
        assert spec.exit_code == 4, code
        assert spec.source.value == "classifier", code


# --- The negative gate on this command's OWN surfaces ------------------------

# ADR-0042 excluded each of these by name. The gate reads only `export smoke`'s
# declared options, its input/output schema and its result keys — never
# `export run`'s, whose #839 project-tree mutation report is a different fact on
# a different command and is asserted alive at the bottom of this file.
_EXCLUDED_OPTIONS = {
    "--digest",
    "--sha256",
    "--windowed",
    "--completion-marker",
    "--pck",
    "--inventory",
    "--manifest",
    "--receipt",
}

# The words that would mark an excluded surface if this command's help described
# one. `--user-data-root` is deliberately NOT here: the help points at the global
# option, which is the caller's own and not a result field — the transient
# placement is gated on the RESULT KEYS below, where it would actually appear.
_EXCLUDED_HELP_WORDS = (
    "digest",
    "SHA-256",
    "windowed",
    "completion marker",
    "completion-marker",
    "smoke_aborted",
    "provenance",
    "receipt",
    "manifest",
)


def _smoke_option_names() -> set[str]:
    command = EXPORT_SMOKE_COMMAND.command_class()
    result = CliRunner().invoke(app, ["export", "smoke", "--help"])
    assert result.exit_code == 0, result.stdout
    assert command is not None
    return {
        token for token in panel_text(result.stdout).split() if token.startswith("--")
    }


def test_the_excluded_surfaces_do_not_exist_on_this_command():
    options = _smoke_option_names()
    assert not (options & _EXCLUDED_OPTIONS), sorted(options & _EXCLUDED_OPTIONS)

    help_text = panel_text(
        CliRunner().invoke(app, ["export", "smoke", "--help"]).stdout
    )
    for word in _EXCLUDED_HELP_WORDS:
        assert word not in help_text, word

    schema = json.loads(CliRunner().invoke(app, ["export", "smoke", "--schema"]).stdout)
    assert set(schema["input"]["properties"]) == SMOKE_INPUT_KEYS
    assert list(schema["output"]["properties"]) == SMOKE_RESULT_KEYS
    # Transient placement, stated where it would appear: the private root this
    # command creates and removes is never a result field (#862's three named
    # placement builders stay three, and no fourth result publishes the keys).
    assert not (
        {"engine_data_path", "user_data_root", "log_file"}
        & set(schema["output"]["properties"])
    )
    assert not (
        {"engine_data_path", "user_data_root", "log_file"}
        & set(ExportSmokeResult.model_fields)
    )


def test_no_smoke_aborted_code_is_registered():
    # ADR-0042 rejected a completion-marker protocol, so there is no early-abort
    # verdict to register: an exported game has no single entry script whose
    # continued output could carry the liveness contract.
    assert "smoke_aborted" not in ERROR_CODE_BY_CODE


def test_the_gate_leaves_export_runs_own_mutation_report_alone():
    # The scoping, asserted rather than promised: #839's project-tree mutation
    # report is `export run`'s and is untouched by anything above.
    assert "project_tree_mutations" in EXPORT_RUN_COMMAND.output_model.model_fields
