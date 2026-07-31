"""Public bootstrap surface for the permanent Standard Schema 2.0 authority.

These tests deliberately enter through dispatch: the first permanent language
authority is useful only if a consumer can retrieve and identify it without
importing implementation-private registries.
"""

import json
import os
import runpy
import subprocess
import sys
import zipfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from shutil import copytree
from typing import Any, cast, get_args

import jsonschema
import pytest

import gda_balancing.schema2.authority as authority_module
import gda_balancing.schema2.bootstrap as bootstrap_module
import gda_balancing.commands.schema as schema_command_module
from gda_balancing.commands.manifest import MANIFEST
from gda_balancing.commands.experiment import EXPERIMENT_CHECK, EXPERIMENT_RUN
from gda_balancing.commands.model import (
    MODEL_BUILD,
    MODEL_CHECK,
    MODEL_INSPECT,
    MODEL_MIGRATE,
)
from gda_balancing.commands.package import (
    package_get_success_schema,
    package_list_success_schema,
    package_vector_set_success_schema,
)
from gda_balancing.commands.schema import (
    SCHEMA_GET,
    schema_get_handler,
    schema_get_success_schema,
)
from gda_balancing.commands.template import (
    TEMPLATE_GET,
    TEMPLATE_INSTANTIATE,
    TEMPLATE_LIST,
)
from gda_balancing.schema2.authority_graph import (
    LanguageBundleGraph,
    derive_language_index,
)
from gda_balancing.schema2.bootstrap import BOOTSTRAP_REFUSAL_CATALOG
from gda_balancing.schema2.canonical import canonical_bytes, content_identity
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    RefusalStage,
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.schema2.surface import schema2_error_envelope_schema


def _reidentify_graph(kernel, ldb):
    root = deepcopy(ldb.root)
    releases = deepcopy(ldb.package_releases)
    vector_sets = deepcopy(ldb.package_conformance_vector_sets)
    descriptors = []
    package_sizes = []
    vector_set_sizes = []
    for release, vector_set in zip(releases, vector_sets, strict=True):
        vector_body = {
            key: value for key, value in vector_set.items() if key != "content_identity"
        }
        vector_set["content_identity"] = content_identity(
            "package-conformance-vector-set-v2", vector_body
        )
        vector_size = len(canonical_bytes(vector_set))
        vector_set_sizes.append(vector_size)
        release["conformance_vectors"] = {
            "artifact_kind": vector_set["artifact_kind"],
            "byte_size": vector_size,
            "content_identity": vector_set["content_identity"],
        }
        body = {
            key: value for key, value in release.items() if key != "content_identity"
        }
        release["content_identity"] = content_identity(
            "domain-package-release-v2", body
        )
        byte_size = len(canonical_bytes(release))
        package_sizes.append(byte_size)
        descriptors.append(
            {
                "artifact_kind": release["artifact_kind"],
                "byte_size": byte_size,
                "content_identity": release["content_identity"],
                "id": release["id"],
                "version": release["version"],
            }
        )
    root["package_descriptors"] = descriptors
    root_body = {key: value for key, value in root.items() if key != "content_identity"}
    root["content_identity"] = content_identity(
        "language-definition-bundle-v2", root_body
    )
    root_byte_size = len(canonical_bytes(root))
    return derive_language_index(
        root,
        releases,
        vector_sets,
        kernel["admission"]["required_language_members"],
        root_byte_size=root_byte_size,
        package_byte_sizes=package_sizes,
        vector_set_byte_sizes=vector_set_sizes,
        descriptor_order=kernel["meta_format"]["language_bundle"]["package_descriptor"][
            "canonical_order"
        ],
    )


def test_loader_admits_raw_graph_before_returning_derived_index(monkeypatch):
    events: list[str] = []
    production_admit = authority_module.admit_authorities
    production_derive = authority_module.derive_language_index

    def observed_admit(kernel, graph):
        events.append("admit:start")
        assert "language" not in graph
        result = production_admit(kernel, graph)
        events.append("admit:complete")
        assert result.admitted
        return result

    def observed_derive(*args, **kwargs):
        events.append("derive")
        return production_derive(*args, **kwargs)

    monkeypatch.setattr(authority_module, "admit_authorities", observed_admit)
    monkeypatch.setattr(authority_module, "derive_language_index", observed_derive)

    _kernel, language_bundle = authority_module.load_authorities()

    assert "language" in language_bundle
    assert events == ["admit:start", "admit:complete", "derive"]


def test_invalid_raw_graph_never_constructs_a_derived_index(monkeypatch):
    kernel, admitted = authority_module.load_authorities()
    releases = deepcopy(admitted.package_releases)
    releases[0]["content_identity"] = "sha256:" + "0" * 64
    candidate = LanguageBundleGraph(
        root=admitted.root,
        package_releases=releases,
        package_conformance_vector_sets=admitted.package_conformance_vector_sets,
        root_byte_size=admitted.root_byte_size,
        package_byte_sizes=list(admitted.package_byte_sizes),
        vector_set_byte_sizes=list(admitted.vector_set_byte_sizes),
    )

    def fail_if_derived(*_args, **_kwargs):
        raise AssertionError("invalid graph reached derived-index construction")

    monkeypatch.setattr(bootstrap_module, "derive_language_index", fail_if_derived)

    admission = bootstrap_module.admit_authorities(kernel, candidate)

    assert admission.admitted is False
    assert {item.code for item in admission.diagnostics} == {"kernel.binding_mismatch"}
    assert "language" not in candidate


def test_packaged_authority_loader_refuses_duplicate_object_keys(monkeypatch, run_cli):
    class DuplicateKeyResource:
        def joinpath(self, _name):
            return self

        def read_text(self, *, encoding):
            assert encoding == "utf-8"
            return '{"schema_major":999,"schema_major":2}'

        def read_bytes(self):
            return b'{"schema_major":999,"schema_major":2}'

    monkeypatch.setattr(
        authority_module, "files", lambda _package: DuplicateKeyResource()
    )

    with pytest.raises(authority_module.AuthorityLoadError) as caught:
        authority_module.load_authorities()
    assert caught.value.code == "kernel.member_set_mismatch"
    assert caught.value.stage == "ingress"

    injected = replace(
        SCHEMA_GET,
        handler=schema_get_handler(authority_module.load_authorities),
    )
    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "language-bundle"],
        registry=(injected,),
    )
    assert (exit_code, stderr) == (2, "")
    assert json.loads(stdout)["error"]["stage"] == "ingress"


