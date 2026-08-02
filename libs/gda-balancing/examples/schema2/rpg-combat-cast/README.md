# RPG combat-cast tuning loop

This tutorial walks through the first bounded Standard Schema 2.0 RPG example from editable
numeric design to an evaluated combat result:

```text
Human-readable Formula expression <-> structured Formula body
    |
    |  formula parse / formula render
    v
Paired Model Source Package
    + Kernel Specification and Language Definition Bundle
    |
    |  model build
    v
Package Lock + RIR + Resolved Model + Model explanation
    |
    |  experiment check
    v
Admitted Experiment Specification
    |
    |  experiment run
    v
Event trace + Snapshots + Metrics + Evaluation run
```

The example models one bounded multi-Event scenario. An authored external-input root changes the
defense fact, an authored `game.combat.plan-casts-v1` root schedules two child casts, the plan
cancels one pending child, and the remaining `game.combat.cast-v1` child executes at logical time
`1`. Runtime then derives the Metric's read-only observation Event. The game owns two
pure Formulas in Model Source: `effective-accuracy` initializes a game-owned derived Symbol, while
`mitigated-damage` fills the combat package's `damage-policy` Formula slot. The reusable Operation
still owns Event control, RNG, state changes, outcomes, and commit/rollback. The files are:

- [`model-source.json`](model-source.json): the editable numeric model. It declares symbols,
  pure Formulas as exact adjacent `body`/`expression` pairs, static Formula bindings, package
  requirements, and the `combat.cast` / `combat.plan-casts` entrypoints that explicitly bind
  game-owned symbols to Operation ports.
- [`experiment.json`](experiment.json): one exact scenario and evaluation policy. It binds the
  built Model artifacts, authors the two root Events, assigns the generated one-time Scenario Input
  Contract, supplies a seed, and defines the Metric and acceptance target.

This is a beginner-oriented product-feedback slice, not proof of general RPG or Roguelike
coverage.

The `standard.quantity-minimal` template supplies the editable, engine-agnostic derived-Formula
starter. This tutorial then selects `game.combat` and adds the game-owned combat-slot Formula and
binding shown above. The generic starter intentionally does not bind an Operation slot from a
mechanic package it has not selected.

## 1. Prepare the workspace and keys

Prerequisites:

- a checkout of this repository;
- `uv` and `openssl`;
- `jq` for the inspection commands.

Run every command below from `libs/gda-balancing` and prepare its independent environment:

```sh
cd libs/gda-balancing
uv sync
```

The tutorial uses `openssl` to generate the three required 32-octet keys. `openssl rand -hex 32`
prints exactly 64 lowercase hexadecimal digits, which is the format expected by the CLI.

```sh
export GDA_BALANCING_TUTORIAL_ROOT="$(
  mktemp -d /tmp/gda-balancing-rpg-cast.XXXXXX
)"
export GDA_BALANCING_STORE_DIR="$GDA_BALANCING_TUTORIAL_ROOT/store"
export GDA_BALANCING_ANCHOR_KEY="$(openssl rand -hex 32)"
export MODEL_BUILD_INVOCATION_KEY="$(openssl rand -hex 32)"
export EXPERIMENT_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
```

The unique tutorial root prevents an old store or output file from colliding with this run. Keep
the exports in the same shell while following the tutorial.

Keep `GDA_BALANCING_ANCHOR_KEY` stable for the lifetime of this store. It authenticates committed
publication anchors. If it changes, the CLI cannot authenticate artifacts already published in
that store. Treat it as a local secret: do not commit it to source control or print it into logs.

An Invocation key has a different purpose. It identifies one retry-safe command invocation:

- same command descriptor, same Invocation key, and same canonical input: recover the committed
  outcome without executing again;
- same command descriptor and Invocation key, but changed canonical input:
  `invocation_key_conflict`;
- changed input that should execute again: generate a new Invocation key.

`model build` and `experiment run` therefore use separate keys. `experiment check` only analyzes
its input and publishes no artifact set, so it needs no Invocation key.

`jq` does not participate in execution; it only makes the canonical one-line JSON emitted by the
toolkit readable.

## 2. Understand the model source

Inspect the source:

```sh
jq . examples/schema2/rpg-combat-cast/model-source.json
```

The source requires two Domain packages:

- `core.quantity@2.1.0` supplies the generic `Quantity` constructor imported by the source;
- `game.combat@2.0.0` supplies the composed `game.combat.cast-v1` operation.

`game.combat` declares `game.resource`, `game.check`, and `standard.runtime` as required
dependencies. Resolution closes that transitive graph and selects capability providers from the
whole selected closure, so the Model Source does not repeat those indirect dependencies. The
mechanics remain independently owned: resource spending belongs to `game.resource`, hit and
critical checks belong to `game.check`, and damage plus cast composition belong to `game.combat`.
No RPG-wide value constructor or genre umbrella is involved.

