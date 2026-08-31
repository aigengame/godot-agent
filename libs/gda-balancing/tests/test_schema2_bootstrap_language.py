"""Schema 2.0 bootstrap conformance: language ownership."""

# ruff: noqa: F403, F405
import schema2_bootstrap_conformance_support as bootstrap_support
from gda_balancing.domain.formula.inference import infer_formula_operation_result
from gda_balancing.domain.formula.types import formula_contract_matches_operation
from schema2_bootstrap_conformance_support import *
from schema2_bootstrap_production_support import *


@pytest.mark.parametrize(
    ("phase", "expected_prefix"),
    (
        ("invalid-definitions", (1, 0, 0, 0)),
        ("invalid-literal-profiles", (1, 1, 0, 0)),
        ("invalid-composition", (1, 1, 1, 0)),
        ("valid", (1, 1, 1, None)),
    ),
)
def test_bootstrap_consumers_gate_dependent_semantic_phases_in_order(
    monkeypatch,
    phase,
    expected_prefix,
):
    authority = _authority_candidate()
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    language = ldb["language"]
    if phase == "invalid-definitions":
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
    elif phase == "invalid-literal-profiles":
        overlapping = deepcopy(language["literal_typing_profiles"][0])
        overlapping["id"] = "quantity.dimensionless-int64-overlap"
        language["literal_typing_profiles"].append(overlapping)
        owner = next(
            package
            for package in language["packages"]
            if package["id"] == "core.quantity"
        )
        owner["exports"]["literal_typing_profiles"].append(overlapping["id"])
        _refresh_package_closure_and_reidentify(ldb)
    elif phase == "invalid-composition":
        operation = next(
            operation
            for operation in language["operations"]
            if operation["id"] == "game.combat.cast-v1"
        )
        operation["resource_bounds"]["max_steps"] = 1
        _refresh_package_closure_and_reidentify(ldb)

    names = ("definitions", "literal-profiles", "composition", "evidence")
    calls = {
        "production": dict.fromkeys(names, 0),
        "consumer-b": dict.fromkeys(names, 0),
    }
    production_definitions = production_bootstrap._language_definitions_are_closed
    production_literals = production_bootstrap._literal_typing_profiles_are_closed
    production_composition = (
        production_bootstrap._operation_composition_diagnostic_subjects
    )
    production_evidence = production_bootstrap._package_evidence_vectors_are_closed
    consumer_definitions = _consumer_b_language_definitions_are_closed
    consumer_literals = _consumer_b_literal_typing_profiles_are_closed
    consumer_composition = _consumer_b_operation_composition_subjects
    consumer_evidence = _consumer_b_package_evidence_vectors_are_closed

    def count_production_definitions(*args: Any, **kwargs: Any) -> bool:
        calls["production"]["definitions"] += 1
        return production_definitions(*args, **kwargs)

    def count_production_literals(*args: Any, **kwargs: Any) -> bool:
        calls["production"]["literal-profiles"] += 1
        return production_literals(*args, **kwargs)

    def count_production_composition(*args: Any, **kwargs: Any) -> tuple[str, ...]:
        calls["production"]["composition"] += 1
        return production_composition(*args, **kwargs)

    def count_production_evidence(*args: Any, **kwargs: Any) -> bool:
        calls["production"]["evidence"] += 1
        return production_evidence(*args, **kwargs)

    def count_consumer_definitions(*args: Any, **kwargs: Any) -> bool:
        calls["consumer-b"]["definitions"] += 1
        return consumer_definitions(*args, **kwargs)

    def count_consumer_literals(*args: Any, **kwargs: Any) -> bool:
        calls["consumer-b"]["literal-profiles"] += 1
        return consumer_literals(*args, **kwargs)

    def count_consumer_composition(*args: Any, **kwargs: Any) -> tuple[str, ...]:
        calls["consumer-b"]["composition"] += 1
        return consumer_composition(*args, **kwargs)

    def count_consumer_evidence(*args: Any, **kwargs: Any) -> bool:
        calls["consumer-b"]["evidence"] += 1
        return consumer_evidence(*args, **kwargs)

    monkeypatch.setattr(
        production_bootstrap,
        "_language_definitions_are_closed",
        count_production_definitions,
    )
    monkeypatch.setattr(
        production_bootstrap,
        "_literal_typing_profiles_are_closed",
        count_production_literals,
    )
    monkeypatch.setattr(
        production_bootstrap,
        "_operation_composition_diagnostic_subjects",
        count_production_composition,
    )
    monkeypatch.setattr(
        production_bootstrap,
        "_package_evidence_vectors_are_closed",
        count_production_evidence,
    )
    monkeypatch.setattr(
        bootstrap_support,
        "_consumer_b_language_definitions_are_closed",
        count_consumer_definitions,
    )
    monkeypatch.setattr(
        bootstrap_support,
        "_consumer_b_literal_typing_profiles_are_closed",
        count_consumer_literals,
    )
    monkeypatch.setattr(
        bootstrap_support,
        "_consumer_b_operation_composition_subjects",
        count_consumer_composition,
    )
    monkeypatch.setattr(
        bootstrap_support,
        "_consumer_b_package_evidence_vectors_are_closed",
        count_consumer_evidence,
    )

    first = _consumer_a(kernel, ldb)
    second = _consumer_b(kernel, ldb)

    assert first == second
    assert first["admitted"] is (phase == "valid")
    expected = dict(
        zip(
            names,
            (
                expected_prefix[0],
                expected_prefix[1],
                expected_prefix[2],
                len(language["packages"])
                if expected_prefix[3] is None
                else expected_prefix[3],
            ),
            strict=True,
        )
    )
    assert calls == {"production": expected, "consumer-b": expected}


