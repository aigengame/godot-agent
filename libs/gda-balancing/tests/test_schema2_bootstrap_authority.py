"""Schema 2.0 bootstrap conformance: authority ownership."""

# ruff: noqa: F403, F405
import schema2_bootstrap_conformance_support as bootstrap_support
from schema2_bootstrap_conformance_support import *
from schema2_bootstrap_production_support import *


def test_two_independent_consumers_admit_the_exact_authority_and_inventories():
    authority = _authority_candidate()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is True
    assert first["law_ids"]
    assert first["rule_ids"] == ["quantity.declare", "quantity.lower"]
    assert ldb["language"]["model_source_schema_versions"] == ["2.0.0"]


@pytest.mark.parametrize(
    ("binding_group", "member"),
    (
        ("runtime_member_bindings", "evaluation"),
        ("rng_member_bindings", "algorithm"),
    ),
)
def test_reference_consumer_rejects_non_string_runtime_binding_paths(
    binding_group, member
):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    profile_contract = kernel["meta_format"]["runtime_profile_definition"]
    runtime = kernel["meta_format"]["runtime_program"]
    profile = next(
        row
        for row in authority["language_bundle"]["language"]["runtime_profiles"]
        if row["evaluation"] == runtime["version"]
    )
    assert bootstrap_support._consumer_b_active_profile_is_closed(
        profile,
        profile_contract,
        runtime,
    )

    profile_contract["active_runtime"][binding_group][member] = None

    assert not bootstrap_support._consumer_b_active_profile_is_closed(
        profile,
        profile_contract,
        runtime,
    )


def test_cancel_target_is_a_kernel_owned_schedule_result_reference():
    authority = _authority_candidate()
    runtime = authority["kernel"]["meta_format"]["runtime_program"]
    nodes = {node["id"]: node for node in runtime["nodes"]}

    assert nodes["schedule"]["result"]["kind"] == "scheduled-event"
    assert nodes["cancel"]["semantics"]["target_reference"] == {
        "instruction_member": "event",
        "kind": "local",
        "producer_result_kind": "scheduled-event",
        "value_member": "local",
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "arbitrary-runtime-configuration",
        "invalid-lifecycle-role",
        "invalid-observation-phase",
        "invented-initial-boundary",
        "empty-schedule-policy",
        "missing-scheduler-component-contract",
        "missing-relations-with-invented-root-phase",
        "missing-root-phase-map",
    ),
)
def test_two_consumers_refuse_reidentified_runtime_component_drift(
    monkeypatch, mutation
):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    runtime = kernel["meta_format"]["runtime_program"]
    if mutation == "arbitrary-runtime-configuration":
        runtime["runtime_configuration"] = {"host": "invented"}
    elif mutation == "invalid-lifecycle-role":
        runtime["runtime_configuration"]["lifecycle_roles"]["active"] = "host-invented"
    elif mutation == "invalid-observation-phase":
        runtime["scheduler"]["observation"]["phase"] = "host-invented"
    elif mutation == "invented-initial-boundary":
        runtime["step"]["boundary_roles"]["initial"] = "host-invented"
    elif mutation == "empty-schedule-policy":
        runtime["scheduler"]["schedule"] = {}
    elif mutation == "missing-scheduler-component-contract":
        del runtime["component_contract"]["components"]["scheduler"]
        runtime["component_contract"]["relations"] = [
            relation
            for relation in runtime["component_contract"]["relations"]
            if relation["component"] != "scheduler"
        ]
    elif mutation == "missing-relations-with-invented-root-phase":
        runtime["component_contract"]["relations"] = []
        runtime["scheduler"]["root_phases"]["external-input"] = "host-invented"
    else:
        del runtime["scheduler"]["root_phases"]
    _reidentify(kernel, authority["language_bundle"])
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
    )
    monkeypatch.setattr(
        bootstrap_support, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
    )

    first = _consumer_a(kernel, authority["language_bundle"])
    second = _consumer_b(kernel, authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.runtime",
    ) in first["diagnostics"]


def test_two_consumers_refuse_cancel_target_without_a_prior_schedule_producer():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.plan-casts-v1"
    )
    cancel = next(row for row in operation["body"] if row["node"] == "cancel")
    cancel["event"]["local"] = "host-invented-local"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.runtime",
    ) in first["diagnostics"]


def test_rir_semantic_projection_members_close_against_the_wire_schema():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    contract = next(
        row
        for row in ldb["language"]["artifact_contracts"]
        if row["artifact_kind"] == "rir-semantic-payload"
    )
    contract["semantic_identity_projection"]["collection_member_exclusions"][0][
        "excluded_members"
    ] = ["host-invented-member"]
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions.artifact-semantic-projections",
    ) in first["diagnostics"]


