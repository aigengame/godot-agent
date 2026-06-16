"""S1 (e2e): export run against the real Godot engine (issue #121).

Unlike every other command, ``export run`` does not route through operations.gd:
the export subsystem is editor-only, so the export is a native ``--export-<mode>``
invocation, and ``gda`` synthesizes the typed result from the subprocess's exit
code + stderr. These tests exercise that REAL native path — the real
``SubprocessExportRunner`` spawning the real Godot with ``--export-release`` /
``--export-pack``, classified by the real ``classify_export_run``.

A successful export needs the export templates for the running engine version
installed. The test machine may not have them, so the happy-path test
**auto-skips** when ``export get`` reports the templates are missing — the same
template-presence policy the read-only export e2e (issue #114) observes, except
this slice actually runs an export. The structured-failure paths that do NOT need
templates (unknown preset, unset path) run unconditionally, and the
missing-templates path itself is asserted only when templates are absent, so the
real native invocation + stderr classification is covered either way.
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
    # A preset whose export_path is empty, with no --output, is export_path_unset —
    # reported before any export runs, so it needs no templates.
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
def test_export_run_real_export(godot_project, tmp_path):
    # The happy path: a real native --export-release against the real engine. This
    # needs the export templates for the running engine version. When they are
    # absent, the real native invocation instead trips the engine's
    # "due to configuration errors" path, which gda classifies as the structured
    # export_templates_missing — so either way the REAL native invocation + stderr
    # classification is exercised end-to-end; only the success assertion is gated.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    output = tmp_path / "game.x86_64"
    run = gda(
        "export", "run", "--preset", "Linux/X11", "--output", str(output), "--json"
    )

    if not _templates_installed(gda):
        # Templates absent: the real export cannot complete. Assert it surfaces as
        # the structured missing-templates failure (the real native path + stderr
        # classification ran), then skip the success assertion cleanly.
        assert run.returncode == 4, run.stdout + run.stderr
        err = json.loads(run.stdout)["error"]
        assert err["code"] == "export_templates_missing", run.stdout + run.stderr
        pytest.skip(
            "export templates for the running engine version are not installed; "
            "skipping the successful-export assertion (the missing-templates "
            "failure path was verified instead)"
        )

    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["preset"] == "Linux/X11"
    assert data["platform"] == "Linux/X11"
    assert data["mode"] == "release"
    assert data["output_path"] == str(output)
    assert isinstance(data["warnings"], list)
    # The artifact was actually written to disk by the real engine.
    assert output.exists()