@pytest.mark.parametrize(
    "mutation",
    (
        "projection-output-shape",
        "output-equality-type",
    ),
)
def test_two_consumers_refuse_reidentified_authority_type_mismatches(mutation):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    lowering = ldb["language"]["model_lowerings"][0]
    if mutation == "projection-output-shape":
        collection = next(
            item
            for item in lowering["runtime_projection"]["collections"]
            if item["id"] == "components"
        )
        collection["output_shape"] = "definition"
    else:
        lowering["output_equalities"][0]["right"] = ["domain"]
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


def test_two_consumers_type_empty_semantic_collections_from_kernel_contracts():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    ldb["language"]["conversions"] = []
    for package in ldb["language"]["packages"]:
        package["exports"]["conversions"] = []
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True


def test_two_consumers_refuse_inconsistent_evidence_claim_kind_vectors():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    claim_kind = ldb["language"]["evidence_claim_kinds"][0]
    claim_kind["vectors"][0]["expect"] = "refusal"
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "static",
        "kernel.vector_mismatch",
        "language.evidence-claim-kinds",
    ) in first["diagnostics"]


def test_quantity_package_is_complete_content_addressed_and_uses_canonical_terms():
    ldb = _authority_candidate()["language_bundle"]
    package = ldb["language"]["packages"][0]

    assert set(package) == {
        "artifact_kind",
        "capabilities",
        "conformance_vectors",
        "content_identity",
        "dependencies",
        "exports",
        "id",
        "profiles",
        "runtime_semantic_excluded_extensions",
        "runtime_semantic_paths",
        "semantic_closure",
        "semantic_identity",
        "version",
    }
    assert package["artifact_kind"] == "domain-package-release"
    assert package["content_identity"] == _identity(
        "domain-package-release-v2", package
    )
    expected_package = deepcopy(package)
    _reidentify_package_release(expected_package)
    assert package["semantic_identity"] == expected_package["semantic_identity"]
    assert package["dependencies"] == {
        "optional": [],
        "required": [{"id": "standard.compiler", "version": "1.1.0"}],
    }
    assert package["capabilities"]["required"] == []
    assert package["exports"]["components"] == ["quantity.symbol"]
    assert package["exports"]["conversions"] == ["quantity.identity"]
    assert package["exports"]["operations"] == [
        "quantity.floor-zero",
        "quantity.identity",
        "quantity.less-than",
        "quantity.maximum",
        "quantity.subtract",
    ]
    assert package["profiles"]["runtime"] == []
    assert package["exports"]["types"]
    vector_set = _package_vector_set(ldb, package)
    assert vector_set["vectors"]
    assert [item["id"] for item in vector_set["vector_definitions"]] == vector_set[
        "vectors"
    ]
    assert ldb["language"]["quantity"]["representations"] == ["Int"]
    assert "random" in ldb["language"]["quantity"]["symbol_roles"]
    assert "random-variable" not in ldb["language"]["quantity"]["symbol_roles"]
    duplicate = next(
        item
        for item in ldb["diagnostics"]
        if item["code"] == "language.duplicate_symbol"
    )
    assert duplicate["stage"] == "static"


