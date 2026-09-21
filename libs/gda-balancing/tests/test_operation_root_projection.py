"""Operation selection follows actual roots, independently of unrelated Type names."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import (
    AdmittedRir,
    CheckedModel,
    admit_rir,
    check_model_source_value,
    compile_checked_model,
)
from gda_balancing.domain.model._binding import RirAdmissionError
from gda_balancing.domain.model._lowering import _identified_rir_artifact
from schema2_authority_support import (
    mutable_authorities,
    refresh_package_semantic_closures,
)
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import (
    _append_empty_namespace,
    _consumer_a,
    _reidentify_graph_root,
)
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_semantic_artifacts,
)


_EXAMPLES = Path(__file__).parents[1] / "examples/schema2"
_OWNER = "standard.conformance.structured"
_OTHER = "inventory.otheritems"
_UNRELATED = {
    (_OWNER, name)
    for name in (
        "bounded.filter-step",
        "bounded.count-step",
        "bounded.order-step",
        "bounded-fold-v1",
    )
}


def _source():
    return json.loads(
        (_EXAMPLES / "rpg-periodic-effect/model-source.json").read_bytes()
    )


def _collision_candidate(renamed):
    kernel, language = mutable_authorities()
    owner = next(row for row in language["language"]["packages"] if row["id"] == _OWNER)
    other = _append_empty_namespace(language, _OTHER)
    other["runtime_semantic_paths"] = ["language.nominal_types"]
    other["dependencies"]["required"] = ["core.quantity", "standard.schema"]
    name = "OtherItems" if renamed else "IntList4"
    exported = deepcopy(
        next(row for row in owner["exports"]["types"] if row["id"] == "IntList4")
    )
    exported["id"] = name
    other["exports"]["types"] = [exported]
    other["exports"]["nominal_types"] = [name]
    definition = deepcopy(
        next(
            row
            for closure in owner["semantic_closure"]
            if closure["authority_path"] == "language.nominal_types"
            for row in closure["definitions"]
            if row["id"] == "IntList4"
        )
    )
    definition["id"] = name
    definition["definition"]["maximum_length"] = 2
    next(
        row
        for row in other["semantic_closure"]
        if row["authority_path"] == "language.nominal_types"
    )["definitions"] = [definition]
    _reidentify_graph_root(language)
    source = _source()
    source["package_requirements"] += [_OWNER, _OTHER]
    module = source["modules"][0]
    module["imports"].append(
        {"alias": "unused_items", "package": _OTHER, "symbol": name}
    )
    module["symbols"].append(
        {
            "symbol": "unused_items",
            "type": "unused_items",
            "role": "input",
            "value_policy": {"mode": "experiment-required"},
        }
    )
    return kernel, language, source


def _operations(rir):
    return {
        (row["package"], row["definition"]["id"])
        for row in rir["selected_semantics"]["operations"]
    }


def test_unused_same_name_type_rename_preserves_actual_public_operation_closure(
    tmp_path,
):
    observations = []
    for renamed in (False, True):
        kernel, language, source = _collision_candidate(renamed)
        for consumer in (_consumer_a, _consumer_b):
            report = consumer(kernel, language)
            assert report["admitted"], report["diagnostics"]
        context = admit_authority_context(kernel, language)
        assert isinstance(context, AdmittedAuthorityContext), context
        public = _PublicCandidate(
            tmp_path / str(renamed), authorities=(kernel, language)
        )
        public.write_source(source)
        build = public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(public.directory / "build"),
            "--invocation-key",
            "46" * 32,
        )
        artifacts = _members(build)
        assert len(artifacts) == 8
        rir = artifacts["rir-semantic-payload"]
        independent = _reference_check_source(source, kernel, language)
        assert not isinstance(independent, tuple), independent
        assert _reference_semantic_artifacts(independent)["rir-semantic-payload"] == rir
        program = admit_rir(rir, authority_context=context)
        assert isinstance(program, AdmittedRir)
        assert _operations(rir).isdisjoint(_UNRELATED)
        locator = next(
            row["locator"]
            for row in build["member_locators"]
            if row["logical_name"] == "rir-semantic-payload"
        )
        specification = json.loads(
            (_EXAMPLES / "rpg-periodic-effect/experiment.json").read_bytes()
        )
        specification["model"] = {"rir_semantic_identity": rir["semantic_identity"]}
        path = public.directory / "experiment.json"
        path.write_text(json.dumps(specification))
        assert public.cli("experiment", "check", str(path), "--rir", locator)["checked"]
        run = public.cli(
            "experiment",
            "run",
            str(path),
            "--rir",
            locator,
            "--out",
            str(public.directory / "run"),
            "--invocation-key",
            "47" * 32,
        )
        members = _members(run)
        checked = check_experiment_value(
            specification, program, authority_context=context
        )
        assert isinstance(checked, CheckedExperiment), checked
        assert validate_experiment_artifact_set(checked, members)
        # Only these content-derived links vary with the renamed Type declaration.
        # Complete sets above are admitted before comparing every event/state/value.
        metrics = [
            {
                key: value
                for key, value in row.items()
                if key not in {"event_id", "snapshot_identity"}
            }
            for row in members["metric-dataset"]["samples"]
        ]
        events = deepcopy(members["event-trace"]["events"])
        event_ids = {row["event_id"]: row["index"] for row in events}
        scheduled_sites = {
            schedule["call_site_identity"]: (event["index"], index)
            for event in events
            for index, schedule in enumerate(event["schedules"])
        }
        assert len(scheduled_sites) == sum(len(row["schedules"]) for row in events)
        for event in events:
            # Preserve links and ordering while relabeling content-derived IDs.
            event["event_id"] = event_ids[event["event_id"]]
            if "parent_event_id" in event:
                event["parent_event_id"] = event_ids[event["parent_event_id"]]
                event["schedule_call_site_identity"] = scheduled_sites[
                    event["schedule_call_site_identity"]
                ]
            for key in ("snapshot_before_identity", "snapshot_after_identity"):
                del event[key]
            for evaluation in event["formula_evaluations"]:
                del evaluation["frame_identity"]
            for schedule in event["schedules"]:
                schedule["event_id"] = event_ids[schedule["event_id"]]
                schedule["call_site_identity"] = scheduled_sites[
                    schedule["call_site_identity"]
                ]
        snapshots = [
            {
                key: row[key]
                for key in ("index", "logical_time", "name", "scenario", "values")
            }
            | {
                "name": row["name"].replace(
                    row["event_id"], str(event_ids[row["event_id"]])
                )
                if row["event_id"] is not None
                else row["name"],
                "resources": row["continuation"]["resource_ledger"],
                "rng": row["continuation"]["rng"],
                "lifecycle": row["continuation"]["lifecycle_state"],
                "pending": row["continuation"]["pending_event_count"],
            }
            for row in members["snapshot-series"]["snapshots"]
        ]
        observations.append(
            (_operations(rir), rir["entrypoints"], metrics, events, snapshots)
        )
    # Both admitted Type owners remain distinct. Neither supplies an Operation root.
    assert observations[0] == observations[1]


@pytest.mark.parametrize(
    "mutation",
    ["missing-rule", "wrong-collection", "extra-rule-member", "retired-owner-field"],
)
def test_operation_roots_are_one_closed_machine_rule(mutation):
    kernel, language = mutable_authorities()
    profile = language["language"]["model_lowerings"][0]["runtime_projection"]
    if mutation == "missing-rule":
        del profile["operation_roots"]
    elif mutation == "wrong-collection":
        profile["operation_roots"]["collection"] = "types"
    elif mutation == "extra-rule-member":
        profile["operation_roots"]["fallback"] = "all-operations"
    else:
        language["language"]["operations"][0]["owner_type"] = "Quantity"
    # Rebuild the corresponding owner closure, not just an unattached flat row.
    refresh_package_semantic_closures(language, kernel)
    _reidentify_graph_root(language)
    for consumer in (_consumer_a, _consumer_b):
        assert not consumer(kernel, language)["admitted"]


@pytest.mark.parametrize(
    "reference,member",
    [
        ({"package": "game.effect", "id": "unknown"}, "id"),
        ({"package": "game.generation", "id": "generate-v1"}, "package"),
    ],
)
def test_unknown_or_unselected_operation_root_preserves_exact_source_refusal(
    reference, member
):
    source = _source()
    source["entrypoints"][0]["operation"] = reference
    checked = check_model_source_value(source)
    assert isinstance(checked, Schema2RefusalReport), checked
    assert all(d.primary.kind == "artifact" for d in checked.diagnostics)
    assert [
        (d.code, d.primary.pointer)
        for d in checked.diagnostics
        if d.primary.kind == "artifact"
    ] == [("language.source_contract_mismatch", f"/entrypoints/0/operation/{member}")]
    context = packaged_authority_context()
    assert _reference_check_source(source, context.kernel, context.language_bundle) == (
        ("language.source_contract_mismatch", f"/entrypoints/0/operation/{member}"),
    )


@pytest.fixture(scope="module")
def compiled():
    checked = check_model_source_value(_source())
    assert isinstance(checked, CheckedModel), checked
    return compile_checked_model(checked)


@pytest.mark.parametrize(
    "mutation", ["unknown-entrypoint", "omit-operation", "extra-operation"]
)
def test_import_rederives_operation_roots_after_complete_rir_reidentification(
    compiled, mutation
):
    context = packaged_authority_context()
    rir = deepcopy(compiled["rir-semantic-payload"])
    selected = rir["selected_semantics"]
    if mutation == "unknown-entrypoint":
        rir["entrypoints"][0]["operation"]["id"] = "unknown"
    elif mutation == "omit-operation":
        removed = selected["operations"].pop()
        for closure in selected["package_semantic_closures"]:
            if closure["package"] == removed["package"]:
                for entry in closure["definitions"]:
                    if entry["authority_path"] == "language.operations":
                        entry["definitions"] = [
                            row
                            for row in entry["definitions"]
                            if row["id"] != removed["definition"]["id"]
                        ]
    else:
        actual = _operations(rir)
        owner, definition = next(
            (package["id"], definition)
            for package in context.language_bundle["language"]["packages"]
            if package["id"] in {row["id"] for row in selected["packages"]}
            for closure in package["semantic_closure"]
            if closure["authority_path"] == "language.operations"
            for definition in closure["definitions"]
            if (package["id"], definition["id"]) not in actual
        )
        definition = deepcopy(definition)
        definition.pop("vectors")
        selected["operations"].append({"package": owner, "definition": definition})
        closure = next(
            row
            for row in selected["package_semantic_closures"]
            if row["package"] == owner
        )
        next(
            row
            for row in closure["definitions"]
            if row["authority_path"] == "language.operations"
        )["definitions"].append(deepcopy(definition))
    identified = _identified_rir_artifact(
        context.language_bundle,
        {
            key: value
            for key, value in rir.items()
            if key not in {"artifact_kind", "content_identity", "semantic_identity"}
        },
    )
    with pytest.raises(
        RirAdmissionError, match="does not match its admitted semantics"
    ):
        admit_rir(identified, authority_context=context)