def test_formula_semantics_are_owned_by_package_extensions_and_vectors():
    authority = _authority_candidate()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    packages = {package["id"]: package for package in ldb["language"]["packages"]}
    vector_sets = {
        vector_set["package_id"]: vector_set
        for vector_set in ldb.package_conformance_vector_sets
    }
    runtime_package = packages["standard.runtime"]
    runtime_profile = next(
        definition
        for entry in runtime_package["semantic_closure"]
        if entry["authority_path"] == "language.runtime_profiles"
        for definition in entry["definitions"]
        if definition["id"] == "standard.exact-int64-event-v1"
    )

    runtime_profile_contract = kernel["meta_format"]["language_definitions"][
        "collections"
    ]["runtime_profiles"]
    assert "formula_evaluation" not in runtime_profile_contract["field_types"]
    assert "formula_evaluation" not in runtime_profile_contract["optional_members"]
    assert runtime_profile["extensions"]["standard.formula"] == {
        "cache": {
            "admission": "optional-non-semantic",
            "charge_policy": "same-as-uncached-evaluation",
            "key_members": [
                "evaluation-site-identity",
                "frame-or-snapshot-identity",
                "canonical-operands",
                "numeric-profile-identity",
            ],
            "snapshot_change": "requires-reevaluation",
        },
        "contexts": [
            {
                "frame": "pre-snapshot",
                "phase": "initialization",
                "publication": "atomic-before-snapshot-0",
                "reads": "immutable-initialization-frame",
            },
            {
                "frame": "pre-event-snapshot",
                "phase": "event",
                "publication": "inside-atomic-event",
                "reads": "committed-pre-event-state",
            },
            {
                "frame": "post-transition-snapshot",
                "phase": "observation",
                "publication": "after-atomic-event",
                "reads": "committed-post-transition-state",
            },
        ],
        "initialization_refusal": {
            "published_artifacts": [],
            "published_audit": False,
            "published_events": False,
            "published_snapshots": False,
        },
        "resource_charge": {
            "basis": "specialized-operation-instruction-closure",
            "cache_hit": "same-as-evaluation",
        },
        "snapshot_identity_domain": "runtime-snapshot-v2",
    }
    expected_vector_ids = {
        "standard.schema": {
            "formula.schema.accept.named-typed-pure-graph",
            "formula.schema.refuse.dynamic-or-effectful-graph",
        },
        "standard.compiler": {
            "formula.compiler.accept.closed-static-graph",
            "formula.compiler.refuse.invalid-closure",
        },
        "standard.runtime": {
            "formula.runtime.accept.initialization-and-event-frames",
            "formula.runtime.refuse.initialization-atomically",
            "formula.runtime.boundary.cache-charge-invariant",
            "formula.runtime.observation.positive.post-transition-snapshot",
            "formula.runtime.observation.boundary.snapshot-cache-key",
            "formula.runtime.observation.refusal.atomic-prefix",
        },
        "core.quantity": {
            "formula.quantity.accept.pure-operation-closure",
            "formula.quantity.accept.boolean-comparison",
            "formula.notation.quantity.floor-zero",
            "formula.notation.quantity.identity",
            "formula.notation.quantity.less-than",
            "formula.notation.quantity.maximum",
            "formula.notation.quantity.subtract",
        },
        "game.combat": {
            "formula.combat.accept.damage-slot-binding",
            "formula.combat.refuse.missing-or-duplicate-slot-binding",
        },
    }
    for package_id, expected in expected_vector_ids.items():
        assert expected <= {
            vector["id"] for vector in vector_sets[package_id]["vector_definitions"]
        }
    runtime_vectors = {
        vector["id"]: vector
        for vector in vector_sets["standard.runtime"]["vector_definitions"]
    }
    kernel_vector_kinds = {
        kind["id"] for kind in kernel["meta_format"]["package_vector"]["kinds"]
    }
    assert "artifact-evidence" not in kernel_vector_kinds
    assert {
        runtime_vectors[vector_id]["kind"]
        for vector_id in expected_vector_ids["standard.runtime"]
        if ".observation." in vector_id
    } == {"value-program"}
    assert runtime_package["exports"]["artifact_wire_schemas"] == []
    assert (
        next(
            entry["definitions"]
            for entry in runtime_package["semantic_closure"]
            if entry["authority_path"] == "language.artifact_wire_schemas"
        )
        == []
    )
    assert not any(
        entry["artifact_kind"].startswith("formula-observation-")
        for entry in ldb["language"]["artifact_wire_schemas"]
    )
    expected_sites = {
        "runtime.lifecycle-observation.boundary",
        "runtime.lifecycle-observation.positive",
        "runtime.lifecycle-observation.refusal",
    }
    for vector_id in expected_vector_ids["standard.runtime"]:
        if ".observation." not in vector_id:
            continue
        vector = runtime_vectors[vector_id]
        assert vector["input"]["site"] in expected_sites
        assert vector["expect"]["site"] == vector["input"]["site"]
    compiler_package = packages["standard.compiler"]
    resolution_profile = next(
        definition
        for entry in compiler_package["semantic_closure"]
        if entry["authority_path"] == "language.resolution_profiles"
        for definition in entry["definitions"]
        if definition["id"] == "exact-import-resolution-v1"
    )
    assert resolution_profile["extensions"]["standard.formula"][
        "fixed_value_type_aliases"
    ] == [{"alias": "Boolean", "contract": "kernel-boolean"}]
    quantity_operations = {
        definition["id"]: definition
        for entry in packages["core.quantity"]["semantic_closure"]
        if entry["authority_path"] == "language.operations"
        for definition in entry["definitions"]
    }
    less_than = quantity_operations["quantity.less-than"]
    assert less_than["body"] == [
        {"left": "left", "node": "less-than", "right": "right", "target": "result"}
    ]
    assert less_than["result"] == {
        "access": "read",
        "discardable": False,
        "domain": {"kind": "boolean"},
        "id": "result",
        "kind": "boolean",
        "numeric_policy": "exact-bool",
        "representation": "Bool",
        "source": {"kind": "local", "name": "result"},
        "type": {"id": "Boolean", "package": "kernel", "version": "2.0.0"},
        "unit": "1",
    }
    quantity_vectors = {
        vector["id"]: vector
        for vector in vector_sets["core.quantity"]["vector_definitions"]
    }
    for operation_id, operation in quantity_operations.items():
        vector_id = f"formula.notation.{operation_id}"
        vector = quantity_vectors[vector_id]
        assert vector == {
            "category": "positive",
            "expect": operation["extensions"],
            "id": vector_id,
            "kind": "operation-contract",
            "operation": operation_id,
            "probe": {"path": "extensions"},
        }
        assert vector_id in operation["vectors"]