def test_quantity_2_2_adds_only_the_required_composition_operations():
    ldb = _authority_candidate()["language_bundle"]
    releases = {
        (package["id"], package["version"]): package
        for package in ldb["language"]["packages"]
    }

    quantity_2_1 = releases[("core.quantity", "2.1.0")]
    quantity_2_2 = releases[("core.quantity", "2.2.0")]
    assert quantity_2_1["exports"]["operations"] == [
        "quantity.floor-zero",
        "quantity.identity",
        "quantity.less-than",
        "quantity.maximum",
        "quantity.subtract",
    ]
    assert quantity_2_2["exports"]["operations"] == [
        "quantity.add",
        "quantity.floor-divide",
        "quantity.floor-zero",
        "quantity.identity",
        "quantity.less-than",
        "quantity.maximum",
        "quantity.minimum",
        "quantity.multiply",
        "quantity.subtract",
    ]

    operations = {
        operation["id"]: operation
        for operation in next(
            entry["definitions"]
            for entry in quantity_2_2["semantic_closure"]
            if entry["authority_path"] == "language.operations"
        )
    }
    assert [row["node"] for row in operations["quantity.minimum"]["body"]] == [
        "less-than",
        "if",
    ]
    floor_divide = operations["quantity.floor-divide"]
    assert floor_divide["body"] == [
        {
            "left": "left",
            "node": "floor-divide",
            "right": "right",
            "target": "result",
        }
    ]
    assert floor_divide["inputs"][1]["domain"] == {
        "kind": "closed-interval",
        "minimum": 1,
        "maximum": 2**63 - 1,
    }
    assert floor_divide["refusals"] == []


def test_quantity_2_2_composition_inference_and_positive_divisor_contract():
    ldb = _authority_candidate()["language_bundle"]
    releases = {
        (package["id"], package["version"]): package
        for package in ldb["language"]["packages"]
    }
    quantity = releases[("core.quantity", "2.2.0")]
    operations = {
        operation["id"]: operation
        for operation in next(
            entry["definitions"]
            for entry in quantity["semantic_closure"]
            if entry["authority_path"] == "language.operations"
        )
    }
    compiler = releases[("standard.compiler", "1.1.0")]
    profile = next(
        definition
        for entry in compiler["semantic_closure"]
        if entry["authority_path"] == "language.resolution_profiles"
        for definition in entry["definitions"]
        if definition["id"] == "exact-import-resolution-v1"
    )
    policy = profile["extensions"]["standard.formula"]["notation_conversion"]

    def contract(minimum: int, maximum: int) -> dict[str, Any]:
        return {
            "domain": {"minimum": minimum, "maximum": maximum},
            "domain_kind": "closed-interval",
            "kind": "scalar",
            "numeric_policy": "exact-int64",
            "representation": "Int",
            "type_identity": {
                "package": "core.quantity",
                "symbol": "Quantity",
                "version": "2.2.0",
            },
            "unit": "1",
        }

    floor_divide = operations["quantity.floor-divide"]
    assert formula_contract_matches_operation(contract(2, 3), floor_divide["inputs"][1])
    assert not formula_contract_matches_operation(
        contract(0, 3), floor_divide["inputs"][1]
    )
    assert infer_formula_operation_result(
        floor_divide,
        ["left", "right"],
        [contract(-10, 10), contract(2, 3)],
        contract(-10, 10),
        policy,
        {},
    )["domain"] == {"minimum": -5, "maximum": 5}

    expected_domains = {
        "quantity.add": {"minimum": 2, "maximum": 8},
        "quantity.minimum": {"minimum": -2, "maximum": 5},
        "quantity.multiply": {"minimum": -12, "maximum": 15},
    }
    for operation_id, expected_domain in expected_domains.items():
        operation = operations[operation_id]
        assert (
            infer_formula_operation_result(
                operation,
                ["left", "right"],
                [
                    contract(-2, 3),
                    contract(4, 5)
                    if operation_id != "quantity.multiply"
                    else contract(-4, 5),
                ],
                contract(-2, 3),
                policy,
                {},
            )["domain"]
            == expected_domain
        )


