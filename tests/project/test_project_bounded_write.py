"""S3: a project write is bounded to the request and discloses the rest (#843).

Every writer in the ``project`` group persists through ``ProjectSettings.save()``,
which RESERIALIZES ``project.godot``: it drops each explicit line whose value equals
the engine's initial value, adds or rewrites ``application/config/features``, and
writes the sections in its own order. gda restores the dropped declarations and
reports the residual mutation on the result.

The engine is faked here — a runner that replays the reserialized file the engine
would have written — so the wiring (read before, restore after, report on every
writer, on both input paths) is proven without a Godot launch. The real engine's own
reserialization is pinned by the e2e tier (``test_e2e_project.py``).
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.project import (
    PROJECT_ADD_AUTOLOAD_COMMAND,
    PROJECT_ADD_INPUT_ACTION_COMMAND,
    PROJECT_REMOVE_AUTOLOAD_COMMAND,
    PROJECT_REMOVE_INPUT_ACTION_COMMAND,
    PROJECT_SET_COMMAND,
)
from gda.runner import RunResult
from tests.support import ENGINE_BANNER, FakeRunner, sentinel


# The file a hand-authored project holds: an explicit default-equal declaration
# (the engine drops it on every save), a custom section, no features list.
BEFORE = """\
config_version=5

[application]

config/name="fixture"

[zsection]

my/custom=42

[debug]

file_logging/enable_file_logging=false
file_logging/enable_file_logging.pc=false
"""

# What the engine writes back (the shape a real save produces — see the e2e tier):
# the default-equal line gone, a features list added, the sections in the engine's
# own (alphabetical) order.
AFTER = """\
; Engine configuration file.

config_version=5

[application]

config/name="fixture"
config/features=PackedStringArray("4.6")

[debug]

file_logging/enable_file_logging.pc=false

[zsection]

