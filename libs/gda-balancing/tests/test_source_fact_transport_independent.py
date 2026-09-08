"""Independent Source transport closes all initial Facts before applying rules."""

from copy import deepcopy

import jsonschema
import pytest

from gda_balancing.domain.authority.vector_validation import _fact_is_closed
from gda_balancing.domain.model import CheckedModel, check_model_source_value
from gda_balancing.domain.model._compilation import lower_checked_model
from gda_balancing.domain.model._lowering import _resolved_source_symbols
from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_fact_is_closed,
)
import test_schema2_model_lowerer_conformance as reference
from test_source_fact_transport import _fixture


@pytest.mark.parametrize(
    "mutation",
    [
        "domain-rename",
        "missing",
        "extra",
        "wrong-type",
        "symbol-conflict",
        "resolved-conflict",
        "type-conflict",
        "nominal-conflict",
    ],
)
def test_independent_initial_fact_refusal_precedes_all_language_rules(
    monkeypatch, mutation
):
    kernel, graph, source, context = _fixture(
        mutation, renamed=mutation == "symbol-conflict"
    )
    admission = _consumer_b(kernel, graph)
    assert admission["admitted"], admission["diagnostics"]
    snapshot = deepcopy(source)
    calls = []
    original = reference._reference_apply

    def observed(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(reference, "_reference_apply", observed)
    result = reference._reference_check_source(source, kernel, context.language_bundle)
    assert calls == []
    index = 0 if mutation == "nominal-conflict" else 2 if "conflict" in mutation else 4
    prefix = (
        "/opaque~1modules~0/0/declarations~1~0"
        if mutation == "symbol-conflict"
        else "/modules/0/symbols"
    )
    profile = next(
        row
        for row in context.language_bundle["language"]["resolution_profiles"]
        if row["default"]
    )
    reason = next(
        row
        for row in context.language_bundle["language"]["reasons"]
        if row["id"] == profile["structural_reason"]
    )
    assert result == ((reason["diagnostic"], f"{prefix}/{index}"),)
    assert source == snapshot


def test_independent_inactive_nominal_adapter_owns_its_absent_discriminator(
    monkeypatch,
):
    kernel, graph, source, context = _fixture("nominal-conflict")
    symbols = source["modules"][0]["symbols"]
    for symbol in symbols:
        symbol.pop("value_kind", None)
    symbols[0].update(type="quantity", value_kind="nominal-structured")
    admission = _consumer_b(kernel, graph)
    assert admission["admitted"], admission["diagnostics"]
    language = context.language_bundle["language"]
    schema = next(
        row["schema"]
        for row in language["wire_schemas"]
        if row.get("protocol_role") == "model-source-package"
    )
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(source))
    imported = next(
        row for row in source["modules"][0]["imports"] if row["alias"] == "quantity"
    )
    package = next(
        row for row in language["packages"] if row["id"] == imported["package"]
    )
    assert imported["symbol"] not in package["exports"]["nominal_types"]
    snapshot = deepcopy(source)
    calls = []
    original = reference._reference_apply

    def observed(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(reference, "_reference_apply", observed)
    result = reference._reference_check_source(source, kernel, context.language_bundle)
    assert calls == []
    profile = next(row for row in language["resolution_profiles"] if row["default"])
    reason = next(
        row for row in language["reasons"] if row["id"] == profile["structural_reason"]
    )
    assert result == ((reason["diagnostic"], "/modules/0/symbols/0"),)
    assert source == snapshot


@pytest.mark.parametrize(
    ("renamed", "input_member"),
    [(False, None), (True, None), (False, "symbol"), (False, "type")],
    ids=[
        "original",
        "profile-addresses",
        "symbol-input-value-kind",
        "type-input-value-kind",
    ],
)
def test_independent_initial_facts_keep_mixed_nominal_and_quantity_compilation(
    renamed, input_member
):
    kernel, graph, source, context = _fixture(
        renamed=renamed, input_member=input_member
    )
    admission = _consumer_b(kernel, graph)
    assert admission["admitted"], admission["diagnostics"]
    checked = check_model_source_value(source, authority_context=context)
    independent = reference._reference_check_source(
        source, kernel, context.language_bundle
    )
    assert isinstance(checked, CheckedModel)
    assert isinstance(independent, ModelSourceContext)
    rows = reference._reference_resolved_symbols(independent)
    assert rows == _resolved_source_symbols(source, context.language_bundle, kernel)
    assert len(rows) == 5
    assert (
        sum(fields.get("value_kind") == "nominal-structured" for fields, _ in rows) == 2
    )
    actual = lower_checked_model(checked)
    expected = reference._reference_semantic_artifacts(independent)
    for role in ("package-lock", "rir-semantic-payload", "resolved-model", "debug-map"):
        assert actual[role] == expected[role]
    assert reference._reference_admits_semantic_artifacts(actual, independent)


def test_independent_source_vector_corpus_materializes_closed_initial_facts():
    kernel, language = mutable_authorities()
    vectors = [row for row in language["vectors"] if "source_fixture" in row]
    assert len(vectors) == len({row["id"] for row in vectors}) == 34
    retained = deepcopy(vectors)
    positive = [row for row in vectors if row["expect"]["outcome"] != "refused"]
    assert len(positive) == 13
    fact_count = 0
    lowering = reference._reference_lowering(language["language"])
    for vector in positive:
        source = reference._reference_materialize_vector_source(vector, language)
        checked = reference._reference_check_source(source, kernel, language)
        assert isinstance(checked, ModelSourceContext), (vector["id"], checked)
        rows = reference._reference_resolved_symbols(checked)
        assert rows == _resolved_source_symbols(source, language, kernel)
        assert len(rows) == vector["expect"]["declaration_count"]
        for fields, _pointer in rows:
            prefix = (
                "structured_"
                if fields.get("value_kind") == "nominal-structured"
                else ""
            )
            fact = {"kind": lowering[f"{prefix}initial_fact_kind"], "fields": fields}
            assert _consumer_b_fact_is_closed(fact, kernel["meta_format"], language)
            assert _fact_is_closed(fact, kernel["meta_format"], language)
        fact_count += len(rows)
    assert fact_count == 4189
    assert vectors == retained