@pytest.mark.parametrize(
    "mutation",
    (
        "identity-only",
        "reidentified-specification",
        "artifact-schema",
    ),
)
def test_two_consumers_refuse_unilateral_embedded_artifact_binding_drift(mutation):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    schemas = {
        entry["artifact_kind"]: entry["schema"]
        for entry in ldb["language"]["artifact_wire_schemas"]
    }
    refusal_schema = schemas["migration-refusal-report"]
    properties = refusal_schema["properties"]
    if mutation == "identity-only":
        properties["converter_identity"]["const"] = "sha256:" + "0" * 64
    elif mutation == "reidentified-specification":
        specification = properties["converter_specification"]["const"]
        specification["mapping_rules"][0]["report_mapping"] = "unilateral drift"
        specification["content_identity"] = _identity(
            "source-converter-specification-v1", specification
        )
        properties["converter_identity"]["const"] = specification["content_identity"]
    else:
        schemas["source-converter-specification"]["properties"]["mapping_rules"][
            "minItems"
        ] = 5
    _reidentify(kernel, ldb)

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "ingress",
        "kernel.identity_mismatch",
        "language-bundle.admitted-index",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    (
        "relation-missing-path",
        "relation-wrong-result-type",
        "projection-missing-path",
        "projection-wrong-result-type",
        "scalar-routing-drift",
    ),
)
def test_two_consumers_refuse_reidentified_authority_paths_without_typed_closure(
    mutation,
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    profile = ldb["language"]["resolution_profiles"][0]
    lowering = ldb["language"]["model_lowerings"][0]
    if mutation.startswith("relation"):
        recipe = next(
            item for item in profile["relation_recipes"] if item["id"] == "imports"
        )
        alias = next(item for item in recipe["fields"] if item["name"] == "alias")
        alias["term"]["path"] = (
            ["missing_member"] if mutation == "relation-missing-path" else []
        )
    elif mutation.startswith("projection"):
        seed = next(
            item
            for item in lowering["runtime_projection"]["seeds"]
            if item["collection"] == "units"
        )
        seed["target_path"] = (
            ["missing_member"] if mutation == "projection-missing-path" else []
        )
    else:
        profile["modules_member"] = "host_drift"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        stage == "static" and code == "kernel.vector_mismatch"
        for stage, code, _subject in first["diagnostics"]
    )
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions",
    ) in first["diagnostics"]