@pytest.mark.parametrize("transport", ("whitespace", "key-order"))
def test_packaged_authority_loader_refuses_noncanonical_transport_bytes(
    monkeypatch, transport
):
    logical_members = _authority_resource_bytes()
    target = "packages/game-combat/game.combat@1.0.0.conformance-vectors.json"
    decoded = json.loads(logical_members[target])
    if transport == "whitespace":
        logical_members[target] = json.dumps(
            decoded, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
    else:
        logical_members[target] = (
            json.dumps(
                dict(reversed(list(decoded.items()))),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    class MutatedResource:
        def __init__(self, logical_name=""):
            self.logical_name = logical_name

        def joinpath(self, *parts):
            name = "/".join((*self.logical_name.split("/"), *parts)).lstrip("/")
            return MutatedResource(name)

        def read_bytes(self):
            return logical_members[self.logical_name]

    monkeypatch.setattr(authority_module, "files", lambda _package: MutatedResource())

    with pytest.raises(authority_module.AuthorityLoadError) as caught:
        authority_module.load_authorities()

    assert caught.value.code == "kernel.member_set_mismatch"
    assert caught.value.subject.endswith(".conformance_vectors")
    assert "canonical JSON bytes" in caught.value.message


def test_rebuild_tool_projects_kernel_package_coordinate_patterns(tmp_path):
    tool = runpy.run_path(
        str(Path(__file__).parents[1] / "tools" / "rebuild_schema2_ldb.py")
    )
    source = Path(authority_module.__file__).parent / "authorities"
    candidate = tmp_path / "authorities"
    copytree(source, candidate)
    root_path = candidate / "language-bundle.json"
    root = json.loads(root_path.read_text())
    root["package_descriptors"][0]["id"] = "core/quantity"
    root_path.write_text(json.dumps(root), encoding="utf-8")

    with pytest.raises(ValueError, match="Kernel-valid package coordinate"):
        tool["_build"](candidate)


def test_rebuild_tool_reproduces_every_committed_authority_byte():
    tool = runpy.run_path(
        str(Path(__file__).parents[1] / "tools" / "rebuild_schema2_ldb.py")
    )
    source = Path(authority_module.__file__).parent / "authorities"
    root_bytes, package_bytes = tool["_build"](source)
    expected = {
        source / "language-bundle.json": root_bytes,
        **package_bytes,
    }

    assert expected
    assert all(path.read_bytes() == data for path, data in expected.items())


def test_public_package_vector_schema_uses_exact_rng_and_pointer_encodings():
    kernel, language_bundle = authority_module.load_authorities()
    schema = package_vector_set_success_schema()
    pointer_schema = kernel["meta_format"]["json_pointer"]["schema"]
    projected_pointer_schemas = []

    def visit(value):
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict) and "pointer" in properties:
                projected_pointer_schemas.append(properties["pointer"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    assert projected_pointer_schemas
    assert all(item == pointer_schema for item in projected_pointer_schemas)
    vector_sets = language_bundle.package_conformance_vector_sets
    combat = deepcopy(
        next(row for row in vector_sets if row["package_id"] == "game.combat")
    )
    jsonschema.validate(combat, schema)
    runtime_vector = next(
        row
        for row in combat["vector_definitions"]
        if row["id"] == "game.combat.cast.positive"
    )
    runtime_vector["expect"]["rng_draws"][0]["candidate_hex"] = "f"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(combat, schema)

    quantity = deepcopy(
        next(row for row in vector_sets if row["package_id"] == "core.quantity")
    )
    model_vector = next(
        row
        for row in quantity["vector_definitions"]
        if row["id"] == "model.compile.negative-duplicate"
    )
    model_vector["expect"]["diagnostics"][0]["pointer"] = "/bad~2escape"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(quantity, schema)


@pytest.mark.parametrize(
    "data",
    [
        b"{" + b" " * 262144 + b"}",
        b"[" * 33 + b"0" + b"]" * 33,
    ],
)
def test_authority_raw_resource_bounds_precede_json_decode(monkeypatch, data):
    class BoundedResource:
        def joinpath(self, _name):
            return self

        def read_bytes(self):
            return data

    monkeypatch.setattr(authority_module, "files", lambda _package: BoundedResource())

    with pytest.raises(authority_module.AuthorityLoadError) as caught:
        authority_module.load_authorities()
    assert caught.value.code == "kernel.resource_exhausted"


def test_authority_decode_failure_is_a_typed_ingress_refusal(run_cli):
    def failed_provider():
        raise authority_module.AuthorityLoadError(
            code="kernel.member_set_mismatch",
            subject="language-bundle",
            message="duplicate object key",
        )

    descriptor = replace(SCHEMA_GET, handler=schema_get_handler(failed_provider))
    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "language-bundle"], registry=(descriptor,)
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert {item["code"] for item in error["diagnostics"]} == {
        "kernel.member_set_mismatch"
    }


def _authority_resource_bytes() -> dict[str, bytes]:
    root = Path(authority_module.__file__).parent / "authorities"
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*.json")
    }


def test_authority_loader_identity_is_independent_of_physical_member_location(
    monkeypatch, tmp_path
):
    baseline_kernel, baseline_ldb = authority_module.load_authorities()
    logical_members = _authority_resource_bytes()
    relocated: dict[str, Path] = {}
    blob_dir = tmp_path / "arbitrary-transport-layout"
    blob_dir.mkdir()
    for index, (logical_name, data) in enumerate(sorted(logical_members.items())):
        physical_path = blob_dir / f"member-{index}.blob"
        physical_path.write_bytes(data)
        relocated[logical_name] = physical_path

    class RelocatedResource:
        def __init__(self, logical_name=""):
            self.logical_name = logical_name

        def joinpath(self, *parts):
            name = "/".join((*self.logical_name.split("/"), *parts)).lstrip("/")
            return RelocatedResource(name)

        def read_bytes(self):
            return relocated[self.logical_name].read_bytes()

    monkeypatch.setattr(authority_module, "files", lambda _package: RelocatedResource())

    kernel, ldb = authority_module.load_authorities()

    assert kernel == baseline_kernel
    assert ldb.root == baseline_ldb.root
    assert ldb.package_releases == baseline_ldb.package_releases
    assert dict(ldb) == dict(baseline_ldb)


@pytest.mark.parametrize(
    ("unreadable", "subject"),
    [
        (
            "packages/core-quantity/core.quantity@2.0.0.json",
            "language-bundle.package_descriptors.0",
        ),
        (
            "packages/core-quantity/core.quantity@2.0.0.conformance-vectors.json",
            "language-bundle.package_descriptors.0.conformance_vectors",
        ),
    ],
)
def test_authority_loader_refuses_an_unreadable_declared_child(
    monkeypatch, unreadable, subject
):
    logical_members = _authority_resource_bytes()

    class UnreadableResource:
        def __init__(self, logical_name=""):
            self.logical_name = logical_name

        def joinpath(self, *parts):
            name = "/".join((*self.logical_name.split("/"), *parts)).lstrip("/")
            return UnreadableResource(name)

        def read_bytes(self):
            if self.logical_name == unreadable:
                raise OSError("injected unreadable member")
            return logical_members[self.logical_name]

    monkeypatch.setattr(
        authority_module, "files", lambda _package: UnreadableResource()
    )

    with pytest.raises(authority_module.AuthorityLoadError) as caught:
        authority_module.load_authorities()

    assert caught.value.code == "kernel.member_set_mismatch"
    assert caught.value.subject == subject


def test_schema_introspection_does_not_read_runtime_authorities(monkeypatch, run_cli):
    def fail_if_loaded():
        raise AssertionError("introspection read runtime authority")

    monkeypatch.setattr(
        schema_command_module,
        "packaged_authority_context",
        fail_if_loaded,
    )

    for argv in (["schema", "get", "--schema"], ["manifest"]):
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stderr) == (0, "")
        assert json.loads(stdout)


def test_language_bundle_returns_the_admitted_sealed_graph(run_cli):
    exit_code, stdout, stderr = run_cli(["schema", "get", "language-bundle"])

    assert (exit_code, stderr) == (0, "")
    authority = json.loads(stdout)
    assert set(authority) == {
        "kernel",
        "language_bundle",
        "package_conformance_vector_sets",
        "package_releases",
        "admission",
    }
    assert authority["kernel"]["artifact_kind"] == "schema-major-kernel"
    assert authority["language_bundle"]["artifact_kind"] == "language-definition-bundle"
    assert "language" not in authority["language_bundle"]
    assert (
        authority["language_bundle"]["kernel_identity"]
        == authority["kernel"]["content_identity"]
    )
    descriptors = authority["language_bundle"]["package_descriptors"]
    releases = authority["package_releases"]
    assert len(descriptors) == len(releases) > 1
    assert [(item["id"], item["version"]) for item in descriptors] == sorted(
        (item["id"], item["version"]) for item in descriptors
    )
    assert [
        {
            "artifact_kind": release["artifact_kind"],
            "id": release["id"],
            "version": release["version"],
            "content_identity": release["content_identity"],
        }
        for release in releases
    ] == [
        {
            key: descriptor[key]
            for key in ("artifact_kind", "id", "version", "content_identity")
        }
        for descriptor in descriptors
    ]
    assert authority["admission"] == {
        "admitted": True,
        "kernel_identity": authority["kernel"]["content_identity"],
        "language_bundle_identity": authority["language_bundle"]["content_identity"],
    }


def test_language_bundle_exposes_manifest_bound_conformance_vector_children(run_cli):
    exit_code, stdout, stderr = run_cli(["schema", "get", "language-bundle"])

    assert (exit_code, stderr) == (0, "")
    authority = json.loads(stdout)
    releases = authority["package_releases"]
    vector_sets = authority["package_conformance_vector_sets"]
    assert len(releases) == len(vector_sets) > 1

    for release, vector_set in zip(releases, vector_sets, strict=True):
        assert "vector_definitions" not in release
        assert "vectors" not in release
        descriptor = release["conformance_vectors"]
        assert descriptor == {
            "artifact_kind": vector_set["artifact_kind"],
            "byte_size": len(canonical_bytes(vector_set)),
            "content_identity": vector_set["content_identity"],
        }
        assert vector_set["artifact_kind"] == "package-conformance-vector-set"
        assert vector_set["package_id"] == release["id"]
        assert vector_set["package_version"] == release["version"]
        assert [item["id"] for item in vector_set["vector_definitions"]] == vector_set[
            "vectors"
        ]


def test_package_list_and_exact_get_return_root_declared_children(run_cli):
    _, authority_stdout, _ = run_cli(["schema", "get", "language-bundle"])
    authority = json.loads(authority_stdout)

    list_exit, list_stdout, list_stderr = run_cli(["package", "list"])
    assert (list_exit, list_stderr) == (0, "")
    listing = json.loads(list_stdout)
    list_success_schema = json.loads(run_cli(["package", "list", "--schema"])[1])[
        "success"
    ]
    jsonschema.validate(listing, list_success_schema)
    assert listing == {
        "language_bundle_identity": authority["language_bundle"]["content_identity"],
        "packages": authority["language_bundle"]["package_descriptors"],
    }

    for descriptor, release, vector_set in zip(
        listing["packages"],
        authority["package_releases"],
        authority["package_conformance_vector_sets"],
        strict=True,
    ):
        get_exit, get_stdout, get_stderr = run_cli(
            [
                "package",
                "get",
                "--id",
                descriptor["id"],
                "--version",
                descriptor["version"],
            ]
        )
        assert (get_exit, get_stderr) == (0, "")
        retrieved = json.loads(get_stdout)
        assert retrieved == release
        get_success_schema = json.loads(run_cli(["package", "get", "--schema"])[1])[
            "success"
        ]
        jsonschema.validate(retrieved, get_success_schema)
        vector_exit, vector_stdout, vector_stderr = run_cli(
            [
                "package",
                "get",
                "--id",
                descriptor["id"],
                "--version",
                descriptor["version"],
                "--member",
                "conformance-vectors",
            ]
        )
        assert (vector_exit, vector_stderr) == (0, "")
        assert json.loads(vector_stdout) == vector_set
        jsonschema.validate(vector_set, get_success_schema)


def test_package_command_schemas_reverse_conform_to_kernel_meta_format(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    kernel_meta = authority["kernel"]["meta_format"]
    release_contract = kernel_meta["package_release"]
    descriptor_contract = kernel_meta["language_bundle"]["package_descriptor"]

    get_schema = package_get_success_schema()
    release_schema, vector_set_schema = cast(list[dict[str, Any]], get_schema["oneOf"])
    get_properties = cast(dict[str, Any], release_schema["properties"])
    assert set(get_properties) == set(release_contract["required_members"])
    assert set(cast(list[str], release_schema["required"])) == set(
        release_contract["required_members"]
    )
    for field, members in release_contract["nested_members"].items():
        nested = cast(dict[str, Any], get_properties[field])
        assert set(nested["properties"]) == set(members)
        assert set(nested["required"]) == set(members)
    vector_set_contract = kernel_meta["package_conformance_vector_set"]
    assert set(vector_set_schema["properties"]) == set(
        vector_set_contract["required_members"]
    )
    assert set(vector_set_schema["required"]) == set(
        vector_set_contract["required_members"]
    )
    vector_definitions = cast(
        dict[str, Any],
        cast(dict[str, Any], vector_set_schema["properties"])["vector_definitions"],
    )
    vector_items = cast(dict[str, Any], vector_definitions["items"])
    assert {
        cast(dict[str, Any], item)["properties"]["kind"]["const"]
        for item in cast(list[dict[str, Any]], vector_items["oneOf"])
        if "kind" in cast(dict[str, Any], item)["properties"]
    } == {item["id"] for item in kernel_meta["package_vector"]["kinds"]}

    list_schema = package_list_success_schema()
    list_properties = cast(dict[str, Any], list_schema["properties"])
    packages_schema = cast(dict[str, Any], list_properties["packages"])
    descriptor_schema = cast(dict[str, Any], packages_schema["items"])
    assert set(descriptor_schema["properties"]) == set(
        descriptor_contract["required_members"]
    )
    assert set(descriptor_schema["required"]) == set(
        descriptor_contract["required_members"]
    )


def test_package_get_input_projects_kernel_coordinate_patterns(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    coordinate_contracts = authority["kernel"]["meta_format"]["language_bundle"][
        "package_descriptor"
    ]["field_types"]
    command_schema = json.loads(run_cli(["package", "get", "--schema"])[1])
    input_properties = command_schema["input"]["properties"]

    assert input_properties["id"]["pattern"] == coordinate_contracts["id"]["pattern"]
    assert (
        input_properties["version"]["pattern"]
        == coordinate_contracts["version"]["pattern"]
    )

    exit_code, stdout, stderr = run_cli(
        ["package", "get", "--id", "game/combat", "--version", "1.0.0"]
    )

    assert (exit_code, stdout) == (3, "")
    error = json.loads(stderr)["error"]
    assert (error["category"], error["code"]) == ("usage", "invalid_argument")


def test_package_get_schema_rejects_values_forbidden_by_kernel_meta_format(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    release = authority["package_releases"][0]
    success_schema = cast(dict[str, Any], package_get_success_schema())
    schema = cast(dict[str, Any], success_schema["oneOf"][0])
    invalid_releases = []

    invalid_list = deepcopy(release)
    invalid_list["runtime_semantic_paths"] = None
    invalid_releases.append(invalid_list)

    invalid_nested_list = deepcopy(release)
    invalid_nested_list["exports"]["diagnostics"] = None
    invalid_releases.append(invalid_nested_list)

    invalid_dependency = deepcopy(release)
    invalid_dependency["dependencies"]["required"] = [{"id": None, "version": "2.0.0"}]
    invalid_releases.append(invalid_dependency)

    open_dependency = deepcopy(release)
    open_dependency["dependencies"]["required"] = [
        {"id": "core.quantity", "version": "2.0.0", "peer": True}
    ]
    invalid_releases.append(open_dependency)

    invalid_coordinate = deepcopy(release)
    invalid_coordinate["id"] = "core/quantity"
    invalid_releases.append(invalid_coordinate)

    for invalid_release in invalid_releases:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_release, schema)


def test_public_authority_schemas_reject_invalid_package_vector_children(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    package_schema = cast(
        dict[str, Any],
        cast(list[dict[str, Any]], package_get_success_schema()["oneOf"])[1],
    )
    authority_schema = schema_get_success_schema()
    invalid_children = []

    malformed_definition = deepcopy(authority["package_conformance_vector_sets"][0])
    malformed_definition["vector_definitions"][0] = {"host": "invented"}
    invalid_children.append(malformed_definition)

    invalid_coordinate = deepcopy(authority["package_conformance_vector_sets"][0])
    invalid_coordinate["package_id"] = "core/quantity"
    invalid_children.append(invalid_coordinate)

    for invalid_child in invalid_children:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_child, package_schema)
        invalid_authority = deepcopy(authority)
        invalid_authority["package_conformance_vector_sets"][0] = invalid_child
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_authority, authority_schema)


@pytest.mark.parametrize(
    ("vector_id", "mutation"),
    [
        ("model.compile.positive", "outcome-host"),
        ("model.compile.negative-duplicate", "outcome-host"),
        ("model.compile.boundary-max-symbols", "outcome-host"),
        ("model.compile.boundary-max-symbols-plus-one", "outcome-host"),
        ("model.compile.mutation-role-change", "outcome-host"),
        ("model.compile.semantic-equivalent-order", "outcome-host"),
        ("model.compile.positive", "source-not-object"),
        ("model.compile.positive", "lock-oracle-open"),
        ("model.compile.positive", "rir-identity-not-string"),
        ("model.compile.positive", "debug-identity-not-string"),
        ("model.compile.positive", "semantic-artifacts-false"),
        ("model.compile.positive", "declaration-count-zero"),
        ("model.compile.positive", "admitted-diagnostics-nonempty"),
        ("model.compile.positive", "relation-kind-incompatible"),
        ("model.compile.positive", "independent-reference-non-null"),
        ("model.compile.negative-duplicate", "refused-lock-oracle-non-null"),
        ("model.compile.negative-duplicate", "refused-diagnostic-host"),
        ("model.compile.boundary-max-symbols", "collection-path-empty"),
        ("model.compile.boundary-max-symbols", "count-resource-path-empty"),
        ("model.compile.boundary-max-symbols", "count-offset-invalid"),
        ("model.compile.boundary-max-symbols", "template-not-object"),
        ("model.compile.boundary-max-symbols", "index-member-empty"),
        ("model.compile.boundary-max-symbols", "index-prefix-empty"),
        ("model.compile.boundary-max-symbols", "index-width-invalid"),
        ("model.compile.boundary-max-symbols", "index-encoding-host"),
    ],
)
def test_public_schemas_reject_every_invalid_model_program_vector_variant(
    run_cli, vector_id, mutation
):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    vector_set_index, vector_index = next(
        (set_index, definition_index)
        for set_index, vector_set in enumerate(
            authority["package_conformance_vector_sets"]
        )
        for definition_index, vector in enumerate(vector_set["vector_definitions"])
        if vector.get("id") == vector_id
    )
    invalid_child = deepcopy(
        authority["package_conformance_vector_sets"][vector_set_index]
    )
    vector = invalid_child["vector_definitions"][vector_index]
    fixture = vector["source_fixture"]
    expect = vector["expect"]
    if mutation == "outcome-host":
        expect["outcome"] = "host-owned"
    elif mutation == "source-not-object":
        fixture["source"] = 7
    elif mutation == "lock-oracle-open":
        expect["lock_oracle"] = {"host": "invented"}
    elif mutation == "rir-identity-not-string":
        expect["rir_identity"] = 7
    elif mutation == "debug-identity-not-string":
        expect["debug_map_identity"] = 7
    elif mutation == "semantic-artifacts-false":
        expect["semantic_artifacts"] = False
    elif mutation == "declaration-count-zero":
        expect["declaration_count"] = 0
    elif mutation == "admitted-diagnostics-nonempty":
        expect["diagnostics"] = [
            {"code": "host.invented", "stage": "static", "pointer": ""}
        ]
    elif mutation == "relation-kind-incompatible":
        expect["relation"] = {"kind": "semantic-change", "reference": vector_id}
    elif mutation == "independent-reference-non-null":
        expect["relation"]["reference"] = vector_id
    elif mutation == "refused-lock-oracle-non-null":
        expect["lock_oracle"] = {
            member: []
            for member in authority["kernel"]["meta_format"]["model_program_vector"][
                "lock_oracle_members"
            ]
        }
    elif mutation == "refused-diagnostic-host":
        expect["diagnostics"] = [
            {"code": "host.invented", "stage": "static", "pointer": ""}
        ]
    elif mutation == "collection-path-empty":
        fixture["collection_path"] = []
    elif mutation == "count-resource-path-empty":
        fixture["count_resource_path"] = ""
    elif mutation == "count-offset-invalid":
        fixture["count_offset"] = 2
    elif mutation == "template-not-object":
        fixture["template"] = []
    elif mutation == "index-member-empty":
        fixture["index_member"] = ""
    elif mutation == "index-prefix-empty":
        fixture["index_prefix"] = ""
    elif mutation == "index-width-invalid":
        fixture["index_width"] = 0
    else:
        fixture["index_encoding"] = "host-owned"

    package_schema = cast(
        dict[str, Any],
        cast(list[dict[str, Any]], package_get_success_schema()["oneOf"])[1],
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_child, package_schema)

    invalid_authority = deepcopy(authority)
    invalid_authority["package_conformance_vector_sets"][vector_set_index] = (
        invalid_child
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_authority, schema_get_success_schema())


def test_built_wheel_ships_only_the_declared_authority_graph_and_runs_it(
    tmp_path, run_cli
):
    package_root = Path(__file__).resolve().parents[1]
    authority_root = package_root / "src" / "gda_balancing" / "schema2" / "authorities"
    source_root = json.loads((authority_root / "language-bundle.json").read_text())
    expected_members = {
        "gda_balancing/schema2/authorities/kernel.json",
        "gda_balancing/schema2/authorities/language-bundle.json",
        *{
            "gda_balancing/schema2/authorities/packages/"
            f"{descriptor['id'].replace('.', '-')}/"
            f"{descriptor['id']}@{descriptor['version']}{suffix}"
            for descriptor in source_root["package_descriptors"]
            for suffix in (".json", ".conformance-vectors.json")
        },
    }
    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=package_root,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheels = sorted(tmp_path.glob("gda_balancing-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]

    with zipfile.ZipFile(wheel) as archive:
        shipped_members = {
            name
            for name in archive.namelist()
            if name.startswith("gda_balancing/schema2/authorities/")
            and name.endswith(".json")
        }
        assert shipped_members == expected_members
        for member in expected_members:
            source_path = package_root / "src" / member
            assert archive.read(member) == source_path.read_bytes()

    environment = {
        **os.environ,
        "PYTHONPATH": str(wheel),
    }

    def installed(*arguments):
        return subprocess.run(
            [sys.executable, "-m", "gda_balancing", *arguments],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
        )

    source_list = run_cli(["package", "list"])
    installed_list = installed("package", "list")
    assert (installed_list.returncode, installed_list.stderr) == (0, "")
    assert installed_list.stdout == source_list[1]

    for descriptor in source_root["package_descriptors"]:
        for member in ("release", "conformance-vectors"):
            arguments = (
                "package",
                "get",
                "--id",
                descriptor["id"],
                "--version",
                descriptor["version"],
                "--member",
                member,
            )
            source = run_cli(list(arguments))
            from_wheel = installed(*arguments)
            assert (from_wheel.returncode, from_wheel.stderr) == (0, "")
            assert from_wheel.stdout == source[1]


def test_kernel_closes_the_root_descriptor_index_and_graph_limits(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    kernel = authority["kernel"]
    root_contract = kernel["meta_format"]["language_bundle"]

    assert set(kernel["admission"]["required_ldb_members"]) == {
        "artifact_kind",
        "artifact_version",
        "schema_major",
        "kernel_identity",
        "resources",
        "package_descriptors",
        "content_identity",
    }
    assert set(root_contract["required_members"]) == set(
        kernel["admission"]["required_ldb_members"]
    )
    assert root_contract["package_descriptor"]["required_members"] == [
        "artifact_kind",
        "id",
        "version",
        "content_identity",
        "byte_size",
    ]
    assert root_contract["package_descriptor"]["canonical_order"] == [
        "id",
        "version",
    ]
    coordinate_contract = root_contract["package_descriptor"]["field_types"]
    assert coordinate_contract["id"] == {
        "type": "non-empty-string",
        "pattern": r"^[a-z0-9]+(?:\.[a-z0-9]+)*$",
    }
    assert coordinate_contract["version"] == {
        "type": "non-empty-string",
        "pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$",
    }
    identity_law = next(
        law
        for law in authority["kernel"]["admission"]["laws"]
        if law["id"] == "kernel.identity.verify"
    )
    assert {
        target.get("artifact") or target.get("collection")
        for target in identity_law["arguments"]["targets"]
    } == {
        "kernel",
        "language-bundle",
        "language_bundle.language.packages",
        "language_bundle.package_conformance_vector_sets",
    }
    assert set(
        kernel["meta_format"]["admitted_language_index"]["required_members"]
    ) == {
        "artifact_kind",
        "artifact_version",
        "schema_major",
        "kernel_identity",
        "content_identity",
        "language",
        "diagnostics",
        "resources",
        "vectors",
    }
    assert {
        "max_ldb_root_bytes",
        "max_ldb_child_bytes",
        "max_ldb_total_bytes",
        "max_ldb_package_count",
        "max_ldb_dependency_depth",
        "max_ldb_dependency_steps",
        "max_ldb_admission_work",
    } <= set(kernel["resources"])


def test_game_mechanics_are_orthogonal_packages_composed_by_operation(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    releases = {release["id"]: release for release in authority["package_releases"]}
    assert {"game.resource", "game.check", "game.combat"} <= set(releases)
    assert "game.rpg" not in releases

    def definitions(package_id, authority_path):
        return next(
            entry["definitions"]
            for entry in releases[package_id]["semantic_closure"]
            if entry["authority_path"] == authority_path
        )

    resource_operations = {
        item["id"] for item in definitions("game.resource", "language.operations")
    }
    check_operations = {
        item["id"] for item in definitions("game.check", "language.operations")
    }
    combat_operations = {
        item["id"] for item in definitions("game.combat", "language.operations")
    }
    assert resource_operations == {"game.resource.spend-v1"}
    assert check_operations == {
        "game.check.hit-v1",
        "game.check.critical-v1",
    }
    assert combat_operations == {
        "game.combat.damage-v1",
        "game.combat.cast-v1",
    }
    cast = next(
        operation
        for operation in definitions("game.combat", "language.operations")
        if operation["id"] == "game.combat.cast-v1"
    )
    assert [
        (instruction["node"], instruction["operation"]) for instruction in cast["body"]
    ] == [
        (
            "invoke",
            {
                "package": "game.resource",
                "version": "1.0.0",
                "id": "game.resource.spend-v1",
            },
        ),
        (
            "invoke",
            {
                "package": "game.check",
                "version": "1.0.0",
                "id": "game.check.hit-v1",
            },
        ),
        (
            "invoke",
            {
                "package": "game.check",
                "version": "1.0.0",
                "id": "game.check.critical-v1",
            },
        ),
        (
            "invoke",
            {
                "package": "game.combat",
                "version": "1.0.0",
                "id": "game.combat.damage-v1",
            },
        ),
    ]
    assert all(item["type"]["id"] == "Quantity" for item in cast["inputs"])
    serialized = json.dumps(authority["package_releases"], sort_keys=True)
    assert "game.rpg" not in serialized
    assert "RpgValue" not in serialized
    assert "rpg." not in serialized


def test_standard_compiler_owns_generic_model_admission_contracts(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    releases = {release["id"]: release for release in authority["package_releases"]}
    compiler = releases["standard.compiler"]
    quantity = releases["core.quantity"]

    def definitions(package, authority_path):
        return next(
            entry["definitions"]
            for entry in package["semantic_closure"]
            if entry["authority_path"] == authority_path
        )

    compiler_diagnostics = {
        item["code"] for item in definitions(compiler, "diagnostics")
    }
    quantity_diagnostics = {
        item["code"] for item in definitions(quantity, "diagnostics")
    }
    assert {
        "language.duplicate_symbol",
        "language.name_ambiguity",
        "language.package_version_unavailable",
        "language.resolution_ambiguity",
        "language.resolution_binding_mismatch",
        "language.resolved_authority_mismatch",
        "language.resource_exhausted",
        "language.source_contract_mismatch",
        "language.source_parse_failure",
        "language.source_too_large",
        "language.unresolved_name",
    } <= compiler_diagnostics
    assert not compiler_diagnostics & quantity_diagnostics
    assert compiler["profiles"] == {
        "numeric": [],
        "resolution": ["exact-import-resolution-v1"],
        "runtime": ["compile.exact-int64"],
    }
    assert compiler["exports"]["model_checks"] == []
    assert compiler["exports"]["model_lowerings"] == []
    assert quantity["dependencies"]["required"] == [
        {"id": "standard.compiler", "version": "1.0.0"}
    ]
    assert quantity["exports"]["model_checks"]
    assert quantity["exports"]["model_lowerings"] == ["quantity.model-lowering"]


def test_package_dependencies_are_closed_exact_coordinates(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    dependency_contract = authority["kernel"]["meta_format"][
        "package_dependency_constraint"
    ]
    assert dependency_contract == {
        "closed": True,
        "field_types": {
            "id": {
                "pattern": r"^[a-z0-9]+(?:\.[a-z0-9]+)*$",
                "type": "non-empty-string",
            },
            "version": {
                "pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$",
                "type": "non-empty-string",
            },
        },
        "required_members": ["id", "version"],
        "type": "closed-object",
    }
    dependency_fields = authority["kernel"]["meta_format"]["package_release"][
        "nested_field_types"
    ]["dependencies"]
    assert dependency_fields["required"]["items"] == dependency_contract
    assert dependency_fields["optional"]["items"] == dependency_contract

    coordinates = {
        (release["id"], release["version"]) for release in authority["package_releases"]
    }
    for release in authority["package_releases"]:
        for dependency in [
            *release["dependencies"]["required"],
            *release["dependencies"]["optional"],
        ]:
            assert set(dependency) == {"id", "version"}
            assert (dependency["id"], dependency["version"]) in coordinates

    schema_package = next(
        release
        for release in authority["package_releases"]
        if release["id"] == "standard.schema"
    )
    wire_definitions = next(
        entry["definitions"]
        for entry in schema_package["semantic_closure"]
        if entry["authority_path"] == "language.artifact_wire_schemas"
    )
    lock_schema = next(
        item["schema"]
        for item in wire_definitions
        if item["artifact_kind"] == "package-lock"
    )
    edge_schema = lock_schema["properties"]["dependency_edges"]["items"]
    assert set(edge_schema["required"]) == {
        "from_package",
        "kind",
        "to_package",
        "to_version",
    }

    quantity = next(
        release
        for release in authority["package_releases"]
        if release["id"] == "core.quantity"
    )
    vector_sets = {
        vector_set["package_id"]: vector_set
        for vector_set in authority["package_conformance_vector_sets"]
    }
    admitted_oracles = [
        vector["expect"]["lock_oracle"]
        for vector in vector_sets[quantity["id"]]["vector_definitions"]
        if vector.get("expect", {}).get("outcome") == "admitted"
    ]
    assert admitted_oracles
    assert all(
        set(edge) == {"from_package", "kind", "to_package", "to_version"}
        for oracle in admitted_oracles
        for edge in oracle["dependency_edges"]
    )


def test_game_mechanics_ship_closed_owned_evidence_vectors(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    contract = authority["kernel"]["meta_format"]["package_vector"]
    required_categories = {
        "positive",
        "negative",
        "boundary",
        "semantic-mutation",
        "dependency",
        "outcome",
        "refusal",
        "deterministic-rng",
        "effects",
        "rollback-replay",
        "resource",
    }
    assert contract["closed"] is True
    assert set(contract["categories"]) == required_categories
    assert {item["id"] for item in contract["kinds"]} == {
        "package-contract",
        "operation-contract",
        "runtime-scenario",
    }

    releases = {release["id"]: release for release in authority["package_releases"]}
    vector_sets = {
        vector_set["package_id"]: vector_set
        for vector_set in authority["package_conformance_vector_sets"]
    }
    vectors = []
    for package_id in ("game.resource", "game.check", "game.combat"):
        package = releases[package_id]
        vector_set = vector_sets[package_id]
        assert vector_set["vectors"]
        assert [item["id"] for item in vector_set["vector_definitions"]] == vector_set[
            "vectors"
        ]
        owned_operations = {
            item["id"]: item
            for item in next(
                entry["definitions"]
                for entry in package["semantic_closure"]
                if entry["authority_path"] == "language.operations"
            )
        }
        referenced = {
            vector_id
            for operation in owned_operations.values()
            for vector_id in operation["vectors"]
        }
        assert referenced <= set(vector_set["vectors"])
        assert all(operation["vectors"] for operation in owned_operations.values())
        for vector in vector_set["vector_definitions"]:
            if "kind" not in vector:
                continue
            if vector["kind"] != "package-contract":
                assert vector["operation"] in owned_operations
                assert vector["id"] in owned_operations[vector["operation"]]["vectors"]
        vectors.extend(
            vector for vector in vector_set["vector_definitions"] if "kind" in vector
        )

    assert len({item["id"] for item in vectors}) == len(vectors)
    assert {item["category"] for item in vectors} == required_categories


def test_wire_schema_is_an_exact_projection_of_the_admitted_authorities(run_cli):
    _, authority_stdout, _ = run_cli(["schema", "get", "language-bundle"])
    exit_code, stdout, stderr = run_cli(["schema", "get", "wire-schema"])

    assert (exit_code, stderr) == (0, "")
    authority = json.loads(authority_stdout)
    projection = json.loads(stdout)
    assert set(projection) == {
        "artifact_kind",
        "content_identity",
        "kernel_identity",
        "language_bundle_identity",
        "schemas",
    }
    assert projection["artifact_kind"] == "wire-schema-projection"
    assert projection["kernel_identity"] == authority["kernel"]["content_identity"]
    assert (
        projection["language_bundle_identity"]
        == authority["language_bundle"]["content_identity"]
    )
    schemas = {item["artifact_kind"]: item["schema"] for item in projection["schemas"]}
    assert set(schemas) == {
        "artifact-set-manifest",
        "artifact-set-receipt",
        "boundary-vector",
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "declared-package-dependencies",
        "evaluation-run",
        "evaluator-capability-manifest",
        "event-trace",
        "experiment-specification",
        "experiment-template",
        "experiment-verdict",
        "genre-coverage-matrix",
        "golden-scenario",
        "metric-dataset",
        "migration-refusal-report",
        "migration-report",
            "model-build-command-input",
            "model-explanation",
            "model-migrate-command-input",
        "package-lock",
        "publication-index",
        "negative-vector",
        "reproduction-receipt",
        "resolution-receipt",
        "resolved-model",
        "resolved-runtime-profile",
        "rir-semantic-payload",
        "runtime-terminal-audit",
        "schema-major-kernel",
        "snapshot-series",
        "source-converter-specification",
        "language-definition-bundle",
        "model-source-package",
        "template-compatibility",
        "template-defaults",
        "template-documentation",
        "template-instantiate-command-input",
        "template-instantiation-receipt",
        "template-release",
    }
    jsonschema.validate(authority["kernel"], schemas["schema-major-kernel"])
    jsonschema.validate(
        authority["language_bundle"], schemas["language-definition-bundle"]
    )
    for role in (
        "constant",
        "parameter",
        "input",
        "state",
        "derived",
        "output",
        "random",
    ):
        source = json.loads(MODEL_CHECK.fixtures.valid_document or "{}")
        source["entrypoints"] = []
        value_policies = {
            "constant": {"mode": "model-fixed", "value": 1},
            "parameter": {"mode": "experiment-required"},
            "input": {"mode": "experiment-required"},
            "state": {"mode": "experiment-required"},
            "derived": {"mode": "none"},
            "output": {"mode": "none"},
            "random": {"mode": "named-stream"},
        }
        source["modules"][0]["symbols"] = [
            {
                "symbol": role,
                "type": "quantity",
                "role": role,
                "representation": "Int",
                "kind": "scalar",
                "unit": "1",
                "domain_kind": "closed-interval",
                "domain": {"minimum": 0, "maximum": 100},
                "numeric_policy": "exact-int64",
                "value_policy": value_policies[role],
            }
        ]
        jsonschema.validate(
            source,
            schemas["model-source-package"],
        )


def test_diagnostic_catalog_is_reverse_closed_over_kernel_and_ldb(run_cli):
    _, authority_stdout, _ = run_cli(["schema", "get", "language-bundle"])
    exit_code, stdout, stderr = run_cli(["schema", "get", "diagnostic-catalog"])

    assert (exit_code, stderr) == (0, "")
    authority = json.loads(authority_stdout)
    catalog = json.loads(stdout)
    package_diagnostics = [
        entry
        for release in authority["package_releases"]
        for closure in release["semantic_closure"]
        if closure["authority_path"] == "diagnostics"
        for entry in closure["definitions"]
    ]
    expected = sorted(
        [
            {"authority": owner, "code": entry["code"], "stage": entry["stage"]}
            for owner, entries in (
                ("kernel", authority["kernel"]["diagnostics"]),
                ("language-bundle", package_diagnostics),
            )
            for entry in entries
        ],
        key=lambda entry: (entry["stage"], entry["code"], entry["authority"]),
    )
    assert catalog["entries"] == expected
    assert len({entry["code"] for entry in catalog["entries"]}) == len(expected)


def test_manifest_and_per_command_schema_are_one_descriptor_projection(
    run_cli, tmp_path, invocation
):
    exit_code, stdout, stderr = run_cli(["manifest"])

    assert (exit_code, stderr) == (0, "")
    manifest = json.loads(stdout)
    assert manifest["artifact_kind"] == "surface-manifest"
    assert manifest["surface_version"] == "2.0.0"
    assert manifest["command_schema_profile"]["artifact_kind"] == (
        "command-schema-profile"
    )
    commands = {
        " ".join(filter(None, (row["group"], row["command"]))): row
        for row in manifest["commands"]
    }
    assert set(commands) == {
        "schema get",
        "version",
        "manifest",
        "experiment check",
        "experiment run",
        "model check",
            "model build",
            "model inspect",
            "model migrate",
        "template list",
        "template get",
        "template instantiate",
        "package list",
        "package get",
    }

    for path, row in commands.items():
        schema_exit, schema_stdout, schema_stderr = run_cli([*path.split(), "--schema"])
        assert (schema_exit, schema_stderr) == (0, "")
        assert json.loads(schema_stdout) == row["schema"]
        assert row["descriptor_identity"].startswith("sha256:")
        expected_schema_members = {
            "artifact_kind",
            "content_identity",
            "descriptor_identity",
            "error",
            "input",
            "profile_identity",
            "success",
        }
        if path == "experiment run":
            expected_schema_members.add("verdict")
        assert set(row["schema"]) == expected_schema_members
        if path == "schema get":
            argv = ["schema", "get", "language-bundle"]
        elif path == "version":
            argv = ["version"]
        elif path == "manifest":
            argv = ["manifest"]
        elif path == "experiment check":
            argv = invocation(EXPERIMENT_CHECK)
        elif path == "experiment run":
            argv = invocation(EXPERIMENT_RUN)
        elif path == "model inspect":
            argv = invocation(MODEL_INSPECT)
        elif path == "template list":
            argv = ["template", "list"]
        elif path == "template get":
            argv = [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        elif path == "template instantiate":
            argv = [
                "template",
                "instantiate",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
                "--package-id",
                "example.manifest-projection",
                "--out",
                str(tmp_path / "manifest-template-output"),
                "--invocation-key",
                "b" * 64,
            ]
        elif path == "package list":
            argv = ["package", "list"]
        elif path == "package get":
            argv = [
                "package",
                "get",
                "--id",
                "core.quantity",
                "--version",
                "2.0.0",
            ]
        else:
            descriptor = {
                "model build": MODEL_BUILD,
                "model check": MODEL_CHECK,
                "model inspect": MODEL_INSPECT,
                "model migrate": MODEL_MIGRATE,
            }[path]
            source = tmp_path / f"{path.replace(' ', '-')}.json"
            source.write_text(
                descriptor.fixtures.valid_document or "", encoding="utf-8"
            )
            argv = ["model", path.split()[1], str(source)]
            if descriptor.artifact_set:
                argv.extend(
                    [
                        "--out",
                        str(tmp_path / f"manifest-{path.replace(' ', '-')}-output"),
                        "--invocation-key",
                        ("a" if path == "model build" else "c") * 64,
                    ]
                )
        result_exit, result_stdout, result_stderr = run_cli(argv)
        assert (result_exit, result_stderr) == (0, ""), (
            path,
            result_stdout,
            result_stderr,
        )
        jsonschema.validate(json.loads(result_stdout), row["schema"]["success"])


def test_command_refusal_catalogs_are_exact_and_vector_witnessed(run_cli):
    bootstrap = set(BOOTSTRAP_REFUSAL_CATALOG)
    model = {
        ("language.source_too_large", "ingress"),
        ("language.source_parse_failure", "parse"),
        ("language.source_contract_mismatch", "static"),
        ("language.invalid_domain", "static"),
        ("language.unknown_kind", "static"),
        ("language.unknown_unit", "static"),
        ("language.duplicate_symbol", "static"),
        ("language.resource_exhausted", "static"),
        ("language.unresolved_name", "static"),
        ("language.name_ambiguity", "static"),
        ("language.package_version_unavailable", "resolution"),
        ("language.resolution_ambiguity", "resolution"),
    }
    experiment_check = {
        ("language.source_too_large", "ingress"),
        ("language.source_parse_failure", "parse"),
        ("language.source_contract_mismatch", "static"),
        ("language.invalid_domain", "static"),
        ("language.resolved_authority_mismatch", "resolution"),
        ("language.resolution_binding_mismatch", "resolution"),
    }
    experiment_run_only = {
        ("runtime.capability_unsupported", "resolution"),
        ("runtime.step_limit_exceeded", "runtime"),
        ("runtime.numeric_overflow", "runtime"),
        ("evaluation.observation_unavailable", "evaluation"),
    }
    expected = {
        MODEL_CHECK: bootstrap | model,
        MODEL_BUILD: bootstrap | model,
        TEMPLATE_LIST: bootstrap | model,
        TEMPLATE_GET: bootstrap | model,
        TEMPLATE_INSTANTIATE: bootstrap | model,
        EXPERIMENT_CHECK: bootstrap | experiment_check,
        EXPERIMENT_RUN: bootstrap | experiment_check | experiment_run_only,
    }
    for descriptor, catalog in expected.items():
        assert set(descriptor.refusal_catalog) == catalog

    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    witnessed_codes: set[str] = set()
    for vector_set in authority["package_conformance_vector_sets"]:
        for vector in vector_set["vector_definitions"]:
            diagnostic = vector.get("diagnostic")
            if isinstance(diagnostic, str):
                witnessed_codes.add(diagnostic)
            expect = vector.get("expect")
            if isinstance(expect, dict):
                witnessed_codes.update(
                    item["code"]
                    for item in expect.get("diagnostics", [])
                    if isinstance(item, dict) and isinstance(item.get("code"), str)
                )
    for catalog in expected.values():
        assert {code for code, _stage in catalog - bootstrap} <= witnessed_codes


def test_per_command_error_schema_rejects_undeclared_refusal_stages_and_codes(run_cli):
    manifest_schema = json.loads(run_cli(["manifest", "--schema"])[1])["error"]
    schema_get_schema = json.loads(run_cli(["schema", "get", "--schema"])[1])["error"]
    invented_refusal = {
        "error": {
            "category": "refusal",
            "stage": "runtime",
            "diagnostics": [
                {
                    "code": "host.invented",
                    "message": "not authoritative",
                    "primary": {
                        "kind": "artifact",
                        "content_identity": "unidentified",
                        "pointer": "/",
                    },
                    "related": [],
                }
            ],
            "truncated": False,
        }
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invented_refusal, manifest_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invented_refusal, schema_get_schema)


def test_schema2_internal_schema_matches_deterministic_debug_contract():
    schema = schema2_error_envelope_schema(SCHEMA_GET)
    base = {
        "error": {
            "category": "internal",
            "code": "internal_error",
            "message": "sanitized",
        }
    }
    jsonschema.validate(base, schema)
    with_debug = deepcopy(base)
    with_debug["error"]["debug"] = "trace"
    jsonschema.validate(with_debug, schema)

    for forbidden in ("diagnostics", "reproduction"):
        mutant = deepcopy(base)
        mutant["error"][forbidden] = "not reachable"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(mutant, schema)


def test_kernel_stage_vocabulary_is_the_runtime_discriminant(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    declared = tuple(authority["kernel"]["admission"]["refusal_stages"])

    assert declared == (
        "ingress",
        "parse",
        "static",
        "resolution",
        "runtime",
        "evaluation",
        "migration",
        "approval",
    )
    assert set(declared) == set(get_args(RefusalStage))
    assert set(declared) == set(bootstrap_module.SCHEMA2_REFUSAL_STAGES)
    assert {
        (item["code"], item["stage"]) for item in authority["kernel"]["diagnostics"]
    } == set(bootstrap_module.BOOTSTRAP_REFUSAL_CATALOG)


def test_dispatch_rejects_a_refusal_absent_from_the_descriptor_catalog(run_cli):
    invented = Schema2RefusalReport(
        stage="runtime",
        diagnostics=(
            Schema2Diagnostic(
                code="host.invented",
                message="not authoritative",
                primary=ArtifactLocation(content_identity="unidentified", pointer="/"),
            ),
        ),
        truncated=False,
    )
    descriptor = replace(MANIFEST, handler=lambda _inp: invented)

    exit_code, stdout, stderr = run_cli(["manifest"], registry=(descriptor,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


def test_structured_params_share_binding_and_conflict_with_argv_fields(run_cli):
    direct = run_cli(["schema", "get", "language-bundle"])
    inline = run_cli(["schema", "get", '--params-json={"artifact":"language-bundle"}'])
    piped = run_cli(
        ["schema", "get", "--params-json", "-"],
        stdin='{"artifact":"language-bundle"}',
    )

    assert inline == direct == piped

    exit_code, stdout, stderr = run_cli(
        [
            "schema",
            "get",
            "language-bundle",
            "--params-json",
            '{"artifact":"wire-schema"}',
        ]
    )
    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"

    # Bare --schema wins without parsing or reading structured input.
    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "--params-json", "-", "--schema"], stdin="not JSON"
    )
    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["artifact_kind"] == "command-schema"


def test_bootstrap_refusal_reports_sorted_bounded_diagnostics_at_cli(run_cli):
    loaded_kernel, loaded_ldb = authority_module.load_authorities()
    kernel = deepcopy(loaded_kernel)
    ldb = deepcopy(loaded_ldb)
    diagnostic_cap = kernel["resources"]["max_diagnostics"]
    core = next(
        vector_set
        for vector_set in ldb.package_conformance_vector_sets
        if vector_set["package_id"] == "core.quantity"
    )
    for index in range(diagnostic_cap + 2):
        vector_id = f"mutant.{index}"
        core["vector_definitions"].append(
            {
                "expect": {},
                "id": vector_id,
                "input": {"facts": [], "judgment": "missing"},
                "rule": "quantity.declare",
            }
        )
        core["vectors"].append(vector_id)
    ldb = _reidentify_graph(kernel, ldb)

    descriptor = replace(
        SCHEMA_GET,
        handler=schema_get_handler(lambda: (kernel, ldb)),
    )
    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "language-bundle"], registry=(descriptor,)
    )

    assert (exit_code, stderr) == (2, "")
    payload = json.loads(stdout)
    jsonschema.validate(payload, schema2_error_envelope_schema(descriptor))
    error = payload["error"]
    assert error["stage"] == "static"
    assert error["truncated"] is True
    assert len(error["diagnostics"]) == diagnostic_cap
    keys = [(item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]]
    assert keys == sorted(set(keys))


def test_bootstrap_nesting_cap_refuses_before_static_rule_execution(run_cli):
    loaded_kernel, loaded_ldb = authority_module.load_authorities()
    kernel = deepcopy(loaded_kernel)
    ldb = deepcopy(loaded_ldb)
    nested: object = "leaf"
    for _ in range(kernel["resources"]["max_nesting_depth"] + 1):
        nested = [nested]
    ldb.package_conformance_vector_sets[0]["vector_definitions"][0][
        "unused_host_payload"
    ] = nested
    ldb = _reidentify_graph(kernel, ldb)
    descriptor = replace(SCHEMA_GET, handler=schema_get_handler(lambda: (kernel, ldb)))

    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "language-bundle"], registry=(descriptor,)
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert {item["code"] for item in error["diagnostics"]} == {
        "kernel.resource_exhausted"
    }


def test_noncanonical_authority_value_is_a_typed_ingress_refusal(run_cli):
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    ldb["resources"]["max_source_bytes"] = 2**63
    descriptor = replace(SCHEMA_GET, handler=schema_get_handler(lambda: (kernel, ldb)))

    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "language-bundle"], registry=(descriptor,)
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert {item["code"] for item in error["diagnostics"]} == {
        "kernel.identity_mismatch",
        "kernel.member_set_mismatch",
        "kernel.resource_exhausted",
    }


def test_command_schema_profile_closes_objects_and_exhausts_used_keywords(run_cli):
    manifest = json.loads(run_cli(["manifest"])[1])
    admitted = set(manifest["command_schema_profile"]["admitted_keywords"])
    used: set[str] = set()

    def walk(schema):
        assert isinstance(schema, dict)
        used.update(schema)
        if schema.get("type") == "object":
            assert schema.get("unevaluatedProperties") is False
        for keyword in ("properties", "$defs"):
            for child in schema.get(keyword, {}).values():
                walk(child)
        items = schema.get("items")
        if isinstance(items, dict):
            walk(items)
        for keyword in ("oneOf", "anyOf"):
            for child in schema.get(keyword, []):
                walk(child)

    for command in manifest["commands"]:
        for outcome in ("input", "success", "error"):
            walk(command["schema"][outcome])

    assert used <= admitted
