# Seeded Roguelike reward and build tuning

This tutorial runs one reward-selection and build-replacement loop through the public Standard
Schema 2.x path:

```text
Model Source + Formula binding + reward/build state
    |
    v
model check/build/inspect -> exact Model artifact set
    |
    v
Experiment reward Event -> build Event
    |
    v
Event trace + committed Snapshots + reward/build Metrics
```

The `game.generation@1.0.0` Package Release owns the seeded reward policy. The
`game.build@1.0.0` Package Release owns the atomic build replacement. The Model Source owns the
`rare-threshold` Formula and its exact Operation-slot binding. The Experiment owns the seed,
ordered reward options, no declared empty-pool fallback, authored policy state, build plans, initial
state, and Metrics.
The two Operations validate the relationships among those authored values before they commit
state or publish a result.

Host code does not select rewards, resolve conflicts, supply a fallback, or dispatch by genre.
This example closes no Tracer, RPG, Roguelike, Variant, Extension, Replay, Evidence,
template-support, Core Extension Invariance, or cross-genre claim.

## 1. Prepare an isolated run

Prerequisites are `uv`, `jq`, and `openssl`. Run from `libs/gda-balancing`:

```bash
uv sync

export GDA_BALANCING_TUTORIAL_ROOT="$(
  mktemp -d /tmp/gda-balancing-roguelike-reward-build.XXXXXX
)"
export GDA_BALANCING_STORE_DIR="$GDA_BALANCING_TUTORIAL_ROOT/store"
export GDA_BALANCING_ANCHOR_KEY="$(openssl rand -hex 32)"
export MODEL_BUILD_INVOCATION_KEY="$(openssl rand -hex 32)"
export EXPERIMENT_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
```

Keep the anchor key stable for this store. Use a new Invocation key after you change an input.

## 2. Inspect the authored boundary

The checked-in artifacts are:

- `model-source.json` — exact package requirements, Symbols, two entrypoints, and the Formula
  binding;
- `experiment.json` — seed `20260812`, stream `reward`, ordered reward options, an empty
  `no_reward_on_empty` declaration, build plans, initial state, Event plan, and Metrics.

Inspect the Formula, binding, and entrypoints:

```bash
jq '.modules[0].formulas[] | select(.id == "rare-threshold")' \
  examples/schema2/roguelike-reward-build/model-source.json

jq '.formula_bindings[]
  | select(.site.slot == "rare-threshold-policy")' \
  examples/schema2/roguelike-reward-build/model-source.json

jq '.entrypoints[] | {id, operation, arguments, result}' \
  examples/schema2/roguelike-reward-build/model-source.json
```

The reward pool has two eligible options in this order:

1. `steady_guard`, which has rarity `common`;
2. `volatile_crown`, which has rarity `rare`.

`RewardPool` can carry up to 16 `RewardOption` values. Each option pairs one candidate with its
authored selection data. `game.generation.select-reward-v1` uses a binary selector in this release:
it considers only indexes `0` and `1`. Later options do not participate.

The Runtime node vocabulary does not construct `RewardSelection` or `BuildDecision` Record values.
The Experiment therefore authors each paired selection, the build decisions, and the next states.
The Operations validate these relationships before they commit.

The Formula returns the authored `rare_weight`. The `game.generation.select-reward-v1` Operation
uses that value as its rare threshold. The build Operation consumes the resulting typed
`RewardSelection`; it does not sample again.

## 3. Check, build, and inspect the Model

Check the source without publishing artifacts:

```bash
uv run gda-balancing model check \
  examples/schema2/roguelike-reward-build/model-source.json \
  | jq .
```

Build the exact Model and retain its artifact-set receipt:

```bash
export MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/model-set-receipt.json"

uv run gda-balancing model build \
  examples/schema2/roguelike-reward-build/model-source.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json" \
  --invocation-key "$MODEL_BUILD_INVOCATION_KEY" \
  | tee "$MODEL_SET_RECEIPT"
```

Inspect the mandatory Model explanation and the selected RIR semantics:

```bash
export MODEL_EXPLANATION="$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"

uv run gda-balancing model inspect \
  "$MODEL_SET_RECEIPT" \
  --format indented \
  | tee "$MODEL_EXPLANATION"

export RIR_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "rir-semantic-payload")
    | .locator' "$MODEL_SET_RECEIPT"
)"

jq '.formula_explanations[]
  | select(.id == "rare-threshold")
  | {id, identity, expression, evaluation_sites}' \
  "$MODEL_EXPLANATION"

jq '.formula_bindings[]
  | select(.site.slot == "rare-threshold-policy")
  | {formula, site, arguments}' "$RIR_PATH"

jq '.selected_semantics.operations[].definition
  | select(.id == "game.build.replace-reward-v1")
  | {id, outcomes, effects, resource_bounds}' "$RIR_PATH"
```

