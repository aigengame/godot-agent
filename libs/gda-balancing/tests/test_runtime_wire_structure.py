"""Runtime output containers have one owner without granting caller capabilities."""

from copy import deepcopy

import pytest

from gda_balancing.domain.artifacts import select_protocol_artifact_contract
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _consumer_b
from schema2_bootstrap_production_support import _consumer_a
from test_receipt_protocol_structure import _definitions
from test_trace_protocol_structure import _authored, _graph


ROLES = ("evaluator-capability-manifest", "resolved-runtime-profile")


def _row(authored, role):
    return next(
        row
        for row in _definitions(authored, "language.artifact_wire_schemas")
        if row.get("protocol_role") == role
    )


@pytest.mark.parametrize("role", ROLES)
def test_runtime_containers_have_no_authored_schema(role):
    _, language = mutable_authorities()
    assert set(_row(_authored(language), role)) == {"artifact_kind", "protocol_role"}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("rename", [False, True], ids=["exact-shadow", "field-rename"])
def test_runtime_authored_container_override_refuses(tmp_path, role, rename):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    schema = deepcopy(select_protocol_artifact_contract(language, role).schema)
    if rename:
        name = "implementation" if role == ROLES[0] else "runtime_profile"
        schema["properties"]["renamed_" + name] = schema["properties"].pop(name)
        schema["required"] = [
            "renamed_" + name if value == name else value
            for value in schema["required"]
        ]
    _row(authored, role)["schema"] = schema
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"] is False, result
        assert result["diagnostics"] == [
            ("static", "kernel.vector_mismatch", "language.definitions")
        ]
    from test_current_namespace_public import _PublicCandidate
    from test_bounded_fold_public import _source

    public = _PublicCandidate(tmp_path / "public", authorities=(kernel, graph))
    public.write_source(_source())
    refused = public.cli("model", "check", str(public.source), success=False)
    assert public.receipts[-1]["returncode"] == 2
    assert [d["code"] for d in refused["error"]["diagnostics"]] == [
        "kernel.vector_mismatch"
    ]
    assert not list((public.directory / "store").rglob("artifact-set-receipt.json"))


@pytest.mark.parametrize("role", ROLES)
def test_runtime_wire_is_independent_and_inventory_closes_exactly_two_rows(
    role, monkeypatch
):
    import hashlib
    from gda_balancing.domain.authority.runtime_projection import runtime_output_schema
    from gda_balancing.domain.canonical import canonical_bytes
    from schema2_bootstrap_conformance_support import _consumer_b_runtime_output_schema
    from schema2_extension_inventory_support import (
        read_extension_inventory,
        validate_extension_inventory,
    )

    kernel, language = mutable_authorities()
    contract = select_protocol_artifact_contract(language, role)
    expected = runtime_output_schema(kernel, role, contract.definition["artifact_kind"])
    assert canonical_bytes(expected) == canonical_bytes(contract.schema)
    if role == ROLES[0]:
        # Exact original Schema bytes at 609823cab; no capability identities fixed.
        assert hashlib.sha256(canonical_bytes(expected)).hexdigest() == (
            "e5eb41ec341dfb429696be2a3f9346c6f18a7a1e41d7fd4766a8a585daac508f"
        )

    def forbidden(*args, **kwargs):
        pytest.fail("independent consumer called production Runtime wire projection")

    monkeypatch.setattr(
        "gda_balancing.domain.authority.runtime_projection.runtime_output_schema",
        forbidden,
    )
    assert canonical_bytes(
        _consumer_b_runtime_output_schema(
            kernel, role, contract.definition["artifact_kind"]
        )
    ) == canonical_bytes(expected)
    authored = _authored(language)
    result = _consumer_b(kernel, _graph(kernel, authored))
    assert result["admitted"], result
    inventory = read_extension_inventory(kernel, authored)
    validate_extension_inventory(kernel, authored, inventory)
    assert len(inventory.uncovered) == 3
    assert not any(
        gap.pointer
        in {
            "/packages/12/semantic_closure/2/definitions/24",
            "/packages/12/semantic_closure/2/definitions/25",
        }
        for gap in inventory.uncovered
    )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong-kind-owner"])
