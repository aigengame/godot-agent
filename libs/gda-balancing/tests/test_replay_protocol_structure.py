"""Replay owns its fixed comparison container, independently of Publication."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
import pytest

from gda_balancing.domain.authority.replay_projection import replay_comparison_schema
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from gda_balancing.domain.comparison import (
    compare_exact_replay,
    select_exact_replay_contract,
    validate_exact_replay_comparison,
    validate_published_exact_replay_comparison,
)
from gda_balancing.domain.publication import _read_canonical_artifact
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_replay_schema,
    _encoded,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    read_extension_inventory,
    validate_extension_inventory,
)
from test_current_namespace_public import _PublicCandidate, _members
from test_receipt_protocol_structure import _definitions
from test_rir_protocol_structure_independent import _raw_language
from test_schema2_comparison import (
    _artifact_payload,
    _authority_context,
    _same_execution_observation_drift,
    accepted_execution as accepted_execution,
)
from test_trace_protocol_structure import _authored, _graph, _index


def _replay_rows(authored):
    schema = next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == "replay-comparison"
    )
    contract = next(
        row
        for row in _definitions(authored, "language.artifact_contracts")
        if row["schema_kind"] == schema["artifact_kind"]
    )
    return schema, contract


def test_replay_comparison_schema_has_no_authored_owner():
    _, ldb = mutable_authorities()
    schema, _ = _replay_rows(_authored(ldb))
    assert set(schema) == {"artifact_kind", "protocol_role"}


@pytest.mark.parametrize("rename", [False, True], ids=["same-schema", "checks-rename"])
def test_resealed_replay_schema_override_refuses_at_both_consumers(rename):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    schema, _ = _replay_rows(authored)
    generated = deepcopy(
        next(
            row["schema"]
            for row in ldb["language"]["artifact_wire_schemas"]
            if row.get("protocol_role") == "replay-comparison"
        )
    )
    if rename:
        generated["properties"]["review_checks"] = generated["properties"].pop("checks")
        generated["required"] = [
            "review_checks" if member == "checks" else member
            for member in generated["required"]
        ]
    schema["schema"] = generated
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"] is False, result
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]


def test_replay_schema_is_independently_derived_with_exact_original_wire(monkeypatch):

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    before = _encoded(authored)
    _, contract = _replay_rows(authored)
    schema_a = replay_comparison_schema(
        kernel, ldb["language"], contract["artifact_kind"]
    )
    schema_b = _consumer_b_replay_schema(
        kernel, _raw_language(ldb), contract["artifact_kind"]
    )
    assert _encoded(schema_a) == _encoded(schema_b)
    assert len(_encoded(schema_a)) == 2354
    assert (
        hashlib.sha256(_encoded(schema_a)).hexdigest()
        == "d04560ec5d632b7162c65cb9843d180d6396b5a174bf2eea8280ea2f2cbd5d18"
    )
    graph = _graph(kernel, authored)
    assert _consumer_a(kernel, graph)["admitted"]

    def unavailable(*_args, **_kwargs):
        raise AssertionError("B called the production Replay projection")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.replay_projection.replay_comparison_schema",
        unavailable,
    )
    assert _consumer_b(kernel, graph)["admitted"]
    assert _encoded(authored) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-field",
        "duplicate-required",
        "duplicate-owner",
        "missing-outcome",
        "duplicate-outcome",
    ],
)
def test_replay_projection_rejects_incomplete_or_ambiguous_owners(mutation):

    kernel, ldb = mutable_authorities()
    language = _raw_language(ldb)
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "replay_comparison_structure"
    ]
    if mutation == "missing-field":
        del law["field_types"]["original_artifact_set_receipt_identity"]
    elif mutation == "duplicate-required":
        law["required_members"].append("policy")
    elif mutation == "duplicate-owner":
        law["field_types"]["checks"] = {"type": "list"}
    else:
        outcome = next(
            row
            for row in language["artifact_wire_schemas"]
            if row.get("protocol_role") == "evaluation-run"
        )
        if mutation == "missing-outcome":
            language["artifact_wire_schemas"].remove(outcome)
        else:
            language["artifact_wire_schemas"].append(deepcopy(outcome))
    for projector in (replay_comparison_schema, _consumer_b_replay_schema):
        with pytest.raises(ValueError):
            projector(kernel, language, "actual.comparison")


@pytest.mark.parametrize(
    "mismatch", [False, True], ids=["executed-match", "observed-drift"]
)
def test_replay_wire_keeps_actual_complete_comparison_oracle(
    accepted_execution, mismatch
):

    checked, execution = accepted_execution
    context = _authority_context(checked)
    contract = select_exact_replay_contract(context)
    # A real successful execution is the control. The drift case deliberately
    # changes returned observations; it is not a second conforming Runtime run.
    replay = (
        _same_execution_observation_drift(checked, execution).members
        if mismatch
        else execution.members
    )
    arguments: dict[str, Any] = dict(
        replay_contract=contract,
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:" + "1" * 64,
        original_members=execution.members,
        replay_members=replay,
    )
    actual = compare_exact_replay(**arguments).value
    assert actual["result"] == ("mismatched" if mismatch else "matched")
    assert [row["key"] for row in actual["checks"]] == [
        "evaluation_outcome_status",
        "event_trace_identity",
        "snapshot_series_identity",
        "metric_dataset_identity",
    ]
    assert [row["match"] for row in actual["checks"]] == [not mismatch] * 4
    assert actual["original_observation"]["evaluation_outcome_status"] == "accepted"
    assert actual["replay_observation"]["evaluation_outcome_status"] == (
        "rejected" if mismatch else "accepted"
    )
    assert validate_exact_replay_comparison(actual, **arguments)
    assert validate_published_exact_replay_comparison(actual, **arguments)
    kernel, language = context.mutable_pair()
    Draft202012Validator(
        _consumer_b_replay_schema(kernel, language["language"], actual["artifact_kind"])
    ).validate(actual)


@pytest.mark.parametrize(
    "mutation",
    [
        "receipt-binding",
        "original-outcome",
        "replay-outcome",
        "outcome-kind",
        "missing-observation",
        "extra-observation",
        "missing-check",
        "duplicate-check",
        "coordinated-lie",
    ],
)
def test_resealed_replay_wire_cannot_replace_the_actual_comparison_oracle(
    accepted_execution, mutation
):

    checked, execution = accepted_execution
    contract = select_exact_replay_contract(_authority_context(checked))
    arguments: dict[str, Any] = dict(
        replay_contract=contract,
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:" + "1" * 64,
        original_members=execution.members,
        replay_members=execution.members,
    )
    actual = compare_exact_replay(**arguments).value
    payload = _artifact_payload(actual)
    bindings = {
        "receipt-binding": "original_artifact_set_receipt_identity",
        "original-outcome": "original_evaluation_run_identity",
        "replay-outcome": "replay_outcome_identity",
    }
    if mutation in bindings:
        payload[bindings[mutation]] = "sha256:" + "0" * 64
    elif mutation == "outcome-kind":
        payload["replay_outcome_kind"] = checked.output_contracts[
            "experiment-verdict"
        ].definition["artifact_kind"]
    elif mutation == "missing-observation":
        del payload["replay_observation"]["metric_dataset_identity"]
    elif mutation == "extra-observation":
        payload["replay_observation"]["copied_observation"] = payload[
            "replay_observation"
        ]["metric_dataset_identity"]
    elif mutation == "missing-check":
        payload["checks"].pop()
    elif mutation == "duplicate-check":
        payload["checks"][-1] = deepcopy(payload["checks"][0])
    else:
        payload["replay_observation"]["metric_dataset_identity"] = "sha256:" + "0" * 64
        payload["checks"][-1]["replay"] = "sha256:" + "0" * 64
        payload["checks"][-1]["match"] = False
        payload["result"] = "mismatched"

    forged = {**actual, **payload}
    forged["content_identity"] = content_identity(
        contract.artifact.definition["identity_domain"],
        {name: value for name, value in forged.items() if name != "content_identity"},
    )
    assert contract.artifact.verify(forged) is (
        mutation not in {"missing-observation", "extra-observation"}
    )
    assert not validate_exact_replay_comparison(forged, **arguments)
    assert not validate_published_exact_replay_comparison(forged, **arguments)


def _rename_replay(authored):
    schema, contract = _replay_rows(authored)
    old_schema, old_kind = schema["artifact_kind"], contract["artifact_kind"]
    schema["artifact_kind"] = contract["schema_kind"] = "review.replay.schema"
    contract["artifact_kind"] = "review.replay.result"
    for package in authored["packages"]:
        for collection, old, new in (
            ("artifact_wire_schemas", old_schema, schema["artifact_kind"]),
            ("artifact_contracts", old_kind, contract["artifact_kind"]),
        ):
            package["exports"][collection] = [
                new if value == old else value
                for value in package["exports"][collection]
            ]


def test_replay_schema_gap_closes_without_ghost_fields_or_forged_coverage():

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _rename_replay(authored)
    inventory = read_extension_inventory(kernel, authored)
    validate_extension_inventory(kernel, authored, inventory)
    schema_token = AuthorityToken(
        "language.artifact_wire_schemas", (), "review.replay.schema"
    )
    kind_token = AuthorityToken(
        "language.artifact_contracts", (), "review.replay.result"
    )
    assert {schema_token, kind_token} <= inventory.tokens - inventory.reserved
    declaration = next(
        o
        for o in inventory.occurrences
        if o.token == schema_token and o.use == "declaration"
    )
    pointer = declaration.pointer.removesuffix("/artifact_kind")
    assert not any(g.pointer == pointer for g in inventory.uncovered)
    assert not any(
        o.pointer.startswith(pointer + "/schema/") for o in inventory.occurrences
    )
    assert inventory.uncovered
    link = next(
        o
        for o in inventory.occurrences
        if o.token == schema_token and o.pointer.endswith("/schema_kind")
    )
    forged = replace(
        inventory, occurrences=tuple(o for o in inventory.occurrences if o != link)
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, authored, forged)
    authored_schema, _ = _replay_rows(authored)
    authored_schema["unclassified"] = "hidden.name"
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, authored)


def test_actual_public_authenticated_replay_survives_distinct_schema_and_kind_names(
    tmp_path,
):

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    _rename_replay(authored)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result["diagnostics"]
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    example = Path(__file__).parents[1] / "examples/schema2/bounded-fold"
    candidate.write_source(json.loads((example / "model-source.json").read_text()))
    candidate.cli("model", "check", str(candidate.source))
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "d1" * 32,
    )
    rir = _members(build)["rir-semantic-payload"]
    rir_path = tmp_path / "rir.json"
    rir_path.write_text(json.dumps(rir))
    specification = json.loads((example / "experiment.json").read_text())
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    specification_path = tmp_path / "experiment.json"
    specification_path.write_text(json.dumps(specification))
    candidate.cli(
        "experiment", "check", str(specification_path), "--rir", str(rir_path)
    )
    run = candidate.cli(
        "experiment",
        "run",
        str(specification_path),
        "--rir",
        str(rir_path),
        "--out",
        str(tmp_path / "run.json"),
        "--invocation-key",
        "d2" * 32,
    )
    assert {
        row["metric"]: row["value"]
        for row in _members(run)["metric-dataset"]["samples"]
    } == {"ordered_value": 1234, "selected_count": 2}
    receipt_path = tmp_path / "original-receipt.json"
    receipt_path.write_text(json.dumps(run))
    replay = candidate.cli(
        "experiment",
        "replay",
        str(specification_path),
        "--rir",
        str(rir_path),
        "--original-experiment-run-artifact-set-receipt",
        str(receipt_path),
        "--out",
        str(tmp_path / "comparison.json"),
        "--invocation-key",
        "d3" * 32,
    )
    assert replay["claim_state"] == "candidate"
    actual = json.loads((tmp_path / "comparison.json").read_text())
    assert actual["artifact_kind"] == "review.replay.result"
    assert actual["result"] == "matched"
    assert actual["original_artifact_set_receipt_identity"] == run["content_identity"]
    assert actual["original_observation"] == actual["replay_observation"]
    assert [row["key"] for row in actual["checks"]] == [
        "evaluation_outcome_status",
        "event_trace_identity",
        "snapshot_series_identity",
        "metric_dataset_identity",
    ]
    assert all(row["match"] for row in actual["checks"])
    language = _index(kernel, graph)["language"]
    Draft202012Validator(
        _consumer_b_replay_schema(kernel, language, actual["artifact_kind"])
    ).validate(actual)


@pytest.mark.parametrize(
    "duplicate", ["original_observation", "metric_dataset_identity"]
)
def test_replay_publication_reader_rejects_duplicate_observation_keys(
    accepted_execution, tmp_path, duplicate
):

    checked, execution = accepted_execution
    contract = select_exact_replay_contract(_authority_context(checked))
    actual = compare_exact_replay(
        replay_contract=contract,
        output_contracts=checked.output_contracts,
        original_artifact_set_receipt_identity="sha256:" + "1" * 64,
        original_members=execution.members,
        replay_members=execution.members,
    ).value
    path = tmp_path / "comparison.json"
    path.write_bytes(canonical_bytes(actual))
    assert _read_canonical_artifact(path) == actual
    data = path.read_text()
    value = (
        actual[duplicate]
        if duplicate in actual
        else actual["original_observation"][duplicate]
    )
    pair = (
        json.dumps(duplicate)
        + ":"
        + json.dumps(value, sort_keys=True, separators=(",", ":"))
    )
    assert pair in data
    path.write_text(data.replace(pair, pair + "," + pair, 1))
    with pytest.raises(
        RuntimeError, match="committed publication member is unreadable"
    ) as refused:
        _read_canonical_artifact(path)
    assert isinstance(refused.value.__cause__, ValueError)
    assert "duplicate object key" in str(refused.value.__cause__)


@pytest.mark.parametrize(
    "projector", [replay_comparison_schema, _consumer_b_replay_schema], ids=["A", "B"]
)
def test_replay_generated_schema_does_not_mutate_its_supplied_owners(projector):
    kernel, ldb = mutable_authorities()
    language = _raw_language(ldb)
    before = _encoded([kernel, language])
    schema = projector(kernel, language, "actual.comparison")
    schema["properties"]["checks"]["items"]["required"].pop()
    schema["properties"]["policy"]["required"].pop()
    schema["properties"]["result"]["enum"].pop()
    schema["properties"]["original_observation"]["required"].pop()
    assert _encoded([kernel, language]) == before
