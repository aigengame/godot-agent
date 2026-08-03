"""Schema 2.0 bootstrap conformance: resources ownership."""

# ruff: noqa: F403, F405
import schema2_bootstrap_conformance_support as bootstrap_support
from schema2_bootstrap_conformance_support import *
from schema2_bootstrap_production_support import *


def test_reidentified_numeric_policy_cannot_invent_overflow_semantics():
    authority = _authority_candidate()
    policy = authority["language_bundle"]["language"]["quantity"]["numeric_policies"][0]
    policy["overflow"] = "wrap"
    authority["language_bundle"]["content_identity"] = _identity(
        "language-definition-bundle-v2", authority["language_bundle"]
    )

    first = _consumer_a(authority["kernel"], authority["language_bundle"])
    second = _consumer_b(authority["kernel"], authority["language_bundle"])

    assert first == second
    assert first["admitted"] is False


def test_two_consumers_agree_on_report_all_cap_and_truncation():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = next(
        candidate
        for candidate in ldb["language"]["packages"]
        if "quantity.declare" in candidate["exports"]["language_rules"]
    )
    diagnostic_cap = authority["kernel"]["resources"]["max_diagnostics"]
    vector_set = _package_vector_set(ldb, package)
    for index in range(diagnostic_cap + 2):
        vector_id = f"mutant.{index}"
        vector_set["vectors"].append(vector_id)
        vector_set["vector_definitions"].append(
            {
                "expect": {},
                "id": vector_id,
                "input": {"facts": [], "judgment": "missing"},
                "rule": "quantity.declare",
            }
        )
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["truncated"] is True
    assert len(first["diagnostics"]) == diagnostic_cap


def test_two_consumers_refuse_the_same_nesting_resource_exhaustion():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    package = ldb["language"]["packages"][0]
    nested: object = "leaf"
    for _ in range(authority["kernel"]["resources"]["max_nesting_depth"] + 1):
        nested = [nested]
    vector_set = _package_vector_set(ldb, package)
    vector_set["vector_definitions"][0]["unused_host_payload"] = nested
    _bind_package_vector_set(package, vector_set)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["diagnostics"] == [
        ("ingress", "kernel.resource_exhausted", "language-bundle.package-vectors.0")
    ]


def test_two_consumers_refuse_the_same_noncanonical_integer():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    ldb.root["resources"]["max_source_bytes"] = 2**63

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert {code for _, code, _ in first["diagnostics"]} == {
        "kernel.identity_mismatch",
        "kernel.resource_exhausted",
    }


