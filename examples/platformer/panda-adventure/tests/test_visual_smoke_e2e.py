"""The Visual-smoke seam gate (gADR-0007, #401) — pixels, not just state.

The demo's fourth test seam: ONE windowed Engine session walks ONE scripted
scenario (boot -> gravity fire -> kill) and a handful of viewport captures
prove every player-visible feature actually RENDERS — closing the
"data right, pixels absent" class a playtest exposed (an invisible,
mispositioned, or occluded visual satisfies every headless node/label/log
assertion). Checkpoints over the current player-visible surface:

- the HUD column is visible at boot (absorbs S6a's per-feature windowed
  check from ``test_reward_hud_e2e.py`` — the seam's first checkpoint);
- Wave 1's Enemy Kind blockout and the Obstacle blockout are visible at
  their config spawn regions (S4/S3);
- the Gravity Field's translucent blockout is visible while active after a
  gravity fire — its config RGBA alpha-blended over the boot capture (S3);
- the EXP/Gold readout pixels change after a kill (S6a), and the next
  Wave's spawn becomes visible (S5) — the reward loop, on screen.

All assertions are presence-level and config-derived (gADR-0007): colors,
sizes, and positions come from the authoritative JSON; screen regions come
from the settled follow-camera anchor (the camera centers on the Player, so
``world - player + viewport/2``) and from HUD Control rects read live; pixel
decode happens engine-side (``tests/gdscript/check_pixels.gd`` via ``gda
script run`` — the no-image-decode-dependency convention). Explicitly NOT a
golden-image test: blockout art churns and GPU/font rendering varies, so only
structural pixel properties are asserted.

One timing knob is retuned in the throwaway copy: ``field_duration`` is
lengthened so a capture reliably lands inside the Gravity Field's lifetime
(the waves-e2e retune precedent; gADR-0007 allows durations, never
colors/geometry).

Display-gated like ``test_e2e_screenshot.py``: skips visibly (``-rs``) where
no window server is usable — a desktop/pre-merge tier, not a CI gate; CI
keeps the headless seams. Isolation: the throwaway-copy pattern (``daemon
start`` mutates ``project.godot``); posix-only (AF_UNIX).
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gda.binary import resolve_godot_binary

import build_config

pytestmark = pytest.mark.skipif(os.name != "posix", reason="daemon uses AF_UNIX")

GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

_COPY_IGNORE = shutil.ignore_patterns(
    "tests", ".godot", "build", "generated", "__pycache__"
)

# Daemon error codes meaning "this environment cannot show a window" — a skip
# signal, not a failure (the test_e2e_screenshot.py precedent, #345).
_NO_DISPLAY_CODES = {"live_windowed_unavailable", "live_display_unavailable"}

_HUD_LABEL = "/root/Main/Hud/Stats/%sLabel"

# --- Structural test constants (capture mechanics, not game balance) ---

# The shipped field_duration (~2s) is shorter than the CLI round-trips between
# "fire" and "capture" can guarantee, so the throwaway copy lengthens the
# DURATION only — the one timing retune gADR-0007 allows.
_FIELD_DURATION_FLOOR = 8.0
# Follow-camera settle before a capture anchors world->screen mapping on the
# Player: the smoothing residual decays as e^(-speed*t); at the shipped speed
# (5.0) and t=2s even a full-screen pan settles to < 0.1 px.
_CAMERA_SETTLE = 2.0
# Padding around a blockout's config rect: absorbs sub-pixel camera residual
# and tween/antialiasing edges. Background pixels inside the padded region
# simply don't match, so padding never weakens a color check.
_REGION_PAD = 24.0
# Clearance the Gravity Field probe keeps from neighboring level geometry
# (Platform top, Obstacle bottom) so the blend reference stays unoccluded.
_PROBE_CLEARANCE = 8.0
# The probe box over the HUD column, anchored at the config margin (the S6a
# probe grown to six lines). A fixed box, not the live VBox rect: Labels
# render text past their container rect (no clip), and container-managed
# Controls expose no offset/rect properties to the live reader — the rendered
# extent is only ever approximated structurally.
_HUD_PROBE_SIZE = (280.0, 190.0)
# The HUD column's line order (hud_controller.LINES): hp, mp, level, exp,
# gold, weapon — the EXP/GOLD readout band is lines 3..4 of 6.
_HUD_LINES = 6
_EXP_LINE = 3
_GOLD_LINE = 4
# Padding on the readout band, absorbing the VBox's row separation.
_READOUT_PAD = 6.0

# --- Presence thresholds ---

# Non-background pixels the HUD column region must show (S6a precedent):
# six lines of light text light up thousands; 200 stays far from
# antialiasing noise while failing hard on an invisible/mispositioned HUD.
_MIN_HUD_PIXELS = 200
# Per-channel delta that counts a pixel as "not background" / "changed"
# (S6a precedent).
_CHANNEL_DELTA = 0.15
# Fraction of a blockout's own (unpadded) area that must match its config
# color. Blockouts are opaque flat rects in an unlit scene, so most of the
# area matches exactly; 0.5 tolerates tween/AA edges and partial overlap.
_BLOCKOUT_FILL = 0.5
# Fraction of the Gravity Field probe that must match the config RGBA
# blended over the boot capture (probe sits over uniform background).
_FIELD_FILL = 0.6
# Changed pixels the EXP/Gold readout region must show after the kill: one
# changed digit glyph at the default font is tens of pixels; two labels
# change ("EXP 0"->"EXP 10", "GOLD 0"->"GOLD 5").
_MIN_READOUT_DELTA_PIXELS = 20
# Per-channel tolerance for opaque blockout colors (flat unlit rects — only
# 8-bit quantization away from the config value).
_COLOR_TOLERANCE = 0.05
# Per-channel tolerance for the translucent field blend (adds the fade
# tween's final frame and 8-bit rounding on both captures).
_BLEND_TOLERANCE = 0.06


def _make_project_copy(dst: Path) -> Path:
    """Copy the game into a throwaway dir, retune the ONE timing knob, build.

    ``field_duration`` is floored to ``_FIELD_DURATION_FLOOR`` so the field
    outlives the fire->capture CLI round-trips; everything the seam ASSERTS
    (colors, sizes, positions, offsets) ships untouched.
    """
    shutil.copytree(GAME_DIR, dst, ignore=_COPY_IGNORE)
    gravity_path = dst / "data" / "json" / "gravity_config.json"
    doc = json.loads(gravity_path.read_text())
    doc["field_duration"] = max(float(doc["field_duration"]), _FIELD_DURATION_FLOOR)
    gravity_path.write_text(json.dumps(doc, indent=2) + "\n")
    build_config.build_all(root=dst)
    return dst


def _error_code(stdout: str) -> str | None:
    """The gda error envelope's ``error.code`` from a CLI result, if any."""
    try:
        return json.loads(stdout).get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None