my/custom=42
"""

# The same save when the ADDRESSED setting is the default-equal one: the operation
# moves its initial value aside, so the engine writes the line itself.
AFTER_FORCED = AFTER.replace(
    "file_logging/enable_file_logging.pc=false",
    "file_logging/enable_file_logging=false\nfile_logging/enable_file_logging.pc=false",
)

SET_RESULT = {
    "setting": "application/config/name",
    "type": "String",
    "value": "fixture",
}


class ReserializingRunner(FakeRunner):
    """A fake engine run that REWRITES ``project.godot`` the way the engine does."""

    def __init__(self, result: RunResult, path, after: str) -> None:
        super().__init__(result)
        self._path = path
        self._after = after

    def run(self, operation: str, params: dict) -> RunResult:
        self._path.write_text(self._after, encoding="utf-8")
        return super().run(operation, params)


def write_project(tmp_path, text: str = BEFORE):
    (tmp_path / "project.godot").write_text(text, encoding="utf-8")
    return tmp_path / "project.godot"


def invoke_write(monkeypatch, tmp_path, argv, *, payload=SET_RESULT, after=AFTER):
    """Run a project writer against a fake engine that reserializes the file."""
    path = write_project(tmp_path)
    fake = ReserializingRunner(
        RunResult(stdout=ENGINE_BANNER + sentinel(payload), stderr="", exit_code=0),
        path,
        after,
    )
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)
    result = CliRunner().invoke(app, [*argv, "--project", str(tmp_path)])
    return result, path, fake


def test_a_dropped_explicit_default_line_is_restored_verbatim(monkeypatch, tmp_path):
    result, path, _ = invoke_write(
        monkeypatch,
        tmp_path,
        ["project", "set", "application/config/name", "--value", "fixture", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    text = path.read_text(encoding="utf-8")
    # The caller's own declaration is back, in the section it was written in.
    assert "file_logging/enable_file_logging=false" in text
    assert "[debug]" in text
    assert json.loads(result.stdout)["restored_settings"] == [
        "debug/file_logging/enable_file_logging"
    ]


def test_the_engine_added_setting_is_reported(monkeypatch, tmp_path):
    result, _, _ = invoke_write(
        monkeypatch,
        tmp_path,
        ["project", "set", "application/config/name", "--value", "fixture", "--json"],
    )

    data = json.loads(result.stdout)
    assert data["added_settings"] == ["application/config/features"]
    assert data["rewritten_settings"] == []


def test_a_rewritten_setting_is_reported(monkeypatch, tmp_path):
    before = BEFORE.replace(
        'config/name="fixture"',
        'config/name="fixture"\nconfig/features=PackedStringArray("4.5")',
    )
    path = write_project(tmp_path, before)
    fake = ReserializingRunner(
        RunResult(stdout=ENGINE_BANNER + sentinel(SET_RESULT), stderr="", exit_code=0),
        path,
        AFTER,
    )
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app,
        [
            "project",
            "set",
            "application/config/name",
            "--value",
            "fixture",
            "--json",
            "--project",
            str(tmp_path),
        ],
    )

    data = json.loads(result.stdout)
    assert data["rewritten_settings"] == ["application/config/features"]
    assert data["added_settings"] == []


def test_a_reordered_file_is_reported_but_not_reordered_back(monkeypatch, tmp_path):
    # The engine owns the layout: gda says the order changed, it does not fight it.
    result, path, _ = invoke_write(
        monkeypatch,
        tmp_path,
        ["project", "set", "application/config/name", "--value", "fixture", "--json"],
    )

    assert json.loads(result.stdout)["sections_reordered"] is True
    # The file keeps the ENGINE's order, not the one it was written in.
    text = path.read_text(encoding="utf-8")
    assert text.index("[debug]") < text.index("[zsection]")


def test_an_unchanged_section_order_reports_no_reorder(monkeypatch, tmp_path):
    result, _, _ = invoke_write(
        monkeypatch,
        tmp_path,
        ["project", "set", "application/config/name", "--value", "fixture", "--json"],
        after=BEFORE.replace(
            'config/name="fixture"',
            'config/name="fixture"\nconfig/features=PackedStringArray("4.6")',
        ),
    )

    data = json.loads(result.stdout)
    assert data["sections_reordered"] is False
    assert data["restored_settings"] == []


def test_the_addressed_setting_is_never_reported_as_residual(monkeypatch, tmp_path):
    # remove-autoload DROPS the key it addresses: that is the request, not a
    # default-equal line the engine deleted, so it is neither restored nor reported.
    before = BEFORE.replace(
        "[zsection]", '[autoload]\n\nGlobal="*res://global.gd"\n\n[zsection]'
    )
    path = write_project(tmp_path, before)
    fake = ReserializingRunner(
        RunResult(
            stdout=ENGINE_BANNER + sentinel({"name": "Global"}), stderr="", exit_code=0
        ),
        path,
        AFTER,
    )
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app,
        ["project", "remove-autoload", "Global", "--json", "--project", str(tmp_path)],
    )

    data = json.loads(result.stdout)
    assert data["restored_settings"] == ["debug/file_logging/enable_file_logging"]
    assert "autoload/Global" not in data["restored_settings"]
    assert "autoload/Global" not in path.read_text(encoding="utf-8")


def test_the_engine_reported_restore_of_the_addressed_key_rides_through(
    monkeypatch, tmp_path
):
    # A `project set` to the engine's own default is dropped by the save, so the
    # operation forces the line back and names it; the CLI merges that with its own.
    result, _, _ = invoke_write(
        monkeypatch,
        tmp_path,
        [
            "project",
            "set",
            "debug/file_logging/enable_file_logging",
            "--value",
            "false",
            "--json",
        ],
        payload={
            "setting": "debug/file_logging/enable_file_logging",
            "type": "bool",
            "value": False,
            "restored_settings": ["debug/file_logging/enable_file_logging"],
        },
        after=AFTER_FORCED,
    )

    assert json.loads(result.stdout)["restored_settings"] == [
        "debug/file_logging/enable_file_logging"
    ]


def test_every_writer_reports_the_mutation(monkeypatch, tmp_path):
    writers = [
        (
            ["project", "set", "application/config/name", "--value", "fixture"],
            SET_RESULT,
        ),
        (
            ["project", "add-autoload", "Global", "res://global.gd"],
            {"name": "Global", "path": "*res://global.gd"},
        ),
        (["project", "remove-autoload", "Global"], {"name": "Global"}),
        (
            ["project", "add-input-action", "jump", "--key", "J"],
            {
                "name": "jump",
                "deadzone": 0.5,
                "events": [
                    {"kind": "key", "key": "J", "keycode": 74, "physical": False}
                ],
            },
        ),
        (["project", "remove-input-action", "jump"], {"name": "jump"}),
    ]
    for argv, payload in writers:
        result, _, _ = invoke_write(
            monkeypatch, tmp_path, [*argv, "--json"], payload=payload
        )
        data = json.loads(result.stdout)
        assert data["restored_settings"] == [
            "debug/file_logging/enable_file_logging"
        ], argv
        assert data["added_settings"] == ["application/config/features"], argv
        assert data["sections_reordered"] is True, argv


def test_human_output_lines_each_non_empty_category(monkeypatch, tmp_path):
    result, _, _ = invoke_write(
        monkeypatch,
        tmp_path,
        ["project", "set", "application/config/name", "--value", "fixture"],
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == 'set application/config/name (String) = "fixture"'
    assert "engine added: application/config/features" in lines
    assert "gda restored: debug/file_logging/enable_file_logging" in lines
    assert "sections reordered by the engine" in lines
    # A category with nothing in it is not a line.
    assert not [line for line in lines if line.startswith("engine rewrote")]


def test_a_clean_write_renders_only_its_own_line(monkeypatch, tmp_path):
    result, _, _ = invoke_write(
        monkeypatch,
        tmp_path,
        ["project", "set", "application/config/name", "--value", "fixture"],
        after=BEFORE,
    )

    assert result.stdout.strip() == 'set application/config/name (String) = "fixture"'


def test_a_projectless_writer_reports_no_mutation(monkeypatch, tmp_path):
    # Nothing to compare against: the op's own project_not_found is the answer, and
    # the report stays empty rather than guessing.
    fake = FakeRunner(
        RunResult(stdout=ENGINE_BANNER + sentinel(SET_RESULT), stderr="", exit_code=0)
    )
    monkeypatch.setattr("gda.dispatch.make_runner", lambda binary, project=None: fake)

    result = CliRunner().invoke(
        app,
        ["project", "set", "application/config/name", "--value", "fixture", "--json"],
        env={"GDA_PROJECT": ""},
    )

    data = json.loads(result.stdout)
    assert data["added_settings"] == []
    assert data["restored_settings"] == []
    assert data["sections_reordered"] is False


def test_params_json_takes_the_same_path(monkeypatch, tmp_path):
    # ADR-0015: the two input channels are indistinguishable downstream, so the
    # bounded write must ride the descriptor, not the argv body.
    result, path, _ = invoke_write(
        monkeypatch,
        tmp_path,
        [
            "project",
            "set",
            "--params-json",
            json.dumps({"setting": "application/config/name", "value": "fixture"}),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "file_logging/enable_file_logging=false" in path.read_text(encoding="utf-8")
    assert json.loads(result.stdout)["restored_settings"] == [
        "debug/file_logging/enable_file_logging"
    ]


def test_every_writer_publishes_the_four_report_fields():
    for cmd in (
        PROJECT_SET_COMMAND,
        PROJECT_ADD_AUTOLOAD_COMMAND,
        PROJECT_REMOVE_AUTOLOAD_COMMAND,
        PROJECT_ADD_INPUT_ACTION_COMMAND,
        PROJECT_REMOVE_INPUT_ACTION_COMMAND,
    ):
        fields = set(cmd.output_model.model_fields)
        assert {
            "added_settings",
            "rewritten_settings",
            "restored_settings",
            "sections_reordered",
        } <= fields, cmd.operation


def test_every_writer_help_states_the_reserialization():
    for command in (
        "set",
        "add-autoload",
        "remove-autoload",
        "add-input-action",
        "remove-input-action",
    ):
        result = CliRunner().invoke(app, ["project", command, "--help"])
        assert "reserializes" in result.stdout, command
        assert "restores" in result.stdout, command
