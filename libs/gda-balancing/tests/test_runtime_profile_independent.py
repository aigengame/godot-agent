"""Independent Formula compilation derives phases from the actual Kernel owners."""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.diagnostics import ArtifactLocation, Schema2RefusalReport
from gda_balancing.domain.model import (
    CheckedModel,
    RirAdmissionError,
    admit_rir,
    check_model_source_value,
)
from gda_balancing.domain.model._compilation import lower_checked_model
from gda_balancing.domain.model._resolution import ModelSourceContext
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _consumer_b_rir_schema
from schema2_bootstrap_production_support import _consumer_a
from test_rir_protocol_structure import _definitions
from test_trace_protocol_structure import _authored, _graph, _index
import test_schema2_model_lowerer_conformance as reference


def _source():
    return json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )


@pytest.mark.parametrize(
    "extension",
    [{}, {"standard.formula": {}}, {"opaque.profile": {"frame": "data"}}],
    ids=["empty", "formula", "opaque"],
)
def test_independent_runtime_profile_refuses_retired_extension_interface(extension):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    profile = next(
        row
        for row in _definitions(authored, "language.runtime_profiles")
        if row["evaluation"] == "declaration-only"
    )
    profile["extensions"] = deepcopy(extension)
    graph = _graph(kernel, authored)
    actual = _consumer_a(kernel, graph)
    independent = _consumer_b(kernel, graph)
    assert independent == actual
    assert not independent["admitted"]
    assert independent["diagnostics"] == [
        ("static", "kernel.vector_mismatch", "language.definitions")
    ]


@pytest.mark.parametrize("member", ["phase", "frame"])
def test_independent_selected_slot_rejects_unowned_context_before_compilation(member):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    source = _source()
    index, binding = next(
        (index, row)
        for index, row in enumerate(source["formula_bindings"])
        if row["site"]["kind"] == "operation-slot"
    )
    coordinate = binding["site"]["operation"]
    package = next(
        row for row in authored["packages"] if row["id"] == coordinate["package"]
    )
    operation = next(
        row
        for row in _definitions({"packages": [package]}, "language.operations")
        if row["id"] == coordinate["id"]
    )
    slot = next(
        row
        for row in operation["extensions"]["standard.formula-slots"]
        if row["id"] == binding["site"]["slot"]
    )
    slot["context"][member] = (
        "absent-phase" if member == "phase" else "pre-event-snapshot"
    )
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        observation = consumer(kernel, graph)
        assert observation["admitted"], observation["diagnostics"]
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    actual = check_model_source_value(source, authority_context=context)
    independent = reference._reference_check_source(
        source, kernel, context.language_bundle
    )
    assert isinstance(actual, Schema2RefusalReport)
    assert actual.stage == "static" and len(actual.diagnostics) == 1
    diagnostic = actual.diagnostics[0]
    assert isinstance(diagnostic.primary, ArtifactLocation)
    assert (diagnostic.code, diagnostic.primary.pointer) == (
        "language.formula_context_mismatch",
        f"/formula_bindings/{index}/site",
    )
    assert independent == ((diagnostic.code, diagnostic.primary.pointer),)


@pytest.fixture(scope="module")
def phase_only_rir():
    context = packaged_authority_context()
    kernel, language = context.mutable_pair()
    source = _source()
    checked = check_model_source_value(source, authority_context=context)
    independent = reference._reference_check_source(source, kernel, language)
    assert isinstance(checked, CheckedModel)
    assert isinstance(independent, ModelSourceContext)
    actual = lower_checked_model(checked)
    expected = reference._reference_semantic_artifacts(independent)
    for role in ("package-lock", "rir-semantic-payload", "resolved-model", "debug-map"):
        assert actual[role] == expected[role]
    assert reference._reference_admits_semantic_artifacts(actual, independent)
    rir = actual["rir-semantic-payload"]
    kind = rir["artifact_kind"]
    assert isinstance(kind, str)
    schema = _consumer_b_rir_schema(kernel, language, kind)
    Draft202012Validator(schema).validate(rir)
    return context, rir, schema


def test_independent_formula_contexts_retain_only_the_actual_phase(phase_only_rir):
    context, rir, _schema = phase_only_rir
    runtime = context.kernel["meta_format"]["runtime_program"]
    configuration = runtime["runtime_configuration"]
    expected = {
        configuration["formula_initialization_phase"],
        configuration["lifecycle_roles"]["active"],
        runtime["scheduler"]["observation"]["phase"],
    }
    sites = [row["site"] for row in rir["formula_bindings"]]
    assert {site["kind"] for site in sites} == {"derived-symbol", "operation-slot"}
    assert {site["context"]["phase"] for site in sites} == expected
    assert all(set(site["context"]) == {"phase"} for site in sites)
    assert all(
        set(row["site"]["context"]) == {"phase"}
        for row in rir["initialization_programs"]
    )
    assert not any(
        "extensions" in row for row in rir["selected_semantics"]["runtime_profiles"]
    )
    language = context.language_bundle["language"]
    periodic = [
        row["extensions"]["game.effect.periodic"]["magnitude"]["frame"]
        for row in language["operations"]
        if "game.effect.periodic" in row.get("extensions", {})
    ]
    capability = next(
        row for row in language["capabilities"] if row["id"] == "game.effect.periodic"
    )
    expected_frames = [
        row["contract"]["expect"]["magnitude"]["frame"]
        for row in capability["extensions"]["standard.operation-relation-policy"]
    ]
    assert periodic == expected_frames == ["pre-event-snapshot", "pre-event-snapshot"]


@pytest.mark.parametrize("site_kind", ["derived-symbol", "operation-slot"])
@pytest.mark.parametrize("member", ["phase", "frame"])
def test_independent_formula_context_schema_refuses_wrong_phase_and_old_frame(
    phase_only_rir, site_kind, member
):
    context, rir, schema = phase_only_rir
    forged = deepcopy(rir)
    active = context.kernel["meta_format"]["runtime_program"]["runtime_configuration"][
        "lifecycle_roles"
    ]["active"]
    index, binding = next(
        (index, row)
        for index, row in enumerate(forged["formula_bindings"])
        if row["site"]["kind"] == site_kind
        and row["site"]["context"]["phase"] == active
    )
    site = binding["site"]
    if member == "frame":
        site["context"][member] = "pre-event-snapshot"
    else:
        site["context"][member] = (
            "absent-phase"
            if site_kind == "derived-symbol"
            else context.kernel["meta_format"]["runtime_program"][
                "runtime_configuration"
            ]["formula_initialization_phase"]
        )
    errors = list(Draft202012Validator(schema).iter_errors(forged))
    observed = []
    pending = list(errors)
    while pending:
        error = pending.pop()
        observed.append((list(error.absolute_path), error.validator))
        pending.extend(error.context)
    path = ["formula_bindings", index, "site", "context"]
    if member == "frame":
        assert (path, "unevaluatedProperties") in observed
    else:
        assert ([*path, "phase"], "const") in observed
    with pytest.raises(RirAdmissionError, match="admitted semantics"):
        admit_rir(forged, authority_context=context)