def test_two_consumers_refuse_a_closed_dependency_cycle():
    authority = _authority_candidate()
    ldb = authority["language_bundle"]
    check = next(
        package
        for package in ldb["language"]["packages"]
        if package["id"] == "game.check"
    )
    check["dependencies"]["required"].append({"id": "game.combat", "version": "2.1.0"})
    _reidentify_package_release(check)
    _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert (
        "ingress",
        "kernel.binding_mismatch",
        "language-bundle.package-dependencies",
    ) in first["diagnostics"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing", "kernel.member_set_mismatch"),
        ("extra", "kernel.member_set_mismatch"),
        ("duplicate", "kernel.duplicate_identifier"),
        ("substituted", "kernel.binding_mismatch"),
        ("digest-mismatch", "kernel.binding_mismatch"),
        ("size-mismatch", "kernel.binding_mismatch"),
        ("coordinate-mismatch", "kernel.binding_mismatch"),
        ("unresolved-dependency", "kernel.binding_mismatch"),
        ("wrong-dependency-version", "kernel.binding_mismatch"),
        ("same-coordinate-different-content", "kernel.duplicate_identifier"),
    ),
)
def test_two_consumers_refuse_adversarial_graph_membership_and_binding(
    mutation, expected_code
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]

    if mutation == "missing":
        ldb.package_releases.pop()
        ldb.package_conformance_vector_sets.pop()
        ldb.package_byte_sizes = ldb.package_byte_sizes[:-1]
        ldb.vector_set_byte_sizes = ldb.vector_set_byte_sizes[:-1]
    elif mutation == "extra":
        ldb.package_releases.append(deepcopy(ldb.package_releases[-1]))
        ldb.package_conformance_vector_sets.append(
            deepcopy(ldb.package_conformance_vector_sets[-1])
        )
        ldb.package_byte_sizes += (ldb.package_byte_sizes[-1],)
        ldb.vector_set_byte_sizes += (ldb.vector_set_byte_sizes[-1],)
    elif mutation in {"duplicate", "same-coordinate-different-content"}:
        duplicate = deepcopy(ldb.package_releases[-1])
        if mutation == "same-coordinate-different-content":
            duplicate["dependencies"]["optional"].append(
                {"id": "game.check", "version": "1.0.1"}
            )
            _reidentify_package_release(duplicate)
        ldb["language"]["packages"].append(duplicate)
        _reidentify_graph_root(ldb)
    elif mutation == "substituted":
        ldb.package_releases[0] = deepcopy(ldb.package_releases[-1])
    elif mutation == "digest-mismatch":
        ldb.root["package_descriptors"][0]["content_identity"] = "sha256:" + "0" * 64
    elif mutation == "size-mismatch":
        ldb.package_byte_sizes = (ldb.package_byte_sizes[0] + 1,) + tuple(
            ldb.package_byte_sizes[1:]
        )
    elif mutation == "coordinate-mismatch":
        ldb.root["package_descriptors"][0]["id"] = "core.substituted"
    else:
        package = ldb["language"]["packages"][0]
        if mutation == "wrong-dependency-version":
            package["dependencies"]["required"][0]["version"] = "9.0.0"
        else:
            package["dependencies"]["required"].append(
                {"id": "host.missing", "version": "1.0.0"}
            )
        _reidentify_package_release(package)
        _reidentify_graph_root(ldb)

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == expected_code for _, code, _ in first["diagnostics"])


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing", "kernel.member_set_mismatch"),
        ("extra", "kernel.member_set_mismatch"),
        ("substituted", "kernel.binding_mismatch"),
        ("digest-mismatch", "kernel.binding_mismatch"),
        ("size-mismatch", "kernel.binding_mismatch"),
        ("coordinate-mismatch", "kernel.binding_mismatch"),
        ("malformed", "kernel.identity_mismatch"),
    ),
)
def test_two_consumers_refuse_adversarial_package_vector_children(
    mutation, expected_code
):
    authority = _authority_candidate()
    ldb = authority["language_bundle"]

    if mutation == "missing":
        ldb.package_conformance_vector_sets.pop()
        ldb.vector_set_byte_sizes = ldb.vector_set_byte_sizes[:-1]
    elif mutation == "extra":
        ldb.package_conformance_vector_sets.append(
            deepcopy(ldb.package_conformance_vector_sets[-1])
        )
        ldb.vector_set_byte_sizes += (ldb.vector_set_byte_sizes[-1],)
    elif mutation == "substituted":
        ldb.package_conformance_vector_sets[0] = deepcopy(
            ldb.package_conformance_vector_sets[-1]
        )
    elif mutation == "digest-mismatch":
        ldb.package_conformance_vector_sets[0]["content_identity"] = (
            "sha256:" + "0" * 64
        )
    elif mutation == "size-mismatch":
        ldb.vector_set_byte_sizes = (ldb.vector_set_byte_sizes[0] + 1,) + tuple(
            ldb.vector_set_byte_sizes[1:]
        )
    elif mutation == "coordinate-mismatch":
        ldb.package_conformance_vector_sets[0]["package_id"] = "core.substituted"
    else:
        ldb.package_conformance_vector_sets[0].pop("vectors")

    first = _consumer_a(authority["kernel"], ldb)
    second = _consumer_b(authority["kernel"], ldb)

    assert first == second
    assert first["admitted"] is False
    assert any(code == expected_code for _, code, _ in first["diagnostics"])


@pytest.mark.parametrize(
    "limit_name",
    (
        "max_ldb_root_bytes",
        "max_ldb_child_bytes",
        "max_ldb_package_bytes",
        "max_ldb_total_bytes",
        "max_ldb_package_count",
        "max_ldb_package_member_count",
        "max_ldb_dependency_depth",
        "max_ldb_dependency_steps",
        "max_ldb_admission_work",
    ),
)
def test_two_consumers_agree_at_and_above_each_graph_resource_boundary(
    monkeypatch, limit_name
):
    baseline = _authority_candidate()
    observed = _graph_metrics(baseline["language_bundle"])[limit_name]

    for limit, admitted in ((observed, True), (observed - 1, False)):
        authority = deepcopy(baseline)
        authority["kernel"]["resources"][limit_name] = limit
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
        assert first["admitted"] is admitted
        if not admitted:
            assert (
                "ingress",
                "kernel.resource_exhausted",
                "language-bundle",
            ) in first["diagnostics"]


@pytest.mark.parametrize(
    ("limit_name", "shape_index"),
    (("max_nesting_depth", 0), ("max_members", 1)),
)
def test_two_consumers_agree_at_and_above_each_authority_shape_boundary(
    monkeypatch, limit_name, shape_index
):
    baseline = _authority_candidate()
    ldb = baseline["language_bundle"]
    artifacts = [
        baseline["kernel"],
        ldb.root,
        *ldb.package_releases,
        *ldb.package_conformance_vector_sets,
    ]
    observed = max(_shape(artifact)[shape_index] for artifact in artifacts)

    for limit, admitted in ((observed, True), (observed - 1, False)):
        authority = deepcopy(baseline)
        authority["kernel"]["resources"][limit_name] = limit
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
        assert first["admitted"] is admitted
        if not admitted:
            assert any(
                code == "kernel.resource_exhausted"
                for _stage, code, _subject in first["diagnostics"]
            )