def test_kernel_meta_format_and_ldb_rules_are_structured_for_independent_execution():
    authority = _authority_candidate()
    meta_format = authority["kernel"]["meta_format"]

    assert set(meta_format) == {
        "admitted_language_index",
        "authority_wire_schema_projection",
        "fact",
        "term",
        "rule",
        "rule_selection",
        "binding_substitution",
        "diagnostic_reason",
        "json_pointer",
        "language_bundle",
        "language_definitions",
        "literal_typing",
        "model_program_vector",
        "package_dependency_constraint",
        "package_conformance_vector_set",
        "package_release",
        "package_vector",
        "resolution_judgment",
        "runtime_program",
        "runtime_profile_definition",
        "runtime_projection",
        "template_admission",
    }
    resolution = meta_format["resolution_judgment"]
    assert _consumer_b_package_vector_contract_is_closed(meta_format["package_vector"])
    assert production_bootstrap._package_vector_contract_is_closed(
        meta_format["package_vector"]
    )
    assert resolution["closed"] is True
    assert resolution["stage_order"] == ["static", "resolution"]
    assert [item["id"] for item in resolution["operations"]] == [
        item["id"]
        for stage in resolution["stage_order"]
        for item in resolution["operations"]
        if item["stage"] == stage
    ]
    assert _consumer_b_resolution_contract_is_closed(resolution)
    assert all(
        set(item)
        == {
            "effects",
            "id",
            "input",
            "law",
            "refusals",
            "resources",
            "result",
            "stage",
        }
        for item in resolution["operations"]
    )
    assert all(
        item["input"] == {"fact_kind": "resolution-state"}
        and item["result"] == {"fact_kind": "resolution-state"}
        and item["effects"] == []
        and item["refusals"] == ["reason-bound-diagnostic"]
        and item["resources"]
        for item in resolution["operations"]
    )
    template_admission = meta_format["template_admission"]
    profile = authority["language_bundle"]["language"]["template_admission_profiles"][0]
    assert template_admission["closed"] is True
    assert template_admission["role_contract"] == {
        "identifier": "non-empty-string",
        "cardinalities": ["exactly-one", "one-or-more"],
    }
    assert _consumer_b_template_admission_is_closed(
        meta_format, authority["language_bundle"]
    )
    assert {item["operation"] for item in profile["judgments"]} == {
        item["id"] for item in template_admission["operations"]
    }
    assert all(
        set(item)
        == {
            "effects",
            "id",
            "input",
            "law",
            "refusals",
            "resources",
            "result",
        }
        and item["input"] == {"fact_kind": "template-graph"}
        and item["result"] == {"fact_kind": "template-graph"}
        and item["effects"] == []
        and item["refusals"] == ["reason-bound-diagnostic"]
        and item["resources"]
        and item["law"]["operator"] == item["id"]
        and item["law"]["primitive"]
        in {
            primitive["id"]
            for primitive in template_admission["primitive_spec"]["primitives"]
        }
        for item in template_admission["operations"]
    )
    assert {item["law"]["primitive"] for item in template_admission["operations"]} == {
        primitive["id"]
        for primitive in template_admission["primitive_spec"]["primitives"]
    }
    assert {item["role"] for item in profile["member_roles"]} == {
        "source",
        "experiment",
        "dependencies",
        "defaults",
        "compatibility",
        "documentation",
        "coverage",
        "golden",
        "negative-vector",
        "boundary-vector",
    }
    assert {item["tag"] for item in meta_format["term"]["constructors"]} == {
        "literal",
        "variable",
    }
    for rule in authority["language_bundle"]["language"]["rules"]:
        assert set(rule) == {"id", "phase", "judgment", "premises", "conclusion"}
        assert rule["phase"] in meta_format["rule"]["phases"]
        assert rule["premises"]
        assert set(rule["conclusion"]) == {"fact_kind", "fields"}


