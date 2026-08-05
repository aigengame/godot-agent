"""Regression guard for GameLog's print() fallback under a dormant harness.

This project COMMITS the gda harness, so ``/root/GdaHarness`` is present in EVERY
run — but its ``gda_log()`` only emits when gda-daemon launched the run and is a
silent no-op otherwise. So the exact regression surface is: harness PRESENT (it is
committed) but NOT daemon-launched (a plain ``godot --headless --path`` run) —
``GameLog.emit`` must fall back to ``print()`` rather than routing to the dormant
harness and silently dropping the record. That plain-run path went dark once the
harness was committed and is fixed in ``addons/game_log/game_log.gd``; this locks it down.

The daemon-launched *rich* path (``origin == "gda_log"`` via ``gda logger tail``)
is covered by ``test_player_e2e.py`` — the complementary half. Engine tier (a real
``godot``, no daemon); never ``e2e``. gda-side issue #362 delivered the public
``is_daemon_launched()`` predicate, which ``GameLog`` now gates on (no private flag).
"""

from __future__ import annotations

import subprocess

import pytest

from gda.binary import resolve_godot_binary

import build_config

GAME_DIR = build_config.GAME_DIR


@pytest.mark.engine
def test_plain_run_prints_logs_despite_committed_dormant_harness() -> None:
    """A plain headless run prints the boot records instead of swallowing them.

    Precondition: the harness is committed (present in ``project.godot``), so this
    exercises the present-but-dormant path — not the harness-absent path — which is
    the one that regressed. A plain ``godot --headless --path`` run is NOT
    daemon-launched, so ``GameLog`` must ``print()`` the records (no rich
    ``<<<GDA:LOG>>>`` marker, which only a daemon-launched harness emits).
    """
    project_godot = (GAME_DIR / "project.godot").read_text(encoding="utf-8")
    assert "GdaHarness" in project_godot, (
        "expected the COMMITTED harness autoload — this test guards the "
        "present-but-dormant fallback path"
    )

    build_config.build_all()  # ensure every derived .tres reflects the current JSON
    godot = resolve_godot_binary()
    result = subprocess.run(
        [str(godot), "--headless", "--path", str(GAME_DIR), "--quit-after", "30"],
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr

    # The dormant harness's gda_log() is a no-op, so GameLog fell back to print():
    # the boot records (emitted from _ready, deterministic) appear on stdout.
    assert "[info] player_ready" in result.stdout, combined
    assert "[info] boot" in result.stdout, combined
    assert "[info] game_shell_ready" in result.stdout, combined
    # As PLAIN print lines — never the rich daemon marker (dormant harness = no IPC).
    assert "<<<GDA:LOG>>>" not in result.stdout, combined
    # And the boot itself stayed clean.
    assert "SCRIPT ERROR" not in combined, combined
    assert "Parse Error" not in combined, combined
