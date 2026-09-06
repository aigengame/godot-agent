"""Schema 2.0 bootstrap conformance: composition ownership."""

# ruff: noqa: F403, F405
import schema2_bootstrap_conformance_support as bootstrap_support
from schema2_bootstrap_conformance_support import *
from schema2_bootstrap_production_support import *


def _rename_structural_type_member(value, *, kind, old, new):
    if isinstance(value, dict):
        if value.get("kind") == kind and old in value:
            value[new] = value.pop(old)
        for child in value.values():
            _rename_structural_type_member(child, kind=kind, old=old, new=new)
    elif isinstance(value, list):
        for child in value:
            _rename_structural_type_member(child, kind=kind, old=old, new=new)


@pytest.mark.parametrize(
    ("constructor_id", "rule_member", "kind", "old", "new"),
    (
        ("standard.schema.record", "fields_member", "record", "fields", "members"),
        ("standard.schema.list", "element_member", "list", "element", "item"),
    ),
)
def test_two_consumers_follow_constructor_member_indirection(
    constructor_id, rule_member, kind, old, new
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    language = ldb["language"]
    constructor = next(
        item for item in language["constructors"] if item["id"] == constructor_id
    )
    constructor["value_rule"][rule_member] = new
    for nominal_type in language["nominal_types"]:
        _rename_structural_type_member(
            nominal_type["definition"], kind=kind, old=old, new=new
        )
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True, first["diagnostics"]


@pytest.mark.parametrize(
    ("law_member", "replacement", "diagnostic_member"),
    (
        ("result_projection", "list-element-type", "typing"),
        ("refusal_signal", "example-unknown-signal", "refusals"),
    ),
)
def test_two_consumers_require_declared_record_lookup_semantics(
    law_member, replacement, diagnostic_member
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        item
        for item in ldb["language"]["structured_operations"]
        if item["id"] == "standard.schema.record-field-v1"
    )
    operation["law"][law_member] = replacement
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.standard.conformance.structured."
        "standard.conformance.structured.select-v1.body.0."
        f"{diagnostic_member}",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    (
        "guard-unbound-condition",
        "guard-wrong-condition-type",
        "nested-guard",
        "undeclared-outcome",
        "guard-unbound-body-reference",
        "guard-body-unknown-member",
        "guard-body-early-outcome",
        "guard-body-propagated-outcome",
        "undeclared-require-reason",
        "insufficient-resource-bound",
    ),
)
def test_two_consumers_refuse_invalid_runtime_control_compositions(mutation):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        item
        for item in ldb["language"]["operations"]
        if item["id"] == "standard.conformance.structured.select-v1"
    )
    guard = next(item for item in operation["body"] if item["node"] == "guard-block")
    requirement = next(item for item in operation["body"] if item["node"] == "require")

    if mutation == "guard-unbound-condition":
        guard["condition"] = "missing-condition"
    elif mutation == "guard-wrong-condition-type":
        guard["condition"] = "candidates"
    elif mutation == "nested-guard":
        guard["body"] = [deepcopy(guard)]
    elif mutation == "undeclared-outcome":
        guard["outcome"] = "unknown-outcome"
    elif mutation == "guard-unbound-body-reference":
        guard["body"] = [{"node": "copy", "target": "copied", "value": "missing-value"}]
    elif mutation == "guard-body-unknown-member":
        guard["body"][0]["unexpected"] = True
    elif mutation == "guard-body-early-outcome":
        guard["body"] = [
            {
                "node": "precondition-greater-than-or-equal",
                "left": "selection_metric",
                "right": "selection_metric",
                "outcome": "selected",
            }
        ]
    elif mutation == "guard-body-propagated-outcome":
        guard["body"] = [
            {
                "node": "invoke",
                "site": "guarded-spend",
                "operation": {
                    "package": "game.resource",
                    "id": "game.resource.spend-v1",
                },
                "arguments": [
                    {
                        "port": "resource",
                        "operand": {"kind": "port", "port": "selection_metric"},
                    },
                    {"port": "cost", "operand": {"kind": "literal", "literal": 1}},
                ],
                "result": {"kind": "discard"},
                "outcomes": [
                    {"outcome": "spent", "action": {"kind": "continue"}},
                    {
                        "outcome": "insufficient-resource",
                        "action": {
                            "kind": "propagate",
                            "outcome": "candidate-mismatch",
                        },
                    },
                ],
            }
        ]
        operation["resource_bounds"]["max_steps"] += 8
        _owned_vector(ldb, "structured.select.resource-bound")["expect"] += 8
    elif mutation == "undeclared-require-reason":
        requirement["reason"] = "example.reason.not-declared"
    else:
        operation["resource_bounds"]["max_steps"] = 3
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        "standard.conformance.structured.select-v1" in subject
        for _stage, _code, subject in first["diagnostics"]
    )


