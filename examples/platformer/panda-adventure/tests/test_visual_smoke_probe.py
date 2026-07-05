"""Headless coverage for the Visual-smoke seam's generic pixel probe.

The windowed gate (``test_visual_smoke_e2e.py``) is display-gated and PR CI
runs no Godot at all — so without this test the shared probe's matching logic
(``tests/gdscript/check_pixels.gd``: background_delta / color_match /
blend_match / image_delta) could break while every green tier stays green.
This pins it WITHOUT a display (gADR-0007): tiny synthetic PNG fixtures are
authored by the engine's own Image API (``make_pixel_fixtures.gd`` — the
no-image-decode-dependency convention, no Pillow) with known geometry, so
every mode is asserted with EXACT positive and negative counts, plus the
rect clamp and the loud failure paths.

Engine tier (one-shot headless ``gda script run`` calls — no daemon, no
window), so it runs wherever a Godot binary resolves: the local fast tier
and CI's engine-or-e2e job.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from gda.binary import resolve_godot_binary

import build_config

GDA_CMD = [sys.executable, "-m", "gda"]
GODOT = resolve_godot_binary()
GAME_DIR = build_config.GAME_DIR

# The fixture geometry, mirrored from make_pixel_fixtures.gd — change them
# together. base.png: BACKGROUND everywhere except RED_RECT; next.png: base
# plus DELTA_RECT turned white and BLEND_RECT holding the alpha-mix of
# BLEND_COLOR over the background.
SIZE = 100
BACKGROUND = [0.3, 0.3, 0.3]
RED_RECT = [40, 40, 20, 20]
RED = [1.0, 0.0, 0.0]
DELTA_RECT = [70, 70, 10, 10]
BLEND_RECT = [10, 10, 20, 20]
BLEND_COLOR = [0.35, 0.65, 1.0, 0.35]


def _script_run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """One headless ``gda script run`` against the committed game project."""
    return subprocess.run(
        [
            *GDA_CMD,
            "script",
            "run",
            script,
            "--project",
            str(GAME_DIR),
            "--godot",
            str(GODOT),
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def _make_fixtures(tmp_path, env) -> tuple[str, str]:
    gen = _script_run(
        "res://tests/gdscript/make_pixel_fixtures.gd",
        {**env, "PIXEL_FIXTURES_DIR": str(tmp_path)},
    )
    assert gen.returncode == 0, gen.stdout + gen.stderr
    doc = json.loads(gen.stdout)
    assert doc["exit_status"] == 0, doc
    assert "FIXTURES_DONE" in doc["stdout"], doc["stdout"]
    base, nxt = tmp_path / "base.png", tmp_path / "next.png"
    assert base.exists() and nxt.exists()
    return str(base), str(nxt)


def _run_probe(spec_path, env) -> subprocess.CompletedProcess:
    return _script_run(
        "res://tests/gdscript/check_pixels.gd",
        {**env, "PIXEL_CHECKS_SPEC": str(spec_path)},
    )


def _probe_counts(spec_path, env) -> dict[str, dict]:
    probe = _run_probe(spec_path, env)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    doc = json.loads(probe.stdout)
    assert doc["exit_status"] == 0, doc
    marker = next(
        (
            line.removeprefix("PIXEL_CHECKS: ")
            for line in doc["stdout"].splitlines()
            if line.startswith("PIXEL_CHECKS: ")
        ),
        None,
    )
    assert marker is not None, doc["stdout"]
    return {r["name"]: r for r in json.loads(marker)["results"]}


@pytest.mark.engine
def test_probe_counts_every_mode_exactly(tmp_path):
    env = {**os.environ}
    base_png, next_png = _make_fixtures(tmp_path, env)

    checks = [
        # --- positive: each mode finds exactly its fixture patch ---
        {
            "name": "bg_delta_hits_red",
            "mode": "background_delta",
            "image": "base",
            # A window around RED_RECT; the reference samples plain background.
            "rect": [35, 35, 30, 30],
            "reference": [5, 5],
            "min_delta": 0.15,
        },
        {
            "name": "color_match_red",
            "mode": "color_match",
            "image": "base",
            "rect": [30, 30, 40, 40],
            "color": RED,
            "tolerance": 0.05,
        },
        {
            "name": "blend_match_patch",
            "mode": "blend_match",
            "image": "next",
            "base_image": "base",
            "rect": BLEND_RECT,
            "color": BLEND_COLOR,
            "tolerance": 0.02,
        },
        {
            "name": "image_delta_patch",
            "mode": "image_delta",
            "image": "next",
            "base_image": "base",
            "rect": [65, 65, 20, 20],
            "min_delta": 0.15,
        },
        # --- negative: an absent visual counts ZERO, never "close enough" ---
        {
            "name": "color_match_wrong_color",
            "mode": "color_match",
            "image": "base",
            "rect": [30, 30, 40, 40],
            "color": [0.2, 0.8, 0.6],
            "tolerance": 0.05,
        },
        {
            "name": "color_match_wrong_region",
            "mode": "color_match",
            "image": "base",
            "rect": [0, 60, 30, 30],
            "color": RED,
            "tolerance": 0.05,
        },
        {
            "name": "bg_delta_uniform_region",
            "mode": "background_delta",
            "image": "base",
            "rect": [0, 60, 30, 30],
            "reference": [5, 5],
            "min_delta": 0.15,
        },
        {
            "name": "image_delta_unchanged_region",
            "mode": "image_delta",
            "image": "next",
            "base_image": "base",
            "rect": [40, 40, 20, 20],
            "min_delta": 0.15,
        },
        # --- rect clamp: out-of-bounds pixels are skipped, not sampled ---
        {
            "name": "clamped_rect",
            "mode": "color_match",
            "image": "base",
            "rect": [90, 90, 20, 20],
            "color": BACKGROUND,
            "tolerance": 0.05,
        },
    ]
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps({"images": {"base": base_png, "next": next_png}, "checks": checks})
    )
    counted = _probe_counts(spec_path, env)

    red_area = RED_RECT[2] * RED_RECT[3]
    blend_area = BLEND_RECT[2] * BLEND_RECT[3]
    delta_area = DELTA_RECT[2] * DELTA_RECT[3]
    expected = {
        # (counted, sampled) — flat synthetic fills, so counts are EXACT.
        "bg_delta_hits_red": (red_area, 900),
        "color_match_red": (red_area, 1600),
        "blend_match_patch": (blend_area, blend_area),
        "image_delta_patch": (delta_area, 400),
        "color_match_wrong_color": (0, 1600),
        "color_match_wrong_region": (0, 900),
        "bg_delta_uniform_region": (0, 900),
        "image_delta_unchanged_region": (0, 400),
        "clamped_rect": (100, 100),
    }
    for name, (want_counted, want_sampled) in expected.items():
        got = counted[name]
        assert (got["counted"], got["sampled"]) == (want_counted, want_sampled), (
            f"{name}: got counted={got['counted']} sampled={got['sampled']}, "
            f"want counted={want_counted} sampled={want_sampled}"
        )


@pytest.mark.engine
def test_probe_fails_loudly_on_bad_input(tmp_path):
    env = {**os.environ}

    def assert_check_fail(proc: subprocess.CompletedProcess, needle: str):
        # `script run` promotes the script's own exit into exit_status; the
        # CLI call itself succeeds. Failures must be LOUD (CHECK_FAIL + 1),
        # never a zero-count result that upstream thresholds happen to catch.
        assert proc.returncode == 0, proc.stdout + proc.stderr
        doc = json.loads(proc.stdout)
        assert doc["exit_status"] == 1, doc
        assert "CHECK_FAIL" in doc["stdout"], doc["stdout"]
        assert needle in doc["stdout"], doc["stdout"]

    # No spec env at all.
    no_spec_env = {k: v for k, v in env.items() if k != "PIXEL_CHECKS_SPEC"}
    assert_check_fail(
        _script_run("res://tests/gdscript/check_pixels.gd", no_spec_env),
        "PIXEL_CHECKS_SPEC not set",
    )

    base_png, _ = _make_fixtures(tmp_path, env)

    # An unknown mode is a spec bug, not a zero count.
    bad_mode = tmp_path / "bad_mode.json"
    bad_mode.write_text(
        json.dumps(
            {
                "images": {"base": base_png},
                "checks": [
                    {
                        "name": "x",
                        "mode": "bogus_mode",
                        "image": "base",
                        "rect": [0, 0, 4, 4],
                    }
                ],
            }
        )
    )
    assert_check_fail(_run_probe(bad_mode, env), "bad check spec")

    # A missing image file fails at load, before any counting.
    missing_image = tmp_path / "missing_image.json"
    missing_image.write_text(
        json.dumps(
            {
                "images": {"base": str(tmp_path / "nope.png")},
                "checks": [],
            }
        )
    )
    assert_check_fail(_run_probe(missing_image, env), "could not load image")
