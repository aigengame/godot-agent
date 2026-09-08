"""Schedules capture state at their instruction, after preceding Event writes."""

from copy import deepcopy
import json

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import content_identity
from gda_balancing.domain.experiment import (
    CheckedExperiment,
    check_experiment_value,
    derive_scenario_program_requirements,
)
from gda_balancing.domain.experiment_artifacts import (
    _event_catalog_record_is_valid,
    _event_catalog_records_are_authoritative,
    validate_experiment_artifact_set,
    validate_experiment_member,
)
from gda_balancing.domain.model import AdmittedRir, admit_rir
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_experiment_cli import _experiment, _metric_contract, _rpg_model_source


@pytest.fixture(scope="module")
def capture_candidate(tmp_path_factory):
    kernel, language = mutable_authorities()
    package = next(
        row for row in language["language"]["packages"] if row["id"] == "game.combat"
    )
    operation = next(
        definition
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
        for definition in entry["definitions"]
        if definition["id"] == "game.combat.plan-casts-v1"
    )
    operation["body"][:0] = [
        {"node": "constant", "target": "refilled_resource", "literal": 20},
        {
            "node": "write-state",
            "symbol": "actor_resource",
            "value": "refilled_resource",
        },
    ]
    operation["resource_bounds"]["max_steps"] += 2
    vectors = next(
        row
        for row in language.package_conformance_vector_sets
        if row["package_id"] == package["id"]
    )
    _bind_package_vector_set(package, vectors, kernel=kernel)
    _reidentify_graph_root(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    candidate = _PublicCandidate(
        tmp_path_factory.mktemp("schedule-capture"), authorities=(kernel, language)
    )
    candidate.write_source(_rpg_model_source())
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(candidate.directory / "build"),
        "--invocation-key",
        "18" * 32,
    )
    rir = _members(build)["rir-semantic-payload"]
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    rir_path = next(
        row["locator"]
        for row in build["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    return candidate, context, build, rir, program, rir_path


@pytest.fixture(
    scope="module", params=[20, 30], ids=["unchanged-value", "post-write-value"]
)
def captured_execution(capture_candidate, request):
    candidate, context, build, rir, program, rir_path = capture_candidate
    specification = _experiment(build_receipt=build, base_damage=12)
    scenario = specification["scenarios"][0]
    next(
        row for row in scenario["assignments"] if row["target"]["name"] == "actor_mana"
    )["value"] = request.param
    scenario["event_plan"] = [
        {
            "kind": "transition-invocation",
            "root_event_ref": "plan-casts",
            "logical_time": 0,
            "priority": 0,
            "entrypoint": "combat.plan-casts",
            "payload": [],
        }
    ]
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": 2}
    specification["metrics"] = [
        _metric_contract(
            {
                "id": "remaining-mana",
                "kind": "scalar",
                "unit": "1",
                "observation": {
                    "source": "snapshot",
                    "name": "terminal",
                    "member": "actor_mana",
                },
                "target": {"minimum": 12, "maximum": 12},
            }
        )
    ]
    requirements, _ = derive_scenario_program_requirements(
        rir,
        "combat.plan-casts",
        specification["runtime"]["profile"],
        specification["seed"]["algorithm"],
    )
    specification["runtime"]["required_evaluator"] = requirements
    path = candidate.directory / f"experiment-{request.param}.json"
    path.write_text(json.dumps(specification))
    candidate.cli("experiment", "check", str(path), "--rir", rir_path)
    receipt = candidate.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        rir_path,
        "--out",
        str(candidate.directory / f"run-{request.param}"),
        "--invocation-key",
        f"{request.param:02x}" * 32,
    )
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    members = _members(receipt)
    assert validate_experiment_artifact_set(checked, members)
    return checked, members, request.param


def test_public_schedule_captures_the_actual_post_write_value(captured_execution):
    _, members, initial = captured_execution
    events = members["event-trace"]["events"]
    parent, child, observation = events
    assert parent["operation"] == "game.combat.plan-casts-v1"
    assert child["operation"] == "game.combat.cast-v1"
    assert observation["operation"] is None
    before = {row["name"]: row["value"] for row in parent["state_before"]}
    after = {row["name"]: row["value"] for row in parent["state_after"]}
    assert (before["actor_mana"], after["actor_mana"]) == (initial, 20)
    assert len(parent["schedules"]) == 2
    assert len(parent["cancellations"]) == 1
    for schedule in parent["schedules"]:
        assert (
            next(
                row for row in schedule["arguments"] if row["name"] == "actor_resource"
            )["value"]
            == 20
        )
        assert next(
            row
            for row in schedule["state_references"]
            if row["name"] == "actor_resource"
        )["target"] == {
            "model": "example.rpg-combat-cast",
            "module": "combat",
            "name": "actor_mana",
        }
    assert child["event_id"] == parent["schedules"][0]["event_id"]
    assert {row["name"]: row["value"] for row in child["state_after"]}[
        "actor_mana"
    ] == 12
    assert [row["value"] for row in members["metric-dataset"]["samples"]] == [12]


@pytest.mark.parametrize(
    "mutation", ["captured-value", "argument-name", "state-reference"]
)
def test_resealed_schedule_capture_cannot_forge_replayed_bindings(
    captured_execution, mutation
):
    checked, original, _ = captured_execution
    members = deepcopy(original)
    catalog = members["snapshot-series"]["event_catalog"]
    events = members["event-trace"]["events"]
    parent = events[0]
    schedule = parent["schedules"][0]
    record = next(row for row in catalog if row["event_id"] == schedule["event_id"])
    for carrier in (schedule, record["event_spec"]):
        if mutation == "state-reference":
            row = next(
                row
                for row in carrier["state_references"]
                if row["name"] == "actor_resource"
            )
            row["target"]["name"] = "target_health"
        else:
            row = next(
                row for row in carrier["arguments"] if row["name"] == "actor_resource"
            )
            row["value" if mutation == "captured-value" else "name"] = (
                30 if mutation == "captured-value" else "forged_resource"
            )
    domain = checked.kernel["meta_format"]["runtime_program"]["scheduler"][
        "runtime_journal"
    ]["event_spec"]["domain"]
    record["event_spec_identity"] = content_identity(domain, record["event_spec"])
    assert _event_catalog_record_is_valid(checked, record)
    # This boundary does not inspect the containing artifacts' hashes: the
    # coordinated, resealed claim itself must disagree with actual Replay.
    assert not _event_catalog_records_are_authoritative(checked, catalog, events)
    for name in ("event-trace", "snapshot-series"):
        contract = checked.output_contracts[name]
        members[name] = contract.identify(
            {
                key: value
                for key, value in members[name].items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            }
        )
        assert validate_experiment_member(checked, name, members[name])
    assert not validate_experiment_artifact_set(checked, members)
