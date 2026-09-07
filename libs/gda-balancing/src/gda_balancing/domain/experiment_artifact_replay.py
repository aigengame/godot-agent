"""Independent behavioral adapter for Runtime evidence replay."""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.operation_program import (
    OperationCoordinate,
    guard_expanded_instruction_indices,
    instruction_evaluation_sites,
    operation_coordinate,
    operation_body_instructions,
    selected_operation_index,
)
from gda_balancing.domain.program_reachability import reachable_formula_programs
from gda_balancing.domain.runtime.projections import (
    operation_formula_evaluation_record,
    resolved_display_names,
    resolved_state_rows,
    runtime_contract,
    runtime_nodes,
    scheduler_contract,
    scheduled_event_id,
)
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    StructuredValueIndex,
    admit_typed_value,
    list_type_contract,
    structured_fault_reason,
    equal_typed_values,
    is_empty_typed_value,
    lookup_selector_kind,
    lookup_typed_value,
    selected_structured_value_index,
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


class _NonpositiveDivisorError(ValueError):
    """A selected floor-divide cannot execute outside its positive domain."""


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
    structured_resource_limit: int | None,
) -> JsonValue:
    """Independently admit one replayed value under its declaration."""
    type_identity = cast(dict[str, str], declaration["type_identity"])
    declared_type: JsonValue = {
        "id": type_identity["id"],
        "package": type_identity["package"],
    }
    if declaration.get("value_kind") == "nominal-structured":
        type_member, _value_member = typed_envelope_members(structured_authority)
        admitted = admit_typed_value(
            value,
            authority=structured_authority,
            resource_limit=structured_resource_limit,
        )
        if canonical_bytes(admitted[type_member]) != canonical_bytes(declared_type):
            raise StructuredValueFault("structured.reason.type-mismatch", "/type")
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
                    "structured.reason.type-mismatch", f"/{type_member}"
                )
            value = admitted[value_member]
    if not isinstance(value, int) or isinstance(value, bool):
        raise StructuredValueFault(
            "structured.reason.type-mismatch", f"/{value_member}"
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


def _append_replay_list(
    envelope: Any,
    item: Any,
    *,
    authority: StructuredValueIndex,
    resource_limit: int | None,
) -> dict[str, JsonValue]:
    """Interpret selected append independently; only type admission is shared."""
    admitted = admit_typed_value(
        envelope, authority=authority, resource_limit=resource_limit
    )
    type_member, value_member = typed_envelope_members(authority)
    element, maximum = list_type_contract(admitted[type_member], authority=authority)
    expression = cast(dict[str, Any], admitted[type_member])
    if "package" in expression and "id" in expression:
        constructor = authority.types[(expression["package"], expression["id"])][
            "constructor"
        ]
    else:
        constructor = next(
            row["id"]
            for row in authority.constructors.values()
            if row["value_rule"].get("definition_kind") == expression["kind"]
        )
    law = next(
        row["law"]
        for row in authority.operations.values()
        if row["owner_constructor"] == constructor
        and row["law"]["operator"] == "bounded-list-append"
    )
    if law != {
        "operator": "bounded-list-append",
        "element_projection": "list-element-type",
        "result_projection": "same-list-type",
        "order": "append-after-existing",
        "duplicates": "preserve",
        "capacity": "length-less-than-maximum",
        "refusal_signal": "structured-list-capacity-exceeded",
    }:
        raise ValueError("unsupported selected List append law")
    # The item is admitted before testing capacity, including when the List is full.
    if isinstance(item, dict) and set(item) == {type_member, value_member}:
        item_envelope = admit_typed_value(
            item, authority=authority, resource_limit=resource_limit
        )
        if item_envelope[type_member] != element:
            raise StructuredValueFault("structured.reason.type-mismatch", "/item/type")
    else:
        item_envelope = admit_typed_value(
            {type_member: element, value_member: item},
            authority=authority,
            resource_limit=resource_limit,
        )
    values = cast(list[JsonValue], admitted[value_member])
    if len(values) == maximum:
        reason = next(
            row
            for row in authority.reasons.values()
            if row.get("stage") == "runtime"
            and row.get("signal") == law["refusal_signal"]
        )
        raise StructuredValueFault(reason["id"], "/value")
    return {
        type_member: admitted[type_member],
        value_member: [*values, item_envelope[value_member]],
    }


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
        "integer-floor-divide",
        "integer-subtract",
        "integer-multiply",
    }:
        left = _require_runtime_integer(
            variables[cast(str, instruction["left"])], structured_authority
        )
        right = _require_runtime_integer(
            variables[cast(str, instruction["right"])], structured_authority
        )
        if operator == "integer-floor-divide" and right <= 0:
            raise _NonpositiveDivisorError("floor-divide divisor must be positive")
        value = (
            left + right
            if operator == "integer-add"
            else left // right
            if operator == "integer-floor-divide"
            else left - right
            if operator == "integer-subtract"
            else left * right
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
        if structured_authority is None:
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
                        "structured.reason.type-mismatch", f"/{type_member}"
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
    elif operator == "bounded-list-append":
        if structured_authority is None or structured_resource_limit is None:
            raise ValueError("structured authority is required for List append")
        variables[cast(str, instruction["target"])] = _append_replay_list(
            variables[cast(str, instruction["value"])],
            variables[cast(str, instruction["item"])],
            authority=structured_authority,
            resource_limit=structured_resource_limit,
        )
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
    programs = reachable_formula_programs(
        checked.rir, selected_entrypoints, phase=phase
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


@dataclass(frozen=True)
class ReplayOperationRefusal:
    """The first independently executed refusal, including its attempted charge."""

    signal: str
    operation: str
    call_path: str
    call_site_identity: str | None
    evaluation_site_identity: str | None
    instruction_index: int
    event_steps: int
    node_steps: int


class _OperationFault(Exception):
    def __init__(self, refusal: ReplayOperationRefusal) -> None:
        super().__init__(refusal.signal)
        self.refusal = refusal


@dataclass(frozen=True)
class _ReplayEvent:
    """Facts available before an Event, separate from any committed outcome."""

    event_id: str
    index: int
    state_before: list[dict[str, JsonValue]]
    snapshot_identity: str


@dataclass
class _ReplayResult:
    outcome: str | None
    formula_evaluations: list[dict[str, JsonValue]]
    calls: list[dict[str, JsonValue]]
    draws: list[dict[str, JsonValue]]
    state_after: list[dict[str, JsonValue]] | None = None
    schedule_arguments: (
        tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]] | None
    ) = None
    refusal: ReplayOperationRefusal | None = None
    event_steps: int = 0
    node_steps: int = 0


