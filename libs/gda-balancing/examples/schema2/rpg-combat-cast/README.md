# Reciprocal RPG combat through ordered Runtime Events

This tutorial runs one Standard Schema 2.x combat example through the public CLI:

```text
Formula body <-> canonical human-readable expression
    |
    v
Model Source Package -> model build -> complete Model artifact set
    |
    v
Experiment with two same-logical-time root Events
    |
    v
ordered Event trace + committed Snapshots + Metrics
```

The Model exposes two directional entrypoints:

- `combat.player-attacks-enemy`
- `combat.enemy-attacks-player`

Both entrypoints bind the reusable `game.combat.cast-v1` Operation. The Model explicitly reverses
the actor and target operands. Runtime and host code do not swap role names.

The Experiment admits both root Events at logical time `0`. Runtime derives the `transition` phase.
It assigns an enqueue sequence and an `event_id` to each Event. Runtime then dispatches the Events
in total order. The second Event reads the Snapshot that the first Event committed.

This is logical simultaneity with deterministic serialization. It is not thread parallelism,
batch-state evaluation, a bidirectional damage primitive, or a combat-specific scheduler.

The files are:

- `model-source.json` — distinct player/enemy Symbols, two pure Formulas, two directional cast
  entrypoints, one explicit cancellation wrapper, and one scheduler-companion entrypoint;
- `experiment.json` — the focused reciprocal scenario with two same-logical-time roots, an exact
  Resolved Model binding, seed, six dimensioned Metrics, and acceptance policy;
- `multi-time-experiment.json` — an external-input root, scheduled and canceled child Events, and
  multiple logical times.

This example demonstrates one bounded reciprocal exchange. It does not define a complete RPG,
Action, turn, interruption, defeat, Replay, Evidence, or general same-logical-time combat contract.

## 1. Prepare an isolated run

Prerequisites:

- `uv` for the package environment and CLI;
- `jq` for JSON projection and inspection;
- `openssl` for tutorial-only random key generation.

Run from `libs/gda-balancing`:

```bash
uv sync
```

Create a temporary artifact store and three independent keys:

```bash
export GDA_BALANCING_TUTORIAL_ROOT="$(
  mktemp -d /tmp/gda-balancing-reciprocal-combat.XXXXXX
)"
export GDA_BALANCING_STORE_DIR="$GDA_BALANCING_TUTORIAL_ROOT/store"
export GDA_BALANCING_ANCHOR_KEY="$(openssl rand -hex 32)"
export MODEL_BUILD_INVOCATION_KEY="$(openssl rand -hex 32)"
export EXPERIMENT_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
```

Keep `GDA_BALANCING_ANCHOR_KEY` stable for this store. Repeat a command with the same Invocation key
and exact input to recover the committed result byte-for-byte. After you edit the input, generate a
new Invocation key.

## 2. Read the directional Model

Inspect the source:

```bash
jq . examples/schema2/rpg-combat-cast/model-source.json
```

The source selects `core.quantity@2.1.0` and `game.combat@2.1.0`. The selected closure supplies
resource spending, hit and critical checks, deterministic Runtime behavior, and the directional
cast Operation.

The important Symbols are:

| Combatant | State | Parameters and inputs | Derived | Output |
| --- | --- | --- | --- | --- |
| player | `player_mana`, `player_health` | `player_action_cost`, `player_accuracy`, `player_base_damage`, `player_critical_threshold`, `player_defense` | `player_effective_accuracy` | `player_damage_dealt` |
| enemy | `enemy_mana`, `enemy_health` | `enemy_action_cost`, `enemy_accuracy`, `enemy_base_damage`, `enemy_critical_threshold`, `enemy_defense` | `enemy_effective_accuracy` | `enemy_damage_dealt` |

The player entrypoint binds player resource and attack values to actor ports. It binds enemy defense
and health to target ports. The enemy entrypoint uses the reverse binding. The compiler does not
infer bindings from matching names.

The same `effective-accuracy` Formula declaration binds to the player and enemy derived Symbols.
The `mitigated-damage` Formula fills the `game.combat.damage-v1` `damage-policy` slot. Thus, both
directional casts use the same authored damage policy.

The cancellation wrapper remains directional. It invokes the player cast and then reads an explicit
`EventReference` port. It does not discover "the next enemy attack" from the queue.

## 3. Round-trip Formula notation

Every Formula stores an authoritative structured body and its canonical human-readable expression.
The expression is a reversible projection. It is not a second execution authority.

