"""Independent Source roles preserve Facts and reject malformed authored fields."""

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.vector_validation import _fact_is_closed
from gda_balancing.domain.diagnostics import Schema2RefusalReport
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
from test_source_fact_transport import _definitions, _rename_member
from test_trace_protocol_structure import _authored, _graph, _index


def _member(schema, member):
    matches = [
        (name, child)
        for name, child in schema["properties"].items()
        if child.get("semantic_member") == member
    ]
    assert len(matches) == 1
    return matches[0]


def _fixture(*, renamed=False, input_member=None, domain_renamed=False):
    """Author Source names at their Schema roles; keep interpretation in each consumer."""
    kernel, language = mutable_authorities()
    authored = _authored(language)
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/bounded-fold/model-source.json"
        ).read_text()
    )
    schema = next(
        row["schema"]
        for row in _definitions(authored, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )
    law = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "source_notation"
    ]["semantic_roles"]
    assert schema["semantic_role"] == law["root"]
    modules, module_array = _member(schema, "modules")
    module_schema = module_array["items"]
    assert [module_schema["semantic_role"]] == law["children"]["source"]["modules"][
        "items"
    ]
    symbols, symbol_array = _member(module_schema, "symbols")
    symbol_schema = symbol_array["items"]
    assert [symbol_schema["semantic_role"]] == law["children"]["module"]["symbols"][
        "items"
    ]
    profile = next(
        row
        for row in _definitions(authored, "language.resolution_profiles")
        if row["default"]
    )
    names = {name: name for name in (modules, symbols, "symbol", "type", "domain")}
    if renamed:
        names.update(
            modules="opaque/modules~",
            symbols="declarations/~",
            symbol="local/name~",
            type="import/type~",
        )
    if input_member is not None:
        assert input_member in {"symbol", "type"}
        names[input_member] = "value_kind"
    if domain_renamed:
        names["domain"] = "opaque/domain~"
    for owner, member in (
        (schema, "modules"),
        (module_schema, "symbols"),
        (symbol_schema, "symbol"),
        (symbol_schema, "type"),
        (symbol_schema, "domain"),
    ):
        old, _ = _member(owner, member)
        _rename_member(owner, old, names[old])

    # Existing relation/check terms name authored fields. Schema annotations
    # own their canonical meaning; no retired Resolution selector is restored.
    def rename_term(term):
        selected = {}
        if term["root"] == "source":
            selected = {modules: names[modules]}
        elif term["root"] == "binding" and term["binding"] == "module":
            selected = {symbols: names[symbols]}
        elif term["root"] == "binding" and term["binding"] == "symbol":
            selected = {
                member: names[member] for member in ("symbol", "type", "domain")
            }
        term["path"] = [selected.get(part, part) for part in term["path"]]

    for recipe in profile["relation_recipes"]:
        for binding in recipe["bindings"]:
            rename_term(binding["source"])
        for predicate in recipe["predicates"]:
            rename_term(predicate["left"])
            rename_term(predicate["right"])
        for field in recipe["fields"]:
            rename_term(field["term"])
    for module in source[modules]:
        for symbol in module[symbols]:
            for member in ("symbol", "type", "domain"):
                if member in symbol:
                    symbol[names[member]] = symbol.pop(member)
        module[names[symbols]] = module.pop(symbols)
    source[names[modules]] = source.pop(modules)
    graph = _graph(kernel, authored)
    assert _consumer_b(kernel, graph)["admitted"]
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(source))
    return kernel, graph, source, context


@pytest.mark.parametrize(
    "mutation",
    [
        "unsynchronized-domain",
        "missing",
        "extra",
        "wrong-type",
        "symbol-conflict",
        "resolved-conflict",
        "type-conflict",
        "nominal-conflict",
    ],
)
def test_independent_source_shape_refusal_precedes_all_language_rules(
    monkeypatch, mutation
):
    kernel, graph, source, context = _fixture(renamed=mutation == "symbol-conflict")
    modules = "opaque/modules~" if mutation == "symbol-conflict" else "modules"
    symbols_member = "declarations/~" if mutation == "symbol-conflict" else "symbols"
    index = 0 if mutation == "nominal-conflict" else 2
    symbol = source[modules][0][symbols_member][index]
    member = {
        "extra": "unowned_fact_field",
        "symbol-conflict": "symbol",
        "resolved-conflict": "resolved_symbol",
        "type-conflict": "type_identity",
        "nominal-conflict": "value_kind",
        "missing": "domain",
        "wrong-type": "domain",
        "unsynchronized-domain": "domain",
    }[mutation]
    if mutation == "missing":
        symbol.pop(member)
    elif mutation == "wrong-type":
        symbol[member] = 1
    elif mutation == "unsynchronized-domain":
        symbol["opaque_domain"] = symbol.pop(member)
    else:
        symbol[member] = "authored-value-must-not-be-overwritten"
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
    members = (
        ["domain", "opaque_domain"] if mutation == "unsynchronized-domain" else [member]
    )
    expected = tuple(
        (reason["diagnostic"], f"{prefix}/{index}/{name}") for name in members
    )
    assert result == expected
    actual = check_model_source_value(source, authority_context=context)
    assert isinstance(actual, Schema2RefusalReport) and actual.stage == "static"
    assert (
        tuple(
            (item.code, item.primary.model_dump()["pointer"])
            for item in actual.diagnostics
        )
        == expected
    )
    assert source == snapshot


def test_independent_source_rejects_an_undeclared_nominal_discriminator(
    monkeypatch,
):
    kernel, graph, source, context = _fixture()
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
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(source))
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
    expected = ((reason["diagnostic"], "/modules/0/symbols/0/value_kind"),)
    assert result == expected
    actual = check_model_source_value(source, authority_context=context)
    assert isinstance(actual, Schema2RefusalReport) and actual.stage == "static"
    assert (
        tuple(
            (item.code, item.primary.model_dump()["pointer"])
            for item in actual.diagnostics
        )
        == expected
    )
    assert source == snapshot


@pytest.mark.parametrize(
    ("renamed", "input_member", "domain_renamed"),
    [
        (False, None, False),
        (True, None, False),
        (False, "symbol", False),
        (False, "type", False),
        (False, None, True),
    ],
    ids=[
        "original",
        "schema-role-addresses",
        "symbol-input-value-kind",
        "type-input-value-kind",
        "domain-role-address",
    ],
)
def test_independent_initial_facts_keep_mixed_nominal_and_quantity_compilation(
    renamed, input_member, domain_renamed
):
    kernel, graph, source, context = _fixture(
        renamed=renamed, input_member=input_member, domain_renamed=domain_renamed
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
    assert rows == _resolved_source_symbols(
        checked.source_projection, context.language_bundle, kernel
    )
    if renamed or input_member is not None or domain_renamed:
        original_kernel, _, original_source, original_context = _fixture()
        control = reference._reference_check_source(
            original_source, original_kernel, original_context.language_bundle
        )
        assert isinstance(control, ModelSourceContext)
        assert independent.source_projection.value == control.source_projection.value
        assert [fields for fields, _ in rows] == [
            fields for fields, _ in reference._reference_resolved_symbols(control)
        ]
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
        production = check_model_source_value(source)
        assert isinstance(production, CheckedModel)
        assert rows == _resolved_source_symbols(
            production.source_projection, language, kernel
        )
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
