"""Independent finite value-program interpretation for package vectors."""

from typing import Any

from gda_balancing.domain.canonical import canonical_bytes


def reference_evaluate_value_program_vector(
    vector: dict[str, Any],
) -> dict[str, Any]:
    inp = vector["input"]
    instructions = inp["instructions"]
    numeric = inp["numeric"]
    operands = {row["name"]: row["value"] for row in inp["operands"]}
    cache: dict[bytes, int] = {}
    charge = 0
    result = None
    signal = None
    site = inp["site"]
    for _ in range(inp["evaluations"]):
        charge += len(instructions)
        if charge > inp["resource_limit"]:
            signal = "step-limit"
            result = None
            break
        key = canonical_bytes(
            {
                "instructions": instructions,
                "numeric": numeric,
                "operands": [
                    {"name": name, "value": value}
                    for name, value in sorted(operands.items())
                ],
                "result": inp["result"],
                "site": inp["site"],
            }
        )
        if inp["cache"] and key in cache:
            result = cache[key]
            continue
        values = dict(operands)
        for row in instructions:
            instruction = row["instruction"]
            node = instruction["node"]
            if node == "constant":
                value = instruction["literal"]
            elif node == "copy":
                value = values[instruction["value"]]
            elif node == "add":
                value = values[instruction["left"]] + values[instruction["right"]]
            elif node == "subtract":
                value = values[instruction["left"]] - values[instruction["right"]]
            elif node == "multiply":
                value = values[instruction["left"]] * values[instruction["right"]]
            elif node == "floor-divide":
                divisor = values[instruction["right"]]
                if divisor <= 0:
                    signal = "invalid-domain"
                    site = row["evaluation_site_identity"]
                    result = None
                    break
                value = values[instruction["left"]] // divisor
            elif node == "less-than":
                value = values[instruction["left"]] < values[instruction["right"]]
            else:
                assert node == "if"
                value = values[
                    instruction[
                        "when_true"
                        if values[instruction["condition"]]
                        else "when_false"
                    ]
                ]
            if type(value) is int and not (
                numeric["minimum"] <= value <= numeric["maximum"]
            ):
                signal = "numeric-overflow"
                site = row["evaluation_site_identity"]
                result = None
                break
            values[instruction["target"]] = value
        if signal is not None:
            break
        result = values[inp["result"]]
        if inp["cache"]:
            cache[key] = result
    admitted = signal is None
    return {
        "cache_entries": len(cache),
        "charge": charge,
        "outcome": "admitted" if admitted else "refused",
        "result": result,
        "result_artifact": admitted,
        "signal": signal,
        "site": inp["site"] if admitted else site,
    }
