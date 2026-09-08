"""Artifact protocol responsibilities survive renamed wire kinds and member labels."""

from copy import deepcopy
import json

import pytest

from gda_balancing.domain.artifacts import (
    artifacts_by_protocol_role,
    identified_artifact,
    verify_artifact,
)
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import AdmittedRir, admit_rir
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from test_bounded_fold_public import _source, _specification
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import _reidentify_language_bundle


def _authorities(renamed):
    kernel, language = mutable_authorities()
    if renamed:
        names = {
            row["artifact_kind"]
            for collection in ("wire_schemas", "artifact_wire_schemas")
            for row in language["language"][collection]
            if "protocol_role" in row
        } | {row["artifact_kind"] for row in language["language"]["artifact_contracts"]}
        replacements = {
            name: f"candidate.transport.{index}"
            for index, name in enumerate(sorted(names))
        }

        def transform(value, path=()):
            if isinstance(value, dict):
                for member, child in list(value.items()):
                    if member != "protocol_role":
                        value[member] = transform(child, (*path, member))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    value[index] = transform(child, (*path, str(index)))
            elif isinstance(value, str):
                direct = path[-1:] in (
                    ("artifact_kind",),
                    ("schema_kind",),
                    ("member_kind",),
                )
                exported = "exports" in path and any(
                    collection in path
                    for collection in (
                        "artifact_contracts",
                        "artifact_wire_schemas",
                        "wire_schemas",
                    )
                )
                wire_value = "properties" in path and any(
                    member in path
                    for member in ("artifact_kind", "replay_outcome_kind")
                )
                if direct or exported or wire_value:
                    return replacements.get(value, value)
            return value

        # Change declared kind references, not an identically spelled Kernel
        # initialization_source role, vector constructor, or Evidence subject ID.
        transform(language)
        _reidentify_language_bundle(language)
    return kernel, language


@pytest.fixture(scope="module", params=[False, True], ids=["original", "renamed"])
def protocol_public(request, tmp_path_factory):
    kernel, language = _authorities(request.param)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    independent = _consumer_b(kernel, language)
    assert independent["admitted"], independent["diagnostics"]
    directory = tmp_path_factory.mktemp("artifact-protocol")
    candidate = _PublicCandidate(directory, authorities=(kernel, language))
    candidate.write_source(_source())
    build = candidate.cli(
        "model",
        "build",
        str(candidate.source),
        "--out",
        str(directory / "build"),
        "--invocation-key",
        "76" * 32,
    )
    built = artifacts_by_protocol_role(language, _members(build))
    rir = built["rir-semantic-payload"]
    rir_path = directory / "rir.json"
    rir_path.write_text(json.dumps(rir))
    specification = _specification(rir, [1, 2, 3, 4])
    specification_path = directory / "experiment.json"
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
        str(directory / "run"),
        "--invocation-key",
        "77" * 32,
    )
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment), checked
    return candidate, context, built, checked, run, specification_path, rir_path


def test_public_compilation_execution_and_inspection_follow_selected_roles(
    protocol_public,
):
    candidate, context, built, checked, run, _, _ = protocol_public
    artifacts = _members(run)
    assert validate_experiment_artifact_set(checked, artifacts)
    semantic = artifacts_by_protocol_role(context.language_bundle, artifacts)
    samples = semantic["metric-dataset"]["samples"]
    assert {row["metric"]: row["value"] for row in samples} == {
        "selected_count": 2,
        "ordered_value": 1234,
    }
    build_receipt = candidate.directory / "build-receipt.json"
    build_receipt.write_text(candidate.receipts[0]["stdout"])
    explanation = candidate.cli("model", "inspect", str(build_receipt))
    assert explanation == built["model-explanation"]


def test_public_exact_replay_follows_selected_roles(protocol_public):
    candidate, context, _, _, run, specification, rir = protocol_public
    original = candidate.directory / "original-receipt.json"
    original.write_text(json.dumps(run))
    replay = candidate.cli(
        "experiment",
        "replay",
        str(specification),
        "--rir",
        str(rir),
        "--original-experiment-run-artifact-set-receipt",
        str(original),
        "--out",
        str(candidate.directory / "replay"),
        "--invocation-key",
        "78" * 32,
    )
    artifacts = artifacts_by_protocol_role(
        context.language_bundle, _members(replay["artifact_set"])
    )
    assert artifacts["replay-comparison"]["result"] == "matched"