The explanation binds the exact Formula identity to the exact package Operation slot. The RIR
contains the admitted reward and build Operations. It contains no host callback or genre dispatch.

## 4. Run the baseline configuration

The checked-in Experiment binds the exact Model build that section 3 produces from the checked-in
Model Source. Check and run it:

```bash
export BASELINE_EXPERIMENT=examples/schema2/roguelike-reward-build/experiment.json

uv run gda-balancing experiment check "$BASELINE_EXPERIMENT" | jq .

export BASELINE_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/baseline-set-receipt.json"
uv run gda-balancing experiment run \
  "$BASELINE_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/baseline-evaluation.json" \
  --invocation-key "$EXPERIMENT_RUN_INVOCATION_KEY" \
  | tee "$BASELINE_SET_RECEIPT"
```

Resolve the public artifacts:

```bash
export BASELINE_TRACE="$(
  jq -r '.member_locators[] | select(.logical_name == "event-trace") | .locator' \
    "$BASELINE_SET_RECEIPT"
)"
export BASELINE_METRICS="$(
  jq -r '.member_locators[] | select(.logical_name == "metric-dataset") | .locator' \
    "$BASELINE_SET_RECEIPT"
)"
export BASELINE_REPRODUCTION="$(
  jq -r '.member_locators[] | select(.logical_name == "reproduction-receipt") | .locator' \
    "$BASELINE_SET_RECEIPT"
)"
```

Inspect the RNG draw, policy, reward disposition, and build replacement:

```bash
jq '{seed_algorithm, seed_value}' "$BASELINE_REPRODUCTION"

jq '.events[0].facts[]
  | select(.name == "reward_pool")
  | .value.value
  | {options, no_reward_on_empty, policy_before}' "$BASELINE_TRACE"

jq '.events[]
  | select(.operation != null)
  | {
      root_event_ref,
      operation,
      outcome,
      rng_draws,
      formula_evaluations,
      facts,
      state_before,
      state_after
    }' "$BASELINE_TRACE"

jq '.samples[] | {metric, value, snapshot_identity}' "$BASELINE_METRICS"
```

The seed and stream produce draw index `0`, candidate hex `cb822c763bee22e2`, and value `3`.
With `rare_weight = 5`, the reward Event selects `volatile_crown`. The build Event atomically
replaces `starter_blade` with `volatile_crown`. The public Metrics are:

- `reward_score = 80`;
- `build_score = 90`.

## 5. Tune one authored value and rerun

Change only `rare_weight` from `5` to `2`. The Model, Package Lock, RIR, evaluator, seed, stream,
option order, and build plans stay unchanged.

This one-field edit works because `rare_weight` is not repeated in a `RewardOption`. Editing a
candidate field, such as `reward_score`, also requires the same change in that option's selection.
Otherwise, the reward Event returns the typed `game.generation.invalid_option` refusal and rolls
back.

Create and run the tuned Experiment:

```bash
export TUNED_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/tuned-experiment.json"

jq '
  .id = "roguelike.reward-build-feedback.lower-rare-weight"
  | (.scenarios[0].assignments[]
      | select(.target.name == "rare_weight")
      | .value) = 2
' "$BASELINE_EXPERIMENT" > "$TUNED_EXPERIMENT"

uv run gda-balancing experiment check "$TUNED_EXPERIMENT" | jq .

export TUNED_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/tuned-set-receipt.json"
uv run gda-balancing experiment run \
  "$TUNED_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/tuned-evaluation.json" \
  --invocation-key "$(openssl rand -hex 32)" \
  | tee "$TUNED_SET_RECEIPT"

export TUNED_TRACE="$(
  jq -r '.member_locators[] | select(.logical_name == "event-trace") | .locator' \
    "$TUNED_SET_RECEIPT"
)"
export TUNED_METRICS="$(
  jq -r '.member_locators[] | select(.logical_name == "metric-dataset") | .locator' \
    "$TUNED_SET_RECEIPT"
)"

jq '.events[]
  | select(.operation != null)
  | {root_event_ref, outcome, rng_draws, facts}' "$TUNED_TRACE"
jq '.samples[] | {metric, value}' "$TUNED_METRICS"
```

The RNG draw is still `3`. The lower threshold now selects `steady_guard`, and the build Event
replaces the slot with `steady_guard`. The Metrics change to `reward_score = 20` and
`build_score = 30`. This change is explainable from one authored value and the unchanged draw.

## 6. Change the Formula binding

The slot has an explicit one-step resource bound. This example changes the binding without
expanding that package contract. Add an equivalent Formula and bind the slot to it:

