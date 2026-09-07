"""Experiment ingress projects diagnostics from the declared reason identity."""

from copy import deepcopy
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from starlette.types import Message, Scope

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.diagnostics import Schema2RefusalReport, reason_by_id
from gda_balancing.domain.experiment import check_experiment, check_experiment_value
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
    admit_rir,
)
from test_schema2_model_cli import _reidentify_language_bundle


_EXAMPLE = Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast"


def _remap_context(reason_id: str, other_id: str) -> AdmittedAuthorityContext:
    kernel, language_bundle = packaged_authority_context().mutable_pair()
    left = reason_by_id(language_bundle, reason_id)
    right = reason_by_id(language_bundle, other_id)
    assert left["stage"] == right["stage"]
    replacements = {
        left["diagnostic"]: right["diagnostic"],
        right["diagnostic"]: left["diagnostic"],
    }
    left["diagnostic"], right["diagnostic"] = right["diagnostic"], left["diagnostic"]
    for vector in language_bundle["vectors"]:
        if vector.get("reason") in {reason_id, other_id}:
            vector["diagnostic"] = replacements[vector["diagnostic"]]
    _reidentify_language_bundle(language_bundle)
    context = admit_authority_context(kernel, language_bundle)
    assert isinstance(context, AdmittedAuthorityContext), context
    return context


def _admitted_example(context: AdmittedAuthorityContext):
    source = json.loads((_EXAMPLE / "model-source.json").read_bytes())
    model = check_model_source_value(source, authority_context=context)
    assert isinstance(model, CheckedModel), model
    artifacts = compile_checked_model(model)
    assert len(artifacts) == 8
    program = admit_rir(artifacts["rir-semantic-payload"], authority_context=context)
    value = json.loads((_EXAMPLE / "experiment.json").read_bytes())
    value["model"] = {
        "rir_semantic_identity": artifacts["rir-semantic-payload"]["semantic_identity"]
    }
    return program, value, artifacts


def _envelope(reason: dict[str, Any], identity: str, pointer: str, message: str):
    return {
        "stage": reason["stage"],
        "variant": None,
        "diagnostics": [
            {
                "code": reason["diagnostic"],
                "message": message,
                "primary": {
                    "kind": "artifact",
                    "content_identity": identity,
                    "pointer": pointer,
                },
                "related": [],
            }
        ],
        "truncated": False,
        "terminal_audit": None,
    }


@pytest.mark.parametrize(
    "case,reason_id,other_id",
    [
        (
            "numeric",
            "quantity.reason.invalid-domain",
            "structured.reason.type-mismatch",
        ),
        (
            "schema",
            "model.reason.source-contract-mismatch",
            "quantity.reason.invalid-domain",
        ),
        (
            "parse-file",
            "model.reason.source-parse-failure",
            "formula.reason.notation-parse-failure",
        ),
        (
            "parse-value",
            "model.reason.source-parse-failure",
            "formula.reason.notation-parse-failure",
        ),
        (
            "resolution",
            "model.reason.resolution-binding-mismatch",
            "model.reason.resolved-authority-mismatch",
        ),
    ],
)
def test_legal_ingress_reason_mapping_preserves_the_complete_refusal(
    case: str, reason_id: str, other_id: str, tmp_path: Path
):
    observations = []
    rir_identities = []
    for context in (packaged_authority_context(), _remap_context(reason_id, other_id)):
        program, value, artifacts = _admitted_example(context)
        rir_identities.append(artifacts["rir-semantic-payload"]["semantic_identity"])
        reason = reason_by_id(context.language_bundle, reason_id)
        if case == "numeric":
            assignment = value["scenarios"][0]["assignments"][0]
            declaration = next(
                row
                for row in cast(
                    list[dict[str, Any]],
                    artifacts["rir-semantic-payload"]["declarations"],
                )
                if row["resolved_symbol"] == assignment["target"]
            )
            assignment["value"] = declaration["domain"]["maximum"] + 1
            pointer = "/scenarios/0/assignments/0/value"
            message = "Scenario assignment does not match its declared value"
        elif case == "schema":
            del value["id"]
            pointer = "/id"
            message = "'id' is a required property"
        elif case.startswith("parse"):
            pointer = ""
            message = "Experiment Specification is not canonical JSON data"
        else:
            value["runtime"]["profile"] = "unknown-profile"
            pointer = "/runtime/profile"
            message = "Experiment Runtime profile is absent from the selected RIR"
        if case == "parse-file":
            raw = b"{"
            path = tmp_path / "malformed.json"
            path.write_bytes(raw)
            identity = "sha256:" + hashlib.sha256(raw).hexdigest()
            refusal = check_experiment(str(path), program, authority_context=context)
        else:
            if case == "parse-value":
                value = {"invalid": float("nan")}
                identity = "unidentified"
            else:
                identity = content_identity(
                    "experiment-specification-v2", cast(JsonValue, value)
                )
            refusal = check_experiment_value(value, program, authority_context=context)
        assert isinstance(refusal, Schema2RefusalReport), refusal
        observations.append(
            (
                refusal.model_dump(mode="json"),
                _envelope(reason, identity, pointer, message),
            )
        )
        if case == "numeric":
            # These are input-admission reasons, not numeric execution dependencies.
            selected = cast(
                dict[str, Any], artifacts["rir-semantic-payload"]["selected_semantics"]
            )
            assert {reason_id, other_id}.isdisjoint(
                row["definition"]["id"] for row in selected["diagnostic_reasons"]
            )
    for observed, expected in observations:
        assert observed == expected
    if case == "numeric":
        assert rir_identities[0] == rir_identities[1]
    assert (
        observations[0][0]["diagnostics"][0]["code"]
        != observations[1][0]["diagnostics"][0]["code"]
    )


