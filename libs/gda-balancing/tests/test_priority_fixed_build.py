"""Fixed A/B exchange for the finite #878 priority witness."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest

from gda_balancing.domain.artifacts import identified_artifact, verify_artifact
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.graph import LanguageBundleIndex
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    admit_resolved_model,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.model._compilation import (
    _capability_manifest as production_capability_manifest,
)
from gda_balancing.domain.model._compilation import (
    _model_explanation as production_model_explanation,
)
from gda_balancing.domain.model._lowering import _LOWERER_IMPLEMENTATION_IDENTITY
from gda_balancing.domain.model._resolution import (
    _RESOLVER_IMPLEMENTATION_IDENTITY,
    _model_lowering,
    _resolution_profile,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    evaluate_experiment,
)
from gda_balancing.domain.runtime.projections import evaluator_build_identity
from priority_extension_proof_support import (
    _rename_experiment_semantics,
    _rename_package_semantics,
    _rename_source_semantics,
    admits_selected_dependency_binding,
    build_priority_case,
    selected_dependency_binding,
)
from priority_model_independent_support import (
    reference_admits_model_artifacts,
    reference_model_artifacts,
    reference_model_producer,
)
from priority_runtime_independent_support import (
    IndependentRuntimeUnsupported,
    _PRIORITY_OPERATORS,
    _build_identity as reference_runtime_build_identity,
    _supported_shape,
    reference_admits_runtime_artifacts,
    reference_runtime_artifacts,
)
from test_schema2_model_lowerer_conformance import (
    ModelSourceContext,
    _reference_check_source,
)


_MODEL_ROLES = {
    "build-receipt",
    "capability-manifest",
    "debug-map",
    "model-explanation",
    "package-lock",
    "resolution-receipt",
    "resolved-model",
    "rir-semantic-payload",
}
_RUNTIME_ROLES = {
    "evaluation-run",
    "evaluator-capability-manifest",
    "event-trace",
    "metric-dataset",
    "resolved-runtime-profile",
    "snapshot-series",
}


@dataclass(frozen=True)
class _Case:
    binding_a: dict[str, Any]
    binding_b: dict[str, Any]
    model_a: dict[str, dict[str, Any]]
    model_b: dict[str, dict[str, Any]]
    runs: dict[str, dict[str, Any]]


def _language(payload: dict[str, Any]) -> LanguageBundleIndex:
    return LanguageBundleIndex(
        payload["projection"],
        root=payload["root"],
        package_releases=payload["package_releases"],
        package_conformance_vector_sets=payload["package_conformance_vector_sets"],
        root_byte_size=payload["root_byte_size"],
        package_byte_sizes=payload["package_byte_sizes"],
        vector_set_byte_sizes=payload["vector_set_byte_sizes"],
    )


def _fixed_build_identities() -> dict[str, Any]:
    return {
        "a": {
            "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
            "resolver": _RESOLVER_IMPLEMENTATION_IDENTITY,
            "runtime": evaluator_build_identity(),
        },
        "b": {
            "model": reference_model_producer(),
            "runtime": reference_runtime_build_identity(),
        },
    }


def _a_admits_model(
    context: AdmittedAuthorityContext,
    artifacts: dict[str, dict[str, Any]],
    *,
    source_identity: str,
    producer: dict[str, str],
    expected_semantic_artifacts: dict[str, dict[str, Any]],
) -> bool:
    try:
        if set(artifacts) != _MODEL_ROLES or not all(
            verify_artifact(value, context.language_bundle)
            for value in artifacts.values()
        ):
            return False
        lock = artifacts["package-lock"]
        rir = artifacts["rir-semantic-payload"]
        resolved = artifacts["resolved-model"]
        debug = artifacts["debug-map"]
        if any(
            artifacts[role] != expected_semantic_artifacts[role]
            for role in (
                "package-lock",
                "rir-semantic-payload",
                "resolved-model",
                "debug-map",
            )
        ):
            return False
        if not admit_resolved_model(
            {
                role: artifacts[role]
                for role in ("package-lock", "rir-semantic-payload", "resolved-model")
            },
            authority_context=context,
        ).admitted:
            return False
        if artifacts["capability-manifest"] != production_capability_manifest(
            lock, rir, resolved, context.language_bundle
        ) or artifacts["model-explanation"] != production_model_explanation(
            context, lock, rir, debug, rir["declarations"]
        ):
            return False
        source = {
            "source_identity": source_identity,
            "kernel_identity": context.kernel["content_identity"],
            "language_bundle_identity": context.language_bundle["content_identity"],
        }
        lowering = _model_lowering(context.language_bundle)
        profile = _resolution_profile(
            context.language_bundle, lowering["resolution_profile"]
        )
        resolution_receipt = identified_artifact(
            context.language_bundle,
            "resolution-receipt",
            {
                **source,
                "resolver": producer["resolver"],
                "resolution_profile": profile["id"],
                "package_lock_identity": lock["content_identity"],
                "diagnostics": [],
            },
        )
        if artifacts["resolution-receipt"] != resolution_receipt:
            return False
        return artifacts["build-receipt"] == identified_artifact(
            context.language_bundle,
            "build-receipt",
            {
                **source,
                "compiler": producer["compiler"],
                **{
                    field: artifacts[role]["content_identity"]
                    for field, role in (
                        ("package_lock_identity", "package-lock"),
                        ("rir_identity", "rir-semantic-payload"),
                        ("resolved_model_identity", "resolved-model"),
                        ("capability_manifest_identity", "capability-manifest"),
                        ("debug_map_identity", "debug-map"),
                        ("model_explanation_identity", "model-explanation"),
                        ("resolution_receipt_identity", "resolution-receipt"),
                    )
                },
            },
        )
    except (KeyError, TypeError, ValueError):
        return False


def _b_admits_model(
    checked: ModelSourceContext,
    artifacts: dict[str, dict[str, Any]],
    *,
    expected_semantic_artifacts: dict[str, dict[str, Any]],
) -> bool:
    producer = {
        "compiler": artifacts["build-receipt"]["compiler"],
        "resolver": artifacts["resolution-receipt"]["resolver"],
    }
    return reference_admits_model_artifacts(
        artifacts,
        checked,
        producer=producer,
        expected_semantic_artifacts=expected_semantic_artifacts,
    )


def _boundary(trace: dict[str, Any], mapping: dict[str, str]) -> list[dict[str, Any]]:
    reverse = {renamed: original for original, renamed in mapping.items()}

    def operation_id(value: Any) -> str:
        identity = value["id"] if isinstance(value, dict) else value
        assert isinstance(identity, str)
        return reverse.get(identity, identity)

    result = []
    for event in trace["events"]:
        if event["operation"] is None:
            continue
        state = {row["name"]: row["value"] for row in event["state_after"]}

        def value(name: str) -> Any:
            member = state[name]
            return (
                member["value"]
                if isinstance(member, dict) and "type" in member
                else member
            )

        result.append(
            {
                "operation": operation_id(event["operation"]),
                "ordering_key": event["ordering_key"],
                "calls": [operation_id(row["operation"]) for row in event["calls"]],
                "schedules": [
                    {
                        "operation": operation_id(row["operation"]),
                        "ordering_key": row["ordering_key"],
                    }
                    for row in event["schedules"]
                ],
                "pending": [
                    value("root_id"),
                    value("next_id"),
                    value("ids"),
                    [row["target"] for row in value("counters")],
                    value("priority"),
                    value("passes"),
                    value("window_open"),
                    value("canceled_ids"),
                    value("final_power"),
                    value("status"),
                ],
            }
        )
    return result


def _build_case(renamed: bool) -> _Case:
    authored, proof = build_priority_case(renamed=renamed)
    language = _language(authored["language_bundle"])
    context = admit_authority_context(authored["kernel"], language)
    assert isinstance(context, AdmittedAuthorityContext), context

    checked_a = check_model_source_value(authored["source"], authority_context=context)
    assert isinstance(checked_a, CheckedModel), checked_a
    model_a = compile_checked_model(checked_a)
    assert set(model_a) == _MODEL_ROLES

    checked_b = _reference_check_source(
        authored["source"], authored["kernel"], language
    )
    assert isinstance(checked_b, ModelSourceContext), checked_b
    producer_b = reference_model_producer()
    model_b = reference_model_artifacts(checked_b, producer=producer_b)
    assert set(model_b) == _MODEL_ROLES
    assert _a_admits_model(
        context,
        model_b,
        source_identity=checked_b.source_identity,
        producer=producer_b,
        expected_semantic_artifacts=model_a,
    )
    assert _b_admits_model(checked_b, model_a, expected_semantic_artifacts=model_b)

    binding_a = selected_dependency_binding(model_a)
    binding_b = selected_dependency_binding(model_b)
    assert admits_selected_dependency_binding(model_a, binding_a)
    assert admits_selected_dependency_binding(model_b, binding_b)
    expected_coordinates = (
        {
            "game.action::RenamedCounter",
            "game.action::RenamedCounters",
            "game.action::RenamedOutcome",
            "game.action::RenamedPendingIds",
            "game.action::renamed-append-counter",
            "game.action::renamed-cancel-reverse-step",
            "game.action::renamed-count-match",
            "game.action::renamed-propose",
            "game.action::renamed-resolve",
            "game.turn::renamed-open",
            "game.turn::renamed-pass",
            "game.turn::renamed-respond",
        }
        if renamed
        else {
            "game.action::Counter",
            "game.action::Counters",
            "game.action::Outcome",
            "game.action::PendingIds",
            "game.action::append-counter",
            "game.action::cancel-reverse-step",
            "game.action::count-match",
            "game.action::propose",
            "game.action::resolve",
            "game.turn::open",
            "game.turn::pass",
            "game.turn::respond",
        }
    )
    for binding in (binding_a, binding_b):
        assert (
            set(binding["extension_type_coordinates"])
            | set(binding["extension_operation_coordinates"])
            == expected_coordinates
        )
    assert proof["renamed_identity_count"] == (12 if renamed else 0)

    runs = {}
    for variant, specification in authored["experiments"].items():
        specification_b = deepcopy(specification)
        specification_b["model"]["rir_semantic_identity"] = model_b[
            "rir-semantic-payload"
        ]["semantic_identity"]
        runtime_b = reference_runtime_artifacts(
            checked_b, model_b["rir-semantic-payload"], specification_b
        )
        assert set(runtime_b) == _RUNTIME_ROLES

        program_a = admit_rir(
            model_a["rir-semantic-payload"], authority_context=context
        )
        assert isinstance(program_a, AdmittedRir), program_a
        experiment_a = check_experiment_value(
            specification, program_a, authority_context=context
        )
        assert isinstance(experiment_a, CheckedExperiment), experiment_a
        evaluated_a = evaluate_experiment(experiment_a)
        assert isinstance(evaluated_a, EvaluationArtifacts), evaluated_a
        runtime_a = {name: member.value for name, member in evaluated_a.members.items()}
        assert set(runtime_a) == _RUNTIME_ROLES

        program_b = admit_rir(
            model_b["rir-semantic-payload"], authority_context=context
        )
        assert isinstance(program_b, AdmittedRir), program_b
        experiment_b = check_experiment_value(
            specification_b, program_b, authority_context=context
        )
        assert isinstance(experiment_b, CheckedExperiment), experiment_b
        assert validate_experiment_artifact_set(experiment_b, runtime_b)
        assert reference_admits_runtime_artifacts(
            checked_b,
            model_a["rir-semantic-payload"],
            specification,
            runtime_a,
            expected=runtime_b,
        )
        runs[variant] = {
            "a": runtime_a,
            "b": runtime_b,
            "mapping": authored["mapping"],
        }
    return _Case(binding_a, binding_b, model_a, model_b, runs)


@pytest.fixture(scope="module")
def fixed_matrix() -> dict[str, _Case]:
    frozen = _fixed_build_identities()
    matrix = {name: _build_case(name == "renamed") for name in ("original", "renamed")}
    assert _fixed_build_identities() == frozen
    return matrix


def test_fixed_builds_exchange_exact_eight_model_and_six_runtime_members(
    fixed_matrix,
):
    for case in fixed_matrix.values():
        assert set(case.model_a) == set(case.model_b) == _MODEL_ROLES
        for run in case.runs.values():
            assert set(run["a"]) == set(run["b"]) == _RUNTIME_ROLES
            assert _boundary(run["a"]["event-trace"], run["mapping"]) == _boundary(
                run["b"]["event-trace"], run["mapping"]
            )
    for variant, metric in (("baseline", 7), ("variant", 0)):
        original = fixed_matrix["original"].runs[variant]
        renamed = fixed_matrix["renamed"].runs[variant]
        assert _boundary(original["a"]["event-trace"], {}) == _boundary(
            renamed["a"]["event-trace"], renamed["mapping"]
        )
        assert original["a"]["metric-dataset"]["samples"][0]["value"] == metric
        assert renamed["b"]["metric-dataset"]["samples"][0]["value"] == metric


def test_model_admission_checks_all_eight_member_relationships(fixed_matrix):
    case = fixed_matrix["original"]
    authored, _ = build_priority_case(renamed=False)
    language = _language(authored["language_bundle"])
    context = admit_authority_context(authored["kernel"], language)
    assert isinstance(context, AdmittedAuthorityContext), context
    candidate = deepcopy(case.model_b)
    explanation_payload = {
        key: value
        for key, value in candidate["model-explanation"].items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    explanation_payload["operation_explanations"] = []
    candidate["model-explanation"] = identified_artifact(
        context.language_bundle, "model-explanation", explanation_payload
    )
    receipt_payload = {
        key: value
        for key, value in candidate["build-receipt"].items()
        if key
        not in {
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        }
    }
    receipt_payload["model_explanation_identity"] = candidate["model-explanation"][
        "content_identity"
    ]
    candidate["build-receipt"] = identified_artifact(
        context.language_bundle, "build-receipt", receipt_payload
    )
    producer = {
        "compiler": candidate["build-receipt"]["compiler"],
        "resolver": candidate["resolution-receipt"]["resolver"],
    }
    assert not _a_admits_model(
        context,
        candidate,
        source_identity=candidate["build-receipt"]["source_identity"],
        producer=producer,
        expected_semantic_artifacts=case.model_a,
    )


def test_independent_model_refuses_same_id_source_expansion():
    authored, _ = build_priority_case(renamed=False)
    source = deepcopy(authored["source"])
    power = next(
        row for row in source["modules"][0]["symbols"] if row["symbol"] == "power"
    )
    power["domain"]["maximum"] = 11
    language = _language(authored["language_bundle"])
    checked = _reference_check_source(source, authored["kernel"], language)
    assert isinstance(checked, ModelSourceContext), checked
    with pytest.raises(ValueError, match="two fixed priority Model Sources"):
        reference_model_artifacts(checked, producer=reference_model_producer())


@pytest.mark.parametrize(
    "mutation",
    (
        "omitted-selected-semantics",
        "stale-selected-semantics",
        "omitted-rir-identity",
        "stale-rir-identity",
        "omitted-model-identity",
        "stale-model-identity",
    ),
)
def test_priority_selected_binding_refuses_omitted_or_stale(fixed_matrix, mutation):
    case = fixed_matrix["renamed"]
    candidate = deepcopy(case.binding_b)
    if mutation == "omitted-selected-semantics":
        del candidate["selected_semantics_sha256"]
    elif mutation == "stale-selected-semantics":
        candidate["selected_semantics_sha256"] = "sha256:" + "0" * 64
    elif mutation == "omitted-rir-identity":
        del candidate["rir_semantic_identity"]
    elif mutation == "stale-rir-identity":
        candidate["rir_semantic_identity"] = "sha256:" + "0" * 64
    elif mutation == "omitted-model-identity":
        del candidate["model_artifact_identities"]["debug-map"]
    else:
        candidate["model_artifact_identities"]["debug-map"] = "sha256:" + "0" * 64
    assert not admits_selected_dependency_binding(case.model_b, candidate)


def test_bounded_rename_preserves_ordinary_strings_and_source_entrypoint_names():
    ordinary = {
        "label": "Counter",
        "payload": {"operation": "pass", "type": "Outcome"},
        "metadata": {"package": "game.action", "id": "Counter"},
    }
    package = {
        "exports": {
            "operations": ["open"],
            "nominal_types": ["Counter"],
            "types": [{"id": "Counter"}],
        },
        "semantic_closure": [
            {
                "authority_path": "language.operations",
                "definitions": [
                    {"id": "open", "owner_type": "Counter", "inputs": [], "body": []}
                ],
            },
            {
                "authority_path": "language.nominal_types",
                "definitions": [{"id": "Counter", "definition": {}}],
            },
        ],
        "ordinary": deepcopy(ordinary),
    }
    source = {
        "modules": [
            {
                "imports": [
                    {
                        "alias": "Counter",
                        "package": "game.action",
                        "symbol": "Counter",
                    }
                ],
                "symbols": [{"type": "Counter"}],
            }
        ],
        "entrypoints": [
            {
                "id": "open",
                "operation": {"package": "game.turn", "id": "open"},
            }
        ],
        "ordinary": deepcopy(ordinary),
    }
    experiment = {
        "scenarios": [
            {"event_plan": [{"entrypoint": "open", "facts": []}], "assignments": []}
        ],
        "ordinary": deepcopy(ordinary),
    }
    _rename_package_semantics(package)
    _rename_source_semantics(source)
    _rename_experiment_semantics(experiment)
    assert (
        package["ordinary"] == source["ordinary"] == experiment["ordinary"] == ordinary
    )
    assert package["exports"]["operations"] == ["renamed-open"]
    assert source["entrypoints"][0] == {
        "id": "open",
        "operation": {"package": "game.turn", "id": "renamed-open"},
    }
    assert experiment["scenarios"][0]["event_plan"][0]["entrypoint"] == "open"


def test_independent_runtime_refuses_scope_outside_priority(fixed_matrix):
    case = fixed_matrix["original"]
    authored, _ = build_priority_case(renamed=False)
    language = _language(authored["language_bundle"])
    checked = _reference_check_source(authored["source"], authored["kernel"], language)
    assert isinstance(checked, ModelSourceContext), checked
    specification = deepcopy(authored["experiments"]["baseline"])
    specification["id"] = "another-scenario"
    with pytest.raises(IndependentRuntimeUnsupported, match="priority witness"):
        reference_runtime_artifacts(
            checked, case.model_b["rir-semantic-payload"], specification
        )


def test_independent_runtime_declares_only_the_priority_closure(fixed_matrix):
    case = fixed_matrix["original"]
    authored, _ = build_priority_case(renamed=False)
    specification = authored["experiments"]["baseline"]
    rir = case.model_b["rir-semantic-payload"]
    available = _supported_shape(specification, rir)
    runtime = rir["selected_semantics"]["execution_laws"]["runtime_program"]
    operators = {row["id"]: row["semantics"]["operator"] for row in runtime["nodes"]}
    required = specification["runtime"]["required_evaluator"]
    assert {operators[node] for node in required["instruction_nodes"]} == (
        _PRIORITY_OPERATORS
    )
    assert available["operation_kinds"] == ["event-program", "pure-expression"]

    expanded_metric = deepcopy(specification)
    second_metric = deepcopy(expanded_metric["metrics"][0])
    second_metric["id"] = "second-result"
    expanded_metric["metrics"].append(second_metric)

    event_count = deepcopy(specification)
    event_count["scenarios"][0]["terminal_condition"] = {
        "kind": "event-count",
        "maximum": 1,
    }

    widened_capability = deepcopy(specification)
    widened_capability["runtime"]["required_evaluator"]["operation_kinds"].append(
        "event-fragment"
    )

    for expanded in (expanded_metric, event_count, widened_capability):
        with pytest.raises(
            IndependentRuntimeUnsupported,
            match="four fixed priority Experiment inputs",
        ):
            _supported_shape(expanded, rir)
