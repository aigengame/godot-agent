"""Inline Source selectors adapt to the unchanged Kernel Formula operand roles."""

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.model import (
    CheckedModel,
    admit_rir,
    AdmittedRir,
    check_model_source_value,
    compile_checked_model,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_trace_protocol_structure import _authored, _graph, _index


def _definitions(authored, path):
    return [
        row
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == path
        for row in closure["definitions"]
    ]


def _profile(authored):
    return next(
        row
        for row in _definitions(authored, "language.resolution_profiles")
        if row["default"]
    )


def _inline_case(renamed):
    """Change only the actual inline selector, corresponding Schema and Source."""
    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/roguelike-reward-build/model-source.json"
        ).read_text()
    )
    schema = next(
        row["schema"]
        for row in _definitions(authored, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )
    if renamed:
        bodies = schema["properties"]["modules"]["items"]["properties"]["formulas"][
            "items"
        ]["properties"]["body"]["oneOf"]
        inline = next(row for row in bodies if "oneOf" in row)["oneOf"][0]
        assert inline["properties"]["node"]["const"] == "parameter"
        old = next(
            member
            for member, child in inline["properties"].items()
            if child.get("semantic_member") == "parameter"
        )
        new = "input_parameter"
        inline["properties"][new] = inline["properties"].pop(old)
        inline["required"] = [
            new if member == old else member for member in inline["required"]
        ]
        for module in source["modules"]:
            for formula in module.get("formulas", []):
                body = formula["body"]
                if body.get("node") == "parameter":
                    body[new] = body.pop(old)
    jsonschema.Draft202012Validator(schema).validate(source)
    return kernel, authored, source


def _formula_request(source):
    return {
        "schema_version": source["schema_version"],
        "package_requirements": deepcopy(source["package_requirements"]),
        "module": deepcopy(source["modules"][0]),
        "modules": deepcopy(source["modules"]),
        "formula": deepcopy(source["modules"][0]["formulas"][0]),
    }


@pytest.mark.parametrize("renamed", [False, True], ids=["original", "renamed-input"])
def test_public_inline_formula_and_model_follow_schema_roles(tmp_path, renamed):
    kernel, authored, source = _inline_case(renamed)
    graph = _graph(kernel, authored)
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(source)
    assert public.cli("model", "check", str(public.source))["checked"] is True
    receipt = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(tmp_path / "build"),
        "--invocation-key",
        "f4" * 32,
    )
    artifacts = _members(receipt)
    assert len(artifacts) == 8
    rir = artifacts["rir-semantic-payload"]
    assert isinstance(admit_rir(rir, authority_context=context), AdmittedRir)
    request = _formula_request(source)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    rendered = public.cli("formula", "render", str(path))
    assert rendered["body"] == request["formula"]["body"]
    assert rendered["expression"] == "rare_weight"
    del request["formula"]["body"]
    request["formula"]["expression"] = rendered["expression"]
    path.write_text(json.dumps(request))
    parsed = public.cli("formula", "parse", str(path))
    assert parsed["body"] == rendered["body"]
    assert parsed["expression"] == rendered["expression"]
    # The selector affects Source bytes, not the normalized Formula or RIR meaning.
    control_kernel, control_authored, control_source = _inline_case(False)
    control_context = admit_authority_context(
        control_kernel, _index(control_kernel, _graph(control_kernel, control_authored))
    )
    assert isinstance(control_context, AdmittedAuthorityContext)
    control = check_model_source_value(
        control_source, authority_context=control_context
    )
    assert isinstance(control, CheckedModel)
    assert canonical_bytes(rir) == canonical_bytes(
        compile_checked_model(control)["rir-semantic-payload"]
    )
    (tmp_path / "authored.json").write_bytes(canonical_bytes(authored))
    (tmp_path / "source.json").write_bytes(canonical_bytes(source))


