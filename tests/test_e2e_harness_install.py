"""S1 (e2e): the installed gda harness loads inert in a real engine (#7, #225, ADR-0018).

Per RULES.md DoD the fast install tests do not count toward this gate: these boot
a REAL Godot on a project with the harness installed and assert the autoload is
valid GDScript and stays inert — no daemon launch marker, so it opens no
connection and the engine boots clean. The exact failure ADR-0018 guards (a
dangling autoload crashing the boot, or the harness opening a connection in a
plain run / shipped build) must NOT occur.

Two boots: a plain ``--path`` run (#7, strengthened by #225), and an EXPORTED PCK
run (#225) — the harness packed into a templateless ``.pck`` and run with no
``gda-daemon`` marker, the shipped-build path ADR-0018 point 2 calls out.
"""

import json
import shutil
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from gda.harness.install import (
    HARNESS_AUTOLOAD_NAME,
    HARNESS_RES_PATH,
    install_harness,
)

from .conftest import project_godot

GODOT = resolve_godot_binary()

# A trivial main scene so a normal (non-`--script`) boot runs the autoload's
# `_ready`; file logging stays disabled via project_godot (issue #180).
MAIN_TSCN = '[gd_scene format=3]\n\n[node name="Main" type="Node"]\n'
PROJECT_GODOT = project_godot(extra='run/main_scene="res://main.tscn"')

# The harness only connects when a `gda-daemon` marker is present in the user args
# (StreamPeerUDS.connect_to_host). An inert boot opens nothing, so none of these
# connection/socket diagnostics may appear in the engine output.
_CONNECTION_NOISE = ("StreamPeerUDS", "connect_to_host", "harness_socket", ".sock")


def _assert_inert_boot(out: str, returncode: int) -> None:
    assert "SCRIPT ERROR" not in out, out
    assert "Parse Error" not in out, out
    # Strengthened (#225): the autoload must not have opened a connection — no
    # daemon marker, so it returns early and touches no socket.
    for needle in _CONNECTION_NOISE:
        assert needle not in out, f"unexpected harness connection activity: {needle}\n{out}"
    assert returncode == 0, out


@pytest.mark.e2e
def test_installed_harness_boots_inert_in_a_real_engine(tmp_path):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    result = install_harness(tmp_path)

    assert result.changed is True
    assert (tmp_path / "addons" / "gda_harness" / "gda_harness.gd").exists()
    text = (tmp_path / "project.godot").read_text(encoding="utf-8")
    assert f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"' in text

    # Boot the real engine. The installed autoload must load (valid GDScript) and
    # stay inert — no `gda-daemon` marker in the args, so it returns early and
    # opens nothing, and the engine boots without a script/parse error.
    proc = subprocess.run(
        [str(GODOT), "--headless", "--path", str(tmp_path), "--quit"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    _assert_inert_boot(proc.stdout + proc.stderr, proc.returncode)


@pytest.mark.e2e
def test_exported_pck_with_harness_runs_inert(tmp_path):
    # #225 / ADR-0018 point 2: the harness installed into a project must stay inert
    # in a SHIPPED build. Pack the project (harness autoload included) into a
    # templateless .pck via `export run --mode pack` (needs no platform templates),
    # then RUN that .pck with no `gda-daemon` marker — the engine loads the packed
    # autoload, which must boot clean and open nothing (the exact crash ADR-0018
    # guards: a dangling/active autoload in an exported game).
    gda = shutil.which("gda")
    assert gda, "the `gda` console script is not on PATH"

    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")
    install_harness(tmp_path)

    # A minimal Linux preset so `export run --mode pack` has a preset to pack from
    # (pack produces project data only; platform is immaterial, no templates used).
    (tmp_path / "export_presets.cfg").write_text(
        "[preset.0]\n\n"
        'name="Pack"\n'
        'platform="Linux/X11"\n'
        "runnable=true\n"
        'export_filter="all_resources"\n'
        'include_filter=""\n'
        'exclude_filter=""\n'
        'export_path="build/game.x86_64"\n\n'
        "[preset.0.options]\n\n"
        "binary_format/embed_pck=false\n",
        encoding="utf-8",
    )
    pck_rel = "dist/game.pck"
    pck = tmp_path / pck_rel
    pck.parent.mkdir(parents=True, exist_ok=True)

    packed = subprocess.run(
        [
            gda, "export", "run", "--preset", "Pack",
            "--mode", "pack", "--output", pck_rel,
            "--project", str(tmp_path), "--godot", str(GODOT), "--json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert packed.returncode == 0, packed.stdout + packed.stderr
    assert json.loads(packed.stdout)["mode"] == "pack"
    assert pck.exists(), f"expected packed .pck at {pck}"

    # Run the engine against the packed .pck (the shipped-build path): the packed
    # GdaHarness autoload must boot inert — no marker, so it opens nothing.
    proc = subprocess.run(
        [str(GODOT), "--headless", "--main-pack", str(pck), "--quit"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    _assert_inert_boot(proc.stdout + proc.stderr, proc.returncode)
