"""Only the declared Operation notation address is outside runtime semantics."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, cast

import pytest

import gda_balancing.domain.authority.admission as production_admission
import schema2_bootstrap_conformance_support as independent_admission
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.authority.package_semantics import (
    package_runtime_semantic_closure,
)
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from gda_balancing.domain.formula.notation import (
    admit_formula_pair,
    parse_formula_expression,
    render_formula_body,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from schema2_formula_conformance_support import admit_pair, parse_canonical, render_body
from test_current_namespace_public import _PublicCandidate
from test_rir_protocol_structure import public_rir as public_rir
from test_trace_protocol_structure import _authored, _graph, _index


_SOURCE = (
    Path(__file__).parents[1] / "examples/schema2/rpg-combat-cast/model-source.json"
)


@pytest.mark.parametrize(
    ("owner", "excluded"),
    [
        ("game.combat", []),
        ("core.quantity", ["standard.formula-notation"]),
        ("game.combat", ["standard.formula-slots"]),
    ],
    ids=["empty", "notation", "executed-slots"],
)
def test_authored_package_exclusion_refuses_before_public_compilation(
    tmp_path, owner, excluded
):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    package = next(row for row in authored["packages"] if row["id"] == owner)
    package["runtime_semantic_excluded_extensions"] = excluded
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result
        assert any(
            stage == "ingress" and code == "kernel.member_set_mismatch"
            for stage, code, _ in result["diagnostics"]
        )
    candidate = _PublicCandidate(tmp_path, authorities=(kernel, graph))
    candidate.write_source(json.loads(_SOURCE.read_text()))
    for command in ("check", "build"):
        arguments = ["model", command, str(candidate.source)]
        if command == "build":
            arguments += [
                "--out",
                str(tmp_path / "build"),
                "--invocation-key",
                "bc" * 32,
            ]
        result = candidate.cli(*arguments, success=False)
        assert candidate.receipts[-1]["returncode"] == 2
        assert result["error"]["stage"] == "ingress"
        assert any(
            row["code"] == "kernel.member_set_mismatch"
            for row in result["error"]["diagnostics"]
        )


def test_actual_execution_retains_formula_slot_values_and_evidence(public_rir):
    _, rir, _, artifacts = public_rir
    operation = next(
        row["definition"]
        for row in rir["selected_semantics"]["operations"]
        if row["package"] == "game.combat"
        and row["definition"]["id"] == "game.combat.damage-v1"
    )
    slots = operation["extensions"]["standard.formula-slots"]
    assert any(slot["id"] == "damage-policy" for slot in slots)
    observations = [
        row
        for event in artifacts["event-trace"]["events"]
        for row in event["formula_evaluations"]
        if row["slot"] == "damage-policy"
    ]
    assert [(row["arguments"], row["result"]) for row in observations] == [
        (
            [
                {"parameter": "damage_before_defense", "value": 45},
                {"parameter": "mitigation", "value": 8},
            ],
            37,
        ),
        (
            [
                {"parameter": "damage_before_defense", "value": 20},
                {"parameter": "mitigation", "value": 6},
            ],
            14,
        ),
    ]
    first = observations[0]
    assert first["arguments"] == [
        {"parameter": "damage_before_defense", "value": 45},
        {"parameter": "mitigation", "value": 8},
    ]
    assert first["result"] == 37
    assert first["operation"]["package"] == "game.combat"
    assert first["operation"]["id"] == operation["id"]
    assert first["evaluation_site_identity"] == next(
        binding["site"]["identity"]
        for binding in rir["formula_bindings"]
        if binding["site"].get("slot") == "damage-policy"
    )


def test_supplied_kernel_notation_address_rename_preserves_opaque_data(monkeypatch):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    owner = kernel["meta_format"]["language_definitions"]["wire_schema_protocol_roles"][
        "source_notation"
    ]["operation_source"]
    old = owner["extension_member"]
    renamed = "opaque~/notation.address"
    owner["extension_member"] = renamed
    count = 0
    for package in authored["packages"]:
        for closure in package["semantic_closure"]:
            if closure["authority_path"] != owner["authority_path"]:
                continue
            for operation in closure["definitions"]:
                extensions = operation.get("extensions", {})
                if old in extensions:
                    extensions[renamed] = extensions.pop(old)
                    count += 1
    assert count > 0
    # These vectors observe the complete extensions object. Rename the same
    # declared address in that authored observation, preserving its entire value.
    for vector_set in authored["vector_sets"]:
        for vector in vector_set["vector_definitions"]:
            if (
                vector.get("kind") == "operation-contract"
                and vector.get("probe") == {"path": "extensions"}
                and old in vector["expect"]
            ):
                vector["expect"][renamed] = vector["expect"].pop(old)
    kernel["content_identity"] = content_identity(
        "schema-major-kernel-v2",
        {key: value for key, value in kernel.items() if key != "content_identity"},
    )
    # This is a supplied-Kernel law variant: declare compatibility for both actual
    # implementations, without replacing their admission or projection algorithms.
    for implementation in (production_admission, independent_admission):
        monkeypatch.setattr(
            implementation, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
        )
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result["diagnostics"]
    admitted = _index(kernel, graph)
    context = admit_authority_context(kernel, admitted)
    assert isinstance(context, AdmittedAuthorityContext), context
    # Add opaque data only to a detached projection input; the admitted graph
    # above and the actual Formula consumers below use the coherent rename.
    quantity = next(
        package
        for package in deepcopy(authored["packages"])
        if package["id"] == "core.quantity"
    )
    operation = next(
        value
        for closure in quantity["semantic_closure"]
        if closure["authority_path"] == owner["authority_path"]
        for value in closure["definitions"]
        if value["id"] == "quantity.add"
    )
    opaque = {old: {renamed: ["version", "package", "id"]}, renamed: [3, 1, 2]}
    operation["extensions"]["example.opaque-data"] = deepcopy(opaque)
    numeric_policy = next(
        value
        for closure in quantity["semantic_closure"]
        if closure["authority_path"] == "language.quantity.numeric_policies"
        for value in closure["definitions"]
    )
    numeric_policy["extensions"] = {renamed: deepcopy(opaque)}
    projected = cast(
        list[dict[str, Any]], package_runtime_semantic_closure(quantity, kernel)
    )
    projected_operation = next(
        value
        for closure in projected
        if closure["authority_path"] == owner["authority_path"]
        for value in closure["definitions"]
        if value["id"] == operation["id"]
    )
    assert renamed not in projected_operation["extensions"]
    assert canonical_bytes(
        projected_operation["extensions"]["example.opaque-data"]
    ) == canonical_bytes(opaque)
    projected_numeric_policy = next(
        value
        for closure in projected
        if closure["authority_path"] == "language.quantity.numeric_policies"
        for value in closure["definitions"]
        if value["id"] == numeric_policy["id"]
    )
    assert projected_numeric_policy == numeric_policy
    source = json.loads(_SOURCE.read_text())
    witnessed = 0
    for module in source["modules"]:
        for formula in module["formulas"]:
            request = {
                "schema_version": source["schema_version"],
                "package_requirements": source["package_requirements"],
                "modules": source["modules"],
                "module": module,
                "formula": formula,
            }
            a = parse_formula_expression(request, context)
            b = parse_canonical(formula["expression"], request, admitted, kernel=kernel)
            assert (
                canonical_bytes(a)
                == canonical_bytes(b)
                == canonical_bytes(formula["body"])
            )
            assert (
                render_formula_body(a, context)
                == render_body(b, request, admitted, kernel=kernel)
                == formula["expression"]
            )
            admit_formula_pair(request, context)
            assert admit_pair(request, admitted, kernel=kernel)
            witnessed += 1
    assert witnessed > 0
