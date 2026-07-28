"""Exact-authority Experiment admission and deterministic event evaluation."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, cast

import jsonschema

from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.bootstrap import admit_authorities
from gda_balancing.schema2.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
    parse_canonical_object,
)
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
_SUPPORTED_RUNTIME_OPERATORS = frozenset(
    {
        "copy-value",
        "gameplay-precondition",
        "integer-add",
        "integer-compare",
        "integer-literal",
        "integer-maximum",
        "integer-multiply",
        "integer-subtract",
        "invoke-operation",
        "named-integer-draw",
        "select-value",
        "state-integer-subtract",
        "state-write",
    }
)


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
    scenario_id: str
    scenario_index: int
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


def _unique_canonical_rows(rows: list[dict[str, Any]], member: str) -> bool:
    values = [canonical_bytes(cast(JsonValue, row[member])) for row in rows]
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


def _runtime_contract(checked: CheckedExperiment) -> dict[str, Any]:
    return cast(dict[str, Any], checked.kernel["meta_format"]["runtime_program"])


def _runtime_nodes(checked: CheckedExperiment) -> dict[str, dict[str, Any]]:
    return {
        row["id"]: row
        for row in cast(list[dict[str, Any]], _runtime_contract(checked)["nodes"])
    }


def _expanded_operation_body(
    operation: dict[str, Any],
    operations: dict[str, dict[str, Any]],
    visiting: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Expand generic Operation composition without package-specific dispatch."""
    operation_id = cast(str, operation["id"])
    if operation_id in visiting:
        raise ValueError("admitted Operation composition is cyclic")
    nested_visiting = visiting | {operation_id}
    expanded: list[dict[str, Any]] = []
    for instruction in cast(list[dict[str, Any]], operation["body"]):
        expanded.append(instruction)
        if instruction["node"] != "invoke":
            continue
        operation_ref = cast(dict[str, Any], instruction["operation"])
        invoked = operations.get(cast(str, operation_ref["id"]))
        if invoked is None:
            raise ValueError("admitted Operation composition target is absent")
        expanded.extend(_expanded_operation_body(invoked, operations, nested_visiting))
    return expanded


