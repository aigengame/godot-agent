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
ordered candidates, authored policy state, build plans, initial state, and Metrics.
The two Operations validate the relationships among those authored values before they commit
state or publish a result.

Host code does not select rewards, resolve conflicts, supply a fallback, or dispatch by genre.
This example does not close a Roguelike coverage row, Replay, Evidence, template support, Core
Extension Invariance, or a cross-genre claim.

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
- `experiment.json` — seed `20260812`, stream `reward`, ordered reward candidates, build plans,
  initial state, Event plan, and Metrics.

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

The reward pool has two eligible candidates in this order:

1. `steady_guard`, which has rarity `common`;
2. `volatile_crown`, which has rarity `rare`.

`RewardPool` can carry up to 16 candidate and selection entries. This Operation version is a
binary selector: it considers only indexes `0` and `1`. A complete binary pool supplies a matching
candidate and selection at both indexes; later entries do not participate.

The Runtime node vocabulary does not construct `RewardSelection` or `BuildDecision` Record values.
The Experiment therefore authors the candidate-aligned selections, build decisions, and next
states. The Operations validate these mirrored relationships before they commit.

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
  | {candidates, policy_before}' "$BASELINE_TRACE"

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
candidate order, and build plans stay unchanged.

This one-field edit works because `rare_weight` is not repeated in the parallel candidate and
selection entries. Editing a mirrored candidate field, such as `reward_score`, also requires a
change to the corresponding selection. Otherwise, the reward Event rolls back with
`candidate-mismatch`.

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
| Empty candidate and selection lists, with no fallback | `runtime.structured_lookup_out_of_range`; the terminal audit proves rollback |
| Declared `no-reward` selection under `relaxed-pool` | reward success followed by build `no-reward` gameplay alternative |
| Candidate, selection, score, or policy fields contradict each other | `candidate-mismatch` gameplay alternative; the reward Event rolls back |
| Build plan constraint `conflict` | `build-conflict` gameplay alternative; all provisional writes roll back |
| Build state, next state, decision, or score fields contradict each other | `plan-mismatch` gameplay alternative; the build Event rolls back |
| Unknown reward disposition or build constraint | `language.structured_value_unknown_enum` during `experiment check` |

Run the focused tests:

```bash
uv run pytest tests/test_schema2_experiment_cli.py \
  -k 'public_reward or public_build or formula_edit'
```

These cases are typed refusals or declared gameplay outcomes. They are not internal failures.

## 8. Dogfood observations

The `Classification` column uses the four feedback classes from issue #585:
`Confirms current design`, `Adopted contract refinement`,
`Unresolved product/architecture gap`, and `Authored-example-only`.

| Observation | Classification | Narrowest owner and action |
|---|---|---|
| The public Model and Experiment commands support seeded reward selection and a later build Event. | Confirms current design | Model, Experiment, and Runtime contracts; no host change |
| Enum, Record, List, Ref, exact equality, bounded lookup, numeric relations, and transactional writes express the Roguelike slice. | Confirms current design | The `game.generation@1.0.0` and `game.build@1.0.0` Package Releases realize the existing LDB package boundary. |
| A Record lookup preserves the typed `Quantity` envelope. Runtime numeric nodes consume its admitted integer value. | Confirms current design | The Runtime implementation gap is closed: Runtime follows the admitted scalar contract, and package Operations do not depend on field-specific host code. |
| The Formula slot has a one-step bound. An equivalent Formula can be rebound within that bound. | Confirms current design | `game.generation` keeps the bound; broader Formula cost needs separate evidence. |
| Reward and build Metrics distinguish the two configurations (`80/90` versus `20/30`). | Confirms current design | The Experiment Specification owns both Metrics. |
| Empty pools, contradictory authored values, no-reward, conflict, and invalid Enum values keep distinct public semantics. | Confirms current design | `standard.schema`, `game.generation`, `game.build`, and Runtime own their respective results. |
| The Runtime cannot construct the result Records, so the Experiment authors mirrored results and the Operations validate them with guard chains. The guard cost grows with mirrored fields and outcomes. | Unresolved product/architecture gap | Gate 5 must re-evaluate the mirror-and-guard cost before broader Roguelike reuse. This slice adds no new Kernel node, Runtime phase, compiler dispatch, or evaluator dispatch. |
| `candidate-mismatch` and `plan-mismatch` classify authored-data contradictions as `gameplay-alternative`, the same outcome kind used for expected gameplay branches. | Unresolved product/architecture gap | Gate 5 must resolve the outcome classification with `game.generation`, `game.build`, and the shared outcome contract. The current trace remains explicit about the outcome and rollback. |

Neither unresolved input blocks this bounded example. Both must be re-evaluated before Gate 5
reuses the pattern or makes a cross-genre claim.

## 9. Human review checkpoint

The product and architecture owner reviews this maintained example before dependent coverage work
uses it. The review must record one result: accept, accept with conditions, or reopen.

Review these questions:

- Is the reward and build configuration understandable without reading host code?
- Is the one-value tuning loop practical?
- Do the trace, Formula evidence, replacement decision, and two Metrics explain the result?
- Are the empty-pool, no-reward, conflict, authored-data contradiction, and invalid-configuration
  results assigned to the right owner and stage?
- Do the non-claims prevent this slice from being mistaken for Roguelike or cross-genre coverage?

The pull request for issue #585 is the HITL decision point. Until that review records its result,
the example is implementation evidence, not an accepted coverage claim.
