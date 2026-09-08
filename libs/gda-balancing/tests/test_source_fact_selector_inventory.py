"""Source selector ownership follows typed addresses and initial Fact transport."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

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
from schema2_bootstrap_conformance_support import _consumer_b
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
    _member_path_values,
    _rewrite_positions,
)
from test_current_namespace_public import _PublicCandidate, _members
from test_source_fact_transport import _fixture
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
    copied = set()
    links = set(_source_address_links(kernel, graph, copied_fields=copied))
    return links, copied


def _scoped_rename(graph, inventory, names):
    """Make this bounded witness; unfinished graph roles still prohibit a full rename."""
    values, keys, paths, member_paths = {}, {}, {}, {}
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
        elif occurrence.location == "member-path":
            member_paths.setdefault(occurrence.pointer, {})[
                int(occurrence.projection)
            ] = name
        else:
            raise AssertionError(occurrence)
    values.update(_json_pointer_values(graph, paths))
    values.update(_member_path_values(graph, member_paths))
    return _rewrite_positions(graph, values, keys)


def test_every_model_check_segment_and_endpoint_has_an_actual_source_owner(witness):
    kernel, graph, inventory = witness
    before = canonical_bytes(graph)
    validate_extension_inventory(kernel, graph, inventory)
    links, copied = _links(kernel, graph)
    checks = list(
        _authority_path_rows(kernel, graph, "language_bundle.language.model_checks")
    )
    assert len(checks) == 5
    for _, check, pointer in checks:
        for member in ("selector", "scope_selector"):
            for index, segment in enumerate(check.get(member, [])):
                found = [
                    row for row in links if row[1] == f"{pointer}/{member}/{index}"
                ]
                assert len(found) == (0 if segment == "*" else 1)
    assert {row["mode"] for _, row, _ in checks} == {"all", "count", "each"}
    assert any(row.get("scope_selector") for _, row, _ in checks)
    assert not any("model_checks" in gap.law for gap in inventory.uncovered)
    # The remaining artifact, Template, profile and program gaps stay explicit.
    assert len(inventory.uncovered) == 40
    assert {token.name for token in copied} == {
        "domain",
        "domain_kind",
        "kind",
        "numeric_policy",
        "representation",
        "role",
        "unit",
        "value_policy",
    }
    assert copied <= inventory.reserved
    assert canonical_bytes(graph) == before


def test_new_copy_and_branch_occurrences_cannot_be_erased_or_misowned(witness):
    kernel, graph, inventory = witness
    links, _ = _links(kernel, graph)
    # Main profile addresses already had reverse coverage. The new copy links
    # and same-instance Schema branches must each independently be necessary.
    new_positions = {
        (token, pointer, use, location, projection)
        for token, pointer, use, location, projection, law in links
        if law == _TRANSPORT or "/oneOf/" in pointer
    }
    required = [
        o
        for o in inventory.occurrences
        if (o.token, o.pointer, o.use, o.location, o.projection) in new_positions
    ]
    assert len(required) == len(new_positions) == 69
    for occurrence in required:
        removed = replace(
            inventory,
            occurrences=tuple(o for o in inventory.occurrences if o != occurrence),
        )
        with pytest.raises(InventoryRefusal, match="Source field address coverage"):
            validate_extension_inventory(kernel, graph, removed)
        wrong = replace(
            occurrence, token=replace(occurrence.token, owner=("unrelated-owner",))
        )
        misowned = replace(
            inventory,
            tokens=inventory.tokens | {wrong.token},
            occurrences=tuple(
                wrong if o == occurrence else o for o in inventory.occurrences
            ),
        )
        with pytest.raises(InventoryRefusal, match="Source field address coverage"):
            validate_extension_inventory(kernel, graph, misowned)


def test_copy_reservation_cannot_be_removed_or_applied_to_a_profile_adapter(witness):
    kernel, graph, inventory = witness
    _, copied = _links(kernel, graph)
    adapted = next(
        t for t in inventory.tokens if t.role == "source-field" and t.name == "symbol"
    )
    for reserved in (inventory.reserved - copied, inventory.reserved | {adapted}):
        with pytest.raises(InventoryRefusal, match="copied/adapted"):
            validate_extension_inventory(
                kernel, graph, replace(inventory, reserved=frozenset(reserved))
            )
    source_names = {
        t: f"free_{i}"
        for i, t in enumerate(sorted(inventory.tokens - inventory.reserved))
    }
    kind = next(t for t in copied if t.name == "kind")
    nominal_key = next(
        o
        for o in inventory.occurrences
        if o.token.role == "record-field"
        and o.token.name == "kind"
        and o.location == "key"
        and o.pointer.startswith("/vector_sets/")
    )
    # Equal bytes in a real typed nominal payload do not transport a Source key.
    with pytest.raises(InventoryRefusal, match="value vector occurrence"):
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
    domain = next(t for t in copied if t.name == "domain")
    pairs = token_bijection_from_names(inventory, source_names)
    with pytest.raises(InventoryRefusal, match="reserved"):
        validate_token_bijection(
            inventory, (*pairs, (domain, replace(domain, name="opaque_domain")))
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
    mutation,
):
    kernel, graph, source, _ = _fixture(mutation, renamed=mutation == "symbol-conflict")
    independent = _consumer_b(kernel, graph)
    assert independent["admitted"], independent["diagnostics"]
    authored = {**_authored(graph), "source": source}
    with pytest.raises(InventoryRefusal, match="Source copy"):
        read_extension_inventory(kernel, authored)


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
        checks[0][1]["selector"][-1] = "no-such-member"
    elif mutation == "unknown-scope":
        next(c for _, c, _ in checks if "scope_selector" in c)["scope_selector"][0] = (
            "no-such-scope"
        )
    elif mutation == "wildcard-as-field":
        checks[0][1]["selector"][1] = "not-an-item"
    elif mutation == "field-as-wildcard":
        inventory = witness[2]
        member = next(
            t
            for t in inventory.tokens
            if t.role == "source-field" and t.name == "modules"
        )
        graph = _scoped_rename(original, inventory, {member: "*"})
    elif mutation == "wildcard-on-object":
        checks[0][1]["selector"].append("*")
    elif mutation == "opaque-canonical-child":
        checks[0][1]["selector"][-1:] = ["value_policy", "mode"]
    else:
        lowering = next(
            _authority_path_rows(
                kernel, graph, "language_bundle.language.model_lowerings"
            )
        )[1]
        lowering["source_selector"].pop()
    with pytest.raises(
        InventoryRefusal, match="Source selector|Source lowering selector"
    ):
        read_extension_inventory(kernel, graph)


def test_classified_profile_renames_keep_public_mixed_model_and_nominal_ownership(
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
    assert len(renamed_inventory.uncovered) == 40
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


def test_branch_only_source_member_cannot_escape_initial_fact_ownership():
    # Spec's exact candidate: keep the real Source key and its oneOf
    # declarations, removing only the duplicate top-level property declaration.
    from test_source_fact_transport import _definitions
    import jsonschema

    kernel, graph, source, _ = _fixture("extra")
    candidate = {**_authored(graph), "source": source}
    schema = next(
        row["schema"]
        for row in _definitions(candidate, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )
    symbol = schema["properties"]["modules"]["items"]["properties"]["symbols"]["items"]
    del symbol["properties"]["unowned_fact_field"]
    sealed = _graph(kernel, candidate)
    before = canonical_bytes(candidate)
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(source))
    a, b = _consumer_a(kernel, sealed), _consumer_b(kernel, sealed)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    with pytest.raises(
        InventoryRefusal, match="Source copy has no initial Fact field owner"
    ):
        read_extension_inventory(kernel, candidate)
    assert canonical_bytes(candidate) == before


def test_branch_only_declared_fact_field_retains_real_selector_ownership(witness):
    from test_source_fact_transport import _definitions
    import jsonschema

    kernel, original, _ = witness
    candidate = deepcopy(original)
    schema = next(
        row["schema"]
        for row in _definitions(candidate, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )
    symbol = schema["properties"]["modules"]["items"]["properties"]["symbols"]["items"]
    domain = symbol["properties"].pop("domain")
    symbol["oneOf"][0]["properties"]["domain"] = domain
    sealed = _graph(kernel, candidate)
    before = canonical_bytes(candidate)
    assert not list(
        jsonschema.Draft202012Validator(schema).iter_errors(candidate["source"])
    )
    a, b = _consumer_a(kernel, sealed), _consumer_b(kernel, sealed)
    assert a["admitted"] and b["admitted"], (a["diagnostics"], b["diagnostics"])
    context = admit_authority_context(kernel, _index(kernel, sealed))
    assert isinstance(context, AdmittedAuthorityContext)
    assert isinstance(
        check_model_source_value(candidate["source"], authority_context=context),
        CheckedModel,
    )
    inventory = read_extension_inventory(kernel, candidate)
    validate_extension_inventory(kernel, candidate, inventory)
    owned = next(
        t for t in inventory.reserved if t.role == "source-field" and t.name == "domain"
    )
    links = [o for o in inventory.occurrences if o.token == owned]
    assert any("/oneOf/0/properties/domain" in o.pointer for o in links)
    assert any(o.pointer.endswith("/selector/4") for o in links)
    assert any(o.pointer.startswith("/source/") for o in links)
    assert canonical_bytes(candidate) == before
    assert inventory.uncovered == witness[2].uncovered


@pytest.mark.parametrize(
    "names",
    [{"symbol": "type", "type": "symbol"}, {"symbol": "type", "type": "opaque_type"}],
    ids=["swap-symbol-type", "symbol-name-as-type"],
)
def test_profile_input_roles_survive_symbol_and_type_name_exchange(
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
    # Reverse validation already assigns these inputs their profile roles;
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
