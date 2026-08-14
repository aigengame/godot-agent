# Reward Run playable

Reward Run is the player-facing HITL product for the maintained
`roguelike-reward-build` slice. It presents two short, comparable trials and hides the Model,
Experiment, Formula, trace, Metric, and artifact workflow from the player.

The player defeats a training target, equips a reward, and tests the changed build against a
tougher target. Trial 1 grants Storm Crown with power 90. Trial 2 grants Iron Guard with power 30.
Both trials begin with the same Training Blade and target conditions. The contrast makes the
reward and equipment change directly perceptible.

The player can use the action button or press Space/Enter. After both trials, the in-game form
records preference, perceived reward strength, equipment-change clarity, and optional notes.
**Save & Copy Feedback** writes `user://reward_run_feedback.json` and copies the same player-facing
payload to the clipboard.

## Visual checkpoints

| Trial | Reward | Feedback |
| --- | --- | --- |
| ![Initial trial](docs/screenshots/initial-trial.png) | ![Reward reveal](docs/screenshots/reward-reveal.png) | ![Feedback form](docs/screenshots/feedback.png) |

## Architecture

The project uses one-way Godot modules:

```text
UI -> Content -> Systems -> Godot
```

- `systems/playtest_session.gd` owns the reusable multi-trial lifecycle.
- `systems/playtest_feedback.gd` owns the reusable feedback envelope and persistence.
- `systems/reward_run.gd` owns Reward Run combat, reward, equipment, and completion state.
- `content/reward_run/reward_outcome_source.gd` is the current generated-case Adapter.
- `content/reward_run/reward_run_controller.gd` coordinates the feature and feedback submission.
- `ui/playtest_shell.gd` owns common progress, controls, feedback, and copy behavior.
- `ui/reward_run_view.gd` owns Reward presentation and Tween animations.
- `main.gd` is the thin bootstrap that injects the Adapter and connects the UI.

The project has no Add-on, Autoload, event bus, service container, or plugin registry. A later live
Runtime Adapter can replace the generated-case Adapter at the Content composition seam without
changing UI or Systems. The generated-case Adapter owns its file locator; Reward Content sees only
feature outcomes. No live protocol is designed here.

## Generated product data

- `generated/reward_cases.json` contains player-facing reward and build values plus opaque
  playtest provenance references. The exported product loads this file but does not resolve the
  references.
- `generated/evidence/playtest-provenance.json` maps each opaque reference to exact formal
  artifacts for maintainers. The Godot product does not load or export this file.
- `generated/evidence/` contains the referenced public artifacts and is excluded from export.

Regenerate the cases from `libs/gda-balancing` through the installed public command:

```bash
uv run python examples/schema2/playtest/tools/generate_reward_cases.py
```

Check that the committed projection is current without rewriting it:

```bash
uv run python examples/schema2/playtest/tools/generate_reward_cases.py --check
```

The generator imports no gda-balancing Python module. It runs `model check`, `model build`,
`experiment check`, and `experiment run` as subprocesses.

## Verify the Godot product

Set `GDA_GODOT` to Godot 4.6 or later. From `libs/gda-balancing`, run the focused Systems test:

```bash
uv run --directory ../.. --frozen gda script run \
  res://tests/test_playtest.gd \
  --project "$PWD/examples/schema2/playtest" \
  --json
```

For a real player-path check, start a windowed session:

```bash
uv run --directory ../.. --frozen gda daemon start \
  --windowed \
  --project "$PWD/examples/schema2/playtest" \
  --json
```

Use `gda input`, `gda screen capture`, `gda logger tail`, and `gda diag errors` to verify mouse and
keyboard play, the reward reveal, the build change, feedback save, structured completion logs, and
the absence of runtime errors. A headless DisplayServer skip is not visual evidence. Stop the
daemon and run `gda daemon uninstall` after live verification so the development harness does not
become project architecture.

## Export the player product

The first supported delivery is an unsigned macOS debug `.app`. The preset excludes documentation,
maintainer evidence, provenance, tests, tools, and the transient gda harness. With `gda` on `PATH`
and matching Godot export templates installed, run:

```bash
examples/schema2/playtest/scripts/export_macos.sh
```

The script creates `build/RewardRun.app` and launches its bundled binary headlessly. The smoke test
passes only when the exported product reaches the player-facing path without Python, `gda`, or a
development harness.