def test_formula_conversion_follows_the_source_schema_role(protocol_public):
    from test_schema2_formula_cli import _quantity_contract

    candidate, _, _, _, _, _, _ = protocol_public
    contract = _quantity_contract("value")
    value_contract = {key: value for key, value in contract.items() if key != "id"}
    request = {
        "schema_version": "2.0.0",
        "package_requirements": ["core.quantity"],
        "module": {
            "id": "main",
            "imports": [
                {"alias": "quantity", "package": "core.quantity", "symbol": "Quantity"}
            ],
        },
        "formula": {
            "id": "identity",
            "parameters": [contract],
            "result": value_contract,
            "body": {
                "nodes": [
                    {
                        "id": "same",
                        "node": "operation-call",
                        "operation": {
                            "package": "core.quantity",
                            "id": "quantity.identity",
                        },
                        "arguments": [
                            {
                                "port": "value",
                                "operand": {"kind": "parameter", "parameter": "value"},
                            }
                        ],
                        "result": value_contract,
                    }
                ],
                "result": {"kind": "local", "local": "same"},
            },
        },
    }
    path = candidate.directory / "formula-render.json"
    path.write_text(json.dumps(request))
    rendered = candidate.cli("formula", "render", str(path))
    assert rendered["expression"] == "let same = identity(value);\nsame"
    assert rendered["body"] == request["formula"]["body"]
    from schema2_formula_conformance_support import admit_pair, parse_canonical

    request["formula"]["expression"] = rendered["expression"]
    assert (
        parse_canonical(
            rendered["expression"], request, candidate.ldb, kernel=candidate.kernel
        )
        == request["formula"]["body"]
    )
    assert admit_pair(request, candidate.ldb, kernel=candidate.kernel)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "unknown", "wrong-category"]
)
def test_protocol_role_admission_requires_one_declared_owner(mutation):
    kernel, language = mutable_authorities()
    trace = next(
        row
        for row in language["language"]["artifact_wire_schemas"]
        if row.get("protocol_role") == "event-trace"
    )
    if mutation == "missing":
        del trace["protocol_role"]
    elif mutation == "duplicate":
        trace["protocol_role"] = "runtime-terminal-audit"
    elif mutation == "unknown":
        trace["protocol_role"] = "invented.responsibility"
    else:
        source = language["language"]["wire_schemas"][0]
        source["protocol_role"], trace["protocol_role"] = (
            trace["protocol_role"],
            source["protocol_role"],
        )
    _reidentify_language_bundle(language)
    assert not isinstance(
        admit_authority_context(kernel, language), AdmittedAuthorityContext
    )
    assert not _consumer_b(kernel, language)["admitted"]


def test_role_free_extension_kinds_remain_open():
    kernel, language = mutable_authorities()
    contracts = language["language"]["artifact_contracts"]
    schemas = language["language"]["artifact_wire_schemas"]
    contract = deepcopy(
        next(row for row in contracts if row["artifact_kind"] == "capability-manifest")
    )
    contract.update(
        artifact_kind="extension.any.kind/~@",
        schema_kind="extension.unrelated.schema",
        identity_domain="extension-payload-v1",
        wire_schema_identity_domain="extension-wire-v1",
    )
    schema = deepcopy(
        next(
            row for row in schemas if row.get("protocol_role") == "capability-manifest"
        )
    )
    del schema["protocol_role"]
    schema["artifact_kind"] = contract["schema_kind"]
    body = schema["schema"]
    body["properties"] = {
        key: value
        for key, value in body["properties"].items()
        if key
        in (
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "content_identity",
        )
    }
    body["properties"]["artifact_kind"]["const"] = contract["artifact_kind"]
    body["properties"]["value"] = {"type": "integer"}
    body["required"] = list(body["properties"])
    contracts.append(contract)
    schemas.append(schema)
    package = next(
        row
        for row in language["language"]["packages"]
        if row["id"] == "standard.schema"
    )
    package["exports"]["artifact_contracts"].append(contract["artifact_kind"])
    package["exports"]["artifact_wire_schemas"].append(schema["artifact_kind"])
    _reidentify_language_bundle(language)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    assert _consumer_b(kernel, language)["admitted"]
    artifact = identified_artifact(
        context.language_bundle, contract["artifact_kind"], {"value": 17}
    )
    assert verify_artifact(artifact, context.language_bundle)


def _reseal(checked, role, value):
    return checked.output_contracts[role].identify(
        {
            key: item
            for key, item in value.items()
            if key
            not in {
                "artifact_kind",
                "artifact_version",
                "wire_schema_identity",
                "content_identity",
            }
        }
    )