@pytest.mark.parametrize(
    ("member", "replacement"),
    (
        ("instruction_member", "unknown-reason-member"),
        ("source", "ambient-operation-refusals"),
    ),
)
def test_two_consumers_follow_require_refusal_reference(
    member, replacement, monkeypatch
):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    require = next(
        node
        for node in kernel["meta_format"]["runtime_program"]["nodes"]
        if node["id"] == "require"
    )
    require["semantics"]["refusal_reference"][member] = replacement
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
    assert any(
        "standard.conformance.structured.select-v1" in subject
        for _stage, _code, subject in first["diagnostics"]
    )


@pytest.mark.parametrize(
    ("member", "replacement"),
    (
        ("owner_constructor", "standard.schema.record"),
        ("operator", "unknown-list-law"),
        ("result_contract", "kernel-unit"),
        ("max_steps", 0),
    ),
)
def test_two_consumers_close_list_empty_law(member, replacement):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    law = next(
        row
        for row in ldb["language"]["structured_operations"]
        if row["id"] == "standard.schema.list-empty-v1"
    )
    target = law["resource_bounds"] if member == "max_steps" else law
    if member in {"operator", "result_contract"}:
        target = law["law"]
    target[member] = replacement
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def _install_negative_vector_artifact_contract(ldb, *, retain_standalone):
    language = ldb["language"]
    source = next(
        item
        for item in language["artifact_wire_schemas"]
        if item["artifact_kind"] == "negative-vector"
    )
    wire_identity_domain = source["wire_schema_identity_domain"]
    schema_kind = (
        "negative-vector-alt-schema" if retain_standalone else "negative-vector-schema"
    )
    package = next(
        item for item in language["packages"] if item["id"] == "standard.schema"
    )
    schema_exports = package["exports"]["artifact_wire_schemas"]
    if retain_standalone:
        schema_definition = deepcopy(source)
        schema_definition.pop("wire_schema_identity_domain")
        schema_definition["artifact_kind"] = schema_kind
        language["artifact_wire_schemas"].append(schema_definition)
        schema_exports.append(schema_kind)
    else:
        source.pop("wire_schema_identity_domain")
        source["artifact_kind"] = schema_kind
        schema_exports[schema_exports.index("negative-vector")] = schema_kind
    language["artifact_contracts"].append(
        {
            "artifact_kind": "negative-vector",
            "identity_domain": "negative-vector-v2",
            "identity_excluded_members": [],
            "schema_kind": schema_kind,
            "wire_schema_identity_domain": wire_identity_domain,
        }
    )
    package["exports"]["artifact_contracts"].append("negative-vector")
    _refresh_package_closure_and_reidentify(ldb)


def test_two_consumers_admit_reidentified_nested_integer_literal():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    cast_operation = next(
        operation
        for operation in ldb["language"]["operations"]
        if operation["id"] == "game.combat.cast-v1"
    )
    spend_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "spend-resource"
    )
    cost = next(
        argument for argument in spend_call["arguments"] if argument["port"] == "cost"
    )
    cost["operand"] = {"kind": "literal", "literal": 8}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


def test_two_consumers_admit_a_template_role_with_distinct_artifact_schema_kind():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    _install_negative_vector_artifact_contract(ldb, retain_standalone=False)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


def test_two_consumers_refuse_an_artifact_kind_that_shadows_a_standalone_schema():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    _install_negative_vector_artifact_contract(ldb, retain_standalone=True)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.wire-schema-identity-domains",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "initialization_source",
    ("named-random-stream", "resolved-model"),
)
def test_two_consumers_refuse_assignment_modes_without_an_operand_value_producer(
    initialization_source,
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    policy = ldb["language"]["model_lowerings"][0]["assignment_policy"]
    parameter = next(row for row in policy["roles"] if row["role"] == "parameter")
    mode = next(row for row in parameter["modes"] if row["id"] == "experiment-required")
    mode.update(
        {
            "initialization_source": initialization_source,
            "value_member": "forbidden",
            "experiment_cardinality": "forbidden",
            "override": False,
        }
    )
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions.assignment-policy",
    ) in first["diagnostics"]


def test_literal_typing_is_an_independent_package_owned_authority():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    language = ldb["language"]
    policy = language["model_lowerings"][0]["assignment_policy"]
    profiles = language["literal_typing_profiles"]
    owners = {
        package["id"]: package
        for package in language["packages"]
        if package["id"] == "core.quantity"
    }
    structured_owner = next(
        package
        for package in language["packages"]
        if package["id"] == "standard.schema"
    )

    assert "literal_profiles" not in policy
    assert "literal_selection" not in policy
    assert [profile["id"] for profile in profiles] == [
        "quantity.dimensionless-int64-v2-2",
        "quantity.positive-dimensionless-int64-v2-2",
        "standard.schema.nominal-structured",
    ]
    assert set(owners) == {"core.quantity"}
    assert owners["core.quantity"]["exports"]["literal_typing_profiles"] == [
        "quantity.dimensionless-int64-v2-2",
        "quantity.positive-dimensionless-int64-v2-2",
    ]
    assert structured_owner["exports"]["literal_typing_profiles"] == [
        "standard.schema.nominal-structured"
    ]
    assert all(
        "language.literal_typing_profiles" in owner["runtime_semantic_paths"]
        for owner in owners.values()
    )
    assert (
        "language.literal_typing_profiles" in structured_owner["runtime_semantic_paths"]
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-type",
        "missing-numeric-policy",
        "overlapping-profile",
    ),
)
def test_two_consumers_refuse_unclosed_or_ambiguous_literal_typing_profiles(
    mutation,
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    profiles = ldb["language"]["literal_typing_profiles"]
    profile = profiles[0]
    if mutation == "missing-type":
        profile["type"]["id"] = "MissingQuantity"
    elif mutation == "missing-numeric-policy":
        profile["numeric_policy"] = "missing-numeric-policy"
    else:
        overlapping = deepcopy(profile)
        overlapping["id"] = "quantity.dimensionless-int64-overlap"
        profiles.append(overlapping)
        owner = next(
            package
            for package in ldb["language"]["packages"]
            if package["id"] == "core.quantity"
        )
        owner["exports"]["literal_typing_profiles"].append(overlapping["id"])
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.literal-typing-profiles",
    ) in first["diagnostics"]


