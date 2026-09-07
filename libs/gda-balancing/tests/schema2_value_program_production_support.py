"""Translate package vectors into requests to the actual Formula evaluator."""

from typing import Any

import gda_balancing.domain.runtime.execution as runtime


def evaluate_value_program_vector(
    kernel: dict[str, Any], vector: dict[str, Any], *, phase: str
) -> dict[str, Any]:
    inp = vector["input"]
    program = {
        "identity": vector["id"],
        "site": {"identity": inp["site"], "context": {"phase": phase}},
        "body": inp["instructions"],
        "result": {"name": inp["result"]},
        # Legacy vectors declare one finite instruction list, not a compiled
        # bound. This supplies its one-pass request bound; Runtime owns charges.
        "resource_bounds": {"max_steps": len(inp["instructions"])},
    }
    operands = {row["name"]: row["value"] for row in inp["operands"]}
    nodes = {
        row["id"]: row for row in kernel["meta_format"]["runtime_program"]["nodes"]
    }
    cache: dict[bytes, int] | None = {} if inp["cache"] else None
    consumed_steps = 0
    value = None
    signal = None
    site = inp["site"]
    for _ in range(inp["evaluations"]):
        try:
            result = runtime._evaluate_formula_program(
                program,
                operands,
                numeric=inp["numeric"],
                runtime_nodes=nodes,
                frame_identity=inp["site"],
                phase=phase,
                consumed_steps=consumed_steps,
                runtime_limit=inp["resource_limit"],
                cache=cache,
            )
        except runtime._InitializationProgramFault as fault:
            consumed_steps = fault.consumed_steps
            signal = fault.signal
            site = fault.evaluation_site_identity
            value = None
            break
        consumed_steps = result.consumed_steps
        value = result.value
    return {
        "cache_entries": len(cache) if cache is not None else 0,
        "charge": consumed_steps,
        "outcome": "admitted" if signal is None else "refused",
        "result": value,
        "result_artifact": signal is None,
        "signal": signal,
        "site": site,
    }