def _forged_formula():
    return {
        "evaluation_site_identity": "forged",
        "binding_identity": "forged",
        "formula": {"module": "forged", "id": "forged", "identity": "forged"},
        "operation": {"package": "forged", "id": "forged", "identity": "forged"},
        "slot": "forged",
        "context": {"phase": "event", "frame": "forged"},
        "arguments": [],
        "result": 0,
        "frame_identity": "forged",
        "call_path": "forged",
    }


@pytest.fixture(scope="module")
def protocol_terminal(protocol_public):
    candidate, context, built, _, _, _, rir_path = protocol_public
    rir = built["rir-semantic-payload"]
    specification = _specification(rir, [(1 << 63) - 1, 1])
    path = candidate.directory / "numeric-refusal.json"
    path.write_text(json.dumps(specification))
    candidate.cli("experiment", "check", str(path), "--rir", str(rir_path))
    result = candidate.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        str(rir_path),
        "--out",
        str(candidate.directory / "refusal"),
        "--invocation-key",
        "79" * 32,
        success=False,
    )
    assert result["error"]["diagnostics"][0]["code"] == "runtime.numeric_overflow"
    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir)
    checked = check_experiment_value(specification, program, authority_context=context)
    assert isinstance(checked, CheckedExperiment)
    artifacts = _members(result["error"]["terminal_audit"])
    assert validate_experiment_artifact_set(checked, artifacts)
    return checked, artifacts


def test_renamed_roles_retain_semantic_trace_and_first_refusal_checks(
    protocol_public, protocol_terminal
):
    from gda_balancing.domain.experiment_artifacts import validate_experiment_member

    _, context, _, checked, run, _, _ = protocol_public
    success = artifacts_by_protocol_role(context.language_bundle, _members(run))
    trace = deepcopy(success["event-trace"])
    trace["events"][0]["formula_evaluations"] = [_forged_formula()]
    trace = _reseal(checked, "event-trace", trace)
    assert checked.output_contracts["event-trace"].verify(trace)
    assert not validate_experiment_member(checked, "arbitrary-label", trace)
    assert not validate_experiment_artifact_set(
        checked, {**success, "event-trace": trace}
    )
    refused, raw_terminal = protocol_terminal
    terminal = artifacts_by_protocol_role(context.language_bundle, raw_terminal)
    audit = deepcopy(terminal["runtime-terminal-audit"])
    audit["diagnostic"]["code"] = "runtime.step_limit_exceeded"
    audit["refusing_event"]["reason"] = "runtime.step_limit_exceeded"
    audit = _reseal(refused, "runtime-terminal-audit", audit)
    assert refused.output_contracts["runtime-terminal-audit"].verify(audit)
    assert not validate_experiment_artifact_set(
        refused, {**terminal, "runtime-terminal-audit": audit}
    )
    audit = deepcopy(terminal["runtime-terminal-audit"])
    audit["committed_trace_prefix"] = [deepcopy(trace["events"][0])]
    audit = _reseal(refused, "runtime-terminal-audit", audit)
    assert refused.output_contracts["runtime-terminal-audit"].verify(audit)
    assert not validate_experiment_member(refused, "arbitrary-label", audit)


def test_independent_compiler_and_runtime_consume_renamed_protocols(protocol_public):
    from schema2_runtime_independent_support import (
        reference_runtime_artifacts,
        reference_admits_runtime_artifacts,
    )
    from test_schema2_model_lowerer_conformance import (
        _reference_check_source,
        _reference_semantic_artifacts,
    )

    candidate, context, built, checked, run, _, _ = protocol_public
    reference = _reference_check_source(_source(), candidate.kernel, candidate.ldb)
    assert not isinstance(reference, tuple), reference
    model = _reference_semantic_artifacts(reference)
    assert all(value == built[role] for role, value in model.items())
    rir = model["rir-semantic-payload"]
    independent = reference_runtime_artifacts(reference, rir, checked.value)
    actual = _members(run)
    assert validate_experiment_artifact_set(checked, independent)
    assert reference_admits_runtime_artifacts(reference, rir, checked.value, actual)
    actual = artifacts_by_protocol_role(context.language_bundle, actual)
    assert all(
        value == actual[role]
        for role, value in independent.items()
        if role != "evaluator-capability-manifest"
    )
    assert (
        independent["evaluator-capability-manifest"]["evaluator_build_identity"]
        != actual["evaluator-capability-manifest"]["evaluator_build_identity"]
    )


