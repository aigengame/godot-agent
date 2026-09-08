"""Source parse refusal is a closed Resolution reference, not a generic extension."""

from copy import deepcopy

import pytest

from gda_balancing.domain.authority.admission import _resolution_judgment_is_closed
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_production_support import _consumer_a
from test_bounded_fold_public import _source
from test_current_namespace_public import _PublicCandidate, _members
from test_trace_protocol_structure import _authored, _graph


def _definitions(authored, path):
    return [
        definition
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == path
        for definition in closure["definitions"]
    ]


def _profile(authored):
    return next(
        profile
        for profile in _definitions(authored, "language.resolution_profiles")
        if profile["default"] is True
    )


def _rename_parse_reason(authored, *, rename_diagnostic=False):
    """Rename actual reason, optional diagnostic, and their declared references."""
    old = _profile(authored)["parse_reason"]
    renamed = "review.source-parse-reason"
    reason = next(
        row for row in _definitions(authored, "language.reasons") if row["id"] == old
    )
    diagnostic = reason["diagnostic"]
    new_diagnostic = "review.source_parse_failure" if rename_diagnostic else diagnostic
    reason["id"] = renamed
    reason["diagnostic"] = new_diagnostic
    for profile in _definitions(authored, "language.resolution_profiles"):
        if profile["parse_reason"] == old:
            profile["parse_reason"] = renamed
    for definition in _definitions(authored, "diagnostics"):
        if definition["code"] == diagnostic:
            definition["code"] = new_diagnostic
    for package in authored["packages"]:
        package["exports"]["reasons"] = [
            renamed if value == old else value
            for value in package["exports"]["reasons"]
        ]
        package["exports"]["diagnostics"] = [
            new_diagnostic if value == diagnostic else value
            for value in package["exports"]["diagnostics"]
        ]
    for vector_set in authored["vector_sets"]:
        for vector in vector_set["vector_definitions"]:
            if vector.get("reason") == old:
                vector["reason"] = renamed
                vector["diagnostic"] = new_diagnostic
    return renamed


def test_resolution_parse_reason_has_one_closed_owner_and_no_duplicate_selection_flags():
    kernel, ldb = mutable_authorities()
    profile = _profile(_authored(ldb))
    grammar = kernel["meta_format"]["language_definitions"]["collections"][
        "resolution_profiles"
    ]
    assert profile["parse_reason"]
    assert "parse_reason" in grammar["required_members"]
    assert grammar["field_types"]["parse_reason"] == {"type": "non-empty-string"}
    for member in ("extensions", "dependency_closure", "capability_selection"):
        assert member not in profile
        assert member not in grammar["required_members"]
        assert member not in grammar["field_types"]
    judgment = kernel["meta_format"]["resolution_judgment"]
    assert judgment["parse_reason_stage"] == "parse"
    assert judgment["stage_order"] == ["static", "resolution"]
    operations = {row["id"]: row for row in judgment["operations"]}
    for name in ("close-required-dependencies", "bind-capability-providers"):
        assert operations[name]["law"]["operator"] == "require-match"
        assert operations[name]["law"]["cardinality"] == "exactly-one"
        assert any(row["operation"] == name for row in profile["judgment_chain"])


@pytest.mark.parametrize(
    "mutation",
    [
        "original-wrapper",
        "renamed-wrapper",
        "shadow-wrapper",
        "missing",
        "unknown",
        "wrong-stage",
        "nonstring",
        "dependency_closure",
        "capability_selection",
    ],
)
def test_resolution_parse_reason_rejects_closed_contract_violations(mutation):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    profile = _profile(authored)
    if mutation in {"original-wrapper", "renamed-wrapper"}:
        name = (
            "standard.source-boundary"
            if mutation == "original-wrapper"
            else "opaque.source-boundary"
        )
        profile["extensions"] = {name: {"parse_reason": profile.pop("parse_reason")}}
    elif mutation == "shadow-wrapper":
        profile["extensions"] = {
            "standard.source-boundary": {"parse_reason": profile["parse_reason"]}
        }
    elif mutation == "missing":
        del profile["parse_reason"]
    elif mutation == "unknown":
        profile["parse_reason"] = "missing.reason"
    elif mutation == "wrong-stage":
        profile["parse_reason"] = profile["structural_reason"]
    elif mutation == "nonstring":
        profile["parse_reason"] = 3
    else:
        profile[mutation] = {
            "dependency_closure": "required-transitive",
            "capability_selection": "single-provider",
        }[mutation]
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert result["admitted"] is False
    assert any(
        row[:2] == ("static", "kernel.vector_mismatch") for row in result["diagnostics"]
    )


