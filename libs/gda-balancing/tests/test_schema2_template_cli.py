"""Public Template release and instantiation tracer for Standard Schema 2.0 (#553)."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest
from gda_balancing.commands.template import (
    TEMPLATE_GET,
    TEMPLATE_INSTANTIATE,
    template_get_handler,
    template_instantiate_handler,
)
from gda_balancing.schema2.canonical import canonical_bytes, content_identity


def _reidentify_release(release):
    release["manifest"] = []
    for member in release["members"]:
        member["content_identity"] = content_identity(
            "template-member-v2",
            {key: value for key, value in member.items() if key != "content_identity"},
        )
        release["manifest"].append(
            {
                key: member[key]
                for key in (
                    "logical_name",
                    "member_kind",
                    "member_schema_identity",
                    "content_identity",
                )
            }
        )
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    return release


def _template_invocation_directory(invocation_key):
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "invocations").glob(
            f"*/{invocation_key}"
        )
    )
    assert len(matches) == 1
    return matches[0]


def _template_anchor_path(invocation_key):
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors").glob(
            f"*/{invocation_key}.json"
        )
    )
    assert len(matches) == 1
    return matches[0]


def test_template_list_exposes_the_packaged_content_addressed_release(run_cli):
    exit_code, stdout, stderr = run_cli(["template", "list"])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result == {
        "templates": [
            {
                "id": "standard.quantity-minimal",
                "version": "2.0.0",
                "content_identity": (
                    "sha256:a084070dd49bb4911206d36c1d7759183aa1f68f1a7b04607c6375bd2d54d3f1"
                ),
            }
        ]
    }
    assert result["templates"][0]["content_identity"].startswith("sha256:")


def test_template_get_returns_the_complete_content_addressed_release(run_cli):
    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ]
    )

    assert (exit_code, stderr) == (0, "")
    release = json.loads(stdout)
    assert release["artifact_kind"] == "template-release"
    assert (release["id"], release["version"]) == (
        "standard.quantity-minimal",
        "2.0.0",
    )
    assert [item["logical_name"] for item in release["manifest"]] == [
        "starter-model-source",
        "experiment-specification",
        "declared-package-dependencies",
        "defaults",
        "compatibility",
        "documentation",
        "coverage-matrix",
        "golden-scenario",
        "negative-vector",
        "boundary-vector",
    ]
    assert len(release["members"]) == len(release["manifest"])
    for entry, member in zip(release["manifest"], release["members"], strict=True):
        assert {
            key: member[key]
            for key in (
                "logical_name",
                "member_kind",
                "member_schema_identity",
                "content_identity",
            )
        } == entry
        assert member["content_identity"] == content_identity(
            "template-member-v2",
            {key: value for key, value in member.items() if key != "content_identity"},
        )
    assert release["content_identity"] == content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )


def test_every_template_member_is_admitted_by_the_exact_kernel_and_ldb(
    tmp_path, run_cli
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    members = {item["logical_name"]: item for item in release["members"]}
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    schemas = {
        item["artifact_kind"]: item["schema"]
        for item in json.loads(run_cli(["schema", "get", "wire-schema"])[1])["schemas"]
    }

    for member in members.values():
        schema = schemas[member["member_kind"]]
        assert member["member_schema_identity"] == (
            "sha256:" + schema["$id"].rsplit(":", 1)[-1]
        )
        jsonschema.validate(member["payload"], schema)

    starter = members["starter-model-source"]["payload"]
    source = tmp_path / "starter.json"
    source.write_text(json.dumps(starter), encoding="utf-8")
    assert run_cli(["model", "check", str(source)])[0] == 0
    starter_identity = content_identity("model-source-package-v2", starter)

    language = authority["language_bundle"]["language"]
    package_inventory = {
        (item["id"], item["version"], item["content_identity"])
        for item in language["packages"]
    }
    dependencies = members["declared-package-dependencies"]["payload"]
    assert {
        (item["id"], item["version"], item["content_identity"])
        for item in dependencies["packages"]
    } <= package_inventory

    experiment = members["experiment-specification"]["payload"]
    assert experiment["kernel_identity"] == release["kernel_identity"]
    assert experiment["language_bundle_identity"] == release["language_bundle_identity"]
    assert experiment["model_source_identity"] == starter_identity

    coverage = members["coverage-matrix"]["payload"]["rows"][0]
    assert set(coverage["capabilities"]) <= {
        item["id"] for item in language["capabilities"]
    }
    known_operations = {item["id"] for item in language["operations"]}
    assert set(coverage["operations"]) <= known_operations
    assert set(coverage["packages"]) <= {item["id"] for item in language["packages"]}
    assert set(coverage["observables"]) <= {
        item["id"] for item in experiment["metrics"]
    }
    assert coverage["experiment"] == experiment["id"]

    golden = members["golden-scenario"]["payload"]
    negative = members["negative-vector"]["payload"]
    boundary = members["boundary-vector"]["payload"]
    assert golden["id"] == coverage["golden_scenario"]
    assert golden["experiment"] == experiment["id"]
    assert golden["model_source_identity"] == starter_identity
    assert {negative["id"], boundary["id"]} == set(coverage["vectors"])

    refused = deepcopy(starter)
    refused["modules"][0]["symbols"][0]["domain"] = negative["mutation"]["value"]
    refused_path = tmp_path / "negative.json"
    refused_path.write_text(json.dumps(refused), encoding="utf-8")
    exit_code, stdout, stderr = run_cli(["model", "check", str(refused_path)])
    assert (exit_code, stderr) == (2, "")
    assert (
        json.loads(stdout)["error"]["diagnostics"][0]["code"] == negative["diagnostic"]
    )

    accepted = deepcopy(starter)
    accepted["modules"][0]["symbols"][0]["domain"]["minimum"] = boundary["value"]
    accepted_path = tmp_path / "boundary.json"
    accepted_path.write_text(json.dumps(accepted), encoding="utf-8")
    assert run_cli(["model", "check", str(accepted_path)])[0] == 0


def test_template_get_refuses_an_unknown_release_with_a_stable_ldb_diagnostic(
    run_cli,
):
    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "missing.template",
            "--version",
            "9.9.9",
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.package_version_unavailable"
    ]


def test_template_get_refuses_a_release_for_an_incompatible_ldb(run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    release["language_bundle_identity"] = "sha256:" + "0" * 64
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert error["diagnostics"][0]["code"] == ("language.package_version_unavailable")
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/language_bundle_identity"
    )


def test_template_get_refuses_a_member_outside_its_ldb_wire_schema(run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    documentation = next(
        item for item in release["members"] if item["logical_name"] == "documentation"
    )
    documentation["payload"]["host_customization_hook"] = "forbidden"
    documentation["content_identity"] = content_identity(
        "template-member-v2",
        {
            key: value
            for key, value in documentation.items()
            if key != "content_identity"
        },
    )
    manifest_entry = next(
        item for item in release["manifest"] if item["logical_name"] == "documentation"
    )
    manifest_entry["content_identity"] = documentation["content_identity"]
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == ("language.source_contract_mismatch")


def test_template_get_refuses_semantically_unbound_companion_evidence(run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    experiment = next(
        item
        for item in release["members"]
        if item["logical_name"] == "experiment-specification"
    )
    experiment["payload"]["model_source_identity"] = "sha256:" + "0" * 64
    experiment["content_identity"] = content_identity(
        "template-member-v2",
        {key: value for key, value in experiment.items() if key != "content_identity"},
    )
    manifest_entry = next(
        item
        for item in release["manifest"]
        if item["logical_name"] == "experiment-specification"
    )
    manifest_entry["content_identity"] = experiment["content_identity"]
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == ("language.source_contract_mismatch")


def test_template_get_refuses_every_reidentified_semantic_admission_mutation(
    run_cli,
):
    pristine = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )

    def member(release, name):
        return next(
            item for item in release["members"] if item["logical_name"] == name
        )["payload"]

    mutations = []

    missing_operation = deepcopy(pristine)
    extra_row = deepcopy(member(missing_operation, "coverage-matrix")["rows"][0])
    extra_row["id"] = "template.quantity.unbound"
    extra_row["operations"] = ["missing.operation"]
    member(missing_operation, "coverage-matrix")["rows"].append(extra_row)
    mutations.append(missing_operation)

    missing_pointer = deepcopy(pristine)
    member(missing_pointer, "boundary-vector")["pointer"] = "/does/not/exist"
    mutations.append(missing_pointer)

    false_negative = deepcopy(pristine)
    member(false_negative, "negative-vector")["mutation"]["value"] = {
        "minimum": 0,
        "maximum": 100,
    }
    mutations.append(false_negative)

    unavailable_source_package = deepcopy(pristine)
    starter = member(unavailable_source_package, "starter-model-source")
    starter["package_requirements"][0]["version"] = "9.9.9"
    starter["modules"][0]["imports"][0]["version"] = "9.9.9"
    mutated_source_identity = content_identity("model-source-package-v2", starter)
    member(unavailable_source_package, "experiment-specification")[
        "model_source_identity"
    ] = mutated_source_identity
    member(unavailable_source_package, "golden-scenario")["model_source_identity"] = (
        mutated_source_identity
    )
    mutations.append(unavailable_source_package)

    missing_role = deepcopy(pristine)
    missing_role["members"] = [
        item
        for item in missing_role["members"]
        if item["logical_name"] != "documentation"
    ]
    mutations.append(missing_role)

    unknown_metric_unit = deepcopy(pristine)
    member(unknown_metric_unit, "experiment-specification")["metrics"][0]["unit"] = (
        "missing-unit"
    )
    mutations.append(unknown_metric_unit)

    invalid_default = deepcopy(pristine)
    member(invalid_default, "defaults")["symbol_values"][0]["value"] = 101
    mutations.append(invalid_default)

    unbound_dependency = deepcopy(pristine)
    member(unbound_dependency, "declared-package-dependencies")["packages"][0][
        "content_identity"
    ] = "sha256:" + "f" * 64
    mutations.append(unbound_dependency)

    for release in mutations:
        descriptor = replace(
            TEMPLATE_GET,
            handler=template_get_handler(
                lambda release=_reidentify_release(release): release
            ),
        )
        exit_code, stdout, stderr = run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ],
            registry=(descriptor,),
        )
        assert (exit_code, stderr) == (2, "")
        assert json.loads(stdout)["error"]["diagnostics"][0]["code"] in {
            "language.source_contract_mismatch",
            "language.package_version_unavailable",
        }


def test_template_instantiate_publishes_a_new_editable_model_source_identity(
    tmp_path, run_cli
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    starter = next(
        item["payload"]
        for item in release["members"]
        if item["logical_name"] == "starter-model-source"
    )
    starter_identity = content_identity("model-source-package-v2", starter)
    out = tmp_path / "my-quantity.json"

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.my-quantity",
            "--out",
            str(out),
            "--invocation-key",
            "1" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    assert receipt["artifact_kind"] == "artifact-set-receipt"
    assert [item["logical_name"] for item in receipt["member_locators"]] == [
        "model-source-package",
        "template-instantiation-receipt",
    ]
    source = json.loads(out.read_text(encoding="utf-8"))
    assert source["manifest"]["id"] == "example.my-quantity"
    assert source["manifest"]["template_provenance"] == {
        "template_id": release["id"],
        "template_version": release["version"],
        "template_identity": release["content_identity"],
        "starter_identity": starter_identity,
    }
    source_identity = content_identity("model-source-package-v2", source)
    assert source_identity != starter_identity
    instantiation_locator = next(
        item["locator"]
        for item in receipt["member_locators"]
        if item["logical_name"] == "template-instantiation-receipt"
    )
    instantiation_receipt = json.loads(
        Path(instantiation_locator).read_text(encoding="utf-8")
    )
    assert {
        key: instantiation_receipt[key]
        for key in (
            "template_identity",
            "starter_identity",
            "model_source_identity",
            "package_id",
            "kernel_identity",
            "language_bundle_identity",
        )
    } == {
        "template_identity": release["content_identity"],
        "starter_identity": starter_identity,
        "model_source_identity": source_identity,
        "package_id": "example.my-quantity",
        "kernel_identity": release["kernel_identity"],
        "language_bundle_identity": release["language_bundle_identity"],
    }
    assert run_cli(["model", "check", str(out)])[0] == 0

    unchanged_release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    assert (
        next(
            item["payload"]
            for item in unchanged_release["members"]
            if item["logical_name"] == "starter-model-source"
        )
        == starter
    )


def test_instantiated_source_can_be_edited_and_built_without_a_toolkit_fork(
    tmp_path, run_cli
):
    source_path = tmp_path / "editable.json"
    assert (
        run_cli(
            [
                "template",
                "instantiate",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
                "--package-id",
                "example.edited-quantity",
                "--out",
                str(source_path),
                "--invocation-key",
                "2" * 64,
            ]
        )[0]
        == 0
    )
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["modules"][0]["symbols"][0]["domain"]["maximum"] = 250
    source_path.write_text(json.dumps(source), encoding="utf-8")
    resolved_path = tmp_path / "resolved.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source_path),
            "--out",
            str(resolved_path),
            "--invocation-key",
            "3" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["artifact_kind"] == "artifact-set-receipt"
    assert json.loads(resolved_path.read_text())["artifact_kind"] == ("resolved-model")


def test_template_instantiation_is_atomic_retry_safe_and_input_bound(tmp_path, run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    invocation_key = "4" * 64
    base = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        "example.retry-safe",
        "--invocation-key",
        invocation_key,
    ]
    failed_out = tmp_path / "failed.json"
    faulting = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(
            lambda: release,
            publication_fault="before-anchor-commit",
        ),
    )

    exit_code, stdout, stderr = run_cli(
        [*base, "--out", str(failed_out)],
        registry=(faulting,),
    )

    assert exit_code == 4
    assert stdout == ""
    assert json.loads(stderr)["error"]["category"] == "internal"
    assert not failed_out.exists()

    first_out = tmp_path / "first.json"
    first = run_cli([*base, "--out", str(first_out)])
    assert (first[0], first[2]) == (0, "")
    second_out = tmp_path / "second.json"
    second = run_cli([*base, "--out", str(second_out)])
    assert (second[0], second[2]) == (0, "")
    assert json.loads(first[1]) == json.loads(second[1])
    assert first_out.read_bytes() == second_out.read_bytes()

    conflict_out = tmp_path / "conflict.json"
    conflict = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.different-input",
            "--out",
            str(conflict_out),
            "--invocation-key",
            invocation_key,
        ]
    )
    assert (conflict[0], conflict[1]) == (3, "")
    assert json.loads(conflict[2])["error"]["code"] == ("invocation_key_conflict")
    assert not conflict_out.exists()


@pytest.mark.parametrize(
    "publication_fault",
    (
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
        "after-commit",
    ),
)
def test_every_template_publication_fault_is_all_or_nothing_and_retryable(
    publication_fault, tmp_path, run_cli
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    invocation_key = {
        "after-member-write": "5",
        "before-commit": "6",
        "before-anchor-commit": "7",
        "after-commit": "8",
    }[publication_fault] * 64
    argv = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        f"example.{publication_fault}",
        "--out",
        str(tmp_path / "failed.json"),
        "--invocation-key",
        invocation_key,
    ]
    faulting = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(
            lambda: release,
            publication_fault=publication_fault,
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not (tmp_path / "failed.json").exists()
    invocation_matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "invocations").glob(
            f"*/{invocation_key}"
        )
    )
    anchor_matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors").glob(
            f"*/{invocation_key}.json"
        )
    )
    if publication_fault == "after-commit":
        assert len(invocation_matches) == len(anchor_matches) == 1
    else:
        assert invocation_matches == []
        assert anchor_matches == []

    recovered_out = tmp_path / "recovered.json"
    recovered = run_cli(
        [
            *argv[:-4],
            "--out",
            str(recovered_out),
            "--invocation-key",
            invocation_key,
        ]
    )
    assert (recovered[0], recovered[2]) == (0, "")
    assert recovered_out.is_file()


def test_template_publication_rejects_output_symlinks(tmp_path, run_cli):
    target = tmp_path / "target.json"
    target.write_text("unchanged", encoding="utf-8")
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.alias",
            "--out",
            str(alias),
            "--invocation-key",
            "9" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_template_recovery_rejects_a_coherently_reidentified_anchor_rewrite(
    tmp_path, run_cli
):
    invocation_key = "a" * 64
    argv = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        "example.anchor-rewrite",
        "--out",
        str(tmp_path / "first.json"),
        "--invocation-key",
        invocation_key,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    invocation = _template_invocation_directory(invocation_key)
    index_path = invocation / "publication-index.json"
    index = json.loads(index_path.read_text())
    index["command_input_identity"] = "sha256:" + "f" * 64
    index["content_identity"] = content_identity(
        "publication-index-v2",
        {key: value for key, value in index.items() if key != "content_identity"},
    )
    index_path.write_bytes(canonical_bytes(index))
    anchor_path = _template_anchor_path(invocation_key)
    anchor = json.loads(anchor_path.read_text())
    anchor["publication_index"] = index
    anchor_path.unlink()
    anchor_path.write_bytes(canonical_bytes(anchor))
    anchor_path.chmod(0o444)
    (tmp_path / "first.json").unlink()

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


def test_template_recovery_rejects_a_symlinked_committed_member(tmp_path, run_cli):
    invocation_key = "b" * 64
    argv = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        "example.member-alias",
        "--out",
        str(tmp_path / "first.json"),
        "--invocation-key",
        invocation_key,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    invocation = _template_invocation_directory(invocation_key)
    member = invocation / "model-source-package.json"
    preserved = tmp_path / "preserved-member.json"
    preserved.write_bytes(member.read_bytes())
    member.unlink()
    member.symlink_to(preserved)
    (tmp_path / "first.json").unlink()

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"


def test_concurrent_template_retries_recover_one_committed_set(tmp_path, run_cli):
    invocation_key = "c" * 64
    barrier = threading.Barrier(2)

    def instantiate(name):
        barrier.wait(timeout=10)
        return run_cli(
            [
                "template",
                "instantiate",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
                "--package-id",
                "example.concurrent",
                "--out",
                str(tmp_path / f"{name}.json"),
                "--invocation-key",
                invocation_key,
            ]
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(instantiate, "first")
        second = executor.submit(instantiate, "second")
        first_result = first.result(timeout=20)
        second_result = second.result(timeout=20)

    assert (first_result[0], first_result[2]) == (0, "")
    assert (second_result[0], second_result[2]) == (0, "")
    assert json.loads(first_result[1]) == json.loads(second_result[1])
    assert (tmp_path / "first.json").read_bytes() == (
        tmp_path / "second.json"
    ).read_bytes()
    assert _template_anchor_path(invocation_key).is_file()
