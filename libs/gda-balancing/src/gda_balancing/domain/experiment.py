"""Exact-authority Experiment admission and resolved program requirements."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    packaged_authority_context,
)
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    content_identity,
    parse_canonical_object,
)
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    DiagnosticLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.domain.artifact_errors import PublishedArtifactIntegrityError
from gda_balancing.infrastructure.input_bytes import (
    read_bounded_input_with_sha256,
)
from gda_balancing.domain.model import admit_resolved_model
from gda_balancing.domain.publication import find_published_artifact
from gda_balancing.domain.runtime.scheduler import RuntimeScheduler
from gda_balancing.domain.structured_values import (
    StructuredValueAuthority,
    StructuredValueFault,
    admit_typed_value,
    package_structured_value_authority,
)

_EXPERIMENT_IDENTITY_DOMAIN = "experiment-specification-v2"

EXPERIMENT_CHECK_REFUSAL_REASONS = (
    "model.reason.source-too-large",
    "model.reason.source-parse-failure",
    "model.reason.source-contract-mismatch",
    "quantity.reason.invalid-domain",
    "structured.reason.resource-exhausted",
    "structured.reason.type-mismatch",
    "structured.reason.unknown-enum",
    "structured.reason.record-member-mismatch",
    "model.reason.resolved-authority-mismatch",
    "model.reason.resolution-binding-mismatch",
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
    authority_context: AdmittedAuthorityContext | None = None


def _refusal(
    *,
    stage: str,
    code: str,
    identity: str,
    pointer: str,
    message: str,
    variant: str | None = None,
    primary: DiagnosticLocation | None = None,
    related: tuple[DiagnosticLocation, ...] = (),
) -> Schema2RefusalReport:
    return Schema2RefusalReport(
        stage=cast(Any, stage),
        variant=variant,
        diagnostics=(
            Schema2Diagnostic(
                code=code,
                message=message,
                primary=(
                    primary
                    if primary is not None
                    else ArtifactLocation(
                        content_identity=identity,
                        pointer=pointer,
                    )
                ),
                related=related,
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


def _declared_value_fault(
    value: Any,
    declaration: dict[str, Any],
    *,
    structured_authority: StructuredValueAuthority,
    resource_limit: int,
) -> StructuredValueFault | None:
    type_identity = cast(dict[str, str], declaration["type_identity"])
    declared_type: JsonValue = {
        "id": type_identity["symbol"],
        "package": type_identity["package"],
        "version": type_identity["version"],
    }
    if declaration.get("value_kind") == "nominal-structured":
        try:
            admitted = admit_typed_value(
                value,
                authority=structured_authority,
                resource_limit=resource_limit,
            )
        except StructuredValueFault as fault:
            return fault
        if canonical_bytes(admitted["type"]) != canonical_bytes(declared_type):
            return StructuredValueFault(
                "language.structured_value_type_mismatch", "/type"
            )
        return None
    domain = declaration["domain"]
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not domain["minimum"] <= value <= domain["maximum"]
    ):
        return StructuredValueFault("language.invalid_domain", "")
    return None


def _pointer(parts: Any) -> str:
    encoded = []
    for part in parts:
        encoded.append(str(part).replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(encoded) if encoded else ""


def _schema_error_pointer(error: jsonschema.ValidationError) -> str:
    if (
        error.validator == "oneOf"
        and isinstance(error.instance, dict)
        and isinstance(error.schema, dict)
        and isinstance(error.schema.get("oneOf"), list)
    ):
        discriminator = error.instance.get("kind")
        matching_branches = [
            index
            for index, branch in enumerate(error.schema["oneOf"])
            if isinstance(branch, dict)
            and isinstance(branch.get("properties"), dict)
            and branch["properties"].get("kind", {}).get("const") == discriminator
        ]
        if len(matching_branches) == 1:
            selected_branch = matching_branches[0]
            branch_errors = [
                nested
                for nested in error.context
                if list(nested.relative_schema_path)[:1] == [selected_branch]
            ]
            if branch_errors:
                most_specific = min(
                    branch_errors,
                    key=lambda nested: (
                        nested.validator not in {"required", "unevaluatedProperties"},
                        tuple(str(part) for part in nested.absolute_path),
                    ),
                )
                return _schema_error_pointer(most_specific)
    parts = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [
            member
            for member in cast(list[str], error.validator_value)
            if member not in error.instance
        ]
        if missing:
            parts.append(sorted(missing)[0])
    elif error.validator in {"additionalProperties", "unevaluatedProperties"} and (
        isinstance(error.instance, dict)
        and isinstance(error.schema, dict)
        and isinstance(error.schema.get("properties"), dict)
    ):
        extras = set(error.instance) - set(error.schema["properties"])
        if extras:
            parts.append(sorted(extras)[0])
    return _pointer(parts)


def _unique_rows(rows: list[dict[str, Any]], member: str) -> bool:
    values = [row[member] for row in rows]
    return len(values) == len(set(values))


def _unique_canonical_rows(rows: list[dict[str, Any]], member: str) -> bool:
    values = [canonical_bytes(cast(JsonValue, row[member])) for row in rows]
    return len(values) == len(set(values))


def _canonical_contract_union(
    rows: list[dict[str, Any]],
    *,
    contract_name: str,
) -> dict[bytes, dict[str, Any]]:
    union: dict[bytes, dict[str, Any]] = {}
    for row in rows:
        identity = canonical_bytes(cast(JsonValue, row["target"]))
        previous = union.get(identity)
        if previous is not None and previous != row:
            raise ValueError(f"conflicting {contract_name} rows")
        union[identity] = row
    return union


def _scenario_root_events(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], scenario["event_plan"])


def _ordered_root_events_under(
    scheduler: Mapping[str, Any], scenario: dict[str, Any]
) -> list[dict[str, Any]]:
    root_phases = cast(dict[str, str], scheduler["root_phases"])
    admitted = [
        {
            **event,
            "phase": root_phases[cast(str, event["kind"])],
            "enqueue_sequence": sequence,
        }
        for sequence, event in enumerate(_scenario_root_events(scenario))
    ]
    return RuntimeScheduler(scheduler).ordered_events(admitted)


def _external_input_plan_is_admitted(
    scenario: dict[str, Any], scheduler: Mapping[str, Any]
) -> bool:
    admission = cast(dict[str, Any], scheduler["external_input_admission"])
    ordering = cast(list[str], admission["ordering"])
    source_members = ordering[:-1]
    sequence_member = ordering[-1]
    sequence_origin = cast(int, admission["sequence_origin"])
    external_events = [
        event
        for event in _ordered_root_events_under(scheduler, scenario)
        if event["kind"] == "external-input"
    ]
    source_coordinates = sorted(
        {tuple(event[member] for member in source_members) for event in external_events}
    )
    for source_coordinate in source_coordinates:
        sequences = [
            cast(int, event[sequence_member])
            for event in external_events
            if tuple(event[member] for member in source_members) == source_coordinate
        ]
        if sequences != list(range(sequence_origin, sequence_origin + len(sequences))):
            return False
    return True


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
        if instruction["node"] not in {"invoke", "schedule"}:
            continue
        operation_ref = cast(dict[str, Any], instruction["operation"])
        invoked = operations.get(cast(str, operation_ref["id"]))
        if invoked is None:
            raise ValueError("admitted Operation composition target is absent")
        expanded.extend(_expanded_operation_body(invoked, operations, nested_visiting))
    return expanded


def derive_scenario_program_requirements(
    rir: dict[str, Any],
    entrypoint_id: str,
    runtime_profile: str,
    rng_algorithm: str,
) -> tuple[dict[str, list[str]], list[str]]:
    """Project one Scenario's evaluator contract from its admitted RIR."""
    selected = cast(dict[str, Any], rir["selected_semantics"])
    operations = {
        row["definition"]["id"]: row["definition"]
        for row in cast(list[dict[str, Any]], selected["operations"])
    }
    entrypoints = {
        row["id"]: row for row in cast(list[dict[str, Any]], rir["entrypoints"])
    }
    entrypoint = entrypoints.get(entrypoint_id)
    if entrypoint is None:
        raise ValueError("Scenario entrypoint is absent from the selected RIR")
    operation = operations.get(entrypoint["operation"]["id"])
    if operation is None:
        raise ValueError("Scenario Operation is absent from the selected RIR")
    if operation["runtime_profile"] != runtime_profile:
        raise ValueError("Scenario Operation requires another Runtime profile")
    expanded_body = _expanded_operation_body(operation, operations)
    instruction_nodes = {instruction["node"] for instruction in expanded_body}
    requirements = {
        "operation_kinds": sorted(
            {
                operation["operation_kind"],
                *(
                    operations[instruction["operation"]["id"]]["operation_kind"]
                    for instruction in expanded_body
                    if instruction["node"] in {"invoke", "schedule"}
                ),
            }
        ),
        "instruction_nodes": sorted(instruction_nodes),
        "effects": sorted(set(operation["effects"])),
        "numeric_policies": [operation["numeric_policy"]],
        "rng_algorithms": [rng_algorithm] if "draw" in instruction_nodes else [],
        "runtime_profiles": [runtime_profile],
    }
    named_streams = sorted(
        {
            instruction["stream"]
            for instruction in expanded_body
            if instruction["node"] == "draw"
        }
    )
    return requirements, named_streams


