# RPG combat-cast tuning loop

This is the first bounded Standard Schema 2.0 product-feedback slice. It contains an exact
[`model-source.json`](model-source.json) and its companion
[`experiment.json`](experiment.json) for one deterministic `rpg.combat.cast-v1` event.

Run the loop from `libs/gda-balancing` with one persistent local store:

```sh
export GDA_BALANCING_STORE_DIR=/tmp/gda-balancing-rpg-cast
export GDA_BALANCING_ANCHOR_KEY=a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5

uv run gda-balancing model build \
  examples/schema2/rpg-combat-cast/model-source.json \
  --out /tmp/rpg-cast-model.json \
  --invocation-key 1111111111111111111111111111111111111111111111111111111111111111

uv run gda-balancing experiment check \
  examples/schema2/rpg-combat-cast/experiment.json

uv run gda-balancing experiment run \
  examples/schema2/rpg-combat-cast/experiment.json \
  --out /tmp/rpg-cast-evaluation.json \
  --invocation-key 2222222222222222222222222222222222222222222222222222222222222222
```

Inspect the returned member locators for `event-trace`, `snapshot-series`, and
`metric-dataset`. With the committed seed and inputs, the authored `base_damage` value of `24`
produces `damage_dealt = 18`.

To exercise the designer iteration, copy `experiment.json`, change the scenario's authored
`base_damage` value from `24` to `40`, and run the copy with a new output and Invocation key. The
Experiment identity, trace, and Metric dataset change, while the exact Model binding remains
fixed; `damage_dealt` increases in the explainable direction.

This example validates one public configure/build/check/run/inspect/edit/rerun loop. It does not
close an RPG coverage row or establish general RPG or Roguelike support.
