# One periodic Effect through the Runtime Event queue

This tutorial runs one bounded periodic Effect through the public Standard Schema 2.x path:

```text
Model Source Package + game.effect Formula binding
    |
    v
model build -> complete Model artifact set
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

The Effect uses Runtime logical time and the Runtime Event queue. It does not use an Effect-specific
loop, wall-clock timer, evaluator callback, or repeated scenarios.

The `game.effect@1.0.0` Package Release defines this bounded variant. Its duration is `3`, and its
period is `1`. It schedules ticks at logical times `1` and `2`, and it expires at `3`. The
Experiment cannot change these package-owned values.

This example does not define immunity, stacking, dispel, buildup, multiple contributors, same-Event
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

Keep the anchor key stable for this store. Repeat a command with the same Invocation key and
byte-identical input to recover the committed result. After you change the Model Source Package or
Experiment input, generate a new Invocation key.

## 2. Read the authored Model and package boundary

The checked-in files are:

- `model-source.json` — state, the `periodic-magnitude` Formula, exact snapshot/live Formula-slot
  bindings, and Model entrypoints;
- `experiment.json` — one snapshot-policy lifecycle;
- `same-time-experiment.json` — one live tick sharing logical time `1` with a combat Event.

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

The Model Source Package owns the pure Formula policy and its exact Operation-slot bindings. The
`game.effect` Package Release defines when Runtime evaluates the slot. It also defines how the
result participates in apply, tick, and expiry Operations. Runtime owns generic ordering,
scheduling legality, atomic commit, budgets, RNG, and Snapshot laws.

## 3. Build and inspect the Model artifact set

Build and save the artifact-set receipt:

```bash
export MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/model-set-receipt.json"

uv run gda-balancing model build \
  examples/schema2/rpg-periodic-effect/model-source.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json" \
  --invocation-key "$MODEL_BUILD_INVOCATION_KEY" \
  | tee "$MODEL_SET_RECEIPT"
```

Inspect the stored Model explanation and RIR semantic payload:

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

The RIR semantic payload contains `game.effect.periodic` with the Runtime instructions. The
snapshot apply Operation contains three schedule nodes. The live apply Operation schedules tick
Events. Each live tick Operation contains its Formula evaluation site. Host code does not provide
an Effect descriptor or arithmetic table.

## 4. Run the snapshot lifecycle

The checked-in Experiment files bind the identities of the checked-in Model Source Package. Use the
snapshot Experiment directly:

```bash
export SNAPSHOT_EXPERIMENT=examples/schema2/rpg-periodic-effect/experiment.json
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

The transition sequence is `apply -> tick -> tick -> expire`. The logical times are `0`, `1`, `2`,
and `3`. The snapshot policy records one Formula evaluation during apply. Its result is `15`.
Both scheduled tick Events carry this captured magnitude.

Health changes from `100` to `85` and then to `70`. Expiry changes `effect_active` from `1` to `0`.
The same positive Effect instance identity appears in all lifecycle Events.

## 5. Compare live and snapshot timing at the same logical time

Run the companion Experiment in its default live/combat-first order:

```bash
export SAME_TIME_EXPERIMENT=examples/schema2/rpg-periodic-effect/same-time-experiment.json

export SAME_TIME_INVOCATION_KEY="$(openssl rand -hex 32)"
uv run gda-balancing experiment run \
  "$SAME_TIME_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/same-time-live-run.json" \
  --invocation-key "$SAME_TIME_INVOCATION_KEY" \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/same-time-live-receipt.json"
```

Runtime admits the combat root before the apply Event schedules the live tick. Both Events have
priority `0` at logical time `1`. Runtime therefore dispatches and commits the combat Event first.

The live tick reads health `90` and calculates a magnitude of `5`. The second tick calculates `0`.
The terminal health and the `target_health_remaining` Metric value are both `85`.

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

The tick has priority `0`, and the combat Event has priority `-1`. Runtime therefore dispatches the
tick first. The tick reads health `100` and calculates `15`. The combat Event then commits `10`
damage. The terminal health and the `target_health_remaining` Metric value are both `75`.

The `effect.apply-snapshot-periodic` entrypoint evaluates `15` once at logical time `0`. Both
priority orders then produce terminal health `60`. Run that policy explicitly:

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

Priority changes Event order. It does not change the fixed phase table. It also does not expose an
Event's buffered writes to another Event.

## 6. Edit the authored Formula and rerun

Create a tuned Model Source Package. Reverse the subtraction and update the adjacent canonical
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

Resolve the new Build receipt and bind a new Experiment. Widen only the tutorial target so that it
accepts both values:

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

The tuned Formula returns `0`. Thus, terminal health remains `100`.

The edit changes the Model Source Package, Formula, RIR semantic payload, and Resolved Model
identities. It also changes the exact Experiment, Event trace, and Metric identities. It does not
change the Kernel, LDB, Package Lock, package Operations, compiler dispatch, or evaluator dispatch.

The old Experiment still binds the old Resolved Model. It remains valid only for that exact build.
Create a new Experiment from the new Build receipt before you run the tuned Model. Experiment
admission refuses an incoherent mix of old and new identities.

## 7. Why logical time is not an Effect loop or repeated scenarios

The tick and combat Event must observe each other's committed results. Therefore, they must use one
Runtime Event queue. A private fixed-tick Effect loop would create a second ordering authority and
could expose different state.

Repeated Experiment scenarios are not equivalent to scheduled ticks. Each scenario has its own
Snapshot 0, Event queue, RNG state, and replication identity. A scenario cannot be the next tick of
another scenario.

The `game.effect` Package Release schedules ordinary child Events. Runtime orders them with all
other Events. It uses logical time, phase, priority, and enqueue sequence. Runtime commits each
transaction atomically and creates a Snapshot after each success. This example uses no other
time-advancement mechanism.

## 8. Validation scope

Automated end-to-end tests validate the snapshot lifecycle, live timing, same-logical-time order,
Formula edit, exact Experiment binding, refusal paths, recovery, and independent evaluation.
[Periodic Effect dogfooding](../../../docs/ARCHITECTURE.md#129-periodic-effect-dogfooding) records the
accepted architecture observations and limits.
This README explains how to run and inspect those behaviors. It does not define their architecture.

## Troubleshooting

- Keys must contain exactly 64 lowercase hexadecimal digits.
- Use the same store and anchor key for build and run. Runtime can then resolve the exact build
  artifacts.
- `invocation_key_conflict` means that the key already identifies different canonical input.
- Checked-in Experiments bind the checked-in Model Source Package. After you edit that source,
  create a new Experiment from the new Build receipt.
- `language.formula_notation_mismatch` means that the Formula body and expression are not one
  canonical pair.
- Inspect the receipt's `member_locators`. The `--out` file is a convenience copy, not the complete
  artifact set.
