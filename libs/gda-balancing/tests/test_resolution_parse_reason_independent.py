"""Source parse reasons close as actual Resolution references before byte parsing."""

from copy import deepcopy
import json

import pytest

from gda_balancing.domain.artifacts import artifacts_by_protocol_role, verify_artifact
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.model import admit_resolved_model
from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_resolution_contract_is_closed,
    _encoded,
)
from schema2_bootstrap_production_support import _consumer_a
from test_bounded_fold_public import _source
from test_current_namespace_public import _PublicCandidate, _members
from test_resolution_parse_reason import _profile, _rename_parse_reason
from test_schema2_model_lowerer_conformance import (
    _reference_admits_semantic_artifacts,
    _reference_check_source,
    _reference_semantic_artifacts,
)
from test_trace_protocol_structure import _authored, _graph, _index


@pytest.mark.parametrize(
    "mutation",
    [
        "old-wrapper",
        "wrapper-reentry",
        "empty-wrapper",
        "renamed-wrapper",
        "dependency-closure",
        "capability-selection",
        "missing-reason",
        "unknown-reason",
        "wrong-stage",
    ],
)
def test_resolution_parse_reference_refuses_invalid_correctly_resealed_authority(
    mutation,
):
    kernel, index = mutable_authorities()
    authored = _authored(index)
    profile = _profile(authored)
    if mutation in {"old-wrapper", "wrapper-reentry", "renamed-wrapper"}:
        wrapper = (
            "opaque.source-boundary"
            if mutation == "renamed-wrapper"
            else "standard.source-boundary"
        )
        profile["extensions"] = {wrapper: {"parse_reason": profile["parse_reason"]}}
        if mutation == "old-wrapper":
            del profile["parse_reason"]
    elif mutation == "empty-wrapper":
        profile["extensions"] = {}
    elif mutation == "dependency-closure":
        profile["dependency_closure"] = "required-transitive"
    elif mutation == "capability-selection":
        profile["capability_selection"] = "single-provider"
    elif mutation == "missing-reason":
        del profile["parse_reason"]
    elif mutation == "unknown-reason":
        profile["parse_reason"] = "missing.parse.reason"
    else:
        profile["parse_reason"] = next(
            reason["id"]
            for reason in index["language"]["reasons"]
            if reason["stage"]
            != kernel["meta_format"]["resolution_judgment"]["parse_reason_stage"]
        )
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]
        assert not result["admitted"]


def test_resolution_parse_stage_has_one_supported_primitive_owner():
    kernel, _index_value = mutable_authorities()
    law = kernel["meta_format"]["resolution_judgment"]
    assert _consumer_b_resolution_contract_is_closed(law)
    for replacement in [None, "static"]:
        changed = deepcopy(law)
        if replacement is None:
            del changed["parse_reason_stage"]
        else:
            changed["parse_reason_stage"] = replacement
        assert not _consumer_b_resolution_contract_is_closed(changed)


@pytest.mark.parametrize("renamed", [False, True], ids=["original", "renamed-reason"])
def test_parse_reason_public_boundary_matches_independently_admitted_owner(
    tmp_path, renamed
):
    kernel, index = mutable_authorities()
    authored = _authored(index)
    if renamed:
        _rename_parse_reason(authored)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result["diagnostics"]
    index = _index(kernel, graph)
    context = admit_authority_context(kernel, index)
    assert isinstance(context, AdmittedAuthorityContext), context
    profile = _profile(authored)
    reason = next(
        row
        for row in index["language"]["reasons"]
        if row["id"] == profile["parse_reason"]
    )
    stage = kernel["meta_format"]["resolution_judgment"]["parse_reason_stage"]
    assert reason["stage"] == stage
    source = _source()
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(source)
    public.cli("model", "check", str(public.source))
    built = artifacts_by_protocol_role(
        index,
        _members(
            public.cli(
                "model",
                "build",
                str(public.source),
                "--out",
                str(public.directory / "build"),
                "--invocation-key",
                "e4" * 32,
            )
        ),
    )
    assert len(built) == 8
    checked = _reference_check_source(source, kernel, index)
    assert isinstance(checked, ModelSourceContext), checked
    reference = _reference_semantic_artifacts(checked)
    assert len(reference) == 4
    assert all(
        _encoded(built[role]) == _encoded(value) for role, value in reference.items()
    )
    assert _reference_admits_semantic_artifacts(built, checked)
    assert all(verify_artifact(value, index) for value in reference.values())
    assert admit_resolved_model(
        {
            role: reference[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted
    bad = public.directory / "malformed-source.json"
    bad.write_bytes(b"{")
    for command in ["check", "build"]:
        arguments = ["model", command, str(bad)]
        if command == "build":
            arguments += [
                "--out",
                str(public.directory / "invalid-build"),
                "--invocation-key",
                "e5" * 32,
            ]
        output = public.cli(*arguments, success=False)
        assert public.receipts[-1]["returncode"] == 2
        assert output["error"]["stage"] == stage
        assert output["error"]["category"] == "refusal"
        assert output["error"]["truncated"] is False
        (diagnostic,) = output["error"]["diagnostics"]
        assert diagnostic["code"] == reason["diagnostic"]
        assert diagnostic["primary"] == {
            "content_identity": "unidentified",
            "kind": "artifact",
            "pointer": "",
        }
    (public.directory / "independent-comparison.json").write_text(
        json.dumps(
            {
                "parse_reason": reason["id"],
                "diagnostic": reason["diagnostic"],
                "stage": stage,
                "four_artifact_identities": {
                    role: value["content_identity"] for role, value in reference.items()
                },
                "parse_scope": "Existing public byte parser; B independently admits its actual reason and phase owner, not a second byte parser.",
            },
            indent=2,
        )
        + "\n"
    )
