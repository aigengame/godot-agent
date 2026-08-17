# RPG playtest suite

This repository-local Godot project contains three small, player-facing applications:

| Application | Player experience | Feature under test |
| --- | --- | --- |
| Reward Run | Break targets, equip a reward, and compare two builds. | Reward frequency and build impact |
| Arcane Duel | Cast a spell and absorb a counterattack across two exchanges. | Reciprocal damage and resource readability |
| Curse Timing | Apply two curses and watch each pulse, strike, and expiry. | Periodic-effect timing and impact |

Each application uses blockout shapes, short Tween animations, mouse and keyboard controls, and a
feature-specific feedback form. A player does not need to know how `gda-balancing` compiles or
executes the maintained data.

## Launch a playtest

Install the `gda-balancing` package environment and provide Godot 4.6 or later. From
`libs/gda-balancing`, choose one application:

```bash
GDA_GODOT=/absolute/path/to/godot \
  examples/schema2/playtest/scripts/run_reward_run.sh

GDA_GODOT=/absolute/path/to/godot \
  examples/schema2/playtest/scripts/run_combat_cast.sh

GDA_GODOT=/absolute/path/to/godot \
  examples/schema2/playtest/scripts/run_periodic_effect.sh
```

The common launcher finds `gda-balancing` from `GDA_BALANCING_EXECUTABLE` or the current `PATH`.
It passes an explicit executable to the game when one is found. Otherwise, the game Add-on performs
its own `PATH` lookup. An invalid explicit path produces a visible retry action. It does not
silently select another installation.

These are repository-local products. They do not embed Python, package a companion executable, or
claim standalone export support.

## Player controls and feedback

Use the primary button or press Space or Enter to advance gameplay. Use the settings on the main
screen to select 1080p, 2K, or 4K. The default is 2K. The language selector supports English and
Simplified Chinese. English is the default.

Each application saves a different feedback file:

| Application | Feedback file |
| --- | --- |
| Reward Run | `user://reward_run_feedback.json` |
| Arcane Duel | `user://rpg_combat_cast_feedback.json` |
| Curse Timing | `user://rpg_periodic_effect_feedback.json` |

After a playthrough, **Save & Copy Feedback** writes the file, shows its platform-specific absolute
path, and copies the same JSON payload to the clipboard. The payload contains the player's answers,
optional notes, observed gameplay values, and opaque provenance for maintainers. The UI copies the
payload as one value. It does not inspect or display that provenance.

### Reward Run

1. Choose a rare-reward frequency and start the first trial.
2. Break a target with the Training Blade.
3. Equip the selected reward.
4. Test the changed build on a stronger target.
5. Choose another frequency and complete the second trial.
6. Compare both results and save feedback.

The maintained seed makes `5` and `2` a useful comparison. Frequency `5` selects the rare Storm
Crown and produces power 90. Frequency `2` selects the common Iron Guard and produces power 30.

| Frequency | Reward | Feedback |
| --- | --- | --- |
| ![Frequency control](docs/screenshots/initial-trial.png) | ![Reward reveal](docs/screenshots/reward-reveal.png) | ![Feedback form](docs/screenshots/feedback.png) |

### Arcane Duel

1. Cast a spell and inspect the rival's health and mana.
2. Reveal the rival's counterattack and inspect your health.
3. Continue to a second exchange that starts from the first exchange's validated result.
4. Compare the two exchanges and save feedback.

Godot presents the returned damage, health, mana, and order. It does not calculate the combat
outcome.

### Curse Timing

1. Apply the first curse.
2. Watch the curse pulse, an intervening strike, another pulse, and expiry.
3. Repeat the same sequence with the second curse.
4. Compare the timing and impact, then save feedback.

Both trials derive from the maintained same-time experiment. They use the same visible ordering.
The Effect entrypoint is the only comparison variable. Godot presents the validated lifecycle. It
does not calculate effect magnitude, damage, timing, or scheduling.

## Architecture

The project uses four downward dependency layers. Each application has a thin composition root.

