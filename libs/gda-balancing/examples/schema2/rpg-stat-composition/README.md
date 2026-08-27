# RPG Attack Damage composition

[Schema 2.x examples](../README.md) · [CLI index](../cli/README.md) · [Player app](../playtest/README.md#attack-damage-training)

This example composes Base Damage, a Level Bonus, a Weapon Bonus, and a percentage Damage Buff into
one capped Attack Damage value. The maintained [`model-source.json`](model-source.json) owns the
calculation. The maintained [`experiment.json`](experiment.json) owns the Golden attack and its
observations. CLI and Godot consume these same files.

The Golden attack uses Level 3 and Weapon Damage Bonus 8:

```text
Base Damage        20
Level Bonus        12
Weapon Bonus        8
Pre-Buff Damage    40
Damage Buff        10
Attack Damage      50
Dummy HP           70
```

Damage Buff rounds down after multiplying by 25%. Attack Damage cannot exceed 60.

## Run the CLI example

Run these commands from `libs/gda-balancing` after `uv sync`:

```bash
RUN_DIR="$(mktemp -d /tmp/gda-stat-composition.XXXXXX)"
export GDA_BALANCING_STORE_DIR="$RUN_DIR/store"
export GDA_BALANCING_ANCHOR_KEY="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

uv run gda-balancing model check \
  examples/schema2/rpg-stat-composition/model-source.json

uv run gda-balancing model build \
  examples/schema2/rpg-stat-composition/model-source.json \
  --out "$RUN_DIR/model" \
  --invocation-key 1111111111111111111111111111111111111111111111111111111111111111

uv run gda-balancing experiment check \
  examples/schema2/rpg-stat-composition/experiment.json

uv run gda-balancing experiment run \
  examples/schema2/rpg-stat-composition/experiment.json \
  --out "$RUN_DIR/run" \
  --invocation-key 2222222222222222222222222222222222222222222222222222222222222222
```

The run publishes Progression, Build, pre-Buff, Buff, Attack Damage, damage dealt, and terminal HP
Metrics. The test suite also derives the maintained round-down, exact-cap, and clamped-cap vectors
from these same files.

## Play Attack Damage Training

Launch the player-facing application:

```bash
GDA_GODOT=/absolute/path/to/Godot \
GDA_BALANCING_EXECUTABLE="$PWD/.venv/bin/gda-balancing" \
examples/schema2/playtest/scripts/run_stat_composition.sh
```

Adjust Level, Weapon Damage Bonus, and Damage Buff between attacks. Attack until the 120-HP dummy
is defeated, then save feedback. The application shows gameplay values only. It keeps revision and
artifact identifiers as opaque maintainer provenance in the saved feedback payload.

Run the real UI-to-service-to-feedback path with a writable Godot user-data root:

```bash
export PLAYTEST_USER_DATA_ROOT="$(mktemp -d /tmp/gda-playtest-stat.XXXXXX)"
PATH="$PWD/.venv/bin:$PATH" \
  uv run --directory ../.. --frozen gda \
  --user-data-root "$PLAYTEST_USER_DATA_ROOT" \
  script run res://tests/test_stat_composition_main_live.gd \
  --project "$PWD/examples/schema2/playtest" --json
```
