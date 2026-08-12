# Structured values through Model build and Runtime

This tutorial runs one neutral selection flow through the public Standard Schema 2.x path:

```text
Enum + Record + List + Ref values in Model Source and Experiment
    |
    v
model check/build/inspect -> typed RIR and Model explanation
    |
    v
experiment check/run -> deterministic lookup and equality
    |
    v
Event trace + committed Snapshots + numeric Metric
```

`standard.schema@2.4.0` owns the generic structured-value rules. The
`standard.conformance.structured@2.0.0` Package Release owns the nominal `CandidateKind`,
`CandidateRef`, `Candidate`, `SelectionResult`, and `SelectionState` definitions. It also owns the
bounded selection Operation. Host code does not define these types, Ref keys, lookup behavior,
equality, or selection policy.

This example is neutral. It does not define a game entity, reward, inventory, target, or query
language.

## 1. Prepare an isolated run

Prerequisites are `uv`, `jq`, and `openssl`. Run from `libs/gda-balancing`:

```bash
uv sync

export GDA_BALANCING_TUTORIAL_ROOT="$(
  mktemp -d /tmp/gda-balancing-structured-selection.XXXXXX
)"
export GDA_BALANCING_STORE_DIR="$GDA_BALANCING_TUTORIAL_ROOT/store"
export GDA_BALANCING_ANCHOR_KEY="$(openssl rand -hex 32)"
export MODEL_BUILD_INVOCATION_KEY="$(openssl rand -hex 32)"
export EXPERIMENT_RUN_INVOCATION_KEY="$(openssl rand -hex 32)"
```

Keep the anchor key stable for this store. Use a new Invocation key after you change an input.

## 2. Read and check the Model Source Package

The Model imports two nominal structured types and one Quantity type. Its entrypoint literals name
the exact `CandidateKind` and `CandidateRef` coordinates directly:

```bash
jq '.modules[0] | {imports, symbols}' \
  examples/schema2/structured-selection/model-source.json

jq '.entrypoints[] | {id, operation, arguments, result}' \
  examples/schema2/structured-selection/model-source.json
```

The structured Symbols omit Quantity-only fields such as `representation`, `unit`, and `domain`.
Their imported nominal definitions supply the exact value contracts. The entrypoint literals use
explicit `{type, value}` envelopes for `CandidateKind` and `CandidateRef`.

Check the source without publishing artifacts:

```bash
uv run gda-balancing model check \
  examples/schema2/structured-selection/model-source.json \
  | jq .
```

## 3. Build and inspect the typed artifacts

Build the Model and retain its artifact-set receipt:

```bash
export MODEL_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/model-set-receipt.json"

uv run gda-balancing model build \
  examples/schema2/structured-selection/model-source.json \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/resolved-model.json" \
  --invocation-key "$MODEL_BUILD_INVOCATION_KEY" \
  | tee "$MODEL_SET_RECEIPT"
```

Inspect the generated Model explanation:

```bash
uv run gda-balancing model inspect \
  "$MODEL_SET_RECEIPT" \
  --format indented \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"

jq '.declaration_explanations' \
  "$GDA_BALANCING_TUTORIAL_ROOT/model-explanation.json"
```

The explanation identifies each structured declaration with `value_kind` set to
`nominal-structured` and with its exact package, version, and type id.

Inspect the RIR literal types and selected structured semantics:

```bash
export RIR_PATH="$(
  jq -r '.member_locators[]
    | select(.logical_name == "rir-semantic-payload")
    | .locator' "$MODEL_SET_RECEIPT"
)"

jq '{
  declarations: [.declarations[]
    | select(.value_kind == "nominal-structured")],
  literals: [.entrypoints[].arguments[].operand
    | select(.kind == "literal")],
  nominal_types: [.selected_semantics.nominal_types[]
    | select(.package == "standard.conformance.structured")]
}' "$RIR_PATH"
```

RIR preserves the canonical literal envelopes and the exact nominal definitions. It does not
replace them with host classes or untyped JSON.

## 4. Check and run the Experiment

The Experiment starts with candidates A and B. Its first result is A with rank `3`. Its current
stored result is B with rank `9`. The fixed seed and named stream select list index `0`.

```bash
export STRUCTURED_EXPERIMENT=examples/schema2/structured-selection/experiment.json

uv run gda-balancing experiment check "$STRUCTURED_EXPERIMENT" | jq .

export EXPERIMENT_SET_RECEIPT="$GDA_BALANCING_TUTORIAL_ROOT/experiment-set-receipt.json"
uv run gda-balancing experiment run \
  "$STRUCTURED_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/evaluation-run.json" \
  --invocation-key "$EXPERIMENT_RUN_INVOCATION_KEY" \
  | tee "$EXPERIMENT_SET_RECEIPT"
```

Resolve the trace, Snapshot, and Metric artifacts:

```bash
export TRACE_PATH="$(
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

jq '.events[0] | {
  outcome,
  rng_draws,
  selection_result: [.facts[] | select(.name == "selection_result")],
  state_before,
  state_after
}' "$TRACE_PATH"

jq '.snapshots[-1].values' "$SNAPSHOT_PATH"
jq '.samples' "$METRIC_PATH"
```