def test_quantity_2_2_has_one_compatible_downstream_release_chain():
    ldb = _authority_candidate()["language_bundle"]
    releases = {
        (package["id"], package["version"]): package
        for package in ldb["language"]["packages"]
    }
    expected_dependencies = {
        ("game.check", "1.1.0"): [
            {"id": "core.quantity", "version": "2.2.0"},
            {"id": "standard.runtime", "version": "1.1.0"},
        ],
        ("game.resource", "1.1.0"): [
            {"id": "core.quantity", "version": "2.2.0"},
            {"id": "standard.runtime", "version": "1.1.0"},
        ],
        ("game.generation", "1.1.0"): [
            {"id": "core.quantity", "version": "2.2.0"},
            {"id": "standard.runtime", "version": "1.1.0"},
            {"id": "standard.schema", "version": "2.4.0"},
        ],
        ("game.combat", "2.2.0"): [
            {"id": "core.quantity", "version": "2.2.0"},
            {"id": "game.check", "version": "1.1.0"},
            {"id": "game.resource", "version": "1.1.0"},
            {"id": "standard.runtime", "version": "1.1.0"},
        ],
    }
    retained_versions = {
        "game.check": "1.0.1",
        "game.resource": "1.0.1",
        "game.generation": "1.0.0",
        "game.combat": "2.1.0",
    }

    assert {
        (package, version) for package, version in retained_versions.items()
    } <= set(releases)
    for coordinate, dependencies in expected_dependencies.items():
        release = releases[coordinate]
        assert release["dependencies"]["required"] == dependencies
        assert (
            release["exports"]
            == releases[(coordinate[0], retained_versions[coordinate[0]])]["exports"]
        )

        vector_set = next(
            item
            for item in ldb.package_conformance_vector_sets
            if (item["package_id"], item["package_version"]) == coordinate
        )
        dependency_vectors = [
            vector
            for vector in vector_set["vector_definitions"]
            if vector.get("kind") == "package-contract"
            and vector.get("probe") == {"path": "dependencies.required"}
        ]
        assert [vector["expect"] for vector in dependency_vectors] == [dependencies]


def test_stat_contribution_releases_own_pure_formula_slots():
    ldb = _authority_candidate()["language_bundle"]
    releases = {
        (package["id"], package["version"]): package
        for package in ldb["language"]["packages"]
    }
    expected = {
        ("game.progression", "1.0.0"): {
            "dependencies": [{"id": "core.quantity", "version": "2.2.0"}],
            "operation": "game.progression.contribution@1",
            "slot": "progression-policy",
            "parameters": ["level", "damage_per_level"],
        },
        ("game.build", "2.0.0"): {
            "dependencies": [
                {"id": "core.quantity", "version": "2.2.0"},
                {"id": "game.generation", "version": "1.1.0"},
                {"id": "standard.runtime", "version": "1.1.0"},
                {"id": "standard.schema", "version": "2.4.0"},
            ],
            "operation": "game.build.contribution@1",
            "slot": "build-policy",
            "parameters": ["weapon_damage_bonus"],
        },
        ("game.effect", "2.0.0"): {
            "dependencies": [
                {"id": "core.quantity", "version": "2.2.0"},
                {"id": "standard.runtime", "version": "1.1.0"},
            ],
            "operation": "game.effect.contribute@1",
            "slot": "effect-policy",
            "parameters": ["pre_buff_damage", "buff_percent", "buff_enabled"],
        },
    }

    for coordinate, contract in expected.items():
        release = releases[coordinate]
        assert release["dependencies"]["required"] == contract["dependencies"]
        assert contract["operation"] in release["exports"]["operations"]
        operations = next(
            entry["definitions"]
            for entry in release["semantic_closure"]
            if entry["authority_path"] == "language.operations"
        )
        operation = next(
            item for item in operations if item["id"] == contract["operation"]
        )
        assert operation["operation_kind"] == "pure-expression"
        assert operation["effects"] == []
        assert operation["result"]["source"] == {"kind": "local", "name": "result"}
        [slot] = operation["extensions"]["standard.formula-slots"]
        assert slot["id"] == contract["slot"]
        assert slot["context"] == {
            "frame": "pre-event-snapshot",
            "phase": "event",
        }
        assert [parameter["id"] for parameter in slot["parameters"]] == contract[
            "parameters"
        ]
        assert [parameter["source"] for parameter in slot["parameters"]] == [
            {"kind": "port", "name": name} for name in contract["parameters"]
        ]
        assert slot["target"] == "result"
        assert slot["placeholder_index"] == 0
        assert slot["placeholder_length"] == len(operation["body"])


