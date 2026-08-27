# Standard Schema 2.x examples

These maintained examples use one checked-in Model Source Package and one or more checked-in
Experiment Specifications for each feature. The CLI tutorials and player-facing Godot applications
are two entry points to those shared sources. Neither entry point owns a second copy.

## Structure and ownership

| Maintained example source | Authored inputs | CLI entry | Player entry |
| --- | --- | --- | --- |
| [`roguelike-reward-build/`](roguelike-reward-build/) | `model-source.json`, `experiment.json` | [Reward and build tutorial](roguelike-reward-build/README.md) | [Reward Run](playtest/README.md#reward-run) |
| [`rpg-combat-cast/`](rpg-combat-cast/) | `model-source.json`, `experiment.json`, `multi-time-experiment.json` | [RPG combat tutorial](rpg-combat-cast/README.md) | [Arcane Duel](playtest/README.md#arcane-duel) |
| [`rpg-periodic-effect/`](rpg-periodic-effect/) | `model-source.json`, `experiment.json`, `same-time-experiment.json` | [Periodic Effect tutorial](rpg-periodic-effect/README.md) | [Curse Timing](playtest/README.md#curse-timing) |
| [`rpg-stat-composition/`](rpg-stat-composition/) | `model-source.json`, `experiment.json` | [Attack Damage composition tutorial](rpg-stat-composition/README.md) | [Attack Damage Training](playtest/README.md#attack-damage-training) |
| [`structured-selection/`](structured-selection/) | `model-source.json`, `experiment.json` | [Structured selection tutorial](structured-selection/README.md) | Not required for this conformance-focused example |

The feature directories own the maintained authored inputs and explain their semantics. The
[`cli/`](cli/) directory is the command-line entry point. The [`playtest/`](playtest/) directory is
the player-facing Godot project.

## One authority, two entry points

- Keep each maintained Model Source Package and Experiment Specification in its feature directory.
- Let CLI tutorials and playtest Content read those files directly. Do not copy them into `cli/` or
  `playtest/`.
- A player action can derive a complete immutable Experiment revision from a maintained Experiment.
  Such a revision is a runtime value, not another checked-in authority.
- Keep a named tuning preset in one place. If both CLI and playtest need the same preset, express it
  as a shared Experiment Specification instead of repeating its values in both entry points.
- Write generated artifacts and temporary edited Experiments outside this directory, as the CLI
  tutorials demonstrate with temporary run directories.

## Add an example

1. Add one feature directory with its maintained Model Source Package, Experiment Specifications,
   and a README that explains the demonstrated behavior.
2. Prove the source through a deterministic public execution path. The CLI is the usual first
   tracer, but a polished CLI tutorial does not need to block the first playable vertical slice.
3. Add a playtest application only when the claim needs player interaction, perception, or
   feedback. A conformance-focused example can remain CLI-only.
4. Add the new entry to this table and extend the source-authority structure test.

See the [CLI index](cli/README.md) for maintainer workflows and the [playtest
README](playtest/README.md) for player applications.
