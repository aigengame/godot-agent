---
status: accepted
---

# Visual-smoke seam: presence-level screenshot checks for player-visible features

The demo's three seams (data, logic, integration) all assert STATE — a node
exists, a Label holds the right text, a log record carries the right fields.
A playtest on the S6a wave asked "can the player actually SEE the HUD and the
reward?", and no committed gate could answer it: an invisible, mispositioned,
or occluded visual satisfies every headless assertion. That is the
"data right, pixels absent" failure class. PR #398 (S6a) closed it for ONE
feature with a one-off windowed pixel check (`check_hud_pixels.gd`); this
decision generalizes that check into the demo's FOURTH test seam so a playtest
never again discovers what a screenshot assertion could have.

The model:

- **Scope trigger.** Any acceptance criterion of the form "the player sees X"
  gets a visual-smoke checkpoint. Features whose surface is purely
  content/data/logic/log stay on the three headless seams.
- **Presence-level structural assertions only.** A checkpoint asserts pixel
  PRESENCE, not appearance: a config-derived region differs from the scene
  background; a blockout color appears near its config position; a readout
  region's pixels change after a state change. Explicitly NOT golden-image
  baselines — blockout-phase art churns daily and GPU/driver/font rendering
  varies per machine, so baselines would be both high-maintenance and flaky.
  Layout aesthetics (spacing, readability, art quality) stay human playtest.
- **One consolidated windowed session.** All checkpoints ride ONE scripted
  scenario in ONE `gda daemon start --windowed` session
  (`tests/test_visual_smoke_e2e.py`), with a handful of captures at scenario
  beats. A windowed engine session is the demo's most expensive test tier;
  when a future slice adds a player-visible feature, it adds a checkpoint (a
  capture and/or a check) to this scenario — never a new windowed session.
- **Display-gated: a desktop tier, not a CI gate.** Gated exactly like
  `test_e2e_screenshot.py`: `gda.display.windowed_unavailable()`
  pre-checks the window server, and the daemon's typed no-display refusals
  (`live_windowed_unavailable` / `live_windowed_permission_denied` /
  `live_display_unavailable`, #345, #667) are
  honored as skips — visible under `-rs`, never silent. CI keeps the headless
  seams; the visual-smoke seam runs pre-merge on a real desktop.
- **Engine-side pixel decode.** Captures are analyzed by the engine's own
  `Image` API through `gda script run` (`tests/gdscript/check_pixels.gd`),
  preserving the repo's no-image-decode-dependency convention (no Pillow).
  The checker is a GENERIC counting probe — modes: background-delta,
  color-match, alpha-blend-match, image-delta — that knows nothing about the
  game; it counts matching pixels per spec'd region and reports. WHAT to
  probe is decided on the Python side, and splits in two:
  - the asserted **game truth** — blockout colors, sizes, spawn/config
    positions, the HUD margin — derives from the authoritative JSON configs
    and live reads (the settled follow-camera anchors world→screen mapping;
    the Stats column's readable offsets), never hardcoded;
  - the probe **mechanics** — presence thresholds, paddings, tolerances, and
    structural probe boxes — are structural TEST constants, named and
    commented as such in the gate. They encode capture-noise policy (what
    counts as "present" on a real GPU), not game data, and deliberately have
    no authoritative-config home.
- **Timing knobs may be retuned in the throwaway copy.** Where a capture must
  land inside a transient visual's lifetime, the test may lengthen a DURATION
  in its throwaway project copy (the waves-e2e chance-retune precedent).
  Colors, sizes, and positions — the things the seam asserts — are never
  retuned.

Consequences:

- The S6a HUD check (PR #398: `check_hud_pixels.gd` + the windowed test in
  `test_reward_hud_e2e.py`) is absorbed as this seam's first checkpoint and
  deleted from its original home — no duplicated windowed sessions.
- The probe's matching logic is itself pinned WITHOUT a display: a headless
  engine-tier test authors tiny synthetic PNG fixtures with the engine's own
  Image API and asserts exact positive/negative counts per mode
  (`test_visual_smoke_probe.py`), so the shared probe cannot silently break
  while the windowed gate is skipping.
- The current player-visible surface maps to checkpoints in one boot →
  gravity-fire → kill walk: HUD column at boot (S6a), Enemy Kind and Obstacle
  blockouts at their spawn regions (S4), the Gravity Field's translucent
  blockout while active (S3), the EXP/Gold readout change after a kill (S6a),
  and the next Wave's spawn becoming visible (S5).
- The macOS export in `build/` is a LOCAL, gitignored artifact (S0), not a
  committed one — but it feeds playtests, and a stale build misled one. The
  demo's docs (AGENTS.md) now expect a `gda export run` refresh at wave
  close, and this slice ships one built from current main.

> **Outcome (2026-07-05).** The "container-managed Controls expose no
> offset/rect to the live reader" constraint that forced the HUD's structural
> probe boxes was filed as gda #419 and fixed in gda v0.5.0: `gda game rect`
> reads a Control's rendered viewport rect live. New checkpoints may probe
> exact per-Control rects (the S7 BUN/WINE item-lines check is the first);
> the whole-column box stays structural because Label text renders past its
> container rect regardless.

> **Amendment (2026-07-06, PR #430).** The retune class is wider than the
> original "lengthen a DURATION" wording: the throwaway copy may also retune
> **scenario-choreography behavior knobs** — aggro ranges, move speeds,
> cooldowns, warp offsets, attack values — that determinize WHEN and WHERE a
> beat happens so a capture lands reliably. The S8 Warp beat already
> practiced this (huge aggro, zero move speed, minute-long cooldown); the S9
> End-screen beat (lose-on-demand: a re-aimed blink plus a one-hit attack)
> makes it explicit. The invariant is unchanged and remains the boundary:
> anything a checkpoint ASSERTS — colors, sizes, blockout geometry, config
> anchors — is never retuned.
