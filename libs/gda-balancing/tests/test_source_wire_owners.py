"""Source transport addresses belong to the selected Resolution profile."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b, _encoded
from schema2_bootstrap_production_support import _consumer_a
from test_resolution_parse_reason import _definitions, _profile
from test_trace_protocol_structure import _authored, _graph, _index


def _source_schema(graph):
    return next(
        row["schema"]
        for row in _definitions(graph, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )


def test_source_entrypoint_schema_cannot_drift_from_its_selected_address():
    kernel, index = mutable_authorities()
    authored = _authored(index)
    original = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        assert consumer(kernel, original)["admitted"]
    schema = _source_schema(authored)
    schema["properties"]["opaque_entrypoints"] = schema["properties"].pop("entrypoints")
    schema["required"] = [
        "opaque_entrypoints" if field == "entrypoints" else field
        for field in schema["required"]
    ]
    candidate = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, candidate)
        assert not result["admitted"], result


@pytest.mark.parametrize(
    "all_roots", [False, True], ids=["entrypoints", "all-root-containers"]
)
def test_source_entrypoints_coherent_rename_reaches_public_and_independent_compilers(
    tmp_path, all_roots
):
    from gda_balancing.domain.artifacts import (
        artifacts_by_protocol_role,
        verify_artifact,
    )
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.model import admit_resolved_model
    from gda_balancing.domain.model._resolution import ModelSourceContext
    from test_current_namespace_public import _PublicCandidate, _members
    from test_schema2_model_lowerer_conformance import (
        _reference_admits_semantic_artifacts,
        _reference_check_source,
        _reference_semantic_artifacts,
    )

    kernel, index = mutable_authorities()
    authored = _authored(index)
    profile = _profile(authored)
    names: dict[str, str] = {"entrypoints": "opaque/entry~points"}
    if all_roots:
        names.update(
            {
                name: "opaque/" + name + "~"
                for name in (
                    "schema_version",
                    "manifest",
                    "modules",
                    "package_requirements",
                    "formula_bindings",
                )
            }
        )
    schema = _source_schema(authored)
    for original, renamed in names.items():
        schema["properties"][renamed] = schema["properties"].pop(original)
    schema["required"] = [names.get(name, name) for name in schema["required"]]
    for member in (
        "entrypoints_member",
        "schema_version_member",
        "modules_member",
        "requirements_member",
    ):
        profile[member] = names.get(profile[member], profile[member])
    for member in ("manifest_id_path", "manifest_entry_module_path"):
        root, *tail = str(profile[member]).split(".")
        profile[member] = ".".join([names.get(root, root), *tail])
    policy = profile["formula_resolution"]
    policy["bindings_member"] = names.get(
        policy["bindings_member"], policy["bindings_member"]
    )
    for recipe in profile["relation_recipes"]:
        for term in (
            [row["source"] for row in recipe["bindings"]]
            + [row["term"] for row in recipe["fields"]]
            + [row[side] for row in recipe["predicates"] for side in ("left", "right")]
        ):
            if term.get("root") == "source" and term["path"]:
                term["path"][0] = names.get(term["path"][0], term["path"][0])
    for check in _definitions(authored, "language.model_checks"):
        for member in ("selector", "scope_selector"):
            if check.get(member):
                check[member][0] = names.get(check[member][0], check[member][0])
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], (consumer.__name__, result["diagnostics"])
    from schema2_extension_inventory_support import _source_format_role

    assert (
        _source_format_role(kernel, authored) == "language.model_source_schema_versions"
    )
    index = _index(kernel, graph)
    context = admit_authority_context(kernel, index)
    assert isinstance(context, AdmittedAuthorityContext), context
    source = json.loads(
        (
            Path(__file__).parents[1]
            / "examples/schema2/rpg-combat-cast/model-source.json"
        ).read_text()
    )
    assert set(names) <= source.keys()
    assert source["formula_bindings"] and source["entrypoints"]
    for original, renamed in names.items():
        source[renamed] = source.pop(original)
    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(source)
    public.cli("model", "check", str(public.source))
    built = artifacts_by_protocol_role(
        index,
        _members(
            public.cli(
                "model",
                "build",
                str(public.source),
                "--out",
                str(public.directory / "build"),
                "--invocation-key",
                "e4" * 32,
            )
        ),
    )
    assert len(built) == 8
    checked = _reference_check_source(source, kernel, index)
    assert isinstance(checked, ModelSourceContext), checked
    reference = _reference_semantic_artifacts(checked)
    assert len(reference) == 4
    assert all(
        _encoded(built[role]) == _encoded(value) for role, value in reference.items()
    )
    assert _reference_admits_semantic_artifacts(built, checked)
    assert all(verify_artifact(value, index) for value in reference.values())
    assert admit_resolved_model(
        {
            role: reference[role]
            for role in ("package-lock", "rir-semantic-payload", "resolved-model")
        },
        authority_context=context,
    ).admitted
    binding_reference = source[policy["bindings_member"]][0][
        policy["binding_formula_member"]
    ]
    original_formula = binding_reference["id"]
    binding_reference["id"] = "missing-formula"
    public.write_source(source)
    refused = public.cli("model", "check", str(public.source), success=False)
    binding_pointer = (
        "/"
        + policy["bindings_member"].replace("~", "~0").replace("/", "~1")
        + "/0/formula"
    )
    assert refused["error"]["diagnostics"][0]["primary"]["pointer"] == binding_pointer
    reference_refusal = _reference_check_source(source, kernel, index)
    assert isinstance(reference_refusal, tuple)
    assert reference_refusal[0][1] == binding_pointer
    binding_reference["id"] = original_formula
    source[profile["entrypoints_member"]][0]["operation"]["id"] = "missing-operation"
    public.write_source(source)
    refused = public.cli("model", "check", str(public.source), success=False)
    expected_pointer = (
        "/"
        + profile["entrypoints_member"].replace("~", "~0").replace("/", "~1")
        + "/0/operation/id"
    )
    assert refused["error"]["diagnostics"][0]["primary"]["pointer"] == expected_pointer
    reference_refusal = _reference_check_source(source, kernel, index)
    assert isinstance(reference_refusal, tuple)
    assert reference_refusal[0][1] == expected_pointer


def test_retired_signed_integer_context_cannot_reenter_resealed_source_grammar():
    kernel, index = mutable_authorities()
    authored = _authored(index)
    definition = next(
        row
        for row in _definitions(authored, "language.wire_schemas")
        if row.get("protocol_role") == "model-source-package"
    )
    definition["formula_grammar"]["signed_integer_context"] = "operand-position"
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], result


@pytest.mark.parametrize("member", ["entrypoints_member", "schema_version_member"])
@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "unknown", "wrong-type", "optional"]
)
def test_source_root_selectors_are_complete_and_schema_related(member, mutation):
    kernel, index = mutable_authorities()
    authored = _authored(index)
    profile = _profile(authored)
    schema = _source_schema(authored)
    selected = profile[member]
    if mutation == "missing":
        del profile[member]
    elif mutation == "extra":
        profile[member + "_fallback"] = selected
    elif mutation == "unknown":
        profile[member] = "not-declared"
    elif mutation == "wrong-type":
        schema["properties"][selected] = {"type": "boolean"}
    else:
        schema["required"].remove(selected)
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert not result["admitted"], (consumer.__name__, result)


def test_template_instantiation_updates_the_profile_owned_manifest_identity():
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.canonical import content_identity
    from gda_balancing.domain.model import CheckedModel, check_model_source_value
    from gda_balancing.domain.template import minimal_release
    from gda_balancing.domain.template._release_semantics import (
        TemplateInstantiationPlan,
        prepare_template_instantiation,
    )
    from test_schema2_template_cli import _reidentify_release

    kernel, language = mutable_authorities()
    authored = _authored(language)
    profile = _profile(authored)
    profile["manifest_id_path"] = "opaque_header.opaque_id"
    profile["manifest_entry_module_path"] = "opaque_header.entry_module"
    schema = _source_schema(authored)
    header = schema["properties"].pop("manifest")
    schema["properties"]["opaque_header"] = header
    schema["required"] = [
        "opaque_header" if key == "manifest" else key for key in schema["required"]
    ]
    header["properties"]["opaque_id"] = header["properties"].pop("id")
    header["required"] = [
        "opaque_id" if key == "id" else key for key in header["required"]
    ]
    for recipe in profile["relation_recipes"]:
        terms = (
            [row["source"] for row in recipe["bindings"]]
            + [row["term"] for row in recipe["fields"]]
            + [row[side] for row in recipe["predicates"] for side in ("left", "right")]
        )
        for term in terms:
            if (
                term.get("root") == "source"
                and term["path"]
                and term["path"][0] == "manifest"
            ):
                term["path"][0] = "opaque_header"
                if term["path"][-1] == "id":
                    term["path"][-1] = "opaque_id"
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        assert consumer(kernel, graph)["admitted"]
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext)
    release = cast(dict[str, Any], minimal_release(context))
    source = next(
        member["payload"]
        for member in release["members"]
        if member["member_kind"] == "model-source-package"
    )
    source["opaque_header"] = source.pop("manifest")
    source["opaque_header"]["opaque_id"] = source["opaque_header"].pop("id")
    starter_identity = content_identity(profile["source_identity_domain"], source)
    for member in release["members"]:
        if member["member_kind"] in {"experiment-template", "golden-scenario"}:
            member["payload"]["model_source_identity"] = starter_identity
    release = _reidentify_release(release)
    plan = prepare_template_instantiation(
        release["id"], "example.renamed-manifest", lambda _: release, lambda: context
    )
    assert isinstance(plan, TemplateInstantiationPlan), plan
    instance = plan.artifacts["model-source-package"].value
    assert "manifest" not in instance and "id" not in instance["opaque_header"]
    assert instance["opaque_header"]["opaque_id"] == "example.renamed-manifest"
    assert instance["opaque_header"]["template_provenance"] == {
        "template_id": release["id"],
        "template_identity": release["content_identity"],
        "starter_identity": starter_identity,
    }
    assert plan.member_is_admitted(plan.source_kind, instance)
    assert isinstance(
        check_model_source_value(instance, authority_context=context), CheckedModel
    )
