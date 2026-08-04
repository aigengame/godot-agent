# One periodic Effect through the ordinary Runtime schedule

This tutorial drives one bounded periodic Effect through the public Standard Schema 2.x path:

```text
Model Source Formula + game.effect binding
    |
    v
Model build -> Package Lock + RIR + Model explanation
    |
    v
Experiment apply Event -> scheduled tick/tick/expire Events
    |
    v
Event trace + committed Snapshots + Metrics
```

The example demonstrates two magnitude-timing policies over the same authored Formula:

- `snapshot`: evaluate once during apply and schedule both ticks with the captured magnitude;
- `live`: evaluate at each tick against that Event's pre-Event committed Snapshot.

The Effect uses Runtime logical time and the ordinary Event queue. It has no Effect-specific loop,
wall-clock timer, evaluator callback, or repeated-scenario substitute. The `game.effect@1.0.0`
Package Release owns this exact bounded variant: duration `3`, period `1`, ticks at logical times
`1` and `2`, and expiry at `3`. Those values are a closed package contract, not authored
Experiment timing knobs.

This slice does not claim immunity, stacking, dispel, buildup, multiple contributors, same-Event
request precedence, complete buff/debuff coverage, Replay, or Evidence.

## 1. Prepare an isolated run

Prerequisites are `uv`, `jq`, and `openssl`. Run from `libs/gda-balancing`:

```bash
uv sync

export GDA_BALANCING_TUTORIAL_ROOT="$(
  mktemp -d /tmp/gda-balancing-periodic-effect.XXXXXX
)"
export GDA_BALANCING_STORE_DIR="$GDA_BALANCING_TUTORIAL_ROOT/store"
export GDA_BALANCING_ANCHOR_KEY="$(openssl rand -hex 32)"
export MODEL_BUILD_INVOCATION_KEY="$(openssl rand -hex 32)"
export EXPERIMENT_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
```

Keep the anchor key stable for this store. Reusing an Invocation key with byte-identical input
recovers the committed result. Generate a new key after changing Model Source or Experiment input.

## 2. Read the authored Model and package boundary

The permanent files are:

- `model-source.json` — state, the `periodic-magnitude` Formula, exact snapshot/live Formula-slot
  bindings, and Model entrypoints;
- `experiment.json` — one snapshot-policy lifecycle;
- `same-time-experiment.json` — one live tick sharing logical time `1` with ordinary combat.

Inspect the Formula and bindings:

```bash
jq '.modules[0].formulas[] | select(.id == "periodic-magnitude")' \
  examples/schema2/rpg-periodic-effect/model-source.json

jq '.formula_bindings[] | select(.formula.id == "periodic-magnitude")' \
  examples/schema2/rpg-periodic-effect/model-source.json
```

The Formula computes:

```text
let raw_magnitude = current_value - threshold;
let magnitude = floor_zero(raw_magnitude);
magnitude
```

Model Source owns that pure policy and its exact Operation-slot bindings. The package owns when the
slot is evaluated and how the result participates in apply/tick/expiry. Runtime owns only generic
ordering, scheduling legality, atomic commit, budgets, RNG and Snapshot laws.

## 3. Build and inspect the exact Model

Build and save the artifact-set receipt:

```bash
export MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/model-set-receipt.json"

uv run gda-balancing model build \
  examples/schema2/rpg-periodic-effect/model-source.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json" \
  --invocation-key "$MODEL_BUILD_INVOCATION_KEY" \
  | tee "$MODEL_SET_RECEIPT"
```

Inspect the stored explanation and exact RIR:

```bash
uv run gda-balancing model inspect \
  "$MODEL_SET_RECEIPT" \
  --format indented \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"

export BUILD_RECORD_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "build-receipt")
    | .locator' "$MODEL_SET_RECEIPT"
)"
export RIR_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "rir-semantic-payload")
    | .locator' "$MODEL_SET_RECEIPT"
)"

jq '.formula_explanations[]
  | select(.id == "periodic-magnitude")
  | {id, identity, expression, evaluation_sites, closure}' \
  "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"

jq '.selected_semantics.operations[].definition
  | select(.id | startswith("game.effect."))
  | {id, effects, resource_bounds, extensions}' "$RIR_PATH"
```

The RIR exposes `game.effect.periodic` beside ordinary Runtime instructions. Snapshot apply
contains three schedule nodes; live apply schedules tick Events whose own Operation carries the
Formula evaluation site. No host-only Effect descriptor or arithmetic table exists.

## 4. Bind and run the snapshot lifecycle

The checked-in Experiment files use zero identities deliberately: a runnable Experiment must bind
the exact build produced in the current artifact store. Define one binding helper:

