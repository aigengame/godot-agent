"""Source adapters must produce closed initial Facts before language rules run."""

import json
from pathlib import Path

import jsonschema
import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.vector_validation import _fact_is_closed
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.model import CheckedModel, check_model_source_value
from gda_balancing.domain.model._lowering import _resolved_source_symbols
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b_fact_is_closed
from schema2_bootstrap_production_support import _consumer_a
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import _materialize_vector_source
from test_trace_protocol_structure import _authored, _graph, _index

_EXAMPLES = Path(__file__).parents[1] / "examples/schema2"


def _definitions(authored, path):
    return [
        value
        for package in authored["packages"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == path
        for value in entry["definitions"]
    ]


def _rename_member(schema, old, new):
    if old in schema.get("properties", {}):
        schema["properties"][new] = schema["properties"].pop(old)
    if "required" in schema:
        schema["required"] = [new if key == old else key for key in schema["required"]]
    for branch in schema.get("oneOf", []):
        _rename_member(branch, old, new)


def _fixture(mutation=None, *, renamed=False):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    source = json.loads((_EXAMPLES / "bounded-fold/model-source.json").read_text())
    schema = next(
        row["schema"]
        for row in _definitions(authored, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )
    profile = next(
        row
        for row in _definitions(authored, "language.resolution_profiles")
        if row["default"]
    )
    module_schema = schema["properties"]["modules"]["items"]
    symbol_schema = module_schema["properties"]["symbols"]["items"]
    checks = _definitions(authored, "language.model_checks")
    if renamed:
        names = {
            "modules": "opaque/modules~",
            "symbols": "declarations/~",
            "symbol": "local/name~",
            "type": "import/type~",
        }
        _rename_member(schema, "modules", names["modules"])
        _rename_member(module_schema, "symbols", names["symbols"])
        _rename_member(symbol_schema, "symbol", names["symbol"])
        _rename_member(symbol_schema, "type", names["type"])
        for role, old in (
            ("modules_member", "modules"),
            ("symbols_member", "symbols"),
            ("symbol_name_member", "symbol"),
            ("symbol_type_member", "type"),
        ):
            profile[role] = names[old]
        # Only the actual authored Source address terms are renamed. Import
        # references and the Kernel's Fact/compiled Symbol fields retain owners.
        for recipe in profile["relation_recipes"]:
            for binding in recipe["bindings"]:
                term = binding["source"]
                if term.get("root") == "source" and term["path"] == ["modules"]:
                    term["path"] = [names["modules"]]
                elif term.get("root") == "binding" and term["path"] == ["symbols"]:
                    term["path"] = [names["symbols"]]
            for field in recipe["fields"]:
                term = field["term"]
                if term.get("root") == "binding" and term.get("binding") == "symbol":
                    term["path"] = [names[part] for part in term["path"]]
        for lowering in _definitions(authored, "language.model_lowerings"):
            lowering["source_selector"] = [
                names.get(part, part) for part in lowering["source_selector"]
            ]
        for check in checks:
            for field in ("selector", "scope_selector"):
                if field in check:
                    check[field] = [names.get(part, part) for part in check[field]]
        source[names["modules"]] = source.pop("modules")
        for module in source[names["modules"]]:
            module[names["symbols"]] = module.pop("symbols")
            for symbol in module[names["symbols"]]:
                symbol[names["symbol"]] = symbol.pop("symbol")
                symbol[names["type"]] = symbol.pop("type")
    modules, symbols = profile["modules_member"], profile["symbols_member"]
    quantity = [row for row in source[modules][0][symbols] if "domain" in row]
    nominal = [row for row in source[modules][0][symbols] if "domain" not in row]
    if mutation == "domain-rename":
        _rename_member(symbol_schema, "domain", "opaque_domain")
        for check in checks:
            if check["selector"][-1] == "domain":
                check["selector"][-1] = "opaque_domain"
        for row in quantity:
            row["opaque_domain"] = row.pop("domain")
    elif mutation == "missing":
        for branch in symbol_schema["oneOf"]:
            branch["required"] = [key for key in branch["required"] if key != "domain"]
        for row in quantity:
            row.pop("domain")
    elif mutation == "wrong-type":
        symbol_schema["properties"]["domain"] = {"type": "integer"}
        for row in quantity:
            row["domain"] = 1
    elif mutation is not None:
        member = {
            "extra": "unowned_fact_field",
            "symbol-conflict": "symbol",
            "resolved-conflict": "resolved_symbol",
            "type-conflict": "type_identity",
            "nominal-conflict": "value_kind",
            "inactive-nominal-conflict": "value_kind",
        }[mutation]
        symbol_schema["properties"][member] = {"type": "string"}
        for branch in symbol_schema["oneOf"]:
            branch["properties"][member] = {}
        if mutation == "inactive-nominal-conflict":
            # A non-nominal import cannot acquire the derived discriminator from
            # copied authoring data, even when its constructed Fact would fit.
            nominal[0][profile["symbol_type_member"]] = "quantity"
            nominal[0][member] = "nominal-structured"
            package = next(
                row for row in authored["packages"] if row["id"] == "core.quantity"
            )
            assert package["exports"]["nominal_types"] == []
        else:
            for row in nominal if mutation == "nominal-conflict" else quantity:
                row[member] = "authored-value-must-not-be-overwritten"
    vector_bytes = canonical_bytes(authored["vector_sets"])
    graph = _graph(kernel, authored)
    assert canonical_bytes(authored["vector_sets"]) == vector_bytes
    assert _consumer_a(kernel, graph)["admitted"]
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(source))
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    return kernel, graph, source, context


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
        "inactive-nominal-conflict",
    ],
)
def test_schema_valid_source_refuses_at_its_initial_fact_before_any_rule(
    tmp_path, monkeypatch, mutation
):
    kernel, graph, source, context = _fixture(
        mutation, renamed=mutation == "symbol-conflict"
    )

    def no_language_rule(*_args, **_kwargs):
        raise AssertionError("an invalid initial Fact reached a language rule")

    monkeypatch.setattr(
        "gda_balancing.domain.model._lowering._apply_language_rule", no_language_rule
    )
    result = check_model_source_value(source, authority_context=context)
    assert isinstance(result, Schema2RefusalReport), result
    index = (
        0
        if mutation in {"nominal-conflict", "inactive-nominal-conflict"}
        else 2
        if mutation in {"symbol-conflict", "resolved-conflict", "type-conflict"}
        else 4
    )
    prefix = (
        "/opaque~1modules~0/0/declarations~1~0"
        if mutation == "symbol-conflict"
        else "/modules/0/symbols"
    )
    pointer = prefix + "/" + str(index)
    assert result.stage == "static"
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert isinstance(diagnostic.primary, ArtifactLocation)
    assert diagnostic.code == "language.source_contract_mismatch"
    assert diagnostic.primary.pointer == pointer
    assert "initial Fact" in diagnostic.message
    # The subprocess retains the real rule evaluator and public refusal framing.
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    candidate.write_source(source)
    for command in ("check", "build"):
        args = ["model", command, str(candidate.source)]
        if command == "build":
            args += ["--out", str(tmp_path / "build"), "--invocation-key", "ce" * 32]
        public = candidate.cli(*args, success=False)
        assert candidate.receipts[-1]["returncode"] == 2
        assert public["error"]["stage"] == "static"
        actual = public["error"]["diagnostics"][0]
        assert actual["code"] == diagnostic.code
        assert actual["primary"]["pointer"] == pointer
        assert (
            actual["primary"]["content_identity"] == diagnostic.primary.content_identity
        )


