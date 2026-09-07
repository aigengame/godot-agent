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
RUN_DIR="$(mktemp -d /tmp/gda-progression.XXXXXX)"
export GDA_BALANCING_STORE_DIR="$RUN_DIR/store"
export GDA_BALANCING_ANCHOR_KEY="$(openssl rand -hex 32)"
uv run gda-balancing model build examples/schema2/progression-periodic-effect/model-source.json --out "$RUN_DIR/model" --invocation-key "$(openssl rand -hex 32)" | tee "$RUN_DIR/model-receipt.json"
RIR_PATH="$(jq -r '.member_locators[] | select(.logical_name == "rir-semantic-payload") | .locator' "$RUN_DIR/model-receipt.json")"
uv run gda-balancing experiment run examples/schema2/progression-periodic-effect/experiment.json --rir "$RIR_PATH" --out "$RUN_DIR/run" --invocation-key "$(openssl rand -hex 32)"
```

The Experiment binds `model.rir_semantic_identity`; `--rir` supplies the actual program read from
the Model-build Artifact-set receipt. Runtime independently admits that program. Package
requirements remain namespace strings and nominal references remain `{package, id}`. Whole-LDB
and Build-receipt provenance no longer controls execution eligibility; published Build records
retain their own exact checks.

The permanent public test changes only level to 4 and the expected terminal target:
the same rules derive 68, capture 32 per tick, and leave 36 health. CLI and real HTTP
execution must return identical artifacts for each input. This discriminating case
checks that the result comes from the composed rules and authored inputs.
