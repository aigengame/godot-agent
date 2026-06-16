"""S1 (e2e): export run against the real Godot engine (issue #121).

Unlike every other command, ``export run`` does not route through operations.gd:
the export subsystem is editor-only, so the export is a native ``--export-release``
invocation, and ``gda`` synthesizes the typed result from the subprocess's exit
code (#121 fixes the mode to release; --mode/--output are deferred to #170). These
tests exercise that REAL path — the real ``SubprocessExportRunner`` spawning the
real Godot, classified by the real ``classify_export_run`` — plus the real
``export get`` structured template-readiness preflight.

The acceptance behavior is exporting to the preset's **configured** ``export_path``
(no ``--output``). A successful export needs the export templates for the running
engine version installed; the test machine may not have them, so the configured-
path happy-path test **auto-skips** when ``export get`` reports the templates are
missing — the same template-presence policy the read-only export e2e (issue #114)
observes. Crucially, missing templates are now caught by gda's STRUCTURED preflight
(export get's ``templates_installed``) *before* any native run, so when templates
are absent this test asserts the structured ``export_templates_missing`` path live
and then skips only the success assertion. The structured-failure paths that need
no templates (unknown preset, unset path) run unconditionally.
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary

GODOT = resolve_godot_binary()

# A runnable Linux preset writing to build/game.x86_64, plus a non-runnable
# preset with NO export_path (to exercise export_path_unset). Sibling `.options`
# sections are filtered out by export get, exactly as in the read-only e2e.
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

name="NoPath"
platform="Linux/X11"
runnable=false
custom_features=""
export_filter="all_resources"
export_path=""

[preset.1.options]

binary_format/embed_pck=false
"""


def _gda_project(project) -> "callable":
    """A ``gda`` bound to ``--godot`` + ``--project`` for the real engine."""
    gda_bin = shutil.which("gda")
    assert gda_bin, "the `gda` console script is not on PATH"

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [gda_bin, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


def _templates_installed(gda) -> bool:
    """Ask the real engine (via export get) whether templates are installed."""
    got = gda("export", "get", "--preset", "Linux/X11", "--json")
    assert got.returncode == 0, got.stdout + got.stderr
    return json.loads(got.stdout)["templates_installed"]


@pytest.mark.e2e
def test_export_run_unknown_preset_reuses_export_get_error(godot_project):
    # export run resolves the preset via export get first, so an unknown preset is
    # export-get's clean export_preset_not_found — surfaced before any export. This
    # runs regardless of template presence (no export is attempted).
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    run = gda("export", "run", "--preset", "Nope", "--json")

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "export_preset_not_found"
    assert "Nope" in err["message"]


@pytest.mark.e2e
def test_export_run_unset_path_yields_export_path_unset(godot_project):
    # A preset whose configured export_path is empty is export_path_unset —
    # reported before any export runs, so it needs no templates (--output, which
    # could have supplied a path, is deferred to #170).
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    run = gda("export", "run", "--preset", "NoPath", "--json")

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "export_path_unset"
    assert err["category"] == "operation"


@pytest.mark.e2e
def test_export_run_writes_to_configured_export_path(godot_project):
    # PRIMARY acceptance behavior (#121): `gda export run --preset NAME` (no
    # --output) exports to the preset's CONFIGURED export_path. The preset writes
    # to res://build/game.x86_64, so the artifact lands at <project>/build/... and
    # the reported output_path is the configured string verbatim.
    #
    # The configured parent directory is created first (a real export writes the
    # binary there). When templates are absent the real export cannot complete —
    # but gda now catches that via its STRUCTURED preflight (export get's
    # templates_installed) BEFORE any native run, so we assert the structured
    # export_templates_missing failure live and then skip only the success
    # assertion, consistent with the e2e template-presence policy.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    configured_rel = "build/game.x86_64"
    artifact = godot_project / configured_rel
    artifact.parent.mkdir(parents=True, exist_ok=True)  # the preset's configured dir
    gda = _gda_project(godot_project)

    run = gda("export", "run", "--preset", "Linux/X11", "--json")

    if not _templates_installed(gda):
        # Templates absent: gda's structured preflight fails fast with
        # export_templates_missing, before any native export — so no artifact is
        # written. Verify that path live, then skip the success assertion cleanly.
        assert run.returncode == 4, run.stdout + run.stderr
        err = json.loads(run.stdout)["error"]
        assert err["code"] == "export_templates_missing", run.stdout + run.stderr
        assert not artifact.exists(), "no artifact when the preflight fails fast"
        pytest.skip(
            "export templates for the running engine version are not installed; "
            "skipping the successful-export assertion (the structured "
            "export_templates_missing preflight was verified instead)"
        )

    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["preset"] == "Linux/X11"
    assert data["platform"] == "Linux/X11"
    assert data["mode"] == "release"
    # (b) The reported output_path equals the preset's configured export_path.
    assert data["output_path"] == configured_rel
    assert isinstance(data["warnings"], list)
    # (a) The artifact was actually written to the configured path on disk.
    assert artifact.exists(), f"expected artifact at configured path {artifact}"
