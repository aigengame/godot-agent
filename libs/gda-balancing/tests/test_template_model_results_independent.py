"""Independent Model results for the existing Template semantic interpreter.

This does not turn that interpreter into a complete Template member wire reader.
The two changed coordinate-bearing member schemas are checked explicitly here.
"""

from copy import deepcopy
from dataclasses import replace
import json

from jsonschema import Draft202012Validator
import pytest

from conftest import _run
from gda_balancing.domain import model
from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.model import CheckedModel
from gda_balancing.domain.model._resolution import ModelSourceContext
from gda_balancing.interfaces.cli.template_catalog import (
    TEMPLATE_GET,
    template_get_handler,
)
from gda_balancing.interfaces.cli.template_instantiation import (
    TEMPLATE_INSTANTIATE,
    template_instantiate_handler,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_template_admission_is_closed,
    _encoded,
)
from schema2_bootstrap_production_support import _consumer_a
from test_bounded_fold_public import _source as _structured_source
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    _reference_resolved_symbols,
)
import test_schema2_template_cli as template_reference
from test_schema2_template_cli import (
    _reference_primitive_is_supported,
    _reference_template_admission,
    _reference_template_model_results,
)
from test_template_model_results import _model_primitive, _payload, _release_case
from test_trace_protocol_structure import _authored, _graph


def test_independent_template_result_origins_and_members_are_closed():
    kernel, index = mutable_authorities()
    release = _release_case(packaged_authority_context())
    assert _consumer_b_template_admission_is_closed(kernel["meta_format"], index)
    primitive = _model_primitive(kernel)
    assert _reference_primitive_is_supported(primitive)
    for mutation in (
        "old-only",
        "old-and-new",
        "missing-results",
        "missing-result",
        "extra-result",
        "unknown-origin",
        "swapped-origins",
        "extra-origin-field",
    ):
        candidate = deepcopy(kernel)
        changed = _model_primitive(candidate)
        if mutation == "old-only":
            changed["result_members"] = list(changed.pop("results"))
        elif mutation == "old-and-new":
            changed["result_members"] = list(changed["results"])
        elif mutation == "missing-results":
            del changed["results"]
        elif mutation == "missing-result":
            del changed["results"]["source_symbols"]
        elif mutation == "extra-result":
            changed["results"]["opaque"] = {"origin": "admitted-namespace-selection"}
        elif mutation == "unknown-origin":
            changed["results"]["source_symbols"]["origin"] = "authored-source"
        elif mutation == "swapped-origins":
            (
                changed["results"]["source_symbols"],
                changed["results"]["resolved_packages"],
            ) = (
                changed["results"]["resolved_packages"],
                changed["results"]["source_symbols"],
            )
        else:
            changed["results"]["source_symbols"]["schema"] = {}
        # These actual interpreter checks run without the Kernel identity gate.
        assert not _reference_primitive_is_supported(changed), mutation
        assert not _consumer_b_template_admission_is_closed(
            candidate["meta_format"], index
        ), mutation
        assert _reference_template_admission(release, candidate, index) == (
            False,
            "language.source_contract_mismatch",
        ), mutation


@pytest.mark.parametrize("structured", [False, True], ids=["quantity", "nominal"])
def test_independent_model_results_copy_admitted_inputs_and_every_fact_field(
    monkeypatch, structured
):
    context = packaged_authority_context()
    source = (
        _structured_source()
        if structured
        else _payload(_release_case(context), "model-source-package")
    )
    actual_a = model.check_model_source_value(source, authority_context=context)
    assert isinstance(actual_a, CheckedModel)
    expected = model.checked_model_template_facts(actual_a)

    def no_shared_model_result(*_args, **_kwargs):
        pytest.fail("B Model judgment/results must not use the A Model facade")

    with monkeypatch.context() as isolated:
        isolated.setattr(model, "check_model_source_value", no_shared_model_result)
        isolated.setattr(model, "checked_model_template_facts", no_shared_model_result)
        checked = _reference_check_source(
            source, context.kernel, context.language_bundle
        )
        assert isinstance(checked, ModelSourceContext)
        primitive = _model_primitive(context.kernel)
        actual = _reference_template_model_results(checked, primitive["results"])
    assert _encoded(actual) == canonical_bytes(expected)
    assert actual["root_requirements"] == source["package_requirements"]
    assert actual["resolved_packages"] == [
        package.namespace for package in checked.namespace_selection.packages
    ]
    fields = [row for row, _pointer in _reference_resolved_symbols(checked)]
    assert _encoded(actual["source_symbols"]) == _encoded(fields)
    assert all("id" not in row for row in fields)
    if structured:
        nominal = [
            row for row in fields if row.get("value_kind") == "nominal-structured"
        ]
        assert nominal and all("domain" not in row for row in nominal)
    before = _encoded(
        deepcopy([checked.source, checked.kernel, checked.language_bundle])
    )
    actual["source_symbols"][0]["resolved_symbol"]["name"] = "changed-output"
    actual["root_requirements"].clear()
    actual["resolved_packages"].clear()
    assert (
        _encoded(deepcopy([checked.source, checked.kernel, checked.language_bundle]))
        == before
    )
    assert _encoded(
        _reference_template_model_results(checked, primitive["results"])
    ) == (canonical_bytes(expected))


