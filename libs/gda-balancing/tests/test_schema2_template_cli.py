"""Public Template release and instantiation tracer for Standard Schema 2.0 (#553)."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import jsonschema
from gda_balancing.commands.template import (
    TEMPLATE_GET,
    TEMPLATE_INSTANTIATE,
    template_get_handler,
    template_instantiate_handler,
)
from gda_balancing.schema2.canonical import content_identity


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
                    "sha256:44cadc6a5659007bbce23220a986ba0bfdc2c3157285eb26c9ca20bc2246cc2c"
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
    known_operations = {item["id"] for item in language["operations"]}
    assert set(coverage["operations"]) <= known_operations
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