The fixed draw selects candidate A. Runtime uses bounded List lookup, exact Ref and Enum equality,
and closed Record values. The Event replaces the structured result with A/rank `3`, commits the
same envelope to the Snapshot, and emits numeric Metric value `3`.

## 5. Edit structured data and rerun

Copy the Experiment, reverse both ordered Lists, and change candidate B's rank. Select the matching
entrypoint. No Model, package, evaluator, or host-code change is required:

```bash
export REORDERED_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/reordered-experiment.json"

jq '
  (.scenarios[0].assignments[]
    | select(.target.name == "selection_state")
    | .value.value.candidates) |= reverse
  | (.scenarios[0].assignments[]
    | select(.target.name == "selection_state")
    | .value.value.results) |= reverse
  | (.scenarios[0].assignments[]
    | select(.target.name == "selection_state")
    | .value.value.results[0].rank) = 7
  | .scenarios[0].event_plan[0].entrypoint = "structured.select-candidate-b"
' "$STRUCTURED_EXPERIMENT" > "$REORDERED_EXPERIMENT"

uv run gda-balancing experiment check "$REORDERED_EXPERIMENT" | jq .

uv run gda-balancing experiment run \
  "$REORDERED_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/reordered-evaluation.json" \
  --invocation-key "$(openssl rand -hex 32)" \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/reordered-receipt.json"
```

The RNG draw still selects index `0`. The authored order now maps that index to candidate B, and
the authored result value makes the Metric `7`. The generic Runtime code is unchanged.

## 6. Observe the guarded empty-list outcome

Remove both ordered lists. Runtime detects the empty candidate list before the draw or lookup. The
guard completes the Event with the declared gameplay outcome:

```bash
export EMPTY_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/empty-experiment.json"

jq '
  (.scenarios[0].assignments[]
    | select(.target.name == "selection_state")
    | .value.value.candidates) = []
  | (.scenarios[0].assignments[]
    | select(.target.name == "selection_state")
    | .value.value.results) = []
' "$STRUCTURED_EXPERIMENT" > "$EMPTY_EXPERIMENT"

uv run gda-balancing experiment run \
  "$EMPTY_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/empty-evaluation.json" \
  --invocation-key "$(openssl rand -hex 32)" \
  | tee "$GDA_BALANCING_TUTORIAL_ROOT/empty-receipt.json"
```

The Event outcome is `candidate-mismatch`. It consumes no RNG, publishes no Operation result, and
leaves the state and Metric value unchanged. This neutral package uses that outcome only to prove
the generic guard path. A product package owns its own gameplay vocabulary.

## 7. Observe a typed refusal and rollback

Keep the original list order but request candidate B. Runtime selects A, performs the Operation's
provisional structured writes, and then reaches the declared typed requirement. The requirement
refuses because the selected candidate does not match the expected candidate. The Event discards
all writes and the run publishes a terminal audit:

```bash
export FAILURE_EXPERIMENT="$GDA_BALANCING_TUTORIAL_ROOT/failure-experiment.json"

jq '.scenarios[0].event_plan[0].entrypoint = "structured.select-candidate-b"' \
  "$STRUCTURED_EXPERIMENT" > "$FAILURE_EXPERIMENT"

uv run gda-balancing experiment run \
  "$FAILURE_EXPERIMENT" \
  --out "$GDA_BALANCING_TUTORIAL_ROOT/failure-evaluation.json" \
  --invocation-key "$(openssl rand -hex 32)" \
  > "$GDA_BALANCING_TUTORIAL_ROOT/failure-output.json" \
  || test "$?" -eq 2

jq . "$GDA_BALANCING_TUTORIAL_ROOT/failure-output.json"
```

The command exits with status `2`. The Diagnostic code is
`standard.conformance.candidate_mismatch`. Resolve `runtime-terminal-audit` from
`.error.terminal_audit.member_locators` in the captured output. The audit shows that
`rollback.state_after` equals `rollback.state_before` and that the Runtime charged the executed
nodes. The refused Event publishes no Event Trace, Snapshot, Metric, or Operation result.

## 8. Validation scope

Automated tests validate:

- public Model check, build, and inspect;
- exact structured assignment Diagnostics and pointers;
- fixed-RNG selection and order-sensitive data changes;
- structured trace, Snapshot, and numeric Metric values;
- the empty-list gameplay outcome with no draw or lookup;
- typed-require refusal, terminal audit, rollback, and executed-node accounting; and
- production/independent-consumer parity for positive, boundary, and refusal vectors.

The [Structured selection entry](../../../docs/ARCHITECTURE.md#122-maintained-product-examples)
summarizes the architecture consequence and open boundary. This README explains how to run and
inspect the delivered behavior. It does not define the authority.

## Troubleshooting

- Keys must contain exactly 64 lowercase hexadecimal digits.
- Use the same store and anchor key for Model build and Experiment run.
- Checked-in Experiments bind the checked-in Model Source and final authority identities.
- After a Model or authority change, rebuild and update the Experiment's exact Model identities.
- Inspect `member_locators` in a receipt. The `--out` file is only a convenience copy.