def test_publication_labels_are_not_protocol_identities(
    protocol_public, protocol_terminal, monkeypatch
):
    from gda_balancing.domain.artifact_set import (
        EXPERIMENT_SUCCESS_ARTIFACT_SET,
        EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET,
        ProtocolArtifactSetMemberSpec,
        label_artifacts,
        resolve_artifact_set,
    )
    from gda_balancing.domain.experiment_artifacts import validate_experiment_member
    from gda_balancing.domain.publication import (
        PublicationMember,
        publish_artifact_set,
        read_authenticated_declared_artifact_set,
        select_publication_contracts,
    )

    candidate, context, _, checked, run, specification, rir = protocol_public
    monkeypatch.setenv(
        "GDA_BALANCING_STORE_DIR", candidate.env["GDA_BALANCING_STORE_DIR"]
    )
    monkeypatch.setenv(
        "GDA_BALANCING_ANCHOR_KEY", candidate.env["GDA_BALANCING_ANCHOR_KEY"]
    )
    for index, (owner, artifacts, canonical_plan) in enumerate(
        (
            (checked, _members(run), EXPERIMENT_SUCCESS_ARTIFACT_SET),
            (*protocol_terminal, EXPERIMENT_RUNTIME_REFUSAL_ARTIFACT_SET),
        )
    ):
        plan = tuple(
            ProtocolArtifactSetMemberSpec(
                member.protocol_role,
                logical_name=f"opaque-{23 - offset * 3}",
                role=member.role,
            )
            for offset, member in enumerate(canonical_plan)
        )
        resolved = resolve_artifact_set(context.language_bundle, plan)
        values = label_artifacts(
            artifacts, resolved, lambda value: value["artifact_kind"]
        )
        members = {
            label: PublicationMember(
                value=value,
                artifact_kind=value["artifact_kind"],
                wire_schema_identity=value["wire_schema_identity"],
                content_identity=value["content_identity"],
            )
            for label, value in values.items()
        }
        receipt = publish_artifact_set(
            members,
            str(candidate.directory / f"relabeled-{index}"),
            f"{80 + index:02x}" * 32,
            "sha256:" + "3" * 64,
            owner.content_identity,
            select_publication_contracts(context.language_bundle),
            resolved,
            lambda name, value: validate_experiment_member(owner, name, value),
            artifact_set_validator=lambda value: validate_experiment_artifact_set(
                owner, value
            ),
        )
        receipt_path = candidate.directory / f"relabeled-receipt-{index}.json"
        receipt_path.write_text(json.dumps(receipt))
        read = read_authenticated_declared_artifact_set(
            str(receipt_path), (canonical_plan,), authority_context=context
        )
        assert read.artifacts == values
        locators = receipt["member_locators"]
        assert isinstance(locators, list)
        assert all(isinstance(row, dict) for row in locators)
        assert [row["logical_name"] for row in locators if isinstance(row, dict)] == [
            member.logical_name for member in plan
        ]
        assert validate_experiment_artifact_set(owner, read.artifacts)
        assert not validate_experiment_artifact_set(
            owner, {**values, "duplicate": deepcopy(next(iter(values.values())))}
        )
        if index == 0:
            result = candidate.cli(
                "experiment",
                "replay",
                str(specification),
                "--rir",
                str(rir),
                "--original-experiment-run-artifact-set-receipt",
                str(receipt_path),
                "--out",
                str(candidate.directory / "relabeled-replay"),
                "--invocation-key",
                "83" * 32,
            )
            replay = artifacts_by_protocol_role(
                context.language_bundle, _members(result["artifact_set"])
            )
            assert replay["replay-comparison"]["result"] == "matched"


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_independent_formula_requires_one_source_schema_role(mutation):
    from schema2_formula_conformance_support import parse_canonical

    kernel, language = _authorities(True)
    definition = next(
        row
        for row in language["language"]["wire_schemas"]
        if row.get("protocol_role") == "model-source-package"
    )
    if mutation == "missing":
        del definition["protocol_role"]
    else:
        duplicate = deepcopy(definition)
        duplicate["artifact_kind"] += ".second"
        language["language"]["wire_schemas"].append(duplicate)
        owner = next(
            package
            for package in language["language"]["packages"]
            if definition["artifact_kind"] in package["exports"]["wire_schemas"]
        )
        owner["exports"]["wire_schemas"].append(duplicate["artifact_kind"])
    _reidentify_language_bundle(language)
    assert not isinstance(
        admit_authority_context(kernel, language), AdmittedAuthorityContext
    )
    assert not _consumer_b(kernel, language)["admitted"]
    with pytest.raises(ValueError, match="no unique Model Source schema"):
        parse_canonical("unread", {}, language, kernel=kernel)
