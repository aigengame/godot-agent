"""Orchestrate dual-consumer Operation execution conformance."""

from typing import Any, cast

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_operation_execution_independent_support import reference_execute_event
from schema2_operation_execution_production_support import (
    evaluate_operation_execution_vector_with_evidence,
)


OperationCoordinate = tuple[str, str, str]


def _operation_index(ldb: Any) -> dict[OperationCoordinate, dict[str, Any]]:
    language = cast(dict[str, Any], ldb["language"])
    return {
        (
            cast(str, package["id"]),
            cast(str, package["version"]),
            cast(str, definition["id"]),
        ): definition
        for package in cast(list[dict[str, Any]], language["packages"])
        for closure in cast(list[dict[str, Any]], package["semantic_closure"])
        if closure["authority_path"] == "language.operations"
        for definition in cast(list[dict[str, Any]], closure["definitions"])
    }


def operation_execution_vectors(
    ldb: Any,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Discover every manifest-bound Operation execution vector."""
    return [
        (vector_set["package_id"], vector_set["package_version"], vector)
        for vector_set in ldb.package_conformance_vector_sets
        for vector in vector_set["vector_definitions"]
        if vector.get("kind") == "operation-execution"
    ]


def independent_operation_execution_projection(
    kernel: dict[str, Any],
    ldb: Any,
    operations: dict[OperationCoordinate, dict[str, Any]],
    package_id: str,
    package_version: str,
    vector: dict[str, Any],
    *,
    include_execution_evidence: bool = False,
) -> dict[str, Any]:
    """Project the independent adapter result to the canonical vector shape."""
    coordinate = (package_id, package_version, cast(str, vector["operation"]))
    operation = operations[coordinate]
    event = reference_execute_event(
        kernel,
        operation,
        operations,
        {"id": vector["id"], "values": vector["input"]["values"]},
        seed=vector["input"]["seed"],
        state_names={
            row["id"] for row in operation["inputs"] if row["access"] == "read-write"
        },
        language_bundle=ldb,
        root_operation_coordinate=coordinate,
        include_execution_evidence=include_execution_evidence,
    )
    state_after = {row["name"]: row["value"] for row in event["state_after"]}
    state_names = [
        row["id"] for row in operation["inputs"] if row["access"] == "read-write"
    ]
    if "refusal" in event:
        observation = {
            "completion": {"kind": "refusal", "reason": event["refusal"]["reason"]},
            "result": {"kind": "not-produced"},
            "rng_draws": [],
            "state_after": [
                {"name": name, "value": state_after[name]} for name in state_names
            ],
        }
        if include_execution_evidence:
            return {
                "execution_evidence": event["execution_evidence"],
                "observation": observation,
            }
        return observation
    observation = {
        "completion": {"kind": "outcome", "id": event["outcome"]["id"]},
        "result": (
            {"kind": "value", "value": event["result"]}
            if event["outcome"]["kind"] == "success"
            else {"kind": "not-produced"}
        ),
        "rng_draws": [
            {
                member: draw[member]
                for member in ("candidate_hex", "index", "stream", "value")
            }
            for draw in event["rng_draws"]
        ],
        "state_after": [
            {"name": name, "value": state_after[name]} for name in state_names
        ],
    }
    if include_execution_evidence:
        return {
            "execution_evidence": event["execution_evidence"],
            "observation": observation,
        }
    return observation


def _operation_execution_results(
    kernel: dict[str, Any],
    ldb: Any,
    vector: dict[str, Any],
    *,
    context: AdmittedAuthorityContext,
    package_id: str,
    package_version: str,
) -> dict[str, dict[str, Any]]:
    production = evaluate_operation_execution_vector_with_evidence(
        context,
        vector,
        package_id=package_id,
        package_version=package_version,
    )
    return {
        "production": production,
        "independent": independent_operation_execution_projection(
            kernel,
            ldb,
            production["resolved_operations"],
            package_id,
            package_version,
            vector,
            include_execution_evidence=True,
        ),
    }


def operation_execution_observations(
    kernel: dict[str, Any],
    ldb: Any,
    vector: dict[str, Any],
    *,
    context: AdmittedAuthorityContext | None = None,
    package_id: str | None = None,
    package_version: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Observe one vector through both adapters in the canonical shape."""
    resolved_context = context or admit_authority_context(kernel, ldb)
    assert isinstance(resolved_context, AdmittedAuthorityContext)
    if package_id is None or package_version is None:
        owners = [
            (owner_id, owner_version)
            for owner_id, owner_version, declared in operation_execution_vectors(ldb)
            if declared["id"] == vector["id"]
            and declared["operation"] == vector["operation"]
        ]
        if len(owners) != 1:
            raise ValueError("operation execution vector owner is not unique")
        package_id, package_version = owners[0]
    results = _operation_execution_results(
        kernel,
        ldb,
        vector,
        context=resolved_context,
        package_id=package_id,
        package_version=package_version,
    )
    return {
        "expected": vector["expect"],
        "production": results["production"]["observation"],
        "independent": results["independent"]["observation"],
    }


def candidate_conformance_failures(
    kernel: dict[str, Any],
    ldb: Any,
    *,
    vector_overrides: dict[str, dict[str, Any]] | None = None,
    vector_coordinates: set[tuple[str, str, str]] | None = None,
    execution_evidence_expectations: dict[
        tuple[str, str, str], dict[str, Any]
    ]
    | None = None,
) -> list[dict[str, Any]]:
    """Return bounded candidate-graph and execution-vector disagreements."""
    production_admission = _consumer_a(kernel, ldb)
    independent_admission = _consumer_b(kernel, ldb)
    if production_admission != independent_admission:
        return [
            {
                "kind": "admission-divergence",
                "independent": independent_admission,
                "production": production_admission,
            }
        ]
    if production_admission["admitted"] is not True:
        return [
            {
                "kind": "candidate-refused",
                "observed": production_admission["diagnostics"],
            }
        ]
    context = admit_authority_context(kernel, ldb)
    assert isinstance(context, AdmittedAuthorityContext)
    failures: list[dict[str, Any]] = []
    overrides = vector_overrides or {}
    for package_id, package_version, declared in operation_execution_vectors(ldb):
        coordinate = (package_id, package_version, cast(str, declared["id"]))
        if vector_coordinates is not None and coordinate not in vector_coordinates:
            continue
        vector = overrides.get(declared["id"], declared)
        results = _operation_execution_results(
            kernel,
            ldb,
            vector,
            context=context,
            package_id=package_id,
            package_version=package_version,
        )
        observations = {
            "expected": vector["expect"],
            "production": results["production"]["observation"],
            "independent": results["independent"]["observation"],
        }
        if (
            observations["production"] != observations["independent"]
            or observations["production"] != observations["expected"]
        ):
            failures.append(
                {
                    "kind": "vector-divergence",
                    "package": package_id,
                    "vector": vector["id"],
                    **observations,
                }
            )
        evidence_expectation = (execution_evidence_expectations or {}).get(coordinate)
        if evidence_expectation is not None and (
            results["production"]["execution_evidence"]
            != results["independent"]["execution_evidence"]
            or results["production"]["execution_evidence"]
            != evidence_expectation
        ):
            failures.append(
                {
                    "kind": "execution-evidence-divergence",
                    "package": package_id,
                    "vector": vector["id"],
                    "expected": evidence_expectation,
                    "production": results["production"]["execution_evidence"],
                    "independent": results["independent"]["execution_evidence"],
                }
            )
    return failures