def test_distinct_overlapping_numeric_literal_profiles_preserve_operation_admission():
    authority = _authority_candidate()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    language = ldb["language"]
    owner = next(
        package for package in language["packages"] if package["id"] == "core.quantity"
    )
    currency_constructor = deepcopy(
        next(
            constructor
            for constructor in language["constructors"]
            if constructor["id"] == "core.quantity"
        )
    )
    currency_constructor["id"] = "core.currency"
    language["constructors"].append(currency_constructor)
    owner["exports"]["constructors"].append(currency_constructor["id"])
    currency_profile = deepcopy(language["literal_typing_profiles"][0])
    currency_profile["id"] = "currency.dimensionless-int64"
    currency_profile["type"]["id"] = "Currency"
    language["literal_typing_profiles"].append(currency_profile)
    owner["exports"]["literal_typing_profiles"].append(currency_profile["id"])
    owner["exports"]["types"].append({"constructor": "core.currency", "id": "Currency"})
    currency_identity = deepcopy(
        next(
            operation
            for operation in language["operations"]
            if operation["id"] == "quantity.identity"
        )
    )
    currency_identity["id"] = "currency.identity"
    currency_identity["vectors"] = [
        vector_id
        for vector_id in currency_identity["vectors"]
        if vector_id != "formula.notation.quantity.identity"
    ]
    currency_notation_vector = deepcopy(
        _owned_vector(ldb, "formula.notation.quantity.identity")
    )
    currency_notation_vector["id"] = "formula.notation.currency.identity"
    currency_notation_vector["operation"] = currency_identity["id"]
    currency_identity["vectors"].append(currency_notation_vector["id"])
    for contract in [*currency_identity["inputs"], currency_identity["result"]]:
        contract["type"]["id"] = "Currency"
    language["operations"].append(currency_identity)
    owner["exports"]["operations"].append(currency_identity["id"])
    vector_set = _package_vector_set(ldb, owner)
    vector_set["vector_definitions"].append(currency_notation_vector)
    vector_set["vectors"].append(currency_notation_vector["id"])
    _refresh_package_closure_and_reidentify(ldb)

    assert production_bootstrap._literal_typing_profiles_are_closed(kernel, ldb)
    assert _consumer_b_literal_typing_profiles_are_closed(kernel, ldb)
    assert (
        production_bootstrap._operation_composition_diagnostic_subjects(
            kernel,
            ldb,
        )
        == ()
    )
    assert _consumer_b_operation_composition_subjects(kernel, ldb) == ()
    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)
    assert first == second
    assert first["admitted"] is True, first["diagnostics"]


