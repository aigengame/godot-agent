# Reciprocal RPG combat through ordered Runtime Events

This tutorial drives one permanent Standard Schema 2.x example through the public CLI:

```text
Formula body <-> human-readable expression
    |
    v
Model Source -> Package Lock + RIR + Model explanation
    |
    v
Experiment with two same-time root Events
    |
    v
ordered Event trace + committed Snapshots + Metrics
```

The Model exposes two directional entrypoints:

- `combat.player-attacks-enemy`
- `combat.enemy-attacks-player`

Both bind the same reusable `game.combat.cast-v1` Operation. The Model reverses the actor and
target operands explicitly; neither Runtime nor host code swaps role names. The Experiment admits
both roots at logical time `0`. Runtime derives `transition` phase, assigns an enqueue sequence and a
stable `event_id` to each root, then dispatches them in total order. The second attack reads the
Snapshot committed by the first.

This is logical simultaneity with deterministic serialization. It is not thread parallelism,
batch-state evaluation, a bidirectional damage primitive, or a combat-specific scheduler.

The files are:

- `model-source.json` — distinct player/enemy Symbols, two pure Formulas, two directional cast
  entrypoints, one explicit cancellation wrapper, and one scheduler-companion entrypoint;
- `experiment.json` — the focused reciprocal scenario with two same-time roots, exact Model
  bindings, seed, six dimensioned Metrics, and acceptance policy;
- `multi-time-experiment.json` — the retained external-input, scheduled-child, cancellation, and
  multi-logical-time companion from the generic Runtime tutorial.

The example is a bounded product-feedback slice. It proves no complete RPG, Action, turn,
interruption, defeat, Replay, Evidence, or general same-time-combat contract.

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

Keep `GDA_BALANCING_ANCHOR_KEY` stable for this store. A repeated command with the same Invocation
key and exact input recovers the committed result byte-for-byte. Use a new Invocation key after
editing the input.

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

The player entrypoint binds player resource and attack values to actor ports, and enemy defense
and health to target ports. The enemy entrypoint performs the exact reverse binding. Matching
names are never inferred.

The same `effective-accuracy` Formula declaration is bound independently to the player and enemy
derived Symbols. The `mitigated-damage` Formula fills the `game.combat.damage-v1` `damage-policy` slot,
so both directional casts consume the same authored damage policy.

The cancellation wrapper remains directional. It invokes the ordinary player cast and then
consumes an explicit `EventReference` port. It does not discover "the next enemy attack" from the
queue.

## 3. Round-trip Formula notation

Every Formula stores an authoritative structured body beside its exact canonical human-readable
expression. The expression is a reversible projection, not a second execution authority.

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

## 4. Build and inspect the exact Model

Build once and save the artifact-set receipt:

```bash
export MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/model-set-receipt.json"

uv run gda-balancing model build \
  examples/schema2/rpg-combat-cast/model-source.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json" \
  --invocation-key "$MODEL_BUILD_INVOCATION_KEY" \
  | tee "$MODEL_SET_RECEIPT"
```

The set contains Package Lock, RIR, Resolved Model, capability manifest, Debug Map, Model
explanation, resolution receipt, and build receipt.

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

For `effective-accuracy`, the evaluation sites expose both `player_accuracy` and `enemy_accuracy`.
That is the public proof that both directions consume the authored Formula without a host-side
role swap.

Resolve and inspect the RIR:

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
Event reference. It is separate from numeric payload targets.

## 5. Understand the reciprocal Experiment

The committed Experiment authors exactly two roots:

| root_event_ref | entrypoint | logical time | priority | authored phase |
| --- | --- | ---: | ---: | --- |
| `player-attacks-enemy` | `combat.player-attacks-enemy` | 0 | 0 | none |
| `enemy-attacks-player` | `combat.enemy-attacks-player` | 0 | 0 | none |

Phase is absent because Runtime derives `transition` for `transition-invocation`. Authored phase is
rejected.

Both Events are admitted before dispatch. With equal time, phase and priority, enqueue sequence
breaks the tie. The array's canonical root-member order therefore makes the player attack
sequence 0 and the enemy attack sequence 1. Changing priority is a different semantic edit from
changing root-member admission order.

The later Event does not read Snapshot 0. It reads the Snapshot committed by the earlier Event.
Runtime does not infer defeat, interruption, or cancellation from health-like values. Those are
package-owned policies and must produce explicit operations and outcomes.

Two independent scenarios would each receive their own Snapshot 0, queue, and replication. They
would not form a reciprocal exchange and could not observe each other's committed state.

Check without publishing:

```bash
uv run gda-balancing experiment check \
  examples/schema2/rpg-combat-cast/experiment.json \
  | jq .
```

Admission closes exact authority/Model bindings, unique root references, entrypoints, Scenario
inputs, Event-local payloads, Event references, named streams, Runtime requirements, and Metrics.

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

Each Metric has an explicit scenario window plus entity and role dimensions. State continuity is
visible directly: the enemy Event's `state_before` equals the player Event's `state_after`, and its
`snapshot_before_identity` is that committed Snapshot.

Repeat the exact command with the same Invocation key. Recovery returns the same receipt and
canonical artifact bytes without dispatching again.

## 7. Compare ordinary, miss and insufficient-resource outcomes

`game.combat.cast-v1` owns three typed outcomes:

| Setup | Typed outcome | State policy |
| --- | --- | --- |
| admitted hit | `cast-resolved` / `success` | `commit` |
| hit check fails | `miss` / `gameplay-alternative` | `rollback` |
| actor resource below action cost | `insufficient-resource` / `gameplay-alternative` | `rollback` |

A one-way scenario contains only `player-attacks-enemy` and only that entrypoint's Scenario Input
Contract. It is useful for an ordinary cast comparison, but it is not reciprocal combat.

For a deterministic miss with the committed seed, copy the Experiment, retain only the player
root, set `player_accuracy` to `0` and `enemy_defense` to `1000`, and retain snapshot-sourced Metrics.
For insufficient resource, instead set `player_mana` to `0`. The Event trace distinguishes the typed
outcomes; neither branch is a Runtime refusal, and both roll back the Event's state writes.

## 8. Explicitly cancel the admitted counterattack

Cancellation resolves a declared Event-reference role to an authored root reference, then to the
Runtime `event_id` admitted for that root. Create a cancellation variant:

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

The root map still contains both admitted event ids. Only the player attack dispatches. Its
cancellations row names the enemy root's exact `event_id` and outcome `canceled`, and the committed
continuation has no pending Event. Cancellation is prospective; it does not rewind the player's
already committed cast.

Binding `counterattack` to `player-attacks-enemy` instead targets the currently active root. That
run refuses with `runtime.cancel_active`; Runtime never reclassifies the active Event as pending.

## 9. Prove Runtime does not infer defeat or eligibility

Create a separate no-cancellation variant by setting `enemy_health` to `37`. The first attack deals
37 damage and commits `enemy_health = 0`:

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

The enemy attack still dispatches, reads `enemy_health = 0` from the latest Snapshot, and returns
ordinary `cast-resolved`. This is not a claim that a defeated actor should attack. It proves only
that Runtime owns ordering, not an undeclared defeat or eligibility policy.

## 10. Edit one combatant's bound value

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

Only `player_damage_dealt` and `enemy_health_remaining` change: 37 becomes 47, and 63 becomes 53.
Enemy damage, player health, and both resource results remain unchanged. Kernel, LDB, Package
Lock, RIR, evaluator dispatch, and exact Model bindings are unchanged; the Experiment, trace and
Metric identities change.

Edit Model Source and rebuild when changing a Formula body or binding. Such an edit changes the
Formula/RIR/Resolved-Model identities, and the old exact Experiment must refuse until rebound to
the new build. It still does not require a new Kernel primitive or host evaluator branch when the
edit stays within the admitted Formula and pure-Operation vocabulary.

The `game.combat.damage-v1` `damage-policy` is one package Operation slot, so its current Formula
binding is intentionally shared by both directional entrypoints. Actor-specific tuning in this
example therefore uses actor-specific bound values. A genuinely actor-specific Formula policy
would require a distinct authored policy-selection seam; it must not be simulated by host dispatch
or by duplicating the package Operation.

## 11. Retain the multi-time scheduler companion

The reciprocal baseline stays focused on two same-time attacks and six reciprocal Metrics.
`multi-time-experiment.json` independently retains the earlier generic Runtime tutorial surface:
an external-input root, `combat.player-plans-attacks`, its scheduled child at logical time `1`, its
explicitly canceled child at logical time `2`, and a separate retry root at logical time `2`.

Run it against the same exact Model build:

```bash
export MULTI_TIME_INVOCATION_KEY="$(openssl rand -hex 32)"

uv run gda-balancing experiment run \
  examples/schema2/rpg-combat-cast/multi-time-experiment.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/multi-time-run.json" \
  --invocation-key "$MULTI_TIME_INVOCATION_KEY"
```

This companion preserves #609's external-input, scheduling, cancellation, and multi-logical-time
dogfooding without adding unrelated Events to the reciprocal baseline or changing its Metrics.

## 12. Product and architecture review

The human owner should run the baseline, cancellation, eligibility, tuning, and multi-time variants, then
record one of accept, accept with explicit conditions, or reopen on issue #595.

Review:

- whether player/enemy configuration and reversed operands are clear;
- whether same-logical-time admission versus serialized dispatch is understandable;
- whether the second Event's Snapshot dependency is visible;
- whether Formula explanation sites show both directions;
- whether cancellation provenance identifies the authored reference and Runtime id;
- whether trace, Snapshot and Metric fields make the edit feedback obvious;
- whether any new behavior belongs in Kernel, a sealed package, Model Source, Experiment, or only
  this authored example.

Do not close broader Tracer, RPG, turn, defeat, Replay, Evidence, or Action/Combat claims from this
tutorial.

## Artifact-store and troubleshooting notes

The receipt, not the convenience `--out` copy, locates the complete committed artifact set.
Committed store members use canonical one-line JSON and authenticated anchors. Format them with
`jq` for display; do not rewrite files inside the store.

Common failures:

- `invalid_argument` for a key — use exactly 64 lowercase hexadecimal digits;
- `invocation_key_conflict` — the key already names different canonical input; restore that input
  or generate a new key;
- Experiment cannot resolve Model artifacts — reuse the build's store and anchor key, build first,
  and bind the exact Build receipt, Resolved Model, Package Lock and RIR identities;
- `language.formula_notation_mismatch` — regenerate the adjacent `body`/`expression` pair through
  `formula parse` or `formula render`;
- `language.source_contract_mismatch` on a one-way variant — remove assignments and Metrics that
  belong only to the unselected directional entrypoint.