@dataclass(frozen=True)
class ReplayEventEvidence:
    """Independently observed Event evidence and its actual attempted charges."""

    schedule_arguments: (
        tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]] | None
    )
    formula_evaluations: list[dict[str, JsonValue]]
    event_steps: int
    node_steps: int


def execution_path_segment(value: str) -> str:
    """Independently encode one raw static execution-path segment."""
    return value.replace("~", "~0").replace("/", "~1")


def operation_at_execution_path(
    checked: CheckedExperiment,
    root_reference: dict[str, Any],
    root_path: str,
    path: str,
) -> OperationCoordinate | None:
    """Resolve static ownership; actual fold lengths are checked by value replay."""
    segments = path.split("/")
    if not segments or segments.pop(0) != root_path:
        return None
    coordinate = operation_coordinate(root_reference)
    operations = selected_operation_index(checked.rir["selected_semantics"])
    nodes = runtime_nodes(checked)
    while segments:
        operation = operations.get(coordinate)
        if operation is None:
            return None
        segment = segments.pop(0)
        # Comparing canonical encodings also rejects malformed escapes.
        matches = [
            row
            for row in operation_body_instructions(operation["body"])
            if nodes[row["node"]]["semantics"]["operator"]
            in {"invoke-operation", "bounded-pure-fold"}
            and execution_path_segment(row["site"]) == segment
        ]
        if len(matches) != 1:
            return None
        instruction = matches[0]
        if nodes[instruction["node"]]["semantics"]["operator"] == "bounded-pure-fold":
            if (
                not segments
                or re.fullmatch(r"@(0|[1-9][0-9]*)", segments.pop(0)) is None
            ):
                return None
        coordinate = operation_coordinate(instruction["operation"])
    return coordinate if coordinate in operations else None