def _diagnostic_for_signal(checked: CheckedExperiment, signal: str, stage: str) -> str:
    matches = [
        reason["diagnostic"]
        for reason in checked.language_bundle["language"]["reasons"]
        if reason.get("signal") == signal and reason.get("stage") == stage
    ]
    if len(matches) != 1:
        raise ValueError(f"admitted Diagnostic signal is not unique: {signal}")
    return cast(str, matches[0])


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
        value = parse_canonical_object(
            data,
            artifact_name="Experiment Specification",
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return _refusal(
            stage="parse",
            code="language.source_parse_failure",
            identity=observed_identity,
            pointer="",
            message="Experiment Specification is not canonical JSON data",
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
    if value["external_inputs"]:
        return _refusal(
            stage="static",
            code="language.source_contract_mismatch",
            identity=experiment_identity,
            pointer="/external_inputs",
            message=(
                "The bounded RPG Experiment slice admits no external input "
                "until an LDB-owned input judgment is selected"
            ),
        )
    for scenario_index, scenario in enumerate(value["scenarios"]):
        if (
            not _unique_canonical_rows(scenario["assignments"], "target")
            or len(scenario["named_streams"]) != len(set(scenario["named_streams"]))
            or scenario["terminal_condition"]["maximum"] != 1
        ):
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}",
                message=(
                    "The deterministic-event-v1 slice requires unique assignments, "
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
    entrypoints = {row["id"]: row for row in rir["entrypoints"]}
    runtime_profiles = {row["id"]: row for row in selected["runtime_profiles"]}
    declarations = {
        canonical_bytes(cast(JsonValue, row["resolved_symbol"])): row
        for row in rir["declarations"]
    }
    required_profile = value["runtime"]["profile"]
    if required_profile not in runtime_profiles:
        return _refusal(
            stage="resolution",
            code="language.resolution_binding_mismatch",
            identity=experiment_identity,
            pointer="/runtime/profile",
            message="Experiment Runtime profile is absent from the selected RIR",
        )
    required_operation_kinds: set[str] = set()
    required_instruction_nodes: set[str] = set()
    required_effects: set[str] = set()
    required_numeric_policies: set[str] = set()
    required_rng_algorithms: set[str] = set()
    for scenario_index, scenario in enumerate(value["scenarios"]):
        entrypoint = entrypoints.get(scenario["entrypoint"])
        if entrypoint is None:
            return _refusal(
                stage="resolution",
                code="language.resolution_binding_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/entrypoint",
                message="Scenario entrypoint is absent from the selected RIR",
            )
        operation = operations.get(entrypoint["operation"]["id"])
        if operation is None:
            return _refusal(
                stage="resolution",
                code="language.resolution_binding_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/entrypoint",
                message="Scenario entrypoint Operation is absent from the selected RIR",
            )
        if operation["runtime_profile"] != required_profile:
            return _refusal(
                stage="resolution",
                code="language.resolution_binding_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/entrypoint",
                message="Scenario entrypoint requires another Runtime profile",
            )
        try:
            expanded_body = _expanded_operation_body(operation, operations)
        except ValueError:
            return _refusal(
                stage="resolution",
                code="language.resolution_binding_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/entrypoint",
                message="Scenario Operation composition is not closed",
            )
        required_operation_kinds.update(
            operations[instruction["operation"]["id"]]["operation_kind"]
            for instruction in expanded_body
            if instruction["node"] == "invoke"
        )
        required_operation_kinds.add(operation["operation_kind"])
        required_instruction_nodes.update(
            instruction["node"] for instruction in expanded_body
        )
        required_effects.update(operation["effects"])
        required_numeric_policies.add(operation["numeric_policy"])
        if any(instruction["node"] == "draw" for instruction in expanded_body):
            required_rng_algorithms.add(value["seed"]["algorithm"])
        contract_targets = cast(
            list[dict[str, Any]],
            entrypoint["scenario_input_contract"]["targets"],
        )
        allowed = {
            canonical_bytes(cast(JsonValue, row["target"])): row
            for row in contract_targets
            if row["owner"] == "experiment"
        }
        provided = {
            canonical_bytes(cast(JsonValue, row["target"])): row
            for row in scenario["assignments"]
        }
        required = {
            key
            for key, row in allowed.items()
            if row["cardinality"] == "required"
        }
        if not required <= provided.keys() or not provided.keys() <= allowed.keys():
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/assignments",
                message="Scenario assignments do not close the Scenario Input Contract",
            )
        draws = {
            instruction["stream"]
            for instruction in expanded_body
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
        for row in scenario["assignments"]:
            declaration = declarations[
                canonical_bytes(cast(JsonValue, row["target"]))
            ]
            domain = declaration["domain"]
            if not domain["minimum"] <= row["value"] <= domain["maximum"]:
                return _refusal(
                    stage="static",
                    code="language.invalid_domain",
                    identity=experiment_identity,
                    pointer=f"/scenarios/{scenario_index}/assignments",
                    message="Scenario assignment is outside its declared domain",
                )
    expected_requirements = {
        "operation_kinds": required_operation_kinds,
        "instruction_nodes": required_instruction_nodes,
        "effects": required_effects,
        "numeric_policies": required_numeric_policies,
        "rng_algorithms": required_rng_algorithms,
        "runtime_profiles": {required_profile},
    }
    required_evaluator = value["runtime"]["required_evaluator"]
    for member, expected in expected_requirements.items():
        if set(required_evaluator[member]) != expected:
            return _refusal(
                stage="resolution",
                code="language.resolution_binding_mismatch",
                identity=experiment_identity,
                pointer=f"/runtime/required_evaluator/{member}",
                message=(
                    f"Experiment required {member} do not exactly close "
                    "the selected program"
                ),
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


def _admit_numeric(value: int, numeric: dict[str, Any]) -> int:
    if value < numeric["minimum"] or value > numeric["maximum"]:
        raise OverflowError("exact-int64 arithmetic overflow")
    return value


def _integer_compare(comparison: str, left: int, right: int) -> bool:
    if comparison == "greater-than-or-equal":
        return left >= right
    if comparison == "less-than":
        return left < right
    if comparison == "less-than-or-equal":
        return left <= right
    raise ValueError("unsupported admitted integer comparison")


class _NamedRng:
    def __init__(self, seed: int, contract: dict[str, Any]) -> None:
        if (
            contract["algorithm"] != "splitmix64-v1"
            or contract["word_bits"] != 64
            or contract["seed_encoding"] != "unsigned-modulo-2^64"
        ):
            raise ValueError("unsupported admitted Named-stream RNG contract")
        self._contract = contract
        self._mask = (1 << contract["word_bits"]) - 1
        self._seed = seed & self._mask
        self._states: dict[str, int] = {}
        self._indices: dict[str, int] = {}

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
                self._seed
                + int.from_bytes(
                    digest[start:end],
                    derivation["byte_order"],
                )
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


def _metric_definition_identity(metric: dict[str, Any]) -> str:
    return content_identity(
        "metric-definition-v2",
        cast(
            JsonValue,
            {
                name: metric[name]
                for name in (
                    "id",
                    "kind",
                    "unit",
                    "dimensions",
                    "window",
                    "aggregation",
                    "replication",
                    "missing",
                    "censoring",
                    "observation",
                )
            },
        ),
    )


@cache
def _evaluator_build_identity(root: Path | None = None) -> str:
    """Bind evaluator provenance to the installed Python source build."""
    package_root = root or Path(__file__).parents[1]
    sources: list[JsonValue] = []
    for source in sorted(package_root.rglob("*.py")):
        sources.append(
            {
                "path": source.relative_to(package_root).as_posix(),
                "sha256": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    if not sources:
        raise RuntimeError("evaluator build contains no Python source")
    return content_identity("evaluator-build-v1", sources)


def _evaluator_manifest(checked: CheckedExperiment) -> PublicationMember:
    runtime_contract = _runtime_contract(checked)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    entrypoints = {row["id"]: row for row in checked.rir["entrypoints"]}
    reachable_nodes = {
        instruction["node"]
        for scenario in checked.value["scenarios"]
        for instruction in _expanded_operation_body(
            operations[entrypoints[scenario["entrypoint"]]["operation"]["id"]],
            operations,
        )
    }
    nodes = sorted(
        row["id"]
        for row in runtime_contract["nodes"]
        if row["id"] in reachable_nodes
        and row["semantics"]["operator"] in _SUPPORTED_RUNTIME_OPERATORS
    )
    supported_profiles = sorted(
        row["id"]
        for row in checked.language_bundle["language"]["runtime_profiles"]
        if (
            row.get("evaluation") == runtime_contract["version"]
            and row.get("runtime_program_version") == runtime_contract["version"]
            and row.get("numeric_policy") == "exact-int64"
            and row.get("numeric_law") == runtime_contract["numeric"]["id"]
            and row.get("rng")
            == {
                "algorithm": runtime_contract["named_rng"]["algorithm"],
                "interval_sampling": runtime_contract["named_rng"]["interval_sampling"][
                    "mapping"
                ],
                "bias_policy": runtime_contract["named_rng"]["interval_sampling"][
                    "bias_policy"
                ],
            }
            and row.get("budget_scopes")
            == {
                "operation_max_steps": "per-event",
                "runtime_max_steps": "per-run",
            }
            and set(row["effects"])
            <= {
                "event.commit",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            }
        )
    )
    build_identity = _evaluator_build_identity()
    implementation_identity = content_identity(
        "evaluator-implementation-v1",
        {
            "implementation": _EVALUATOR_IMPLEMENTATION,
            "evaluator_build_identity": build_identity,
            "runtime_program_version": runtime_contract["version"],
            "operation_kinds": ["event-fragment", "event-program"],
            "instruction_nodes": nodes,
            "effects": [
                "event.commit",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            ],
            "numeric_policies": ["exact-int64"],
            "rng_algorithms": ["splitmix64-v1"],
            "runtime_profiles": supported_profiles,
        },
    )
    return _artifact(
        checked,
        "evaluator-capability-manifest",
        {
            "evaluator_build_identity": build_identity,
            "implementation_identity": implementation_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "operation_kinds": ["event-fragment", "event-program"],
            "instruction_nodes": nodes,
            "effects": [
                "event.commit",
                "metric.observe",
                "rng.named-stream",
                "snapshot.commit",
            ],
            "numeric_policies": ["exact-int64"],
            "rng_algorithms": ["splitmix64-v1"],
            "runtime_profiles": supported_profiles,
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
                "runtime_program_version": definition["runtime_program_version"],
                "numeric_law": definition["numeric_law"],
                "rng": definition["rng"],
                "budget_scopes": definition["budget_scopes"],
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
        "runtime_profiles",
    ):
        if not set(required[member]) <= set(available[member]):
            return _refusal(
                stage="resolution",
                code=_diagnostic_for_signal(
                    checked, "capability-unsupported", "resolution"
                ),
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
    diagnostic = report.diagnostics[0]
    audit = _artifact(
        checked,
        "runtime-terminal-audit",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "evaluator_manifest_identity": evaluator.content_identity,
                "scenario": outcome.scenario_id,
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
        ),
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
    scenario_id: str,
    scenario_index: int,
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
        pointer=f"/scenarios/{scenario_index}/operation",
        message=message,
    )
    return RuntimeRefusalOutcome(
        report=report,
        scenario_id=scenario_id,
        scenario_index=scenario_index,
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
        return capability_refusal
    resolved_runtime = _resolved_runtime_profile(checked, evaluator)
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in checked.rir["selected_semantics"]["operations"]
    }
    entrypoints = {row["id"]: row for row in checked.rir["entrypoints"]}
    declarations = {
        canonical_bytes(cast(JsonValue, row["resolved_symbol"])): row
        for row in checked.rir["declarations"]
    }
    runtime_contract = _runtime_contract(checked)
    numeric = cast(dict[str, Any], runtime_contract["numeric"])
    node_contracts = _runtime_nodes(checked)
    rng = _NamedRng(
        checked.value["seed"]["value"],
        cast(dict[str, Any], runtime_contract["named_rng"]),
    )
    events: list[dict[str, JsonValue]] = []
    snapshots: list[dict[str, JsonValue]] = []
    scenario_outputs: dict[str, tuple[dict[str, Any], dict[str, int], str]] = {}
    total_steps = 0
    runtime_limit = checked.language_bundle["resources"]["max_runtime_steps"]
    for scenario_index, scenario in enumerate(checked.value["scenarios"]):
        actual_values: dict[str, Any] = {}
        for declaration in declarations.values():
            value_policy = cast(dict[str, Any], declaration["value_policy"])
            if value_policy["mode"] in {"model-fixed", "experiment-override"}:
                actual_values[declaration["symbol"]] = value_policy["value"]
        for assignment in scenario["assignments"]:
            declaration = declarations[
                canonical_bytes(cast(JsonValue, assignment["target"]))
            ]
            actual_values[declaration["symbol"]] = assignment["value"]
        state = {
            declaration["symbol"]: cast(int, actual_values[declaration["symbol"]])
            for declaration in declarations.values()
            if declaration["role"] == "state"
            and declaration["symbol"] in actual_values
        }
        before = dict(state)
        snapshots.append(
            cast(
                dict[str, JsonValue],
                {
                    "index": len(snapshots),
                    "name": f"{scenario['id']}:initial",
                    "values": _int_rows(state),
                },
            )
        )
        entrypoint = entrypoints[scenario["entrypoint"]]
        operation = operations[entrypoint["operation"]["id"]]
        outcomes = {row["id"]: row for row in operation["outcomes"]}
        draws: list[dict[str, JsonValue]] = []
        call_trace: list[dict[str, JsonValue]] = []

        def execute_operation(
            selected_operation: dict[str, Any],
            arguments: dict[str, Any],
            state_references: dict[str, str],
            call_path: tuple[str, ...],
        ) -> tuple[str, Any]:
            nonlocal total_steps
            operation_before = dict(state)
            variables = dict(arguments)
            outcome = selected_operation["default_outcome"]
            operation_steps = 0
            for instruction in selected_operation["body"]:
                node_contract = node_contracts[instruction["node"]]
                charge = node_contract["resource_charge"]["amount"]
                total_steps += charge
                operation_steps += charge
                if (
                    total_steps > runtime_limit
                    or operation_steps
                    > selected_operation["resource_bounds"]["max_steps"]
                ):
                    raise RuntimeError("step-limit")
                semantics = node_contract["semantics"]
                operator = semantics["operator"]
                if operator == "invoke-operation":
                    child = operations[instruction["operation"]["id"]]
                    child_arguments: dict[str, Any] = {}
                    child_state_references: dict[str, str] = {}
                    for binding in instruction["arguments"]:
                        actual = binding["operand"]
                        if actual["kind"] == "port":
                            child_arguments[binding["port"]] = variables[
                                actual["port"]
                            ]
                            if actual["port"] in state_references:
                                child_state_references[binding["port"]] = (
                                    state_references[actual["port"]]
                                )
                        elif actual["kind"] == "local":
                            child_arguments[binding["port"]] = variables[
                                actual["local"]
                            ]
                        else:
                            child_arguments[binding["port"]] = actual["literal"]
                    child_outcome, child_result = execute_operation(
                        child,
                        child_arguments,
                        child_state_references,
                        (*call_path, instruction["site"]),
                    )
                    call_trace.append(
                        {
                            "site": "/".join((*call_path, instruction["site"])),
                            "operation": child["id"],
                            "outcome": child_outcome,
                        }
                    )
                    result_binding = instruction["result"]
                    if result_binding["kind"] == "local":
                        variables[result_binding["name"]] = child_result
                    for binding in instruction["arguments"]:
                        actual = binding["operand"]
                        if (
                            actual["kind"] == "port"
                            and actual["port"] in state_references
                        ):
                            variables[actual["port"]] = state[
                                state_references[actual["port"]]
                            ]
                    mapping = next(
                        row
                        for row in instruction["outcomes"]
                        if row["outcome"] == child_outcome
                    )
                    if mapping["action"]["kind"] == "propagate":
                        outcome = mapping["action"]["outcome"]
                        break
                    continue
                if operator == "gameplay-precondition":
                    if not _integer_compare(
                        semantics["comparison"],
                        variables[instruction["left"]],
                        variables[instruction["right"]],
                    ):
                        outcome = instruction["outcome"]
                        break
                elif operator == "named-integer-draw":
                    value, index, candidate, accepted = rng.draw(
                        instruction["stream"],
                        instruction["minimum"],
                        instruction["maximum"],
                    )
                    variables[instruction["target"]] = value
                    draws.append(
                        {
                            "stream": instruction["stream"],
                            "index": index,
                            "candidate_hex": f"{candidate:016x}",
                            "accepted": accepted,
                            "minimum": instruction["minimum"],
                            "maximum": instruction["maximum"],
                            "value": value,
                        }
                    )
                elif operator == "integer-literal":
                    variables[instruction["target"]] = instruction["literal"]
                elif operator == "copy-value":
                    variables[instruction["target"]] = variables[instruction["value"]]
                elif operator in {
                    "integer-add",
                    "integer-subtract",
                    "integer-multiply",
                    "integer-maximum",
                }:
                    left = variables[instruction["left"]]
                    right = variables[instruction["right"]]
                    result = (
                        left + right
                        if operator == "integer-add"
                        else left - right
                        if operator == "integer-subtract"
                        else left * right
                        if operator == "integer-multiply"
                        else max(left, right)
                    )
                    variables[instruction["target"]] = _admit_numeric(result, numeric)
                elif operator == "integer-compare":
                    variables[instruction["target"]] = _integer_compare(
                        semantics["comparison"],
                        variables[instruction["left"]],
                        variables[instruction["right"]],
                    )
                elif operator == "select-value":
                    variables[instruction["target"]] = variables[
                        instruction[
                            "when_true"
                            if variables[instruction["condition"]]
                            else "when_false"
                        ]
                    ]
                elif operator in {"state-integer-subtract", "state-write"}:
                    formal = instruction["symbol"]
                    actual = state_references[formal]
                    value = (
                        state[actual] - variables[instruction["value"]]
                        if operator == "state-integer-subtract"
                        else variables[instruction["value"]]
                    )
                    state[actual] = _admit_numeric(value, numeric)
                    variables[formal] = state[actual]
                else:
                    raise ValueError(
                        f"admitted evaluator lacks runtime operator {operator}"
                    )
            outcome_definition = next(
                row
                for row in selected_operation["outcomes"]
                if row["id"] == outcome
            )
            if outcome_definition["state_policy"] == "rollback":
                state.clear()
                state.update(operation_before)
            result_source = selected_operation["result"]["source"]
            result = (
                variables[result_source["name"]]
                if result_source["kind"] == "local"
                and outcome_definition["kind"] == "success"
                else None
            )
            return cast(str, outcome), result

        root_arguments: dict[str, Any] = {}
        root_state_references: dict[str, str] = {}
        for binding in entrypoint["arguments"]:
            resolved_operand = binding["operand"]
            if resolved_operand["kind"] == "symbol":
                declaration = declarations[
                    canonical_bytes(cast(JsonValue, resolved_operand["symbol"]))
                ]
                root_arguments[binding["port"]["name"]] = actual_values[
                    declaration["symbol"]
                ]
                if declaration["role"] == "state":
                    root_state_references[binding["port"]["name"]] = declaration[
                        "symbol"
                    ]
            else:
                root_arguments[binding["port"]["name"]] = resolved_operand["value"]
        try:
            outcome, root_result = execute_operation(
                operation,
                root_arguments,
                root_state_references,
                (cast(str, entrypoint["id"]),),
            )
        except RuntimeError:
            return _runtime_refusal_outcome(
                checked,
                scenario_id=scenario["id"],
                scenario_index=scenario_index,
                code=_diagnostic_for_signal(checked, "step-limit", "runtime"),
                message="Runtime program exhausted its exact step bound",
                events=events,
                operation=operation["id"],
                state_before=before,
            )
        except OverflowError:
            return _runtime_refusal_outcome(
                checked,
                scenario_id=scenario["id"],
                scenario_index=scenario_index,
                code=_diagnostic_for_signal(
                    checked, "numeric-overflow", "runtime"
                ),
                message="Exact-int64 operation overflowed its numeric domain",
                events=events,
                operation=operation["id"],
                state_before=before,
            )
        for name, value in state.items():
            actual_values[name] = value
        outcome_definition = outcomes[outcome]
        if outcome_definition["kind"] == "success":
            result_symbol = entrypoint["result"]["symbol"]["name"]
            actual_values[result_symbol] = root_result
        typed_outcome = {
            "id": outcome,
            "kind": outcome_definition["kind"],
        }
        event = cast(
            dict[str, JsonValue],
            {
                "index": len(events),
                "operation": operation["id"],
                "outcome": typed_outcome,
                "facts": _value_rows(actual_values),
                "state_before": _int_rows(before),
                "state_after": _int_rows(state),
                "rng_draws": draws,
            },
        )
        events.append(event)
        snapshots.append(
            cast(
                dict[str, JsonValue],
                {
                    "index": len(snapshots),
                    "name": f"{scenario['id']}:terminal",
                    "values": _int_rows(state),
                },
            )
        )
        scenario_outputs[scenario["id"]] = (event, state, outcome)

    samples: list[dict[str, JsonValue]] = []
    metric_definition_identities: list[str] = []
    for metric in checked.value["metrics"]:
        metric_identity = _metric_definition_identity(metric)
        metric_definition_identities.append(metric_identity)
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
                code=_diagnostic_for_signal(
                    checked, "observation-unavailable", "evaluation"
                ),
                identity=checked.content_identity,
                pointer=f"/metrics/{metric['id']}/observation",
                message="Metric observation did not resolve to exactly one value",
            )
        scenario_id, value = matched[0]
        target = metric["target"]
        samples.append(
            {
                "metric": metric["id"],
                "metric_definition_identity": metric_identity,
                "scenario": scenario_id,
                "status": "value",
                "value": value,
                "unit": metric["unit"],
                "logical_time": 0,
                "window": metric["window"]["name"],
                "dimensions": metric["dimensions"],
                "replication_identity": scenario_id,
                "source_kind": "simulated",
                "provenance": {
                    "scenario": scenario_id,
                    "observation_source": observation["source"],
                    "observation_name": observation["name"],
                    "observation_member": observation["member"],
                },
                "within_target": target["minimum"] <= value <= target["maximum"],
                "source": observation["source"],
                "member": observation["member"],
            }
        )

    trace = _artifact(
        checked,
        "event-trace",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "scenario": ",".join(row["id"] for row in checked.value["scenarios"]),
                "events": events,
            },
        ),
    )
    snapshot_series = _artifact(
        checked,
        "snapshot-series",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "scenario": ",".join(row["id"] for row in checked.value["scenarios"]),
                "snapshots": snapshots,
            },
        ),
    )
    metric_dataset = _artifact(
        checked,
        "metric-dataset",
        cast(
            dict[str, JsonValue],
            {
                "experiment_identity": checked.content_identity,
                "resolved_runtime_profile_identity": resolved_runtime.content_identity,
                "metric_definition_identities": metric_definition_identities,
                "source_provenance": {
                    "kind": "simulated",
                    "resolved_model_identity": checked.resolved_model[
                        "content_identity"
                    ],
                    "resolved_runtime_profile_identity": (
                        resolved_runtime.content_identity
                    ),
                    "evaluator_manifest_identity": evaluator.content_identity,
                },
                "data_version": "1",
                "partition": "evaluation",
                "ordering": ("metric-definition-identity,replication-identity"),
                "ingestion_transformation_identity": None,
                "samples": samples,
            },
        ),
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