@pytest.mark.e2e
def test_player_visible_surface_renders_in_the_windowed_viewport(
    tmp_path, daemon_runtime_dir
):
    from gda.display import windowed_unavailable_reason

    reason = windowed_unavailable_reason()
    if reason is not None:
        pytest.skip(reason)

    project = _make_project_copy(tmp_path / "game")

    # Every expectation derives from the AUTHORITATIVE JSON, never hardcoded.
    enemies = build_config.load_json(GAME_DIR / "data" / "json" / "enemies_config.json")
    gravity = build_config.load_json(GAME_DIR / "data" / "json" / "gravity_config.json")
    combat = build_config.load_json(GAME_DIR / "data" / "json" / "combat_config.json")
    player_cfg = build_config.load_json(
        GAME_DIR / "data" / "json" / "player_config.json"
    )
    wave1_spawns = enemies["waves"][0]["spawns"]
    wave2_spawns = enemies["waves"][1]["spawns"]
    default_spawn = wave1_spawns[0]
    kind = enemies["kinds"][default_spawn["kind"]]
    reward = enemies["tiers"][kind["tier"]]
    player_stats = combat["player_stats"]
    # The S2 damage formula + the S6a kill walk (the reward-e2e-proven loop).
    laser_damage = max(
        combat["min_damage"],
        player_stats["attack"] * combat["attack_scale"]
        - kind["defense"] * combat["defense_scale"],
    )
    shots_to_kill = math.ceil(kind["max_hp"] / laser_damage)
    iframe = combat["iframe_duration"]
    rest_y = (
        player_cfg["platform_position"][1]
        - player_cfg["platform_size"][1] / 2.0
        - player_cfg["player_size"][1] / 2.0
    )
    start_x = player_cfg["player_start"][0]
    enemy_x = default_spawn["position"][0]
    target_x = enemy_x - kind["aggro_range"] + 40.0
    hold_ticks = round((target_x - start_x) / (player_cfg["move_speed"] / 60.0))
    # Level geometry bounding the Gravity Field probe (world space).
    platform_top = (
        player_cfg["platform_position"][1] - player_cfg["platform_size"][1] / 2.0
    )
    obstacle_bottom = (
        gravity["obstacle_position"][1] + gravity["obstacle_size"][1] / 2.0
    )
    env = {**os.environ}

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                *GDA_CMD,
                *args,
                "--project",
                str(project),
                "--godot",
                str(GODOT),
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    def records(message: str) -> list[dict]:
        proc = run("logger", "tail")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return [
            r
            for r in json.loads(proc.stdout)["records"]
            if r["message"] == message and r["origin"] == "gda_log"
        ]

    def poll(predicate, timeout: float = 20.0, interval: float = 0.5):
        deadline = time.monotonic() + timeout
        result = predicate()
        while not result and time.monotonic() < deadline:
            time.sleep(interval)
            result = predicate()
        return result

    def prop(path: str, name: str):
        got = run("game", "get", path, "--property", name)
        assert got.returncode == 0, got.stdout + got.stderr
        for p in json.loads(got.stdout)["properties"]:
            if p["name"] == name:
                return p["value"]
        raise AssertionError(f"{name} not returned for {path}")

    def label(key: str) -> str:
        return prop(_HUD_LABEL % key, "text")

    def tap(action: str) -> None:
        seq = run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": action, "frame": 0},
                    {"type": "action", "action": action, "release": True, "frame": 4},
                ]
            ),
        )
        assert seq.returncode == 0, seq.stdout + seq.stderr

    def capture(name: str) -> tuple[Path, dict]:
        out = tmp_path / f"{name}.png"
        cap = run("screen", "capture", "--output", str(out))
        if cap.returncode != 0:
            code = _error_code(cap.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(f"windowed session unavailable ({code})")
            raise AssertionError(cap.stdout + cap.stderr)
        doc = json.loads(cap.stdout)
        assert doc["format"] == "png"
        assert doc["width"] > 0 and doc["height"] > 0
        return out, doc

    try:
        started = run("daemon", "start", "--windowed")
        if started.returncode != 0:
            code = _error_code(started.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(f"windowed session unavailable ({code})")
            raise AssertionError(started.stdout + started.stderr)
        assert json.loads(started.stdout)["windowed"] is True

        # The Engine session launches lazily on the first live op; if this
        # environment can't bring up a window after all (env race past the
        # pre-check), the daemon reports a display code — skip, not fail.
        tree = run("game", "tree")
        if tree.returncode != 0:
            code = _error_code(tree.stdout)
            if code in _NO_DISPLAY_CODES:
                pytest.skip(f"windowed session unavailable ({code})")
            raise AssertionError(tree.stdout + tree.stderr)

        # --- Beat 1: boot. HUD live, Player landed, camera settled — this
        # capture is both the boot checkpoint and the blend/diff baseline.
        assert poll(lambda: records("hud_ready")), "no gda_log 'hud_ready' record"
        assert poll(
            lambda: abs(prop("/root/Main/Player", "position")[1] - rest_y) <= 2.0
        ), "Player did not land"
        time.sleep(_CAMERA_SETTLE)
        anchor_boot = prop("/root/Main/Player", "position")
        # The HUD column's screen anchor and row pitch. The Stats VBox is
        # free-positioned (its offsets ARE readable, unlike its
        # container-managed Labels'), sits at the config margin, and stacks
        # _HUD_LINES uniform Label rows down to offset_bottom.
        stats_left = prop("/root/Main/Hud/Stats", "offset_left")
        stats_top = prop("/root/Main/Hud/Stats", "offset_top")
        stats_bottom = prop("/root/Main/Hud/Stats", "offset_bottom")
        row_pitch = (stats_bottom - stats_top) / _HUD_LINES
        hud_cfg = build_config.load_json(GAME_DIR / "data" / "json" / "hud_config.json")
        assert (stats_left, stats_top) == pytest.approx(tuple(hud_cfg["margin"])), (
            "the rendered HUD column is not anchored at the config margin"
        )
        boot_png, boot_doc = capture("boot")
        dims = (boot_doc["width"], boot_doc["height"])

        # --- Beat 2: one Gravity Gun fire; capture while the field is live
        # (its retuned duration outlives these round-trips).
        tap("switch_weapon")
        assert poll(lambda: label("Weapon") == "GRAVITY GUN"), (
            "HUD should show the Gravity Gun after switch_weapon"
        )
        tap("fire")
        spawned = poll(lambda: records("gravity_field_spawned"))
        assert spawned, "no gda_log 'gravity_field_spawned' record"
        field_x = spawned[0]["fields"]["x"]
        field_y = spawned[0]["fields"]["y"]
        assert spawned[0]["fields"]["radius"] == pytest.approx(gravity["field_radius"])
        field_png, field_doc = capture("field")
        assert (field_doc["width"], field_doc["height"]) == dims

        # --- Beat 3: the S6a kill walk (Laser back, physics-clock walk into
        # Aggro Range, spaced shots past the i-frame), then let the readout,
        # the Wave-2 spawn, and the camera settle before the last capture.
        tap("switch_weapon")
        assert poll(lambda: label("Weapon") == "LASER GUN"), (
            "HUD should show the Laser Gun after switching back"
        )
        walk = run(
            "input",
            "sequence",
            "--events",
            json.dumps(
                [
                    {"type": "action", "action": "move_right", "physics_frame": 0},
                    {
                        "type": "action",
                        "action": "move_right",
                        "release": True,
                        "physics_frame": hold_ticks,
                    },
                ]
            ),
        )
        assert walk.returncode == 0, walk.stdout + walk.stderr
        for _ in range(shots_to_kill * 2):
            if records("enemy_died"):
                break
            time.sleep(iframe + 0.3)
            tap("fire")
            poll(lambda: bool(records("enemy_died")), timeout=3.0)
        assert poll(lambda: records("enemy_died")), "the Enemy never died"

        exp_text = f"EXP {math.floor(reward['exp_reward'])}"
        gold_text = f"GOLD {math.floor(reward['gold_reward'])}"
        assert poll(lambda: label("Exp") == exp_text), (
            f"EXP readout never showed the reward: {label('Exp')}"
        )
        assert poll(lambda: label("Gold") == gold_text), (
            f"Gold readout never showed the reward: {label('Gold')}"
        )
        assert poll(
            lambda: any(r["fields"]["wave"] == 2 for r in records("wave_started"))
        ), "Wave 2 never started after the kill"
        time.sleep(_CAMERA_SETTLE)
        anchor_kill = prop("/root/Main/Player", "position")
        kill_png, kill_doc = capture("kill")
        assert (kill_doc["width"], kill_doc["height"]) == dims
    finally:
        run("daemon", "stop")

    # ------------------------------------------------------------------
    # Derive the presence checks (all from config + live-read anchors) and
    # run the engine-side probe ONCE, offline, over the three captures.
    # ------------------------------------------------------------------

    def to_screen(wx: float, wy: float, anchor) -> tuple[float, float]:
        """World -> screen under the settled follow-camera (drag-center)."""
        return (wx - anchor[0] + dims[0] / 2.0, wy - anchor[1] + dims[1] / 2.0)

    def blockout_region(world_pos, size, anchor) -> list[float]:
        """The padded screen rect of a blockout centered on ``world_pos``."""
        cx, cy = to_screen(world_pos[0], world_pos[1], anchor)
        return [
            cx - size[0] / 2.0 - _REGION_PAD,
            cy - size[1] / 2.0 - _REGION_PAD,
            size[0] + 2 * _REGION_PAD,
            size[1] + 2 * _REGION_PAD,
        ]

    def blockout_min(size) -> int:
        return int(_BLOCKOUT_FILL * size[0] * size[1])

    def pad_rect(rect, pad: float) -> list[float]:
        return [
            rect[0] - pad,
            rect[1] - pad,
            rect[2] + 2 * pad,
            rect[3] + 2 * pad,
        ]

    # The Gravity Field probe: the inner half of the field square, clipped
    # clear of the Obstacle above, the Platform below, and the Player to the
    # left, so the blend reference (the boot capture) is uniform background
    # there. Bounds are all config/live-derived (gADR-0007).
    radius = gravity["field_radius"]
    player_right = anchor_boot[0] + player_cfg["player_size"][0] / 2.0
    fx0 = max(field_x - radius / 2.0, player_right + _PROBE_CLEARANCE)
    fx1 = field_x + radius / 2.0
    fy0 = max(field_y - radius / 2.0, obstacle_bottom + _PROBE_CLEARANCE)
    fy1 = min(field_y + radius / 2.0, platform_top - _PROBE_CLEARANCE)
    assert fx1 - fx0 >= 16 and fy1 - fy0 >= 16, (
        f"Gravity Field probe collapsed ({fx0},{fy0})-({fx1},{fy1}) — "
        "did the level geometry around the field spawn change?"
    )
    sx0, sy0 = to_screen(fx0, fy0, anchor_boot)
    field_region = [sx0, sy0, fx1 - fx0, fy1 - fy0]

    # The HUD probe box: the config-margin anchor (cross-checked against the
    # live Stats offsets) + the structural probe size.
    hud_region = [stats_left, stats_top, _HUD_PROBE_SIZE[0], _HUD_PROBE_SIZE[1]]

    # The EXP/Gold readout band: lines _EXP_LINE.._GOLD_LINE of the HUD
    # column's uniform row stack, full probe width (Label text renders past
    # the 1px-wide shrink-wrapped VBox rect), padded for the row separation.
    readout_region = [
        stats_left - _READOUT_PAD,
        stats_top + _EXP_LINE * row_pitch - _READOUT_PAD,
        _HUD_PROBE_SIZE[0] + 2 * _READOUT_PAD,
        (_GOLD_LINE - _EXP_LINE + 1) * row_pitch + 2 * _READOUT_PAD,
    ]

    # (check spec, minimum matching pixels, what a failure means)
    checks: list[tuple[dict, int, str]] = [
        (
            {
                "name": "hud_column",
                "mode": "background_delta",
                "image": "boot",
                "rect": pad_rect(hud_region, 4.0),
                # Top-right inset: the HUD column sits at the top-left
                # margin, so this samples plain scene background (S6a).
                "reference": [dims[0] - 8, 8],
                "min_delta": _CHANNEL_DELTA,
            },
            _MIN_HUD_PIXELS,
            "the HUD column is not visibly rendering at boot",
        ),
        (
            {
                "name": "obstacle",
                "mode": "color_match",
                "image": "boot",
                "rect": blockout_region(
                    gravity["obstacle_position"], gravity["obstacle_size"], anchor_boot
                ),
                "color": gravity["obstacle_color"][:3],
                "tolerance": _COLOR_TOLERANCE,
            },
            blockout_min(gravity["obstacle_size"]),
            "the Obstacle blockout is not visible at its config position",
        ),
        (
            {
                "name": "gravity_field",
                "mode": "blend_match",
                "image": "field",
                "base_image": "boot",
                "rect": field_region,
                "color": gravity["field_color"],
                "tolerance": _BLEND_TOLERANCE,
            },
            int(_FIELD_FILL * field_region[2] * field_region[3]),
            "the Gravity Field's translucent blockout is not visible while active",
        ),
        (
            {
                "name": "exp_gold_readout",
                "mode": "image_delta",
                "image": "kill",
                "base_image": "boot",
                "rect": readout_region,
                "min_delta": _CHANNEL_DELTA,
            },
            _MIN_READOUT_DELTA_PIXELS,
            "the EXP/Gold readout did not visibly change after the kill",
        ),
    ]
    for spawn in wave1_spawns:
        spawn_kind = enemies["kinds"][spawn["kind"]]
        checks.append(
            (
                {
                    "name": f"wave1_{spawn['name']}",
                    "mode": "color_match",
                    "image": "boot",
                    "rect": blockout_region(
                        spawn["position"], spawn_kind["size"], anchor_boot
                    ),
                    "color": spawn_kind["color"][:3],
                    "tolerance": _COLOR_TOLERANCE,
                },
                blockout_min(spawn_kind["size"]),
                f"Wave 1 spawn '{spawn['name']}' ({spawn['kind']}) blockout "
                "is not visible at its spawn region at boot",
            )
        )
    for spawn in wave2_spawns:
        spawn_kind = enemies["kinds"][spawn["kind"]]
        checks.append(
            (
                {
                    "name": f"wave2_{spawn['name']}",
                    "mode": "color_match",
                    "image": "kill",
                    "rect": blockout_region(
                        spawn["position"], spawn_kind["size"], anchor_kill
                    ),
                    "color": spawn_kind["color"][:3],
                    "tolerance": _COLOR_TOLERANCE,
                },
                blockout_min(spawn_kind["size"]),
                f"Wave 2 spawn '{spawn['name']}' ({spawn['kind']}) blockout "
                "is not visible after the kill advanced the wave",
            )
        )

    spec_path = tmp_path / "pixel_checks.json"
    spec_path.write_text(
        json.dumps(
            {
                "images": {
                    "boot": str(boot_png),
                    "field": str(field_png),
                    "kill": str(kill_png),
                },
                "checks": [c for c, _, _ in checks],
            }
        )
    )
    # Decode/count with the engine's own Image API. The throwaway copy
    # excludes tests/, so the probe runs against the committed game dir —
    # only the spec path (env) feeds it.
    probe = subprocess.run(
        [
            *GDA_CMD,
            "script",
            "run",
            "res://tests/gdscript/check_pixels.gd",
            "--project",
            str(GAME_DIR),
            "--godot",
            str(GODOT),
            "--json",
        ],
        capture_output=True,
        text=True,
        env={**env, "PIXEL_CHECKS_SPEC": str(spec_path)},
        timeout=120,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    result = json.loads(probe.stdout)
    assert result["exit_status"] == 0, result
    marker = next(
        (
            line.removeprefix("PIXEL_CHECKS: ")
            for line in result["stdout"].splitlines()
            if line.startswith("PIXEL_CHECKS: ")
        ),
        None,
    )
    assert marker is not None, result["stdout"]
    counted = {r["name"]: r for r in json.loads(marker)["results"]}

    for check, min_pixels, meaning in checks:
        got = counted[check["name"]]
        assert got["counted"] >= min_pixels, (
            f"{check['name']}: {got['counted']} of {got['sampled']} pixels match "
            f"(need >= {min_pixels}) in rect {check['rect']} — {meaning}"
        )