@pytest.mark.parametrize(
    ("package_id", "previous_version", "breaking_version"),
    (
        ("game.build", "1.0.0", "2.0.0"),
        ("game.effect", "1.0.0", "2.0.0"),
    ),
)
def test_stat_contribution_breaking_releases_retain_the_previous_major_line(
    package_id,
    previous_version,
    breaking_version,
):
    ldb = _authority_candidate()["language_bundle"]
    releases = {
        (package["id"], package["version"]): package
        for package in ldb["language"]["packages"]
    }
    assert (package_id, previous_version) in releases
    assert (package_id, breaking_version) in releases
    assert (package_id, "1.1.0") not in releases


def test_coherent_package_semantic_change_changes_the_release_identity():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = next(
        item for item in ldb["language"]["packages"] if item["id"] == "core.quantity"
    )
    old_release_identity = package["content_identity"]
    operation = next(
        item
        for item in ldb["language"]["operations"]
        if item["id"] == "quantity.identity"
    )
    operation["resource_bounds"]["max_steps"] = 2
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
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is True
    assert package["content_identity"] != old_release_identity


def test_semantic_closure_cannot_move_a_definition_to_a_non_owner_package():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    quantity_package = ldb["language"]["packages"][0]
    other_package = deepcopy(quantity_package)
    other_package["id"] = "core.other"
    other_package["capabilities"] = {"provided": [], "required": []}
    other_package["dependencies"] = {"optional": [], "required": []}
    other_package["exports"] = {member: [] for member in quantity_package["exports"]}
    other_package["profiles"] = {"numeric": [], "resolution": [], "runtime": []}
    for entry in other_package["semantic_closure"]:
        entry["definitions"] = []

    quantity_components = next(
        entry
        for entry in quantity_package["semantic_closure"]
        if entry["authority_path"] == "language.components"
    )
    other_components = next(
        entry
        for entry in other_package["semantic_closure"]
        if entry["authority_path"] == "language.components"
    )
    other_components["definitions"] = quantity_components["definitions"]
    quantity_components["definitions"] = []

    for package in (quantity_package, other_package):
        _reidentify_package_release(package)
    ldb["language"]["packages"].append(other_package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.identity_mismatch" and subject.endswith(".semantic_identity")
        for _, code, subject in first["diagnostics"]
    )


def test_bootstrap_executes_every_rule_vector_into_a_stable_projection():
    authority = _authority_candidate()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    assert admission.admitted is True
    assert dict(admission.rule_projections).keys() == {
        "quantity.declare.valid",
        "quantity.lower.valid",
        "quantity.v2-2.quantity.declare.valid",
        "quantity.v2-2.quantity.lower.valid",
        "structured.declare.valid",
        "structured.lower.valid",
    }
    assert all(
        identity.startswith("sha256:") for _, identity in admission.rule_projections
    )


def test_bootstrap_behavior_covers_every_ldb_diagnostic_reason():
    authority = _authority_candidate()
    admission = admit_authorities(authority["kernel"], authority["language_bundle"])

    catalog_codes = {
        item["code"] for item in authority["language_bundle"]["diagnostics"]
    }
    projection_codes = {code for _, code, _ in admission.diagnostic_projections}
    assert admission.admitted is True
    assert projection_codes == catalog_codes
    assert all(
        identity.startswith("sha256:")
        for _, _, identity in admission.diagnostic_projections
    )


def test_reidentified_deletion_of_every_law_and_rule_is_refused_by_both_consumers():
    baseline = _authority_candidate()
    kernel_laws = baseline["kernel"]["admission"]["laws"]
    ldb_rules = baseline["language_bundle"]["language"]["rules"]

    for index in range(len(kernel_laws)):
        authority = deepcopy(baseline)
        del authority["kernel"]["admission"]["laws"][index]
        _reidentify(authority["kernel"], authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False
        assert any(
            code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
        )

    for index in range(len(ldb_rules)):
        authority = deepcopy(baseline)
        del authority["language_bundle"]["language"]["rules"][index]
        _refresh_package_closure_and_reidentify(authority["language_bundle"])
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False
        assert any(
            code == "kernel.identity_mismatch" for _, code, _ in first["diagnostics"]
        ), first["diagnostics"]


def test_reidentified_duplicate_diagnostic_is_not_hidden_by_set_projection():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    diagnostic = deepcopy(ldb["diagnostics"][0])
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if diagnostic["code"] in candidate["exports"]["diagnostics"]
    )
    package["exports"]["diagnostics"].append(diagnostic["code"])
    diagnostic_entry = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    diagnostic_entry["definitions"].append(diagnostic)
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "ingress",
        "kernel.member_set_mismatch",
        "language-bundle.language.packages.0",
    ) in first["diagnostics"]


