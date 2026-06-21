"""S1 (e2e): the installed gda harness loads inert in a real engine (#7, ADR-0018).

Per RULES.md DoD the fast install tests do not count toward this gate: this boots
a REAL Godot on a project with the harness installed and asserts the autoload is
valid GDScript and stays inert — no daemon launch marker, so it opens nothing and
the engine boots clean. The daemon<->harness connection itself is a later slice.
"""

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


@pytest.mark.e2e
def test_installed_harness_boots_inert_in_a_real_engine(tmp_path):
    (tmp_path / "project.godot").write_text(PROJECT_GODOT, encoding="utf-8")
    (tmp_path / "main.tscn").write_text(MAIN_TSCN, encoding="utf-8")

    changed = install_harness(tmp_path)

    assert changed is True
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
    out = proc.stdout + proc.stderr
    assert "SCRIPT ERROR" not in out, out
    assert "Parse Error" not in out, out
    assert proc.returncode == 0, out