Its symbols demonstrate five lifecycle roles:

| Role | Symbols in this example | Meaning |
|---|---|---|
| `state` | `actor_mana`, `target_health` | Persistent values changed by an Event |
| `parameter` | `action_cost`, `accuracy`, `base_damage`, `critical_threshold` | Designer-controlled values supplied to the operation |
| `input` | `target_defense` | Scenario input read by the operation |
| `derived` | `effective_accuracy` | Read-only value computed from a Formula before Snapshot 0 |
| `output` | `damage_dealt` | Event result exposed for observation and Metrics |

All nine values use exact signed-64-bit integer semantics and an admitted range of `0..1000`.
The Model Source owns these definitions; it does not contain a scenario, seed, Metric target, or
runtime result.

Each Formula carries one authoritative structured `body` beside its exact canonical human-readable
`expression`. The expression is a reversible contextual projection, not a second execution
authority or an independent host script. `effective-accuracy` calls the pure `quantity.maximum`
Operation to enforce a minimum accuracy of one, then binds that result to the
`effective_accuracy` derived Symbol in the immutable Initialization frame. `mitigated-damage`
calls `quantity.subtract` and `quantity.floor-zero`, then binds exactly once to the
`game.combat.damage-v1` Operation's `damage-policy` slot for Event evaluation. Formula calls may
only reach statically resolved pure Formulas and pure Operations; the compiler closes their
refusal, resource-charge, and termination contracts before Typed HIR.

Formula timing belongs to each binding site, not to the declaration. Initialization Formulas read
only the pre-Snapshot frame and must all succeed before Snapshot 0 commits. Event Formula slots
read the committed pre-event Snapshot and cannot observe buffered writes. An implementation may
cache a pure result, but a cache hit applies the same charge as an uncached evaluation, so caching
cannot move the resource-exhaustion boundary.

Formula arguments bind by explicit parameter or Operation-port name, never by list position. If
two operands have the same admitted contract, swapping their named bindings is therefore a valid
semantic edit rather than a type error; the binding, Formula, RIR, and downstream identities make
that edit observable.

The Model Source also owns `combat.cast` and `combat.plan-casts` entrypoints. Their reusable LDB
Operations own formal ports such as `hit_defense` and `damage_mitigation`. Both entrypoints bind
those read-only ports explicitly to the one game-owned
`target_defense` symbol; matching names are neither required nor used for resolution. The
LDB assignment policy marks that Symbol as a required Experiment input, so RIR exports one exact
target even though two ports consume it; the Experiment assigns that target once. A Model-fixed
value would instead appear as a Model initializer, and an admitted override mode would expose one
optional Experiment target over that explicit default. The same LDB policy separately exports
read-only `parameter` and `input` operands as optional Event-local targets. The example plan uses
that contract to supply `base_damage` for its transition without making `actor_mana` state
payload-addressable. This is deliberate DRY:

```text
LDB Operation formal ports
    -> Model entrypoint binds game-owned symbols
        -> RIR derives exact call sites and Scenario Input Contract
            + Event-local payload contract
                -> Experiment assigns only the matching members at each boundary
```

## 3. Round-trip Formula notation

`formula render` starts from a structured body and returns the admitted canonical pair. Build a
request for the committed two-binding damage Formula without duplicating its context:

```sh
export FORMULA_RENDER_REQUEST="$GDA_BALANCING_TUTORIAL_ROOT/formula-render.json"
export RENDERED_FORMULA_PAIR="$GDA_BALANCING_TUTORIAL_ROOT/formula-rendered-pair.json"

jq '{
  schema_version,
  package_requirements,
  module: (.modules[0] | {id, imports}),
  formula: (.modules[0].formulas[]
    | select(.id == "mitigated-damage")
    | del(.expression))
}' examples/schema2/rpg-combat-cast/model-source.json > "$FORMULA_RENDER_REQUEST"

uv run gda-balancing formula render "$FORMULA_RENDER_REQUEST" \
  | tee "$RENDERED_FORMULA_PAIR"

jq '{body, expression}' "$RENDERED_FORMULA_PAIR"
```

The canonical expression is:

```text
let raw_damage = damage_before_defense - mitigation;
let damage = floor_zero(raw_damage);
damage
```

`formula parse` runs the reverse direction. It accepts grammar-valid extra whitespace and redundant
parentheses, resolves package-owned notation under the same module and exact LDB, and returns the
same canonical pair:

```sh
export FORMULA_PARSE_REQUEST="$GDA_BALANCING_TUTORIAL_ROOT/formula-parse.json"
export PARSED_FORMULA_PAIR="$GDA_BALANCING_TUTORIAL_ROOT/formula-parsed-pair.json"

jq '{
  schema_version,
  package_requirements,
  module: (.modules[0] | {id, imports}),
  formula: ((.modules[0].formulas[]
    | select(.id == "mitigated-damage")
    | del(.body))
    | .expression = " let raw_damage = ((damage_before_defense - mitigation)); let damage = floor_zero(((raw_damage))); damage ")
}' examples/schema2/rpg-combat-cast/model-source.json > "$FORMULA_PARSE_REQUEST"

uv run gda-balancing formula parse "$FORMULA_PARSE_REQUEST" \
  | tee "$PARSED_FORMULA_PAIR"

test "$(jq -cS '.body' "$PARSED_FORMULA_PAIR")" = \
  "$(jq -cS '.body' "$RENDERED_FORMULA_PAIR")"
test "$(jq -r '.expression' "$PARSED_FORMULA_PAIR")" = \
  "$(jq -r '.expression' "$RENDERED_FORMULA_PAIR")"
```

The second committed Formula also demonstrates literal `1` and exact identifier quoting:

```sh
jq '.modules[0].formulas[]
  | select(.id == "effective-accuracy")
  | {body, expression}' examples/schema2/rpg-combat-cast/model-source.json
```

Its local `minimum-accuracy` must appear as `` `minimum-accuracy` ``. The unquoted spelling is
parsed as subtraction and never resolves as that local. Operation spelling and ordered ports come
from the selected package releases: `-`, `floor_zero(...)`, `max(...)`, and the `identity(...)`
witness used in section 7 below. Host code owns no parallel operation-notation table.

## 4. Build the Resolved Model and RIR

Build the model and save the returned artifact-set receipt:

```sh
export MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/model-set-receipt.json"

uv run gda-balancing model build \
  examples/schema2/rpg-combat-cast/model-source.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json" \
  --invocation-key "$MODEL_BUILD_INVOCATION_KEY" \
  | tee "$MODEL_SET_RECEIPT"
```

The command resolves the source against the exact active Kernel and LDB, then atomically publishes
one complete artifact set. `--out` receives a convenience copy of the primary
`resolved-model` member; stdout is the receipt for the complete set.

List the published members:

```sh
jq -r '.member_locators[] | [.logical_name, .locator] | @tsv' \
  "$MODEL_SET_RECEIPT"
```

The model build publishes:

| Artifact | What it tells you |
|---|---|
| `package-lock` | Exact selected package closure, versions, operations, profiles, and bindings |
| `rir-semantic-payload` | Canonical reachable semantics used for execution |
| `resolved-model` | Immutable wrapper binding the Kernel, LDB, Package Lock, and RIR |
| `capability-manifest` | Capabilities selected by this exact model |
| `debug-map` | Non-semantic mapping back to authored source |
| `model-explanation` | Stored non-semantic Formula and Operation explanation derived from the exact RIR and Debug Map |
| `resolution-receipt` | Provenance for dependency and capability resolution |
| `build-receipt` | Provenance tying the source and all build artifacts together |

Inspect the stored explanation without regenerating or executing anything:

```sh
uv run gda-balancing model inspect \
  "$MODEL_SET_RECEIPT" \
  --format indented \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"

jq '{
  formulas: [.formula_explanations[] | {
    id,
    body,
    expression,
    closure,
    evaluation_sites
  }],
  operations: [.operation_explanations[] | {
    id,
    formula_evaluation_sites,
    effects,
    outcomes
  }]
}' "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"
```

`formula_explanations` preserves the selected Formula declarations, bindings, operands, contexts,
results, canonical expressions, refusals, and resource charges. `operation_explanations` preserves control/effect/RNG/
outcome/commit boundaries and refers to Formula-site identities without copying Formula semantics.
The explanation, Debug Map, RIR, and receipts are generated immutable artifacts: inspect them, but
edit `model-source.json` and rebuild instead of editing anything in the artifact store.

Inspect the selected combat operation in the RIR:

```sh
export RIR_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "rir-semantic-payload")
    | .locator' "$MODEL_SET_RECEIPT"
)"

jq '{
  content_identity,
  semantic_identity,
  formulas: [.formulas[] | {id, body, expression}]
}' "$RIR_PATH"

jq '{
  content_identity,
  rir_content_identity,
  rir_semantic_identity
}' "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json"

jq '.selected_semantics.operations[]
  | select(.definition.id == "game.combat.cast-v1")
  | .definition' "$RIR_PATH"
```

The operation shows the executable relationship between the authored values:

```text
hit_score = accuracy + hit_roll
hit when hit_score >= target_defense
critical when critical_roll <= critical_threshold
damage = max((critical ? base_damage * 2 : base_damage) - target_defense, 0)
target_health = target_health - damage
actor_mana = actor_mana - action_cost
```

The three JSON surfaces now show the same paired data:

- authored Model Source: `.modules[].formulas[].body` beside `.expression`;
- stored RIR: `.formulas[].body` beside `.expression`;
- authenticated Model explanation: `.formula_explanations[].body` beside `.expression`.

RIR `content_identity` covers the complete canonical RIR, including expression bytes. RIR
`semantic_identity` excludes the notation-only projection and represents executable behavior.
Resolved Model binds both, so notation-only changes cannot masquerade as the same exact wrapper,
while behavior-equivalence checks do not treat spelling as new semantics.

### Demonstrate AST/expression drift refusal

An admitted Model Source must already contain the exact canonical pair. Make only the expression
bytes drift and check through the public boundary:

```sh
export DRIFTED_MODEL_SOURCE="$GDA_BALANCING_TUTORIAL_ROOT/model-source-drifted.json"
export DRIFT_REFUSAL="$GDA_BALANCING_TUTORIAL_ROOT/model-source-drift-refusal.json"

jq '(.modules[0].formulas[]
  | select(.id == "mitigated-damage")
  | .expression) += " "' \
  examples/schema2/rpg-combat-cast/model-source.json > "$DRIFTED_MODEL_SOURCE"

set +e
uv run gda-balancing model check "$DRIFTED_MODEL_SOURCE" > "$DRIFT_REFUSAL"
export DRIFT_EXIT="$?"
set -e

test "$DRIFT_EXIT" -eq 2
jq '.error.diagnostics[0] | {code, primary}' "$DRIFT_REFUSAL"
```

The exact Diagnostic is `language.formula_notation_mismatch` at the Formula's `expression`
pointer. Admission neither chooses a side nor repairs it; use `formula parse` or `formula render`
to produce a pair, then replace both adjacent members together.

## 5. Check the Experiment Specification

The companion [`experiment.json`](experiment.json) binds the exact source, Build receipt,
Resolved Model, Package Lock, and RIR identities produced by the build. Its `one-cast` scenario
authors an external-input root and a `combat.plan-casts` transition root, then assigns the canonical
union of their seven required initialization targets exactly once. It also owns:

- the `standard.exact-int64-event-v1` Runtime profile request;
- the effective RNG algorithm and seed;
- the `one-cast` Scenario Input assignments and Named random streams;
- the `target_health_remaining` Metric;
- its target range and the all-Metrics acceptance policy.

The Event plan deliberately separates concepts that are easy to conflate:

- `root_event_ref` is the stable authored name in `experiment.json`; Runtime maps each root to its
  own `event_id` before dispatch. Scheduled children have Runtime ids and parent/call-site
  provenance, but no authored root reference.
- `payload` is checked against the selected entrypoint's independently derived Event-local
  contract. Here it explicitly overrides `base_damage` with the same tutorial value for the
  `plan-casts` Event; trying to put writable `actor_mana` state there refuses before Runtime.
- Logical time orders modeled Events; it is not a tick count and is unrelated to node-step or
  per-Event resource budgets. Here the roots execute at time `0`, and the surviving child executes
  at time `1`.
- Equal logical times are legal and serialized by phase (`input`, `transition`, `observation`),
  priority, then enqueue sequence. Each Event reads the Snapshot committed by the preceding Event,
  including another Event at the same logical time.
- `queue-drained` ends this scenario after the pending queue empties. `event-count` is the other
  admitted multi-step terminal condition; neither turns separate scenarios into sequential steps.
  Multiple scenarios remain independent replications with separate Snapshot 0 values and queues.
- Runtime `step` advances to the next observation or logical boundary. Queue, total-Event,
  zero-time-depth, logical-time, node-step, and per-Event budgets remain separate profile members.

Check it before execution:

```sh
uv run gda-balancing experiment check \
  examples/schema2/rpg-combat-cast/experiment.json \
  | jq .
```

A successful check reports:

```json
{
  "checked": true,
  "experiment_identity": "sha256:...",
  "resolved_model_identity": "sha256:...",
  "runtime_profile": "standard.exact-int64-event-v1"
}
```

This stage verifies structure, exact authority and Model bindings, entrypoint selection, complete
Scenario Input assignment, Named streams, Runtime profile requirements, and Metric definitions. It
does not execute the combat Event and does not publish an artifact set.

## 6. Run and inspect the Experiment

Execute the admitted Experiment and save its artifact-set receipt:

```sh
export EXPERIMENT_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-set-receipt.json"

uv run gda-balancing experiment run \
  examples/schema2/rpg-combat-cast/experiment.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/evaluation-run.json" \
  --invocation-key "$EXPERIMENT_RUN_INVOCATION_KEY" \
  | tee "$EXPERIMENT_SET_RECEIPT"
```

For an accepted Experiment, `--out` receives the primary `evaluation-run`; the complete
publication also contains:

| Artifact | What to inspect |
|---|---|
| `event-trace` | Root mapping, complete ordering keys, schedule/cancel provenance, observations, RNG draws, and state before/after |
| `snapshot-series` | Initial state and every committed Event boundary, each with a stable Snapshot identity |
| `metric-dataset` | Metric values, provenance, target comparison, and status |
| `reproduction-receipt` | Exact Model, RIR, Runtime profile, evaluator, seed, and input identities |
| `resolved-runtime-profile` | Runtime definition bound to the evaluator, platform, budgets, numeric policy, and RNG policy |
| `evaluator-capability-manifest` | Runtime features implemented by this evaluator build |
| `evaluation-run` | Identities of the complete evaluated result and its accepted outcome |

Resolve the three most useful paths from the receipt:

```sh
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

Inspect the complete Event sequence:

```sh
jq '.events[] | {
  event_id,
  root_event_ref,
  parent_event_id,
  ordering_key,
  entrypoint,
  operation,
  calls,
  schedules,
  cancellations,
  observation,
  outcome,
  rng_draws,
  state_before,
  state_after
}' "$EVENT_TRACE_PATH"
```

Inspect the committed snapshots:

```sh
jq '.snapshots' "$SNAPSHOT_PATH"
```

Inspect the evaluated Metrics:

```sh
jq '.samples[] | {
  metric,
  value,
  within_target,
  provenance
}' "$METRIC_PATH"
```

With the committed example values, the external-input root changes defense from `30` to `20`.
The surviving critical cast then changes target health from `100` to `30`, and actor mana from
`35` to `26`. These tutorial inputs are
intentionally independent from the package's normative conformance-vector inputs: the public loop
consumes the same admitted semantics without treating package evidence as product configuration.

The committed values deliberately make both random branches reachable:

- `accuracy = 25` and `target_defense = 30`, so a hit roll of at least `5` hits;
- `critical_threshold = 50`, so a critical roll of at most `50` doubles base damage.

Seed `20260726` draws hit `10` and critical `45`, producing the committed critical hit. To prove
that the seed affects modeled behavior—not just trace metadata—run the same Experiment with seed
`4`:

```sh
jq '.seed.value = 4' \
  examples/schema2/rpg-combat-cast/experiment.json \
  > "$GDA_BALANCING_TUTORIAL_ROOT/experiment-seed-4.json"

export SEED_4_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
export SEED_4_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/seed-4-set-receipt.json"

uv run gda-balancing experiment run \
  "$GDA_BALANCING_TUTORIAL_ROOT/experiment-seed-4.json" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/seed-4-evaluation-run.json" \
  --invocation-key "$SEED_4_RUN_INVOCATION_KEY" \
  | tee "$SEED_4_SET_RECEIPT"
```

Seed `4` draws hit `22` and critical `72`. It still hits, but takes the non-critical branch:
target health is `75`, and actor mana is `26`. The two fixed seeds therefore
exercise different critical outcomes and different terminal states while keeping the Model,
scenario assignments, and Metric policy unchanged. A different seed can still produce the same
result when its draws remain on the same modeled branches.

## 7. Edit a Formula and run again

An Experiment assignment tunes one run without changing model semantics. This time, change the
game's numeric policy itself: replace the existing `mitigated-damage` Formula with a pure identity
call that ignores mitigation. The structured edit changes no Operation control, RNG, effects,
outcomes, or host code:

```sh
export EDITED_MODEL_SOURCE="$GDA_BALANCING_TUTORIAL_ROOT/model-source-unmitigated.json"

jq '
  (.manifest.version) = "1.1.0"
  | (.modules[0].formulas[]
      | select(.id == "mitigated-damage")) |=
    (.body = {
      "nodes": [{
        "id": "unmitigated-damage",
        "node": "operation-call",
        "operation": {
          "package": "core.quantity",
          "version": "2.1.0",
          "id": "quantity.identity"
        },
        "arguments": [{
          "port": "value",
          "operand": {
            "kind": "parameter",
            "parameter": "damage_before_defense"
          }
        }],
        "result": .result
      }],
      "result": {
        "kind": "local",
        "local": "unmitigated-damage"
      }
    }
    | .expression = "let `unmitigated-damage` = identity(damage_before_defense);\n`unmitigated-damage`")
