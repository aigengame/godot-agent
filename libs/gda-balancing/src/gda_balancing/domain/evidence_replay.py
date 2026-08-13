"""Independent behavioral adapter for Runtime evidence replay."""

import hashlib
from collections.abc import Sequence
from typing import Any, cast

from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.experiment import CheckedExperiment
from gda_balancing.domain.operation_program import (
    OperationCoordinate,
    guard_expanded_instruction_indices,
    instruction_evaluation_sites,
    operation_coordinate,
    selected_operation_index,
)
from gda_balancing.domain.runtime.projections import (
    formula_programs_reachable_from_entrypoints,
    operation_formula_evaluation_record,
    resolved_display_names,
    runtime_contract,
    runtime_nodes,
    scheduler_contract,
)
from gda_balancing.domain.structured_values import (
    StructuredValueFault,
    StructuredValueIndex,
    admit_typed_value,
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


def replay_event_evidence(
    checked: CheckedExperiment,
    parent_event: dict[str, JsonValue],
    parent_spec: dict[str, JsonValue],
    target_schedule: dict[str, JsonValue] | None,
    root_arguments: tuple[
        dict[str, JsonValue],
        dict[str, dict[str, JsonValue]],
        dict[bytes, Any],
    ],
    *,
    scenario_id: str,
    catalog_by_id: dict[str, dict[str, JsonValue]],
    events_by_id: dict[str, dict[str, JsonValue]],
) -> (
    tuple[
        tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]] | None,
        list[dict[str, JsonValue]],
    ]
    | None
):
    """Replay one committed Operation event without using Runtime execution."""
    operations = selected_operation_index(checked.rir["selected_semantics"])
    formula_bindings_by_site = {
        cast(str, cast(dict[str, Any], binding["site"])["identity"]): binding
        for binding in cast(list[dict[str, Any]], checked.rir["formula_bindings"])
        if cast(dict[str, Any], binding["site"])["kind"] == "operation-slot"
    }
    entrypoint_reference = parent_event.get("entrypoint")
    if isinstance(entrypoint_reference, dict):
        entrypoint = next(
            (
                row
                for row in checked.rir["entrypoints"]
                if row["id"] == entrypoint_reference.get("id")
            ),
            None,
        )
        root_reference = entrypoint.get("operation") if entrypoint is not None else None
    else:
        root_reference = parent_spec.get("operation")
    if not isinstance(root_reference, dict):
        return None
    try:
        root_coordinate = operation_coordinate(root_reference)
    except (KeyError, TypeError):
        return None
    root_operation = operations.get(root_coordinate)
    if root_operation is None or parent_event.get("operation") != root_coordinate[2]:
        return None
    declarations = {
        canonical_bytes(cast(JsonValue, row["resolved_symbol"])): row
        for row in cast(list[dict[str, Any]], checked.rir["declarations"])
    }
    display_names = resolved_display_names(declarations)
    values_by_name = {
        cast(str, row["name"]): row["value"]
        for row in cast(list[dict[str, JsonValue]], parent_event["state_before"])
    }
    state: dict[bytes, JsonValue] = {
        identity: values_by_name[display_name]
        for identity, display_name in display_names.items()
        if display_name in values_by_name
    }
    actual_values = root_arguments[2]
    calls = cast(list[dict[str, JsonValue]], parent_event["calls"])
    schedules = cast(list[dict[str, JsonValue]], parent_event["schedules"])
    draws = cast(list[dict[str, JsonValue]], parent_event["rng_draws"])
    draw_index = 0
    formula_evaluations: list[dict[str, JsonValue]] = []
    runtime = runtime_contract(checked)
    rng = ReplayNamedRng(
        cast(int, checked.value["seed"]["value"]),
        cast(dict[str, Any], runtime["named_rng"]),
    )

    def consume_authoritative_draw(traced: dict[str, JsonValue]) -> int | None:
        try:
            value, index, candidate, accepted = rng.draw(
                cast(str, traced["stream"]),
                cast(int, traced["minimum"]),
                cast(int, traced["maximum"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        expected = {
            "stream": traced["stream"],
            "index": index,
            "candidate_hex": rng.encode_candidate(candidate),
            "accepted": accepted,
            "minimum": traced["minimum"],
            "maximum": traced["maximum"],
            "value": value,
        }
        return value if traced == expected else None

    for prior_event in sorted(
        events_by_id.values(), key=lambda row: cast(int, row["index"])
    ):
        if cast(int, prior_event["index"]) >= cast(int, parent_event["index"]):
            break
        prior_record = catalog_by_id.get(cast(str, prior_event["event_id"]))
        if prior_record is None:
            return None
        if prior_record["scenario"] != scenario_id:
            continue
        if any(
            consume_authoritative_draw(draw) is None
            for draw in cast(list[dict[str, JsonValue]], prior_event["rng_draws"])
        ):
            return None
    numeric = cast(dict[str, Any], runtime["numeric"])
    node_contracts = runtime_nodes(checked)
    structured_authority = selected_structured_value_index(
        cast(dict[str, Any], checked.rir["selected_semantics"]),
        kernel=checked.kernel,
    )
    structured_resource_limit = cast(
        int, checked.language_bundle["resources"]["max_rule_match_steps"]
    )
    schedule_identity = scheduler_contract(checked)["call_site_identity"]["schedule"]

    def execute(
        coordinate: OperationCoordinate,
        operation: dict[str, Any],
        arguments: dict[str, JsonValue],
        state_references: dict[str, dict[str, JsonValue]],
        call_path: tuple[str, ...],
    ) -> tuple[
        str,
        JsonValue,
        tuple[dict[str, JsonValue], dict[str, dict[str, JsonValue]]] | None,
    ]:
        nonlocal draw_index
        operation_before = dict(state)
        variables: dict[str, Any] = dict(arguments)
        extensions = operation.get("extensions", {})
        snapshot_operands = (
            extensions.get("standard.snapshot-operands")
            if isinstance(extensions, dict)
            else None
        )
        if isinstance(snapshot_operands, dict):
            for row in cast(
                list[dict[str, Any]], snapshot_operands.get("operands", [])
            ):
                identity = canonical_bytes(cast(JsonValue, row["resolved_symbol"]))
                if identity not in actual_values:
                    return "", None, None
                variables[cast(str, row["name"])] = actual_values[identity]
        operation_results: dict[str, JsonValue] = {}
        outcome = cast(str, operation["default_outcome"])
        evaluation_sites = instruction_evaluation_sites(operation)
        for instruction_index, instruction in enumerate(
            cast(list[dict[str, Any]], operation["body"])
        ):
            evaluation_site_identity = evaluation_sites.get(instruction_index)
            node_contract = node_contracts[instruction["node"]]
            operator = node_contract["semantics"]["operator"]
            if operator == "invoke-operation":
                child_coordinate = operation_coordinate(instruction["operation"])
                child = operations.get(child_coordinate)
                if child is None:
                    return "", None, None
                child_arguments: dict[str, JsonValue] = {}
                child_state_references: dict[str, dict[str, JsonValue]] = {}
                for binding in instruction["arguments"]:
                    operand = binding["operand"]
                    name = cast(str, binding["port"])
                    if operand["kind"] == "port":
                        source = cast(str, operand["port"])
                        child_arguments[name] = cast(JsonValue, variables[source])
                        if source in state_references:
                            child_state_references[name] = state_references[source]
                    elif operand["kind"] == "local":
                        child_arguments[name] = cast(
                            JsonValue, variables[operand["local"]]
                        )
                    else:
                        child_arguments[name] = cast(JsonValue, operand["literal"])
                child_path = (*call_path, cast(str, instruction["site"]))
                child_outcome, child_result, found = execute(
                    child_coordinate,
                    child,
                    child_arguments,
                    child_state_references,
                    child_path,
                )
                if found is not None:
                    return "", None, found
                call = next(
                    (
                        row
                        for row in calls
                        if row["site"] == "/".join(child_path)
                        and operation_coordinate(cast(dict[str, Any], row["operation"]))
                        == child_coordinate
                    ),
                    None,
                )
                if (
                    call is None
                    or cast(dict[str, JsonValue], call["outcome"])["id"]
                    != child_outcome
                ):
                    return "", None, None
                result_binding = instruction["result"]
                if result_binding["kind"] == "local":
                    variables[result_binding["name"]] = child_result
                elif result_binding["kind"] == "operation-result":
                    operation_results[instruction["site"]] = child_result
                for alias, target in state_references.items():
                    variables[alias] = state[canonical_bytes(cast(JsonValue, target))]
                mapping = next(
                    row
                    for row in instruction["outcomes"]
                    if row["outcome"] == child_outcome
                )
                if mapping["action"]["kind"] == "propagate":
                    outcome = cast(str, mapping["action"]["outcome"])
                    break
                continue
            if operator == "schedule-operation":
                child_arguments = {}
                child_state_references = {}
                for binding in instruction["arguments"]:
                    operand = binding["operand"]
                    name = cast(str, binding["port"])
                    if operand["kind"] == "port":
                        source = cast(str, operand["port"])
                        child_arguments[name] = cast(JsonValue, variables[source])
                        if source in state_references:
                            child_state_references[name] = state_references[source]
                    elif operand["kind"] == "local":
                        child_arguments[name] = cast(
                            JsonValue, variables[operand["local"]]
                        )
                    else:
                        child_arguments[name] = cast(JsonValue, operand["literal"])
                call_site_identity = content_identity(
                    cast(str, schedule_identity["domain"]),
                    cast(
                        JsonValue,
                        {
                            "parent_event_id": parent_event["event_id"],
                            "parent_operation": coordinate[2],
                            "site": instruction["site"],
                            "operation": instruction["operation"],
                        },
                    ),
                )
                if (
                    target_schedule is not None
                    and target_schedule["call_site_identity"] == call_site_identity
                    and target_schedule["call_path"] == "/".join(call_path)
                ):
                    return "", None, (child_arguments, child_state_references)
                scheduled = next(
                    (
                        row
                        for row in schedules
                        if row["call_site_identity"] == call_site_identity
                        and row["call_path"] == "/".join(call_path)
                    ),
                    None,
                )
                if scheduled is None:
                    return "", None, None
                variables[instruction["result"]["name"]] = scheduled["event_id"]
                continue
            if operator == "cancel-event":
                continue
            if operator == "gameplay-precondition":
                if not integer_compare(
                    node_contract["semantics"]["comparison"],
                    cast(int, variables[instruction["left"]]),
                    cast(int, variables[instruction["right"]]),
                ):
                    outcome = cast(str, instruction["outcome"])
                    break
            elif operator == "typed-require":
                if variables[instruction["condition"]] != instruction["expected"]:
                    return "", None, None
            elif operator == "guarded-outcome-block":
                if variables[instruction["condition"]]:
                    guarded_operation = {
                        "body": instruction["body"],
                        "default_outcome": instruction["outcome"],
                        "extensions": {},
                        "id": operation["id"],
                        "outcomes": list(operation["outcomes"]),
                        "result": {"source": {"kind": "unit"}},
                    }
                    guarded_outcome, _guarded_result, found = execute(
                        coordinate,
                        guarded_operation,
                        variables,
                        state_references,
                        call_path,
                    )
                    if found is not None:
                        return "", None, found
                    if guarded_outcome != instruction["outcome"]:
                        return "", None, None
                    outcome = cast(str, instruction["outcome"])
                    break
            elif operator == "named-integer-draw":
                if draw_index >= len(draws):
                    return "", None, None
                draw = draws[draw_index]
                draw_index += 1
                if (
                    draw["stream"] != instruction["stream"]
                    or draw["minimum"] != instruction["minimum"]
                    or draw["maximum"] != instruction["maximum"]
                ):
                    return "", None, None
                value = consume_authoritative_draw(draw)
                if value is None:
                    return "", None, None
                variables[instruction["target"]] = value
            elif node_contract["family"] == "expression":
                execute_value_instruction(
                    instruction,
                    variables,
                    numeric,
                    node_contract,
                    structured_authority=structured_authority,
                    structured_resource_limit=structured_resource_limit,
                )
            elif operator in {"state-integer-subtract", "state-write"}:
                formal = cast(str, instruction["symbol"])
                target = canonical_bytes(cast(JsonValue, state_references[formal]))
                declaration = declarations.get(target)
                if declaration is None:
                    return "", None, None
                state[target] = admit_declared_value(
                    cast(int, state[target])
                    - cast(int, variables[instruction["value"]])
                    if operator == "state-integer-subtract"
                    else variables[instruction["value"]],
                    numeric,
                    declaration,
                    structured_authority=structured_authority,
                    structured_resource_limit=structured_resource_limit,
                )
                for alias, alias_target in state_references.items():
                    if canonical_bytes(cast(JsonValue, alias_target)) == target:
                        variables[alias] = state[target]
            else:
                return "", None, None
            if (
                evaluation_site_identity is not None
                and evaluation_sites.get(instruction_index + 1)
                != evaluation_site_identity
            ):
                binding = formula_bindings_by_site.get(evaluation_site_identity)
                if binding is None:
                    return "", None, None
                evaluation = operation_formula_evaluation_record(
                    operation,
                    binding,
                    variables,
                    evaluation_site_identity=evaluation_site_identity,
                    frame_identity=cast(
                        JsonValue, parent_event["snapshot_before_identity"]
                    ),
                    call_path=call_path,
                )
                if evaluation is None:
                    return "", None, None
                formula_evaluations.append(evaluation)
        outcome_definition = next(
            row for row in operation["outcomes"] if row["id"] == outcome
        )
        if outcome_definition["state_policy"] == "rollback":
            state.clear()
            state.update(operation_before)
        result_source = operation["result"]["source"]
        if outcome_definition["kind"] != "success":
            result: JsonValue = None
        elif result_source["kind"] in {"local", "port"}:
            result = cast(JsonValue, variables[result_source["name"]])
        elif result_source["kind"] == "operation-result":
            result = operation_results[result_source["site"]]
        else:
            result = None
        return outcome, result, None

    root_state_references = {name: target for name, target in root_arguments[1].items()}
    root_path = (
        (cast(str, cast(dict[str, JsonValue], parent_event["entrypoint"])["id"]),)
        if parent_event.get("entrypoint") is not None
        else (f"scheduled:{parent_spec['call_site_identity']}",)
    )
    try:
        replayed_outcome, _result, found = execute(
            root_coordinate,
            root_operation,
            root_arguments[0],
            root_state_references,
            root_path,
        )
    except (
        KeyError,
        OverflowError,
        StopIteration,
        StructuredValueFault,
        TypeError,
        ValueError,
    ):
        return None
    if not replayed_outcome and found is None:
        return None
    return found, formula_evaluations


def attempted_operation_charge(
    checked: CheckedExperiment,
    refusing_event: dict[str, Any],
    refusing_event_spec: dict[str, Any],
    *,
    node_steps_before_operation: int,
    bounds: dict[str, int],
    require_budget_breach: bool,
) -> int | None:
    """Replay the exact Operation charge up to one refused instruction."""
    evaluation_site_identity = refusing_event.get("evaluation_site_identity")
    target_instruction_index = refusing_event.get("instruction_index")
    target_path = refusing_event.get("call_path")
    if (
        not isinstance(target_path, str)
        or not isinstance(target_instruction_index, int)
        and not isinstance(evaluation_site_identity, str)
    ):
        return None
    operations = selected_operation_index(checked.rir["selected_semantics"])
    if refusing_event_spec["kind"] == "transition-invocation":
        entrypoint = next(
            (
                row
                for row in checked.rir["entrypoints"]
                if row["id"] == refusing_event_spec["entrypoint"]
            ),
            None,
        )
        root_coordinate = (
            operation_coordinate(cast(dict[str, Any], entrypoint["operation"]))
            if entrypoint is not None
            else None
        )
    elif refusing_event_spec["kind"] == "scheduled-transition":
        operation_reference = refusing_event_spec.get("operation")
        root_coordinate = (
            operation_coordinate(operation_reference)
            if isinstance(operation_reference, dict)
            else None
        )
    else:
        return None
    root_operation = operations.get(root_coordinate) if root_coordinate else None
    if root_operation is None:
        return None
    root_path = target_path.split("/", 1)[0]
    calls = cast(list[dict[str, JsonValue]], refusing_event["attempted_calls"])
    used_calls: set[int] = set()
    node_contracts = runtime_nodes(checked)
    event_charge = 0
    node_steps = node_steps_before_operation

    def is_target(
        operation: dict[str, Any],
        call_path: str,
        instruction_index: int,
        sites: dict[int, str],
    ) -> bool:
        return (
            call_path == target_path
            and operation["id"] == refusing_event["operation"]
            and (
                instruction_index == target_instruction_index
                if isinstance(target_instruction_index, int)
                else sites.get(instruction_index) == evaluation_site_identity
            )
        )

    def charge_instruction(
        operation: dict[str, Any],
        operation_charge: int,
        instruction: dict[str, Any],
    ) -> tuple[int, bool]:
        nonlocal event_charge, node_steps
        amount = cast(
            int, node_contracts[instruction["node"]]["resource_charge"]["amount"]
        )
        operation_charge += amount
        event_charge += amount
        node_steps += amount
        breached = (
            operation_charge > cast(int, operation["resource_bounds"]["max_steps"])
            or event_charge > bounds["max_event_steps"]
            or node_steps > bounds["max_node_steps"]
        )
        return operation_charge, breached

    def completed_invocation(
        instruction: dict[str, Any], parent_path: str
    ) -> dict[str, Any] | None:
        child_path = f"{parent_path}/{instruction['site']}"
        child_coordinate = operation_coordinate(instruction["operation"])
        child = operations.get(child_coordinate)
        call_rows = [
            (index, row)
            for index, row in enumerate(calls)
            if row["site"] == child_path
            and isinstance(row.get("operation"), dict)
            and operation_coordinate(cast(dict[str, Any], row["operation"]))
            == child_coordinate
        ]
        if child is None or len(call_rows) != 1:
            return None
        call_index, call = call_rows[0]
        child_outcome = cast(str, cast(dict[str, JsonValue], call["outcome"])["id"])
        if not completed_operation(child, child_path, child_outcome):
            return None
        mapping = next(
            (row for row in instruction["outcomes"] if row["outcome"] == child_outcome),
            None,
        )
        if mapping is None:
            return None
        used_calls.add(call_index)
        return cast(dict[str, Any], mapping["action"])

    def completed_operation(
        operation: dict[str, Any],
        call_path: str,
        expected_outcome: str,
    ) -> bool:
        operation_charge = 0
        outcome = cast(str, operation["default_outcome"])
        sites = instruction_evaluation_sites(operation)
        body = cast(list[dict[str, Any]], operation["body"])
        expanded_indices = guard_expanded_instruction_indices(body)
        for body_index, instruction in enumerate(body):
            instruction_index = expanded_indices[body_index]
            operation_charge, breached = charge_instruction(
                operation,
                operation_charge,
                instruction,
            )
            if breached or is_target(operation, call_path, instruction_index, sites):
                return False
            operator = node_contracts[instruction["node"]]["semantics"]["operator"]
            if operator == "invoke-operation":
                action = completed_invocation(instruction, call_path)
                if action is None:
                    return False
                if action["kind"] == "propagate":
                    outcome = cast(str, action["outcome"])
                    break
            elif operator == "guarded-outcome-block":
                if instruction["outcome"] != expected_outcome:
                    continue
                for guard_instruction in cast(
                    list[dict[str, Any]], instruction["body"]
                ):
                    operation_charge, breached = charge_instruction(
                        operation,
                        operation_charge,
                        guard_instruction,
                    )
                    if breached:
                        return False
                    guard_operator = node_contracts[guard_instruction["node"]][
                        "semantics"
                    ]["operator"]
                    if guard_operator != "invoke-operation":
                        continue
                    action = completed_invocation(guard_instruction, call_path)
                    if action is None or action["kind"] == "propagate":
                        return False
                outcome = expected_outcome
                break
            elif (
                operator == "gameplay-precondition"
                and instruction["outcome"] == expected_outcome
            ):
                outcome = expected_outcome
                break
        return outcome == expected_outcome

    def charge_to_target(
        operation: dict[str, Any],
        call_path: str,
    ) -> bool:
        operation_charge = 0
        sites = instruction_evaluation_sites(operation)
        body = cast(list[dict[str, Any]], operation["body"])
        expanded_indices = guard_expanded_instruction_indices(body)
        for body_index, instruction in enumerate(body):
            instruction_index = expanded_indices[body_index]
            operation_charge, breached = charge_instruction(
                operation,
                operation_charge,
                instruction,
            )
            target = is_target(operation, call_path, instruction_index, sites)
            if breached or target:
                return target and (breached or not require_budget_breach)
            operator = node_contracts[instruction["node"]]["semantics"]["operator"]
            if operator == "guarded-outcome-block":
                guard_body = cast(list[dict[str, Any]], instruction["body"])
                guard_start = instruction_index + 1
                guard_stop = guard_start + len(guard_body)
                target_is_directly_in_guard = (
                    call_path == target_path
                    and operation["id"] == refusing_event["operation"]
                    and isinstance(target_instruction_index, int)
                    and guard_start <= target_instruction_index < guard_stop
                )
                target_is_in_guard_call = any(
                    node_contracts[guard_instruction["node"]]["semantics"]["operator"]
                    == "invoke-operation"
                    and (
                        target_path == f"{call_path}/{guard_instruction['site']}"
                        or target_path.startswith(
                            f"{call_path}/{guard_instruction['site']}/"
                        )
                    )
                    for guard_instruction in guard_body
                )
                if not (target_is_directly_in_guard or target_is_in_guard_call):
                    continue
                for guard_offset, guard_instruction in enumerate(guard_body):
                    operation_charge, breached = charge_instruction(
                        operation,
                        operation_charge,
                        guard_instruction,
                    )
                    guard_index = guard_start + guard_offset
                    target = is_target(operation, call_path, guard_index, sites)
                    if breached or target:
                        return target and (breached or not require_budget_breach)
                    guard_operator = node_contracts[guard_instruction["node"]][
                        "semantics"
                    ]["operator"]
                    if guard_operator != "invoke-operation":
                        continue
                    child_path = f"{call_path}/{guard_instruction['site']}"
                    child = operations.get(
                        operation_coordinate(guard_instruction["operation"])
                    )
                    if child is None:
                        return False
                    if target_path == child_path or target_path.startswith(
                        f"{child_path}/"
                    ):
                        return charge_to_target(child, child_path)
                    action = completed_invocation(guard_instruction, call_path)
                    if action is None or action["kind"] == "propagate":
                        return False
                return False
            if operator != "invoke-operation":
                continue
            child_path = f"{call_path}/{instruction['site']}"
            child = operations.get(operation_coordinate(instruction["operation"]))
            if child is None:
                return False
            if target_path == child_path or target_path.startswith(f"{child_path}/"):
                return charge_to_target(child, child_path)
            action = completed_invocation(instruction, call_path)
            if action is None or action["kind"] == "propagate":
                return False
        return False

    reached_target = charge_to_target(root_operation, root_path)
    if not reached_target or used_calls != set(range(len(calls))):
        return None
    return event_charge
