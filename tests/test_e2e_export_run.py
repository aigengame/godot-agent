"""S1 (e2e): export run against the real Godot engine (issue #121).

Unlike every other command, ``export run`` does not route through operations.gd:
the export subsystem is editor-only, so the export is a native ``--export-release``
invocation, and ``gda`` synthesizes the typed result from the subprocess's exit
code (#121 fixes the mode to release; --mode/--output are deferred to #170). These
tests exercise that REAL path — the real ``SubprocessExportRunner`` spawning the
real Godot, classified by the real ``classify_export_run`` — plus the real
``export get`` structured template-readiness preflight.

The acceptance behavior is exporting to the preset's **configured** ``export_path``
(no ``--output``). A successful *release* export needs the export templates for the
running engine version installed; the test machine may not have them, so the
configured-path release happy-path test **auto-skips** when ``export get`` reports
the templates are missing — the same template-presence policy the read-only export
e2e (issue #114) observes. Crucially, missing templates are caught by gda's
STRUCTURED preflight (export get's ``templates_installed``) *before* any native run,
so when templates are absent that release test asserts the structured
``export_templates_missing`` path live and then skips only the success assertion.

``--mode pack`` is different (#170): Godot's native ``--export-pack`` produces
project data only (a PCK/ZIP) and needs **no** platform export templates, so the
pack test must RUN — not skip — on a template-less machine: it asserts exit 0 and
the ``.pck`` on disk, giving the on-disk verification a release export cannot give
here. The structured-failure paths that need no templates (unknown preset, unset
path) run unconditionally.
"""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary
from gda.harness.install import (
    HARNESS_AUTOLOAD_NAME,
    HARNESS_FILE,
    HARNESS_RES_DIR,
    install_harness,
)
from tests.support import GDA_CMD, templates_installed

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
include_filter=""
exclude_filter=""
export_path="build/game.x86_64"

[preset.0.options]

binary_format/embed_pck=false

[preset.1]

name="NoPath"
platform="Linux/X11"
runnable=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path=""

[preset.1.options]