' examples/schema2/rpg-combat-cast/model-source.json > "$EDITED_MODEL_SOURCE"
```

Build and inspect the edited model with a new Invocation key:

```sh
export EDITED_MODEL_BUILD_INVOCATION_KEY="$(openssl rand -hex 32)"
export EDITED_MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/edited-model-set-receipt.json"

uv run gda-balancing model build \
  "$EDITED_MODEL_SOURCE" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/edited-resolved-model.json" \
  --invocation-key "$EDITED_MODEL_BUILD_INVOCATION_KEY" \
  | tee "$EDITED_MODEL_SET_RECEIPT"

uv run gda-balancing model inspect \
  "$EDITED_MODEL_SET_RECEIPT" \
  --format indented \
  | jq '.formula_explanations[]
    | select(.id == "mitigated-damage")
    | {id, body, expression, closure, evaluation_sites}'
```

The Formula, both RIR identities, Resolved Model, Build receipt, and Model explanation identities
change because this is a semantic body edit, not a notation-only edit. The Kernel, LDB, selected
package releases, Package Lock, compiler build, and evaluator build stay fixed: the edit uses the
already admitted Formula language and pure `quantity.identity` Operation.

An exact Experiment cannot silently follow that new model. First make a deliberately stale
specification by changing only its source identity; `experiment check` refuses because the old
Build receipt and Resolved Model belong to the baseline source:

```sh
export EDITED_BUILD_RECORD_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "build-receipt")
    | .locator' "$EDITED_MODEL_SET_RECEIPT"
)"
export STALE_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/stale-experiment.json"

jq --slurpfile build "$EDITED_BUILD_RECORD_PATH" \
  '.model.source_identity = $build[0].source_identity' \
  examples/schema2/rpg-combat-cast/experiment.json \
  > "$STALE_EXPERIMENT"

set +e
uv run gda-balancing experiment check "$STALE_EXPERIMENT"
export STALE_EXIT="$?"
set -e
test "$STALE_EXIT" -eq 2
```

Create a newly identified exact Experiment by binding every edited build identity. This particular
Formula edit also removes the `maximum` and `subtract` instructions from the reachable evaluator
closure; all other scenario, seed, Metric, and acceptance intent stays unchanged:

```sh
export EDITED_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-unmitigated.json"

jq --slurpfile build "$EDITED_BUILD_RECORD_PATH" '
  .version = "1.1.0"
  | .model = {
      "source_identity": $build[0].source_identity,
      "build_receipt_identity": $build[0].content_identity,
      "resolved_model_identity": $build[0].resolved_model_identity,
      "package_lock_identity": $build[0].package_lock_identity,
      "rir_identity": $build[0].rir_identity
    }
  | .runtime.required_evaluator.instruction_nodes -=
      ["maximum", "subtract"]
' examples/schema2/rpg-combat-cast/experiment.json > "$EDITED_EXPERIMENT"

uv run gda-balancing experiment check "$EDITED_EXPERIMENT" | jq .
```

Run the edited Formula and read the terminal-health Metric:

```sh
export EDITED_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
export EDITED_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/edited-set-receipt.json"

uv run gda-balancing experiment run \
  "$EDITED_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/edited-evaluation-run.json" \
  --invocation-key "$EDITED_RUN_INVOCATION_KEY" \
  | tee "$EDITED_SET_RECEIPT"

export EDITED_METRIC_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "metric-dataset")
    | .locator' "$EDITED_SET_RECEIPT"
)"
export EDITED_TRACE_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "event-trace")
    | .locator' "$EDITED_SET_RECEIPT"
)"

jq '.samples[]
  | select(.metric == "target_health_remaining")
  | {metric, value, within_target}' "$EDITED_METRIC_PATH"
jq '.events[]
  | select(.operation == "game.combat.cast-v1")
  | .state_after' "$EDITED_TRACE_PATH"
```

With the same seed and assignments, target health falls from `30` to `10`. Edit Model Source when
changing a game's numeric policy. Publish a new Domain
package only when changing reusable mechanic contracts such as Operation ports, Formula slots,
control/effects, permitted refusals, or resource budgets.

## 8. Exercise a rejected Verdict

An admitted and fully executed Experiment can still fail its declared Metric targets. Create a
copy whose terminal-health target is impossible for this scenario:

```sh
jq '(.metrics[]
  | select(.id == "target_health_remaining")
  | .target) = {"minimum": 1000, "maximum": 1000}' \
  examples/schema2/rpg-combat-cast/experiment.json \
  > "$GDA_BALANCING_TUTORIAL_ROOT/experiment-rejected.json"

