"""Independent behavioral adapter for Runtime evidence replay."""

import hashlib
from collections.abc import Sequence
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.runtime.projections import (
    formula_programs_reachable_from_entrypoints,
    runtime_contract,
    runtime_nodes,
)
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    StructuredValueIndex,
    admit_typed_value,
    equal_typed_values,
    is_empty_typed_value,
    lookup_selector_kind,
    lookup_typed_value,
    typed_envelope_members,
)


class ReplayInitializationProgramFault(Exception):
    """Independent replay refusal for one initialization Formula program."""

    def __init__(
        self,
        *,
        signal: str,
        program: str,
        evaluation_site_identity: str,
        frame_identity: str,
    ) -> None:
        super().__init__(signal)
        self.signal = signal
        self.program = program
        self.evaluation_site_identity = evaluation_site_identity
        self.frame_identity = frame_identity


def _admit_numeric(value: int, numeric: dict[str, Any]) -> int:
    if value < numeric["minimum"] or value > numeric["maximum"]:
        raise OverflowError("exact-int64 arithmetic overflow")
    return value


def _admit_declared_numeric(
    value: int, numeric: dict[str, Any], declaration: dict[str, Any]
) -> int:
    admitted = _admit_numeric(value, numeric)
    if declaration["domain_kind"] == "closed-interval":
        domain = cast(dict[str, int], declaration["domain"])
        if not domain["minimum"] <= admitted <= domain["maximum"]:
            raise OverflowError("value is outside its declared numeric domain")
    return admitted


def admit_declared_value(
    value: Any,
    numeric: dict[str, Any],
    declaration: dict[str, Any],
    *,
    structured_authority: StructuredValueIndex,
    structured_resource_limit: int,
) -> JsonValue:
    """Independently admit one replayed value under its declaration."""
    type_identity = cast(dict[str, str], declaration["type_identity"])
    declared_type: JsonValue = {
        "id": type_identity["symbol"],
        "package": type_identity["package"],
        "version": type_identity["version"],
    }
    if declaration.get("value_kind") == "nominal-structured":
        type_member, _value_member = typed_envelope_members(structured_authority)
        admitted = admit_typed_value(
            value,
            authority=structured_authority,
            resource_limit=structured_resource_limit,
        )
        if canonical_bytes(admitted[type_member]) != canonical_bytes(declared_type):
            raise StructuredValueFault(
                "language.structured_value_type_mismatch", "/type"
            )
        return cast(JsonValue, admitted)
    value_member = "value"
    if (
        isinstance(value, dict)
        and structured_authority.typed_envelope_profile is not None
    ):
        type_member, value_member = typed_envelope_members(structured_authority)
        if set(value) == {type_member, value_member}:
            admitted = admit_typed_value(
                value,
                authority=structured_authority,
                resource_limit=structured_resource_limit,
            )
            if canonical_bytes(admitted[type_member]) != canonical_bytes(declared_type):
                raise StructuredValueFault(
                    "language.structured_value_type_mismatch", f"/{type_member}"
                )
            value = admitted[value_member]
    if not isinstance(value, int) or isinstance(value, bool):
        raise StructuredValueFault(
            "language.structured_value_type_mismatch", f"/{value_member}"
        )
    return _admit_declared_numeric(value, numeric, declaration)


def integer_compare(comparison: str, left: int, right: int) -> bool:
    """Independently apply an admitted integer comparison."""
    if comparison == "greater-than-or-equal":
        return left >= right
    if comparison == "less-than":
        return left < right
    if comparison == "less-than-or-equal":
        return left <= right
    raise ValueError("unsupported admitted integer comparison")


def _project_runtime_integer(
    value: Any, structured_authority: StructuredValueIndex | None
) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if (
        structured_authority is None
        or structured_authority.typed_envelope_profile is None
    ):
        return None
    type_member, value_member = typed_envelope_members(structured_authority)
    if (
        isinstance(value, dict)
        and set(value) == {type_member, value_member}
        and isinstance(value[value_member], int)
        and not isinstance(value[value_member], bool)
    ):
        return cast(int, value[value_member])
    return None


