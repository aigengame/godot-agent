"""Explanation wire structure follows the compiled facts it actually inspects."""

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from gda_balancing.domain.artifacts import _identified_artifact, verify_artifact
from gda_balancing.domain.authority.model_projection import model_protocol_schema
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source,
    compile_checked_model,
    validate_compiled_artifacts,
)
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _consumer_b_model_schema
from schema2_bootstrap_production_support import _consumer_a
from schema2_model_companions_independent_support import (
    reference_model_artifacts,
    reference_admits_model_artifacts,
)
from test_schema2_model_lowerer_conformance import (
    _reference_check_source,
    ModelSourceContext,
)
from test_model_protocol_structure import _model_rows
from test_trace_protocol_structure import _authored, _graph


def test_explanation_has_one_kernel_owner_and_independent_rir_projection(monkeypatch):
    kernel, ldb = mutable_authorities()
    definition, contract = _model_rows(_authored(ldb), "model-explanation")
    assert set(definition) == {"artifact_kind", "protocol_role"}
    schema = model_protocol_schema(
        kernel, "model-explanation", contract["artifact_kind"], language=ldb["language"]
    )
    assert schema == _consumer_b_model_schema(
        kernel, "model-explanation", contract["artifact_kind"], language=ldb["language"]
    )

    from gda_balancing.domain.authority.context import packaged_authority_context
    from test_model_namespace_structure import _assert_owned_mutable_schema

    frozen = packaged_authority_context()
    for project in (model_protocol_schema, _consumer_b_model_schema):
        _assert_owned_mutable_schema(
            project(
                frozen.kernel,
                "model-explanation",
                contract["artifact_kind"],
                language=frozen.language_bundle["language"],
            )
        )

    def forbidden(*args, **kwargs):
        pytest.fail("B called production RIR or Model Schema projection")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.model_projection.model_protocol_schema",
        forbidden,
    )
    monkeypatch.setattr(
        "gda_balancing.domain.authority.model_projection.rir_protocol_schema", forbidden
    )
    assert _consumer_b(kernel, _graph(kernel, _authored(ldb)))["admitted"]


@pytest.mark.parametrize("mutation", ("shadow", "missing-role", "duplicate-role"))
def test_explanation_physical_override_and_ambiguous_owner_refuse(mutation):
    from gda_balancing.domain.artifacts import select_protocol_artifact_contract

    kernel, ldb = mutable_authorities()
    authored = _authored(ldb)
    definition, _ = _model_rows(authored, "model-explanation")
    if mutation == "shadow":
        definition["schema"] = deepcopy(
            select_protocol_artifact_contract(ldb, "model-explanation").schema
        )
    elif mutation == "missing-role":
        del definition["protocol_role"]
    else:
        _model_rows(authored, "debug-map")[0]["protocol_role"] = "model-explanation"
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        assert not consumer(kernel, graph)["admitted"]


@pytest.mark.parametrize("project", (model_protocol_schema, _consumer_b_model_schema))
def test_explanation_requires_actual_supplied_language(project):
    kernel, _ = mutable_authorities()
    with pytest.raises(ValueError, match="actual"):
        project(kernel, "model-explanation", "model-explanation")


@pytest.fixture(scope="module")
def explanation_pairs():
    result = {}
    for model in ("progression-periodic-effect", "structured-selection"):
        path = (
            Path(__file__).parents[1] / "examples/schema2" / model / "model-source.json"
        )
        checked = check_model_source(str(path))
        assert isinstance(checked, CheckedModel), checked
        reference = _reference_check_source(
            json.loads(path.read_bytes()), checked.kernel, checked.language_bundle
        )
        assert isinstance(reference, ModelSourceContext), reference
        original = compile_checked_model(checked)
        producer = {
            "compiler": original["build-receipt"]["compiler"],
            "resolver": original["resolution-receipt"]["resolver"],
        }
        independent = reference_model_artifacts(reference, producer=producer)
        assert all(independent[key] == value for key, value in original.items())
        original["model-build-command-input"] = independent["model-build-command-input"]
        result[model] = checked, reference, original, producer
    return result