def test_kernel_publishes_the_complete_canonical_identity_recipe():
    encoding = _authority_candidate()["kernel"]["canonical_encoding"]

    assert encoding["identity_algorithm"] == "sha256"
    assert encoding["identity_domain_prefix"] == "gda-balancing:"
    assert encoding["identity_domain_suffix"] == ":"
    assert encoding["identity_excluded_members"] == ["content_identity"]
    assert encoding["identity_output_prefix"] == "sha256:"
    assert encoding["digest_hex_case"] == "lowercase"
    assert encoding["document_terminator"] == "LF"
    assert encoding["array_order"] == "preserve"
    assert encoding["whitespace"] == "none"
    assert encoding["item_separator"] == ","
    assert encoding["key_separator"] == ":"
    assert encoding["non_ascii_strings"] == "literal-utf8"
    assert encoding["escape_solidus"] is False
    assert encoding["printable_ascii_escaping"] == (
        "only-quotation-mark-and-reverse-solidus"
    )
    assert encoding["control_character_escaping"] == {
        "backspace": "\\b",
        "form-feed": "\\f",
        "line-feed": "\\n",
        "other-u0000-u001f": "lowercase-u00xx",
        "carriage-return": "\\r",
        "tab": "\\t",
    }
    assert encoding["delete_character_escaping"] == "literal-byte-7f"
    assert encoding["lone_surrogate"] == "refuse"
    assert encoding["number_kinds"] == ["signed-int64"]
    assert encoding["duplicate_object_keys"] == "refuse-at-decoding"
    assert {item["id"] for item in encoding["vectors"]} == {
        "canonical.boundary-integers",
        "canonical.control-character-escaping",
        "canonical.order-array-unicode-escaping",
        "canonical.reject-duplicate-key",
        "canonical.reject-float",
        "canonical.reject-lone-surrogate",
    }


def test_every_kernel_law_publishes_a_complete_machine_contract():
    kernel = _authority_candidate()["kernel"]

    for law in kernel["admission"]["laws"]:
        assert set(law) == {
            "arguments",
            "effects",
            "id",
            "input",
            "operation",
            "refusals",
            "resources",
            "result",
        }
        assert isinstance(law["arguments"], dict)
        assert law["input"] == {"fact_kind": "authority-pair"}
        assert law["result"] == {"fact_kind": "admission-verdict"}
        assert law["effects"] == []
        assert law["refusals"]
        assert isinstance(law["resources"], list)


def test_reidentified_ldb_cannot_hide_a_tampered_package_release():
    authority = _authority_candidate()
    package = authority["language_bundle"]["language"]["packages"][0]
    package["version"] = "2.0.1"
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
    )


def test_package_release_identity_binds_normative_vector_definitions():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    vector_set = _package_vector_set(ldb, package)
    old_release_identity = package["content_identity"]
    old_semantic_identity = package["semantic_identity"]
    old_vector_identity = vector_set["content_identity"]
    vector = _owned_vector(ldb, "model.compile.positive")
    vector["expect"]["debug_map_identity"] = "sha256:" + "f" * 64

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" and subject.endswith(".conformance_vectors")
        for _, code, subject in first["diagnostics"]
    ), first["diagnostics"]

    _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)

    package = ldb["language"]["packages"][0]
    vector_set = _package_vector_set(ldb, package)
    assert vector_set["content_identity"] != old_vector_identity
    assert package["content_identity"] != old_release_identity
    assert package["semantic_identity"] == old_semantic_identity
    assert _consumer_a(authority["kernel"], ldb)["admitted"] is True


def test_kernel_identity_law_owns_every_authority_artifact_domain():
    kernel = _authority_candidate()["kernel"]
    law = next(
        item
        for item in kernel["admission"]["laws"]
        if item["id"] == "kernel.identity.verify"
    )

    assert {
        target.get("artifact") or target.get("collection"): target["domain"]
        for target in law["arguments"]["targets"]
    } == {
        "kernel": "schema-major-kernel-v2",
        "language-bundle": "language-definition-bundle-v2",
        "language_bundle.language.packages": "domain-package-release-v2",
        "language_bundle.package_conformance_vector_sets": (
            "package-conformance-vector-set-v2"
        ),
    }


def test_two_consumers_project_kernel_package_coordinate_patterns():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = next(
        item for item in ldb["language"]["packages"] if item["id"] == "game.combat"
    )
    vector_set = _package_vector_set(ldb, package)
    package["id"] = "game/combat"
    vector_set["package_id"] = package["id"]
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert {code for _stage, code, _subject in first["diagnostics"]} >= {
        "kernel.binding_mismatch",
        "kernel.member_set_mismatch",
    }


def test_two_consumers_follow_an_expanded_kernel_coordinate_pattern(monkeypatch):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    kernel["meta_format"]["package_conformance_vector_set"]["field_types"][
        "package_id"
    ]["pattern"] = r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$"
    _reidentify(kernel, ldb)
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
    )
    monkeypatch.setattr(
        bootstrap_support, "_SUPPORTED_KERNEL_IDENTITY", kernel["content_identity"]
    )

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is True
    assert first["diagnostics"] == []


