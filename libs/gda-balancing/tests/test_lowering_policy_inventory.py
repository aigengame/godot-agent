"""Lowering keeps executable owners and removes redundant policy declarations."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import (
    _consumer_b,
    _encoded,
    _consumer_b_runtime_projection_is_closed,
)
from schema2_bootstrap_production_support import _consumer_a
from schema2_extension_inventory_support import (
    AuthorityToken,
    InventoryRefusal,
    UncoveredRole,
    _json_pointer_segments,
    read_extension_inventory,
    validate_extension_inventory,
)
from gda_balancing.domain.authority.admission import _runtime_projection_is_closed
from gda_balancing.domain.artifacts import artifacts_by_protocol_role, verify_artifact
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.model import admit_resolved_model
from gda_balancing.domain.model._resolution import ModelSourceContext
from test_bounded_fold_public import _source
from test_current_namespace_public import _PublicCandidate, _members
from test_schema2_model_lowerer_conformance import (
    _reference_admits_semantic_artifacts,
    _reference_check_source,
    _reference_semantic_artifacts,
)
from test_trace_protocol_structure import _authored, _graph, _index


def _lowering(authored):
    return next(
        row
        for package in authored["packages"]
        for closure in package["semantic_closure"]
        if closure["authority_path"] == "language.model_lowerings"
        for row in closure["definitions"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "composition_policy",
            {
                "effects": {
                    "aggregation": "union",
                    "containment": "callee-subset-of-caller-declaration",
                },
                "refusals": {
                    "aggregation": "union",
                    "containment": "callee-subset-of-caller-declaration",
                },
                "resources": {
                    "aggregation": "sum",
                    "containment": "transitive-charge-within-caller-bound",
                },
            },
        ),
        ("coordinate_members", ["package", "id"]),
        ("structural_kind_member", "kind"),
        ("duplicate_actual_policy", "collapse"),
        ("scenario_target_cardinality", "one-per-resolved-actual"),
    ],
)
def test_retired_lowering_policy_fields_refuse_after_correct_reseal(field, value):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    lowering = _lowering(authored)
    target = (
        lowering
        if field == "composition_policy"
        else lowering["runtime_projection"]["type_reference_closure"]
        if field in {"coordinate_members", "structural_kind_member"}
        else lowering["assignment_policy"]
    )
    target[field] = deepcopy(value)
    candidate = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, candidate)
        assert not result["admitted"], (field, result)
        assert set(result["diagnostics"]) == {
            ("static", "kernel.vector_mismatch", "language.definitions")
        }


@pytest.fixture(scope="module")
def inventory_case():
    kernel, language = mutable_authorities()
    authored = _authored(language)
    authored["source"] = _source()
    inventory = read_extension_inventory(kernel, authored)
    validate_extension_inventory(kernel, authored, inventory)
    return kernel, authored, inventory


def test_lowering_closes_only_its_actual_contract_and_keeps_other_gaps(inventory_case):
    _, _, inventory = inventory_case
    assert inventory.uncovered
    assert not any(
        "nested language.model_lowerings" in gap.reason for gap in inventory.uncovered
    )
    assert not any(
        "type_reference_closure" in gap.pointer for gap in inventory.uncovered
    )
    assert any("wire_schemas" in gap.reason for gap in inventory.uncovered)
    paths = {
        row.pointer
        for row in inventory.occurrences
        if row.token.role == "kernel.lowering-address"
    }
    assert any(path.endswith("/output_equalities/0/right/1") for path in paths)
    assert any(path.endswith("/edges/1/target_path/1") for path in paths)
    assert any(path.endswith("/seeds/0/declaration_path/1") for path in paths)
    assert any(path.endswith("/entrypoint_operand_access/0") for path in paths)


@pytest.mark.parametrize(
    "defect",
    [
        "omit",
        "omit-class",
        "wrong-owner",
        "unreserve",
        "extra-reserved",
        "reserve-nominal",
        "invent-owner-gap",
    ],
)
def test_lowering_inverse_checks_exact_address_owner_and_reservation(
    inventory_case, defect
):
    kernel, authored, inventory = inventory_case
    row = next(
        o
        for o in inventory.occurrences
        if o.pointer.endswith("/output_equalities/0/right/1")
    )
    if defect in {"omit", "omit-class"}:
        occurrences = tuple(
            o
            for o in inventory.occurrences
            if (
                o != row
                if defect == "omit"
                else o.token.role != "kernel.lowering-address"
            )
        )
        tokens = frozenset(o.token for o in occurrences)
        changed = replace(
            inventory,
            tokens=tokens,
            occurrences=occurrences,
            reserved=inventory.reserved & tokens,
        )
    elif defect == "wrong-owner":
        wrong = replace(row.token, owner=("/meta_format/unrelated",))
        occurrences = tuple(
            replace(o, token=wrong) if o == row else o for o in inventory.occurrences
        )
        tokens = frozenset(o.token for o in occurrences)
        changed = replace(
            inventory,
            tokens=tokens,
            reserved=(inventory.reserved & tokens) | {wrong},
            occurrences=occurrences,
        )
    elif defect == "unreserve":
        changed = replace(inventory, reserved=inventory.reserved - {row.token})
    elif defect == "invent-owner-gap":
        changed = replace(
            inventory,
            uncovered=inventory.uncovered
            + (
                UncoveredRole(
                    row.pointer, "/meta_format/runtime_projection", "invented owner gap"
                ),
            ),
        )
    elif defect == "reserve-nominal":
        nominal = next(t for t in inventory.tokens if t.role == "assignment-policy")
        changed = replace(inventory, reserved=inventory.reserved | {nominal})
    else:
        changed = replace(
            inventory, reserved=inventory.reserved | {replace(row.token, name="forged")}
        )
    with pytest.raises(InventoryRefusal):
        validate_extension_inventory(kernel, authored, changed)


@pytest.mark.parametrize(
    "part", ["equality", "seed", "edge", "assignment-access", "rule"]
)
def test_lowering_reader_refuses_unowned_interpreted_fields(part):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    lowering = _lowering(authored)
    if part == "equality":
        lowering["output_equalities"][0]["right"] = ["resolved_symbol", "missing"]
    elif part == "seed":
        lowering["runtime_projection"]["seeds"][0]["target_path"] = ["missing"]
    elif part == "edge":
        lowering["runtime_projection"]["edges"][0]["target_path"] = ["missing"]
    elif part == "assignment-access":
        lowering["assignment_policy"]["roles"][0]["entrypoint_operand_access"] = [
            "invented"
        ]
    else:
        lowering["rule_chain"][0]["judgment"] = "lower-quantity"
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(kernel, authored)


def test_lowering_declaration_labels_rename_with_four_public_artifacts(
    tmp_path, inventory_case
):
    kernel, original, inventory = inventory_case
    observations = []
    for renamed in (False, True):
        authored = deepcopy(original)
        if renamed:
            names = {
                token: (
                    "required"
                    if token.role == "assignment-policy"
                    else f"lowering.label.{i}"
                )
                for i, token in enumerate(sorted(inventory.tokens))
                if token.role
                in {
                    "language.model_lowerings",
                    "assignment-policy",
                    "projection-collection",
                }
            }
            assert len(names) == 18
            for row in inventory.occurrences:
                if row.token not in names:
                    continue
                assert row.location == "value"
                parts = _json_pointer_segments(row.pointer)
                value = authored
                for part in parts[:-1]:
                    value = value[int(part)] if isinstance(value, list) else value[part]
                value[int(parts[-1]) if isinstance(value, list) else parts[-1]] = names[
                    row.token
                ]
        source = authored["source"]
        graph = _graph(kernel, authored)
        for consumer in (_consumer_a, _consumer_b):
            result = consumer(kernel, graph)
            assert result["admitted"], result["diagnostics"]
        index = _index(kernel, graph)
        checked = _reference_check_source(source, kernel, index)
        assert isinstance(checked, ModelSourceContext), checked
        reference = _reference_semantic_artifacts(checked)
        assert len(reference) == 4
        public = _PublicCandidate(
            tmp_path / ("renamed" if renamed else "original"),
            authorities=(kernel, graph),
        )
        public.write_source(source)
        public.cli("model", "check", str(public.source))
        produced = artifacts_by_protocol_role(
            index,
            _members(
                public.cli(
                    "model",
                    "build",
                    str(public.source),
                    "--out",
                    str(public.directory / "build"),
                    "--invocation-key",
                    "ed" * 32,
                )
            ),
        )
        assert all(
            _encoded(produced[role]) == _encoded(value)
            for role, value in reference.items()
        )
        assert _reference_admits_semantic_artifacts(produced, checked)
        context = admit_authority_context(kernel, index)
        assert isinstance(context, AdmittedAuthorityContext)
        assert all(verify_artifact(value, index) for value in reference.values())
        assert admit_resolved_model(
            {
                role: reference[role]
                for role in ("package-lock", "rir-semantic-payload", "resolved-model")
            },
            authority_context=context,
        ).admitted
        public.directory.joinpath("independent-artifacts.json").write_text(
            json.dumps(reference, indent=2) + "\n"
        )
        reread = read_extension_inventory(kernel, authored)
        validate_extension_inventory(kernel, authored, reread)
        if renamed:
            token = AuthorityToken(
                "assignment-policy", (_lowering(authored)["id"],), "required"
            )
            assert token in reread.tokens - reread.reserved
            assert any(t.name == "required" for t in reread.reserved)
        observations.append(reference["rir-semantic-payload"])
    assert observations[0] == observations[1]


@pytest.mark.parametrize(
    "defect",
    [
        "missing-definition",
        "missing-constructor",
        "wrong-definition",
        "wrong-constructor",
        "wrong-relation",
    ],
)
def test_structural_type_match_has_one_closed_kernel_owner(defect):
    kernel, language = mutable_authorities()
    projection = language["language"]["model_lowerings"][0]["runtime_projection"]
    meta = kernel["meta_format"]

    def closed(consumer, actual):
        return consumer(
            projection,
            actual["runtime_projection"],
            language,
            actual["fact"]["field_contracts"]["quantity-symbol"],
            actual["language_definitions"],
            actual,
        )

    for consumer in (
        _runtime_projection_is_closed,
        _consumer_b_runtime_projection_is_closed,
    ):
        assert closed(consumer, meta)
    altered = deepcopy(meta)
    match = altered["runtime_projection"]["type_reference_closure"]["structural_match"]
    if defect.startswith("missing-"):
        del match[defect.removeprefix("missing-") + "_kind_member"]
    elif defect == "wrong-relation":
        match["relation"] = "unrelated"
    else:
        match[defect.removeprefix("wrong-") + "_kind_member"] = "unrelated"
    for consumer in (
        _runtime_projection_is_closed,
        _consumer_b_runtime_projection_is_closed,
    ):
        assert not closed(consumer, altered)
    with pytest.raises(InventoryRefusal):
        read_extension_inventory(
            {**kernel, "meta_format": altered}, _authored(language)
        )