@pytest.mark.parametrize(
    ("mutation", "subject_owner", "subject_suffix"),
    (
        (
            "effect",
            "combat",
            "game.combat.cast-v1.body.hit-check.effects",
        ),
        (
            "refusal",
            "combat",
            "game.combat.cast-v1.body.hit-check.refusals",
        ),
        (
            "resource",
            "combat",
            "game.combat.cast-v1.resource_bounds",
        ),
        (
            "cycle",
            "check",
            "game.check.hit-v1.body.cycle.operation",
        ),
        (
            "argument-contract",
            "combat",
            "game.combat.cast-v1.body.hit-check.arguments",
        ),
        (
            "literal-contract",
            "combat",
            "game.combat.cast-v1.body.apply-damage.arguments",
        ),
    ),
    ids=(
        "effect-language.operations.game.combat.game.combat.cast-v1.body.hit-check.effects",
        "refusal-language.operations.game.combat.game.combat.cast-v1.body.hit-check.refusals",
        "resource-language.operations.game.combat.game.combat.cast-v1.resource_bounds",
        "cycle-language.operations.game.check.game.check.hit-v1.body.cycle.operation",
        "argument-contract-language.operations.game.combat.game.combat.cast-v1.body.hit-check.arguments",
        "literal-contract-language.operations.game.combat.game.combat.cast-v1.body.apply-damage.arguments",
    ),
)
def test_two_consumers_refuse_every_reidentified_operation_composition_violation(
    mutation,
    subject_owner,
    subject_suffix,
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operations = {
        operation["id"]: operation for operation in ldb["language"]["operations"]
    }
    hit = operations["game.check.hit-v1"]
    cast_operation = operations["game.combat.cast-v1"]
    if mutation == "effect":
        hit["effects"].append("hidden.child-effect")
    elif mutation == "refusal":
        hit["refusals"].append("hidden.child-refusal")
    elif mutation == "resource":
        cast_operation["resource_bounds"]["max_steps"] = 1
    elif mutation == "argument-contract":
        defense = next(port for port in hit["inputs"] if port["id"] == "defense")
        defense["numeric_policy"] = "exact-bool"
    elif mutation == "literal-contract":
        damage_call = next(
            instruction
            for instruction in cast_operation["body"]
            if instruction.get("site") == "apply-damage"
        )
        critical = next(
            argument
            for argument in damage_call["arguments"]
            if argument["port"] == "critical"
        )
        critical["operand"] = {"kind": "literal", "literal": 1}
    else:
        hit["body"] = [
            {
                "arguments": [
                    {
                        "operand": {"kind": "port", "port": "accuracy"},
                        "port": "accuracy",
                    },
                    {
                        "operand": {"kind": "port", "port": "defense"},
                        "port": "defense",
                    },
                ],
                "node": "invoke",
                "operation": {
                    "id": "game.check.hit-v1",
                    "package": "game.check",
                },
                "outcomes": [
                    {
                        "action": {"kind": "continue"},
                        "outcome": "hit",
                    },
                    {
                        "action": {"kind": "continue"},
                        "outcome": "miss",
                    },
                ],
                "result": {"kind": "discard"},
                "site": "self",
            }
        ]
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    subject_package = "game.check" if subject_owner == "check" else "game.combat"
    expected_subject = f"language.operations.{subject_package}.{subject_suffix}"
    assert (
        "static",
        "kernel.vector_mismatch",
        expected_subject,
    ) in first["diagnostics"]


@pytest.mark.parametrize("member", ("member_roles", "judgments"))
def test_two_consumers_refuse_an_incomplete_template_admission_profile(member):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    ldb["language"]["template_admission_profiles"][0][member].pop()
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_two_consumers_refuse_template_model_source_identity_domain_drift():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    judgment = next(
        row
        for row in ldb["language"]["template_admission_profiles"][0]["judgments"]
        if row["id"] == "template.derive-source-identity"
    )
    judgment["arguments"]["identity_domain"] = "template-only-model-source-v2"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_runtime_program_contract_is_independently_executable_and_profile_bound():
    authority = _authority_candidate()
    runtime = authority["kernel"]["meta_format"]["runtime_program"]

    assert set(runtime) == {
        "closed",
        "version",
        "fixed_value_contracts",
        "expression_nodes",
        "effect_nodes",
        "control_nodes",
        "nodes",
        "numeric",
        "named_rng",
        "scheduler",
        "event_atomicity",
        "component_contract",
        "outcome_contract",
        "invocation_contract",
        "runtime_configuration",
        "transition",
        "step",
        "vectors",
    }
    nodes = {item["id"]: item for item in runtime["nodes"]}
    assert set(nodes) == {
        *runtime["expression_nodes"],
        *runtime["effect_nodes"],
        *runtime["control_nodes"],
    }
    assert len(nodes) == len(runtime["nodes"])
    assert runtime["scheduler"]["external_input_admission"] == {
        "ordering": ["source_identity", "source_sequence"],
        "sequence_origin": 0,
        "continuity": "contiguous-per-source",
    }
    for node_id, node in nodes.items():
        assert set(node) == {
            "family",
            "id",
            "operand_constraints",
            "refusals",
            "required_members",
            "resource_charge",
            "result",
            "semantics",
        }
        assert node["family"] in {"expression", "effect", "control"}
        assert node_id in runtime[f"{node['family']}_nodes"]
        assert node["required_members"][0] == "node"
        assert node["resource_charge"] == {
            "amount": 1,
            "counter": "event-steps",
        }
        assert isinstance(node["semantics"]["operator"], str)
        assert node["semantics"]["operator"]
        assert isinstance(node["result"]["kind"], str)
        assert node["result"]["kind"]
        if node["result"]["kind"] in {"local", "draw"}:
            assert node["result"]["typing"]["kind"] in {
                "declared-result",
                "fixed",
                "same-as-references",
                "literal-profile",
            }
        assert isinstance(node["operand_constraints"], list)

    assert set(runtime["fixed_value_contracts"]) == {
        "kernel-boolean",
        "kernel-event-reference",
        "kernel-unit",
    }
    assert runtime["numeric"] == {
        "compatible_value_numeric_policies": ["exact-int64"],
        "id": "signed-int64-v1",
        "minimum": -(1 << 63),
        "maximum": (1 << 63) - 1,
        "overflow": "runtime-refusal",
        "overflow_signal": "numeric-overflow",
    }
    assert runtime["named_rng"] == {
        "algorithm": "splitmix64-v1",
        "word_bits": 64,
        "seed_encoding": "unsigned-modulo-2^64",
        "stream_name_encoding": "utf-8",
        "candidate_encoding": {
            "alphabet": "0123456789abcdef",
            "case": "lowercase",
            "radix": 16,
            "width_bits": 64,
            "zero_pad": True,
        },
        "stream_derivation": {
            "hash": "sha256",
            "digest_slice": {"offset": 0, "length": 8},
            "byte_order": "big",
            "combine": "unsigned-add-modulo-2^64",
        },
        "state_transition": {
            "increment_hex": "9e3779b97f4a7c15",
            "mix_steps": [
                {"xor_shift_right": 30, "multiply_hex": "bf58476d1ce4e5b9"},
                {"xor_shift_right": 27, "multiply_hex": "94d049bb133111eb"},
                {"xor_shift_right": 31},
            ],
        },
        "interval_sampling": {
            "bounds": "inclusive",
            "mapping": "unsigned-modulo-width",
            "bias_policy": "accepted-modulo-bias-v1",
            "candidates_per_draw": 1,
        },
        "trace_members": [
            "stream",
            "index",
            "candidate_hex",
            "accepted",
            "minimum",
            "maximum",
            "value",
        ],
    }
    assert runtime["event_atomicity"] == {
        "state_writes": "buffered",
        "rng_draws": "buffered",
        "child_events": "buffered",
        "cancellations": "buffered",
        "success": "commit-entire-current-event",
        "runtime_refusal": "rollback-entire-current-event",
    }
    assert runtime["scheduler"]["call_site_identity"] == {
        "schedule": {
            "domain": "runtime-schedule-call-site-v2",
            "projection": [
                "parent_event_id",
                "parent_operation",
                "site",
                "operation",
            ],
        },
        "cancel": {
            "domain": "runtime-cancel-call-site-v2",
            "projection": [
                "canceling_event_id",
                "operation",
                "site",
                "target_event_id",
            ],
        },
    }
    assert runtime["scheduler"]["schedule"] == {
        "child_phase": "transition",
        "legal_position": "strictly-after-active-ordering-key",
        "same_time_priority": "not-greater-than-active-priority",
        "refusal_signals": {
            "backward": "schedule-backward",
            "hidden_input": "schedule-hidden-input",
            "illegal_same_time_priority": "schedule-illegal-same-time-priority",
        },
    }
    assert runtime["scheduler"]["cancel"] == {
        "admitted_target_states": ["pending", "provisional"],
        "refusal_signals": {
            "active": "cancel-active",
            "completed": "cancel-completed",
            "unknown": "cancel-unknown",
        },
    }
    assert runtime["scheduler"]["budget_members"] == {
        "event_steps": "max_event_steps",
        "logical_time": "max_logical_time",
        "node_steps": "max_node_steps",
        "queue_events": "max_queue_events",
        "total_events": "max_total_events",
        "zero_time_depth": "max_zero_time_depth",
    }
    assert runtime["outcome_contract"] == {
        "kinds": ["success", "gameplay-alternative"],
        "state_policies": ["commit", "rollback"],
        "operation_members": ["outcomes", "default_outcome"],
    }
    assert runtime["invocation_contract"]["scope"] == "lexical-call-frame"
    assert runtime["invocation_contract"]["ambient_capture"] == "forbidden"
    assert runtime["invocation_contract"]["outcome_mapping"] == (
        "exactly-once-and-exhaustive"
    )
    node_vectors = {
        item["node"]: item for item in runtime["vectors"] if item["kind"] == "node"
    }
    assert set(node_vectors) == set(nodes)
    for node_id, node in nodes.items():
        assert (
            node_vectors[node_id]["expect"]["operand_constraints"]
            == node["operand_constraints"]
        )
        assert node_vectors[node_id]["expect"].get("result_typing") == node[
            "result"
        ].get("typing")
    assert {item["id"] for item in runtime["vectors"] if item["kind"] == "rng"} == {
        "rng.first-draw",
        "rng.multi-draw",
        "rng.cross-stream",
        "rng.interval-boundary",
    }
    invocation_vectors = {
        item["id"]: item
        for item in runtime["vectors"]
        if item["kind"] == "invocation-result-contract"
    }
    assert invocation_vectors["runtime.invocation.result-contract-compatible"][
        "expect"
    ] == {"admitted": True}
    assert invocation_vectors["runtime.invocation.result-contract-incompatible"][
        "expect"
    ] == {"admitted": False}

    profile = next(
        item
        for item in authority["language_bundle"]["language"]["runtime_profiles"]
        if item["id"] == "standard.exact-int64-event-v1"
    )
    assert profile["runtime_program_version"] == runtime["version"]
    assert profile["numeric_law"] == runtime["numeric"]["id"]
    assert profile["rng"] == {
        "algorithm": runtime["named_rng"]["algorithm"],
        "interval_sampling": runtime["named_rng"]["interval_sampling"]["mapping"],
        "bias_policy": runtime["named_rng"]["interval_sampling"]["bias_policy"],
    }
    assert profile["budget_scopes"] == {
        "event_steps": "per-event-transaction",
        "logical_time": "per-event",
        "node_steps": "per-run",
        "operation_steps": "per-operation-invocation",
        "queue_events": "pending-and-provisional",
        "total_events": "per-scenario",
        "zero_time_depth": "per-descendant-chain",
    }
    assert profile["resource_bounds"] == {
        "max_event_steps": 256,
        "max_logical_time": (1 << 63) - 1,
        "max_node_steps": 4096,
        "max_queue_events": 128,
        "max_total_events": 1024,
        "max_zero_time_depth": 32,
    }


def test_rpg_operation_declares_its_complete_gameplay_outcome_algebra():
    authority = _authority_candidate()
    operation = next(
        item
        for item in authority["language_bundle"]["language"]["operations"]
        if item["id"] == "game.combat.cast-v1"
    )

    assert operation["default_outcome"] == "cast-resolved"
    assert operation["outcomes"] == [
        {"id": "cast-resolved", "kind": "success", "state_policy": "commit"},
        {
            "id": "insufficient-resource",
            "kind": "gameplay-alternative",
            "state_policy": "rollback",
        },
        {
            "id": "miss",
            "kind": "gameplay-alternative",
            "state_policy": "rollback",
        },
    ]
    declared = {item["id"] for item in operation["outcomes"]}
    operations = {
        item["id"]: item
        for item in authority["language_bundle"]["language"]["operations"]
    }
    referenced = {
        mapping["action"]["outcome"]
        for invocation in operation["body"]
        for mapping in invocation["outcomes"]
        if mapping["action"]["kind"] == "propagate"
    }
    assert referenced == declared - {operation["default_outcome"]}
    assert {invocation["operation"]["id"] for invocation in operation["body"]} <= set(
        operations
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-evaluation-field",
        "unknown-argument-type",
        "missing-charge",
        "unknown-operation-primitive",
        "semantic-value",
        "wrong-result-effect",
        "wrong-failure",
        "wrong-charge-law",
        "argument-type-law",
    ),
)
def test_two_consumers_refuse_an_incomplete_template_primitive_spec(
    mutation, monkeypatch
):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    primitive_spec = kernel["meta_format"]["template_admission"]["primitive_spec"]
    if mutation == "missing-evaluation-field":
        primitive_spec["primitives"][0]["evaluation"].pop("canonical_encoding")
    elif mutation == "unknown-argument-type":
        primitive_spec["primitives"][0]["argument_types"]["selector"] = "host-object"
    elif mutation == "missing-charge":
        primitive_spec["primitives"][0]["charges"].remove("judgment")
    elif mutation == "unknown-operation-primitive":
        kernel["meta_format"]["template_admission"]["operations"][0]["law"][
            "primitive"
        ] = "host-only"
    elif mutation == "semantic-value":
        primitive_spec["primitives"][0]["evaluation"]["canonical_encoding"] = "host.foo"
    elif mutation == "wrong-result-effect":
        primitive_spec["primitives"][0]["result_effect"] = "preserve-graph"
    elif mutation == "wrong-failure":
        primitive_spec["primitives"][0]["failure"]["short_circuit"] = False
    elif mutation == "wrong-charge-law":
        primitive_spec["primitives"][0]["charges"] = ["judgment"]
    else:
        primitive_spec["argument_types"][4]["empty"] = True
    _reidentify(kernel, authority["language_bundle"])
    kernel_identity = kernel["content_identity"]
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )
    monkeypatch.setattr(
        bootstrap_support, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )

    first = _consumer_a(kernel, authority["language_bundle"])
    second = _consumer_b(kernel, authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert not _consumer_b_template_admission_is_closed(
        kernel["meta_format"], authority["language_bundle"]
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "authority-wire-schema-domain",
        "runtime-profile-definition-domain",
        "json-pointer-schema",
        "wire-schema-identity-domain",
        "ambiguous-wire-schema-identity-domain",
    ),
)
def test_two_consumers_refuse_incomplete_identity_or_pointer_meta_contracts(
    mutation,
    monkeypatch,
):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    if mutation == "authority-wire-schema-domain":
        kernel["meta_format"]["authority_wire_schema_projection"][
            "identity_domains"
        ].pop("language-definition-bundle")
        subject = "kernel.meta-format.authority-wire-schema-projection"
    elif mutation == "runtime-profile-definition-domain":
        kernel["meta_format"]["runtime_profile_definition"]["domain"] = ""
        subject = "language.runtime"
    elif mutation == "json-pointer-schema":
        kernel["meta_format"]["json_pointer"]["schema"] = {
            "type": "missing-json-schema-type"
        }
        subject = "kernel.meta-format.json-pointer"
    elif mutation == "wire-schema-identity-domain":
        ldb["language"]["wire_schemas"][0].pop("wire_schema_identity_domain")
        _refresh_package_closure_and_reidentify(ldb)
        subject = "language.wire-schema-identity-domains"
    else:
        contract_schema_kinds = {
            contract["schema_kind"]
            for contract in ldb["language"]["artifact_contracts"]
        }
        artifact_schema = next(
            schema
            for schema in ldb["language"]["artifact_wire_schemas"]
            if schema["artifact_kind"] in contract_schema_kinds
        )
        artifact_schema["wire_schema_identity_domain"] = "competing-domain"
        _refresh_package_closure_and_reidentify(ldb)
        subject = "language.wire-schema-identity-domains"
    _reidentify(kernel, ldb)
    kernel_identity = kernel["content_identity"]
    monkeypatch.setattr(
        production_bootstrap, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )
    monkeypatch.setattr(
        bootstrap_support, "_SUPPORTED_KERNEL_IDENTITY", kernel_identity
    )

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        subject,
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    ("empty-non-empty-string", "selector-root-list", "binding-source-list"),
)
def test_two_consumers_execute_template_primitive_argument_types(mutation):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    judgments = ldb["language"]["template_admission_profiles"][0]["judgments"]
    if mutation == "empty-non-empty-string":
        judgment = next(
            row for row in judgments if row["id"] == "template.metric-target-interval"
        )
        judgment["arguments"]["minimum_member"] = ""
    elif mutation == "selector-root-list":
        judgment = next(
            row for row in judgments if row["id"] == "template.derive-source-identity"
        )
        judgment["arguments"]["selector"]["root"] = []
    else:
        judgment = next(
            row for row in judgments if row["id"] == "template.admit-source"
        )
        judgment["arguments"]["fact_bindings"][0]["source"] = []
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown-selector-root",
        "unknown-model-fact",
        "duplicate-derived-result",
        "derived-use-before-production",
        "invalid-resource-limit",
    ),
)
def test_two_consumers_refuse_malformed_template_graph_programs(mutation):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    profile = ldb["language"]["template_admission_profiles"][0]
    if mutation == "unknown-selector-root":
        profile["judgments"][0]["arguments"]["selector"]["root"] = "host"
    elif mutation == "unknown-model-fact":
        profile["judgments"][2]["arguments"]["fact_bindings"][0]["source"] = "host"
    elif mutation == "duplicate-derived-result":
        profile["judgments"][1]["arguments"]["result"] = "source_identity"
    elif mutation == "derived-use-before-production":
        profile["judgments"].append(profile["judgments"].pop(0))
    else:
        ldb["resources"]["max_template_admission_steps"] = 0
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    expected = (
        ("ingress", "kernel.member_set_mismatch")
        if mutation == "invalid-resource-limit"
        else ("static", "kernel.vector_mismatch")
    )
    assert any(
        (stage, code) == expected for stage, code, _subject in first["diagnostics"]
    )