@pytest.mark.parametrize(
    "mutation",
    (
        "contract-expectation",
        "runtime-operation",
        "unknown-kind",
    ),
)
def test_reidentified_package_evidence_vector_mutations_refuse_in_both_consumers(
    mutation,
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    if mutation == "contract-expectation":
        package = next(
            item
            for item in ldb["language"]["packages"]
            if item["id"] == "game.resource"
        )
        vector = _owned_vector(ldb, "game.resource.spend.effects")
        vector["expect"] = ["event.commit"]
    elif mutation in {"runtime-operation", "unknown-kind"}:
        package = next(
            item for item in ldb["language"]["packages"] if item["id"] == "game.combat"
        )
        vector = _owned_vector(ldb, "game.combat.cast.positive")
        if mutation == "runtime-operation":
            vector["operation"] = "game.combat.damage-v1"
        else:
            vector["kind"] = "host-runtime-scenario"
    _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" and subject.endswith(".vectors")
        for _, code, subject in first["diagnostics"]
    ), first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    ("category", "kind-members", "probe-root"),
)
def test_reidentified_package_vector_contract_mutations_refuse_in_both_consumers(
    mutation, monkeypatch
):
    authority = _authority_candidate()
    contract = authority["kernel"]["meta_format"]["package_vector"]
    if mutation == "category":
        contract["categories"].append("host-category")
    elif mutation == "kind-members":
        contract["kinds"][0]["required_members"].append("host")
    else:
        contract["package_probe_roots"].append("content_identity")
    _reidentify(authority["kernel"], authority["language_bundle"])
    kernel_identity = authority["kernel"]["content_identity"]
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )
    monkeypatch.setattr(
        bootstrap_support, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "kernel.meta_format.package_vector",
    ) in first["diagnostics"]


def test_package_identity_binds_the_complete_exported_definition_closure():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        item
        for item in ldb["language"]["operations"]
        if item["id"] == "quantity.identity"
    )
    operation["resource_bounds"]["max_steps"] = 2
    package = next(
        item for item in ldb["language"]["packages"] if item["id"] == "core.quantity"
    )
    operation_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    embedded = next(
        item
        for item in operation_entry["definitions"]
        if item["id"] == "quantity.identity"
    )
    embedded["resource_bounds"]["max_steps"] = 2
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch"
        and subject == "language-bundle.language.packages.0"
        for _, code, subject in first["diagnostics"]
    )


def test_reidentified_package_cannot_hide_a_tampered_embedded_definition():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = next(
        item for item in ldb["language"]["packages"] if item["id"] == "core.quantity"
    )
    operation_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    embedded = next(
        item
        for item in operation_entry["definitions"]
        if item["id"] == "quantity.identity"
    )
    embedded["resource_bounds"]["max_steps"] = 2
    package["content_identity"] = _identity("domain-package-release-v2", package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch"
        and subject == "language-bundle.language.packages.0.semantic_identity"
        for _, code, subject in first["diagnostics"]
    )


def test_kernel_treats_package_extensions_as_canonical_opaque_values():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        item
        for item in ldb["language"]["operations"]
        if item["id"] == "game.combat.damage-v1"
    )
    slots = operation["extensions"]["standard.formula-slots"]
    slots[0]["parameters"][1]["source"]["name"] = "package-owned-port"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "ldb-artifact-kind",
        "ldb-schema-major",
        "diagnostic-extra-member",
        "package-id-type",
        "package-version-type",
        "package-exported-type-empty-id",
    ],
)
def test_reidentified_ldb_and_package_shapes_remain_closed(mutation):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]

    if mutation == "ldb-artifact-kind":
        ldb["artifact_kind"] = "not-a-bundle"
        ldb.root["artifact_kind"] = "not-a-bundle"
    elif mutation == "ldb-schema-major":
        ldb["schema_major"] = 3
        ldb.root["schema_major"] = 3
    elif mutation == "diagnostic-extra-member":
        ldb["diagnostics"][0]["host_semantics"] = True
        diagnostic_code = ldb["diagnostics"][0]["code"]
        package = next(
            candidate
            for candidate in ldb["language"]["packages"]
            if diagnostic_code in candidate["exports"]["diagnostics"]
        )
        diagnostic_entry = next(
            entry
            for entry in package["semantic_closure"]
            if entry["authority_path"] == "diagnostics"
        )
        next(
            row
            for row in diagnostic_entry["definitions"]
            if row["code"] == diagnostic_code
        )["host_semantics"] = True
        _reidentify_package_release(package)
    elif mutation == "package-id-type":
        package["id"] = 7
    elif mutation == "package-version-type":
        package["version"] = False
    else:
        package["exports"]["types"][0]["id"] = ""

    if mutation.startswith("package-"):
        package["content_identity"] = _identity("domain-package-release-v2", package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_reidentified_package_cannot_reference_an_unowned_vector():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    vector_set = _package_vector_set(ldb, package)
    vector_set["vectors"][0] = "host.missing"
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch"
        and subject == "language-bundle.language.packages.0.vectors"
        for _, code, subject in first["diagnostics"]
    ), first["diagnostics"]