```bash
bind_experiment() {
  build_record="$1"
  source_experiment="$2"
  destination="$3"
  jq --slurpfile build "$build_record" '
    .kernel_identity = $build[0].kernel_identity
    | .language_bundle_identity = $build[0].language_bundle_identity
    | .model = {
        source_identity: $build[0].source_identity,
        build_receipt_identity: $build[0].content_identity,
        resolved_model_identity: $build[0].resolved_model_identity,
        package_lock_identity: $build[0].package_lock_identity,
        rir_identity: $build[0].rir_identity
      }
  ' "$source_experiment" > "$destination"
}

export SNAPSHOT_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/snapshot-experiment.json"
bind_experiment \
  "$BUILD_RECORD_PATH" \
  examples/schema2/rpg-periodic-effect/experiment.json \
  "$SNAPSHOT_EXPERIMENT"
```

Check, run and retain the result receipt:

```bash
uv run gda-balancing experiment check "$SNAPSHOT_EXPERIMENT" | jq .

export EXPERIMENT_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-set-receipt.json"
uv run gda-balancing experiment run \
  "$SNAPSHOT_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/evaluation-run.json" \
  --invocation-key "$EXPERIMENT_RUN_INVOCATION_KEY" \
  | tee "$EXPERIMENT_SET_RECEIPT"
```

Resolve the public artifacts:

```bash
export EVENT_TRACE_PATH="$(
  jq -r '.member_locators[] | select(.logical_name == "event-trace") | .locator' \
    "$EXPERIMENT_SET_RECEIPT"
)"
export SNAPSHOT_PATH="$(
  jq -r '.member_locators[] | select(.logical_name == "snapshot-series") | .locator' \
    "$EXPERIMENT_SET_RECEIPT"
)"
export METRIC_PATH="$(
  jq -r '.member_locators[] | select(.logical_name == "metric-dataset") | .locator' \
    "$EXPERIMENT_SET_RECEIPT"
)"
export REPRODUCTION_PATH="$(
  jq -r '.member_locators[] | select(.logical_name == "reproduction-receipt") | .locator' \
    "$EXPERIMENT_SET_RECEIPT"
)"
```

Inspect the scheduled lifecycle and Formula evidence:

```bash
jq '.events[]
  | select(.ordering_key.phase == "transition")
  | {
      event_id,
      parent_event_id,
      schedule_call_site_identity,
      ordering_key,
      operation,
      entrypoint,
      formula_evaluations,
      schedules,
      rng_draws,
      state_before,
      state_after,
      snapshot_before_identity,
      snapshot_after_identity
    }' "$EVENT_TRACE_PATH"

jq '.snapshots[] | {index, logical_time, event_id, snapshot_identity, values}' \
  "$SNAPSHOT_PATH"

jq '.samples[] | {metric, value, logical_time, snapshot_identity, within_target}' \
  "$METRIC_PATH"

jq . "$REPRODUCTION_PATH"
```

The transition sequence is `apply -> tick -> tick -> expire` at logical times `0, 1, 2, 3`.
Snapshot policy records one Formula evaluation during apply with result `15`; both scheduled tick
Events carry that captured magnitude. Health changes `100 -> 85 -> 70`, expiry changes
`effect_active` from `1` to `0`, and the same positive Effect-instance id appears throughout.

## 5. Compare live and snapshot timing at the same logical time

Bind the companion Experiment and run its default live/combat-first order:

```bash
export SAME_TIME_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/same-time-live.json"
bind_experiment \
  "$BUILD_RECORD_PATH" \
  examples/schema2/rpg-periodic-effect/same-time-experiment.json \
  "$SAME_TIME_EXPERIMENT"

export SAME_TIME_INVOCATION_KEY="$(openssl rand -hex 32)"
uv run gda-balancing experiment run \
  "$SAME_TIME_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/same-time-live-run.json" \
  --invocation-key "$SAME_TIME_INVOCATION_KEY" \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/same-time-live-receipt.json"
```

At logical time `1`, the ordinary combat root was admitted before the scheduled live tick and both
have priority `0`, so combat commits first. The live tick reads health `90`, computes magnitude
`5`, and the second tick computes `0`; terminal health is `85`.

Make only the combat priority lower:

```bash
export TICK_FIRST_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/same-time-tick-first.json"
jq '
  .id = "example.rpg-periodic-effect.live-tick-first"
  | .scenarios[0].event_plan[1].priority = -1
' "$SAME_TIME_EXPERIMENT" > "$TICK_FIRST_EXPERIMENT"

export TICK_FIRST_INVOCATION_KEY="$(openssl rand -hex 32)"
uv run gda-balancing experiment run \
  "$TICK_FIRST_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/same-time-tick-first-run.json" \
  --invocation-key "$TICK_FIRST_INVOCATION_KEY" \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/same-time-tick-first-receipt.json"
```

With tick priority `0` and combat priority `-1`, the tick runs first against health `100`, computes
`15`, then combat commits `10`; terminal health is `75`. Changing the apply entrypoint to
`effect.apply-snapshot-periodic` evaluates `15` once at logical time `0`, so either priority order
ends at health `60`. Run that policy explicitly:

