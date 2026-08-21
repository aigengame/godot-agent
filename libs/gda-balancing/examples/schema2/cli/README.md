# Standard Schema 2.x CLI examples

This directory is the command-line entry point for the maintained Standard Schema 2.x examples.
It owns navigation and CLI-specific guidance. It does not own a Model Source Package or Experiment
Specification.

Run all commands from `libs/gda-balancing`. Install the project environment first:

```bash
uv sync
```

## Tutorials

| Feature | Maintained source | CLI tutorial |
| --- | --- | --- |
| Reward selection and build replacement | [`../roguelike-reward-build/`](../roguelike-reward-build/) | [Seeded Roguelike reward and build tuning](../roguelike-reward-build/README.md) |
| Reciprocal RPG combat | [`../rpg-combat-cast/`](../rpg-combat-cast/) | [Reciprocal RPG combat through ordered Runtime Events](../rpg-combat-cast/README.md) |
| Periodic Effect timing | [`../rpg-periodic-effect/`](../rpg-periodic-effect/) | [One periodic Effect through the Runtime Event queue](../rpg-periodic-effect/README.md) |
| Neutral structured values | [`../structured-selection/`](../structured-selection/) | [Structured values through Model build and Runtime](../structured-selection/README.md) |

Each tutorial reads its linked `model-source.json` and `experiment*.json` files directly. Tutorial
commands write edited Experiments, build artifacts, receipts, traces, and Metrics to an isolated
temporary directory. Do not place copies of maintained authored inputs here.

The [Schema 2.x example index](../README.md) defines source ownership and the process for adding an
example. Player-facing applications are documented in the [playtest README](../playtest/README.md).