@pytest.mark.parametrize(
    "renamed", [False, True], ids=["original", "profile-addresses"]
)
def test_mixed_public_model_keeps_closed_facts_and_runtime_values(tmp_path, renamed):
    kernel, graph, source, context = _fixture(renamed=renamed)
    checked = check_model_source_value(source, authority_context=context)
    assert isinstance(checked, CheckedModel)
    rows = _resolved_source_symbols(source, context.language_bundle, kernel)
    assert len(rows) == 5
    assert (
        sum(fields.get("value_kind") == "nominal-structured" for fields, _ in rows) == 2
    )
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    candidate.write_source(source)
    candidate.cli("model", "check", str(candidate.source))
    build = _members(
        candidate.cli(
            "model",
            "build",
            str(candidate.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "cd" * 32,
        )
    )
    rir = build["rir-semantic-payload"]
    rir_path = tmp_path / "rir.json"
    rir_path.write_text(json.dumps(rir))
    specification = json.loads((_EXAMPLES / "bounded-fold/experiment.json").read_text())
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(specification))
    candidate.cli("experiment", "check", str(path), "--rir", str(rir_path))
    run = _members(
        candidate.cli(
            "experiment",
            "run",
            str(path),
            "--rir",
            str(rir_path),
            "--out",
            str(tmp_path / "run"),
            "--invocation-key",
            "cc" * 32,
        )
    )
    assert {
        row["metric"]: row["value"] for row in run["metric-dataset"]["samples"]
    } == {"selected_count": 2, "ordered_value": 1234}


def test_all_current_positive_source_vectors_have_closed_initial_facts():
    kernel, language = mutable_authorities()
    lowering = next(
        row
        for row in language["language"]["model_lowerings"]
        if row["id"]
        == next(
            profile["model_lowering"]
            for profile in language["language"]["resolution_profiles"]
            if profile["default"]
        )
    )
    cases = []
    for vector in language["vectors"]:
        if "source_fixture" not in vector or vector["expect"]["outcome"] != "admitted":
            continue
        source = _materialize_vector_source(vector, language)
        facts = []
        for fields, _ in _resolved_source_symbols(source, language, kernel):
            fact = {
                "kind": lowering[
                    "structured_initial_fact_kind"
                    if fields.get("value_kind") == "nominal-structured"
                    else "initial_fact_kind"
                ],
                "fields": fields,
            }
            assert _fact_is_closed(fact, kernel["meta_format"], language), vector["id"]
            assert _consumer_b_fact_is_closed(fact, kernel["meta_format"], language), (
                vector["id"]
            )
            facts.append(fact)
        cases.append((vector["id"], len(facts)))
    assert len(cases) == 13
    assert sum(count for _, count in cases) == 4189
