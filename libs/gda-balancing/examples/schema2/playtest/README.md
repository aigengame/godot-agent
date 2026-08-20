# RPG playtest suite

[Schema 2.x examples](../README.md) · [CLI index](../cli/README.md)

This repository-local Godot project contains three small, player-facing applications:

| Application | Player experience | Feature under test |
| --- | --- | --- |
| Reward Run | Break targets, equip a reward, and compare two builds. | Reward frequency and build impact |
| Arcane Duel | Choose a spell style and trade casts until one mage is defeated. | Damage, mana cost, opponent pressure, and combat pacing |
| Curse Timing | Compare a Dynamic Curse with a Fixed Curse across two pulses and an intervening strike. | Per-pulse recalculation and cast-time damage |

Each application uses blockout shapes, short Tween animations, mouse and keyboard controls, and a
feature-specific feedback form. A player does not need to know how `gda-balancing` compiles or
executes the maintained data.

Player-facing rules use familiar game terms and explain an outcome at the point where the player
sees it. A player must not need Standard Schema, compiler, or Runtime knowledge to understand what
an action does. Application-specific names are used only when the UI explains their meaning.

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

See [scripts/ENV.md](scripts/ENV.md) for package setup, explicit-path examples, `PATH` fallback,
and commands for all three applications.

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

1. Choose an efficient, balanced, or powerful spell style.
2. Choose a normal or strong rival.
3. Cast a spell and inspect the damage, MP cost, and red HP and blue MP bars.
4. Trade casts until one mage is defeated.
5. Play again or save feedback from the terminal screen.

Each action is one complete Experiment revision. Godot presents the returned damage, health, mana,
and explicit victory or defeat. It does not infer defeat by comparing HP in UI or host code.

### Curse Timing

1. Read the Dynamic Curse rule and locate its 85-Health damage threshold on the health bar.
2. Apply it and observe the first pulse, an intervening strike, and the recalculated second pulse.
3. Finish the first trial. The UI prepares a fresh 100-Health target before the second trial.
4. Apply the Fixed Curse. Its two pulses repeat the damage that was set when the curse was cast.
5. Compare which damage rule was easier to understand, then save feedback.

The Dynamic Curse deals damage equal to the target's Health above 85. It recalculates before each
pulse, so its current trial deals 15 damage and then 0 after the strike moves Health below the
threshold. The UI states why the second pulse deals 0; it does not present it as a missing effect.
The two curses run as independent comparison trials. The health bar visibly resets from 75 to 100
before the Fixed Curse trial, and the UI identifies the replacement as a fresh target. The Fixed
Curse then sets 15 damage when cast and repeats it on both pulses.

Both trials derive from the maintained same-time experiment and use the same visible ordering. The
Effect entrypoint is the only comparison variable. Godot presents the validated lifecycle and
damage. It does not calculate effect magnitude, damage, timing, or scheduling.

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

Each Content module reads its maintained Model Source and Experiment documents directly from the
shared feature directories. The [Schema 2.x example index](../README.md) owns the complete routing
map between maintained sources, CLI tutorials, and player applications:

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