Render `mitigated-damage` from its body:

```bash
export FORMULA_RENDER_REQUEST="$GDA_BALANCING_TUTORIAL_ROOT/formula-render.json"
export RENDERED_FORMULA="$GDA_BALANCING_TUTORIAL_ROOT/formula-rendered.json"

jq '{
  schema_version,
  package_requirements,
  module: (.modules[0] | {id, imports}),
  formula: (.modules[0].formulas[]
    | select(.id == "mitigated-damage")
    | del(.expression))
}' examples/schema2/rpg-combat-cast/model-source.json \
  > "$FORMULA_RENDER_REQUEST"

uv run gda-balancing formula render "$FORMULA_RENDER_REQUEST" \
  | tee "$RENDERED_FORMULA"
```

Its canonical expression is:

```text
let raw_damage = damage_before_defense - mitigation;
let damage = floor_zero(raw_damage);
damage
```

Parse a whitespace-heavy equivalent expression back to the same pair:

```bash
export FORMULA_PARSE_REQUEST="$GDA_BALANCING_TUTORIAL_ROOT/formula-parse.json"
export PARSED_FORMULA="$GDA_BALANCING_TUTORIAL_ROOT/formula-parsed.json"

jq '{
  schema_version,
  package_requirements,
  module: (.modules[0] | {id, imports}),
  formula: ((.modules[0].formulas[]
    | select(.id == "mitigated-damage")
    | del(.body))
    | .expression = " let raw_damage = ((damage_before_defense - mitigation)); let damage = floor_zero(((raw_damage))); damage ")
}' examples/schema2/rpg-combat-cast/model-source.json \
  > "$FORMULA_PARSE_REQUEST"

uv run gda-balancing formula parse "$FORMULA_PARSE_REQUEST" \
  | tee "$PARSED_FORMULA"

test "$(jq -cS '.body' "$PARSED_FORMULA")" = \
  "$(jq -cS '.body' "$RENDERED_FORMULA")"
test "$(jq -r '.expression' "$PARSED_FORMULA")" = \
  "$(jq -r '.expression' "$RENDERED_FORMULA")"
```

Directly changing only expression whitespace is invalid canonical data. Model admission returns
`language.formula_notation_mismatch` rather than choosing or repairing one side.

## 4. Build and inspect the Model artifact set

Build once and save the artifact-set receipt:

```bash
export MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/model-set-receipt.json"

uv run gda-balancing model build \
  examples/schema2/rpg-combat-cast/model-source.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json" \
  --invocation-key "$MODEL_BUILD_INVOCATION_KEY" \
  | tee "$MODEL_SET_RECEIPT"
```

The Model artifact set contains these members:

- Package Lock;
- RIR semantic payload;
- Resolved Model;
- Evaluator Capability Manifest;
- Debug Map;
- Model explanation;
- Resolution receipt; and
- Build receipt.

Inspect the stored explanation:

```bash
uv run gda-balancing model inspect \
  "$MODEL_SET_RECEIPT" \
  --format indented \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"

jq '.formula_explanations[]
  | {id, expression, evaluation_sites, closure}' \
  "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"
```

For `effective-accuracy`, the evaluation sites contain both `player_accuracy` and
`enemy_accuracy`. This evidence shows that both entrypoints use the authored Formula. Host code
does not swap the roles.

Resolve and inspect the RIR semantic payload:

```bash
export RIR_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "rir-semantic-payload")
    | .locator' "$MODEL_SET_RECEIPT"
)"

jq '.entrypoints[] | {
  id,
  operation,
  arguments,
  event_local_payload_contract
}' "$RIR_PATH"
```

The cancellation entrypoint's `event_local_payload_contract` names `counterattack` as a required
Event reference. This reference is separate from the numeric payload targets.

## 5. Understand the reciprocal Experiment

The committed Experiment authors exactly two roots:

| root_event_ref | entrypoint | logical time | priority | authored phase |
| --- | --- | ---: | ---: | --- |
| `player-attacks-enemy` | `combat.player-attacks-enemy` | 0 | 0 | none |
| `enemy-attacks-player` | `combat.enemy-attacks-player` | 0 | 0 | none |

The phase is absent because Runtime derives `transition` for `transition-invocation`. Experiment
admission rejects an authored phase.

Runtime admits both Events before it dispatches either Event. Both Events have the same logical
time, phase, and priority. The enqueue sequence breaks the tie. The canonical root-member order
gives the player attack sequence `0` and the enemy attack sequence `1`. A priority change and a
root-member order change are different semantic edits.

