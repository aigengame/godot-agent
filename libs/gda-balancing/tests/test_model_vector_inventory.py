"""Model vector identities are read from executed Source and selected Lock owners."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    model_refusal_catalog,
)
from gda_balancing.domain.model._compilation import lower_checked_model
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    read_extension_inventory,
    validate_extension_inventory,
)
from schema2_extension_renaming_support import _rewrite_positions
from schema2_model_vector_inventory_support import model_vector_inventory
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import (
    ModelSourceContext,
    _reference_check_source,
    _reference_semantic_artifacts,
    _reference_admits_semantic_artifacts,
)
from test_trace_protocol_structure import _authored, _graph, _index


def _definitions(graph, role):
    return [
        row
        for package in graph["packages"]
        for entry in package["semantic_closure"]
        if entry["authority_path"] == role
        for row in entry["definitions"]
    ]


def _vectors(graph):
    return [
        row
        for vectors in graph["vector_sets"]
        for row in vectors["vector_definitions"]
        if "source_fixture" in row
    ]


@pytest.fixture(scope="module")
def witness():
    kernel, language = mutable_authorities()
    authored = _authored(language)
    inventory = read_extension_inventory(kernel, authored)
    validate_extension_inventory(kernel, authored, inventory)
    return kernel, authored, inventory


def test_model_vector_inventory_closes_all_real_sources_and_lock_oracle_references(
    witness,
):
    kernel, graph, inventory = witness
    rows, roots, projections, reserved = model_vector_inventory(kernel, graph)
    assert len(roots) == 34
    assert (
        len([v for v in _vectors(graph) if v["expect"]["outcome"] == "admitted"]) == 13
    )
    assert (
        len(
            [
                row
                for row in rows
                if "/expect/" in row.pointer and row.location == "value"
            ]
        )
        == 1637
    )
    assert not any(gap.pointer == "/vector_sets" for gap in inventory.uncovered)
    from schema2_extension_inventory_support import (
        source_formula_requests,
        _pointer_value,
    )

    requests = source_formula_requests(kernel, graph)
    assert len(requests) == 25 and len(projections) == 23
    uninterpreted = set(requests) - set(projections)
    assert {
        _pointer_value(graph, "/".join(pointer.split("/")[:5]))["id"]
        for pointer in uninterpreted
    } == {
        "game.combat.model-binding.contract-wrong-type",
        "formula.schema.refuse.dynamic-or-effectful-graph",
    }
    assert not any(
        row.location == "formula" and row.pointer in uninterpreted for row in rows
    )
    assert not any(
        "/source_fixture/source/modules/0/symbols/4095" in row.pointer for row in rows
    )
    indexed = [
        root
        for root in roots
        if any(row.pointer == root + "/source_fixture/index_member" for row in rows)
    ]
    assert len(indexed) == 2
    for root in indexed:
        assert any(
            row.pointer == root + "/source_fixture/template/symbol"
            and row.location == "key"
            for row in rows
        )
        assert not any(
            row.pointer == root + "/source_fixture/template/symbol"
            and row.location == "value"
            for row in rows
        )
    assert reserved <= inventory.reserved


@pytest.mark.parametrize(
    "mutation",
    [
        "source-omitted",
        "expect-omitted",
        "pointer-omitted",
        "free-omitted",
        "extra",
        "misowned",
        "wrong-package",
        "reserved",
        "forged-free",
    ],
)
def test_model_vector_inverse_refuses_missing_extra_and_wrong_owners(witness, mutation):
    kernel, graph, inventory = witness
    rows = list(inventory.occurrences)
    selected = [row for row in rows if row.law == "/meta_format/model_program_vector"]
    reserved = inventory.reserved
    if mutation.endswith("-omitted"):
        match = next(
            row
            for row in selected
            if (
                "/source_fixture/" in row.pointer
                if mutation == "source-omitted"
                else "/expect/lock_oracle/" in row.pointer
                if mutation == "expect-omitted"
                else row.location == "json-pointer"
                if mutation == "pointer-omitted"
                else row.use == "unresolved-reference"
            )
        )
        rows.remove(match)
    elif mutation == "reserved":
        match = next(row for row in selected if row.token not in reserved)
        reserved = reserved | {match.token}
    elif mutation == "forged-free":
        match = next(
            row
            for row in selected
            if row.use == "reference" and row.token.role == "namespace"
        )
        rows[rows.index(match)] = replace(match, use="unresolved-reference")
    else:
        match = next(
            row
            for row in selected
            if row.token.role == "language.operations"
            and "/expect/lock_oracle/" in row.pointer
        )
        token = AuthorityToken(
            match.token.role, ("another.real-or-absent-package",), match.token.name
        )
        if mutation == "misowned":
            token = AuthorityToken("language.reasons", (), match.token.name)
        if mutation != "extra":
            rows.remove(match)
        rows.append(replace(match, token=token))
    malformed = replace(
        inventory,
        tokens=frozenset(row.token for row in rows),
        occurrences=tuple(sorted(rows)),
        reserved=reserved,
    )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, malformed)


def _rename_reasons(kernel, graph, inventory):
    profile = next(
        p for p in _definitions(graph, "language.resolution_profiles") if p["default"]
    )
    lowering = next(
        p
        for p in _definitions(graph, "language.model_lowerings")
        if p["id"] == profile["model_lowering"]
    )
    selected = {
        profile["parse_reason"],
        profile["source_byte_reason"],
        profile["structural_reason"],
        profile["resource_reason"],
        lowering["admission_reason"],
        lowering["runtime_projection"]["resource_reason"],
        *profile["formula_resolution"]["refusal_reasons"].values(),
        *(row["reason"] for row in profile["judgment_chain"]),
        *(row["reason"] for row in _definitions(graph, "language.model_checks")),
    }
    diagnostics = {
        row["diagnostic"]
        for row in _definitions(graph, "language.reasons")
        if row["id"] in selected
    }
    tokens = sorted(
        token
        for token in inventory.tokens - inventory.reserved
        if (token.role == "language.reasons" and token.name in selected)
        or (token.role == "diagnostics" and token.name in diagnostics)
    )
    names = {
        token: f"review.model_reference_{index:03d}"
        for index, token in enumerate(tokens)
    }
    positions = {
        row.pointer: names[row.token]
        for row in inventory.occurrences
        if row.token in names
    }
    assert all(
        row.location == "value" for row in inventory.occurrences if row.token in names
    )
    return _rewrite_positions(graph, positions, {}), names


@pytest.mark.parametrize("renamed", [False, True])
def test_model_reason_owner_rename_reaches_real_public_and_independent_compilers(
    witness, renamed, tmp_path
):
    kernel, original, inventory = witness
    graph = deepcopy(original)
    if renamed:
        graph, _ = _rename_reasons(kernel, graph, inventory)
    raw = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        actual = consumer(kernel, raw)
        assert actual["admitted"], actual["diagnostics"]
    language = _index(kernel, raw)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext)
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, raw))
    selected = {v["id"]: v for v in _vectors(graph)}
    for name in ("model.compile.positive", "model.compile.negative-duplicate"):
        vector = selected[name]
        source = vector["source_fixture"]["source"]
        a = check_model_source_value(source, authority_context=context)
        b = _reference_check_source(source, kernel, language)
        public.write_source(source)
        admitted = vector["expect"]["outcome"] == "admitted"
        checked = public.cli("model", "check", str(public.source), success=admitted)
        built = public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(tmp_path / name),
            "--invocation-key",
            "c5" * 32,
            success=admitted,
        )
        if admitted:
            assert isinstance(a, CheckedModel) and isinstance(b, ModelSourceContext)
            artifacts = lower_checked_model(a)
            independent = _reference_semantic_artifacts(b)
            assert {key: artifacts[key] for key in independent} == independent
            assert _reference_admits_semantic_artifacts(artifacts, b)
            public_artifacts = _members(built)
            for member, value in independent.items():
                assert public_artifacts[member] == value
        else:
            assert isinstance(a, Schema2RefusalReport) and isinstance(b, tuple)
            assert all(isinstance(d.primary, ArtifactLocation) for d in a.diagnostics)
            assert [
                (d.code, d.primary.model_dump()["pointer"]) for d in a.diagnostics
            ] == list(b)
            assert (
                checked["error"]["diagnostics"][0]["code"]
                == built["error"]["diagnostics"][0]["code"]
                == vector["expect"]["diagnostics"][0]["code"]
            )
    catalog = set(model_refusal_catalog(language))
    profile = next(
        p for p in language["language"]["resolution_profiles"] if p["default"]
    )
    reasons = {r["id"]: r for r in language["language"]["reasons"]}
    for category in ("notation-parse", "notation-resource"):
        row = reasons[profile["formula_resolution"]["refusal_reasons"][category]]
        assert (row["diagnostic"], row["stage"]) in catalog
    (tmp_path / "observations.json").write_text(
        json.dumps({"renamed": renamed, "catalog": sorted(catalog)}, indent=2)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "formula-missing",
        "formula-extra",
        "formula-dangling",
        "source-byte-owner",
        "resolution-resource-owner",
        "projection-resource-owner",
    ],
)
def test_reason_owner_contract_refuses_correctly_resealed_wrong_links(
    witness, mutation
):
    kernel, original, _ = witness
    graph = deepcopy(original)
    profile = next(
        p for p in _definitions(graph, "language.resolution_profiles") if p["default"]
    )
    if mutation == "formula-missing":
        profile["formula_resolution"]["refusal_reasons"].pop("notation-parse")
    elif mutation == "formula-extra":
        profile["formula_resolution"]["refusal_reasons"]["unused-category"] = profile[
            "parse_reason"
        ]
    elif mutation == "formula-dangling":
        profile["formula_resolution"]["refusal_reasons"]["type-mismatch"] = (
            "missing.reason"
        )
    elif mutation == "source-byte-owner":
        profile["source_byte_reason"] = profile["resource_reason"]
    elif mutation == "resolution-resource-owner":
        profile["resource_reason"] = profile["source_byte_reason"]
    else:
        lowering = next(
            p
            for p in _definitions(graph, "language.model_lowerings")
            if p["id"] == profile["model_lowering"]
        )
        lowering["runtime_projection"]["resource_reason"] = profile["resource_reason"]
    raw = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        observed = consumer(kernel, raw)
        assert not observed["admitted"]
        assert observed["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]


@pytest.mark.parametrize(
    "mutation",
    [
        "omitted",
        "binding-omitted",
        "duplicate-declaration",
        "misclassified",
        "extra-reason",
    ],
)
def test_template_exhaustion_reserved_role_is_exact(witness, mutation):
    kernel, graph, inventory = witness
    name = kernel["meta_format"]["template_admission"]["resource_accounting"][
        "exhaustion_diagnostic"
    ]
    token = AuthorityToken("diagnostics", (), name)
    assert token in inventory.reserved
    occurrences = [row for row in inventory.occurrences if row.token == token]
    assert occurrences
    reasons = {
        row["id"]
        for row in _definitions(graph, "language.reasons")
        if row["diagnostic"] == name
    }
    assert reasons
    reason = next(
        t
        for t in inventory.tokens
        if t.role == "language.reasons" and t.name in reasons
    )
    assert reason not in inventory.reserved
    if mutation == "extra-reason":
        malformed = replace(inventory, reserved=inventory.reserved | {reason})
    elif mutation == "misclassified":
        malformed = replace(inventory, reserved=inventory.reserved - {token})
    else:
        selected = next(row for row in occurrences if row.use == "declaration")
        if mutation == "binding-omitted":
            selected = next(
                row
                for row in occurrences
                if row.pointer.endswith("/resource_diagnostic")
            )
        rows = list(inventory.occurrences)
        if mutation == "duplicate-declaration":
            rows.append(selected)
        else:
            rows.remove(selected)
        malformed = replace(inventory, occurrences=tuple(rows))
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, graph, malformed)


def test_model_catalog_has_only_selected_pipeline_owners(witness):
    from gda_balancing.domain.authority.admission import BOOTSTRAP_REFUSAL_CATALOG

    kernel, graph, _ = witness
    language = _index(kernel, _graph(kernel, graph))
    profile = next(
        p for p in language["language"]["resolution_profiles"] if p["default"]
    )
    lowering = next(
        p
        for p in language["language"]["model_lowerings"]
        if p["id"] == profile["model_lowering"]
    )
    selected = {
        profile[member]
        for member in (
            "parse_reason",
            "structural_reason",
            "source_byte_reason",
            "resource_reason",
        )
    }
    selected.update(row["reason"] for row in profile["judgment_chain"])
    selected.update(row["reason"] for row in language["language"]["model_checks"])
    selected.update(profile["formula_resolution"]["refusal_reasons"].values())
    selected.update(
        (
            lowering["admission_reason"],
            lowering["runtime_projection"]["resource_reason"],
        )
    )
    reasons = language["language"]["reasons"]
    expected = set(BOOTSTRAP_REFUSAL_CATALOG) | {
        (r["diagnostic"], r["stage"]) for r in reasons if r["id"] in selected
    }
    assert set(model_refusal_catalog(language)) == expected
    unselected = {
        (r["diagnostic"], r["stage"])
        for r in reasons
        if r["stage"] in {"parse", "static"} and r["id"] not in selected
    } - expected
    assert unselected
    assert not unselected.intersection(model_refusal_catalog(language))


@pytest.mark.parametrize("renamed", [False, True])
def test_notation_failure_categories_reach_actual_public_consumers(
    witness, renamed, tmp_path
):
    from test_formula_inline_resolution import _inline_case, _formula_request
    from schema2_formula_conformance_support import (
        FormulaReferenceFailure,
        parse_canonical,
    )

    kernel, _, source = _inline_case(False)
    _, original, inventory = witness
    graph = deepcopy(original)
    if renamed:
        graph, _ = _rename_reasons(kernel, graph, inventory)
    for row in _definitions(graph, "language.wire_schemas"):
        if row.get("protocol_role") == "model-source-package":
            row["formula_grammar"]["max_expression_bytes"] = 1
    raw = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        assert consumer(kernel, raw)["admitted"]
    language = _index(kernel, raw)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext)
    profile = next(
        p for p in language["language"]["resolution_profiles"] if p["default"]
    )
    reasons = {r["id"]: r for r in language["language"]["reasons"]}
    codes = {
        category: reasons[profile["formula_resolution"]["refusal_reasons"][category]][
            "diagnostic"
        ]
        for category in ("notation-parse", "notation-resource")
    }
    a = check_model_source_value(source, authority_context=context)
    b = _reference_check_source(source, kernel, language)
    assert isinstance(a, Schema2RefusalReport) and isinstance(b, tuple)
    assert [(d.code, d.primary.model_dump()["pointer"]) for d in a.diagnostics] == list(
        b
    )
    assert {d.code for d in a.diagnostics} == {codes["notation-resource"]}
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, raw))
    public.write_source(source)
    for args in (
        ("model", "check", str(public.source)),
        (
            "model",
            "build",
            str(public.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "d1" * 32,
        ),
    ):
        result = public.cli(*args, success=False)
        assert result["error"]["stage"] == "parse"
        assert result["error"]["diagnostics"][0]["code"] == codes["notation-resource"]
    request = _formula_request(source)
    for category, expression in (
        ("notation-parse", "?"),
        ("notation-resource", "rare_weight"),
    ):
        request["formula"]["expression"] = expression
        with pytest.raises(FormulaReferenceFailure) as failure:
            parse_canonical(expression, request, language, kernel=kernel)
        assert failure.value.category == category
        path = tmp_path / (category + ".json")
        path.write_text(json.dumps(request))
        result = public.cli("formula", "parse", str(path), success=False)
        assert result["error"]["stage"] == "parse"
        assert result["error"]["diagnostics"][0]["code"] == codes[category]
        assert (codes[category], "parse") in model_refusal_catalog(language)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "renamed"])
def test_template_exhaustion_reference_requires_actual_unique_declaration(
    witness, mutation
):
    from schema2_extension_inventory_support import _template_exhaustion_declaration

    kernel, original, _ = witness
    graph = deepcopy(original)
    name = kernel["meta_format"]["template_admission"]["resource_accounting"][
        "exhaustion_diagnostic"
    ]
    entry = next(
        e
        for p in graph["packages"]
        for e in p["semantic_closure"]
        if e["authority_path"] == "diagnostics"
        and any(r["code"] == name for r in e["definitions"])
    )
    row = next(r for r in entry["definitions"] if r["code"] == name)
    if mutation == "missing":
        entry["definitions"].remove(row)
    elif mutation == "duplicate":
        entry["definitions"].append(deepcopy(row))
    else:
        row["code"] = "review.unbound_diagnostic"
    with pytest.raises(InventoryRefusal, match="no unique declaration"):
        _template_exhaustion_declaration(kernel, graph)


def test_model_lock_reference_cannot_move_to_a_real_same_named_type(witness):
    kernel, original, _ = witness
    graph = deepcopy(original)
    original_package = next(p for p in graph["packages"] if p["id"] == "core.quantity")
    target = next(p for p in graph["packages"] if p["id"] == "game.progression")
    target["exports"]["types"].append(
        deepcopy(
            next(
                t for t in original_package["exports"]["types"] if t["id"] == "Quantity"
            )
        )
    )
    target["exports"]["types"].sort(key=lambda row: row["id"])
    raw = _graph(kernel, graph)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, raw)
        assert result["admitted"], result["diagnostics"]
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    source = AuthorityToken("type", (original_package["id"],), "Quantity")
    other = AuthorityToken("type", (target["id"],), "Quantity")
    assert {source, other} <= inventory.tokens
    match = next(
        o
        for o in inventory.occurrences
        if o.token == source and "/expect/lock_oracle/types/" in o.pointer
    )
    rows = [replace(o, token=other) if o == match else o for o in inventory.occurrences]
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(
            kernel, graph, replace(inventory, occurrences=tuple(rows))
        )


@pytest.mark.parametrize("target_kind", ["declared", "reserved"])
def test_model_missing_lookup_cannot_capture_an_owned_namespace(witness, target_kind):
    from schema2_extension_inventory_support import (
        token_bijection_from_names,
        validate_token_bijection,
    )

    _, _, inventory = witness
    free = next(
        o.token
        for o in inventory.occurrences
        if o.law == "/meta_format/model_program_vector"
        and o.use == "unresolved-reference"
        and o.token.role == "namespace"
    )
    names = {
        token: f"review_token_{i}"
        for i, token in enumerate(sorted(inventory.tokens - inventory.reserved))
    }
    if target_kind == "declared":
        declaration = next(
            o.token
            for o in inventory.occurrences
            if o.use == "declaration"
            and o.token.role == "namespace"
            and o.token not in inventory.reserved
        )
        names[free] = names[declaration]
        message = "duplicate source or target"
    else:
        reserved = next(t for t in inventory.reserved if t.role == "namespace")
        names[free] = reserved.name
        message = "Kernel-reserved token"
    with pytest.raises(InventoryRefusal, match=message):
        validate_token_bijection(
            inventory, token_bijection_from_names(inventory, names)
        )


def test_model_vector_source_ast_rename_keeps_independent_public_construction(
    witness, tmp_path
):
    from schema2_extension_inventory_support import (
        _formula_projections,
        token_bijection_from_names,
    )
    from schema2_extension_renaming_support import _render_formulas

    kernel, graph, inventory = witness
    token = next(
        t
        for t in inventory.tokens
        if t.role == "model-vector-source-formula-parameter"
        and t.owner[0] == "formula.compiler.accept.closed-static-graph"
    )
    names = {token: "review_parameter"}
    occurrences = [o for o in inventory.occurrences if o.token == token]
    assert any(o.location == "formula" for o in occurrences)
    values = {o.pointer: names[o.token] for o in occurrences if o.location == "value"}
    candidate = _rewrite_positions(graph, values, {})
    bodies = _formula_projections(kernel, graph)
    for pointer, body in bodies.items():
        edits = {
            o.projection: names[o.token]
            for o in occurrences
            if o.location == "formula" and o.pointer == pointer
        }
        bodies[pointer] = _rewrite_positions(body, edits, {})
    _render_formulas(kernel, candidate, bodies)
    raw = _graph(kernel, candidate)
    for consumer in (_consumer_a, _consumer_b):
        assert consumer(kernel, raw)["admitted"]
    renamed = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed)
    assert renamed.uncovered == inventory.uncovered
    assert (
        set(dict(token_bijection_from_names(inventory, names)).values())
        <= renamed.tokens
    )
    source = next(v for v in _vectors(candidate) if v["id"] == token.owner[0])[
        "source_fixture"
    ]["source"]
    language = _index(kernel, raw)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext)
    a = check_model_source_value(source, authority_context=context)
    b = _reference_check_source(source, kernel, language)
    assert isinstance(a, CheckedModel) and isinstance(b, ModelSourceContext)
    artifacts = lower_checked_model(a)
    independent = _reference_semantic_artifacts(b)
    assert {key: artifacts[key] for key in independent} == independent
    assert _reference_admits_semantic_artifacts(artifacts, b)
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, raw))
    public.write_source(source)
    assert public.cli("model", "check", str(public.source))["checked"]
    produced = _members(
        public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "d3" * 32,
        )
    )
    assert {key: produced[key] for key in independent} == independent