binary_format/embed_pck=false
"""


def _gda_project(project):
    """A ``gda`` bound to ``--godot`` + ``--project`` for the real engine."""

    def gda(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*GDA_CMD, *args, "--godot", str(GODOT), "--project", str(project)],
            capture_output=True,
            text=True,
        )

    return gda


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
    # all_resources needs at least one exportable file, or the native export fails with
    # "Must select at least one file to export." This success branch only runs where
    # templates exist (CI now installs them, #301), so — like the pack tests below — it
    # must carry pack content; a bare project.godot alone would fail the real export.
    (godot_project / "main.gd").write_text(
        "extends Node\n\nfunc _ready() -> void:\n\tpass\n", encoding="utf-8"
    )
    configured_rel = "build/game.x86_64"
    artifact = godot_project / configured_rel
    artifact.parent.mkdir(parents=True, exist_ok=True)  # the preset's configured dir
    gda = _gda_project(godot_project)

    run = gda("export", "run", "--preset", "Linux/X11", "--json")

    if not templates_installed(gda):
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


@pytest.mark.e2e
def test_export_run_pack_writes_pck_without_templates(godot_project):
    # #170 PROOF: `--mode pack --output <path>.pck` runs Godot's native
    # --export-pack to the OVERRIDDEN path (not the preset's configured
    # build/game.x86_64) and writes a .pck — WITHOUT installed export templates.
    # pack produces project data only, so unlike release/debug it needs no platform
    # templates and gda's preflight must NOT block it. This test therefore does NOT
    # skip on a template-less machine: it asserts exit 0 and the artifact on disk,
    # the on-disk verification a release export cannot give here. (If this machine
    # DOES have templates, the same assertions hold.)
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    # all_resources packs every res:// resource, so the project needs at least one
    # exportable file — a bare project.godot alone yields Godot's "Must select at
    # least one file to export." A trivial script suffices as pack content.
    (godot_project / "main.gd").write_text(
        "extends Node\n\nfunc _ready() -> void:\n\tpass\n", encoding="utf-8"
    )
    override_rel = "dist/packed.pck"
    artifact = godot_project / override_rel
    artifact.parent.mkdir(parents=True, exist_ok=True)
    configured = godot_project / "build/game.x86_64"
    gda = _gda_project(godot_project)

    run = gda(
        "export",
        "run",
        "--preset",
        "Linux/X11",
        "--mode",
        "pack",
        "--output",
        override_rel,
        "--json",
    )

    # No skip: pack must RUN to completion regardless of template presence.
    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads(run.stdout)
    assert data["mode"] == "pack"
    # The reported output_path is the override, and the .pck lands there on disk —
    # NOT at the preset's configured export_path.
    assert data["output_path"] == override_rel
    assert artifact.exists(), f"expected .pck at the override path {artifact}"
    assert not configured.exists(), "the override must not write the configured path"


@pytest.mark.e2e
def test_export_run_pack_omits_installed_harness_and_restores_it(godot_project):
    # ADR-0018: `gda export run` must NEVER carry the dev-only harness into the
    # artifact — and without the developer having to `gda daemon uninstall` first.
    # With the harness INSTALLED, a pack export to a .zip (so we can list it) must
    # contain NO gda_harness.gd, and the dev project must be left UNTOUCHED (the
    # harness file + autoload entry restored). Pack needs no templates, so this runs
    # on a template-less machine and gives real on-disk verification.
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    # Pack content unrelated to the harness, so the archive is non-empty even after
    # the harness is stripped (a bare project alone yields Godot's "select one file").
    (godot_project / "main.gd").write_text(
        "extends Node\n\nfunc _ready() -> void:\n\tpass\n", encoding="utf-8"
    )
    install_harness(godot_project)
    harness_file = godot_project / HARNESS_RES_DIR / HARNESS_FILE
    project_godot = godot_project / "project.godot"
    assert harness_file.exists(), "precondition: harness installed on disk"
    assert HARNESS_AUTOLOAD_NAME in project_godot.read_text(encoding="utf-8")

    override_rel = "dist/packed.zip"
    artifact = godot_project / override_rel
    artifact.parent.mkdir(parents=True, exist_ok=True)
    gda = _gda_project(godot_project)

    run = gda(
        "export",
        "run",
        "--preset",
        "Linux/X11",
        "--mode",
        "pack",
        "--output",
        override_rel,
        "--json",
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert artifact.exists(), f"expected .zip at the override path {artifact}"
    with zipfile.ZipFile(artifact) as zf:
        names = zf.namelist()
        # (a) The harness SCRIPT is absent from the archive.
        assert not any(HARNESS_FILE in n for n in names), (
            "the exported archive still carries the harness script:\n"
            + "\n".join(names)
        )
        # (b) The packed project settings declare NO GdaHarness autoload — the
        # specific Godot risk (project.binary serializes ProjectSettings wholesale,
        # ADR-0028), so checking the file's absence alone is not enough.
        binary_entry = next(n for n in names if n.endswith("project.binary"))
        assert HARNESS_AUTOLOAD_NAME.encode() not in zf.read(binary_entry), (
            "packed project.binary still declares the GdaHarness autoload"
        )
    # The dev project is left UNTOUCHED: harness restored on disk and in config.
    assert harness_file.exists(), "the harness file must be restored after export"
    assert HARNESS_AUTOLOAD_NAME in project_godot.read_text(encoding="utf-8")


@pytest.mark.e2e
@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="forces missing templates by pointing XDG_DATA_HOME at an empty dir, which "
    "only the Linux/BSD engine honors as its data dir (macOS uses ~/Library/"
    "Application Support); this restores the Linux CI coverage lost once CI installs "
    "templates",
)
def test_export_run_without_templates_yields_export_templates_missing(
    godot_project, tmp_path
):
    # Restores the LIVE (real-engine) coverage of the export_templates_missing
    # structured preflight that installing export templates into CI removed: once CI
    # has templates, test_export_run_writes_to_configured_export_path takes its success
    # branch and its missing branch goes dead, leaving that error path on faked unit
    # tests only (which RULES.md DoD says can pass while the artifact is broken). Here
    # we point the engine's data dir (XDG_DATA_HOME) at an EMPTY dir so it finds NO
    # export templates, then assert `gda export run` fails fast with the structured
    # export_templates_missing code BEFORE any native export (#304).
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    (godot_project / "main.gd").write_text(
        "extends Node\n\nfunc _ready() -> void:\n\tpass\n", encoding="utf-8"
    )
    empty_data = tmp_path / "empty-xdg"
    empty_data.mkdir()

    run = subprocess.run(
        [
            *GDA_CMD,
            "export",
            "run",
            "--preset",
            "Linux/X11",
            "--json",
            "--godot",
            str(GODOT),
            "--project",
            str(godot_project),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "XDG_DATA_HOME": str(empty_data)},
    )

    assert run.returncode == 4, run.stdout + run.stderr
    err = json.loads(run.stdout)["error"]
    assert err["code"] == "export_templates_missing", run.stdout + run.stderr
    assert err["category"] == "operation"
    # Fail-fast preflight: no native export ran, so nothing was written.
    assert not (godot_project / "build").exists(), "no artifact when preflight fails"


def _host_templates_on_disk() -> bool:
    """Whether the running platform's export templates are PHYSICALLY present in the
    engine's real user data dir — computed INDEPENDENTLY of gda's own path logic (the
    code #304 fixed), by globbing for a platform template file under ANY version dir.
    A detection regression (Linux ``godot`` vs ``Godot`` case, or a ``.0`` version-dir
    name) shows up as disagreement between this and ``gda export get``.
    """
    home = Path(os.path.expanduser("~"))
    if sys.platform == "darwin":
        root = home / "Library" / "Application Support" / "Godot" / "export_templates"
        return any(root.glob("*/macos.zip"))
    if sys.platform.startswith("linux"):
        data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        root = data / "godot" / "export_templates"
        return any(root.glob("*/linux_release.x86_64")) or any(
            root.glob("*/linux_debug.x86_64")
        )
    return False


@pytest.mark.e2e
def test_templates_installed_is_true_when_host_templates_are_on_disk(godot_project):
    # #304 acceptance, as a HARD assertion: wherever the host's export templates are
    # physically installed (the CI install-godot step, or a dev who installed them),
    # `gda export get` MUST report templates_installed=true. This converts a
    # template-path detection regression — the Linux user-dir case or the .0
    # version-dir name — from a SILENT skip of the #301 proof into a RED failure (the
    # very gap that hid the original #304 bug). It skips only where templates are
    # genuinely absent (a dev box without them); CI always has them.
    if not _host_templates_on_disk():
        pytest.skip(
            "no host export templates on disk (a dev box without them); the CI "
            "install-godot step provides them, where this assertion guards the "
            "template-installed path"
        )
    (godot_project / "export_presets.cfg").write_text(
        EXPORT_PRESETS_CFG, encoding="utf-8"
    )
    gda = _gda_project(godot_project)

    # templates_installed is preset-independent (it only checks the version dir
    # exists), so any real preset works; the on-disk check above is the source of truth.
    assert templates_installed(gda) is True, (
        "host export templates are present on disk but `gda export get` reports "
        "templates_installed=false — the template-path detection regressed (#304)"
    )