The later Event does not read Snapshot 0. It reads the Snapshot that the earlier Event committed.
Runtime does not infer defeat, interruption, or cancellation from health-like values. A package
must define these policies with explicit Operations and outcomes.

Each independent scenario receives its own Snapshot 0, Event queue, and replication. Two scenarios
cannot form a reciprocal exchange or observe each other's committed state.

Check without publishing:

```bash
uv run gda-balancing experiment check \
  examples/schema2/rpg-combat-cast/experiment.json \
  | jq .
```

Experiment admission validates the exact authority and Resolved Model bindings. It validates root
references, entrypoints, and Scenario inputs. It also validates Event-local payloads, Event
references, named streams, Runtime requirements, and Metrics.

## 6. Run and inspect ordering, Snapshots and Metrics

Run and save the receipt:

```bash
export EXPERIMENT_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-set-receipt.json"

uv run gda-balancing experiment run \
  examples/schema2/rpg-combat-cast/experiment.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/evaluation-run.json" \
  --invocation-key "$EXPERIMENT_RUN_INVOCATION_KEY" \
  | tee "$EXPERIMENT_SET_RECEIPT"
```

Resolve the three main artifacts:

```bash
export EVENT_TRACE_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "event-trace")
    | .locator' "$EXPERIMENT_SET_RECEIPT"
)"
export SNAPSHOT_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "snapshot-series")
    | .locator' "$EXPERIMENT_SET_RECEIPT"
)"
export METRIC_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "metric-dataset")
    | .locator' "$EXPERIMENT_SET_RECEIPT"
)"
```

Inspect Runtime-assigned root ids and dispatch evidence:

```bash
jq '.root_event_map, (.events[] | select(.operation != null) | {
  event_id,
  root_event_ref,
  ordering_key,
  entrypoint,
  calls,
  outcome,
  rng_draws,
  state_before,
  state_after,
  snapshot_before_identity,
  snapshot_after_identity,
  cancellations
})' "$EVENT_TRACE_PATH"
```

Inspect committed Snapshots and Metrics:

```bash
jq '.snapshots' "$SNAPSHOT_PATH"
jq '.samples[] | {
  metric,
  value,
  dimensions,
  window,
  within_target,
  provenance
}' "$METRIC_PATH"
```

The committed seed and values produce:

| Metric | Value |
| --- | ---: |
| `player_damage_dealt` | 37 |
| `enemy_damage_dealt` | 14 |
| `player_health_remaining` | 86 |
| `enemy_health_remaining` | 63 |
| `player_resource_remaining` | 26 |
| `enemy_resource_remaining` | 23 |

Each Metric has an explicit Scenario window and entity and role dimensions. The Event trace shows
state continuity. The enemy Event's `state_before` equals the player Event's `state_after`. Its
`snapshot_before_identity` identifies that committed Snapshot.

Repeat the exact command with the same Invocation key. Recovery returns the same receipt and
canonical artifact bytes. Runtime does not dispatch the Events again.

## 7. Edit one combatant's bound value

Experiment assignments tune one run without changing Model or language semantics. Increase only
`player_base_damage` from `45` to `55`:

```bash
export TUNED_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-player-tuned.json"

jq '
  .id = "example.rpg-combat-cast.player-damage-tuned"
  | (.scenarios[0].assignments[]
      | select(.target.name == "player_base_damage")
      | .value) = 55
' examples/schema2/rpg-combat-cast/experiment.json \
  > "$TUNED_EXPERIMENT"

export TUNED_INVOCATION_KEY="$(openssl rand -hex 32)"

uv run gda-balancing experiment run \
  "$TUNED_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/tuned-run.json" \
  --invocation-key "$TUNED_INVOCATION_KEY"
```

Only `player_damage_dealt` and `enemy_health_remaining` change. Player damage changes from `37` to
`47`. Enemy health changes from `63` to `53`. Enemy damage, player health, and both resource results
remain unchanged.

The edit changes the Experiment, Event trace, and Metric identities. It does not change the Kernel,
LDB, Package Lock, RIR semantic payload, evaluator dispatch, or exact Resolved Model binding.

If you change a Formula body or binding, edit the Model Source Package and rebuild it. The edit
changes the Formula, RIR semantic payload, and Resolved Model identities. The old Experiment still
binds the old Resolved Model. Create a new Experiment from the new Build receipt before you run the
new Model. The edit does not require a new Kernel primitive or evaluator branch when it uses the
admitted Formula and pure-Operation vocabulary.