def _replay_operation_event(
    checked: CheckedExperiment,
    event: _ReplayEvent,
    event_spec: dict[str, JsonValue],
    root_arguments: tuple[
        dict[str, JsonValue], dict[str, dict[str, JsonValue]], dict[bytes, Any]
    ],
    *,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
    node_steps_before_operation: int,
    bounds: dict[str, int],
    target_schedule: dict[str, JsonValue] | None = None,
) -> _ReplayResult | None:
    """Execute the selected Operation graph independently of the Runtime executor.

    Both committed evidence and a refused attempt enter here with real pre-event
    facts. Claimed terminal locations never control traversal or termination.
    """
    operations = selected_operation_index(checked.rir["selected_semantics"])
    if event_spec["kind"] == "transition-invocation":
        entrypoint = next(
            (
                row
                for row in checked.rir["entrypoints"]
                if row["id"] == event_spec["entrypoint"]
            ),
            None,
        )
        if entrypoint is None:
            return None
        root_reference = entrypoint["operation"]
        root_path = (execution_path_segment(entrypoint["id"]),)
    elif event_spec["kind"] == "scheduled-transition":
        root_reference = event_spec["operation"]
        root_path = (
            execution_path_segment(f"scheduled:{event_spec['call_site_identity']}"),
        )
    else:
        return None
    root_coordinate = operation_coordinate(cast(dict[str, Any], root_reference))
    root_operation = operations.get(root_coordinate)
    if root_operation is None:
        return None
    runtime = runtime_contract(checked)
    path_contract = runtime["invocation_contract"]["execution_path"]
    if (
        path_contract["segment_encoding"] != {"~": "~0", "/": "~1"}
        or path_contract["separator"] != "/"
        or path_contract["fold_iteration"]["prefix"] != "@"
    ):
        return None
    numeric = cast(dict[str, Any], runtime["numeric"])
    node_contracts = runtime_nodes(checked)
    structured_authority = selected_structured_value_index(
        cast(dict[str, Any], checked.rir["selected_semantics"])
    )
    structured_resource_limit = cast(
        int | None,
        checked.rir["selected_semantics"]["execution_resources"].get(
            "max_rule_match_steps"
        ),
    )
    declarations = {
        canonical_bytes(cast(JsonValue, row["resolved_symbol"])): row
        for row in cast(list[dict[str, Any]], checked.rir["declarations"])
    }
    names = resolved_display_names(declarations)
    named_state = {row["name"]: row["value"] for row in event.state_before}
    state = {
        identity: named_state[name]
        for identity, name in names.items()
        if name in named_state
    }
    actual_values = root_arguments[2]
    call_sites = {
        (operation_coordinate(row["parent_operation"]), row["site"]): row
        for row in checked.rir["call_sites"]
    }
    formula_bindings = {
        binding["site"]["identity"]: binding
        for binding in checked.rir["formula_bindings"]
        if binding["site"]["kind"] == "operation-slot"
    }
    scheduler = scheduler_contract(checked)
    rng = ReplayNamedRng(
        cast(int, checked.value["seed"]["value"]), runtime["named_rng"]
    )
    prior_ids: set[str] = set()
    canceled_ids: set[str] = set()
    for prior in sorted(events_by_id.values(), key=lambda row: cast(int, row["index"])):
        if cast(int, prior["index"]) >= event.index:
            break
        record = catalog_by_id.get(cast(str, prior["event_id"]))
        if record is None:
            return None
        if record["scenario"] != scenario_id:
            continue
        prior_ids.add(cast(str, prior["event_id"]))
        canceled_ids.update(
            cast(str, row["event_id"])
            for row in cast(list[dict[str, JsonValue]], prior["cancellations"])
        )
        for draw in cast(list[dict[str, JsonValue]], prior["rng_draws"]):
            value, index, candidate, accepted = rng.draw(
                cast(str, draw["stream"]),
                cast(int, draw["minimum"]),
                cast(int, draw["maximum"]),
            )
            if draw != {
                "stream": draw["stream"],
                "minimum": draw["minimum"],
                "maximum": draw["maximum"],
                "index": index,
                "candidate_hex": rng.encode_candidate(candidate),
                "accepted": accepted,
                "value": value,
            }:
                return None
    # Only records already enqueued at the current Event are available. Later
    # committed schedules in a full trace must not change a prior refusal budget.
    scenario_catalog = [
        row
        for row in catalog_by_id.values()
        if row["scenario"] == scenario_id
        and (
            cast(dict[str, Any], row["event_spec"])["kind"] != "scheduled-transition"
            or cast(dict[str, Any], row["event_spec"])["parent_event_id"] in prior_ids
        )
    ]
    pending_ids = (
        {cast(str, row["event_id"]) for row in scenario_catalog}
        - prior_ids
        - canceled_ids
        - {event.event_id}
    )
    total_events = len(scenario_catalog)
    next_sequence = (
        max(
            (
                cast(int, cast(dict[str, Any], row["ordering_key"])["enqueue_sequence"])
                for row in scenario_catalog
            ),
            default=-1,
        )
        + 1
    )
    provisional_ids: set[str] = set()
    result = _ReplayResult(None, [], [], [])
    event_steps = 0
    node_steps = node_steps_before_operation
    frames: list[list[int]] = []
    schedule_count = 0

    def fail(
        signal: str,
        operation: dict[str, Any],
        path: tuple[str, ...],
        call_identity: str | None,
        index: int,
        site: str | None,
    ) -> None:
        raise _OperationFault(
            ReplayOperationRefusal(
                signal,
                operation["id"],
                "/".join(path),
                call_identity,
                site,
                index,
                event_steps,
                node_steps,
            )
        )

    def charge(
        amount: int,
        operation: dict[str, Any],
        path: tuple[str, ...],
        call_identity: str | None,
        index: int,
        site: str | None,
    ) -> None:
        nonlocal event_steps, node_steps
        event_steps += amount
        node_steps += amount
        for frame in frames:
            frame[0] += amount
        if (
            event_steps > bounds["max_event_steps"]
            or node_steps > bounds["max_node_steps"]
            or any(used > maximum for used, maximum in frames)
        ):
            fail("step-limit", operation, path, call_identity, index, site)

    def arguments_for(
        instruction: dict[str, Any],
        variables: dict[str, Any],
        references: dict[str, dict[str, JsonValue]],
    ) -> tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]]:
        arguments: dict[str, JsonValue] = {}
        state_references: dict[str, dict[str, JsonValue]] = {}
        for binding in instruction["arguments"]:
            operand = binding["operand"]
            name = binding["port"]
            if operand["kind"] == "port":
                source = operand["port"]
                arguments[name] = variables[source]
                if source in references:
                    state_references[name] = references[source]
            elif operand["kind"] == "local":
                arguments[name] = variables[operand["local"]]
            else:
                arguments[name] = operand["literal"]
        return arguments, state_references

    def execute(
        coordinate: OperationCoordinate,
        operation: dict[str, Any],
        arguments: dict[str, JsonValue],
        references: dict[str, dict[str, JsonValue]],
        path: tuple[str, ...],
        call_identity: str | None,
    ) -> tuple[str | None, JsonValue]:
        nonlocal next_sequence, total_events, schedule_count
        pure = operation["operation_kind"] == "pure-expression"
        before = dict(state)
        variables: dict[str, Any] = dict(arguments)
        snapshot = operation.get("extensions", {}).get("standard.snapshot-operands")
        if snapshot is not None:
            if pure:
                raise ValueError("pure Operation captured Snapshot values")
            for row in snapshot["operands"]:
                variables[row["name"]] = actual_values[
                    canonical_bytes(row["resolved_symbol"])
                ]
        operation_results: dict[str, JsonValue] = {}
        outcome = None if pure else operation["default_outcome"]
        sites = instruction_evaluation_sites(operation)
        frames.append([0, operation["resource_bounds"]["max_steps"]])

        def body(instructions: list[dict[str, Any]], offset: int = 0) -> str | None:
            nonlocal next_sequence, total_events, schedule_count, variables
            indices = guard_expanded_instruction_indices(instructions, offset=offset)
            for body_index, instruction in enumerate(instructions):
                index = indices[body_index]
                site = sites.get(index)
                node = node_contracts[instruction["node"]]
                semantics = node["semantics"]
                operator = semantics["operator"]
                charge(
                    node["resource_charge"]["amount"],
                    operation,
                    path,
                    call_identity,
                    index,
                    site,
                )
                try:
                    if operator == "invoke-operation":
                        child_coordinate = operation_coordinate(
                            instruction["operation"]
                        )
                        child = operations[child_coordinate]
                        resolved = call_sites[(coordinate, instruction["site"])]
                        child_arguments, child_references = arguments_for(
                            instruction, variables, references
                        )
                        child_path = (
                            *path,
                            execution_path_segment(instruction["site"]),
                        )
                        child_outcome, child_result = execute(
                            child_coordinate,
                            child,
                            child_arguments,
                            {}
                            if child["operation_kind"] == "pure-expression"
                            else child_references,
                            child_path,
                            resolved["identity"],
                        )
                        if child["operation_kind"] != "pure-expression":
                            resolved_outcome = next(
                                row
                                for row in resolved["outcomes"]
                                if row["outcome"] == child_outcome
                            )
                            result.calls.append(
                                {
                                    "site": "/".join(child_path),
                                    "call_site_identity": resolved["identity"],
                                    "operation": resolved["operation"],
                                    "outcome": {
                                        "id": child_outcome,
                                        "identity": resolved_outcome["identity"],
                                    },
                                    "arguments": [
                                        {
                                            "formal_port_identity": row["port"][
                                                "identity"
                                            ],
                                            "actual_operand_identity": row["operand"][
                                                "identity"
                                            ],
                                        }
                                        for row in resolved["arguments"]
                                    ],
                                    "result_identity": resolved["result"]["identity"],
                                }
                            )
                        binding = instruction["result"]
                        if binding["kind"] == "local":
                            variables[binding["name"]] = child_result
                        elif binding["kind"] == "operation-result":
                            operation_results[instruction["site"]] = child_result
                        for alias, target in references.items():
                            variables[alias] = state[
                                canonical_bytes(cast(JsonValue, target))
                            ]
                        if child_outcome is not None:
                            action = next(
                                row["action"]
                                for row in instruction["outcomes"]
                                if row["outcome"] == child_outcome
                            )
                            if action["kind"] == "propagate":
                                return cast(str, action["outcome"])
                    elif operator == "bounded-pure-fold":
                        envelope = admit_typed_value(
                            variables[instruction["value"]],
                            authority=structured_authority,
                            resource_limit=structured_resource_limit,
                        )
                        type_member, value_member = typed_envelope_members(
                            structured_authority
                        )
                        element_type, maximum = list_type_contract(
                            envelope[type_member], authority=structured_authority
                        )
                        items = envelope[value_member]
                        if not isinstance(items, list) or len(items) > maximum:
                            raise ValueError(
                                "admitted fold value is not a bounded List"
                            )
                        accumulator = variables[instruction["initial"]]
                        child_coordinate = operation_coordinate(
                            instruction["operation"]
                        )
                        child = operations[child_coordinate]
                        if child["operation_kind"] != "pure-expression":
                            raise ValueError("fold step is not pure")
                        captures, _captured_references = arguments_for(
                            instruction, variables, references
                        )
                        for item_index, item in enumerate(items):
                            child_path = (
                                *path,
                                execution_path_segment(instruction["site"]),
                                f"@{item_index}",
                            )
                            charge(
                                semantics["invocation_charge"],
                                child,
                                child_path,
                                None,
                                0,
                                None,
                            )
                            child_arguments = {
                                **captures,
                                instruction["accumulator_port"]: accumulator,
                                instruction["item_port"]: {
                                    type_member: element_type,
                                    value_member: item,
                                },
                            }
                            _outcome, accumulator = execute(
                                child_coordinate,
                                child,
                                child_arguments,
                                {},
                                child_path,
                                None,
                            )
                        variables[instruction["target"]] = accumulator
                    elif operator == "schedule-operation":
                        child_arguments, child_references = arguments_for(
                            instruction, variables, references
                        )
                        schedule_identity = content_identity(
                            scheduler["call_site_identity"]["schedule"]["domain"],
                            {
                                "parent_event_id": event.event_id,
                                "parent_operation": coordinate[1],
                                "site": instruction["site"],
                                "operation": instruction["operation"],
                            },
                        )
                        schedule_law = scheduler["schedule"]
                        signals = schedule_law["refusal_signals"]
                        logical_time = instruction["logical_time"]
                        depth = (
                            cast(int, event_spec.get("zero_time_depth", 0)) + 1
                            if logical_time
                            == cast(dict[str, Any], event_spec["ordering_key"])[
                                "logical_time"
                            ]
                            else 0
                        )
                        signal = (
                            signals["hidden_input"]
                            if instruction.get("phase", schedule_law["child_phase"])
                            != schedule_law["child_phase"]
                            else signals["backward"]
                            if logical_time
                            < cast(dict[str, Any], event_spec["ordering_key"])[
                                "logical_time"
                            ]
                            else signals["illegal_same_time_priority"]
                            if logical_time
                            == cast(dict[str, Any], event_spec["ordering_key"])[
                                "logical_time"
                            ]
                            and instruction["priority"]
                            > cast(dict[str, Any], event_spec["ordering_key"])[
                                "priority"
                            ]
                            else "logical-time-limit"
                            if logical_time > bounds["max_logical_time"]
                            else "zero-time-depth-limit"
                            if depth > bounds["max_zero_time_depth"]
                            else "event-limit"
                            if total_events + 1 > bounds["max_total_events"]
                            else "queue-limit"
                            if len((pending_ids | provisional_ids) - canceled_ids) + 1
                            > bounds["max_queue_events"]
                            else None
                        )
                        if signal is not None:
                            fail(
                                signal, operation, path, schedule_identity, index, site
                            )
                        if (
                            target_schedule is not None
                            and target_schedule["call_site_identity"]
                            == schedule_identity
                            and target_schedule["call_path"] == "/".join(path)
                        ):
                            result.schedule_arguments = (
                                child_arguments,
                                child_references,
                            )
                            raise _ScheduleFound
                        child_id = scheduled_event_id(
                            checked,
                            scenario_id,
                            {
                                "parent_event_id": event.event_id,
                                "call_site_identity": schedule_identity,
                                "schedule_sequence": schedule_count,
                                "logical_time": logical_time,
                                "phase": schedule_law["child_phase"],
                                "priority": instruction["priority"],
                                "enqueue_sequence": next_sequence,
                            },
                        )
                        schedule_count += 1
                        next_sequence += 1
                        total_events += 1
                        provisional_ids.add(child_id)
                        variables[instruction["result"]["name"]] = child_id
                    elif operator == "cancel-event":
                        target_contract = semantics["target_reference"]
                        target = instruction[target_contract["instruction_member"]]
                        variant = next(
                            (
                                row
                                for row in target_contract["variants"]
                                if row["kind"] == target["kind"]
                            ),
                            None,
                        )
                        target_id = (
                            variables.get(target.get(variant["value_member"]))
                            if variant is not None
                            else None
                        )
                        status = (
                            "unknown"
                            if target_id in canceled_ids
                            else "active"
                            if target_id == event.event_id
                            else "completed"
                            if target_id in prior_ids
                            else "provisional"
                            if target_id in provisional_ids
                            else "pending"
                            if target_id in pending_ids
                            else "unknown"
                        )
                        law = scheduler["cancel"]
                        if status not in law["admitted_target_states"]:
                            fail(
                                law["refusal_signals"][status],
                                operation,
                                path,
                                call_identity,
                                index,
                                site,
                            )
                        canceled_ids.add(cast(str, target_id))
                    elif operator == "gameplay-precondition":
                        if not integer_compare(
                            semantics["comparison"],
                            _require_runtime_integer(
                                variables[instruction["left"]], structured_authority
                            ),
                            _require_runtime_integer(
                                variables[instruction["right"]], structured_authority
                            ),
                        ):
                            return cast(str, instruction["outcome"])
                    elif operator == "typed-require":
                        if (
                            variables[instruction["condition"]]
                            != instruction["expected"]
                        ):
                            reason_id = instruction[
                                semantics["refusal_reference"]["instruction_member"]
                            ]
                            reason = next(
                                row["definition"]
                                for row in checked.rir["selected_semantics"][
                                    "diagnostic_reasons"
                                ]
                                if row["definition"]["id"] == reason_id
                            )
                            fail(
                                reason["signal"],
                                operation,
                                path,
                                call_identity,
                                index,
                                site,
                            )
                    elif operator == "guarded-outcome-block":
                        if variables[instruction["condition"]]:
                            enclosing_variables = variables
                            variables = dict(variables)
                            try:
                                body(instruction["body"], index + 1)
                            finally:
                                variables = enclosing_variables
                            for alias, target in references.items():
                                variables[alias] = state[
                                    canonical_bytes(cast(JsonValue, target))
                                ]
                            return cast(str, instruction["outcome"])
                    elif operator == "named-integer-draw":
                        value, draw_index, candidate, accepted = rng.draw(
                            instruction["stream"],
                            instruction["minimum"],
                            instruction["maximum"],
                        )
                        variables[instruction["target"]] = value
                        result.draws.append(
                            {
                                "stream": instruction["stream"],
                                "minimum": instruction["minimum"],
                                "maximum": instruction["maximum"],
                                "index": draw_index,
                                "candidate_hex": rng.encode_candidate(candidate),
                                "accepted": accepted,
                                "value": value,
                            }
                        )
                    elif node["family"] == "expression":
                        execute_value_instruction(
                            instruction,
                            variables,
                            numeric,
                            node,
                            structured_authority=structured_authority,
                            structured_resource_limit=structured_resource_limit,
                        )
                    elif operator in {"state-integer-subtract", "state-write"}:
                        target = canonical_bytes(
                            cast(JsonValue, references[instruction["symbol"]])
                        )
                        value = (
                            _require_runtime_integer(
                                state[target], structured_authority
                            )
                            - _require_runtime_integer(
                                variables[instruction["value"]], structured_authority
                            )
                            if operator == "state-integer-subtract"
                            else variables[instruction["value"]]
                        )
                        state[target] = admit_declared_value(
                            value,
                            numeric,
                            declarations[target],
                            structured_authority=structured_authority,
                            structured_resource_limit=structured_resource_limit,
                        )
                        for alias, reference in references.items():
                            if canonical_bytes(cast(JsonValue, reference)) == target:
                                variables[alias] = state[target]
                    else:
                        raise ValueError(
                            f"unsupported selected replay operator: {operator}"
                        )
                except (OverflowError, _NonpositiveDivisorError) as error:
                    fail(
                        "invalid-domain"
                        if isinstance(error, _NonpositiveDivisorError)
                        else "numeric-overflow",
                        operation,
                        path,
                        call_identity,
                        index,
                        site,
                    )
                except StructuredValueFault as error:
                    reason = structured_fault_reason(
                        error, authority=structured_authority
                    )
                    if (
                        reason.get("stage") != "runtime"
                        or reason.get("signal") not in node["refusals"]
                    ):
                        raise ValueError(
                            "admitted structured operation violated its type contract"
                        ) from error
                    fail(reason["signal"], operation, path, call_identity, index, site)
                if site is not None and sites.get(index + 1) != site:
                    evaluation = operation_formula_evaluation_record(
                        operation,
                        formula_bindings[site],
                        variables,
                        evaluation_site_identity=site,
                        frame_identity=event.snapshot_identity,
                        call_path=path,
                    )
                    if evaluation is None:
                        raise ValueError(
                            "Formula evaluation record cannot be reconstructed"
                        )
                    result.formula_evaluations.append(evaluation)
            return None

        try:
            body_outcome = body(operation["body"])
            if body_outcome is not None:
                outcome = body_outcome
            if not pure:
                definition = next(
                    row for row in operation["outcomes"] if row["id"] == outcome
                )
                if definition["state_policy"] == "rollback":
                    state.clear()
                    state.update(before)
                if definition["kind"] != "success":
                    return outcome, None
            source = operation["result"]["source"]
            value = (
                variables[source["name"]]
                if source["kind"] in {"local", "port"}
                else operation_results[source["site"]]
                if source["kind"] == "operation-result"
                else None
            )
            return outcome, value
        finally:
            frames.pop()

    try:
        result.outcome, _value = execute(
            root_coordinate,
            root_operation,
            root_arguments[0],
            root_arguments[1],
            root_path,
            None,
        )
        result.state_after = resolved_state_rows(state, names)
    except _OperationFault as fault:
        result.refusal = fault.refusal
    except _ScheduleFound:
        pass
    except (
        KeyError,
        OverflowError,
        StopIteration,
        StructuredValueFault,
        TypeError,
        ValueError,
    ):
        return None
    result.event_steps = event_steps
    result.node_steps = node_steps
    return result


