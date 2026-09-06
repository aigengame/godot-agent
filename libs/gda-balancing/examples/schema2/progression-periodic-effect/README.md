# Progression-derived periodic Effect

This Model composes `game.progression` with the periodic lifecycle in the current
`game.effect` definition. The Experiment assigns level 5 and damage per level 17.
The Model derives the threshold as 85 through the progression Operation and its
Formula policy; the Experiment never assigns that threshold directly.

Starting at 100 health, the snapshot policy captures `max(100 − 85, 0) = 15`.
Two scheduled ticks each subtract 15, leaving 70 health, then the Effect expires.
The Event trace records the derived threshold, Formula arguments/result, scheduled
work and committed state. The terminal Metrics require health 70 and an inactive
Effect. No Kernel law, compiler/evaluator branch or host genre dispatch is added.

From this package directory, build and run the checked-in documents:

```sh
uv run gda-balancing model build examples/schema2/progression-periodic-effect/model-source.json --out /tmp/progression-build --invocation-key 3131313131313131313131313131313131313131313131313131313131313131
uv run gda-balancing experiment run examples/schema2/progression-periodic-effect/experiment.json --out /tmp/progression-run --invocation-key 3232323232323232323232323232323232323232323232323232323232323232
```

Use unused output locations or distinct invocation keys for a new publication.
The committed Experiment binds the current build exactly. Internal version selectors
remain present at this stage; their deletion belongs to #870–#872.

The permanent public test changes only level to 4 and the expected terminal target:
the same rules derive 68, capture 32 per tick, and leave 36 health. CLI and real HTTP
execution must return identical artifacts for each input. This discriminating case
checks that the result comes from the composed rules and authored inputs.
