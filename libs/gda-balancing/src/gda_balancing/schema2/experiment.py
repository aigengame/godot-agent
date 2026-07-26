"""Exact-authority Experiment admission and deterministic event evaluation."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import jsonschema

from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.bootstrap import admit_authorities
from gda_balancing.schema2.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bootstrap_refusal,
)
from gda_balancing.schema2.model import (
    PublicationMember,
    admit_resolved_model,
    find_published_artifact,
    identified_artifact,
    verify_artifact,
    wire_schema_identity,
)

_EXPERIMENT_IDENTITY_DOMAIN = "experiment-specification-v2"
_EVALUATOR_IMPLEMENTATION = "gda-balancing.deterministic-event-evaluator-v1"
_MASK_64 = (1 << 64) - 1
_MIN_INT64 = -(1 << 63)
_MAX_INT64 = (1 << 63) - 1


@dataclass(frozen=True)
class CheckedExperiment:
    value: dict[str, Any]
    content_identity: str
    kernel: dict[str, Any]
    language_bundle: dict[str, Any]
    build_receipt: dict[str, Any]
    package_lock: dict[str, Any]
    resolved_model: dict[str, Any]
    rir: dict[str, Any]


@dataclass(frozen=True)
class EvaluationArtifacts:
    members: dict[str, PublicationMember]
    accepted: bool
    failed_metrics: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeRefusalOutcome:
    report: Schema2RefusalReport
    committed_trace_prefix: tuple[dict[str, JsonValue], ...]
    last_state: dict[str, int]
    refusing_event_index: int
    refusing_operation: str
    state_before: dict[str, int]
    state_after: dict[str, int]


def _raw_identity(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _refusal(
    *,
    stage: str,
    code: str,
    identity: str,
    pointer: str,
    message: str,
) -> Schema2RefusalReport:
    return Schema2RefusalReport(
        stage=cast(Any, stage),
        diagnostics=(
            Schema2Diagnostic(
                code=code,
                message=message,
                primary=ArtifactLocation(
                    content_identity=identity,
                    pointer=pointer,
                ),
            ),
        ),
        truncated=False,
    )


def _experiment_schema(language_bundle: dict[str, Any]) -> dict[str, Any]:
    matches = [
        item["schema"]
        for item in language_bundle["language"]["artifact_wire_schemas"]
        if item["artifact_kind"] == "experiment-specification"
    ]
    if len(matches) != 1:
        raise ValueError("Experiment Specification schema is not unique")
    return cast(dict[str, Any], matches[0])


def _first_schema_error(
    value: dict[str, Any], schema: dict[str, Any]
) -> jsonschema.ValidationError | None:
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    return errors[0] if errors else None


def _pointer(parts: Any) -> str:
    encoded = []
    for part in parts:
        encoded.append(str(part).replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(encoded) if encoded else ""


def _unique_rows(rows: list[dict[str, Any]], member: str) -> bool:
    values = [row[member] for row in rows]
    return len(values) == len(set(values))


def _artifact(
    checked: CheckedExperiment,
    artifact_kind: str,
    payload: dict[str, JsonValue],
) -> PublicationMember:
    value = identified_artifact(
        checked.language_bundle,
        artifact_kind,
        payload,
    )
    return PublicationMember(
        value=value,
        artifact_kind=artifact_kind,
        wire_schema_identity=wire_schema_identity(
            checked.language_bundle, artifact_kind
        ),
        content_identity=cast(str, value["content_identity"]),
    )


def check_experiment(path: str) -> CheckedExperiment | Schema2RefusalReport:
    """Admit one exact Experiment Specification and its model bindings."""
    try:
        data = Path(path).read_bytes()
    except OSError as err:
        from gda_balancing.envelope import UnreadableInputError

        raise UnreadableInputError(f"cannot read input document: {path}") from err

    kernel, language_bundle = load_authorities()
    admission = admit_authorities(kernel, language_bundle)
    if not admission.admitted:
        return bootstrap_refusal(admission)
    observed_identity = _raw_identity(data)
    if len(data) > language_bundle["resources"]["max_source_bytes"]:
        return _refusal(
            stage="ingress",
            code="language.source_too_large",
            identity=observed_identity,
            pointer="",
            message="Experiment Specification exceeds the admitted ingress bound",
        )
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _refusal(
            stage="parse",
            code="language.source_parse_failure",
            identity=observed_identity,
            pointer="",
            message="Experiment Specification is not canonical JSON data",
        )
    if not isinstance(value, dict):
        return _refusal(
            stage="static",
            code="language.source_contract_mismatch",
            identity=observed_identity,
            pointer="",
            message="Experiment Specification must be an object",
        )
    experiment_identity = content_identity(
        _EXPERIMENT_IDENTITY_DOMAIN, cast(JsonValue, value)
    )
    schema_error = _first_schema_error(value, _experiment_schema(language_bundle))
    if schema_error is not None:
        return _refusal(
            stage="static",
            code="language.source_contract_mismatch",
            identity=experiment_identity,
            pointer=_pointer(schema_error.absolute_path),
            message=schema_error.message,
        )
    if (
        value["kernel_identity"] != kernel["content_identity"]
        or value["language_bundle_identity"] != language_bundle["content_identity"]
    ):
        return _refusal(
            stage="resolution",
            code="language.resolved_authority_mismatch",
            identity=experiment_identity,
            pointer="/kernel_identity",
            message="Experiment Specification does not bind the active authorities",
        )
    for collection, member in (
        (value["scenarios"], "id"),
        (value["metrics"], "id"),
    ):
        if not _unique_rows(collection, member):
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer="",
                message=f"Experiment {member} values must be unique",
            )
    for scenario_index, scenario in enumerate(value["scenarios"]):
        if (
            not _unique_rows(scenario["values"], "name")
            or len(scenario["named_streams"]) != len(set(scenario["named_streams"]))
            or scenario["terminal_condition"]["maximum"] != 1
        ):
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}",
                message=(
                    "The deterministic-event-v1 slice requires unique values, "
                    "unique streams, and one terminal Event"
                ),
            )
    for metric_index, metric in enumerate(value["metrics"]):
        if metric["target"]["minimum"] > metric["target"]["maximum"]:
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/metrics/{metric_index}/target",
                message="Metric target minimum exceeds maximum",
            )

    model = value["model"]
    artifact_kinds = {
        "build_receipt": "build-receipt",
        "package_lock": "package-lock",
        "resolved_model": "resolved-model",
        "rir": "rir-semantic-payload",
    }
    identity_members = {
        "build_receipt": "build_receipt_identity",
        "package_lock": "package_lock_identity",
        "resolved_model": "resolved_model_identity",
        "rir": "rir_identity",
    }
    artifacts: dict[str, dict[str, Any]] = {}
    for name, kind in artifact_kinds.items():
        artifact = find_published_artifact(
            model[identity_members[name]],
            kind,
            language_bundle,
        )
        if artifact is None:
            return _refusal(
                stage="resolution",
                code="language.resolved_authority_mismatch",
                identity=experiment_identity,
                pointer=f"/model/{identity_members[name]}",
                message=f"Exact {kind} is unavailable in the committed artifact store",
            )
        artifacts[name] = artifact
    if not admit_resolved_model(
        {
            "package-lock": artifacts["package_lock"],
            "resolved-model": artifacts["resolved_model"],
            "rir-semantic-payload": artifacts["rir"],
        }
    ).admitted:
        return _refusal(
            stage="resolution",
            code="language.resolved_authority_mismatch",
            identity=experiment_identity,
            pointer="/model",
            message="Experiment model artifacts do not form one admitted Resolved Model",
        )
    build = artifacts["build_receipt"]
    expected_build_bindings = {
        "source_identity": model["source_identity"],
        "kernel_identity": value["kernel_identity"],
        "language_bundle_identity": value["language_bundle_identity"],
        "package_lock_identity": model["package_lock_identity"],
        "resolved_model_identity": model["resolved_model_identity"],
        "rir_identity": model["rir_identity"],
    }
    if any(
        build.get(name) != expected
        for name, expected in expected_build_bindings.items()
    ):
        return _refusal(
            stage="resolution",
            code="language.resolved_authority_mismatch",
            identity=experiment_identity,
            pointer="/model",
            message="Experiment Model binding disagrees with its exact Build receipt",
        )

    rir = artifacts["rir"]
    selected = rir["selected_semantics"]
    operations = {
        row["definition"]["id"]: row["definition"] for row in selected["operations"]
    }
    runtime_profiles = {row["id"]: row for row in selected["runtime_profiles"]}
    declarations = {row["symbol"]: row for row in rir["declarations"]}
    required_profile = value["runtime"]["profile"]
    if required_profile not in runtime_profiles:
        return _refusal(
            stage="resolution",
            code="language.resolution_binding_mismatch",
            identity=experiment_identity,
            pointer="/runtime/profile",
            message="Experiment Runtime profile is absent from the selected RIR",
        )
    for scenario_index, scenario in enumerate(value["scenarios"]):
        operation = operations.get(scenario["operation"])
        if operation is None:
            return _refusal(
                stage="resolution",
                code="language.resolution_binding_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/operation",
                message="Scenario operation is absent from the selected RIR",
            )
        if operation["runtime_profile"] != required_profile:
            return _refusal(
                stage="resolution",
                code="language.resolution_binding_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/operation",
                message="Scenario operation requires another Runtime profile",
            )
        provided = {row["name"] for row in scenario["values"]}
        required = {row["name"] for row in operation["inputs"]}
        if provided != required or not provided <= declarations.keys():
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/values",
                message="Scenario values do not exactly close the operation inputs",
            )
        draws = {
            instruction["stream"]
            for instruction in operation["body"]
            if instruction["node"] == "draw"
        }
        if draws != set(scenario["named_streams"]):
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/named_streams",
                message="Scenario Named streams do not exactly close operation draws",
            )
        for row in scenario["values"]:
            declaration = declarations[row["name"]]
            domain = declaration["domain"]
            if not domain["minimum"] <= row["value"] <= domain["maximum"]:
                return _refusal(
                    stage="static",
                    code="language.invalid_domain",
                    identity=experiment_identity,
                    pointer=f"/scenarios/{scenario_index}/values",
                    message="Scenario value is outside its declared domain",
                )
    return CheckedExperiment(
        value=value,
        content_identity=experiment_identity,
        kernel=kernel,
        language_bundle=language_bundle,
        build_receipt=build,
        package_lock=artifacts["package_lock"],
        resolved_model=artifacts["resolved_model"],
        rir=rir,
    )


def _signed_int64(value: int) -> int:
    if value < _MIN_INT64 or value > _MAX_INT64:
        raise OverflowError("exact-int64 arithmetic overflow")
    return value


class _NamedRng:
    def __init__(self, seed: int) -> None:
        self._seed = seed & _MASK_64
        self._states: dict[str, int] = {}
        self._indices: dict[str, int] = {}

    def draw(self, stream: str, minimum: int, maximum: int) -> tuple[int, int]:
        if minimum > maximum:
            raise ValueError("invalid deterministic draw interval")
        if stream not in self._states:
            digest = hashlib.sha256(stream.encode("utf-8")).digest()
            self._states[stream] = (
                self._seed + int.from_bytes(digest[:8], "big")
            ) & _MASK_64
            self._indices[stream] = 0
        state = (self._states[stream] + 0x9E3779B97F4A7C15) & _MASK_64
        self._states[stream] = state
        mixed = state
        mixed = ((mixed ^ (mixed >> 30)) * 0xBF58476D1CE4E5B9) & _MASK_64
        mixed = ((mixed ^ (mixed >> 27)) * 0x94D049BB133111EB) & _MASK_64
        mixed ^= mixed >> 31
        index = self._indices[stream]
        self._indices[stream] = index + 1
        return minimum + mixed % (maximum - minimum + 1), index


def _value_rows(values: dict[str, Any]) -> list[dict[str, JsonValue]]:
    rows: list[dict[str, JsonValue]] = []
    for name in sorted(values):
        value = values[name]
        if isinstance(value, bool):
            rows.append({"name": name, "kind": "boolean", "boolean": value})
        elif isinstance(value, int):
            rows.append({"name": name, "kind": "integer", "integer": value})
        elif isinstance(value, str):
            rows.append({"name": name, "kind": "string", "string": value})
        else:
            raise TypeError("runtime fact is not canonically representable")
    return rows


def _int_rows(values: dict[str, int]) -> list[dict[str, JsonValue]]:
    return [{"name": name, "value": values[name]} for name in sorted(values)]


def _evaluator_manifest(checked: CheckedExperiment) -> PublicationMember:
    runtime_contract = checked.kernel["meta_format"]["runtime_program"]
    nodes = sorted(
        {
            *runtime_contract["expression_nodes"],
            *runtime_contract["control_nodes"],
            *runtime_contract["effect_nodes"],
        }
    )
    implementation_identity = content_identity(
        "evaluator-implementation-v1",
        {
            "implementation": _EVALUATOR_IMPLEMENTATION,
            "operation_kinds": ["event-program"],
            "instruction_nodes": nodes,
            "effects": [
                "event.commit",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            ],
            "numeric_policies": ["exact-int64"],
            "rng_algorithms": ["splitmix64-v1"],
            "runtime_profiles": ["deterministic-event-v1"],
        },
    )
    return _artifact(
        checked,
        "evaluator-capability-manifest",
        {
            "implementation_identity": implementation_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "operation_kinds": ["event-program"],
            "instruction_nodes": nodes,
            "effects": [
                "event.commit",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            ],
            "numeric_policies": ["exact-int64"],
            "rng_algorithms": ["splitmix64-v1"],
            "runtime_profiles": ["deterministic-event-v1"],
        },
    )


def _resolved_runtime_profile(
    checked: CheckedExperiment, evaluator: PublicationMember
) -> PublicationMember:
    profile_id = checked.value["runtime"]["profile"]
    definition = next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == profile_id
    )
    return _artifact(
        checked,
        "resolved-runtime-profile",
        {
            "experiment_identity": checked.content_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": checked.package_lock["content_identity"],
            "resolved_model_identity": checked.resolved_model["content_identity"],
            "rir_identity": checked.rir["content_identity"],
            "evaluator_manifest_identity": evaluator.content_identity,
            "runtime_profile": {
                "id": definition["id"],
                "version": definition["version"],
                "evaluation": definition["evaluation"],
                "numeric_policy": definition["numeric_policy"],
                "effects": definition["effects"],
                "max_steps": definition["resource_bounds"]["max_steps"],
            },
            "rng_algorithm": checked.value["seed"]["algorithm"],
            "platform": {
                "implementation": platform.python_implementation(),
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine() or "unknown",
            },
        },
    )


def _check_evaluator_requirements(
    checked: CheckedExperiment, evaluator: PublicationMember
) -> Schema2RefusalReport | None:
    required = checked.value["runtime"]["required_evaluator"]
    available = evaluator.value
    for member in (
        "operation_kinds",
        "instruction_nodes",
        "effects",
        "numeric_policies",
        "rng_algorithms",
    ):
        if not set(required[member]) <= set(available[member]):
            return _refusal(
                stage="runtime",
                code="rpg.runtime_capability_unsupported",
                identity=checked.content_identity,
                pointer=f"/runtime/required_evaluator/{member}",
                message=f"Evaluator does not provide every required {member}",
            )
    return None


def _reproduction_receipt(
    checked: CheckedExperiment,
    evaluator: PublicationMember,
    resolved_runtime: PublicationMember,
) -> PublicationMember:
    return _artifact(
        checked,
        "reproduction-receipt",
        {
            "experiment_identity": checked.content_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": checked.package_lock["content_identity"],
            "resolved_model_identity": checked.resolved_model["content_identity"],
            "rir_identity": checked.rir["content_identity"],
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "evaluator_manifest_identity": evaluator.content_identity,
            "seed_algorithm": checked.value["seed"]["algorithm"],
            "seed_value": checked.value["seed"]["value"],
            "external_inputs": checked.value["external_inputs"],
        },
    )


def runtime_terminal_audit_members(
    checked: CheckedExperiment,
    outcome: RuntimeRefusalOutcome,
) -> dict[str, PublicationMember]:
    """Prepare the complete terminal-only artifact set for runtime refusal."""
    report = outcome.report
    if report.stage != "runtime":
        raise ValueError("terminal audit requires one runtime refusal")
    evaluator = _evaluator_manifest(checked)
    resolved_runtime = _resolved_runtime_profile(checked, evaluator)
    reproduction = _reproduction_receipt(checked, evaluator, resolved_runtime)
    scenario = checked.value["scenarios"][0]
    diagnostic = report.diagnostics[0]
    audit = _artifact(
        checked,
        "runtime-terminal-audit",
        {
            "experiment_identity": checked.content_identity,
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "evaluator_manifest_identity": evaluator.content_identity,
            "scenario": scenario["id"],
            "committed_trace_prefix": list(outcome.committed_trace_prefix),
            "last_snapshot": _int_rows(outcome.last_state),
            "refusing_event": {
                "index": outcome.refusing_event_index,
                "operation": outcome.refusing_operation,
                "reason": diagnostic.code,
            },
            "rollback": {
                "committed": False,
                "state_before": _int_rows(outcome.state_before),
                "state_after": _int_rows(outcome.state_after),
            },
            "diagnostic": {
                **diagnostic.model_dump(mode="json"),
                "stage": "runtime",
            },
            "reproduction_receipt_identity": reproduction.content_identity,
        },
    )
    return {
        "runtime-terminal-audit": audit,
        "reproduction-receipt": reproduction,
        "resolved-runtime-profile": resolved_runtime,
        "evaluator-capability-manifest": evaluator,
    }


def _scenario_state(
    scenario: dict[str, Any],
    declarations: dict[str, dict[str, Any]],
) -> dict[str, int]:
    return {
        row["name"]: row["value"]
        for row in scenario["values"]
        if declarations[row["name"]]["role"] == "state"
    }


def _runtime_refusal_outcome(
    checked: CheckedExperiment,
    *,
    code: str,
    message: str,
    events: list[dict[str, JsonValue]],
    operation: str,
    state_before: dict[str, int],
) -> RuntimeRefusalOutcome:
    report = _refusal(
        stage="runtime",
        code=code,
        identity=checked.content_identity,
        pointer=f"/scenarios/{len(events)}/operation",
        message=message,
    )
    return RuntimeRefusalOutcome(
        report=report,
        committed_trace_prefix=tuple(
            {
                "index": event["index"],
                "operation": event["operation"],
                "outcome": event["outcome"],
            }
            for event in events
        ),
        last_state=dict(state_before),
        refusing_event_index=len(events),
        refusing_operation=operation,
        state_before=dict(state_before),
        state_after=dict(state_before),
    )


def evaluate_experiment(
    checked: CheckedExperiment,
) -> EvaluationArtifacts | RuntimeRefusalOutcome | Schema2RefusalReport:
    """Evaluate one checked deterministic-event Experiment without publishing."""
    evaluator = _evaluator_manifest(checked)
    capability_refusal = _check_evaluator_requirements(checked, evaluator)
    if capability_refusal is not None:
        declarations = {row["symbol"]: row for row in checked.rir["declarations"]}
        scenario = checked.value["scenarios"][0]
        return RuntimeRefusalOutcome(
            report=capability_refusal,
            committed_trace_prefix=(),
            last_state=_scenario_state(scenario, declarations),
            refusing_event_index=0,
            refusing_operation=scenario["operation"],
            state_before=_scenario_state(scenario, declarations),
            state_after=_scenario_state(scenario, declarations),
        )
    resolved_runtime = _resolved_runtime_profile(checked, evaluator)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    declarations = {row["symbol"]: row for row in checked.rir["declarations"]}
    rng = _NamedRng(checked.value["seed"]["value"])
    events: list[dict[str, JsonValue]] = []
    snapshots: list[dict[str, JsonValue]] = []
    scenario_outputs: dict[str, tuple[dict[str, Any], dict[str, int], str]] = {}
    total_steps = 0
    runtime_limit = checked.language_bundle["resources"]["max_runtime_steps"]
    for scenario in checked.value["scenarios"]:
        variables = {row["name"]: row["value"] for row in scenario["values"]}
        state = _scenario_state(scenario, declarations)
        before = dict(state)
        snapshots.append(
            {
                "index": len(snapshots),
                "name": f"{scenario['id']}:initial",
                "values": _int_rows(state),
            }
        )
        operation = operations[scenario["operation"]]
        outcome = "cast-resolved"
        draws: list[dict[str, JsonValue]] = []
        for instruction in operation["body"]:
            total_steps += 1
            if (
                total_steps > runtime_limit
                or total_steps > operation["resource_bounds"]["max_steps"]
            ):
                return _runtime_refusal_outcome(
                    checked,
                    code="rpg.runtime_step_limit_exceeded",
                    message="Runtime program exhausted its exact step bound",
                    events=events,
                    operation=operation["id"],
                    state_before=before,
                )
            node = instruction["node"]
            if node == "precondition-greater-than-or-equal":
                if variables[instruction["left"]] < variables[instruction["right"]]:
                    outcome = instruction["outcome"]
                    break
            elif node == "draw":
                value, index = rng.draw(
                    instruction["stream"],
                    instruction["minimum"],
                    instruction["maximum"],
                )
                variables[instruction["target"]] = value
                draws.append(
                    {
                        "stream": instruction["stream"],
                        "index": index,
                        "minimum": instruction["minimum"],
                        "maximum": instruction["maximum"],
                        "value": value,
                    }
                )
            elif node == "constant":
                variables[instruction["target"]] = instruction["literal"]
            elif node == "copy":
                variables[instruction["target"]] = variables[instruction["value"]]
            elif node in {"add", "subtract", "multiply", "maximum"}:
                left = variables[instruction["left"]]
                right = variables[instruction["right"]]
                if node == "add":
                    result = left + right
                elif node == "subtract":
                    result = left - right
                elif node == "multiply":
                    result = left * right
                else:
                    result = max(left, right)
                try:
                    variables[instruction["target"]] = _signed_int64(result)
                except OverflowError:
                    return _runtime_refusal_outcome(
                        checked,
                        code="rpg.runtime_numeric_overflow",
                        message="Exact-int64 operation overflowed its numeric domain",
                        events=events,
                        operation=operation["id"],
                        state_before=before,
                    )
            elif node in {
                "greater-than-or-equal",
                "less-than",
                "less-than-or-equal",
            }:
                left = variables[instruction["left"]]
                right = variables[instruction["right"]]
                variables[instruction["target"]] = {
                    "greater-than-or-equal": left >= right,
                    "less-than": left < right,
                    "less-than-or-equal": left <= right,
                }[node]
            elif node == "if":
                variables[instruction["target"]] = variables[
                    instruction[
                        "when_true"
                        if variables[instruction["condition"]]
                        else "when_false"
                    ]
                ]
            elif node == "subtract-state":
                symbol = instruction["symbol"]
                try:
                    state[symbol] = _signed_int64(
                        state[symbol] - variables[instruction["value"]]
                    )
                except OverflowError:
                    return _runtime_refusal_outcome(
                        checked,
                        code="rpg.runtime_numeric_overflow",
                        message="Exact-int64 state update overflowed its numeric domain",
                        events=events,
                        operation=operation["id"],
                        state_before=before,
                    )
                variables[symbol] = state[symbol]
            elif node == "write-state":
                symbol = instruction["symbol"]
                try:
                    state[symbol] = _signed_int64(variables[instruction["value"]])
                except OverflowError:
                    return _runtime_refusal_outcome(
                        checked,
                        code="rpg.runtime_numeric_overflow",
                        message="Exact-int64 state update overflowed its numeric domain",
                        events=events,
                        operation=operation["id"],
                        state_before=before,
                    )
                variables[symbol] = state[symbol]
            else:
                return _runtime_refusal_outcome(
                    checked,
                    code="rpg.runtime_capability_unsupported",
                    message=f"Evaluator does not support instruction node {node}",
                    events=events,
                    operation=operation["id"],
                    state_before=before,
                )
        if outcome != "cast-resolved":
            state = before
            for name, value in before.items():
                variables[name] = value
        event = {
            "index": len(events),
            "operation": operation["id"],
            "outcome": outcome,
            "facts": _value_rows(variables),
            "state_before": _int_rows(before),
            "state_after": _int_rows(state),
            "rng_draws": draws,
        }
        events.append(event)
        snapshots.append(
            {
                "index": len(snapshots),
                "name": f"{scenario['id']}:terminal",
                "values": _int_rows(state),
            }
        )
        scenario_outputs[scenario["id"]] = (event, state, outcome)

    samples: list[dict[str, JsonValue]] = []
    for metric in checked.value["metrics"]:
        observation = metric["observation"]
        matched: list[tuple[str, int]] = []
        for scenario in checked.value["scenarios"]:
            event, state, outcome = scenario_outputs[scenario["id"]]
            if observation["source"] == "event":
                if outcome != observation["name"]:
                    continue
                facts = {
                    row["name"]: row.get("integer")
                    for row in event["facts"]
                    if row["kind"] == "integer"
                }
                value = facts.get(observation["member"])
            else:
                expected_name = observation["name"]
                if expected_name not in {"terminal", f"{scenario['id']}:terminal"}:
                    continue
                value = state.get(observation["member"])
            if isinstance(value, int):
                matched.append((scenario["id"], value))
        if len(matched) != 1:
            return _refusal(
                stage="evaluation",
                code="rpg.evaluation_observation_unavailable",
                identity=checked.content_identity,
                pointer=f"/metrics/{metric['id']}/observation",
                message="Metric observation did not resolve to exactly one value",
            )
        scenario_id, value = matched[0]
        target = metric["target"]
        samples.append(
            {
                "metric": metric["id"],
                "scenario": scenario_id,
                "value": value,
                "unit": metric["unit"],
                "within_target": target["minimum"] <= value <= target["maximum"],
                "source": observation["source"],
                "member": observation["member"],
            }
        )

    trace = _artifact(
        checked,
        "event-trace",
        {
            "experiment_identity": checked.content_identity,
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "scenario": ",".join(row["id"] for row in checked.value["scenarios"]),
            "events": events,
        },
    )
    snapshot_series = _artifact(
        checked,
        "snapshot-series",
        {
            "experiment_identity": checked.content_identity,
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "scenario": ",".join(row["id"] for row in checked.value["scenarios"]),
            "snapshots": snapshots,
        },
    )
    metric_dataset = _artifact(
        checked,
        "metric-dataset",
        {
            "experiment_identity": checked.content_identity,
            "resolved_runtime_profile_identity": resolved_runtime.content_identity,
            "samples": samples,
        },
    )
    reproduction = _reproduction_receipt(checked, evaluator, resolved_runtime)
    failed_metrics = tuple(
        cast(str, sample["metric"])
        for sample in samples
        if sample["within_target"] is False
    )
    if failed_metrics:
        primary = _artifact(
            checked,
            "experiment-verdict",
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "event_trace_identity": trace.content_identity,
                "snapshot_series_identity": snapshot_series.content_identity,
                "metric_dataset_identity": metric_dataset.content_identity,
                "reproduction_receipt_identity": reproduction.content_identity,
                "outcome": "rejected",
                "failed_metrics": list(failed_metrics),
            },
        )
        primary_name = "experiment-verdict"
    else:
        primary = _artifact(
            checked,
            "evaluation-run",
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "evaluator_manifest_identity": evaluator.content_identity,
                "event_trace_identity": trace.content_identity,
                "snapshot_series_identity": snapshot_series.content_identity,
                "metric_dataset_identity": metric_dataset.content_identity,
                "reproduction_receipt_identity": reproduction.content_identity,
                "outcome": "accepted",
            },
        )
        primary_name = "evaluation-run"
    return EvaluationArtifacts(
        members={
            primary_name: primary,
            "event-trace": trace,
            "snapshot-series": snapshot_series,
            "metric-dataset": metric_dataset,
            "reproduction-receipt": reproduction,
            "resolved-runtime-profile": resolved_runtime,
            "evaluator-capability-manifest": evaluator,
        },
        accepted=not failed_metrics,
        failed_metrics=failed_metrics,
    )


def experiment_input_identity(value: dict[str, Any]) -> str:
    """Bind publication retries to the exact Experiment Specification."""
    return content_identity(_EXPERIMENT_IDENTITY_DOMAIN, cast(JsonValue, value))


def validate_experiment_member(
    checked: CheckedExperiment, logical_name: str, value: dict[str, Any]
) -> bool:
    """Re-admit one prepared Experiment output against the exact LDB."""
    del logical_name
    return verify_artifact(value, checked.language_bundle)


def canonical_experiment_bytes(value: dict[str, Any]) -> bytes:
    """Expose canonical bytes for descriptor-owned command-input identity."""
    return canonical_bytes(cast(JsonValue, value))
