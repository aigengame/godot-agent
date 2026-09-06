"""S3: gda export list / export get success paths against a fake runner (issue #114).

The export command group is read-only discovery: ``export list`` enumerates the
project's export presets (from export_presets.cfg) and ``export get`` reports one
preset's details plus export-template install status. These tests drive the same
proven pipeline as the scene/node/script groups — Typer → binary resolution →
runner → sentinel parse → typed model → JSON — with canned engine output, no
real Godot. This slice never runs an actual export (that is issue #121).
"""

import json

from typer.testing import CliRunner

from gda.cli import app
from gda.runner import RunResult, engine_data_path, set_user_data_root
from tests.support import (
    EXPORT_GET_RESULT as GET_RESULT,
    EXPORT_LIST_RESULT as LIST_RESULT,
    invoke_cli,
    minimal_project,
    recording_runner,
    sentinel,
)


def _host_data_path() -> str | None:
    """The host data directory gda hands the export-get op (#840), as JSON."""
    resolved = engine_data_path()
    return str(resolved) if resolved is not None else None


def test_export_list_json_enumerates_presets_and_exit_zero(monkeypatch, tmp_path):
    # export list enumerates the resolved project's export presets (issue #114):
    # each entry carries its index, name, platform, and runnable flag, read
    # cheaply from export_presets.cfg.
    minimal_project(tmp_path)
    result, fake = invoke_cli(
        monkeypatch,
        ["export", "list", "--project", str(tmp_path), "--json"],
        stdout=sentinel(LIST_RESULT),
        stderr="engine diagnostic\n",
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [p["name"] for p in data["presets"]] == ["Linux/X11", "Web"]
    assert data["presets"][0]["platform"] == "Linux/X11"
    assert data["presets"][0]["runnable"] is True
    assert data["presets"][1]["index"] == 1
    assert data["presets"][1]["runnable"] is False
    # export list takes no operation params: the project is process context.
    assert fake.calls == [("export-list", {})]
    assert "engine diagnostic" in result.stderr


def test_export_list_passes_resolved_project_to_the_runner(monkeypatch, tmp_path):
    # export list reads export_presets.cfg in the resolved project, so --project
    # must reach the runner (which hands it to the engine as --path, issue #32).
    minimal_project(tmp_path)
    projects = recording_runner(
        monkeypatch, RunResult(stdout=sentinel(LIST_RESULT), stderr="", exit_code=0)
    )

    result = CliRunner().invoke(
        app, ["export", "list", "--project", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    assert projects[0] == tmp_path


def test_export_get_json_reports_preset_details_and_template_status(monkeypatch):
    # export get reports a named preset's details plus export-template readiness
    # (issue #114): the preset is addressed by --preset (its display name), and
    # the result carries templates_installed/templates_version so an agent can
    # check readiness before an export run.
    result, fake = invoke_cli(
        monkeypatch,
        ["export", "get", "--preset", "Web", "--json"],
        stdout=sentinel(GET_RESULT),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["name"] == "Web"
    assert data["platform"] == "Web"
    assert data["export_path"] == "build/index.html"
    assert data["templates_installed"] is True
    assert data["templates_version"] == "4.6.3.stable"
    # The preset name rides through as the typed param, beside the host data
    # directory gda resolves for the templates comparison (#840).
    assert fake.calls == [
        ("export-get", {"preset": "Web", "host_data_path": _host_data_path()})
    ]


def test_export_get_missing_preset_flag_is_a_usage_error(monkeypatch):
    # --preset is required: export get always needs a preset to address. Its
    # absence is a usage error (exit 2) that fires before any dispatch.
    result, fake = invoke_cli(
        monkeypatch, ["export", "get", "--json"], stdout=sentinel(GET_RESULT)
    )

    assert result.exit_code == 2
    assert fake.calls == []


def test_export_get_templates_missing_rides_through_false(monkeypatch):
    # When the running engine version's templates are not installed,
    # templates_installed=false rides through to the result so the agent knows it
    # must install templates before an export run.
    payload = {**GET_RESULT, "templates_installed": False, "export_path": ""}
    result, _ = invoke_cli(
        monkeypatch,
        ["export", "get", "--preset", "Web", "--json"],
        stdout=sentinel(payload),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["templates_installed"] is False
    assert data["templates_version"] == "4.6.3.stable"


def test_export_get_reports_the_templates_directory_it_checked(monkeypatch):
    # #840: `templates_installed` alone never said WHERE the engine looked, and a
    # `--user-data-root` redirect MOVES that directory (Godot reads the templates
    # from the same data directory the redirect relocates). `export get` therefore
    # reports `templates_root` — the export-templates directory checked, inside
    # which the `templates_version` directory is looked up — so the hidden case is
    # readable before an export ever runs.
    result, _ = invoke_cli(
        monkeypatch,
        ["export", "get", "--preset", "Web", "--json"],
        stdout=sentinel(GET_RESULT),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["templates_root"] == "/host/data/Godot/export_templates"
    # Nothing is hidden on an unredirected run, so the host key is null rather
    # than a repeat of the directory that was checked.
    assert data["templates_root_host"] is None


def test_export_get_reports_the_host_templates_a_redirect_hides(monkeypatch):
    # The interaction #840 is about, made readable one command earlier than the
    # export: under a redirect the checked directory has no templates while the
    # host's standard one does, and `templates_root_host` names the second. The
    # two directories together are what tells "not installed anywhere" from
    # "installed, but out of this run's sight".
    payload = {
        **GET_RESULT,
        "templates_installed": False,
        "templates_root": "/iso/Library/Application Support/Godot/export_templates",
        "templates_root_host": "/home/dev/Library/Application Support/Godot/export_templates",
    }
    result, _ = invoke_cli(
        monkeypatch,
        ["export", "get", "--preset", "Web", "--json"],
        stdout=sentinel(payload),
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["templates_installed"] is False
    assert data["templates_root"] == (
        "/iso/Library/Application Support/Godot/export_templates"
    )
    assert data["templates_root_host"] == (
        "/home/dev/Library/Application Support/Godot/export_templates"
    )


def test_export_get_human_render_names_the_checked_and_hidden_directories(monkeypatch):
    # The human channel says the same thing as the JSON one: which directory was
    # checked, and — when a redirect hid them — where the templates really are.
    payload = {
        **GET_RESULT,
        "templates_installed": False,
        "templates_root": "/iso/data/Godot/export_templates",
        "templates_root_host": "/home/dev/data/Godot/export_templates",
    }
    result, _ = invoke_cli(
        monkeypatch,
        ["export", "get", "--preset", "Web"],
        stdout=sentinel(payload),
    )

    assert result.exit_code == 0
    assert "/iso/data/Godot/export_templates" in result.stdout
    assert "/home/dev/data/Godot/export_templates" in result.stdout


def test_export_get_hands_the_operation_the_host_data_path(monkeypatch, tmp_path):
    # MECHANISM (#840). The templates check runs ENGINE-side against
    # `OS.get_data_dir()`, so a redirected engine cannot see the host's directory,
    # and the templates layout rule (the `godot`/`Godot` directory name, the
    # version directory without a `.0` patch) lives only in operations.gd. gda
    # therefore resolves the HOST data directory over its OWN environment — which
    # `--user-data-root` never touches, it redirects the CHILD's — and passes it as
    # an op param, so the layout rule stays where it is and no CLI-side copy of it
    # appears. The redirect must NOT change what gda passes: that value IS the
    # thing being compared against.
    try:
        result, fake = invoke_cli(
            monkeypatch,
            [
                "--user-data-root",
                str(tmp_path / "iso"),
                "export",
                "get",
                "--preset",
                "Web",
                "--json",
            ],
            stdout=sentinel(GET_RESULT),
        )
    finally:
        # The root option is process-wide config (gda.runner), so a CLI invocation
        # that sets it must not leak into the next test.
        set_user_data_root(None)

    assert result.exit_code == 0
    assert fake.calls == [
        ("export-get", {"preset": "Web", "host_data_path": _host_data_path()})
    ]


def test_the_host_data_path_reaches_the_operation_through_params_json(monkeypatch):
    # ADR-0015: argv and `--params-json` build the SAME params model, so the host
    # data path cannot be something an argv command body pastes in — it is a
    # DEFAULT of the model, and a JSON caller that names only `preset` gets it too.
    result, fake = invoke_cli(
        monkeypatch,
        ["export", "get", "--params-json", '{"preset": "Web"}', "--json"],
        stdout=sentinel(GET_RESULT),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [
        ("export-get", {"preset": "Web", "host_data_path": _host_data_path()})
    ]