export REJECTED_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
export REJECTED_RESULT="$GDA_BALANCING_TUTORIAL_ROOT/rejected-result.json"

set +e
uv run gda-balancing experiment run \
  "$GDA_BALANCING_TUTORIAL_ROOT/experiment-rejected.json" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/rejected-primary.json" \
  --invocation-key "$REJECTED_RUN_INVOCATION_KEY" \
  > "$REJECTED_RESULT"
export REJECTED_EXIT="$?"
set -e

test "$REJECTED_EXIT" -eq 1
jq '{outcome, failed_metrics, artifact_set}' "$REJECTED_RESULT"
```

Exit status `1` is a completed negative Verdict, not a usage or runtime refusal. The result names
`target_health_remaining` in `failed_metrics` and publishes a typed `experiment-verdict` artifact set with
the trace, snapshots, Metrics, reproduction receipt, Runtime profile, and evaluator manifest. It
does not publish a false `evaluation-run` success artifact.

## 9. Understand the artifact store

`GDA_BALANCING_STORE_DIR` is the durable local publication store. If it is unset, the default is
`$XDG_STATE_HOME/gda-balancing/store-v2`, or
`~/.local/state/gda-balancing/store-v2` when `XDG_STATE_HOME` is unset.

After the build and run above, its relevant shape is:

```text
$GDA_BALANCING_STORE_DIR/
├── invocations/
│   ├── <model-build-descriptor-hash>/
│   │   └── <MODEL_BUILD_INVOCATION_KEY>/
│   │       ├── package-lock.json
│   │       ├── rir-semantic-payload.json
│   │       ├── resolved-model.json
│   │       ├── capability-manifest.json
│   │       ├── debug-map.json
│   │       ├── model-explanation.json
│   │       ├── resolution-receipt.json
│   │       ├── build-receipt.json
│   │       ├── artifact-set-manifest.json
│   │       ├── artifact-set-receipt.json
│   │       └── publication-index.json
│   └── <experiment-run-descriptor-hash>/
│       └── <EXPERIMENT_RUN_INVOCATION_KEY>/
│           ├── event-trace.json
│           ├── snapshot-series.json
│           ├── metric-dataset.json
│           ├── reproduction-receipt.json
│           ├── resolved-runtime-profile.json
│           ├── evaluator-capability-manifest.json
│           ├── evaluation-run.json
│           ├── artifact-set-manifest.json
│           ├── artifact-set-receipt.json
│           └── publication-index.json
├── anchors/
│   ├── <model-build-descriptor-hash>/
│   │   └── <MODEL_BUILD_INVOCATION_KEY>.json
│   └── <experiment-run-descriptor-hash>/
│       └── <EXPERIMENT_RUN_INVOCATION_KEY>.json
└── locks/
    ├── <model-build-descriptor-hash>/
    │   └── <MODEL_BUILD_INVOCATION_KEY>.lock
    └── <experiment-run-descriptor-hash>/
        └── <EXPERIMENT_RUN_INVOCATION_KEY>.lock
```

The names have precise meanings:

- **Descriptor hash**: the receipt's `descriptor_identity` with the `sha256:` prefix removed. It
  separates artifact sets produced by different public commands.
- **Invocation key**: the exact 64-character value supplied to `--invocation-key`. It names one
  retry-safe publication beneath that descriptor.
- **Anchor key**: never appears in a path. It is the HMAC key used to authenticate the anchor file,
  which binds the descriptor, Invocation key, canonical command input, and committed receipt.
- **`invocations/`**: immutable committed artifact-set members and their framing artifacts.
- **`anchors/`**: authenticated publication indexes used to discover and verify committed sets.
- **`locks/`**: per-descriptor, per-Invocation-key serialization locks for concurrent/retried
  publication.

Confirm the mapping for the Experiment run:

```sh
export EXPERIMENT_DESCRIPTOR_HASH="$(
  jq -r '.descriptor_identity | sub("^sha256:"; "")' \
  "$EXPERIMENT_SET_RECEIPT"
)"

printf '%s\n' \
  "$GDA_BALANCING_STORE_DIR/invocations/$EXPERIMENT_DESCRIPTOR_HASH/$EXPERIMENT_RUN_INVOCATION_KEY" \
  "$GDA_BALANCING_STORE_DIR/anchors/$EXPERIMENT_DESCRIPTOR_HASH/$EXPERIMENT_RUN_INVOCATION_KEY.json" \
  "$GDA_BALANCING_STORE_DIR/locks/$EXPERIMENT_DESCRIPTOR_HASH/$EXPERIMENT_RUN_INVOCATION_KEY.lock"
