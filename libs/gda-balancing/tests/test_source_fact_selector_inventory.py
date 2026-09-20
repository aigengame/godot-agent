"""Source selectors retain Schema roles, child anchors and initial Fact owners."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest
import jsonschema
import schema2_extension_inventory_support as inventory_support

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import canonical_bytes
from gda_balancing.domain.experiment import CheckedExperiment, check_experiment_value
from gda_balancing.domain.experiment_artifacts import validate_experiment_artifact_set
from gda_balancing.domain.model import (
    AdmittedRir,
    admit_rir,
    CheckedModel,
    check_model_source_value,
    compile_checked_model,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _consumer_b_fact_is_closed,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    _authority_path_rows,
    _source_address_links,
    read_extension_inventory,
    token_bijection_from_names,
    validate_extension_inventory,
    validate_token_bijection,
)
from schema2_extension_renaming_support import (
    _json_pointer_values,
    _rewrite_positions,
)
from schema2_source_inventory_reverse_support import validate_source_inventory
from test_current_namespace_public import _PublicCandidate, _members
from test_source_wire_owners import _source_schema
from test_trace_protocol_structure import _authored, _graph, _index

_TRANSPORT = "/meta_format/language_definitions/collections/model_lowerings/source_fact_transport"
_EXAMPLES = Path(__file__).parents[1] / "examples/schema2"


@pytest.fixture(scope="module")
def witness():
    kernel, ldb = mutable_authorities()
    graph = _authored(ldb)
    graph["source"] = json.loads(
        (_EXAMPLES / "bounded-fold/model-source.json").read_text()
    )
    inventory = read_extension_inventory(kernel, graph)
    return kernel, graph, inventory


def _links(kernel, graph):
    return set(_source_address_links(kernel, graph))


def _symbol_schema(graph):
    symbol = _source_schema(graph)["properties"]["modules"]["items"]["properties"][
        "symbols"
    ]["items"]
    assert symbol["semantic_role"] == "symbol"
    return symbol


def _symbol_fields(inventory):
    return {
        token
        for token in inventory.tokens
        if token.role == "source-field"
        and token.owner[-3:] == ("member", "symbols", "items")
    }


def _assert_authority_refusal(kernel, authored):
    sealed = _graph(kernel, deepcopy(authored))
    for consumer in (_consumer_a, _consumer_b):
        observed = consumer(kernel, sealed)
        assert not observed["admitted"], (consumer.__name__, observed)
        assert observed["diagnostics"][0] == (
            "static",
            "kernel.vector_mismatch",
            "language.definitions",
        )


def _scoped_rename(graph, inventory, names):
    """Make this bounded witness; unfinished graph roles still prohibit a full rename."""
    values, keys, paths = {}, {}, {}
    assert names.keys() <= inventory.tokens - inventory.reserved
    for occurrence in inventory.occurrences:
        if occurrence.token not in names:
            continue
        name = names[occurrence.token]
        if occurrence.location == "key":
            keys[occurrence.pointer] = name
        elif occurrence.location == "value":
            values[occurrence.pointer] = name
        elif occurrence.location == "json-pointer":
            paths.setdefault(occurrence.pointer, {})[int(occurrence.projection)] = name
        else:
            raise AssertionError(occurrence)
    values.update(_json_pointer_values(graph, paths))
    return _rewrite_positions(graph, values, keys)


def test_source_reverse_validator_does_not_reuse_reader_address_links(
    witness, monkeypatch
):
    kernel, graph, inventory = witness

    def fail_if_reused(*_args, **_kwargs):
        raise AssertionError("validator reused the Source inventory reader")

    monkeypatch.setattr(inventory_support, "_source_address_links", fail_if_reused)
    validate_extension_inventory(kernel, graph, inventory)
    kernel_without_role_graph = deepcopy(kernel)
    kernel_without_role_graph["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["source_notation"].pop("semantic_roles", None)
    validate_source_inventory(kernel_without_role_graph, graph, inventory)


def test_source_reverse_rejects_an_omitted_symbol_field_class(witness, monkeypatch):
    kernel, graph, _ = witness
    original = inventory_support._source_address_links

    def omit_symbol_fields(*args, **kwargs):
        return (
            row
            for row in original(*args, **kwargs)
            if row[0].owner[-3:] != ("member", "symbols", "items")
        )

    monkeypatch.setattr(inventory_support, "_source_address_links", omit_symbol_fields)
    incomplete = read_extension_inventory(kernel, graph)
    with pytest.raises(
        InventoryRefusal, match="Source field address coverage is incomplete"
    ):
        validate_extension_inventory(kernel, graph, incomplete)


def test_model_check_semantic_selectors_do_not_restore_physical_source_paths(witness):
    kernel, graph, inventory = witness
    before = canonical_bytes(graph)
    validate_extension_inventory(kernel, graph, inventory)
    links = _links(kernel, graph)
    checks = list(
        _authority_path_rows(kernel, graph, "language_bundle.language.model_checks")
    )
    assert len(checks) == 5
    for _, check, pointer in checks:
        assert "selector" not in check and "scope_selector" not in check
        for member in ("semantic_selector", "semantic_scope_selector"):
            for index, segment in enumerate(check.get(member, [])):
                found = [
                    row for row in links if row[1] == f"{pointer}/{member}/{index}"
                ]
                assert not found, (member, index, segment, found)
    assert {row["mode"] for _, row, _ in checks} == {"all", "count", "each"}
    assert any(row.get("semantic_scope_selector") for _, row, _ in checks)
    assert not any("model_checks" in gap.law for gap in inventory.uncovered)
    # Actual annotations, not a second list of copied/reserved Source spellings,
    # assign every member of the Symbol role to its freely renameable address.
    symbol = _symbol_schema(graph)
    fields = _symbol_fields(inventory)
    semantic_members = [
        child["semantic_member"] for child in symbol["properties"].values()
    ]
    assert semantic_members
    assert len(semantic_members) == len(set(semantic_members))
    assert {token.name for token in fields} == set(symbol["properties"])
    assert not fields & inventory.reserved
    inventory.require_complete()
    assert canonical_bytes(graph) == before


def test_new_copy_and_branch_occurrences_cannot_be_erased_or_misowned(witness):
    kernel, graph, inventory = witness
    links = _links(kernel, graph)
    # Every annotated Symbol address and same-instance branch remains necessary,
    # including the Source keys and the authored Model-check references.
    position_classes = {}
    for token, pointer, use, location, projection, law in links:
        if token not in _symbol_fields(inventory) or not (
            law == _TRANSPORT or "/oneOf/" in pointer
        ):
            continue
        position = (token, pointer, use, location, projection)
        position_classes.setdefault(position, set()).add(
            (location, use, law == _TRANSPORT, "/oneOf/" in pointer)
        )
    new_positions = set(position_classes)
    required = [
        o
        for o in inventory.occurrences
        if (o.token, o.pointer, o.use, o.location, o.projection) in new_positions
    ]
    assert len(required) == len(new_positions)
    assert {o.token for o in required} == _symbol_fields(inventory)
    assert {o.location for o in required} == {"key", "value"}
    assert any("/oneOf/" in o.pointer for o in required)
    # Exercise every semantic shape without rerunning the complete 21k-row
    # graph verifier once per occurrence. The set equalities above retain the
    # exhaustive member/position proof; the two whole-set mutations prove that
    # the verifier rejects omissions and wrong owners across that closed set.
    assert {shape for classes in position_classes.values() for shape in classes} == {
        ("key", "declaration", False, True),
        ("key", "declaration", True, False),
        ("key", "declaration", True, True),
        ("key", "reference", True, False),
        ("value", "reference", False, True),
        ("value", "reference", True, False),
        ("value", "reference", True, True),
    }
    assert {
        (o.token, o.pointer, o.use, o.location, o.projection) for o in required
    } == set(position_classes)
    required_set = set(required)
    removed = replace(
        inventory,
        occurrences=tuple(o for o in inventory.occurrences if o not in required_set),
    )
    with pytest.raises(InventoryRefusal, match="Source field address coverage"):
        validate_extension_inventory(kernel, graph, removed)
    wrong = {
        occurrence: replace(
            occurrence,
            token=replace(occurrence.token, owner=("unrelated-owner",)),
        )
        for occurrence in required
    }
    misowned = replace(
        inventory,
        tokens=inventory.tokens | {row.token for row in wrong.values()},
        occurrences=tuple(wrong.get(o, o) for o in inventory.occurrences),
    )
    with pytest.raises(InventoryRefusal, match="Source field address coverage"):
        validate_extension_inventory(kernel, graph, misowned)


def test_source_addresses_cannot_be_reserved_or_capture_nominal_payloads(witness):
    kernel, graph, inventory = witness
    fields = _symbol_fields(inventory)
    assert fields and not fields & inventory.reserved
    with pytest.raises(InventoryRefusal, match="Source annotated field ownership"):
        validate_extension_inventory(
            kernel, graph, replace(inventory, reserved=inventory.reserved | fields)
        )
    kind = next(t for t in fields if t.name == "kind")
    nominal_key = next(
        o
        for o in inventory.occurrences
        if o.token.role == "record-field"
        and o.token.name == "kind"
        and o.location == "key"
        and o.pointer.startswith("/vector_sets/")
    )
    with pytest.raises(InventoryRefusal, match="Source field address coverage"):
        validate_extension_inventory(
            kernel,
            graph,
            replace(
                inventory,
                occurrences=(
                    *inventory.occurrences,
                    replace(nominal_key, token=kind),
                ),
            ),
        )
    names = {
        t: f"free_{i}"
        for i, t in enumerate(sorted(inventory.tokens - inventory.reserved))
    }
    pairs = token_bijection_from_names(inventory, names)
    marker = next(
        t for t in inventory.reserved if t.role == "type" and t.name == "Boolean"
    )
    with pytest.raises(InventoryRefusal, match="reserved"):
        validate_token_bijection(
            inventory, (*pairs, (marker, replace(marker, name="opaque_boolean")))
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "domain-rename",
        "extra",
        "symbol-conflict",
        "resolved-conflict",
        "type-conflict",
        "nominal-conflict",
    ],
)
def test_schema_valid_copy_and_adapter_conflicts_do_not_acquire_inventory_ownership(
    witness,
    tmp_path,
    mutation,
):
    kernel, original, inventory = witness
    if mutation == "domain-rename":
        domain = next(t for t in _symbol_fields(inventory) if t.name == "domain")
        candidate = _scoped_rename(original, inventory, {domain: "opaque_domain"})
        sealed = _graph(kernel, candidate)
        for consumer in (_consumer_a, _consumer_b):
            assert consumer(kernel, sealed)["admitted"]
        context = admit_authority_context(kernel, _index(kernel, sealed))
        assert isinstance(context, AdmittedAuthorityContext)
        checked = check_model_source_value(
            candidate["source"], authority_context=context
        )
        assert isinstance(checked, CheckedModel), checked
        assert checked.source_projection.value == original["source"]
        from gda_balancing.domain.model._resolution import ModelSourceContext
        from test_schema2_model_lowerer_conformance import (
            _reference_check_source,
            _reference_semantic_artifacts,
        )

        reference = _reference_check_source(
            candidate["source"], kernel, _index(kernel, sealed)
        )
        assert isinstance(reference, ModelSourceContext), reference
        assert (
            _reference_semantic_artifacts(reference)["rir-semantic-payload"]
            == compile_checked_model(checked)["rir-semantic-payload"]
        )

        from gda_balancing.domain.authority.vector_validation import _fact_is_closed
        from gda_balancing.domain.model._lowering import _resolved_source_symbols

        rows = _resolved_source_symbols(
            checked.source_projection, context.language_bundle, kernel
        )
        lowering = next(
            _authority_path_rows(
                kernel, candidate, "language_bundle.language.model_lowerings"
            )
        )[1]
        facts = [
            {
                "kind": lowering[
                    "structured_initial_fact_kind"
                    if fields.get("value_kind") == "nominal-structured"
                    else "initial_fact_kind"
                ],
                "fields": fields,
            }
            for fields, _ in rows
        ]
        assert len(facts) == len(original["source"]["modules"][0]["symbols"])
        assert all(
            _fact_is_closed(fact, kernel["meta_format"], context.language_bundle)
            for fact in facts
        )
        assert all(
            _consumer_b_fact_is_closed(
                fact, kernel["meta_format"], context.language_bundle
            )
            for fact in facts
        )
        observed = read_extension_inventory(kernel, candidate)
        validate_extension_inventory(kernel, candidate, observed)
        assert observed.uncovered == inventory.uncovered
        public = _PublicCandidate(tmp_path, authorities=(kernel, sealed))
        public.write_source(candidate["source"])
        public.cli("model", "check", str(public.source))
        return
    candidate = deepcopy(original)
    if mutation == "symbol-conflict":
        symbol = next(t for t in _symbol_fields(inventory) if t.name == "symbol")
        candidate = _scoped_rename(original, inventory, {symbol: "opaque_symbol"})
    schema = _symbol_schema(candidate)
    member = {
        "extra": "unowned_fact_field",
        "symbol-conflict": "symbol",
        "resolved-conflict": "resolved_symbol",
        "type-conflict": "type_identity",
        "nominal-conflict": "value_kind",
    }[mutation]
    schema["properties"][member] = {"type": "string"}
    for branch in schema["oneOf"]:
        branch["properties"][member] = {}
    for symbol in candidate["source"]["modules"][0]["symbols"]:
        if mutation != "nominal-conflict" or "domain" not in symbol:
            symbol[member] = "must-not-overwrite-an-adapter"
    assert jsonschema.Draft202012Validator(_source_schema(candidate)).is_valid(
        candidate["source"]
    )
    _assert_authority_refusal(kernel, candidate)
    with pytest.raises(
        InventoryRefusal,
        match="Source does not match its admitted closed wire schema or semantic roles",
    ):
        read_extension_inventory(kernel, candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-leaf",
        "unknown-scope",
        "wildcard-as-field",
        "field-as-wildcard",
        "wildcard-on-object",
        "wrong-lowering-endpoint",
        "opaque-canonical-child",
    ],
)
def test_selector_segments_and_endpoints_cannot_escape_their_declared_owners(
    witness, mutation
):
    kernel, original, _ = witness
    graph = deepcopy(original)
    checks = list(
        _authority_path_rows(kernel, graph, "language_bundle.language.model_checks")
    )
    if mutation == "unknown-leaf":
        checks[0][1]["semantic_selector"][-1] = "no-such-member"
    elif mutation == "unknown-scope":
        next(c for _, c, _ in checks if "semantic_scope_selector" in c)[
            "semantic_scope_selector"
        ][0] = "no-such-scope"
    elif mutation == "wildcard-as-field":
        checks[0][1]["semantic_selector"][1] = "not-an-item"
    elif mutation == "field-as-wildcard":
        checks[0][1]["semantic_selector"][2] = "*"
    elif mutation == "wildcard-on-object":
        checks[0][1]["semantic_selector"].append("*")
    elif mutation == "opaque-canonical-child":
        checks[0][1]["semantic_selector"][-1:] = ["domain", "minimum"]
    else:
        # The retired lowering selector is now the contextual child anchor.
        symbol = _symbol_schema(graph)
        assert symbol["semantic_role"] == "symbol"
        symbol["semantic_role"] = "entrypoint"
        _assert_authority_refusal(kernel, graph)

    with pytest.raises(
        InventoryRefusal,
        match="Source semantic roles do not close|Source schema-address judgement",
    ):
        read_extension_inventory(kernel, graph)


def test_classified_schema_renames_keep_public_mixed_model_and_nominal_ownership(
    witness, tmp_path
):
    kernel, original, inventory = witness
    names = {
        t: {
            "modules": "source/modules~",
            "symbols": "source/declarations~",
            "symbol": "source/name~",
            "type": "source/type~",
        }[t.name]
        for t in inventory.tokens
        if t.role == "source-field"
        and t.name in {"modules", "symbols", "symbol", "type"}
    }
    nominal = AuthorityToken(
        "record-field", ("standard.conformance.structured", "Candidate"), "kind"
    )
    assert nominal in inventory.tokens - inventory.reserved
    candidate = _scoped_rename(original, inventory, names)
    # Nominal fields with the same spelling remain independent of transported
    # Source keys. Unfinished vector families still prohibit full-graph rename.
    physical_before = canonical_bytes(original)
    graph = _graph(kernel, candidate)
    a, b = _consumer_a(kernel, graph), _consumer_b(kernel, graph)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    checked = check_model_source_value(candidate["source"], authority_context=context)
    assert isinstance(checked, CheckedModel), checked
    assert len(compile_checked_model(checked)) == 8
    renamed_inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, renamed_inventory)
    assert nominal in renamed_inventory.tokens - renamed_inventory.reserved
    assert any(
        o.token == nominal and o.location == "key"
        for o in renamed_inventory.occurrences
    )
    assert canonical_bytes(original) == physical_before
    assert renamed_inventory.uncovered == inventory.uncovered
    public = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    public.write_source(candidate["source"])
    public.cli("model", "check", str(public.source))
    build = _members(
        public.cli(
            "model",
            "build",
            str(public.source),
            "--out",
            str(tmp_path / "build"),
            "--invocation-key",
            "cd" * 32,
        )
    )
    rir = build["rir-semantic-payload"]
    rir_path = tmp_path / "rir.json"
    rir_path.write_text(json.dumps(rir))
    spec = json.loads((_EXAMPLES / "bounded-fold/experiment.json").read_text())
    spec["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(json.dumps(spec))
    public.cli("experiment", "check", str(spec_path), "--rir", str(rir_path))
    run = _members(
        public.cli(
            "experiment",
            "run",
            str(spec_path),
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
    admitted = admit_rir(rir, authority_context=context)
    assert isinstance(admitted, AdmittedRir), admitted
    experiment = check_experiment_value(spec, admitted, authority_context=context)
    assert isinstance(experiment, CheckedExperiment), experiment
    assert validate_experiment_artifact_set(experiment, run)


@pytest.mark.parametrize(
    "member",
    ["unadapted_members", "adapters", "adapter_conflicts", "initial_fact_admission"],
)
def test_source_address_ownership_requires_the_complete_fixed_transport(
    witness, member
):
    kernel, graph, _ = witness
    changed = deepcopy(kernel)
    del changed["meta_format"]["language_definitions"]["collections"][
        "model_lowerings"
    ]["source_fact_transport"][member]
    with pytest.raises(InventoryRefusal, match="transport law is unsupported"):
        _links(changed, graph)


def test_branch_only_source_member_cannot_escape_initial_fact_ownership(witness):
    kernel, original, _ = witness
    candidate = deepcopy(original)
    symbol = _symbol_schema(candidate)
    # Keep the unknown field only in same-instance branches and the real Source.
    for branch in symbol["oneOf"]:
        branch["properties"]["unowned_fact_field"] = {
            "type": "string",
            "semantic_member": "unowned_fact_field",
        }
    for row in candidate["source"]["modules"][0]["symbols"]:
        row["unowned_fact_field"] = "unowned"
    before = canonical_bytes(candidate)
    assert jsonschema.Draft202012Validator(_source_schema(candidate)).is_valid(
        candidate["source"]
    )
    _assert_authority_refusal(kernel, candidate)
    with pytest.raises(
        InventoryRefusal,
        match="Source semantic roles do not close",
    ):
        read_extension_inventory(kernel, candidate)
    assert canonical_bytes(candidate) == before


def test_branch_only_declared_fact_field_cannot_replace_its_anchor_member(witness):
    kernel, original, _ = witness
    candidate = deepcopy(original)
    schema = _source_schema(candidate)
    symbol = _symbol_schema(candidate)
    domain = symbol["properties"].pop("domain")
    symbol["oneOf"][0]["properties"]["domain"] = domain
    before = canonical_bytes(candidate)
    assert jsonschema.Draft202012Validator(schema).is_valid(candidate["source"])
    # The semantic-role anchor owns one complete, stable member address set.
    # A branch cannot replace its missing top-level native member declaration.
    _assert_authority_refusal(kernel, candidate)
    assert canonical_bytes(candidate) == before


@pytest.mark.parametrize(
    "mutation", ["missing-member", "duplicate-member", "native-shape"]
)
def test_source_member_annotations_and_native_shape_are_not_inventory_exemptions(
    witness, mutation
):
    kernel, original, _ = witness
    candidate = deepcopy(original)
    symbol = _symbol_schema(candidate)
    domain = symbol["properties"]["domain"]
    if mutation == "missing-member":
        del domain["semantic_member"]
    elif mutation == "duplicate-member":
        domain["semantic_member"] = "domain_kind"
    else:
        domain["properties"]["minimum"]["type"] = "string"
        for row in candidate["source"]["modules"][0]["symbols"]:
            if "domain" in row:
                row["domain"]["minimum"] = str(row["domain"]["minimum"])
    assert jsonschema.Draft202012Validator(_source_schema(candidate)).is_valid(
        candidate["source"]
    )
    _assert_authority_refusal(kernel, candidate)


@pytest.mark.parametrize(
    "names",
    [{"symbol": "type", "type": "symbol"}, {"symbol": "type", "type": "opaque_type"}],
    ids=["swap-symbol-type", "symbol-name-as-type"],
)
def test_schema_input_roles_survive_symbol_and_type_name_exchange(
    witness, tmp_path, names
):
    from gda_balancing.domain.model._compilation import lower_checked_model
    from gda_balancing.domain.model._resolution import ModelSourceContext
    from test_schema2_model_lowerer_conformance import _reference_check_source

    kernel, original, inventory = witness
    targets = {
        t: names[t.name]
        for t in inventory.tokens
        if t.role == "source-field" and t.name in names and "symbols" in t.owner
    }
    expected = []
    candidate = _scoped_rename(original, inventory, targets)
    for graph in (deepcopy(original), candidate):
        sealed = _graph(kernel, graph)
        a, b = _consumer_a(kernel, sealed), _consumer_b(kernel, sealed)
        assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
        index = _index(kernel, sealed)
        context = admit_authority_context(kernel, index)
        assert isinstance(context, AdmittedAuthorityContext)
        checked = check_model_source_value(graph["source"], authority_context=context)
        assert isinstance(checked, CheckedModel), checked
        assert isinstance(
            _reference_check_source(graph["source"], kernel, index), ModelSourceContext
        )
        expected.append(
            lower_checked_model(checked)["rir-semantic-payload"]["semantic_identity"]
        )
    assert expected[0] == expected[1]
    public = _PublicCandidate(tmp_path, authorities=(kernel, sealed))
    public.write_source(candidate["source"])
    public.cli("model", "check", str(public.source))
    observed = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, observed)
    assert observed.uncovered == inventory.uncovered
    # Reverse validation already assigns these inputs their semantic roles;
    # co-mutate each same-spelling input to the other valid role and require refusal.
    inputs = [
        o
        for o in observed.occurrences
        if o.pointer.startswith("/source/modules/0/symbols/0/")
        and o.location == "value"
        and o.token.role in {"source-symbol", "source-type-alias"}
    ]
    assert {o.token.role for o in inputs} == {"source-symbol", "source-type-alias"}
    assert len(inputs) == 2 and inputs[0].token.name == inputs[1].token.name
    for i, occurrence in enumerate(inputs):
        wrong = replace(occurrence, token=inputs[1 - i].token)
        forged = replace(
            observed,
            occurrences=tuple(
                wrong if o == occurrence else o for o in observed.occurrences
            ),
        )
        with pytest.raises(InventoryRefusal, match="missing or incorrectly owned"):
            validate_extension_inventory(kernel, candidate, forged)