```text
apps/<application>/main
          |
          v
ui/<application> -> content/<application> -> systems/<application>
                              |
                              v
                 addons/gda_balancing_client -> local gda-balancing service
```

- `apps/` creates one view, one Content controller, and one game-neutral execution client for each
  application. It owns no gameplay or document rules.
- `ui/` owns player presentation, feature controls, feature questions, localization, and Tweens.
- `content/` reads maintained documents, creates complete Experiment revisions, validates returned
  relationships, projects gameplay values, coordinates application flow, and records feedback.
- `systems/` advances only validated gameplay values. It does not parse protocol or Standard Schema
  structures and does not repeat calculations already performed by `gda-balancing`.
- `addons/gda_balancing_client/` owns executable discovery, child-process lifetime, readiness,
  credentials, generic `/v1` requests, handles, and shutdown. It contains no Reward, Combat, or
  Effect fields.
- `addons/playtest_feedback_file/`, `ui/playtest_shell.gd`, and `scripts/run_playtest.sh` contain
  only behavior used by multiple applications.

The project has no Autoload, service locator, event bus, application registry, universal gameplay
payload, or game-specific service route.

## Authoritative data path

Each Content module reads its maintained Model Source and Experiment documents directly:

| Application | Maintained source directory | Model Source input | Experiment input |
| --- | --- | --- | --- |
| Reward Run | `examples/schema2/roguelike-reward-build/` | `model-source.json` | `experiment.json` |
| Arcane Duel | `examples/schema2/rpg-combat-cast/` | `model-source.json` | `experiment.json` |
| Curse Timing | `examples/schema2/rpg-periodic-effect/` | `model-source.json` | `same-time-experiment.json` |

Content sends complete JSON values to the generic local service. Each edit produces a complete,
immutable Experiment revision. Runs always name an exact revision.

The live product path has no generated case file, generator, deployment copy, partial-update
format, or fallback gameplay data. Model Source Packages and Experiment Specifications remain the
only authored authorities. Technical artifacts stay inside Content except for the opaque
maintainer provenance included in saved feedback.

## Developer verification

Run the structure, source-authority, localization, and dependency checks:

```bash
uv run pytest tests/test_schema2_playtest.py
```

Run each critical UI-to-service-to-feedback path with a different writable Godot user-data root:

```bash
export PLAYTEST_USER_DATA_ROOT="$(mktemp -d /tmp/gda-playtest-reward.XXXXXX)"
PATH="$PWD/.venv/bin:$PATH" \
  uv run --directory ../.. --frozen gda \
  --user-data-root "$PLAYTEST_USER_DATA_ROOT" \
  script run res://tests/test_reward_run_main_live.gd \
  --project "$PWD/examples/schema2/playtest" --json

export PLAYTEST_USER_DATA_ROOT="$(mktemp -d /tmp/gda-playtest-combat.XXXXXX)"
PATH="$PWD/.venv/bin:$PATH" \
  uv run --directory ../.. --frozen gda \
  --user-data-root "$PLAYTEST_USER_DATA_ROOT" \
  script run res://tests/test_combat_cast_main_live.gd \
  --project "$PWD/examples/schema2/playtest" --json

export PLAYTEST_USER_DATA_ROOT="$(mktemp -d /tmp/gda-playtest-effect.XXXXXX)"
PATH="$PWD/.venv/bin:$PATH" \
  uv run --directory ../.. --frozen gda \
  --user-data-root "$PLAYTEST_USER_DATA_ROOT" \
  script run res://tests/test_periodic_effect_main_live.gd \
  --project "$PWD/examples/schema2/playtest" --json
```

Read both the command's structured result and the script's `exit_status`. The focused scripts also
cover executable discovery, maintained-document loading, same-session revisions, projection,
refusal atomicity, retry, UI input, gameplay Systems, localization, and feedback persistence.

Godot tests that write `user://` or engine logs must run serially with separate
`--user-data-root` directories. `gda` may also inspect scenes, inject input, capture screenshots,
and read runtime errors during development. It is not part of the playable runtime architecture.