The `game.combat.damage-v1` Operation has one `damage-policy` Formula slot. Both directional
entrypoints intentionally share its current Formula binding. This example uses actor-specific bound
values for actor-specific tuning. A different actor-specific Formula policy requires a separate
authored policy-selection seam. Host dispatch and duplicate package Operations must not simulate
that policy.

## 8. Run optional behavior probes

The core designer loop ends with the edit and rerun in section 7. The following probes demonstrate
additional Runtime and package boundaries.

### 8.1 Compare ordinary, miss, and insufficient-resource outcomes

`game.combat.cast-v1` defines three typed outcomes:

| Setup | Typed outcome | State policy |
| --- | --- | --- |
| admitted hit | `cast-resolved` / `success` | `commit` |
| hit check fails | `miss` / `gameplay-alternative` | `rollback` |
| actor resource below action cost | `insufficient-resource` / `gameplay-alternative` | `rollback` |

A one-way scenario contains only `player-attacks-enemy`. It also contains only that entrypoint's
Scenario Input Contract. It is useful for outcome comparison, but it is not reciprocal combat.

Create the one-way base Experiment. Keep only the player root, its assignments, and its Metrics:

```bash
export ONE_WAY_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-one-way.json"

jq '
  .id = "example.rpg-combat-cast.one-way"
  | .scenarios[0].event_plan = [.scenarios[0].event_plan[0]]
  | .scenarios[0].assignments |= map(
      select(.target.name as $name
        | [
            "enemy_defense",
            "enemy_health",
            "player_accuracy",
            "player_action_cost",
            "player_base_damage",
            "player_critical_threshold",
            "player_mana"
          ]
        | index($name))
    )
  | .metrics |= map(
      select(.id as $id
        | [
            "enemy_health_remaining",
            "player_damage_dealt",
            "player_resource_remaining"
          ]
        | index($id))
    )
' examples/schema2/rpg-combat-cast/experiment.json \
  > "$ONE_WAY_EXPERIMENT"
```

Create the miss and insufficient-resource variants:

```bash
export MISS_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-miss.json"
jq '
  .id = "example.rpg-combat-cast.miss"
  | (.scenarios[0].assignments[]
      | select(.target.name == "player_accuracy")
      | .value) = 0
  | (.scenarios[0].assignments[]
      | select(.target.name == "enemy_defense")
      | .value) = 1000
  | .metrics |= map(select(.observation.source == "snapshot"))
' "$ONE_WAY_EXPERIMENT" > "$MISS_EXPERIMENT"

export RESOURCE_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-insufficient-resource.json"
jq '
  .id = "example.rpg-combat-cast.insufficient-resource"
  | (.scenarios[0].assignments[]
      | select(.target.name == "player_mana")
      | .value) = 0
  | .metrics |= map(select(.observation.source == "snapshot"))
' "$ONE_WAY_EXPERIMENT" > "$RESOURCE_EXPERIMENT"
```

Run both variants with new Invocation keys:

```bash
export MISS_INVOCATION_KEY="$(openssl rand -hex 32)"
uv run gda-balancing experiment run \
  "$MISS_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/miss-run.json" \
  --invocation-key "$MISS_INVOCATION_KEY" \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/miss-receipt.json"

export RESOURCE_INVOCATION_KEY="$(openssl rand -hex 32)"
uv run gda-balancing experiment run \
  "$RESOURCE_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/insufficient-resource-run.json" \
  --invocation-key "$RESOURCE_INVOCATION_KEY" \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/insufficient-resource-receipt.json"
```

Inspect each `event-trace` member as shown in section 6. The miss Event has the `miss` outcome. The
resource Event has the `insufficient-resource` outcome. Both are gameplay alternatives, not Runtime
refusals. Both Events roll back their state writes. These variants keep only Snapshot-sourced
Metrics because a rolled-back alternative produces no damage fact.

### 8.2 Explicitly cancel the admitted counterattack

Cancellation resolves an Event-reference role to an authored Root Event reference. Runtime then
resolves that reference to the admitted `event_id`. Create a cancellation variant:

