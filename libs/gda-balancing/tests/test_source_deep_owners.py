"""Actual Source selectors reach both independent compiler boundaries."""

import json
from pathlib import Path


from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from test_source_wire_owners import _source_schema
from test_trace_protocol_structure import _authored, _graph, _index
from test_schema2_model_lowerer_conformance import _reference_check_source


def _rename_field(schema, old, new):
    schema["properties"][new] = schema["properties"].pop(old)
    schema["required"] = [
        new if member == old else member for member in schema["required"]
    ]


def test_formula_binding_site_selector_is_consumed_by_independent_source_resolution(
    tmp_path,
):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )
    assert len(source["formula_bindings"]) == 3
    target = "opaque/site~"
    _rename_field(
        _source_schema(authored)["properties"]["formula_bindings"]["items"],
        "site",
        target,
    )
    for row in source["formula_bindings"]:
        row[target] = row.pop("site")
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result
    checked = _reference_check_source(source, kernel, _index(kernel, graph))
    assert isinstance(checked, ModelSourceContext), checked
    _assert_public_compilation_and_run(tmp_path, kernel, graph, source)


def test_source_entrypoint_operation_selector_reaches_both_compilers(tmp_path):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )
    target = "opaque/operation~"
    _rename_field(
        _source_schema(authored)["properties"]["entrypoints"]["items"],
        "operation",
        target,
    )
    for entrypoint in source["entrypoints"]:
        entrypoint[target] = entrypoint.pop("operation")
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result
    checked = _reference_check_source(source, kernel, _index(kernel, graph))
    assert isinstance(checked, ModelSourceContext), checked
    _assert_public_compilation_and_run(tmp_path, kernel, graph, source)


def _assert_public_compilation_and_run(tmp_path, kernel, graph, source):
    from gda_balancing.domain.artifacts import (
        artifacts_by_protocol_role,
        verify_artifact,
    )
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.model import admit_resolved_model
    from schema2_bootstrap_conformance_support import _encoded
    from test_bounded_fold_public import _check, _run
    from test_current_namespace_public import _PublicCandidate, _members
    from test_schema2_model_lowerer_conformance import (
        _reference_admits_semantic_artifacts,
        _reference_semantic_artifacts,
    )

    language = _index(kernel, graph)
    context = admit_authority_context(kernel, language)
    assert isinstance(context, AdmittedAuthorityContext), context
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(source)
    public.cli("model", "check", str(public.source))
    receipt = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "34" * 32,
    )
    built = artifacts_by_protocol_role(language, _members(receipt))
    assert len(built) == 8
    checked = _reference_check_source(source, kernel, language)
    assert isinstance(checked, ModelSourceContext), checked
    independent = _reference_semantic_artifacts(checked)
    assert len(independent) == 4
    assert all(
        _encoded(value) == _encoded(built[role]) for role, value in independent.items()
    )
    assert _reference_admits_semantic_artifacts(built, checked)
    assert all(verify_artifact(value, language) for value in independent.values())
    assert admit_resolved_model(
        {
            role: independent[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted
    rir = built["rir-semantic-payload"]
    rir_path = next(
        row["locator"]
        for row in receipt["member_locators"]
        if row["logical_name"] == "rir-semantic-payload"
    )
    specification = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/experiment.json"
        ).read_text()
    )
    specification["model"]["rir_semantic_identity"] = rir["semantic_identity"]
    path, _ = _check(public, rir_path, specification)
    executed = _members(_run(public, rir_path, path))
    from gda_balancing.domain.experiment import (
        CheckedExperiment,
        check_experiment_value,
    )
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from gda_balancing.domain.model import AdmittedRir, admit_rir

    program = admit_rir(rir, authority_context=context)
    assert isinstance(program, AdmittedRir), program
    experiment = check_experiment_value(
        specification, program, authority_context=context
    )
    assert isinstance(experiment, CheckedExperiment), experiment
    assert validate_experiment_artifact_set(experiment, executed)
    return public, checked
