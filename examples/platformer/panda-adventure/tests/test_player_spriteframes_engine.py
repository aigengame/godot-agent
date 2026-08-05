"""Engine proof — the committed Player SpriteFrames really loads in Godot (P2-S5, #443).

The fast tier ``test_assets_lifecycle.py`` pins the multi-animation deriver's TEXT
(``derive_spriteframes_set``: ext_resources, per-state regions, loop flags,
determinism); it cannot prove the emitted ``.tres`` is a *valid Godot resource*.
This engine-tier test closes that gap for the SHIPPED artifact
(``assets/sprites/player.tres``, derived from the per-state sheets and committed): it
loads the resource in a headless Godot ``SceneTree`` and asserts every animation
state is present with a nonempty frame set of ``AtlasTexture`` frames, and that the
locomotion states loop while the verb one-shots do not — the animation contract the
PlayerAnimator drives. The committed project is imported by the conftest autouse
fixture, so the sheet textures the ``AtlasTexture`` sub-resources reference resolve
on load (#439).

Asserts STRUCTURE (state set, nonempty frames, loop semantics), never exact frame
counts — those are placeholder-art detail that wave-close acquisition replaces; the
state set and loop semantics are the stable derivation contract.

``engine`` marker: fails loudly without a Godot binary (conftest), deselected in the
fast CI tier and run in the ``godot-e2e`` job / locally.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary

import build_config

GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

# The animation states the Player set ships, and which loop (locomotion base states)
# vs. play once (verb one-shots) — the contract the PlayerAnimator relies on.
_LOOPING = ("idle", "run", "jump")
_ONESHOT = ("fire", "hurt", "consume", "level_up", "death")

# A headless SceneTree script: load the committed SpriteFrames and print, as JSON, its
# animation names, per-state frame counts, per-state loop flags, and whether idle's
# frame 0 is an AtlasTexture — so the test can assert on stdout.
_PROBE = """extends SceneTree
func _initialize() -> void:
	var sf = load("res://content/assets/sprites/player.tres")
	if sf == null:
		print("RESULT=LOAD_FAILED")
		quit()
		return
	var counts := {}
	var loops := {}
	for n in sf.get_animation_names():
		counts[str(n)] = sf.get_frame_count(n)
		loops[str(n)] = sf.get_animation_loop(n)
	var idle0 = sf.get_frame_texture("idle", 0)
	print("RESULT=" + JSON.stringify({
		"counts": counts, "loops": loops, "idle_atlas": idle0 is AtlasTexture}))
	quit()
"""


@pytest.mark.engine
def test_committed_player_spriteframes_loads_in_godot(tmp_path: Path) -> None:
    probe = tmp_path / "probe.gd"
    probe.write_text(_PROBE, encoding="utf-8")
    run = subprocess.run(
        [str(GODOT), "--headless", "--path", str(GAME_DIR), "--script", str(probe)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    line = next(
        (
            ln.removeprefix("RESULT=")
            for ln in run.stdout.splitlines()
            if ln.startswith("RESULT=")
        ),
        None,
    )
    assert line is not None and line != "LOAD_FAILED", run.stdout + run.stderr
    result = json.loads(line)

    # Every state ships with a nonempty frame set of AtlasTexture frames.
    for state in (*_LOOPING, *_ONESHOT):
        assert result["counts"].get(state, 0) >= 1, (state, result["counts"])
    assert result["idle_atlas"] is True, result

    # Locomotion base states loop; verb one-shots play once (the PlayerAnimator
    # resumes locomotion on their animation_finished).
    for state in _LOOPING:
        assert result["loops"][state] is True, (state, result["loops"])
    for state in _ONESHOT:
        assert result["loops"][state] is False, (state, result["loops"])
