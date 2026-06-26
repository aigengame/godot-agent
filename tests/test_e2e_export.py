"""S1 (e2e): export discovery against the real Godot engine (issue #114).

The export-group tracer: ``gda export list`` parses the project's
export_presets.cfg and enumerates its presets (name, platform, runnable);
``gda export get`` reports one named preset's details plus export-template
install status — the readiness check before a future ``export run`` (issue #121).

This slice is READ-ONLY: it parses a config file and checks the filesystem, it
never runs an actual export, so it needs no installed export templates to pass.
The template-install status is reported as-is (whatever the test machine has),
so these tests assert its SHAPE (a bool, plus the running engine's version dir),
not a fixed value.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

# Two presets in the canonical format Godot writes export_presets.cfg: a
# runnable Linux preset and a non-runnable Web preset, each with its sibling
# `.options` sub-section (which export list/get must filter out — only the bare
# `preset.N` sections are presets).
EXPORT_PRESETS_CFG = """\
[preset.0]

name="Linux/X11"
platform="Linux/X11"
runnable=true
custom_features=""
export_filter="all_resources"
export_path="build/game.x86_64"

[preset.0.options]

binary_format/embed_pck=false

[preset.1]

name="Web"
platform="Web"
runnable=false
custom_features=""
export_filter="all_resources"
export_path=""

[preset.1.options]

html/export_icon=true
"""


def _expected_templates_version() -> str:
    """The export-templates version-dir name the running engine uses, derived from its
    OWN version info — major.minor[.patch].status with the patch OMITTED when 0 (e.g.
    "4.6.stable" for 4.6.0, "4.6.3.stable" for 4.6.3), exactly as engine.cpp formats
    its version string. Asserting ``templates_version`` against THIS (not a loose
    regex) makes a regression in operations.gd::_export_templates_version_dir — e.g.
    re-adding the ``.0`` patch — fail RED here, instead of silently making the
    template-gate e2e skip (templates_installed would go False on a .0 engine).
    """
    info = subprocess.run(
        [*GDA_CMD, "info", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
    )
    assert info.returncode == 0, info.stdout + info.stderr
    v = json.loads(info.stdout)
    base = f"{v['major']}.{v['minor']}"
    if v["patch"]:
        base += f".{v['patch']}"
    return f"{base}.{v['status']}"


def _gda_project(project) -> "callable":
    """A ``gda`` bound to ``--project`` for res:// resolution of the cfg."""

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


def _assert_operation_error(proc: subprocess.CompletedProcess, code: str) -> dict:
    assert proc.returncode == 4, proc.stdout + proc.stderr
    err = json.loads(proc.stdout)["error"]
    assert err["category"] == "operation"
    assert err["code"] == code
    return err


@pytest.mark.e2e
def test_export_list_enumerates_presets_from_export_presets_cfg(godot_project):
    # export list parses export_presets.cfg and reports each preset's index, name,
    # platform, and runnable flag — filtering out the `.options` sub-sections. The
    # listing IS the structured-level verification of the project's export config.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    listed = gda("export", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    presets = json.loads(listed.stdout)["presets"]
    by_name = {p["name"]: p for p in presets}
    assert set(by_name) == {"Linux/X11", "Web"}
    assert by_name["Linux/X11"]["index"] == 0
    assert by_name["Linux/X11"]["platform"] == "Linux/X11"
    assert by_name["Linux/X11"]["runnable"] is True
    assert by_name["Web"]["index"] == 1
    assert by_name["Web"]["runnable"] is False


@pytest.mark.e2e
def test_export_list_empty_cfg_is_an_empty_listing(godot_project):
    # An export_presets.cfg that defines no presets is a valid, empty listing —
    # not an error (distinct from no cfg at all).
    (godot_project / "export_presets.cfg").write_text("", encoding="utf-8")
    gda = _gda_project(godot_project)

    listed = gda("export", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert json.loads(listed.stdout)["presets"] == []


@pytest.mark.e2e
def test_export_list_no_cfg_yields_export_presets_not_found(godot_project):
    # A project that has never configured an export has no export_presets.cfg:
    # export list refuses with the structured export_presets_not_found code rather
    # than a misleading empty listing, so an agent knows the project defines no
    # presets.
    gda = _gda_project(godot_project)

    listed = gda("export", "list", "--json")

    err = _assert_operation_error(listed, "export_presets_not_found")
    assert "export_presets.cfg" in err["message"]


@pytest.mark.e2e
def test_export_list_without_project_yields_project_not_found(tmp_path):
    # export list reads export_presets.cfg in a project, so it cannot run
    # projectless: run from a non-project directory with no --project, it refuses
    # with project_not_found rather than returning a misleading empty listing.
    listed = subprocess.run(
        [*GDA_CMD, "export", "list", "--json", "--godot", str(GODOT)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    err = _assert_operation_error(listed, "project_not_found")
    assert "--project" in err["message"]


@pytest.mark.e2e
def test_export_get_reports_preset_details_and_template_status(godot_project):
    # export get reports one named preset's details plus export-template install
    # status. The preset's own fields come from export_presets.cfg; the template
    # status reflects the test machine as-is, so we assert its SHAPE: a bool, plus
    # the running engine's version directory (major.minor.patch.status).
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    got = gda("export", "get", "--preset", "Web", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert data["index"] == 1
    assert data["name"] == "Web"
    assert data["platform"] == "Web"
    assert data["runnable"] is False
    assert data["export_path"] == ""
    # Template readiness: a bool verdict plus the EXACT version dir it checked —
    # derived from the engine's own version (patch omitted for a .0 release), so a
    # format regression is caught RED here rather than slipping past a loose regex.
    assert isinstance(data["templates_installed"], bool)
    assert data["templates_version"] == _expected_templates_version(), data[
        "templates_version"
    ]


@pytest.mark.e2e
def test_export_get_reports_export_path_of_a_preset_with_one(godot_project):
    # A preset with an export_path reports it verbatim (the Linux preset writes to
    # build/game.x86_64), so an agent learns where an export would land.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    got = gda("export", "get", "--preset", "Linux/X11", "--json")

    assert got.returncode == 0, got.stdout + got.stderr
    data = json.loads(got.stdout)
    assert data["runnable"] is True
    assert data["export_path"] == "build/game.x86_64"


@pytest.mark.e2e
def test_export_get_unknown_preset_yields_export_preset_not_found(godot_project):
    # A preset name not present in export_presets.cfg is the structured
    # export_preset_not_found code, naming the requested preset, so an agent can
    # re-list to find the real names rather than parse prose.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    got = gda("export", "get", "--preset", "Nope", "--json")

    err = _assert_operation_error(got, "export_preset_not_found")
    assert "Nope" in err["message"]


@pytest.mark.e2e
def test_export_get_no_cfg_yields_export_presets_not_found(godot_project):
    # export get over a project with no export_presets.cfg reports the same
    # export_presets_not_found mode as export list — there is nothing to address.
    gda = _gda_project(godot_project)

    got = gda("export", "get", "--preset", "Web", "--json")

    err = _assert_operation_error(got, "export_presets_not_found")
    assert "export_presets.cfg" in err["message"]