def test_reidentified_open_fact_shape_is_refused_by_both_consumers():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    vector_id = next(
        item["id"]
        for item in ldb["vectors"]
        if isinstance(item.get("input"), dict) and "facts" in item["input"]
    )
    vector = _owned_vector(ldb, vector_id)
    vector["input"]["facts"][0]["host_semantics"] = "invented"
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if vector["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_open_reason_shape_is_refused_by_both_consumers():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["reasons"][0]["host_predicate"] = (
        "invented"
    )
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
    ), first["diagnostics"]


def test_reidentified_rule_phase_mutation_is_refused_by_both_consumers():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["rules"][0]["phase"] = "host"
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_capability_definition_cannot_omit_its_rule_reference():
    authority = _authority_candidate()
    del authority["language_bundle"]["language"]["capabilities"][0]["rule"]
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_malformed_quantity_inventory_returns_a_typed_refusal_from_both_consumers():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["quantity"] = []
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert first["diagnostics"]


def test_reidentified_fact_enum_drift_is_refused_by_both_consumers():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    vector_id = next(
        item["id"]
        for item in ldb["vectors"]
        if isinstance(item.get("input"), dict) and "facts" in item["input"]
    )
    vector = _owned_vector(ldb, vector_id)
    input_fact = vector["input"]["facts"][0]
    expected_fact = vector["expect"]
    input_fact["fields"]["role"] = "host-role"
    expected_fact["fields"]["role"] = "host-role"
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if vector["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_operand_type_drift_is_refused_by_both_consumers():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["reasons"][1]["predicate"][
        "member_field"
    ] = 42
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_cannot_change_its_inventory_semantics():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["reasons"][0]["predicate"][
        "inventory_path"
    ] = "language.quantity.symbol_roles"
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_cannot_change_its_limit_semantics():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["reasons"][3]["predicate"][
        "limit_path"
    ] = "resources.max_diagnostics"
    _refresh_package_closure_and_reidentify(authority["language_bundle"])

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


def test_reidentified_reason_vector_with_non_boolean_outcome_is_a_total_refusal():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    reason_vector_id = next(item["id"] for item in ldb["vectors"] if "reason" in item)
    reason_vector = _owned_vector(ldb, reason_vector_id)
    reason_vector["matched"] = {"host": True}
    vector_set = next(
        candidate
        for candidate in ldb.package_conformance_vector_sets
        if reason_vector["id"] in candidate["vectors"]
    )
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if candidate["id"] == vector_set["package_id"]
        and candidate["version"] == vector_set["package_version"]
    )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


@pytest.mark.parametrize(
    ("member", "replacement"),
    [("reason", []), ("diagnostic", {}), ("stage", ["static"])],
)
def test_reidentified_reason_vector_header_type_drift_is_a_total_refusal(
    member, replacement
):
    authority = _authority_candidate()
    reason_vector = next(
        item for item in authority["language_bundle"]["vectors"] if "reason" in item
    )
    reason_vector[member] = replacement
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize(
    ("member", "replacement"),
    [("rule", []), ("rule", {}), ("id", None), ("id", False), ("id", 42)],
)
def test_reidentified_rule_vector_header_type_drift_is_a_total_refusal(
    member, replacement
):
    authority = _authority_candidate()
    rule_vector = next(
        item for item in authority["language_bundle"]["vectors"] if "rule" in item
    )
    rule_vector[member] = replacement
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "rule-id-none",
        "premises-none",
        "bind-list",
        "conclusion-none",
        "conclusion-fields-false",
        "reason-id-none",
        "conclusion-fact-kind-list",
        "premise-fact-kind-list",
        "premise-fact-kind-object",
        "conclusion-term-tag-list",
        "conclusion-term-tag-object",
    ],
)
def test_reidentified_rule_and_reason_shape_drift_is_a_total_refusal(mutation):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    rule = ldb["language"]["rules"][0]
    if mutation == "rule-id-none":
        rule["id"] = None
    elif mutation == "premises-none":
        rule["premises"] = None
    elif mutation == "bind-list":
        rule["premises"][0]["bind"] = []
    elif mutation == "conclusion-none":
        rule["conclusion"] = None
    elif mutation == "conclusion-fields-false":
        rule["conclusion"]["fields"] = False
    elif mutation == "reason-id-none":
        ldb["language"]["reasons"][0]["id"] = None
    elif mutation == "conclusion-fact-kind-list":
        rule["conclusion"]["fact_kind"] = []
    elif mutation == "premise-fact-kind-list":
        rule["premises"][0]["fact_kind"] = []
    elif mutation == "premise-fact-kind-object":
        rule["premises"][0]["fact_kind"] = {}
    elif mutation == "conclusion-term-tag-list":
        next(iter(rule["conclusion"]["fields"].values()))["tag"] = []
    else:
        next(iter(rule["conclusion"]["fields"].values()))["tag"] = {}
    _refresh_package_closure_and_reidentify(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


@pytest.mark.parametrize("replacement", [None, False, 0, "language", []])
def test_reidentified_non_object_language_is_a_total_refusal(replacement):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    ldb["language"] = replacement

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_token_drift_is_refused_by_both_consumers():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    package["exports"]["symbol_roles"][-1] = "host-random"
    symbol_roles = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.quantity.symbol_roles"
    )
    symbol_roles["definitions"][-1] = "host-random"
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(
        code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
    ), first["diagnostics"]