def test_unresolved_root_event_reference_uses_its_declared_resolution_stage():
    context = packaged_authority_context()
    program, value, _artifacts = _admitted_example(context)
    first_root = value["scenarios"][0]["event_plan"][0]
    first_root["entrypoint"] = "combat.player-attacks-enemy-and-cancels-counterattack"
    first_root["event_references"] = [
        {"name": "counterattack", "root_event_ref": "absent-root"}
    ]
    refusal = check_experiment_value(value, program, authority_context=context)
    assert isinstance(refusal, Schema2RefusalReport), refusal
    assert refusal.model_dump(mode="json") == _envelope(
        reason_by_id(
            context.language_bundle, "model.reason.resolution-binding-mismatch"
        ),
        content_identity("experiment-specification-v2", cast(JsonValue, value)),
        "/scenarios/0/event_plan/0/event_references/0/root_event_ref",
        "Event reference does not resolve to an admitted root Event in the same Scenario",
    )


@pytest.mark.parametrize("from_file", [False, True])
def test_experiment_ingress_size_refusal_preserves_observed_identity(
    from_file: bool, tmp_path: Path
):
    context = packaged_authority_context()
    program, _value, _artifacts = _admitted_example(context)
    value = {"padding": "x" * context.language_bundle["resources"]["max_source_bytes"]}
    raw = canonical_bytes(cast(JsonValue, value))
    if from_file:
        path = tmp_path / "oversized.json"
        path.write_bytes(raw)
        refusal = check_experiment(str(path), program, authority_context=context)
    else:
        refusal = check_experiment_value(
            deepcopy(value), program, authority_context=context
        )
    assert isinstance(refusal, Schema2RefusalReport), refusal
    assert refusal.model_dump(mode="json") == _envelope(
        reason_by_id(context.language_bundle, "model.reason.source-too-large"),
        "sha256:" + hashlib.sha256(raw).hexdigest(),
        "",
        "Experiment Specification exceeds the admitted ingress bound",
    )


def test_http_session_creation_emits_the_admitted_numeric_reason(monkeypatch):
    import gda_balancing.domain.model._checking as model_checking
    from gda_balancing.interfaces.http.api_v1 import create_api_v1

    context = _remap_context(
        "quantity.reason.invalid-domain", "structured.reason.type-mismatch"
    )
    _program, value, artifacts = _admitted_example(context)
    assignment = value["scenarios"][0]["assignments"][0]
    declaration = next(
        row
        for row in cast(
            list[dict[str, Any]], artifacts["rir-semantic-payload"]["declarations"]
        )
        if row["resolved_symbol"] == assignment["target"]
    )
    assignment["value"] = declaration["domain"]["maximum"] + 1
    # Supply the legal installed authority at Model ingress; session creation
    # still runs actual Model compilation, program admission and Experiment check.
    monkeypatch.setattr(model_checking, "packaged_authority_context", lambda: context)
    app = create_api_v1()
    raw = json.dumps(
        {
            "model_source": json.loads((_EXAMPLE / "model-source.json").read_bytes()),
            "experiment_specification": value,
        }
    ).encode()
    messages: list[Message] = []

    async def request():
        async def receive() -> Message:
            return {"type": "http.request", "body": raw, "more_body": False}

        async def send(message: Message):
            messages.append(message)

        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "http",
            "method": "POST",
            "path": "/v1/execution-sessions",
            "raw_path": b"/v1/execution-sessions",
            "root_path": "",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw)).encode()),
            ],
            "client": ("127.0.0.1", 9999),
            "server": ("127.0.0.1", 8000),
        }
        await app(scope, receive, send)

    asyncio.run(request())
    assert (
        next(row["status"] for row in messages if row["type"] == "http.response.start")
        == 200
    )
    body = json.loads(
        b"".join(
            row.get("body", b"")
            for row in messages
            if row["type"] == "http.response.body"
        )
    )
    expected = _envelope(
        reason_by_id(context.language_bundle, "quantity.reason.invalid-domain"),
        content_identity("experiment-specification-v2", cast(JsonValue, value)),
        "/scenarios/0/assignments/0/value",
        "Scenario assignment does not match its declared value",
    )
    assert body == {"outcome": "refusal", "refusal": expected}
