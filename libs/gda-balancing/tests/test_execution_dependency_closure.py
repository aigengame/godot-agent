"""Executable budgets must belong to the admitted RIR meaning (#874)."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import content_identity
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
    admit_rir,
)
from gda_balancing.domain.runtime.execution import (
    EvaluationArtifacts,
    evaluate_experiment,
)
from schema2_authority_support import mutable_authorities
from test_schema2_model_cli import _reidentify_language_bundle


_EXAMPLE = Path(__file__).parents[1] / "examples" / "schema2" / "structured-selection"


def _structured_budget_context(limit: int) -> AdmittedAuthorityContext:
    kernel, language_bundle = mutable_authorities()
    language_bundle["resources"]["max_rule_match_steps"] = limit
    state_type = next(
        row
        for row in language_bundle["language"]["nominal_types"]
        if row["id"] == "SelectionState"
    )
    # The same larger legal type is used at all three limits. Its value costs
    # 838 nodes, above this Source's resolution cost, so all builds can succeed.
    for field in state_type["definition"]["fields"]:
        if field["type"].get("kind") == "list":
            field["type"]["maximum_length"] = 64
    for identifier, value in (
        ("model.accept.resolution-step-boundary", limit),
        ("model.refuse.resolution-step-budget", limit + 1),
    ):
        next(row for row in language_bundle["vectors"] if row["id"] == identifier)[
            "input"
        ]["value"] = value
    _reidentify_language_bundle(language_bundle)
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    return context


def test_structured_value_budget_changes_rir_meaning_and_preserves_exact_boundary():
    source = json.loads((_EXAMPLE / "model-source.json").read_bytes())
    specification = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    state = specification["scenarios"][0]["assignments"][0]["value"]["value"]
    state["candidates"] *= 32
    state["results"] *= 32
    semantic_identities: dict[int, str] = {}

    for limit in (837, 838, 839):
        context = _structured_budget_context(limit)
        checked_model = check_model_source_value(source, authority_context=context)
        assert isinstance(checked_model, CheckedModel), checked_model
        artifacts = compile_checked_model(checked_model)
        assert set(artifacts) == {
            "build-receipt",
            "capability-manifest",
            "debug-map",
            "model-explanation",
            "package-lock",
            "resolution-receipt",
            "resolved-model",
            "rir-semantic-payload",
        }
        semantic_identities[limit] = cast(
            str, artifacts["rir-semantic-payload"]["semantic_identity"]
        )
        program = admit_rir(
            artifacts["rir-semantic-payload"], authority_context=context
        )
        value = deepcopy(specification)
        value["model"] = {"rir_semantic_identity": program.semantic_identity}
        checked = check_experiment_value(value, program, authority_context=context)

        if limit == 837:
            assert isinstance(checked, Schema2RefusalReport), checked
            assert checked.model_dump(mode="json") == {
                "stage": "static",
                "variant": None,
                "diagnostics": [
                    {
                        "code": "language.structured_value_resource_exhausted",
                        "message": "Scenario assignment does not match its declared value",
                        "primary": {
                            "kind": "artifact",
                            "content_identity": content_identity(
                                "experiment-specification-v2", value
                            ),
                            "pointer": "/scenarios/0/assignments/0/value/value/selected",
                        },
                        "related": [],
                    }
                ],
                "truncated": False,
                "terminal_audit": None,
            }
            continue

        assert isinstance(checked, CheckedExperiment), checked
        outcome = evaluate_experiment(checked)
        assert isinstance(outcome, EvaluationArtifacts), outcome
        assert outcome.accepted is True
        assert outcome.failed_metrics == ()
        members = {
            name: cast(dict[str, Any], member.value)
            for name, member in outcome.members.items()
        }
        assert validate_experiment_artifact_set(checked, members) is True
        events = members["event-trace"]["events"]
        assert [event["outcome"] for event in events] == [
            {"id": "selected", "kind": "success"},
            {"id": "observation-emitted", "kind": "success"},
        ]
        transition = events[0]
        before = next(
            row
            for row in transition["state_before"]
            if row["name"] == "selected_result"
        )
        after = next(
            row for row in transition["state_after"] if row["name"] == "selected_result"
        )
        assert before["value"]["value"] == {
            "selected": {"key": "candidate_b"},
            "kind": "secondary",
            "rank": 9,
        }
        assert after["value"]["value"] == {
            "selected": {"key": "candidate_a"},
            "kind": "primary",
            "rank": 3,
        }
        fact = next(
            row for row in transition["facts"] if row["name"] == "selection_result"
        )
        assert fact["value"] == after["value"]
        assert [row["value"] for row in members["metric-dataset"]["samples"]] == [3]
        assert (
            members["snapshot-series"]["snapshots"][-1]["values"]
            == transition["state_after"]
        )

    # Assert only after every candidate passes its complete expected pipeline;
    # an inadmissible authority or an earlier behavior drift is not this defect.
    assert len(set(semantic_identities.values())) == 3, semantic_identities