def test_template_role_names_are_ldb_owned_without_a_kernel_change():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    documentation = next(
        row
        for row in ldb["language"]["template_admission_profiles"][0]["member_roles"]
        if row["role"] == "documentation"
    )
    documentation["role"] = "genre-extension"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


def test_resolution_profile_symbol_mapping_must_name_the_declared_semantic_fact():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    ldb["language"]["resolution_profiles"][0]["symbol_fact_member"] = "role"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.definitions",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    (
        "unknown-diagnostic",
        "invalid-resource-recipe",
        "missing-diagnostic-pointer",
        "missing-relation",
    ),
)
def test_reidentified_model_program_vector_contract_mutations_are_refused(
    mutation,
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    if mutation == "unknown-diagnostic":
        vector = _owned_vector(
            ldb,
            "model.compile.negative-duplicate",
        )
        vector["expect"]["diagnostics"][0]["code"] = "host.unknown"
    elif mutation == "invalid-resource-recipe":
        vector = _owned_vector(
            ldb,
            "model.compile.boundary-max-symbols-plus-one",
        )
        vector["source_fixture"]["count_offset"] = 2
    elif mutation == "missing-diagnostic-pointer":
        vector = _owned_vector(
            ldb,
            "model.compile.negative-duplicate",
        )
        vector["expect"]["diagnostics"][0].pop("pointer")
    else:
        vector = _owned_vector(
            ldb,
            "model.compile.mutation-role-change",
        )
        vector["expect"]["relation"]["reference"] = "host.missing"

    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_authority_admission_requires_one_default_resolution_profile():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    profile = ldb["language"]["resolution_profiles"][0]
    profile["default"] = False
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if profile["id"] in candidate["profiles"]["resolution"]
    )
    for entry in package["semantic_closure"]:
        if entry["authority_path"] == "language.resolution_profiles":
            entry["definitions"] = deepcopy(ldb["language"]["resolution_profiles"])
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" and subject == "language.definitions"
        for _, code, subject in first["diagnostics"]
    )