@pytest.mark.parametrize("stage", [None, "static", "resolution"])
def test_resolution_primitive_cannot_redefine_the_parse_phase(stage):
    kernel, _ = mutable_authorities()
    judgment = deepcopy(kernel["meta_format"]["resolution_judgment"])
    assert _resolution_judgment_is_closed(judgment)
    if stage is None:
        del judgment["parse_reason_stage"]
    else:
        judgment["parse_reason_stage"] = stage
    assert not _resolution_judgment_is_closed(judgment)


@pytest.mark.parametrize(
    "wrapper", ["standard.source-boundary", "opaque.source-boundary"]
)
def test_old_source_boundary_wrapper_refuses_publicly_before_parse(tmp_path, wrapper):
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    profile = _profile(authored)
    profile["extensions"] = {wrapper: {"parse_reason": profile.pop("parse_reason")}}
    public = _PublicCandidate(
        tmp_path / "public", authorities=(kernel, _graph(kernel, authored))
    )
    public.source.write_bytes(b"{")
    result = public.cli("model", "check", str(public.source), success=False)
    assert public.receipts[-1]["returncode"] == 2
    assert result["error"]["stage"] == "static"
    assert any(
        row["code"] == "kernel.vector_mismatch"
        for row in result["error"]["diagnostics"]
    )


def test_public_source_parse_follows_the_declared_reason_and_preserves_valid_rir(
    tmp_path,
):
    rirs = []
    other_refusals = []
    for mode in ("original", "reason-renamed", "diagnostic-renamed"):
        kernel, ldb = mutable_authorities()
        authored = _authored(ldb)
        expected_code = "language.source_parse_failure"
        if mode != "original":
            _rename_parse_reason(
                authored, rename_diagnostic=mode == "diagnostic-renamed"
            )
        if mode == "diagnostic-renamed":
            expected_code = "review.source_parse_failure"
        graph = _graph(kernel, authored)
        admission = _consumer_a(kernel, graph)
        assert admission["admitted"], admission["diagnostics"]
        public = _PublicCandidate(tmp_path / mode, authorities=(kernel, graph))
        public.write_source(_source())
        public.cli("model", "check", str(public.source))
        receipt = public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(public.directory / "build"),
            "--invocation-key",
            "e3" * 32,
        )
        built = _members(receipt)
        assert len(built) == 8
        rirs.append(built["rir-semantic-payload"])
        rir_path = next(
            row["locator"]
            for row in receipt["member_locators"]
            if row["logical_name"] == "rir-semantic-payload"
        )
        invalid = public.directory / "invalid-source.json"
        invalid.write_bytes(b"{")
        expected = {
            "error": {
                "category": "refusal",
                "diagnostics": [
                    {
                        "code": expected_code,
                        "message": "Model Source Package is outside canonical JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
                        "primary": {
                            "content_identity": "unidentified",
                            "kind": "artifact",
                            "pointer": "",
                        },
                        "related": [],
                    }
                ],
                "stage": "parse",
                "truncated": False,
            }
        }
        for command in ("check", "build"):
            args = ["model", command, str(invalid)]
            if command == "build":
                args.extend(
                    [
                        "--out",
                        str(public.directory / "invalid-build"),
                        "--invocation-key",
                        "e4" * 32,
                    ]
                )
            result = public.cli(*args, success=False)
            assert public.receipts[-1]["returncode"] == 2
            assert result == expected
        assert not (public.directory / "invalid-build").exists()
        # These public commands also import their declared refusal catalogs. Each
        # ingress retains its own identity/message while sharing the reason owner.
        refusals = []
        for args in (
            ("formula", "parse", str(invalid)),
            ("formula", "render", str(invalid)),
            ("experiment", "check", str(invalid), "--rir", rir_path),
            ("experiment", "check", str(invalid), "--rir", str(invalid)),
        ):
            result = public.cli(*args, success=False)
            assert public.receipts[-1]["returncode"] == 2
            error = result["error"]
            assert error["category"] == "refusal"
            assert error["stage"] == "parse"
            assert error["truncated"] is False
            assert len(error["diagnostics"]) == 1
            diagnostic = error["diagnostics"][0]
            assert diagnostic["code"] == expected_code
            assert diagnostic["primary"]["pointer"] == ""
            assert diagnostic["related"] == []
            normalized = deepcopy(result)
            normalized["error"]["diagnostics"][0]["code"] = (
                "language.source_parse_failure"
            )
            refusals.append(normalized)
        other_refusals.append(refusals)
    assert rirs[0] == rirs[1] == rirs[2]
    assert other_refusals[0] == other_refusals[1] == other_refusals[2]