def _require_runtime_integer(
    value: Any, structured_authority: StructuredValueIndex | None
) -> int:
    integer = _project_runtime_integer(value, structured_authority)
    if integer is None:
        raise ValueError("admitted numeric expression did not carry an integer")
    return integer


class ReplayNamedRng:
    """Independent Named-stream RNG consumer for Evidence replay."""

    def __init__(self, seed: int, contract: dict[str, Any]) -> None:
        if (
            contract["algorithm"] != "splitmix64-v1"
            or contract["word_bits"] != 64
            or contract["seed_encoding"] != "unsigned-modulo-2^64"
            or contract["candidate_encoding"]
            != {
                "alphabet": "0123456789abcdef",
                "case": "lowercase",
                "radix": 16,
                "width_bits": 64,
                "zero_pad": True,
            }
        ):
            raise ValueError("unsupported admitted Named-stream RNG contract")
        self._contract = contract
        self._mask = (1 << contract["word_bits"]) - 1
        self._seed = seed & self._mask
        self._states: dict[str, int] = {}
        self._indices: dict[str, int] = {}

    def snapshot(self) -> tuple[dict[str, int], dict[str, int]]:
        return dict(self._states), dict(self._indices)

    def restore(self, snapshot: tuple[dict[str, int], dict[str, int]]) -> None:
        states, indices = snapshot
        self._states = dict(states)
        self._indices = dict(indices)

    def continuation(self) -> list[dict[str, JsonValue]]:
        width = self._contract["word_bits"] // 4
        return [
            {
                "stream": stream,
                "state_hex": f"{self._states[stream]:0{width}x}",
                "next_index": self._indices[stream],
            }
            for stream in sorted(self._states)
        ]

    def encode_candidate(self, candidate: int) -> str:
        width = self._contract["candidate_encoding"]["width_bits"] // 4
        return f"{candidate:0{width}x}"

    def draw(
        self, stream: str, minimum: int, maximum: int
    ) -> tuple[int, int, int, bool]:
        if minimum > maximum:
            raise ValueError("invalid deterministic draw interval")
        if stream not in self._states:
            derivation = self._contract["stream_derivation"]
            if (
                derivation["hash"] != "sha256"
                or self._contract["stream_name_encoding"] != "utf-8"
                or derivation["combine"] != "unsigned-add-modulo-2^64"
            ):
                raise ValueError("unsupported admitted Named-stream derivation")
            digest = hashlib.sha256(stream.encode("utf-8")).digest()
            digest_slice = derivation["digest_slice"]
            start = digest_slice["offset"]
            end = start + digest_slice["length"]
            self._states[stream] = (
                self._seed + int.from_bytes(digest[start:end], derivation["byte_order"])
            ) & self._mask
            self._indices[stream] = 0
        transition = self._contract["state_transition"]
        state = (
            self._states[stream] + int(transition["increment_hex"], 16)
        ) & self._mask
        self._states[stream] = state
        mixed = state
        for step in transition["mix_steps"]:
            mixed ^= mixed >> step["xor_shift_right"]
            if "multiply_hex" in step:
                mixed = (mixed * int(step["multiply_hex"], 16)) & self._mask
        index = self._indices[stream]
        self._indices[stream] = index + 1
        sampling = self._contract["interval_sampling"]
        if (
            sampling["bounds"] != "inclusive"
            or sampling["mapping"] != "unsigned-modulo-width"
            or sampling["bias_policy"] != "accepted-modulo-bias-v1"
            or sampling["candidates_per_draw"] != 1
        ):
            raise ValueError("unsupported admitted interval-sampling law")
        return minimum + mixed % (maximum - minimum + 1), index, mixed, True