def test_bootstrap_projects_every_kernel_law_without_a_host_fallback_table():
    authority = _authority_candidate()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    law_ids = {item["id"] for item in authority["kernel"]["admission"]["laws"]}
    assert {law_id for law_id, _ in admission.law_projections} == law_ids
    assert all(
        identity.startswith("sha256:") for _, identity in admission.law_projections
    )


def test_reidentified_duplicate_vector_id_is_refused_by_both_consumers():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    duplicate = deepcopy(ldb["vectors"][0])
    duplicate["rule"] = "quantity.lower"
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if duplicate["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    vector_set["vectors"].append(duplicate["id"])
    vector_set["vector_definitions"].append(duplicate)
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert any(
        code == "kernel.vector_mismatch" and subject.endswith(".vectors")
        for _, code, subject in first["diagnostics"]
    )


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("exports", "operations"), ["host.invented"]),
        (("exports", "components"), ["host.invented"]),
        (("exports", "conversions"), ["host.invented"]),
        (("profiles", "runtime"), ["host.invented"]),
        (("capabilities", "provided"), ["host.invented"]),
        (("capabilities", "required"), ["host.invented"]),
        (
            ("dependencies", "required"),
            [{"id": "host.invented", "version": "1.0.0"}],
        ),
        (
            ("dependencies", "optional"),
            [{"id": "host.invented", "version": "1.0.0"}],
        ),
    ],
)
def test_reidentified_package_cannot_hide_an_unowned_reference(path, replacement):
    authority = _authority_candidate()
    package = authority["language_bundle"]["language"]["packages"][0]
    target = package
    for member in path[:-1]:
        target = target[member]
    target[path[-1]] = replacement
    package["content_identity"] = _identity("domain-package-release-v2", package)
    _reidentify_graph_root(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    semantic_owner_paths = {
        ("exports", "operations"),
        ("exports", "components"),
        ("exports", "conversions"),
        ("profiles", "runtime"),
        ("capabilities", "provided"),
    }
    expected_code = (
        "kernel.identity_mismatch"
        if path in semantic_owner_paths
        else (
            "kernel.binding_mismatch"
            if path[0] == "dependencies"
            else "kernel.vector_mismatch"
        )
    )
    assert any(code == expected_code for _, code, _ in first["diagnostics"])


def test_reidentified_local_result_source_requires_a_compatible_node_producer():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    operation["body"].insert(
        -1,
        {
            "node": "less-than",
            "target": "bad_result",
            "left": "base_damage",
            "right": "mitigation",
        },
    )
    operation["resource_bounds"]["max_steps"] += 1
    operation["result"]["source"] = {"kind": "local", "name": "bad_result"}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat@2.0.0.game.combat.damage-v1.result.source",
    ) in first["diagnostics"]


def test_local_result_source_must_exist_before_every_successful_exit_path():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    operation["outcomes"].append(
        {
            "id": "early-applied",
            "kind": "success",
            "state_policy": "commit",
        }
    )
    operation["body"].insert(
        0,
        {
            "node": "precondition-greater-than-or-equal",
            "left": "base_damage",
            "right": "mitigation",
            "outcome": "early-applied",
        },
    )
    operation["resource_bounds"]["max_steps"] += 1
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat@2.0.0.game.combat.damage-v1.result.source",
    ) in first["diagnostics"]