def test_public_unsynchronized_inline_source_is_refused_before_resolution(tmp_path):
    kernel, authored, source = _inline_case(True)
    _, _, original = _inline_case(False)
    graph = _graph(kernel, authored)
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(original)
    result = public.cli("model", "check", str(public.source), success=False)
    assert result["error"]["stage"] == "static"
    assert [row["code"] for row in result["error"]["diagnostics"]] == [
        "language.source_contract_mismatch"
    ]
    assert result["error"]["diagnostics"][0]["primary"]["pointer"].startswith(
        "/modules/0/formulas/0/body"
    )
    request = _formula_request(source)
    request["formula"]["body"] = original["modules"][0]["formulas"][0]["body"]
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    refusal = public.cli("formula", "render", str(path), success=False)
    assert refusal["error"]["stage"] == "static"
    assert (
        refusal["error"]["diagnostics"][0]["code"]
        == "language.source_contract_mismatch"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-role",
        "wrong-role",
        "wrong-discriminator",
        "missing-member-role",
        "duplicate-member-role",
        "extra-member-role",
    ],
)
def test_inline_role_refuses_correctly_resealed_invalid_authority(mutation):
    kernel, authored, _ = _inline_case(False)
    schema = next(
        row["schema"]
        for row in _definitions(authored, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )
    bodies = schema["properties"]["modules"]["items"]["properties"]["formulas"][
        "items"
    ]["properties"]["body"]["oneOf"]
    inline = next(row for row in bodies if "oneOf" in row)["oneOf"][0]
    parameter = inline["properties"]["parameter"]
    if mutation == "missing-role":
        del inline["semantic_role"]
    elif mutation == "wrong-role":
        inline["semantic_role"] = "local-operand"
    elif mutation == "wrong-discriminator":
        inline["properties"]["node"]["const"] = "local"
    elif mutation == "missing-member-role":
        del parameter["semantic_member"]
    elif mutation == "duplicate-member-role":
        parameter["semantic_member"] = "node"
    else:
        inline["properties"]["extra"] = {
            "type": "string",
            "semantic_member": "extra",
        }
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert result["admitted"] is False
    assert result["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("condition_contract", "kernel-boolean"),
        ("formula_argument_compatibility", "exact-resolved-contract"),
        ("formula_result_compatibility", "exact-resolved-contract"),
        ("literal_typing", "selected-unique-formal-match"),
        ("operation_argument_compatibility", "exact-operation-formal"),
        ("symbol_resolution", "exact-module-coordinate"),
        ("literal_result_inference", "contextual-anchor"),
        ("infix_parser.algorithm", "shunting-yard"),
    ],
)
def test_retired_notation_singletons_refuse_reentry(member, value):
    kernel, authored, _ = _inline_case(False)
    policy = _profile(authored)["formula_resolution"]["notation_conversion"]
    if member == "infix_parser.algorithm":
        policy["infix_parser"]["algorithm"] = value
    else:
        policy[member] = value
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert result["admitted"] is False
    assert result["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]


@pytest.mark.parametrize(
    "member",
    [
        "binding",
        "declaration",
        "evaluation_site",
        "expression_node",
        "initialization_program",
        "operation",
    ],
)
def test_formula_identity_domains_require_each_actual_hash_parameter(member):
    kernel, authored, _ = _inline_case(False)
    domains = _profile(authored)["formula_resolution"]["identity_domains"]
    assert set(domains) == {
        "binding",
        "declaration",
        "evaluation_site",
        "expression_node",
        "initialization_program",
        "operation",
    }
    del domains[member]
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert result["admitted"] is False
    assert result["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]


@pytest.mark.parametrize("member", ["closure", "unused_domain"])
def test_formula_identity_domains_reject_unread_and_extra_hash_parameters(member):
    kernel, authored, _ = _inline_case(False)
    _profile(authored)["formula_resolution"]["identity_domains"][member] = (
        "formula-closure-v2"
    )
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert result["admitted"] is False
    assert result["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]


@pytest.mark.parametrize("mutation", ["wrong-node", "wrong-operands"])
def test_selected_comparison_inference_still_joins_the_kernel_boolean_node(mutation):
    kernel, authored, _ = _inline_case(False)
    rules = _profile(authored)["formula_resolution"]["notation_conversion"][
        "local_result_inference"
    ]
    rule = next(row for row in rules if row["rule"] == "closed-interval-less-than")
    if mutation == "wrong-node":
        rule["node"] = "add"
    else:
        rule["operand_members"] = ["left", "target"]
    result = _consumer_a(kernel, _graph(kernel, authored))
    assert result["admitted"] is False
    assert result["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]