def test_runtime_output_roles_have_unique_actual_kind_bindings(role, mutation):
    kernel, language = mutable_authorities()
    authored = _authored(language)
    row = _row(authored, role)
    if mutation == "missing":
        del row["protocol_role"]
    elif mutation == "duplicate":
        _row(authored, ROLES[1] if role == ROLES[0] else ROLES[0])["protocol_role"] = (
            role
        )
    else:
        contract = next(
            d
            for d in _definitions(authored, "language.artifact_contracts")
            if d["schema_kind"] == row["artifact_kind"]
        )
        contract["schema_kind"] = _row(
            authored, ROLES[1] if role == ROLES[0] else ROLES[0]
        )["artifact_kind"]
    graph = _graph(kernel, authored)
    for consumer in (_consumer_a, _consumer_b):
        assert not consumer(kernel, graph)["admitted"]


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-part",
        "missing-part",
        "missing-field",
        "envelope-duplicate",
        "profile-duplicate",
        "duplicate-required",
        "profile-unowned",
        "budget-contract",
    ],
)
def test_runtime_output_kernel_contract_has_no_unknown_or_duplicate_owner(mutation):
    from gda_balancing.domain.authority.runtime_projection import runtime_output_schema
    from schema2_bootstrap_conformance_support import _consumer_b_runtime_output_schema

    kernel, _ = mutable_authorities()
    structure = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["runtime_capability_structure"]
    if mutation == "unknown-part":
        structure["unknown"] = {}
    elif mutation == "missing-part":
        del structure["manifest"]
    elif mutation == "missing-field":
        del structure["resolved_profile"]["field_types"]["experiment_identity"]
    elif mutation == "envelope-duplicate":
        structure["resolved_profile"]["field_types"]["artifact_version"] = {
            "type": "non-empty-string"
        }
    elif mutation == "profile-duplicate":
        structure["resolved_profile"]["field_types"]["runtime_profile"] = {
            "type": "canonical-json"
        }
    elif mutation == "duplicate-required":
        structure["resolved_profile"]["required_members"].append("runtime_profile")
    elif mutation == "profile-unowned":
        kernel["meta_format"]["runtime_profile_definition"]["active_runtime"][
            "required_members"
        ].append("unowned")
    else:
        kernel["meta_format"]["runtime_profile_definition"]["active_runtime"][
            "resource_bounds"
        ]["value_contract"] = "integer"
    for project in (runtime_output_schema, _consumer_b_runtime_output_schema):
        with pytest.raises((KeyError, ValueError)):
            project(kernel, ROLES[1], ROLES[1])