def test_reidentified_non_string_variable_term_returns_a_typed_refusal():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["rules"][0]["conclusion"]["fields"][
        "role"
    ]["name"] = {"host": "role"}
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_conflicting_duplicate_binding_refuses_in_both_consumers():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if "quantity.declare" in candidate["exports"]["language_rules"]
    )
    rules = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.rules"
    )
    rule = next(
        definition
        for definition in rules["definitions"]
        if definition["id"] == "quantity.declare"
    )
    rule["premises"].append(deepcopy(rule["premises"][0]))
    vector = _owned_vector(ldb, "quantity.declare.valid")
    conflicting_fact = deepcopy(vector["input"]["facts"][0])
    conflicting_fact["fields"]["role"] = "input"
    vector["input"]["facts"].append(conflicting_fact)
    vector["expect"]["fields"]["role"] = "input"
    _bind_package_vector_set(package, _package_vector_set(ldb, package))
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_old_identity_tamper_and_reidentified_behavior_or_token_mutations_refuse():
    baseline = _authority_candidate()

    old_identity = deepcopy(baseline)
    old_identity["language_bundle"]["language"]["rules"][0]["conclusion"][
        "fact_kind"
    ] = "changed"
    first = _consumer_a(old_identity["kernel"], old_identity["language_bundle"])
    second = _consumer_b(old_identity["kernel"], old_identity["language_bundle"])
    assert first == second
    assert any(
        code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
    )

    for index in range(len(baseline["kernel"]["admission"]["laws"])):
        authority = deepcopy(baseline)
        authority["kernel"]["admission"]["laws"][index]["operation"] += ".renamed"
        _reidentify(authority["kernel"], authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert any(
            code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
        )

    for index in range(len(baseline["language_bundle"]["language"]["rules"])):
        authority = deepcopy(baseline)
        ldb = authority["language_bundle"]
        rule_id = ldb["language"]["rules"][index]["id"]
        package = next(
            candidate
            for candidate in ldb["language"]["packages"]
            if rule_id in candidate["exports"]["language_rules"]
        )
        rules = next(
            entry
            for entry in package["semantic_closure"]
            if entry["authority_path"] == "language.rules"
        )
        rule = next(
            definition
            for definition in rules["definitions"]
            if definition["id"] == rule_id
        )
        rule["conclusion"]["fact_kind"] += ".changed"
        _reidentify_package_release(package)
        _reidentify_graph_root(ldb)
        first = _consumer_a(authority["kernel"], ldb)
        second = _consumer_b(authority["kernel"], ldb)
        assert first == second
        assert any(
            code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
        )

    for owner, path in (
        ("kernel", ("admission", "laws")),
        ("language_bundle", ("language", "rules")),
    ):
        authority = deepcopy(baseline)
        collection = authority[owner]
        for part in path:
            collection = collection[part]
        if owner == "kernel":
            collection[0]["id"] += ".renamed"
            _reidentify(authority["kernel"], authority["language_bundle"])
        else:
            ldb = authority["language_bundle"]
            rule_id = collection[0]["id"]
            package = next(
                candidate
                for candidate in ldb["language"]["packages"]
                if rule_id in candidate["exports"]["language_rules"]
            )
            rules = next(
                entry
                for entry in package["semantic_closure"]
                if entry["authority_path"] == "language.rules"
            )
            rule = next(
                definition
                for definition in rules["definitions"]
                if definition["id"] == rule_id
            )
            renamed = f"{rule_id}.renamed"
            package["exports"]["language_rules"][
                package["exports"]["language_rules"].index(rule_id)
            ] = renamed
            rule["id"] = renamed
            _reidentify_package_release(package)
            _reidentify_graph_root(ldb)
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        expected_code = (
            "kernel.identity_mismatch"
            if owner == "kernel"
            else "kernel.vector_mismatch"
        )
        assert any(code == expected_code for _, code, _ in first["diagnostics"])


def test_reidentified_kernel_law_operand_mutation_is_refused_by_both_consumers():
    authority = _authority_candidate()
    binding_law = next(
        law
        for law in authority["kernel"]["admission"]["laws"]
        if law["id"] == "kernel.binding.exact"
    )
    binding_law["arguments"]["left"] = "language_bundle.host_invented_binding"
    _reidentify(authority["kernel"], authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
    )


def test_descriptor_transport_order_does_not_change_the_canonical_graph():
    authority = _authority_candidate()
    baseline = authority["language_bundle"]
    reordered_root = deepcopy(baseline.root)
    reordered_root["package_descriptors"].reverse()
    reordered = LanguageBundleGraph(
        root=reordered_root,
        package_releases=list(reversed(baseline.package_releases)),
        package_conformance_vector_sets=list(
            reversed(baseline.package_conformance_vector_sets)
        ),
        root_byte_size=baseline.root_byte_size,
        package_byte_sizes=list(reversed(baseline.package_byte_sizes)),
        vector_set_byte_sizes=list(reversed(baseline.vector_set_byte_sizes)),
    )

    first = _consumer_a(authority["kernel"], reordered)
    second = _consumer_b(authority["kernel"], reordered)

    assert first == second
    assert first["admitted"] is True
    assert reordered.root["package_descriptors"] == list(
        reversed(baseline.root["package_descriptors"])
    )
    assert first["language_bundle_identity"] == baseline["content_identity"]