```bash
export SNAPSHOT_SAME_TIME_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/same-time-snapshot.json"
jq '
  .id = "example.rpg-periodic-effect.snapshot-combat-first"
  | .scenarios[0].event_plan[0].entrypoint = "effect.apply-snapshot-periodic"
' "$SAME_TIME_EXPERIMENT" > "$SNAPSHOT_SAME_TIME_EXPERIMENT"

export SNAPSHOT_SAME_TIME_KEY="$(openssl rand -hex 32)"
uv run gda-balancing experiment run \
  "$SNAPSHOT_SAME_TIME_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/same-time-snapshot-run.json" \
  --invocation-key "$SNAPSHOT_SAME_TIME_KEY"
```

Priority changes ordering; it never changes the fixed phase table or exposes another Event's
buffered writes.

## 6. Edit the authored Formula and rerun

Create a tuned Model Source that reverses the subtraction and updates the adjacent canonical
expression in the same edit:

```bash
export TUNED_SOURCE="$GDA_BALANCING_TUTORIAL_ROOT/model-source-tuned.json"
jq '
  (.modules[0].formulas[] | select(.id == "periodic-magnitude")) |= (
    .body.nodes[0].arguments[0].operand.parameter = "threshold"
    | .body.nodes[0].arguments[1].operand.parameter = "current_value"
    | .expression = "let raw_magnitude = threshold - current_value;\nlet magnitude = floor_zero(raw_magnitude);\nmagnitude"
  )
' examples/schema2/rpg-periodic-effect/model-source.json > "$TUNED_SOURCE"

export TUNED_BUILD_KEY="$(openssl rand -hex 32)"
export TUNED_MODEL_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/tuned-model-receipt.json"
uv run gda-balancing model build \
  "$TUNED_SOURCE" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/tuned-model.json" \
  --invocation-key "$TUNED_BUILD_KEY" \
  | tee "$TUNED_MODEL_RECEIPT"
```

Resolve its build record and bind a new Experiment. Widen only the tutorial target so both values
are accepted:

```bash
export TUNED_BUILD_RECORD="$(
  jq -r '.member_locators[] | select(.logical_name == "build-receipt") | .locator' \
    "$TUNED_MODEL_RECEIPT"
)"
export TUNED_EXPERIMENT_BASE="$GDA_BALANCING_TUTORIAL_ROOT/tuned-experiment-base.json"
export TUNED_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/tuned-experiment.json"

bind_experiment \
  "$TUNED_BUILD_RECORD" \
  examples/schema2/rpg-periodic-effect/experiment.json \
  "$TUNED_EXPERIMENT_BASE"

jq '
  .id = "example.rpg-periodic-effect.snapshot-tuned"
  | .metrics[0].target = {minimum: 0, maximum: 100}
' "$TUNED_EXPERIMENT_BASE" > "$TUNED_EXPERIMENT"

export TUNED_RUN_KEY="$(openssl rand -hex 32)"
uv run gda-balancing experiment run \
  "$TUNED_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/tuned-run.json" \
  --invocation-key "$TUNED_RUN_KEY"
```

The tuned Formula returns `0`, so terminal health remains `100`. Source, Formula, RIR, Resolved
Model, exact Experiment, trace and Metric identities change. Kernel, LDB, Package Lock, package
Operations, compiler/evaluator dispatch and unrelated declarations remain fixed. Running the old
exact Experiment against the new Model is not a rebind; it must refuse until a new exact
Experiment is authored.

## 7. Why logical time is not an Effect loop or repeated scenarios

One Runtime queue is required because the tick and ordinary combat Event must observe each other's
committed results. A private fixed-tick Effect loop would create another ordering authority and
could expose different state. Repeating Experiment scenarios would be even less equivalent: every
scenario has its own Snapshot 0, queue, RNG state and replication identity, so no scenario can be
the next tick of another scenario.

The bounded package contract schedules ordinary child Events. Runtime orders them with every other
Event by logical time, phase, priority and enqueue sequence, commits each transaction atomically,
and creates one Snapshot boundary after success. That is the complete time-advancement model used
by this example.

## 8. Product and architecture review

The human owner should run the snapshot, same-time live/tick-first and tuned-Formula paths, then
record `accept`, `accept with explicit conditions`, or `reopen` on issue #596.

Review:

- whether Formula ownership and snapshot/live timing are understandable;
- whether scheduled child ids, parent links, Effect-instance identity and ordering are inspectable;
- whether state changes are clear across Event trace, Snapshot series and Metrics;
- whether the Formula edit/rebind feedback loop is usable;
- whether any discovered behavior belongs in Kernel, `game.effect`, Model Source, Experiment, or
  only this authored example.

Do not close broader Effect, Replay, Evidence, RPG or Genre coverage from this tutorial.

## Troubleshooting

- Keys must contain exactly 64 lowercase hexadecimal digits.
- Keep the same store and anchor key for build and run so exact Model artifacts remain resolvable.
- `invocation_key_conflict` means that key already names different canonical input.
- A zero-identity checked-in Experiment must be rebound to the current Build receipt before use.
- `language.formula_notation_mismatch` means the Formula body and expression were not edited as one
  canonical pair.
- Inspect receipt `member_locators`; `--out` is only a convenience copy, not the complete set.
