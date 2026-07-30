# RPG combat-cast tuning loop

This tutorial walks through the first bounded Standard Schema 2.0 RPG example from editable
numeric design to an evaluated combat result:

```text
Model Source Package
    + Kernel Specification and Language Definition Bundle
    |
    |  model build
    v
Package Lock + RIR semantic payload + Resolved Model
    |
    |  experiment check
    v
Admitted Experiment Specification
    |
    |  experiment run
    v
Event trace + Snapshots + Metrics + Evaluation run
```

The example models one `game.combat.cast-v1` event. A character spends mana, rolls for hit and
critical outcome, deals damage after defense, and updates the target's health. The files are:

- [`model-source.json`](model-source.json): the editable numeric model. It declares symbols such
  as mana, damage, defense, and health, their roles and domains, its package requirements, and the
  `combat.cast` entrypoint that explicitly binds those symbols to Operation ports.
- [`experiment.json`](experiment.json): one exact scenario and evaluation policy. It binds the
  built Model artifacts, selects `combat.cast`, assigns its generated Scenario Input Contract,
  supplies a seed, and defines the Metrics and acceptance targets.

This is a beginner-oriented product-feedback slice, not proof of general RPG or Roguelike
coverage.

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

- `core.quantity@2.0.0` supplies the generic `Quantity` constructor imported by the source;
- `game.combat@1.0.0` supplies the composed `game.combat.cast-v1` operation.

`game.combat` declares `game.resource`, `game.check`, and `standard.runtime` as required
dependencies. Resolution closes that transitive graph and selects capability providers from the
whole selected closure, so the Model Source does not repeat those indirect dependencies. The
mechanics remain independently owned: resource spending belongs to `game.resource`, hit and
critical checks belong to `game.check`, and damage plus cast composition belong to `game.combat`.
No RPG-wide value constructor or genre umbrella is involved.

Its symbols demonstrate three lifecycle roles:

| Role | Symbols in this example | Meaning |
|---|---|---|
| `state` | `actor_mana`, `target_health` | Persistent values changed by an Event |
| `parameter` | `action_cost`, `accuracy`, `base_damage`, `critical_threshold` | Designer-controlled values supplied to the operation |
| `input` | `target_defense` | Scenario input read by the operation |

All seven values use exact signed-64-bit integer semantics and an admitted range of `0..1000`.
The Model Source owns these definitions; it does not contain a scenario, seed, Metric target, or
runtime result.

The Model Source also owns the `combat.cast` entrypoint. `game.combat.cast-v1` is the reusable LDB
Operation and therefore owns formal ports such as `hit_defense` and `damage_mitigation`. The
entrypoint binds both of those read-only ports explicitly to the one game-owned
`target_defense` symbol; matching names are neither required nor used for resolution. The
LDB assignment policy marks that Symbol as a required Experiment input, so RIR exports one exact
target even though two ports consume it; the Experiment assigns that target once. A Model-fixed
value would instead appear as a Model initializer, and an admitted override mode would expose one
optional Experiment target over that explicit default. This is deliberate DRY:

```text
LDB Operation formal ports
    -> Model entrypoint binds game-owned symbols
        -> RIR derives exact call sites and Scenario Input Contract
            -> Experiment assigns only those contract members
```

## 3. Build the Resolved Model and RIR

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
| `resolution-receipt` | Provenance for dependency and capability resolution |
| `build-receipt` | Provenance tying the source and all build artifacts together |

Inspect the selected combat operation in the RIR:

```sh
export RIR_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "rir-semantic-payload")
    | .locator' "$MODEL_SET_RECEIPT"
)"

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

## 4. Check the Experiment Specification

The companion [`experiment.json`](experiment.json) binds the exact source, Build receipt,
Resolved Model, Package Lock, and RIR identities produced by the build. Its `one-cast` scenario
selects the `combat.cast` Model entrypoint and assigns all seven required symbol identities exactly
once. It also owns:

- the `standard.exact-int64-event-v1` Runtime profile request;
- the effective RNG algorithm and seed;
- the `one-cast` Scenario Input assignments and Named random streams;
- the `damage_dealt` and `target_health_remaining` Metrics;
- their target ranges and the all-Metrics acceptance policy.

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

## 5. Run and inspect the Experiment

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
| `event-trace` | Ordered outcomes, intermediate facts, RNG draws, and state before/after |
| `snapshot-series` | Initial and committed terminal state |
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

Inspect the combat transition:

```sh
jq '.events[] | {
  entrypoint,
  operation,
  calls,
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