def _reseal(candidate, ldb):
    for role in ("model-explanation", "build-receipt"):
        if role == "build-receipt":
            candidate[role]["model_explanation_identity"] = candidate[
                "model-explanation"
            ]["content_identity"]
        candidate[role] = _identified_artifact(
            ldb,
            role,
            {
                key: value
                for key, value in candidate[role].items()
                if key
                not in {
                    "artifact_kind",
                    "artifact_version",
                    "wire_schema_identity",
                    "content_identity",
                }
            },
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "rir-binding",
        "debug-binding",
        "missing-formula",
        "duplicate-formula",
        "formula-identity",
        "formula-expression",
        "site-binding",
        "site-context",
        "missing-operation",
        "duplicate-operation",
        "operation-resource",
        "operation-control",
        "operation-effect",
    ),
)
def test_explanation_semantic_forgery_refuses_after_coordinated_reseal(
    explanation_pairs, mutation
):
    checked, reference, original, producer = explanation_pairs[
        "progression-periodic-effect"
    ]
    candidate = deepcopy(original)
    candidate["model-explanation"] = deepcopy(candidate["model-explanation"])
    explanation = candidate["model-explanation"]
    formulas = explanation["formula_explanations"]
    operations = explanation["operation_explanations"]
    assert formulas and operations
    if mutation in {"rir-binding", "debug-binding"}:
        explanation[
            "rir_identity" if mutation == "rir-binding" else "debug_map_identity"
        ] = "wrong.actual.binding"
    elif mutation == "missing-formula":
        formulas.pop()
    elif mutation == "duplicate-formula":
        formulas.append(deepcopy(formulas[0]))
    elif mutation == "formula-identity":
        formulas[0]["identity"] = "wrong.formula"
    elif mutation == "formula-expression":
        formulas[0]["expression"] += " + 1"
    elif mutation.startswith("site-"):
        site = next(site for row in formulas for site in row["evaluation_sites"])
        if mutation == "site-binding":
            site["binding_identity"] = "wrong.binding"
        else:
            site["context"]["phase"] = (
                "observation" if site["context"]["phase"] != "observation" else "event"
            )
    elif mutation == "missing-operation":
        operations.pop()
    elif mutation == "duplicate-operation":
        operations.append(deepcopy(operations[0]))
    elif mutation == "operation-resource":
        operations[0]["resource_bounds"]["max_steps"] += 1
    elif mutation == "operation-control":
        operations[0]["control_nodes"] = (
            ["add"] if operations[0]["control_nodes"] != ["add"] else ["copy"]
        )
    else:
        operations[0]["effects"] = (
            ["write"] if operations[0]["effects"] != ["write"] else []
        )
    _reseal(candidate, checked.language_bundle)
    assert all(
        verify_artifact(value, checked.language_bundle) for value in candidate.values()
    )
    assert not reference_admits_model_artifacts(candidate, reference, producer=producer)
    with pytest.raises(RuntimeError):
        validate_compiled_artifacts(
            {
                key: value
                for key, value in candidate.items()
                if key != "model-build-command-input"
            },
            checked.source_identity,
            checked.authority_context,
        )


@pytest.mark.parametrize("mutation", ("missing", "duplicate", "wrong-owner"))
def test_explanation_nominal_declarations_keep_their_actual_owner(
    explanation_pairs, mutation
):
    checked, reference, original, producer = explanation_pairs["structured-selection"]
    candidate = deepcopy(original)
    candidate["model-explanation"] = deepcopy(candidate["model-explanation"])
    rows = candidate["model-explanation"]["declaration_explanations"]
    assert rows
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    else:
        rows[0]["type_identity"]["package"] = "wrong.namespace"
    _reseal(candidate, checked.language_bundle)
    assert verify_artifact(candidate["model-explanation"], checked.language_bundle)
    assert not reference_admits_model_artifacts(candidate, reference, producer=producer)
    with pytest.raises(RuntimeError):
        validate_compiled_artifacts(
            {
                key: value
                for key, value in candidate.items()
                if key != "model-build-command-input"
            },
            checked.source_identity,
            checked.authority_context,
        )


def test_explanation_cannot_restore_the_old_unbounded_resource_shape(explanation_pairs):
    checked, _, original, _ = explanation_pairs["progression-periodic-effect"]
    candidate = deepcopy(original)
    candidate["model-explanation"] = deepcopy(candidate["model-explanation"])
    candidate["model-explanation"]["operation_explanations"][0]["resource_bounds"][
        "max_steps"
    ] = 0
    with pytest.raises(jsonschema.ValidationError):
        _reseal(candidate, checked.language_bundle)


def test_explanation_actual_binding_rename_runs_public_build_and_inspect(
    tmp_path, monkeypatch
):
    import test_model_protocol_structure as model_protocol

    monkeypatch.setattr(model_protocol, "MODEL_ROLES", ("model-explanation",))
    model_protocol.test_public_eight_member_build_and_inspect_with_independent_companions(
        tmp_path, True
    )


def test_explanation_inventory_retires_only_its_physical_schema_gap():
    from schema2_extension_inventory_support import (
        read_extension_inventory,
        validate_extension_inventory,
    )
    from test_model_protocol_structure import REMAINING_GAPS

    kernel, ldb = mutable_authorities()
    graph = _authored(ldb)
    before = deepcopy(graph)
    inventory = read_extension_inventory(kernel, graph)
    validate_extension_inventory(kernel, graph, inventory)
    assert graph == before
    assert len(inventory.uncovered) == 2
    assert {gap.pointer for gap in inventory.uncovered} == REMAINING_GAPS