@pytest.fixture(scope="module", params=(False, True), ids=("original", "renamed"))
def runtime_public(request, tmp_path_factory):
    import json
    from gda_balancing.domain.authority.context import (
        AdmittedAuthorityContext,
        admit_authority_context,
    )
    from gda_balancing.domain.experiment import (
        CheckedExperiment,
        check_experiment_value,
    )
    from gda_balancing.domain.model import admit_rir
    from priority_protocol_support import authorities, source, specification
    from test_current_namespace_public import _PublicCandidate, _members
    from test_runtime_effect_renaming import _rename_effects
    from test_schema2_model_lowerer_conformance import _reidentify_language_bundle
    from test_trace_protocol_structure import _index

    kernel, language, turn = authorities()
    original_kernel = deepcopy(kernel)
    if request.param:
        _rename_effects(language)
        profile = next(
            row["id"]
            for row in language["language"]["runtime_profiles"]
            if row["evaluation"] == "deterministic-event-v1"
        )

        def rename_profile(value):
            if isinstance(value, dict):
                return {k: rename_profile(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rename_profile(v) for v in value]
            return "candidate.execution-profile" if value == profile else value

        for name, value in list(language.items()):
            language[name] = rename_profile(value)
        _reidentify_language_bundle(language)
    authored = _authored(language)
    kinds = {}
    for index, role in enumerate(ROLES):
        schema = _row(authored, role)
        contract = next(
            d
            for d in _definitions(authored, "language.artifact_contracts")
            if d["schema_kind"] == schema["artifact_kind"]
        )
        kinds[role] = contract["artifact_kind"]
        if not request.param:
            continue
        old_schema, old_kind = schema["artifact_kind"], contract["artifact_kind"]
        schema["artifact_kind"] = f"candidate.runtime-schema.{index}"
        contract["schema_kind"] = schema["artifact_kind"]
        contract["artifact_kind"] = kinds[role] = f"candidate.runtime-artifact.{index}"
        for package in authored["packages"]:
            for collection, old, new in (
                ("artifact_wire_schemas", old_schema, schema["artifact_kind"]),
                ("artifact_contracts", old_kind, contract["artifact_kind"]),
            ):
                package["exports"][collection] = [
                    new if value == old else value
                    for value in package["exports"][collection]
                ]
    graph = _graph(kernel, authored)
    assert kernel == original_kernel
    for consumer in (_consumer_a, _consumer_b):
        result = consumer(kernel, graph)
        assert result["admitted"], result
    context = admit_authority_context(kernel, _index(kernel, graph))
    assert isinstance(context, AdmittedAuthorityContext), context
    public = _PublicCandidate(
        tmp_path_factory.mktemp("runtime-wire-public"), authorities=(kernel, graph)
    )
    public.write_source(source(turn))
    public.cli("model", "check", str(public.source))
    build = public.cli(
        "model",
        "build",
        str(public.source),
        "--out",
        str(public.directory / "build"),
        "--invocation-key",
        "b1" * 32,
    )
    rir = _members(build)["rir-semantic-payload"]
    rir_path = public.directory / "rir.json"
    rir_path.write_text(json.dumps(rir))
    intent = specification(
        rir,
        runtime_profile="candidate.execution-profile"
        if request.param
        else "standard.exact-int64-event-v1",
    )
    path = public.directory / "experiment.json"
    path.write_text(json.dumps(intent))
    public.cli("experiment", "check", str(path), "--rir", str(rir_path))
    checked = check_experiment_value(
        intent, admit_rir(rir, authority_context=context), authority_context=context
    )
    assert isinstance(checked, CheckedExperiment), checked
    run = public.cli(
        "experiment",
        "run",
        str(path),
        "--rir",
        str(rir_path),
        "--out",
        str(public.directory / "run"),
        "--invocation-key",
        "b2" * 32,
    )
    return public, context, checked, _members(run), kinds


def test_public_runtime_wire_preserves_selected_profile_and_real_capabilities(
    runtime_public,
):
    from jsonschema import Draft202012Validator
    from gda_balancing.domain.artifacts import artifacts_by_protocol_role
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )
    from schema2_bootstrap_conformance_support import _consumer_b_runtime_output_schema

    _, context, checked, members, kinds = runtime_public
    assert validate_experiment_artifact_set(checked, members)
    semantic = artifacts_by_protocol_role(context.language_bundle, members)
    manifest, resolved = (semantic[role] for role in ROLES)
    for role in ROLES:
        assert semantic[role]["artifact_kind"] == kinds[role]
        Draft202012Validator(
            _consumer_b_runtime_output_schema(dict(context.kernel), role, kinds[role])
        ).validate(semantic[role])
    assert [s["value"] for s in semantic["metric-dataset"]["samples"]] == [7]
    assert resolved["runtime_profile"] == next(
        row
        for row in checked.rir["selected_semantics"]["runtime_profiles"]
        if row["id"] == checked.value["runtime"]["profile"]
    )
    assert set(resolved["runtime_profile"]["effects"]) > set(manifest["effects"])
    assert resolved["runtime_profile"]["id"] in manifest["runtime_profiles"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "profile",
        "zero-bound",
        "rng",
        "scope",
        "unsupported-node",
    ],
)
def test_actual_runtime_output_reseals_preserve_semantic_refusal(
    runtime_public, mutation
):
    from gda_balancing.domain.artifacts import artifacts_by_protocol_role
    from gda_balancing.domain.experiment_artifacts import (
        validate_experiment_artifact_set,
    )

    _, context, checked, original, kinds = runtime_public
    members = deepcopy(original)
    semantic = artifacts_by_protocol_role(context.language_bundle, members)
    role = ROLES[0] if mutation == "unsupported-node" else ROLES[1]
    value = semantic[role]
    if mutation == "missing":
        del members[
            next(name for name, artifact in members.items() if artifact is value)
        ]
    elif mutation == "duplicate":
        members["duplicate-runtime-profile"] = deepcopy(value)
    else:
        if mutation == "profile":
            value["runtime_profile"]["id"] = "unselected-profile"
        elif mutation == "zero-bound":
            value["runtime_profile"]["resource_bounds"]["max_node_steps"] = 0
        elif mutation == "rng":
            value["runtime_profile"]["rng"]["algorithm"] = "unsupported-rng"
        elif mutation == "scope":
            value["runtime_profile"]["budget_scopes"]["node_steps"] = "per-event"
        else:
            value["instruction_nodes"].remove("schedule")
        contract = select_protocol_artifact_contract(context.language_bundle, role)
        from gda_balancing.domain.canonical import content_identity

        value["content_identity"] = content_identity(
            contract.definition["identity_domain"],
            {k: v for k, v in value.items() if k != "content_identity"},
        )
    assert not validate_experiment_artifact_set(checked, members)