@pytest.mark.parametrize(
    ("reason_index", "member", "replacement"),
    [
        (0, "inventory_path", "artifact_kind"),
        (1, "member_field", "host"),
        (3, "limit_path", "artifact_kind"),
    ],
)
def test_reidentified_reason_path_shape_drift_is_a_total_refusal(
    reason_index, member, replacement
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    reason_id = ldb["language"]["reasons"][reason_index]["id"]
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if reason_id in candidate["exports"]["reasons"]
    )
    reasons = next(
        entry
        for entry in package["semantic_closure"]
        if entry["authority_path"] == "language.reasons"
    )
    reason = next(
        definition
        for definition in reasons["definitions"]
        if definition["id"] == reason_id
    )
    reason["predicate"][member] = replacement
    _reidentify_package_release(package)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"])


@pytest.mark.parametrize("collection", ["constructors", "wire_schemas"])
def test_reidentified_language_definition_envelopes_are_closed(collection):
    authority = _authority_candidate()
    authority["language_bundle"]["language"][collection][0]["host_semantics"] = (
        "invented"
    )
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_carry_an_unknown_host_keyword():
    authority = _authority_candidate()
    wire_schema = authority["language_bundle"]["language"]["wire_schemas"][0]
    wire_schema["schema"]["host_semantics"] = "invented"
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_must_be_valid_under_its_declared_dialect():
    authority = _authority_candidate()
    symbol_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]
    symbol_schema["type"] = 42
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_bypass_object_closure_with_type_array():
    authority = _authority_candidate()
    domain_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]["properties"][
        "domain"
    ]
    domain_schema["type"] = ["object"]
    del domain_schema["unevaluatedProperties"]
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_object_keywords_require_explicit_closed_type():
    authority = _authority_candidate()
    domain_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]["properties"][
        "domain"
    ]
    del domain_schema["type"]
    del domain_schema["unevaluatedProperties"]
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_add_an_open_combinator_branch():
    authority = _authority_candidate()
    domain_schema = authority["language_bundle"]["language"]["wire_schemas"][0][
        "schema"
    ]["properties"]["modules"]["items"]["properties"]["symbols"]["items"]["properties"][
        "domain"
    ]
    replacement = {"anyOf": [deepcopy(domain_schema), {}]}
    authority["language_bundle"]["language"]["wire_schemas"][0]["schema"]["properties"][
        "modules"
    ]["items"]["properties"]["symbols"]["items"]["properties"]["domain"] = replacement
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_reference_a_missing_local_definition():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["wire_schemas"][0]["schema"]["$ref"] = (
        "#/$defs/missing"
    )
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_wire_schema_cannot_collide_with_reserved_projection_kind():
    authority = _authority_candidate()
    authority["language_bundle"]["language"]["wire_schemas"][0]["artifact_kind"] = (
        "schema-major-kernel"
    )
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_reidentified_duplicate_reason_uses_type_sensitive_scalar_equality():
    authority = _authority_candidate()
    duplicate_vector = next(
        item
        for item in authority["language_bundle"]["vectors"]
        if item["id"] == "quantity.refuse.duplicate"
    )
    duplicate_vector["input"]["values"] = [False, 0]
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_diagnostic_catalog_missing_extra_and_stage_drift_are_refused():
    mutations = []

    missing = _authority_candidate()
    missing_ldb = missing["language_bundle"]
    missing_code = missing_ldb["diagnostics"][-1]["code"]
    missing_package = next(
        package
        for package in missing_ldb["language"]["packages"]
        if missing_code in package["exports"]["diagnostics"]
    )
    missing_definitions = next(
        entry["definitions"]
        for entry in missing_package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    missing_package["exports"]["diagnostics"].remove(missing_code)
    missing_definitions[:] = [
        definition
        for definition in missing_definitions
        if definition["code"] != missing_code
    ]
    _reidentify_package_release(missing_package)
    _reidentify_graph_root(missing_ldb)
    mutations.append(missing)

    extra = _authority_candidate()
    extra_ldb = extra["language_bundle"]
    extra_package = extra_ldb["language"]["packages"][0]
    extra_package["exports"]["diagnostics"].append("language.unreachable")
    extra_definitions = next(
        entry["definitions"]
        for entry in extra_package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    extra_definitions.append({"code": "language.unreachable", "stage": "static"})
    _reidentify_package_release(extra_package)
    _reidentify_graph_root(extra_ldb)
    mutations.append(extra)

    drift = _authority_candidate()
    drift_ldb = drift["language_bundle"]
    drift_code = drift_ldb["diagnostics"][0]["code"]
    drift_package = next(
        package
        for package in drift_ldb["language"]["packages"]
        if drift_code in package["exports"]["diagnostics"]
    )
    drift_definitions = next(
        entry["definitions"]
        for entry in drift_package["semantic_closure"]
        if entry["authority_path"] == "diagnostics"
    )
    next(
        definition
        for definition in drift_definitions
        if definition["code"] == drift_code
    )["stage"] = "resolution"
    _reidentify_package_release(drift_package)
    _reidentify_graph_root(drift_ldb)
    mutations.append(drift)

    for authority in mutations:
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert (
            "static",
            "kernel.diagnostic_closure",
            "language-bundle.diagnostics",
        ) in first["diagnostics"]


def test_reidentified_deletion_and_behavior_mutation_of_every_reason_refuse():
    baseline = _authority_candidate()
    reasons = baseline["language_bundle"]["language"]["reasons"]

    for index in range(len(reasons)):
        for mutation in ("delete", "operation"):
            authority = deepcopy(baseline)
            ldb = authority["language_bundle"]
            reason_id = reasons[index]["id"]
            owners = [
                candidate
                for candidate in ldb["language"]["packages"]
                if reason_id in candidate["exports"]["reasons"]
            ]
            if mutation == "delete":
                for package in owners:
                    target = next(
                        entry["definitions"]
                        for entry in package["semantic_closure"]
                        if entry["authority_path"] == "language.reasons"
                    )
                    package["exports"]["reasons"].remove(reason_id)
                    target.remove(
                        next(
                            definition
                            for definition in target
                            if definition["id"] == reason_id
                        )
                    )
                    _reidentify_package_release(package)
            else:
                package = owners[0]
                target = next(
                    entry["definitions"]
                    for entry in package["semantic_closure"]
                    if entry["authority_path"] == "language.reasons"
                )
                reason = next(
                    definition for definition in target if definition["id"] == reason_id
                )
                reason["predicate"]["operation"] += ".changed"
                _reidentify_package_release(package)
            _reidentify_graph_root(ldb)
            first = _consumer_a(authority["kernel"], ldb)
            second = _consumer_b(authority["kernel"], ldb)
            assert first == second
            assert first["admitted"] is False
            assert any(
                code == "kernel.vector_mismatch" for _, code, _ in first["diagnostics"]
            ), first["diagnostics"]


def test_reidentified_extra_members_cannot_extend_kernel_ldb_or_rule_shapes():
    baseline = _authority_candidate()
    mutations = []

    kernel_extra = deepcopy(baseline)
    kernel_extra["kernel"]["host_extension"] = True
    _reidentify(kernel_extra["kernel"], kernel_extra["language_bundle"])
    mutations.append(kernel_extra)

    ldb_extra = deepcopy(baseline)
    ldb_extra["language_bundle"]["host_extension"] = True
    ldb_extra["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", ldb_extra["language_bundle"]
    )
    mutations.append(ldb_extra)

    rule_extra = deepcopy(baseline)
    rule_extra["language_bundle"]["language"]["rules"][0]["host_hook"] = "run"
    rule_extra["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", rule_extra["language_bundle"]
    )
    mutations.append(rule_extra)

    for authority in mutations:
        first = _consumer_a(authority["kernel"], authority["language_bundle"])
        second = _consumer_b(authority["kernel"], authority["language_bundle"])
        assert first == second
        assert first["admitted"] is False