With the committed example values, `base_damage = 45` produces `damage_dealt = 60`; target health
changes from `100` to `40`, and actor mana changes from `35` to `26`. These tutorial inputs are
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
damage is `15`, target health is `85`, and actor mana is `26`. The two fixed seeds therefore
exercise different critical outcomes and different terminal states while keeping the Model,
scenario assignments, and Metric policy unchanged. A different seed can still produce the same
result when its draws remain on the same modeled branches.

## 6. Tune a value and run again

Create a working copy that raises `base_damage` from `45` to `65`:

```sh
jq '(.scenarios[0].assignments[]
  | select(.target.name == "base_damage")
  | .value) = 65' \
  examples/schema2/rpg-combat-cast/experiment.json \
  > "$GDA_BALANCING_TUTORIAL_ROOT/experiment-damage-65.json"
```

The Experiment input changed, so generate a new Invocation key and choose new output/receipt
paths:

```sh
export TUNED_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
export TUNED_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/tuned-set-receipt.json"

uv run gda-balancing experiment check \
  "$GDA_BALANCING_TUTORIAL_ROOT/experiment-damage-65.json" \
  | jq .

uv run gda-balancing experiment run \
  "$GDA_BALANCING_TUTORIAL_ROOT/experiment-damage-65.json" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/tuned-evaluation-run.json" \
  --invocation-key "$TUNED_RUN_INVOCATION_KEY" \
  | tee "$TUNED_SET_RECEIPT"
```

Read the tuned Metric:

```sh
export TUNED_METRIC_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "metric-dataset")
    | .locator' "$TUNED_SET_RECEIPT"
)"

jq '.samples[]
  | select(.metric == "damage_dealt")
  | {metric, value, within_target}' "$TUNED_METRIC_PATH"
```

For the committed seed and branch outcome, damage increases from `60` to `100`. The Experiment,
trace, snapshots, Metrics, reproduction receipt, and Resolved Runtime profile receive new content
identities, while the exact Model, Package Lock, and RIR bindings remain unchanged. This is the
core tuning loop: change scenario/design intent, check it, run it, inspect evidence, and repeat.

If you instead change `model-source.json`—for example, a symbol's type, role, or admitted
domain—you must run `model build` again and create an Experiment Specification that binds the new
build identities.

## 7. Exercise a rejected Verdict

An admitted and fully executed Experiment can still fail its declared Metric targets. Create a
copy whose damage target is impossible for this scenario:

```sh
jq '(.metrics[]
  | select(.id == "damage_dealt")
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
`damage_dealt` in `failed_metrics` and publishes a typed `experiment-verdict` artifact set with
the trace, snapshots, Metrics, reproduction receipt, Runtime profile, and evaluator manifest. It
does not publish a false `evaluation-run` success artifact.

## 8. Understand the artifact store

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

## 9. How the architecture fits together

The tutorial crosses several Standard Schema 2.0 boundaries:

| Module or artifact | Beginner's mental model |
|---|---|
| Schema-major Kernel Specification | The small, versioned foundation: canonical identity, irreducible numeric/RNG laws, Event-transition primitives, and rules for admitting an LDB |
| Language Definition Bundle (LDB) | The complete language content under that Kernel: schemas, types, packages, operations, profiles, diagnostics, and machine-readable rules |
| Model Source Package | Your editable game numeric definitions and dependency requirements |
| Package Lock | The exact selected package dependency closure and the capability, operation, and profile bindings recorded for this build |
| RIR semantic payload | The canonical executable meaning of the selected, reachable model semantics |
| Resolved Model | The immutable execution authority binding Kernel, LDB, Lock, and RIR identities |
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
