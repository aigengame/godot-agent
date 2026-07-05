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
  data/logic/log stay on the three headless seams.
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
  `test_e2e_screenshot.py`: `gda.display.windowed_unavailable_reason()`
  pre-checks the window server, and the daemon's typed no-display refusals
  (`live_windowed_unavailable` / `live_display_unavailable`, #345) are
  honored as skips — visible under `-rs`, never silent. CI keeps the headless
  seams; the visual-smoke seam runs pre-merge on a real desktop.
- **Engine-side pixel decode.** Captures are analyzed by the engine's own
  `Image` API through `gda script run` (`tests/gdscript/check_pixels.gd`),
  preserving the repo's no-image-decode-dependency convention (no Pillow).
  The checker is a GENERIC counting probe — modes: background-delta,
  color-match, alpha-blend-match, image-delta — that knows nothing about the
  game; it counts matching pixels per spec'd region and reports. WHAT to
  probe (regions, colors, thresholds) is decided on the Python side, derived
  from the authoritative JSON configs and runtime rects read live (the
  settled follow-camera anchors world→screen mapping; Control rects come from
  `gda game get`), never hardcoded.
- **Timing knobs may be retuned in the throwaway copy.** Where a capture must
  land inside a transient visual's lifetime, the test may lengthen a DURATION
  in its throwaway project copy (the waves-e2e chance-retune precedent).
  Colors, sizes, and positions — the things the seam asserts — are never
  retuned.

Consequences:

- The S6a HUD check (PR #398: `check_hud_pixels.gd` + the windowed test in
  `test_reward_hud_e2e.py`) is absorbed as this seam's first checkpoint and
  deleted from its original home — no duplicated windowed sessions.
- The current player-visible surface maps to checkpoints in one boot →
  gravity-fire → kill walk: HUD column at boot (S6a), Enemy Kind and Obstacle
  blockouts at their spawn regions (S4), the Gravity Field's translucent
  blockout while active (S3), the EXP/Gold readout change after a kill (S6a),
  and the next Wave's spawn becoming visible (S5).
- The macOS export in `build/` is a LOCAL, gitignored artifact (S0), not a
  committed one — but it feeds playtests, and a stale build misled one. The
  demo's docs (AGENTS.md) now expect a `gda export run` refresh at wave
  close, and this slice ships one built from current main.