class _ScheduleFound(Exception):
    """A requested schedule's real input evaluation has completed."""


def replay_event_evidence(
    checked: CheckedExperiment,
    parent_event: dict[str, JsonValue],
    parent_spec: dict[str, JsonValue],
    target_schedule: dict[str, JsonValue] | None,
    root_arguments: tuple[
        dict[str, JsonValue], dict[str, dict[str, JsonValue]], dict[bytes, Any]
    ],
    *,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
    node_steps_before_operation: int = 0,
) -> ReplayEventEvidence | None:
    """Independently consume a committed Event and its complete call evidence."""
    profile = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == checked.value["runtime"]["profile"]
    )
    result = _replay_operation_event(
        checked,
        _ReplayEvent(
            cast(str, parent_event["event_id"]),
            cast(int, parent_event["index"]),
            cast(list[dict[str, JsonValue]], parent_event["state_before"]),
            cast(str, parent_event["snapshot_before_identity"]),
        ),
        parent_spec,
        root_arguments,
        scenario_id=scenario_id,
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
        node_steps_before_operation=node_steps_before_operation,
        bounds=profile["resource_bounds"],
        target_schedule=target_schedule,
    )
    if result is None or result.refusal is not None:
        return None
    if result.schedule_arguments is None and (
        result.outcome != cast(dict[str, JsonValue], parent_event["outcome"])["id"]
        or result.calls != parent_event["calls"]
        or result.draws != parent_event["rng_draws"]
        or canonical_bytes(cast(JsonValue, result.state_after))
        != canonical_bytes(parent_event["state_after"])
    ):
        return None
    return ReplayEventEvidence(
        result.schedule_arguments,
        result.formula_evaluations,
        result.event_steps,
        result.node_steps,
    )


def replay_refusing_operation(
    checked: CheckedExperiment,
    event_spec: dict[str, JsonValue],
    root_arguments: tuple[
        dict[str, JsonValue], dict[str, dict[str, JsonValue]], dict[bytes, Any]
    ],
    *,
    index: int,
    state_before: list[dict[str, JsonValue]],
    snapshot_identity: str,
    attempted_calls: list[dict[str, JsonValue]],
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
    node_steps_before_operation: int,
    bounds: dict[str, int],
) -> ReplayOperationRefusal | None:
    """Reconstruct a first refusal without trusting claimed refusal metadata."""
    result = _replay_operation_event(
        checked,
        _ReplayEvent(
            cast(str, event_spec["event_id"]),
            index,
            state_before,
            snapshot_identity,
        ),
        event_spec,
        root_arguments,
        scenario_id=scenario_id,
        catalog_by_id=catalog_by_id,
        events_by_id=events_by_id,
        node_steps_before_operation=node_steps_before_operation,
        bounds=bounds,
    )
    if result is None or result.calls != attempted_calls:
        return None
    return result.refusal