def execute_value_instruction(
    instruction: dict[str, Any],
    variables: dict[str, Any],
    numeric: dict[str, Any],
    node_contract: dict[str, Any],
    *,
    structured_authority: StructuredValueIndex | None = None,
    structured_resource_limit: int | None = None,
) -> None:
    """Independently execute one Kernel value instruction for replay."""
    semantics = cast(dict[str, Any], node_contract["semantics"])
    operator = cast(str, semantics["operator"])
    if operator == "typed-literal":
        value = instruction["literal"]
    elif operator == "copy-value":
        value = variables[cast(str, instruction["value"])]
    elif operator in {
        "integer-add",
        "integer-subtract",
        "integer-multiply",
        "integer-maximum",
    }:
        left = _require_runtime_integer(
            variables[cast(str, instruction["left"])], structured_authority
        )
        right = _require_runtime_integer(
            variables[cast(str, instruction["right"])], structured_authority
        )
        value = (
            left + right
            if operator == "integer-add"
            else left - right
            if operator == "integer-subtract"
            else left * right
            if operator == "integer-multiply"
            else max(left, right)
        )
    elif operator == "integer-compare":
        variables[cast(str, instruction["target"])] = integer_compare(
            cast(str, semantics["comparison"]),
            _require_runtime_integer(
                variables[cast(str, instruction["left"])], structured_authority
            ),
            _require_runtime_integer(
                variables[cast(str, instruction["right"])], structured_authority
            ),
        )
        return
    elif operator == "bounded-lookup":
        if structured_authority is None or structured_resource_limit is None:
            raise ValueError("structured authority is required for bounded lookup")
        key_name = instruction["key"]
        envelope = variables[cast(str, instruction["value"])]
        selector_kind = lookup_selector_kind(envelope, authority=structured_authority)
        if selector_kind == "static-field":
            key = key_name
        elif key_name in variables:
            key = variables[key_name]
        else:
            raise ValueError("admitted List lookup index local is unavailable")
        variables[cast(str, instruction["target"])] = lookup_typed_value(
            envelope,
            key,
            authority=structured_authority,
            resource_limit=structured_resource_limit,
        )
        return
    elif operator == "canonical-equal":
        if structured_authority is None or structured_resource_limit is None:
            raise ValueError("structured authority is required for canonical equality")
        left = variables[cast(str, instruction["left"])]
        right = variables[cast(str, instruction["right"])]
        left_integer = _project_runtime_integer(left, structured_authority)
        right_integer = _project_runtime_integer(right, structured_authority)
        if isinstance(left, bool) and isinstance(right, bool):
            result = left == right
        elif isinstance(left, bool) or isinstance(right, bool):
            raise ValueError(
                "admitted equality operands used different representations"
            )
        elif left_integer is not None and right_integer is not None:
            if isinstance(left, dict) and isinstance(right, dict):
                type_member, _value_member = typed_envelope_members(
                    structured_authority
                )
                if canonical_bytes(left[type_member]) != canonical_bytes(
                    right[type_member]
                ):
                    raise StructuredValueFault(
                        "language.structured_value_type_mismatch", f"/{type_member}"
                    )
            result = left_integer == right_integer
        elif left_integer is None and right_integer is None:
            _type_member, value_member = typed_envelope_members(structured_authority)
            result = equal_typed_values(
                left,
                right,
                authority=structured_authority,
                resource_limit=structured_resource_limit,
            )[value_member]
        else:
            raise ValueError(
                "admitted equality operands used different representations"
            )
        variables[cast(str, instruction["target"])] = result
        return
    elif operator == "collection-is-empty":
        if structured_authority is None or structured_resource_limit is None:
            raise ValueError("structured authority is required for List emptiness")
        result = is_empty_typed_value(
            variables[cast(str, instruction["value"])],
            authority=structured_authority,
            resource_limit=structured_resource_limit,
        )
        _type_member, value_member = typed_envelope_members(structured_authority)
        variables[cast(str, instruction["target"])] = result[value_member]
        return
    elif operator == "select-value":
        value = variables[
            cast(
                str,
                instruction[
                    "when_true"
                    if variables[cast(str, instruction["condition"])]
                    else "when_false"
                ],
            )
        ]
    else:
        raise ValueError(f"Kernel operator is not a value instruction: {operator}")
    if isinstance(value, int) and not isinstance(value, bool):
        value = _admit_numeric(value, numeric)
    variables[cast(str, instruction["target"])] = value