def test_model_lowering_invocation_must_match_the_referenced_rule_contract():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    language = ldb["language"]
    language["model_lowerings"][0]["rule_chain"][0]["judgment"] = (
        "host-invented-judgment"
    )
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.packages",
    ) in first["diagnostics"]


def test_reidentified_package_cannot_export_an_open_host_operation_definition():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    language = ldb["language"]
    language["operations"].append({"host_semantics": "invented", "id": "host.op"})
    package = language["packages"][0]
    package["exports"]["operations"].append("host.op")
    operation_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    operation_entry["definitions"].append(deepcopy(language["operations"][-1]))
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_operation_result_source_cannot_invent_host_semantics():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    operation["result"]["source"] = {"kind": "host-callback", "name": "execute"}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.game.combat.game.combat.damage-v1.result.source",
    ) in first["diagnostics"]


def test_reidentified_operation_result_source_requires_its_exact_call_producer():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.cast-v1"
    )
    operation["result"]["source"] = {
        "kind": "operation-result",
        "site": "apply-damage",
    }
    damage_call = next(
        instruction
        for instruction in operation["body"]
        if instruction.get("site") == "apply-damage"
    )
    damage_call["result"] = {"kind": "local", "name": "damage"}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        ("language.operations.game.combat.game.combat.cast-v1.result.source"),
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    "mutation",
    (
        "port-shadow",
        "forward-reference",
        "unused-incompatible-node",
        "unused-non-numeric-node",
    ),
)
def test_operation_body_typing_uses_the_complete_sequential_lexical_scope(mutation):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "game.combat.damage-v1"
    )
    if mutation == "port-shadow":
        operation["body"].insert(
            -1,
            {
                "node": "less-than",
                "target": "base_damage",
                "left": "base_damage",
                "right": "mitigation",
            },
        )
        operation["result"]["source"] = {"kind": "local", "name": "base_damage"}
        operation["resource_bounds"]["max_steps"] += 1
    elif mutation == "forward-reference":
        producer_index = next(
            index
            for index, instruction in enumerate(operation["body"])
            if instruction.get("target") == "damage"
        )
        operation["body"].insert(0, operation["body"].pop(producer_index))
    elif mutation == "unused-incompatible-node":
        operation["body"].insert(
            -1,
            {
                "node": "add",
                "target": "unused_bad",
                "left": "critical",
                "right": "base_damage",
            },
        )
        operation["resource_bounds"]["max_steps"] += 1
    else:
        operation["body"].insert(
            -1,
            {
                "node": "add",
                "target": "unused_bad",
                "left": "critical",
                "right": "critical",
            },
        )
        operation["resource_bounds"]["max_steps"] += 1
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_two_consumers_refuse_a_floor_divide_operation_with_a_non_positive_domain():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation = next(
        row
        for row in ldb["language"]["operations"]
        if row["id"] == "quantity.floor-divide"
    )
    next(row for row in operation["inputs"] if row["id"] == "right")["domain"][
        "minimum"
    ] = 0
    positive_literal = next(
        row
        for row in ldb["language"]["literal_typing_profiles"]
        if row["id"] == "quantity.positive-dimensionless-int64-v2-2"
    )
    positive_literal["minimum"] = 0
    positive_literal["domain"]["minimum"] = 0
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.operations.core.quantity.quantity.floor-divide.body.0.typing",
    ) in first["diagnostics"]


