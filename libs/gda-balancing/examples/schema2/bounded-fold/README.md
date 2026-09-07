# Filter, count and preserve order

This example keeps integers smaller than 3, preserving their order and duplicates.
It counts the selected items and combines the original input from left to right with
`next = 10 * accumulator + item`, starting at zero.

For `[1, 2, 3, 4]`, the final state contains `[1, 2]`, count `2`, and ordered value
`1234`. Changing the last item to `5` produces `1235`; reversing the input produces
`4321`. The List accepts at most four integers. An empty input produces an empty
selection, count `0`, and ordered value `0`.

Run from the package directory with `uv`, `jq`, and `openssl` available:

```sh
RUN_DIR="$(mktemp -d /tmp/gda-bounded-fold.XXXXXX)"
export GDA_BALANCING_STORE_DIR="$RUN_DIR/store"
export GDA_BALANCING_ANCHOR_KEY="$(openssl rand -hex 32)"
uv run gda-balancing model build examples/schema2/bounded-fold/model-source.json --out "$RUN_DIR/model" --invocation-key "$(openssl rand -hex 32)" | tee "$RUN_DIR/model-receipt.json"
RIR_PATH="$(jq -r '.member_locators[] | select(.logical_name == "rir-semantic-payload") | .locator' "$RUN_DIR/model-receipt.json")"
uv run gda-balancing experiment check examples/schema2/bounded-fold/experiment.json --rir "$RIR_PATH"
uv run gda-balancing experiment run examples/schema2/bounded-fold/experiment.json --rir "$RIR_PATH" --out "$RUN_DIR/run" --invocation-key "$(openssl rand -hex 32)"
```

The run publishes the Event trace, committed snapshots, and terminal observations
`selected_count` and `ordered_value`.