def check_experiment(
    path: str,
    *,
    authority_context: AdmittedAuthorityContext | None = None,
) -> CheckedExperiment | Schema2RefusalReport:
    """Admit one exact Experiment Specification and its model bindings."""
    context = authority_context or packaged_authority_context()
    kernel = context.kernel
    language_bundle = context.language_bundle
    max_source_bytes = cast(int, language_bundle["resources"]["max_source_bytes"])
    observation = read_bounded_input_with_sha256(path, max_source_bytes)
    if observation.data is None:
        return _refusal(
            stage="ingress",
            code="language.source_too_large",
            identity=f"sha256:{observation.sha256}",
            pointer="",
            message="Experiment Specification exceeds the admitted ingress bound",
        )
    data = observation.data
    observed_identity = f"sha256:{observation.sha256}"
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
            pointer=_schema_error_pointer(schema_error),
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
        event_plan = _scenario_root_events(scenario)
        scheduler = RuntimeScheduler.from_kernel(kernel).contract
        if (
            not _unique_canonical_rows(scenario["assignments"], "target")
            or len(scenario["named_streams"]) != len(set(scenario["named_streams"]))
            or not _unique_rows(event_plan, "root_event_ref")
            or any(
                not _unique_canonical_rows(event["facts"], "target")
                for event in event_plan
                if event["kind"] == "external-input"
            )
            or any(
                not _unique_rows(event.get("event_references", []), "name")
                for event in event_plan
                if event["kind"] == "transition-invocation"
            )
            or not _external_input_plan_is_admitted(scenario, scheduler)
        ):
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=(
                    f"/scenarios/{scenario_index}/assignments"
                    if not _unique_canonical_rows(scenario["assignments"], "target")
                    else f"/scenarios/{scenario_index}"
                ),
                message=(
                    "The deterministic-event-v1 slice requires unique assignments, "
                    "unique streams, input facts and root Event references"
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
        try:
            artifact = find_published_artifact(
                model[identity_members[name]],
                kind,
                language_bundle,
            )
        except PublishedArtifactIntegrityError as err:
            return _refusal(
                stage="resolution",
                code="language.resolved_authority_mismatch",
                identity=experiment_identity,
                pointer=f"/model/{identity_members[name]}",
                message=f"Exact {kind} publication failed integrity verification: {err}",
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
        },
        authority_context=context,
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
    structured_authority = package_structured_value_authority(
        cast(
            list[dict[str, Any]],
            context.language_bundle["language"]["packages"],
        )
    )
    structured_resource_limit = cast(
        int, language_bundle["resources"]["max_rule_match_steps"]
    )
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
        selected_entrypoints: list[dict[str, Any]] = []
        required_streams: set[str] = set()
        for event_index, event in enumerate(_scenario_root_events(scenario)):
            if event["kind"] != "transition-invocation":
                continue
            entrypoint = entrypoints.get(event["entrypoint"])
            pointer = f"/scenarios/{scenario_index}/event_plan/{event_index}/entrypoint"
            if entrypoint is None:
                return _refusal(
                    stage="resolution",
                    code="language.resolution_binding_mismatch",
                    identity=experiment_identity,
                    pointer=pointer,
                    message="Root Event entrypoint is absent from the selected RIR",
                )
            operation = operations.get(entrypoint["operation"]["id"])
            if operation is None or operation["runtime_profile"] != required_profile:
                return _refusal(
                    stage="resolution",
                    code="language.resolution_binding_mismatch",
                    identity=experiment_identity,
                    pointer=pointer,
                    message=(
                        "Root Event entrypoint Operation is absent or requires "
                        "another Runtime profile"
                    ),
                )
            try:
                requirements, named_streams = derive_scenario_program_requirements(
                    rir,
                    event["entrypoint"],
                    required_profile,
                    value["seed"]["algorithm"],
                )
            except ValueError:
                return _refusal(
                    stage="resolution",
                    code="language.resolution_binding_mismatch",
                    identity=experiment_identity,
                    pointer=pointer,
                    message="Root Event Operation composition is not closed",
                )
            selected_entrypoints.append(entrypoint)
            required_operation_kinds.update(requirements["operation_kinds"])
            required_instruction_nodes.update(requirements["instruction_nodes"])
            required_effects.update(requirements["effects"])
            required_numeric_policies.update(requirements["numeric_policies"])
            required_rng_algorithms.update(requirements["rng_algorithms"])
            required_streams.update(named_streams)
            payload_contract = cast(
                dict[str, Any], entrypoint["event_local_payload_contract"]
            )
            payload_targets = cast(list[dict[str, Any]], payload_contract["targets"])
            payload = cast(list[dict[str, Any]], event["payload"])
            payload_pointer = (
                f"/scenarios/{scenario_index}/event_plan/{event_index}/payload"
            )
            if not _unique_canonical_rows(payload, "target"):
                return _refusal(
                    stage="static",
                    code="language.source_contract_mismatch",
                    identity=experiment_identity,
                    pointer=payload_pointer,
                    message="Event-local payload repeats a target",
                )
            allowed_payload = {
                canonical_bytes(cast(JsonValue, row["target"])): row
                for row in payload_targets
            }
            provided_payload = {
                canonical_bytes(cast(JsonValue, row["target"])): row for row in payload
            }
            required_payload = {
                key
                for key, row in allowed_payload.items()
                if row["cardinality"] == "required"
            }
            if (
                not required_payload <= provided_payload.keys()
                or not provided_payload.keys() <= allowed_payload.keys()
            ):
                return _refusal(
                    stage="static",
                    code="language.source_contract_mismatch",
                    identity=experiment_identity,
                    pointer=payload_pointer,
                    message=(
                        "Transition payload does not exactly close its Event-local "
                        "payload contract"
                    ),
                )
            for payload_index, row in enumerate(payload):
                declaration = declarations[
                    canonical_bytes(cast(JsonValue, row["target"]))
                ]
                fault = _declared_value_fault(
                    row["value"],
                    declaration,
                    structured_authority=structured_authority,
                    resource_limit=structured_resource_limit,
                )
                if fault is not None:
                    return _refusal(
                        stage="static",
                        code=fault.code,
                        identity=experiment_identity,
                        pointer=(
                            f"{payload_pointer}/{payload_index}/value{fault.pointer}"
                        ),
                        message="Event-local payload does not match its declared value",
                    )
            reference_contracts = cast(
                list[dict[str, Any]], payload_contract["event_references"]
            )
            references = cast(list[dict[str, str]], event.get("event_references", []))
            reference_pointer = (
                f"/scenarios/{scenario_index}/event_plan/{event_index}/event_references"
            )
            allowed_reference_names = {
                cast(str, row["name"]) for row in reference_contracts
            }
            provided_reference_names = {row["name"] for row in references}
            required_reference_names = {
                cast(str, row["name"])
                for row in reference_contracts
                if row["cardinality"] == "required"
            }
            if (
                len(provided_reference_names) != len(references)
                or not required_reference_names <= provided_reference_names
                or not provided_reference_names <= allowed_reference_names
            ):
                return _refusal(
                    stage="static",
                    code="language.source_contract_mismatch",
                    identity=experiment_identity,
                    pointer=reference_pointer,
                    message=(
                        "Transition Event references do not exactly close the "
                        "entrypoint contract"
                    ),
                )
            root_references = {
                cast(str, root["root_event_ref"])
                for root in _scenario_root_events(scenario)
            }
            for reference_index, reference in enumerate(references):
                if reference["root_event_ref"] not in root_references:
                    return _refusal(
                        stage="static",
                        code="language.resolution_binding_mismatch",
                        identity=experiment_identity,
                        pointer=(
                            f"{reference_pointer}/{reference_index}/root_event_ref"
                        ),
                        message=(
                            "Event reference does not resolve to an admitted root "
                            "Event in the same Scenario"
                        ),
                    )
        contract_targets = [
            target
            for entrypoint in selected_entrypoints
            for target in cast(
                list[dict[str, Any]],
                entrypoint["scenario_input_contract"]["targets"],
            )
        ]
        initializer_rows = [
            initializer
            for entrypoint in selected_entrypoints
            for initializer in cast(
                list[dict[str, Any]],
                entrypoint["scenario_input_contract"]["initializers"],
            )
        ]
        try:
            scenario_contract = _canonical_contract_union(
                contract_targets,
                contract_name="Scenario Input Contract",
            )
            _canonical_contract_union(
                initializer_rows,
                contract_name="Scenario initializer contract",
            )
        except ValueError as err:
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/assignments",
                message=str(err),
            )
        allowed = {
            identity: row
            for identity, row in scenario_contract.items()
            if row["owner"] == "experiment"
        }
        provided = {
            canonical_bytes(cast(JsonValue, row["target"])): row
            for row in scenario["assignments"]
        }
        required = {
            key for key, row in allowed.items() if row["cardinality"] == "required"
        }
        if not required <= provided.keys() or not provided.keys() <= allowed.keys():
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/assignments",
                message="Scenario assignments do not close the Scenario Input Contract",
            )
        if required_streams != set(scenario["named_streams"]):
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/named_streams",
                message="Scenario Named streams do not exactly close operation draws",
            )
        external_fact_targets = [
            target
            for entrypoint in selected_entrypoints
            for target in cast(
                list[dict[str, Any]],
                entrypoint["external_fact_contract"]["targets"],
            )
        ]
        try:
            allowed_external_facts = _canonical_contract_union(
                external_fact_targets,
                contract_name="external-fact contract",
            )
        except ValueError as err:
            return _refusal(
                stage="static",
                code="language.source_contract_mismatch",
                identity=experiment_identity,
                pointer=f"/scenarios/{scenario_index}/event_plan",
                message=str(err),
            )
        for assignment_index, row in enumerate(scenario["assignments"]):
            declaration = declarations[canonical_bytes(cast(JsonValue, row["target"]))]
            fault = _declared_value_fault(
                row["value"],
                declaration,
                structured_authority=structured_authority,
                resource_limit=structured_resource_limit,
            )
            if fault is not None:
                return _refusal(
                    stage="static",
                    code=fault.code,
                    identity=experiment_identity,
                    pointer=(
                        f"/scenarios/{scenario_index}/assignments/"
                        f"{assignment_index}/value{fault.pointer}"
                    ),
                    message="Scenario assignment does not match its declared value",
                )
        for event_index, event in enumerate(_scenario_root_events(scenario)):
            if event["kind"] != "external-input":
                continue
            for fact_index, fact in enumerate(event["facts"]):
                identity = canonical_bytes(cast(JsonValue, fact["target"]))
                target_contract = allowed_external_facts.get(identity)
                pointer = (
                    f"/scenarios/{scenario_index}/event_plan/{event_index}"
                    f"/facts/{fact_index}"
                )
                if target_contract is None:
                    return _refusal(
                        stage="static",
                        code="language.source_contract_mismatch",
                        identity=experiment_identity,
                        pointer=f"{pointer}/target",
                        message=(
                            "External-input facts must target the selected "
                            "entrypoints' exact external-fact contract"
                        ),
                    )
                declaration = declarations[identity]
                fault = _declared_value_fault(
                    fact["value"],
                    declaration,
                    structured_authority=structured_authority,
                    resource_limit=structured_resource_limit,
                )
                if fault is not None:
                    return _refusal(
                        stage="static",
                        code=fault.code,
                        identity=experiment_identity,
                        pointer=f"{pointer}/value{fault.pointer}",
                        message="External-input fact does not match its declared value",
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
        authority_context=context,
    )


def experiment_input_identity(value: dict[str, Any]) -> str:
    """Bind publication retries to the exact Experiment Specification."""
    return content_identity(_EXPERIMENT_IDENTITY_DOMAIN, cast(JsonValue, value))


def canonical_experiment_bytes(value: dict[str, Any]) -> bytes:
    """Expose canonical bytes for descriptor-owned command-input identity."""
    return canonical_bytes(cast(JsonValue, value))