def evaluate_initialization_programs(
    checked: CheckedExperiment,
    actual_values: dict[bytes, int],
    *,
    consumed_steps: int,
    runtime_limit: int,
    cache: dict[bytes, int] | None,
    selected_entrypoints: Sequence[dict[str, Any]],
    frame_token: JsonValue | None = None,
    frame_identity: str | None = None,
    phase: str = "initialization",
) -> int:
    """Independently replay closed Formula initialization programs."""
    programs = formula_programs_reachable_from_entrypoints(
        checked, selected_entrypoints, phase=phase
    )
    if not programs:
        return consumed_steps
    available_identities = set(actual_values)
    while programs:
        program_targets = {
            canonical_bytes(cast(JsonValue, program["target"])) for program in programs
        }
        closed_programs = [
            program
            for program in programs
            if {
                canonical_bytes(cast(JsonValue, operand["resolved_symbol"]))
                for row in cast(list[dict[str, Any]], program["inputs"])
                if (operand := cast(dict[str, Any], row["operand"]))["kind"]
                != "literal"
            }
            <= available_identities | program_targets
        ]
        if len(closed_programs) == len(programs):
            break
        programs = closed_programs
    if not programs:
        return consumed_steps
    program_targets = {
        canonical_bytes(cast(JsonValue, program["target"])) for program in programs
    }
    numeric = cast(dict[str, Any], runtime_contract(checked)["numeric"])
    node_contracts = runtime_nodes(checked)
    if frame_identity is None:
        if phase != "initialization":
            raise ValueError(
                "observation requires an exact committed Snapshot identity"
            )
        frame_identity = content_identity(
            "initialization-frame-v2",
            cast(
                JsonValue,
                {
                    "token": frame_token,
                    "values": [
                        {
                            "symbol": identity.decode("utf-8").rstrip("\n"),
                            "value": value,
                        }
                        for identity, value in sorted(actual_values.items())
                        if identity not in program_targets
                    ],
                },
            ),
        )
    pending = list(programs)
    while pending:
        progressed = False
        for program in list(pending):
            input_values: dict[str, int] = {}
            ready = True
            for row in cast(list[dict[str, Any]], program["inputs"]):
                operand = cast(dict[str, Any], row["operand"])
                if operand["kind"] == "literal":
                    value = cast(int, operand["value"])
                else:
                    identity = canonical_bytes(
                        cast(JsonValue, operand["resolved_symbol"])
                    )
                    if identity not in actual_values:
                        ready = False
                        break
                    value = actual_values[identity]
                input_values[cast(str, row["name"])] = value
            if not ready:
                continue
            charge = cast(
                int, cast(dict[str, Any], program["resource_bounds"])["max_steps"]
            )
            consumed_steps += charge
            if consumed_steps > runtime_limit:
                raise ReplayInitializationProgramFault(
                    signal="step-limit",
                    program=cast(str, program["identity"]),
                    evaluation_site_identity=cast(
                        str, cast(dict[str, Any], program["site"])["identity"]
                    ),
                    frame_identity=frame_identity,
                )
            cache_key = canonical_bytes(
                cast(
                    JsonValue,
                    {
                        "program": program["identity"],
                        "site": cast(dict[str, Any], program["site"])["identity"],
                        "frame": frame_identity,
                        "operands": [
                            {"name": name, "value": value}
                            for name, value in sorted(input_values.items())
                        ],
                        "numeric": numeric,
                    },
                )
            )
            if cache is not None and cache_key in cache:
                result_value = cache[cache_key]
            else:
                variables = dict(input_values)
                for row in cast(list[dict[str, Any]], program["body"]):
                    try:
                        instruction = cast(dict[str, Any], row["instruction"])
                        execute_value_instruction(
                            instruction,
                            variables,
                            numeric,
                            node_contracts[cast(str, instruction["node"])],
                        )
                    except OverflowError as error:
                        raise ReplayInitializationProgramFault(
                            signal="numeric-overflow",
                            program=cast(str, program["identity"]),
                            evaluation_site_identity=cast(
                                str, row["evaluation_site_identity"]
                            ),
                            frame_identity=frame_identity,
                        ) from error
                result = cast(dict[str, Any], program["result"])
                result_value = _admit_numeric(
                    variables[cast(str, result["name"])], numeric
                )
                if cache is not None:
                    cache[cache_key] = result_value
            target = canonical_bytes(cast(JsonValue, program["target"]))
            actual_values[target] = result_value
            pending.remove(program)
            progressed = True
        if not progressed:
            raise ValueError("admitted initialization program graph is cyclic")
    return consumed_steps