@pytest.mark.parametrize(
    "collision", [False, True], ids=["minimal", "dotted-coordinates"]
)
def test_independent_coordinate_results_consume_actual_get_and_instantiation(
    tmp_path, monkeypatch, collision
):
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "d7" * 32)
    kernel, index = mutable_authorities()
    graph = _graph(kernel, _authored(index))
    assert all(
        consumer(kernel, graph)["admitted"] for consumer in (_consumer_a, _consumer_b)
    )
    context = packaged_authority_context()
    release = _release_case(context, collision=collision)
    before = canonical_bytes(release)
    release_id = release["id"]
    assert isinstance(release_id, str)

    def no_shared_model_judgment(*_args, **_kwargs):
        pytest.fail("B Template semantics must not call A Model judgment/results")

    with monkeypatch.context() as isolated:
        isolated.setattr(
            template_reference,
            "check_model_source_value",
            no_shared_model_judgment,
            raising=False,
        )
        isolated.setattr(
            template_reference,
            "checked_model_template_facts",
            no_shared_model_judgment,
            raising=False,
        )
        assert _reference_template_admission(release, kernel, index) == (True, None)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _ctx: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    code, stdout, stderr = _run(
        ["template", "get", "--id", release_id], registry=(descriptor,)
    )
    observations = [
        {"command": "get", "exit": code, "stdout": stdout, "stderr": stderr}
    ]
    assert (code, stderr) == (0, "")
    public_release = json.loads(stdout)
    assert canonical_bytes(public_release) == before
    assert _reference_template_admission(public_release, kernel, index) == (True, None)
    source = _payload(public_release, "model-source-package")
    checked = _reference_check_source(source, kernel, index)
    assert isinstance(checked, ModelSourceContext)
    results = _reference_template_model_results(
        checked, _model_primitive(kernel)["results"]
    )
    coordinates = [row["resolved_symbol"] for row in results["source_symbols"]]
    if collision:
        assert len({canonical_bytes(row) for row in coordinates}) == 2
        assert len({row["module"] + "." + row["name"] for row in coordinates}) == 1
    descriptor = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(
            lambda _ctx: deepcopy(release), authority_context_provider=lambda: context
        ),
    )
    output = tmp_path / "instance.json"
    code, stdout, stderr = _run(
        [
            "template",
            "instantiate",
            "--id",
            release_id,
            "--package-id",
            "example.b-instance",
            "--out",
            str(output),
            "--invocation-key",
            "a9" * 32,
        ],
        registry=(descriptor,),
    )
    observations.append(
        {"command": "instantiate", "exit": code, "stdout": stdout, "stderr": stderr}
    )
    (tmp_path / "public-receipt.json").write_text(json.dumps(observations, indent=2))
    assert (code, stderr) == (0, "")
    instance = json.loads(output.read_bytes())
    instance_checked = _reference_check_source(instance, kernel, index)
    assert isinstance(instance_checked, ModelSourceContext)
    instance_fields = _reference_template_model_results(
        instance_checked, _model_primitive(kernel)["results"]
    )["source_symbols"]
    assert all(
        row["resolved_symbol"]["model"] == "example.b-instance"
        for row in instance_fields
    )
    assert [
        (row["resolved_symbol"]["module"], row["resolved_symbol"]["name"])
        for row in instance_fields
    ] == [(row["module"], row["name"]) for row in coordinates]
    assert canonical_bytes(release) == before


@pytest.mark.parametrize(
    "mutation", ["unknown-coordinate", "wrong-model", "wrong-interval", "old-string"]
)
def test_independent_coordinate_queries_refuse_invalid_selected_targets(mutation):
    context = packaged_authority_context()
    release = _release_case(context, collision=True, mutation=mutation)
    assert _reference_template_admission(
        release, context.kernel, context.language_bundle
    ) == (False, "language.source_contract_mismatch")
    # Explicitly check only the two changed member wire schemas, with their actual
    # admitted member-role bindings. The semantic reader above is not full wire admission.
    profile = context.language_bundle["language"]["template_admission_profiles"][0]
    for kind in ("template-defaults", "golden-scenario"):
        role = next(
            row for row in profile["member_roles"] if row["member_kind"] == kind
        )
        schema = next(
            row["schema"]
            for collection in ("wire_schemas", "artifact_wire_schemas")
            for row in context.language_bundle["language"][collection]
            if row["artifact_kind"] == role["member_kind"]
        )
        errors = list(Draft202012Validator(schema).iter_errors(_payload(release, kind)))
        if mutation == "old-string":
            assert len(errors) == 1
            assert errors[0].validator == "type"
            assert list(errors[0].path)[-1] == "symbol"
        else:
            assert not errors
