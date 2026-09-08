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

import pytest

from tests.support import Gda, templates_installed

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
    v = Gda().json("info")
    base = f"{v['major']}.{v['minor']}"
    if v["patch"]:
        base += f".{v['patch']}"
    return f"{base}.{v['status']}"


@pytest.mark.e2e
def test_export_list_enumerates_presets_from_export_presets_cfg(godot_project):
    # export list parses export_presets.cfg and reports each preset's index, name,
    # platform, and runnable flag — filtering out the `.options` sub-sections. The
    # listing IS the structured-level verification of the project's export config.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = Gda(godot_project)

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
    gda = Gda(godot_project)

    listed = gda("export", "list", "--json")

    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert json.loads(listed.stdout)["presets"] == []


@pytest.mark.e2e
def test_export_list_no_cfg_yields_export_presets_not_found(godot_project):
    # A project that has never configured an export has no export_presets.cfg:
    # export list refuses with the structured export_presets_not_found code rather
    # than a misleading empty listing, so an agent knows the project defines no
    # presets.
    gda = Gda(godot_project)

    err = gda.error("export", "list", "--json", code="export_presets_not_found")
    assert "export_presets.cfg" in err["message"]


@pytest.mark.e2e
def test_export_list_without_project_yields_project_not_found(tmp_path):
    # export list reads export_presets.cfg in a project, so it cannot run
    # projectless: run from a non-project directory with no --project, it refuses
    # with project_not_found rather than returning a misleading empty listing.
    err = Gda().error(
        "export", "list", "--json", cwd=tmp_path, code="project_not_found"
    )
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
    gda = Gda(godot_project)

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
    # #840: and WHERE it checked — the export-templates directory holding that
    # version directory, derived engine-side from OS.get_data_dir(). An absolute
    # path ending in `export_templates`, whatever this host's data directory is.
    templates_root = data["templates_root"]
    assert templates_root.startswith("/") or ":" in templates_root, templates_root
    assert templates_root.endswith("export_templates"), templates_root
    # No redirect is in play here, so the host directory IS the one checked and
    # there is nothing hidden to report.
    assert data["templates_root_host"] is None, data["templates_root_host"]


@pytest.mark.e2e
def test_export_get_names_the_host_templates_a_user_data_redirect_hides(
    godot_project, tmp_path
):
    # #840 END TO END, one command before the export. `--user-data-root` relocates
    # Godot's data directory, and Godot reads the export templates from exactly
    # that directory, so a redirected run sees none even when the host has them
    # installed. `export get` now reports BOTH directories: the redirected one it
    # checked, and the host's, which is where the templates it cannot see are.
    #
    # The redirect is passed PER INVOCATION, never exported for the run: exporting
    # it hides the host's templates from every other test too (PITFALLS.md).
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = Gda(godot_project)
    if not templates_installed(gda, preset="Web"):
        pytest.skip(
            "this host has no export templates installed, so there is nothing for "
            "a --user-data-root redirect to hide"
        )
    isolated = tmp_path / "iso"

    data = gda.json(
        "--user-data-root", str(isolated), "export", "get", "--preset", "Web"
    )

    assert data["templates_installed"] is False, data
    # The directory checked moved under the isolated root; the host's did not.
    assert str(isolated) in data["templates_root"], data["templates_root"]
    assert data["templates_root_host"], data
    assert str(isolated) not in data["templates_root_host"], data
    assert data["templates_root_host"].endswith("export_templates"), data


@pytest.mark.e2e
def test_export_get_reports_export_path_of_a_preset_with_one(godot_project):
    # A preset with an export_path reports it verbatim (the Linux preset writes to
    # build/game.x86_64), so an agent learns where an export would land.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = Gda(godot_project)

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
    gda = Gda(godot_project)

    err = gda.error(
        "export", "get", "--preset", "Nope", "--json", code="export_preset_not_found"
    )
    assert "Nope" in err["message"]


@pytest.mark.e2e
def test_export_get_no_cfg_yields_export_presets_not_found(godot_project):
    # export get over a project with no export_presets.cfg reports the same
    # export_presets_not_found mode as export list — there is nothing to address.
    gda = Gda(godot_project)

    err = gda.error(
        "export", "get", "--preset", "Web", "--json", code="export_presets_not_found"
    )
    assert "export_presets.cfg" in err["message"]