```bash
export EDITED_MODEL_SOURCE="$GDA_BALANCING_TUTORIAL_ROOT/model-source-rebound.json"

jq '
  .manifest.version = "1.1.0"
  | (.modules[0].formulas[0]
      | .id = "alternate-rare-threshold") as $alternate
  | .modules[0].formulas += [$alternate]
  | .formula_bindings[0].formula.id = $alternate.id
' examples/schema2/roguelike-reward-build/model-source.json \
  > "$EDITED_MODEL_SOURCE"

export EDITED_MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/edited-model-set-receipt.json"
uv run gda-balancing model build \
  "$EDITED_MODEL_SOURCE" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/edited-resolved-model.json" \
  --invocation-key "$(openssl rand -hex 32)" \
  | tee "$EDITED_MODEL_SET_RECEIPT"

export EDITED_BUILD_RECEIPT="$(
  jq -r '.member_locators[] | select(.logical_name == "build-receipt") | .locator' \
    "$EDITED_MODEL_SET_RECEIPT"
)"
```

A partial rebind is refused. It cannot combine the new Source identity with the old exact Model
identities:

```bash
export STALE_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/stale-experiment.json"

jq --slurpfile build "$EDITED_BUILD_RECEIPT" '
  .model.source_identity = $build[0].source_identity
' "$BASELINE_EXPERIMENT" > "$STALE_EXPERIMENT"

uv run gda-balancing experiment check "$STALE_EXPERIMENT" | jq .
```

The command returns `language.resolved_authority_mismatch` at `/model`. Rebind every exact Model
member, then check and run the new Experiment:

```bash
export REBOUND_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/rebound-experiment.json"

jq --slurpfile build "$EDITED_BUILD_RECEIPT" '
  .id = "roguelike.reward-build-feedback.alternate-formula"
  | .kernel_identity = $build[0].kernel_identity
  | .language_bundle_identity = $build[0].language_bundle_identity
  | .model = {
      source_identity: $build[0].source_identity,
      build_receipt_identity: $build[0].content_identity,
      resolved_model_identity: $build[0].resolved_model_identity,
      package_lock_identity: $build[0].package_lock_identity,
      rir_identity: $build[0].rir_identity
    }
' "$BASELINE_EXPERIMENT" > "$REBOUND_EXPERIMENT"

uv run gda-balancing experiment check "$REBOUND_EXPERIMENT" | jq .
uv run gda-balancing experiment run \
  "$REBOUND_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/rebound-evaluation.json" \
  --invocation-key "$(openssl rand -hex 32)" \
  | jq .
```

The exact Source, RIR, Resolved Model, Build receipt, and Experiment identities change. The Kernel,
LDB, Package Lock, Operation slot, and evaluator dispatch do not change.

## 7. Inspect failure and alternative outcomes

The maintained tests drive these mutations through the public commands:

| Case | Public result |
|---|---|
| Empty `options` and empty `no_reward_on_empty` | `game.generation.selection_exhausted`; the terminal audit proves rollback |
| Empty `options` with one valid no-reward fallback | reward `no-reward` followed by build `no-reward`; neither Event consumes RNG |
| A fallback disposition or policy state contradicts its pool | `game.generation.invalid_fallback`; the terminal audit proves rollback |
| Candidate, selection, score, or policy fields in one option contradict each other | `game.generation.invalid_option`; the terminal audit proves rollback |
| A coherent build plan has constraint `conflict` | `build-conflict` gameplay alternative; all provisional writes roll back |
| Build state, next state, decision, or score fields contradict each other | `game.build.invalid_plan`; the terminal audit proves rollback |
| Unknown reward disposition or build constraint | `language.structured_value_unknown_enum` during `experiment check` |

Run the focused tests:

```bash
uv run pytest tests/test_schema2_experiment_cli.py \
  -k 'public_seeded_reward or public_reward or public_build_conflict or public_build_configuration or public_build_replacement or public_formula_edit'
```

These cases are typed refusals or declared gameplay outcomes. They are not internal failures.

## 8. Product-feedback boundary

This maintained example preserves the stable facts that a reader needs to understand its design:

- the public Model and Experiment paths support the seeded reward and build flow;
- Runtime applies the Kernel `same-value-contract` and `runtime-numeric` rules to the LDB-owned
  `core.quantity` exact-integer value rule;
- Runtime cannot construct the result Records, so the Experiment authors mirrored results and the
  Operations validate them before they commit;
- empty selection without a fallback is a typed Runtime refusal;
- declared fallback and build-conflict paths are gameplay outcomes; and
- contradictory option and plan data are typed runtime refusals with terminal rollback evidence.

The replacement-baseline rerun confirms the `operation-execution`, `is-empty`, `require`, and
`guard-block` additions as adopted contract refinements.

Issue #585 owns the detailed observations, their four feedback classifications, the narrowest
owner and action for each observation, and the human accept, condition, or reopen decision. An
accepted example remains bounded implementation evidence; it does not close any claim listed
above.

The [Roguelike reward feedback entry](../../../docs/ARCHITECTURE.md#122-maintained-product-examples)
summarizes the macro architecture consequence and open boundary. This README explains how to run
and inspect the example and preserves its permanent observations. It does not define language
authority or live completion status.
