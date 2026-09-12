"""Independent Formula Source adapters, closed policy and Model artifact exchange."""

from copy import deepcopy
import json

import pytest

from gda_balancing.domain.artifacts import artifacts_by_protocol_role, verify_artifact
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model import admit_resolved_model, check_model_source_value
from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_formula_resolution_is_closed,
    _consumer_b_inline_parameter_operand,
    _encoded,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_formula_conformance_support import (
    admit_pair,
    normalize_source_body,
    parse_canonical,
    render_body,
)
from test_current_namespace_public import _PublicCandidate, _members
from test_formula_inline_resolution import _formula_request, _inline_case, _profile
from test_schema2_model_lowerer_conformance import (
    _reference_admits_semantic_artifacts,
    _reference_check_source,
    _reference_semantic_artifacts,
)
from test_trace_protocol_structure import _graph, _index


@pytest.mark.parametrize("renamed", [False, True], ids=["original", "renamed-input"])
def test_independent_inline_model_compilation_exchanges_four_public_artifacts(
    tmp_path, renamed
):
    kernel, authored, source = _inline_case(renamed)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result["diagnostics"]
    index = _index(kernel, graph)
    assert _consumer_b_formula_resolution_is_closed(index, kernel["meta_format"])
    context = admit_authority_context(kernel, index)
    assert isinstance(context, AdmittedAuthorityContext)
    program_source = deepcopy(source)
    for module in program_source["modules"]:
        for formula in module.get("formulas", []):
            formula["body"] = normalize_source_body(
                formula["body"], index, kernel=kernel
            )
    # A bare parameter expression parses to the inline Source representation.
    # Replacing only its authored body with an explicit program is not a canonical pair.
    program_checked = _reference_check_source(program_source, kernel, index)
    program_a = check_model_source_value(program_source, authority_context=context)
    reason = _profile(authored)["formula_resolution"]["refusal_reasons"][
        "notation-mismatch"
    ]
    code = next(
        row["diagnostic"] for row in index["language"]["reasons"] if row["id"] == reason
    )
    expected = ((code, "/modules/0/formulas/0/expression"),)
    assert program_checked == expected
    assert isinstance(program_a, Schema2RefusalReport)
    assert (
        tuple(
            (diagnostic.code, diagnostic.primary.model_dump()["pointer"])
            for diagnostic in program_a.diagnostics
        )
        == expected
    )
    checked = _reference_check_source(source, kernel, index)
    assert isinstance(checked, ModelSourceContext), checked
    reference = _reference_semantic_artifacts(checked)
    assert len(reference) == 4

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
                "8d" * 32,
            )
        ),
    )
    assert len(built) == 8
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

    request = _formula_request(source)
    normalized = normalize_source_body(request["formula"]["body"], index, kernel=kernel)
    kind, reference_member = _consumer_b_inline_parameter_operand(kernel["meta_format"])
    source_member = _profile(authored)["formula_resolution"][
        "inline_body_normalizations"
    ][0]["parameter_member"]
    assert normalized == {
        "nodes": [],
        "result": {
            "kind": kind,
            reference_member: request["formula"]["body"][source_member],
        },
    }
    expression = render_body(request["formula"]["body"], request, index, kernel=kernel)
    assert admit_pair(request, index, kernel=kernel)
    parse_request = deepcopy(request)
    del parse_request["formula"]["body"]
    independently_parsed = parse_canonical(
        expression, parse_request, index, kernel=kernel
    )
    assert independently_parsed == request["formula"]["body"]
    request_path = public.directory / "formula-request.json"
    request_path.write_text(json.dumps(parse_request))
    parsed = public.cli("formula", "parse", str(request_path))
    assert parsed["body"] == independently_parsed
    assert parsed["expression"] == expression
    parse_request["formula"]["body"] = independently_parsed
    request_path.write_text(json.dumps(parse_request))
    rendered = public.cli("formula", "render", str(request_path))
    assert rendered["body"] == independently_parsed
    assert rendered["expression"] == expression

    for role, value in reference.items():
        (public.directory / f"independent-{role}.json").write_bytes(_encoded(value))
    (public.directory / "independent-comparison.json").write_text(
        json.dumps(
            {
                "source_member": source_member,
                "normalized_body": normalized,
                "expression": expression,
                "four_artifact_roles": list(reference),
                "four_artifact_canonical_equal": True,
                "mutual_admission": True,
                "noncanonical_program_control_refusal": list(expected),
                "noncanonical_program_control_A_B_equal": True,
            },
            indent=2,
        )
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "old-node",
        "old-result-kind",
        "missing-selector",
        "extra-selector",
        "empty-selector",
        "unknown-selector",
        "discriminator-collision",
        "missing-normalization",
        "extra-normalization",
    ],
)
def test_independent_inline_selector_closes_real_schema_addresses(mutation):
    kernel, authored, _source = _inline_case(False)
    rows = _profile(authored)["formula_resolution"]["inline_body_normalizations"]
    if mutation == "old-node":
        rows[0]["node"] = "parameter"
    elif mutation == "old-result-kind":
        rows[0]["result_kind"] = "parameter"
    elif mutation == "missing-selector":
        del rows[0]["parameter_member"]
    elif mutation == "extra-selector":
        rows[0]["extra"] = "parameter"
    elif mutation == "empty-selector":
        rows[0]["parameter_member"] = ""
    elif mutation == "unknown-selector":
        rows[0]["parameter_member"] = "missing_parameter"
    elif mutation == "discriminator-collision":
        rows[0]["parameter_member"] = "node"
    elif mutation == "missing-normalization":
        rows.clear()
    else:
        rows.append(deepcopy(rows[0]))
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
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
        (
            "operation_result_source",
            {"kind": "local", "source_member": "source", "name_member": "name"},
        ),
        (
            "result_source",
            {"kind": "local", "source_member": "source", "name_member": "name"},
        ),
        ("infix_parser.algorithm", "shunting-yard"),
        ("identity_domains.closure", "formula-closure-v2"),
    ],
)
def test_independent_formula_consumer_refuses_retired_policy_reentry(member, value):
    kernel, authored, source = _inline_case(False)
    formula = _profile(authored)["formula_resolution"]
    conversion = formula["notation_conversion"]
    if member == "identity_domains.closure":
        formula["identity_domains"]["closure"] = value
    elif member == "infix_parser.algorithm":
        conversion["infix_parser"]["algorithm"] = value
    else:
        conversion[member] = value
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"] is False
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]
    # Standalone B Formula entry also refuses this closed policy, rather than
    # inheriting a fingerprint failure from the separate authority judgment.
    index = _index(kernel, graph)
    request = _formula_request(source)
    with pytest.raises(ValueError, match="Formula policy"):
        parse_canonical(request["formula"]["expression"], request, index, kernel=kernel)