```

On macOS, locators may show `/private/tmp/...` when the environment variable contains `/tmp/...`;
the CLI normalizes that symlink, and both paths refer to the same directory.

`artifact-set-manifest.json` lists the logical members and their content identities.
`artifact-set-receipt.json` binds those members to local locators.
`publication-index.json` binds the descriptor and Invocation key to the canonical command-input
identity and committed receipt.

The `--out` file is outside this hierarchy and is only a materialized copy of the primary member.
It is not a replacement for the complete committed artifact set.

Store members use canonical one-line JSON because their exact bytes are verified during recovery.
Use `jq` to display them, but do not reformat or overwrite files inside the store:

```sh
jq . "$EVENT_TRACE_PATH"
jq -C . "$EVENT_TRACE_PATH" | less -R
```

## 10. How the architecture fits together

The tutorial crosses several Standard Schema 2.0 boundaries:

| Module or artifact | Beginner's mental model |
|---|---|
| Schema-major Kernel Specification | The small, versioned foundation: canonical identity, irreducible numeric/RNG laws, Event-transition primitives, and rules for admitting an LDB |
| Language Definition Bundle (LDB) | The complete language content under that Kernel: schemas, types, packages, operations, profiles, diagnostics, and machine-readable rules |
| Model Source Package | Your editable game numeric definitions, exact Formula `body`/`expression` pairs, and dependency requirements |
| Package Lock | The exact selected package dependency closure and the capability, operation, and profile bindings recorded for this build |
| RIR semantic payload | The selected reachable Formula pairs and executable semantics, with distinct exact-content and behavior identities |
| Resolved Model | The immutable execution authority binding Kernel, LDB, Lock, and both RIR identities |
| Experiment Specification | The scenario and evaluation authority: exact Model bindings, inputs, seed, Metrics, targets, and acceptance |
| Runtime profile definition | The LDB-owned execution policy for scheduler/effects, numeric behavior, RNG, and budgets |
| Resolved Runtime profile | That policy bound to the exact Model/RIR, evaluator build, platform, and concrete execution scope |
| Runtime and evaluator | The conforming implementation that admits the profile, executes Events, and emits traces, snapshots, Metrics, and an Evaluation run |

The authority split matters:

- the Kernel defines how the language and irreducible runtime laws are interpreted;
- the sealed LDB root defines exact membership, while its child releases define standard and
  Domain behavior such as `game.resource`, `game.check`, and `game.combat`;
- the Model Source defines this game's numeric vocabulary;
- the Experiment defines what scenario to run and what evidence counts as acceptable;
- the Python host implementation executes those authorities but does not redefine them.

That separation is why changing a scenario value can produce new evaluation evidence without
silently changing the Model, and why every run records enough identities to explain and reproduce
its exact scope.

The dogfooding result is deliberately narrow:

- **Confirmed:** exact Formula body/expression round trips, atomic Event commits, root mapping,
  deterministic ordering, schedule/cancel provenance, derived observations, and artifact recovery
  all execute through the public CLI.
- **Refined and adopted:** the example observes the scheduled child's terminal Snapshot. A
  scheduled Operation is not a Model entrypoint invocation, so it does not rebind its return value
  to the `combat.cast` entrypoint's `damage_dealt` output Symbol.
- **Authored-example-only:** the mana, hit, critical, defense, and cast narrative demonstrates the
  generic contracts but proves no general RPG, Effect, Replay, or Evidence coverage.
- **Gap-opened:** none. The example stays within the admitted scheduler and observation contracts;
  broader scheduler-conformance work remains outside this slice.

## Troubleshooting

### `invalid_argument` for a key

Both `GDA_BALANCING_ANCHOR_KEY` and every Invocation key must contain exactly 64 lowercase
hexadecimal digits:

```sh
openssl rand -hex 32
```

### `invocation_key_conflict`

The key is already committed for different canonical input. Restore the original input to recover
that result, or generate a new Invocation key for the changed input.

### The Experiment cannot resolve its Model artifacts

Use the same `GDA_BALANCING_STORE_DIR` and `GDA_BALANCING_ANCHOR_KEY` that were active during
`model build`. Run the build first, and confirm that the identities in `experiment.json` match the
published Build receipt, Resolved Model, Package Lock, and RIR.

### The JSON is one long line

This is canonical artifact encoding, not missing data. Format it at display time:

```sh
jq . path/to/artifact.json
```

Do not replace a committed store member with the formatted copy; recovery requires canonical
bytes.

### `language.formula_notation_mismatch`

The adjacent `body` and `expression` are not the same canonical Formula. Run `formula render` from
the body or `formula parse` from the expression under the exact module/package context, then use
both members from that successful output. Adding whitespace directly to an admitted pair is still
drift because artifact admission requires canonical expression bytes.