def test_operation_result_source_refuses_a_non_successful_producer_path():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operations = {
        row["id"]: row
        for row in ldb["language"]["operations"]
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    damage = operations["game.combat.damage-v1"]
    damage["outcomes"].append(
        {
            "id": "no-damage",
            "kind": "gameplay-alternative",
            "state_policy": "rollback",
        }
    )
    damage["body"].insert(
        0,
        {
            "node": "precondition-greater-than-or-equal",
            "left": "base_damage",
            "right": "mitigation",
            "outcome": "no-damage",
        },
    )
    damage["resource_bounds"]["max_steps"] += 1
    cast_operation = operations["game.combat.cast-v1"]
    damage_call = next(
        instruction
        for instruction in cast_operation["body"]
        if instruction.get("site") == "apply-damage"
    )
    damage_call["outcomes"].append(
        {"outcome": "no-damage", "action": {"kind": "continue"}}
    )
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        ("language.operations.game.combat.game.combat.cast-v1.result.source"),
    ) in first["diagnostics"]


@pytest.mark.parametrize("replacement", [None, False, 0, [], {}])
def test_reidentified_model_source_schema_version_drift_is_refused(replacement):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    ldb["language"]["wire_schemas"][0]["schema"]["properties"]["schema_version"][
        "const"
    ] = replacement
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_current_slice_refuses_not_yet_delivered_operation_definitions():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["operations"].append(
        {
            "body": {},
            "effects": [],
            "id": "host.op",
            "inputs": {},
            "numeric_profiles": [],
            "refusals": [],
            "resource_bounds": {},
            "result": {},
            "runtime_profiles": [],
            "vectors": [],
        }
    )
    package = authority["language_bundle"]["language"]["packages"][0]
    package["exports"]["operations"].append("host.op")
    package["content_identity"] = _identity("domain-package-release-v2", package)
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_operation_rule_must_match_every_declared_operation_vector():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    operation_id = "quantity.floor-zero"
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if operation_id in candidate["exports"]["operations"]
    )
    operations = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.operations"
    )
    operation = next(
        definition
        for definition in operations["definitions"]
        if definition["id"] == operation_id
    )
    operation["rule"] = "quantity.declare"
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])
