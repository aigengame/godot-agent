# Reward Run playable

Reward Run is the player-facing HITL product for the maintained
`roguelike-reward-build` slice. It presents two short, comparable trials and hides the Model,
Experiment, Formula, trace, Metric, and artifact workflow from the player.

The Godot product is generated and implemented in the next delivery slice. The checked-in data
pipeline already establishes its input contract:

- `generated/reward_cases.json` contains only player-facing reward and build values.
- `generated/playtest_provenance.json` maps each opaque reference to exact formal artifacts for
  maintainers. The Godot product does not load this file.
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