```bash
export CANCELLATION_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-cancel.json"

jq '
  .id = "example.rpg-combat-cast.explicit-cancellation"
  | .scenarios[0].event_plan[0].entrypoint =
      "combat.player-attacks-enemy-and-cancels-counterattack"
  | .scenarios[0].event_plan[0].event_references = [{
      "name": "counterattack",
      "root_event_ref": "enemy-attacks-player"
    }]
  | .runtime.required_evaluator.instruction_nodes += ["cancel"]
  | .runtime.required_evaluator.effects += ["event.cancel"]
  | .metrics |= map(select(.observation.source == "snapshot"))
' examples/schema2/rpg-combat-cast/experiment.json \
  > "$CANCELLATION_EXPERIMENT"

export CANCELLATION_INVOCATION_KEY="$(openssl rand -hex 32)"
export CANCELLATION_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/cancellation-receipt.json"

uv run gda-balancing experiment run \
  "$CANCELLATION_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/cancellation-run.json" \
  --invocation-key "$CANCELLATION_INVOCATION_KEY" \
  | tee "$CANCELLATION_RECEIPT"
```

The `root_event_map` still contains both admitted `event_id` values. Runtime dispatches only the
player attack. Its `cancellations` row identifies the enemy Event and the `canceled` outcome. The
committed continuation contains no pending Event. Cancellation is prospective. It does not reverse
the player cast that Runtime already committed.

If you bind `counterattack` to `player-attacks-enemy`, it targets the active root Event. The run
refuses with `runtime.cancel_active`. Runtime does not reclassify the active Event as pending.

### 8.3 Verify that Runtime does not infer defeat or eligibility

Create a no-cancellation variant. Set `enemy_health` to `37`. The first attack deals `37` damage and
commits `enemy_health = 0`:

```bash
export ELIGIBILITY_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-no-inference.json"

jq '
  .id = "example.rpg-combat-cast.no-inferred-defeat"
  | (.scenarios[0].assignments[]
      | select(.target.name == "enemy_health")
      | .value) = 37
' examples/schema2/rpg-combat-cast/experiment.json \
  > "$ELIGIBILITY_EXPERIMENT"

export ELIGIBILITY_INVOCATION_KEY="$(openssl rand -hex 32)"

uv run gda-balancing experiment run \
  "$ELIGIBILITY_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/no-inference-run.json" \
  --invocation-key "$ELIGIBILITY_INVOCATION_KEY"
```

Runtime still dispatches the enemy attack. The Event reads `enemy_health = 0` from the latest
Snapshot and returns `cast-resolved`. This result does not mean that a defeated actor should attack.
It shows that Runtime does not own an undeclared defeat or eligibility policy.

### 8.4 Run the multi-time scheduler companion

The reciprocal baseline contains two attacks at the same logical time and six reciprocal Metrics.
`multi-time-experiment.json` demonstrates additional Runtime behavior. It contains an external-input
root and the `combat.player-plans-attacks` entrypoint. It also contains a scheduled child at logical
time `1`, a canceled child at logical time `2`, and a retry root at logical time `2`.

Run it against the same Resolved Model binding:

```bash
export MULTI_TIME_INVOCATION_KEY="$(openssl rand -hex 32)"

uv run gda-balancing experiment run \
  examples/schema2/rpg-combat-cast/multi-time-experiment.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/multi-time-run.json" \
  --invocation-key "$MULTI_TIME_INVOCATION_KEY"
```

This companion keeps the baseline focused. It does not add unrelated Events or Metrics to the
reciprocal scenario.

## 9. Validation scope

Automated end-to-end tests validate the baseline, tuning path, typed alternatives, cancellation,
eligibility boundary, and multi-time companion.
[Reciprocal same-time Event dogfooding](../../../docs/ARCHITECTURE.md#128-reciprocal-same-time-event-dogfooding)
records the accepted architecture observations and limits.
This README explains how to run and inspect those behaviors. It does not define their architecture.

## Artifact-store and troubleshooting notes

Use the artifact-set receipt to locate the complete committed artifact set. The `--out` file is
only a convenience copy. Store members use canonical one-line JSON and authenticated anchors. Use
`jq` to format them for display. Do not rewrite files inside the store.

Common failures:

- `invalid_argument` for a key — use exactly 64 lowercase hexadecimal digits;
- `invocation_key_conflict` — the key already names different canonical input; restore that input
  or generate a new key;
- Experiment cannot resolve Model artifacts — reuse the build's store and anchor key. Build the
  Model first. Then bind the exact Build receipt, Resolved Model, Package Lock, and RIR semantic
  payload identities;
- `language.formula_notation_mismatch` — regenerate the adjacent `body`/`expression` pair through
  `formula parse` or `formula render`;
- `language.source_contract_mismatch` on a one-way variant — remove assignments and Metrics that
  belong only to the unselected directional entrypoint.