def test_independent_formula_negative_entries_reach_their_actual_judgments():
    kernel, authored, source = _inline_case(False)
    index = _index(kernel, _graph(kernel, authored))
    request = _formula_request(source)
    assert admit_pair(request, index, kernel=kernel)
    expression = request["formula"]["expression"]
    wrong_result = deepcopy(request)
    wrong_result["formula"]["result"]["domain"] = {"minimum": 1, "maximum": 1}
    with pytest.raises(ValueError, match="result contract is incompatible"):
        parse_canonical(expression, wrong_result, index, kernel=kernel)
    wrong_context = deepcopy(request)
    wrong_context["schema_version"] = "unavailable"
    with pytest.raises(ValueError, match="source schema version is unavailable"):
        parse_canonical(expression, wrong_context, index, kernel=kernel)
    grammar = next(
        row["formula_grammar"]
        for row in index["language"]["wire_schemas"]
        if row.get("protocol_role") == "model-source-package"
    )
    with pytest.raises(ValueError, match="expression exceeds its byte bound"):
        parse_canonical(
            "x" * (grammar["max_expression_bytes"] + 1), request, index, kernel=kernel
        )


@pytest.mark.parametrize("mutation", ["wrong-node", "wrong-operands"])
def test_independent_comparison_inference_keeps_the_kernel_boolean_owner(mutation):
    kernel, authored, _source = _inline_case(False)
    conversion = _profile(authored)["formula_resolution"]["notation_conversion"]
    assert "condition_contract" not in conversion
    assert "operation_result_source" not in conversion
    rule = next(
        row
        for row in conversion["local_result_inference"]
        if row["rule"] == "closed-interval-less-than"
    )
    if mutation == "wrong-node":
        rule["node"] = "add"
    else:
        rule["operand_members"] = ["left", "target"]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"] is False
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]


def test_independent_model_rejects_unsynchronized_inline_source():
    kernel, authored, source = _inline_case(True)
    _kernel, _authored, old_source = _inline_case(False)
    index = _index(kernel, _graph(kernel, authored))
    request = _formula_request(source)
    request["formula"]["body"] = _formula_request(old_source)["formula"]["body"]
    with pytest.raises(ValueError, match="inline Formula body is malformed"):
        normalize_source_body(request["formula"]["body"], index, kernel=kernel)
    assert not admit_pair(request, index, kernel=kernel)
    result = _reference_check_source(old_source, kernel, index)
    assert isinstance(result, tuple) and result
    assert all(
        code == "language.source_contract_mismatch"
        and pointer.startswith("/modules/")
        and "/body" in pointer
        for code, pointer in result
    )


def test_independent_inline_projection_reads_the_kernel_reference_and_detaches():
    kernel, authored, source = _inline_case(False)
    index = _index(kernel, _graph(kernel, authored))
    body = _formula_request(source)["formula"]["body"]
    normal = normalize_source_body(body, index, kernel=kernel)
    changed = deepcopy(kernel)
    law = changed["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "rir_structure"
    ]["containers"]["formula_parameter_operand"]
    _kind, reference = _consumer_b_inline_parameter_operand(kernel["meta_format"])
    law["field_types"]["kernel_parameter_ref"] = law["field_types"].pop(reference)
    law["required_members"] = [
        "kernel_parameter_ref" if name == reference else name
        for name in law["required_members"]
    ]
    projected = normalize_source_body(body, index, kernel=changed)
    assert projected["result"]["kernel_parameter_ref"] == normal["result"][reference]
    assert reference not in projected["result"]
    # This is a pure law-projection witness, not admission of a different Kernel.
    normal["result"][reference] = "changed-output"
    assert body["parameter"] != "changed-output"
