"""A real observation Formula refusal retains its external-input dispatch."""

import json

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.model import AdmittedRir, admit_rir
from gda_balancing.domain.runtime.execution import (
    RuntimeRefusalOutcome,
    evaluate_experiment,
)
from schema2_authority_support import mutable_authorities
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_experiment_cli import _experiment, _rpg_model_source
from test_schema2_model_cli import _reidentify_language_bundle


@pytest.mark.parametrize("maximum,boundary", [(2, "logical-boundary"), (1, "terminal")])
def test_public_external_input_observation_budget_refusal(tmp_path, maximum, boundary):
    kernel, language = mutable_authorities()
    profile = next(
        row
        for row in language["language"]["runtime_profiles"]
        if row["id"] == "standard.exact-int64-event-v1"
    )
    # Initialization reserves 3. The next observation Formula must reserve 3
    # more, even though no transition instruction has run after external input.
    profile["resource_bounds"]["max_node_steps"] = 3
    _reidentify_language_bundle(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, language))
    candidate.write_source(_rpg_model_source())
    receipt = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "13" * 32,
    )
    artifacts = _members(receipt)
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    specification = _experiment(build_receipt=receipt, base_damage=24)
    scenario = specification["scenarios"][0]
    transition = scenario["event_plan"][0]
    transition["logical_time"] = 1
    scenario["event_plan"] = [
        {
            "kind": "external-input",
            "root_event_ref": "raise/~defense",
            "logical_time": 0,
            "priority": 0,
            "source_identity": "sha256:" + "e" * 64,
            "source_sequence": 0,
            "facts": [
                {
                    "target": {
                        "model": "example.rpg-combat-cast",
                        "module": "combat",
                        "name": "target_defense",
                    },
                    "value": 20,
                }
            ],
        },
        transition,
    ]
    scenario["terminal_condition"] = {"kind": "event-count", "maximum": maximum}
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(specification), encoding="utf-8")
    candidate.cli("experiment", "check", str(path), "--rir", rir_path)
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked

    outcome = evaluate_experiment(checked)
    assert isinstance(outcome, RuntimeRefusalOutcome), outcome
    assert outcome.report.variant == "post-dispatch"
    assert outcome.report.diagnostics[0].code == "runtime.step_limit_exceeded"
    assert len(outcome.committed_trace_prefix) == 1
    committed = outcome.committed_trace_prefix[0]
    assert committed["operation"] is None
    assert committed["outcome"] == {"id": "input-admitted", "kind": "success"}
    assert committed["state_before"] == committed["state_after"]
    assert outcome.refusing_entrypoint_id == "input:raise/~defense"
    assert outcome.refusing_entrypoint_identity == committed["event_id"]
    assert outcome.refusing_call_path == "input:raise~1~0defense"
    assert outcome.refusing_operation == "external-input"
    assert outcome.refusing_call_site_identity is None
    assert outcome.refusing_instruction_index is None
    observation = next(
        row
        for row in rir["initialization_programs"]
        if row["site"]["context"]["phase"] == "observation"
    )
    assert outcome.refusing_evaluation_site_identity == observation["site"]["identity"]
    assert outcome.budget_counters["node_steps"] == 6
    assert outcome.budget_counters["event_steps"] == 0
    assert outcome.budget_counters["queue_events"] == 1
    continuation = outcome.last_snapshot_record["continuation"]
    assert isinstance(continuation, dict)
    assert continuation["step_boundary"] == boundary
    ledger = continuation["resource_ledger"]
    assert isinstance(ledger, dict)
    assert ledger["node_steps"] == 3

    result = candidate.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        rir_path,
        "--out",
        str(tmp_path / "run"),
        "--invocation-key",
        "14" * 32,
        success=False,
    )
    assert (candidate.receipts[-1]["returncode"], candidate.receipts[-1]["stderr"]) == (
        2,
        "",
    )
    assert result["error"]["stage"] == "runtime"
    assert result["error"]["diagnostics"][0]["code"] == "runtime.step_limit_exceeded"
    audit = _members(result["error"]["terminal_audit"])["runtime-terminal-audit"]
    assert audit["refusing_event"]["entrypoint"] == {
        "id": outcome.refusing_entrypoint_id,
        "identity": committed["event_id"],
    }
    assert audit["refusing_event"]["call_path"] == outcome.refusing_call_path
