"""Public Model compiler tracer for Standard Schema 2.0 (#539)."""

import hashlib
import hmac
import json
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import gda_balancing.commands.model as model_command_module
import gda_balancing.schema2.model as model_module
import jsonschema
import pytest
from gda_balancing.schema2.bootstrap import admit_authorities
from gda_balancing.schema2.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.schema2.authority_graph import (
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.schema2.surface import descriptor_identity


def _quantity_symbol(name: str, role: str) -> dict[str, Any]:
    return {
        "symbol": name,
        "type": "quantity",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": 0, "maximum": 100},
        "numeric_policy": "exact-int64",
    }


def _model_source() -> dict[str, Any]:
    roles = (
        "constant",
        "parameter",
        "input",
        "state",
        "derived",
        "output",
        "random",
    )
    return {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "example.quantity-model",
            "version": "1.0.0",
            "entry_module": "main",
        },
        "package_requirements": [{"id": "core.quantity", "version": "2.0.0"}],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.0.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": [_quantity_symbol(f"{role}_value", role) for role in roles],
            }
        ],
    }


def _symbols(source: dict[str, Any]) -> list[dict[str, Any]]:
    return source["modules"][0]["symbols"]


def _artifact_directory(receipt: dict[str, Any]):
    return Path(receipt["manifest_locator"]).parent


def _invocation_directory(_parent, invocation_key: str):
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "invocations").glob(
            f"*/{invocation_key}"
        )
    )
    assert len(matches) == 1
    return matches[0]


def _anchor_path(invocation_key: str) -> Path:
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors").glob(
            f"*/{invocation_key}.json"
        )
    )
    assert len(matches) == 1
    return matches[0]


def test_model_check_accepts_all_quantity_roles_without_publishing(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    before = set(tmp_path.iterdir())

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result == {
        "checked": True,
        "kernel_identity": result["kernel_identity"],
        "language_bundle_identity": result["language_bundle_identity"],
    }
    assert result["kernel_identity"].startswith("sha256:")
    assert result["language_bundle_identity"].startswith("sha256:")
    assert set(tmp_path.iterdir()) == before


def test_model_check_resolves_capabilities_from_transitive_package_dependencies(
    tmp_path, run_cli
):
    source_document = _model_source()
    source_document["package_requirements"].append(
        {"id": "game.combat", "version": "1.0.0"}
    )
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["checked"] is True


def test_in_memory_model_check_reuses_only_a_matching_authority_admission():
    kernel, language_bundle = model_module.load_authorities()
    admission = admit_authorities(kernel, language_bundle)

    checked = model_module.check_model_source_value(
        _model_source(),
        kernel=kernel,
        language_bundle=language_bundle,
        authority_admission=admission,
    )

    assert isinstance(checked, model_module.CheckedModel)
    mismatched_ldb = deepcopy(language_bundle)
    mismatched_ldb["content_identity"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="another Kernel/LDB pair"):
        model_module.check_model_source_value(
            _model_source(),
            kernel=kernel,
            language_bundle=mismatched_ldb,
            authority_admission=admission,
        )


def test_model_check_runs_the_same_lowering_and_admission_front_end(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    calls = 0
    real_lowerer = model_module.lower_checked_model

    def observed_lowerer(checked):
        nonlocal calls
        calls += 1
        return real_lowerer(checked)

    monkeypatch.setattr(model_command_module, "lower_checked_model", observed_lowerer)

    assert run_cli(["model", "check", str(source)])[0] == 0
    assert calls == 1
    assert set(tmp_path.iterdir()) == {source}


def test_model_check_refuses_an_inverted_quantity_support_interval(tmp_path, run_cli):
    source_document = _model_source()
    _symbols(source_document)[0]["domain"] = {"minimum": 2, "maximum": 1}
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.invalid_domain"
    ]


def test_model_check_reports_all_static_diagnostics_in_canonical_location_order(
    tmp_path, run_cli
):
    source_document = _model_source()
    _symbols(source_document)[0]["kind"] = "unknown-kind"
    _symbols(source_document)[1]["unit"] = "unknown-unit"
    _symbols(source_document)[2]["domain"] = {"minimum": 2, "maximum": 1}
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    ] == [
        ("/modules/0/symbols/0/kind", "language.unknown_kind"),
        ("/modules/0/symbols/1/unit", "language.unknown_unit"),
        ("/modules/0/symbols/2/domain", "language.invalid_domain"),
    ]
    assert error["truncated"] is False


def test_model_check_applies_the_ldb_diagnostic_cap_and_marks_truncation(
    tmp_path, run_cli, monkeypatch
):
    source_document = _model_source()
    for symbol in _symbols(source_document)[:3]:
        symbol["kind"] = "unknown-kind"
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")
    kernel, language_bundle = model_module.load_authorities()
    candidate_ldb = deepcopy(language_bundle)
    candidate_ldb["resources"]["max_diagnostics"] = 2
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert [item["primary"]["pointer"] for item in error["diagnostics"]] == [
        "/modules/0/symbols/0/kind",
        "/modules/0/symbols/1/kind",
    ]
    assert error["truncated"] is True


def test_symbol_uniqueness_is_scoped_to_each_module_and_locates_the_duplicate(
    tmp_path, run_cli
):
    across_modules = _model_source()
    second_module = deepcopy(across_modules["modules"][0])
    second_module["id"] = "secondary"
    across_modules["modules"].append(second_module)
    accepted = tmp_path / "accepted.json"
    accepted.write_text(json.dumps(across_modules), encoding="utf-8")

    assert run_cli(["model", "check", str(accepted)])[0] == 0

    within_module = _model_source()
    _symbols(within_module).append(deepcopy(_symbols(within_module)[0]))
    refused = tmp_path / "refused.json"
    refused.write_text(json.dumps(within_module), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(refused)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert len(error["diagnostics"]) == 1
    diagnostic = error["diagnostics"][0]
    assert diagnostic["code"] == "language.duplicate_symbol"
    assert diagnostic["primary"]["pointer"] == "/modules/0/symbols/7/symbol"
    assert [item["pointer"] for item in diagnostic["related"]] == [
        "/modules/0/symbols/0/symbol"
    ]


def test_model_check_refuses_a_source_without_a_selected_domain_package(
    tmp_path, run_cli
):
    source_document = _model_source()
    source_document["package_requirements"] = []
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert {
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    } == {
        (
            "/package_requirements",
            "language.source_contract_mismatch",
        ),
        (
            "/modules/0/imports/0/package",
            "language.unresolved_name",
        ),
    }


def test_model_check_classifies_an_unavailable_exact_package_as_resolution(
    tmp_path, run_cli
):
    source_document = _model_source()
    source_document["package_requirements"][0]["version"] = "9.0.0"
    source_document["modules"][0]["imports"][0]["version"] = "9.0.0"
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert [
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    ] == [
        (
            "/package_requirements/0/version",
            "language.package_version_unavailable",
        )
    ]
    assert error["truncated"] is False


def test_model_check_classifies_name_legality_as_static(tmp_path, run_cli):
    duplicate_alias = _model_source()
    duplicate_alias["modules"][0]["imports"].append(
        deepcopy(duplicate_alias["modules"][0]["imports"][0])
    )
    duplicate_path = tmp_path / "duplicate-alias.json"
    duplicate_path.write_text(json.dumps(duplicate_alias), encoding="utf-8")

    unresolved_name = _model_source()
    unresolved_name["modules"][0]["symbols"][0]["type"] = "missing"
    unresolved_path = tmp_path / "unresolved-name.json"
    unresolved_path.write_text(json.dumps(unresolved_name), encoding="utf-8")

    duplicate = run_cli(["model", "check", str(duplicate_path)])
    unresolved = run_cli(["model", "check", str(unresolved_path)])

    assert duplicate[0] == unresolved[0] == 2
    duplicate_error = json.loads(duplicate[1])["error"]
    unresolved_error = json.loads(unresolved[1])["error"]
    assert duplicate_error["stage"] == "static"
    assert duplicate_error["diagnostics"][0]["code"] == "language.name_ambiguity"
    assert duplicate_error["diagnostics"][0]["primary"]["pointer"] == (
        "/modules/0/imports/1/alias"
    )
    assert unresolved_error["stage"] == "static"
    assert unresolved_error["diagnostics"][0]["code"] == "language.unresolved_name"
    assert unresolved_error["diagnostics"][0]["primary"]["pointer"] == (
        "/modules/0/symbols/0/type"
    )


def test_model_check_reports_structural_members_at_the_exact_artifact_pointer(
    tmp_path, run_cli
):
    source_document = _model_source()
    del source_document["modules"][0]["symbols"][0]["unit"]
    source_document["modules"][0]["symbols"][1]["unexpected"] = True
    source = tmp_path / "structural-errors.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [
        (item["primary"]["kind"], item["primary"]["pointer"], item["code"])
        for item in error["diagnostics"]
    ] == [
        (
            "artifact",
            "/modules/0/symbols/0/unit",
            "language.source_contract_mismatch",
        ),
        (
            "artifact",
            "/modules/0/symbols/1/unexpected",
            "language.source_contract_mismatch",
        ),
    ]


def test_model_check_gates_resolution_when_required_top_level_members_are_missing(
    tmp_path, run_cli
):
    source = tmp_path / "structurally-incomplete.json"
    source.write_text('{"schema_version":"2.0.0"}', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert {
        (item["primary"]["pointer"], item["code"]) for item in error["diagnostics"]
    } == {
        ("/manifest", "language.source_contract_mismatch"),
        ("/package_requirements", "language.source_contract_mismatch"),
        ("/modules", "language.source_contract_mismatch"),
    }


def test_model_check_reports_source_size_at_ingress(tmp_path, run_cli):
    source = tmp_path / "oversized-source.json"
    source.write_bytes(b" " * (1024 * 1024 + 1))

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "ingress"
    assert error["diagnostics"][0]["code"] == "language.source_too_large"


def test_model_check_reports_wire_decode_failure_at_parse(tmp_path, run_cli):
    source = tmp_path / "malformed-source.json"
    source.write_text('{"schema_version":"2.0.0",', encoding="utf-8")

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "parse"
    assert error["diagnostics"][0]["code"] == "language.source_parse_failure"


@pytest.mark.parametrize("anchor_key", [None, "A5" * 32, "a5" * 31, "not-hex"])
def test_model_build_rejects_invalid_anchor_authentication_configuration_before_publication(
    tmp_path, run_cli, monkeypatch, anchor_key
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    store = tmp_path / "store"
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store))
    if anchor_key is None:
        monkeypatch.delenv("GDA_BALANCING_ANCHOR_KEY", raising=False)
    else:
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", anchor_key)

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    error = json.loads(stderr)["error"]
    assert error == {
        "category": "usage",
        "code": "invalid_argument",
        "message": (
            "GDA_BALANCING_ANCHOR_KEY must contain exactly 64 lowercase "
            "hexadecimal digits"
        ),
    }
    assert not out.exists()
    assert not store.exists()


def test_model_build_validates_anchor_configuration_before_reading_source(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "missing-model-source.json"
    out = tmp_path / "published-model"
    monkeypatch.delenv("GDA_BALANCING_ANCHOR_KEY", raising=False)

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invalid_argument"
    assert not out.exists()


def test_model_build_atomically_publishes_a_framed_typed_artifact_set(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    invocation_key = "a" * 64

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            invocation_key,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    assert receipt["artifact_kind"] == "artifact-set-receipt"
    assert receipt["invocation_key"] == invocation_key
    artifact_dir = _artifact_directory(receipt)
    assert receipt["manifest_locator"] == str(
        artifact_dir / "artifact-set-manifest.json"
    )
    assert receipt["member_locators"] == [
        {
            "logical_name": name,
            "locator": str(artifact_dir / f"{name}.json"),
        }
        for name in (
            "build-receipt",
            "capability-manifest",
            "debug-map",
            "package-lock",
            "resolution-receipt",
            "resolved-model",
            "rir-semantic-payload",
        )
    ]
    assert out.is_file()
    assert json.loads(out.read_text())["artifact_kind"] == "resolved-model"
    assert receipt["content_identity"] == content_identity(
        "artifact-set-receipt-v2",
        {
            key: value
            for key, value in receipt.items()
            if key
            not in {
                "content_identity",
                "manifest_locator",
                "member_locators",
            }
        },
    )

    manifest = json.loads((artifact_dir / "artifact-set-manifest.json").read_text())
    assert manifest["artifact_kind"] == "artifact-set-manifest"
    assert [item["logical_name"] for item in manifest["members"]] == [
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    ]
    for member in manifest["members"]:
        assert member["artifact_kind"]
        assert member["wire_schema_identity"].startswith("sha256:")
        path = artifact_dir / f"{member['logical_name']}.json"
        artifact = json.loads(path.read_text())
        assert artifact["content_identity"] == member["content_identity"]
        assert "locator" not in member

    assert (
        json.loads((artifact_dir / "artifact-set-receipt.json").read_text()) == receipt
    )
    assert (artifact_dir / "publication-index.json").is_file()
    assert sorted(path.name for path in artifact_dir.iterdir()) == [
        "artifact-set-manifest.json",
        "artifact-set-receipt.json",
        "build-receipt.json",
        "capability-manifest.json",
        "debug-map.json",
        "package-lock.json",
        "publication-index.json",
        "resolution-receipt.json",
        "resolved-model.json",
        "rir-semantic-payload.json",
    ]

    schema_exit, schema_stdout, schema_stderr = run_cli(
        ["schema", "get", "wire-schema"]
    )
    assert (schema_exit, schema_stderr) == (0, "")
    schemas = {
        item["artifact_kind"]: item["schema"]
        for item in json.loads(schema_stdout)["schemas"]
    }
    for member in manifest["members"]:
        schema = schemas[member["artifact_kind"]]
        schema_identity = "sha256:" + schema["$id"].rsplit(":", 1)[-1]
        assert member["wire_schema_identity"] == schema_identity
        jsonschema.validate(
            json.loads((artifact_dir / f"{member['logical_name']}.json").read_text()),
            schema,
        )
    surface = json.loads(run_cli(["manifest"])[1])
    model_build = next(
        row
        for row in surface["commands"]
        if row["group"] == "model" and row["command"] == "build"
    )
    assert model_build["artifact_set"] == [
        {
            "logical_name": item["logical_name"],
            "artifact_kind": item["artifact_kind"],
            "role": (
                "primary" if item["logical_name"] == "resolved-model" else "companion"
            ),
        }
        for item in manifest["members"]
    ]


def test_model_build_descriptor_declares_exactly_one_primary_artifact():
    members = model_command_module.MODEL_BUILD.artifact_set
    assert [member.logical_name for member in members if member.role == "primary"] == [
        "resolved-model"
    ]

    without_primary = tuple(replace(member, role="companion") for member in members)
    with pytest.raises(ValueError, match="exactly one primary"):
        replace(model_command_module.MODEL_BUILD, artifact_set=without_primary)

    multiple_primary = tuple(
        replace(
            member,
            role=(
                "primary"
                if member.logical_name in {"package-lock", "resolved-model"}
                else "companion"
            ),
        )
        for member in members
    )
    with pytest.raises(ValueError, match="exactly one primary"):
        replace(model_command_module.MODEL_BUILD, artifact_set=multiple_primary)


def test_model_publisher_materializes_the_descriptor_declared_primary_member(
    tmp_path, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
    artifact_set = tuple(
        replace(
            member,
            role=("primary" if member.logical_name == "package-lock" else "companion"),
        )
        for member in model_command_module.MODEL_BUILD.artifact_set
    )
    out = tmp_path / "primary.json"

    model_module.publish_model_artifacts(
        checked,
        str(source),
        str(out),
        "b" * 64,
        "sha256:" + "b" * 64,
        artifact_set,
    )

    assert json.loads(out.read_text())["artifact_kind"] == "package-lock"


def test_artifact_set_manifest_identity_is_independent_of_store_and_invocation(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    manifests = []
    receipts = []

    for index in (1, 2):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / f"store-{index}"))
        built = run_cli(
            [
                "model",
                "build",
                str(source),
                "--out",
                str(tmp_path / f"published-{index}.json"),
                "--invocation-key",
                str(index) * 64,
            ]
        )
        assert built[0] == 0
        receipt = json.loads(built[1])
        receipts.append(receipt)
        manifests.append(
            json.loads(
                (
                    _artifact_directory(receipt) / "artifact-set-manifest.json"
                ).read_text()
            )
        )

    assert manifests[0]["members"] == manifests[1]["members"]
    assert manifests[0]["content_identity"] == manifests[1]["content_identity"]
    assert canonical_bytes(manifests[0]) == canonical_bytes(manifests[1])
    assert receipts[0]["member_locators"] != receipts[1]["member_locators"]


def test_model_build_retry_recovers_without_running_the_lowerer(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "b" * 64,
    ]
    first = run_cli(argv)
    assert first[0] == 0

    def lowerer_must_not_run(_checked):
        raise AssertionError("retry executed the lowerer")

    monkeypatch.setattr(model_module, "lower_checked_model", lowerer_must_not_run)
    second = run_cli(argv)

    assert second == first


def test_model_build_retry_can_select_a_new_presentation_without_reexecution(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    first_out = tmp_path / "first.json"
    second_out = tmp_path / "second.json"
    key = "5" * 64
    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(first_out),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0

    def lowerer_must_not_run(_checked):
        raise AssertionError("retry executed the lowerer")

    monkeypatch.setattr(model_module, "lower_checked_model", lowerer_must_not_run)
    second = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(second_out),
            "--invocation-key",
            key,
        ]
    )

    assert second == first
    assert first_out.read_bytes() == second_out.read_bytes()
    assert json.loads(second_out.read_text())["artifact_kind"] == "resolved-model"


def test_model_build_retry_rejects_output_aliases_to_every_committed_publication_file(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    key = "9" * 64
    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "published-model.json"),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    committed = sorted(artifact_dir.iterdir())
    before = {path.name: path.read_bytes() for path in committed}

    for member in committed:
        for alias_kind, out in (
            ("direct", member),
            ("symlink", tmp_path / f"{member.stem}-alias.json"),
        ):
            if alias_kind == "symlink":
                out.symlink_to(member)

            exit_code, stdout, stderr = run_cli(
                [
                    "model",
                    "build",
                    str(source),
                    "--out",
                    str(out),
                    "--invocation-key",
                    key,
                ]
            )

            assert (exit_code, stdout) == (3, "")
            assert json.loads(stderr)["error"]["code"] == "argument_conflict"
            assert {path.name: path.read_bytes() for path in committed} == before
            if alias_kind == "symlink":
                out.unlink()


def test_model_commands_share_the_descriptor_owned_structured_input(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    assert run_cli(
        [
            "model",
            "check",
            "--params-json",
            json.dumps({"source": str(source)}),
        ]
    ) == run_cli(["model", "check", str(source)])

    out = tmp_path / "published-model"
    params = {
        "source": str(source),
        "out": str(out),
        "invocation_key": "b" * 64,
    }
    direct = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "b" * 64,
        ]
    )
    structured = run_cli(["model", "build", "--params-json", json.dumps(params)])
    assert structured == direct


def test_model_build_rejects_invocation_key_reuse_for_changed_input(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    key = "c" * 64
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        key,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    before = {path.name: path.read_bytes() for path in artifact_dir.iterdir()}
    changed = _model_source()
    _symbols(changed)[0]["domain"]["maximum"] = 101
    source.write_text(json.dumps(changed), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invocation_key_conflict"
    assert {path.name: path.read_bytes() for path in artifact_dir.iterdir()} == before


def test_model_build_rejects_changed_input_for_the_same_store_invocation_key_even_when_out_changes(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    key = "8" * 64
    first_parent = tmp_path / "first-store-presentation"
    second_parent = tmp_path / "second-store-presentation"
    first_parent.mkdir()
    second_parent.mkdir()

    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(first_parent / "model.json"),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0
    changed = _model_source()
    _symbols(changed)[0]["domain"]["maximum"] = 101
    source.write_text(json.dumps(changed), encoding="utf-8")

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(second_parent / "model.json"),
            "--invocation-key",
            key,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invocation_key_conflict"


def test_model_build_rejects_invocation_key_reuse_after_exact_authority_changes(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    key = "a" * 64
    first = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "first.json"),
            "--invocation-key",
            key,
        ]
    )
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    before = {path.name: path.read_bytes() for path in artifact_dir.iterdir()}

    kernel, language_bundle = model_module.load_authorities()
    candidate_ldb = deepcopy(language_bundle)
    candidate_ldb["resources"]["max_diagnostics"] -= 1
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "second.json"),
            "--invocation-key",
            key,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "invocation_key_conflict"
    assert {path.name: path.read_bytes() for path in artifact_dir.iterdir()} == before
    assert not (tmp_path / "second.json").exists()


def test_model_build_rejects_direct_and_symlink_input_output_aliases(tmp_path, run_cli):
    for suffix, out_factory in (
        ("direct", lambda source: source),
        ("symlink", lambda source: tmp_path / "source-alias.json"),
    ):
        source = tmp_path / f"model-source-{suffix}.json"
        source.write_text(json.dumps(_model_source()), encoding="utf-8")
        before = source.read_bytes()
        out = out_factory(source)
        if suffix == "symlink":
            out.symlink_to(source)

        exit_code, stdout, stderr = run_cli(
            [
                "model",
                "build",
                str(source),
                "--out",
                str(out),
                "--invocation-key",
                ("d" if suffix == "direct" else "e") * 64,
            ]
        )

        assert (exit_code, stdout) == (3, "")
        assert json.loads(stderr)["error"]["code"] == "argument_conflict"
        assert source.read_bytes() == before


def test_model_publisher_rejects_a_known_source_alias_after_the_source_disappears(
    tmp_path, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    source.unlink()
    store = tmp_path / "store"
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store))

    with pytest.raises(model_module.UsageError) as caught:
        model_module.publish_model_artifacts(
            checked,
            str(source),
            str(source),
            "e" * 64,
            descriptor_identity(model_command_module.MODEL_BUILD),
            model_command_module.MODEL_BUILD.artifact_set,
        )

    assert caught.value.code == "argument_conflict"
    assert not source.exists()
    assert not store.exists()


def test_model_build_rejects_a_symlinked_store_ancestor(tmp_path, run_cli, monkeypatch):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    real_store_parent = tmp_path / "real-store-parent"
    real_store_parent.mkdir()
    store_alias = tmp_path / "store-alias"
    store_alias.symlink_to(real_store_parent, target_is_directory=True)
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store_alias / "schema2-store"))
    out = tmp_path / "published-model.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"
    assert not out.exists()


def test_model_build_rejects_every_output_overlap_with_the_reserved_invocation_path(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    store = tmp_path / "store"
    monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(store))
    key = "f" * 64
    descriptor_key = descriptor_identity(model_command_module.MODEL_BUILD).removeprefix(
        "sha256:"
    )
    invocation_path = store / "invocations" / descriptor_key / key
    invocation_path.parent.mkdir(parents=True)

    for out in (
        store,
        store / "invocations",
        invocation_path.parent,
        invocation_path,
        invocation_path / "resolved-model.json",
    ):
        exit_code, stdout, stderr = run_cli(
            [
                "model",
                "build",
                str(source),
                "--out",
                str(out),
                "--invocation-key",
                key,
            ]
        )

        assert (exit_code, stdout) == (3, "")
        assert json.loads(stderr)["error"]["code"] == "argument_conflict"
        assert not invocation_path.exists()


def test_model_build_precommit_fault_leaves_no_visible_or_partial_set(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    descriptor = replace(
        model_command_module.MODEL_BUILD,
        handler=model_command_module.model_build_handler(
            publication_fault="after-member-write"
        ),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "f" * 64,
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not out.exists()
    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    assert not (store / "invocations").exists()
    assert not (store / "anchors").exists()


def test_model_build_postcommit_fault_is_recoverable_by_invocation_key(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "0" * 64,
    ]
    faulting = replace(
        model_command_module.MODEL_BUILD,
        handler=model_command_module.model_build_handler(
            publication_fault="after-commit"
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    artifact_dir = _invocation_directory(tmp_path, "0" * 64)
    assert (artifact_dir / "publication-index.json").is_file()
    assert not out.exists()

    recovered_exit, recovered_stdout, recovered_stderr = run_cli(
        argv, registry=(model_command_module.MODEL_BUILD,)
    )
    assert (recovered_exit, recovered_stderr) == (0, "")
    assert json.loads(recovered_stdout)["invocation_key"] == "0" * 64


def test_model_build_before_anchor_commit_fault_has_no_visible_anchor_and_recovers(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "8" * 64,
    ]
    faulting = replace(
        model_command_module.MODEL_BUILD,
        handler=model_command_module.model_build_handler(
            publication_fault="before-anchor-commit"
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    anchors = Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors"
    assert not anchors.exists() or not list(anchors.rglob("*.json"))
    assert not out.exists()

    recovered_exit, recovered_stdout, recovered_stderr = run_cli(argv)
    assert (recovered_exit, recovered_stderr) == (0, "")
    assert json.loads(recovered_stdout)["invocation_key"] == "8" * 64


def test_publication_anchor_is_authenticated_outside_the_writable_store(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "7" * 64,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    anchor_path = _anchor_path("7" * 64)
    anchor = json.loads(anchor_path.read_text())
    assert anchor["anchor_kind"] == "authenticated-publication-index-v1"
    assert anchor["algorithm"] == "hmac-sha256"
    expected = hmac.new(
        bytes.fromhex(os.environ["GDA_BALANCING_ANCHOR_KEY"]),
        canonical_bytes(anchor["publication_index"]),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(anchor["authentication"], expected)

    anchor["publication_index"]["receipt_identity"] = "sha256:" + "f" * 64
    anchor_path.unlink()
    anchor_path.write_bytes(canonical_bytes(anchor))
    anchor_path.chmod(0o444)
    out.unlink()

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


def test_publication_anchor_fsync_covers_read_only_mode(tmp_path, monkeypatch):
    path = tmp_path / "anchor.json"
    observed: list[tuple[str, int]] = []
    real_fchmod = os.fchmod
    real_fsync = os.fsync

    def record_fchmod(descriptor: int, mode: int) -> None:
        real_fchmod(descriptor, mode)
        observed.append(("fchmod", stat.S_IMODE(os.fstat(descriptor).st_mode)))

    def record_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        if stat.S_ISREG(mode):
            observed.append(("fsync", stat.S_IMODE(mode)))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fchmod", record_fchmod)
    monkeypatch.setattr(os, "fsync", record_fsync)

    model_module._write_anchor_exclusive(
        path,
        cast(
            dict[str, JsonValue],
            {"content_identity": "sha256:" + "1" * 64},
        ),
        bytes.fromhex(os.environ["GDA_BALANCING_ANCHOR_KEY"]),
    )

    assert observed == [("fchmod", 0o444), ("fsync", 0o444)]


def test_same_invocation_key_concurrent_writers_recover_one_committed_set(
    tmp_path, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    entered_anchor = threading.Event()
    release_anchor = threading.Event()
    second_started = threading.Event()
    real_write_anchor = model_module._write_anchor_exclusive
    calls = 0
    calls_guard = threading.Lock()

    def pause_first_anchor(path, artifact, authentication_key, **kwargs):
        nonlocal calls
        with calls_guard:
            calls += 1
            current = calls
        if current == 1:
            entered_anchor.set()
            assert release_anchor.wait(timeout=10)
        return real_write_anchor(path, artifact, authentication_key, **kwargs)

    monkeypatch.setattr(model_module, "_write_anchor_exclusive", pause_first_anchor)
    key = "6" * 64
    descriptor = descriptor_identity(model_command_module.MODEL_BUILD)

    def publish(out: Path, *, announce: bool = False):
        if announce:
            second_started.set()
        return model_module.publish_model_artifacts(
            checked,
            str(source),
            str(out),
            key,
            descriptor,
            model_command_module.MODEL_BUILD.artifact_set,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(publish, tmp_path / "first.json")
        assert entered_anchor.wait(timeout=10)
        second = executor.submit(
            publish,
            tmp_path / "second.json",
            announce=True,
        )
        assert second_started.wait(timeout=10)
        time.sleep(0.05)
        release_anchor.set()
        first_receipt = first.result(timeout=10)
        second_receipt = second.result(timeout=10)

    assert first_receipt == second_receipt
    assert (tmp_path / "first.json").is_file()
    assert (tmp_path / "second.json").is_file()
    assert _anchor_path(key).is_file()


def test_publication_index_anchor_rejects_a_coherently_reidentified_rewrite(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    argv = [
        "model",
        "build",
        str(source),
        "--out",
        str(out),
        "--invocation-key",
        "9" * 64,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    artifact_dir = _artifact_directory(json.loads(first[1]))
    anchor = _anchor_path("9" * 64)
    anchor_before = anchor.read_bytes()
    assert anchor.stat().st_mode & 0o222 == 0

    rir = json.loads((artifact_dir / "rir-semantic-payload.json").read_text())
    rir["declarations"][0]["domain"]["maximum"] = 99
    _reidentify(rir, "rir-semantic-payload-v2")
    resolved = json.loads((artifact_dir / "resolved-model.json").read_text())
    resolved["rir_identity"] = rir["content_identity"]
    _reidentify(resolved, "resolved-model-v2")
    debug_map = json.loads((artifact_dir / "debug-map.json").read_text())
    debug_map["rir_identity"] = rir["content_identity"]
    _reidentify(debug_map, "debug-map-v2")
    capability_manifest = json.loads(
        (artifact_dir / "capability-manifest.json").read_text()
    )
    capability_manifest["rir_identity"] = rir["content_identity"]
    capability_manifest["resolved_model_identity"] = resolved["content_identity"]
    _reidentify(capability_manifest, "capability-manifest-v2")
    build_receipt = json.loads((artifact_dir / "build-receipt.json").read_text())
    build_receipt["rir_identity"] = rir["content_identity"]
    build_receipt["resolved_model_identity"] = resolved["content_identity"]
    build_receipt["debug_map_identity"] = debug_map["content_identity"]
    build_receipt["capability_manifest_identity"] = capability_manifest[
        "content_identity"
    ]
    _reidentify(build_receipt, "build-receipt-v2")
    for name, artifact in (
        ("rir-semantic-payload", rir),
        ("resolved-model", resolved),
        ("debug-map", debug_map),
        ("capability-manifest", capability_manifest),
        ("build-receipt", build_receipt),
    ):
        (artifact_dir / f"{name}.json").write_bytes(canonical_bytes(artifact))

    manifest = json.loads((artifact_dir / "artifact-set-manifest.json").read_text())
    replacements = {
        "rir-semantic-payload": rir["content_identity"],
        "resolved-model": resolved["content_identity"],
        "debug-map": debug_map["content_identity"],
        "capability-manifest": capability_manifest["content_identity"],
        "build-receipt": build_receipt["content_identity"],
    }
    for member in manifest["members"]:
        if member["logical_name"] in replacements:
            member["content_identity"] = replacements[member["logical_name"]]
    _reidentify(manifest, "artifact-set-manifest-v2")
    (artifact_dir / "artifact-set-manifest.json").write_bytes(canonical_bytes(manifest))
    receipt = json.loads((artifact_dir / "artifact-set-receipt.json").read_text())
    receipt["manifest_identity"] = manifest["content_identity"]
    _reidentify(receipt, "artifact-set-receipt-v2")
    (artifact_dir / "artifact-set-receipt.json").write_bytes(canonical_bytes(receipt))
    index = json.loads((artifact_dir / "publication-index.json").read_text())
    index["receipt_identity"] = receipt["content_identity"]
    _reidentify(index, "publication-index-v2")
    (artifact_dir / "publication-index.json").write_bytes(canonical_bytes(index))
    forged_anchor = json.loads(anchor.read_text())
    forged_anchor["publication_index"] = index
    anchor.unlink()
    anchor.write_bytes(canonical_bytes(forged_anchor))
    anchor.chmod(0o444)
    out.unlink()
    assert anchor.read_bytes() != anchor_before

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


def test_receipt_content_identity_excludes_transport_locators():
    _, language_bundle = model_module.load_authorities()
    common = {
        "descriptor_identity": "sha256:" + "1" * 64,
        "invocation_key": "2" * 64,
        "manifest_identity": "sha256:" + "3" * 64,
    }
    first = model_module._identified_artifact(
        language_bundle,
        "artifact-set-receipt",
        {
            **common,
            "manifest_locator": "/store-a/manifest.json",
            "member_locators": [
                {"logical_name": "resolved-model", "locator": "/store-a/member.json"}
            ],
        },
    )
    second = model_module._identified_artifact(
        language_bundle,
        "artifact-set-receipt",
        {
            **common,
            "manifest_locator": "/store-b/manifest.json",
            "member_locators": [
                {"logical_name": "resolved-model", "locator": "/store-b/member.json"}
            ],
        },
    )

    assert first["content_identity"] == second["content_identity"]


def test_recovery_rejects_a_symlinked_committed_member(tmp_path, run_cli):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out_a = tmp_path / "published-a"
    out_b = tmp_path / "published-b"
    argv_a = [
        "model",
        "build",
        str(source),
        "--out",
        str(out_a),
        "--invocation-key",
        "6" * 64,
    ]
    argv_b = [
        "model",
        "build",
        str(source),
        "--out",
        str(out_b),
        "--invocation-key",
        "7" * 64,
    ]
    first_a = run_cli(argv_a)
    first_b = run_cli(argv_b)
    assert first_a[0] == 0
    assert first_b[0] == 0
    artifact_a = _artifact_directory(json.loads(first_a[1]))
    artifact_b = _artifact_directory(json.loads(first_b[1]))
    member = artifact_a / "package-lock.json"
    member.unlink()
    member.symlink_to(artifact_b / "package-lock.json")

    exit_code, stdout, stderr = run_cli(argv_a)

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"


def test_package_lock_closes_the_selected_semantic_graph_without_provenance(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"

    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "1" * 64,
        ]
    )
    assert built[0] == 0
    artifact_dir = _artifact_directory(json.loads(built[1]))

    lock = json.loads((artifact_dir / "package-lock.json").read_text())
    assert [(package["id"], package["version"]) for package in lock["packages"]] == [
        ("core.quantity", "2.0.0"),
        ("standard.compiler", "1.0.0"),
    ]
    assert all(
        set(package)
        == {
            "id",
            "version",
            "content_identity",
            "semantic_identity",
        }
        for package in lock["packages"]
    )
    assert lock["semantic_identity"].startswith("sha256:")
    assert lock["capability_bindings"]
    assert lock["types"]
    assert lock["components"]
    assert lock["conversions"]
    assert lock["operations"]
    assert lock["numeric_profiles"]
    assert lock["runtime_profiles"]
    assert "resolver" not in lock
    assert "compiler" not in lock

    resolution_receipt = json.loads(
        (artifact_dir / "resolution-receipt.json").read_text()
    )
    assert resolution_receipt["resolver"]
    assert resolution_receipt["kernel_identity"].startswith("sha256:")
    assert resolution_receipt["language_bundle_identity"].startswith("sha256:")
    assert resolution_receipt["diagnostics"] == []
    set_receipt = json.loads((artifact_dir / "artifact-set-receipt.json").read_text())
    assert {item["logical_name"] for item in set_receipt["member_locators"]} == {
        "build-receipt",
        "capability-manifest",
        "debug-map",
        "package-lock",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
    }
    rir = json.loads((artifact_dir / "rir-semantic-payload.json").read_text())
    assert all(
        declaration["type_identity"]
        == {
            "package": "core.quantity",
            "version": "2.0.0",
            "symbol": "Quantity",
        }
        for declaration in rir["declarations"]
    )
    assert all(
        declaration["resolved_symbol"]["model"] == "example.quantity-model"
        and declaration["resolved_symbol"]["module"] == "main"
        for declaration in rir["declarations"]
    )


def test_equivalent_source_orderings_share_lock_rir_and_resolved_model_identity(
    tmp_path, run_cli
):
    source_a = _model_source()
    source_b = _model_source()
    _symbols(source_b).reverse()
    outputs = []
    for index, source in enumerate((source_a, source_b), start=2):
        source_path = tmp_path / f"source-{index}.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        out = tmp_path / f"published-{index}"
        built = run_cli(
            [
                "model",
                "build",
                str(source_path),
                "--out",
                str(out),
                "--invocation-key",
                str(index) * 64,
            ]
        )
        assert built[0] == 0
        outputs.append(_artifact_directory(json.loads(built[1])))

    for name in (
        "package-lock.json",
        "rir-semantic-payload.json",
        "resolved-model.json",
    ):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
    assert (outputs[0] / "debug-map.json").read_bytes() != (
        outputs[1] / "debug-map.json"
    ).read_bytes()
    rir = json.loads((outputs[0] / "rir-semantic-payload.json").read_text())
    assert "source_identity" not in rir
    assert "compiler" not in rir
    assert "debug_map_identity" not in rir


def _published_semantic_artifacts(out) -> dict[str, dict]:
    return {
        name: json.loads((out / f"{name}.json").read_text())
        for name in (
            "package-lock",
            "rir-semantic-payload",
            "resolved-model",
        )
    }


def _reidentify(artifact: dict, domain: str) -> None:
    excluded = (
        {"manifest_locator", "member_locators"}
        if domain == "artifact-set-receipt-v2"
        else set()
    )
    artifact["content_identity"] = content_identity(
        domain,
        {
            key: value
            for key, value in artifact.items()
            if key != "content_identity" and key not in excluded
        },
    )


def _reidentify_language_bundle(language_bundle: dict[str, Any]) -> None:
    assert isinstance(language_bundle, LanguageBundleIndex)
    kernel, _ = model_module.load_authorities()
    projections = kernel["meta_format"]["package_release"]["semantic_closure"][
        "projections"
    ]

    def path_values(root: Any, dotted: str) -> list[Any]:
        values = [root]
        for segment in dotted.split("."):
            selected: list[Any] = []
            for value in values:
                if not isinstance(value, dict) or segment not in value:
                    continue
                child = value[segment]
                selected.extend(child if isinstance(child, list) else [child])
            values = selected
        return values

    for package in language_bundle["language"]["packages"]:
        package["vector_definitions"] = [
            deepcopy(
                next(
                    vector
                    for vector in language_bundle["vectors"]
                    if vector["id"] == vector_id
                )
            )
            for vector_id in package["vectors"]
        ]
        for entry, projection in zip(
            package["semantic_closure"], projections, strict=True
        ):
            definitions = path_values(language_bundle, entry["authority_path"])
            owners = path_values(package, projection["owners_path"])
            key_member = projection["key_member"]
            entry["definitions"] = deepcopy(
                [
                    definition
                    for definition in definitions
                    if (
                        definition.get(key_member)
                        if key_member is not None and isinstance(definition, dict)
                        else definition
                    )
                    in owners
                ]
            )
        runtime_paths = set(package["runtime_semantic_paths"])
        package["semantic_identity"] = content_identity(
            "domain-package-semantic-closure-v2",
            cast(
                JsonValue,
                [
                    entry
                    for entry in package["semantic_closure"]
                    if entry["authority_path"] in runtime_paths
                ],
            ),
        )
        _reidentify(package, "domain-package-release-v2")
    graph_root = getattr(language_bundle, "root", None)
    if isinstance(graph_root, dict):
        packages = deepcopy(language_bundle["language"]["packages"])
        packages.sort(key=lambda package: (package["id"], package["version"]))
        sizes = [len(canonical_bytes(cast(JsonValue, package))) for package in packages]
        graph_root["resources"] = deepcopy(language_bundle["resources"])
        graph_root["package_descriptors"] = [
            {
                "artifact_kind": package["artifact_kind"],
                "byte_size": size,
                "content_identity": package["content_identity"],
                "id": package["id"],
                "version": package["version"],
            }
            for package, size in zip(packages, sizes, strict=True)
        ]
        _reidentify(graph_root, "language-definition-bundle-v2")
        language_bundle.root = deepcopy(graph_root)
        language_bundle.package_releases = packages
        language_bundle.root_byte_size = len(
            canonical_bytes(cast(JsonValue, graph_root))
        )
        language_bundle.member_byte_sizes = tuple(sizes)
        rebuilt = derive_language_index(
            graph_root,
            packages,
            kernel["admission"]["required_language_members"],
            root_byte_size=language_bundle.root_byte_size,
            member_byte_sizes=sizes,
            descriptor_order=kernel["meta_format"]["language_bundle"][
                "package_descriptor"
            ]["canonical_order"],
        )
        language_bundle.root = deepcopy(rebuilt.root)
        language_bundle.package_releases = deepcopy(rebuilt.package_releases)
        language_bundle.root_byte_size = rebuilt.root_byte_size
        language_bundle.member_byte_sizes = rebuilt.member_byte_sizes
        language_bundle.clear()
        language_bundle.update(dict(rebuilt))
        return
    _reidentify(language_bundle, "language-definition-bundle-v2")


def test_resolved_model_admission_rejects_coherently_reidentified_authority_drift(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "3" * 64,
        ]
    )
    assert built[0] == 0
    original = _published_semantic_artifacts(_artifact_directory(json.loads(built[1])))
    assert model_module.admit_resolved_model(original).admitted is True

    def mutate_operation(artifacts):
        artifacts["package-lock"]["operations"][0]["definition"]["id"] = (
            "quantity.reidentified"
        )

    def mutate_diagnostic(artifacts):
        artifacts["package-lock"]["diagnostics"][0] = "language.reidentified"

    def mutate_profile(artifacts):
        artifacts["package-lock"]["runtime_profiles"][0]["id"] = "compile.reidentified"

    def mutate_reason(artifacts):
        artifacts["package-lock"]["diagnostic_reasons"][0]["id"] = (
            "quantity.reason.reidentified"
        )

    for mutate in (
        mutate_operation,
        mutate_diagnostic,
        mutate_profile,
        mutate_reason,
    ):
        artifacts = deepcopy(original)
        mutate(artifacts)
        _reidentify(artifacts["package-lock"], "package-lock-v2")
        artifacts["resolved-model"]["package_lock_identity"] = artifacts[
            "package-lock"
        ]["content_identity"]
        artifacts["resolved-model"]["rir_identity"] = artifacts["rir-semantic-payload"][
            "content_identity"
        ]
        _reidentify(artifacts["resolved-model"], "resolved-model-v2")

        admission = model_module.admit_resolved_model(artifacts)

        assert admission.admitted is False
        assert admission.diagnostics == ("language.resolved_authority_mismatch",)


def test_resolved_model_admission_rejects_coherently_reidentified_invalid_declarations(
    tmp_path, run_cli
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    out = tmp_path / "published-model"
    built = run_cli(
        [
            "model",
            "build",
            str(source),
            "--out",
            str(out),
            "--invocation-key",
            "4" * 64,
        ]
    )
    assert built[0] == 0
    original = _published_semantic_artifacts(_artifact_directory(json.loads(built[1])))

    for field, value in (
        ("symbol", "semantically-different"),
        ("role", "host-owned-role"),
        ("kind", "host-owned-kind"),
        ("unit", "host-owned-unit"),
        ("numeric_policy", "host-owned-policy"),
        ("representation", "HostInt"),
        ("domain", {"minimum": 2, "maximum": 1}),
    ):
        artifacts = deepcopy(original)
        artifacts["rir-semantic-payload"]["declarations"][0][field] = value
        _reidentify(artifacts["rir-semantic-payload"], "rir-semantic-payload-v2")
        artifacts["resolved-model"]["rir_identity"] = artifacts["rir-semantic-payload"][
            "content_identity"
        ]
        _reidentify(artifacts["resolved-model"], "resolved-model-v2")

        admission = model_module.admit_resolved_model(artifacts)

        assert admission.admitted is False
        assert admission.diagnostics == ("language.resolved_authority_mismatch",)


def test_lowerer_executes_the_admitted_ldb_rule_instead_of_copying_source_fields(
    tmp_path,
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    candidate_ldb = deepcopy(checked.language_bundle)
    rule = next(
        item
        for item in candidate_ldb["language"]["rules"]
        if item["id"] == "quantity.lower"
    )
    rule["conclusion"]["fields"]["role"] = {
        "tag": "literal",
        "value": "lowered-by-ldb",
    }
    vector = next(
        item
        for item in candidate_ldb["vectors"]
        if item["id"] == "quantity.lower.valid"
    )
    vector["expect"]["fields"]["role"] = "lowered-by-ldb"
    candidate_ldb["language"]["quantity"]["symbol_roles"].append("lowered-by-ldb")
    candidate_ldb["language"]["packages"][0]["exports"]["symbol_roles"].append(
        "lowered-by-ldb"
    )
    candidate_ldb["language"]["wire_schemas"][0]["schema"]["properties"]["modules"][
        "items"
    ]["properties"]["symbols"]["items"]["properties"]["role"]["enum"].append(
        "lowered-by-ldb"
    )
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = model_module.CheckedModel(
        source=checked.source,
        source_identity=checked.source_identity,
        kernel=checked.kernel,
        language_bundle=candidate_ldb,
    )

    artifacts = model_module.lower_checked_model(candidate)

    declarations = cast(
        list[dict[str, Any]], artifacts["rir-semantic-payload"]["declarations"]
    )
    assert {item["role"] for item in declarations} == {"lowered-by-ldb"}


def test_rir_identity_binds_the_reachable_selected_runtime_semantics(tmp_path):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    candidate_ldb["language"]["quantity"]["units"][0]["dimension"] = (
        "reidentified-dimension"
    )
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = replace(checked, language_bundle=candidate_ldb)

    mutated = model_module.lower_checked_model(candidate)

    original_lock = original["package-lock"]
    mutated_lock = mutated["package-lock"]
    original_rir = original["rir-semantic-payload"]
    mutated_rir = mutated["rir-semantic-payload"]
    original_selected = cast(dict[str, Any], original_rir["selected_semantics"])
    mutated_selected = cast(dict[str, Any], mutated_rir["selected_semantics"])
    assert original_selected != original_lock["selected_semantics"]
    assert mutated_selected != mutated_lock["selected_semantics"]
    assert [row["definition"]["id"] for row in original_selected["operations"]] == [
        "quantity.identity"
    ]
    assert original_selected["conversions"] == []
    original_closures = cast(
        list[dict[str, Any]], original_selected["package_semantic_closures"]
    )
    mutated_closures = cast(
        list[dict[str, Any]], mutated_selected["package_semantic_closures"]
    )
    original_units = next(
        entry["definitions"]
        for entry in cast(list[dict[str, Any]], original_closures[0]["definitions"])
        if entry["authority_path"] == "language.quantity.units"
    )
    mutated_units = next(
        entry["definitions"]
        for entry in cast(list[dict[str, Any]], mutated_closures[0]["definitions"])
        if entry["authority_path"] == "language.quantity.units"
    )
    assert original_units[0]["dimension"] == "dimensionless"
    assert mutated_units[0]["dimension"] == "reidentified-dimension"
    assert original_lock["content_identity"] != mutated_lock["content_identity"]
    assert original_rir["content_identity"] != mutated_rir["content_identity"]
    assert "package_lock_semantic_identity" not in original_rir
    assert "semantic_identity" not in original_closures[0]


def test_compile_only_package_authority_does_not_change_rir_semantics(tmp_path):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    candidate_ldb["language"]["model_checks"].reverse()
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = replace(checked, language_bundle=candidate_ldb)

    mutated = model_module.lower_checked_model(candidate)

    original_package = checked.language_bundle["language"]["packages"][0]
    mutated_package = candidate_ldb["language"]["packages"][0]
    assert original_package["semantic_identity"] == mutated_package["semantic_identity"]
    assert original_package["content_identity"] != mutated_package["content_identity"]
    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["package-lock"] != mutated["package-lock"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_unreachable_runtime_operation_does_not_change_rir_semantics(tmp_path):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    unreachable = next(
        operation
        for operation in candidate_ldb["language"]["operations"]
        if operation["id"] == "game.combat.cast-v1"
    )
    unreachable["resource_bounds"]["max_steps"] += 1
    resource_vector = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "game.combat.cast.resource-bound"
    )
    resource_vector["expect"] += 1
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True
    candidate = replace(checked, language_bundle=candidate_ldb)

    mutated = model_module.lower_checked_model(candidate)

    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["package-lock"] == mutated["package-lock"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_non_rpg_package_is_consumed_without_a_kernel_or_host_extension(
    tmp_path, monkeypatch
):
    kernel, baseline_ldb = model_module.load_authorities()
    candidate_ldb = deepcopy(baseline_ldb)
    language = candidate_ldb["language"]
    package = deepcopy(
        next(item for item in language["packages"] if item["id"] == "standard.compiler")
    )
    package["id"] = "genre.economy"
    package["version"] = "1.0.0"
    package["dependencies"] = {
        "optional": [],
        "required": ["core.quantity"],
    }
    package["capabilities"] = {
        "provided": ["genre.economy.discount"],
        "required": ["quantity.lower"],
    }
    package["exports"] = {name: [] for name in package["exports"]}
    package["exports"]["operations"] = ["genre.economy.discount-v1"]
    package["profiles"] = {"numeric": [], "resolution": [], "runtime": []}
    package["runtime_semantic_paths"] = [
        "language.capabilities",
        "language.operations",
    ]
    for entry in package["semantic_closure"]:
        entry["definitions"] = []
    operation = {
        "body": [
            {
                "left": "price",
                "node": "subtract",
                "right": "discount",
                "target": "result",
            }
        ],
        "effects": [],
        "id": "genre.economy.discount-v1",
        "inputs": [
            {"name": "price", "type": "Quantity"},
            {"name": "discount", "type": "Quantity"},
        ],
        "kind_rules": {"inputs": "preserve", "result": "preserve"},
        "numeric_policy": "exact-int64",
        "operation_kind": "pure-expression",
        "owner_type": "Quantity",
        "purity": "pure",
        "refusals": [],
        "resource_bounds": {"max_steps": 1},
        "result": "Quantity",
        "rule": "quantity.lower",
        "runtime_profile": "compile.exact-int64",
        "unit_rules": {"inputs": "preserve", "result": "preserve"},
        "vectors": ["genre.economy.discount.body"],
        "version": "1.0.0",
    }
    vector = {
        "category": "positive",
        "expect": operation["body"],
        "id": "genre.economy.discount.body",
        "kind": "operation-contract",
        "operation": operation["id"],
        "probe": {"path": "body"},
    }
    package["vectors"] = [vector["id"]]
    package["vector_definitions"] = [deepcopy(vector)]
    language["capabilities"].append(
        {"id": "genre.economy.discount", "rule": "quantity.lower"}
    )
    language["operations"].append(operation)
    candidate_ldb["vectors"].append(vector)
    language["packages"].append(package)
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    assert kernel == model_module.load_authorities()[0]
    assert baseline_ldb == model_module.load_authorities()[1]

    source_document = _model_source()
    source_document["package_requirements"] = [
        {"id": "core.quantity", "version": "2.0.0"},
        {"id": "genre.economy", "version": "1.0.0"},
    ]
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(source_document), encoding="utf-8")
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    artifacts = model_module.lower_checked_model(checked)

    package_lock = cast(dict[str, Any], artifacts["package-lock"])
    lock_packages = cast(list[dict[str, Any]], package_lock["packages"])
    assert [package["id"] for package in lock_packages] == [
        "core.quantity",
        "genre.economy",
        "standard.compiler",
    ]
    rir = cast(dict[str, Any], artifacts["rir-semantic-payload"])
    selected = cast(dict[str, Any], rir["selected_semantics"])
    operations = cast(list[dict[str, Any]], selected["operations"])
    assert any(
        row["definition"]["id"] == "genre.economy.discount-v1" for row in operations
    )
    host_sources = (
        Path(model_module.__file__),
        Path(model_command_module.__file__),
        Path(model_module.__file__).with_name("experiment.py"),
    )
    assert all("genre.economy" not in path.read_text() for path in host_sources)


@pytest.mark.parametrize(
    "unused_semantics",
    ("domain", "runtime-profile", "capability"),
)
def test_unreachable_package_semantics_do_not_change_rir(
    tmp_path,
    unused_semantics,
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    checked = model_module.check_model_source(str(source))
    assert isinstance(checked, model_module.CheckedModel)
    original = model_module.lower_checked_model(checked)
    candidate_ldb = deepcopy(checked.language_bundle)
    language = candidate_ldb["language"]
    package = language["packages"][0]
    if unused_semantics == "domain":
        language["quantity"]["domains"].append("unused-domain")
        package["exports"]["domains"].append("unused-domain")
    elif unused_semantics == "runtime-profile":
        language["runtime_profiles"].append(
            {
                "id": "compile.unused",
                "version": "2.0.0",
                "numeric_policy": "exact-int64",
                "evaluation": "declaration-only",
                "effects": [],
                "resource_bounds": {"max_steps": 1},
            }
        )
        package["profiles"]["runtime"].append("compile.unused")
    else:
        language["capabilities"].append(
            {"id": "quantity.unused", "rule": "quantity.lower"}
        )
        package["capabilities"]["provided"].append("quantity.unused")
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(checked.kernel, candidate_ldb).admitted is True

    mutated = model_module.lower_checked_model(
        replace(checked, language_bundle=candidate_ldb)
    )

    assert original["rir-semantic-payload"] == mutated["rir-semantic-payload"]
    assert original["package-lock"] != mutated["package-lock"]
    assert original["resolved-model"] != mutated["resolved-model"]


def test_resolution_step_exhaustion_is_a_typed_static_refusal(
    tmp_path, run_cli, monkeypatch
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    kernel, candidate_ldb = deepcopy(model_module.load_authorities())
    candidate_ldb["resources"]["max_rule_match_steps"] = 1
    boundary = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.accept.resolution-step-boundary"
    )
    successor = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.refuse.resolution-step-budget"
    )
    boundary["input"]["value"] = 1
    successor["input"]["value"] = 2
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    exit_code, stdout, stderr = run_cli(["model", "check", str(source)])

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.resource_exhausted"
    ]


@pytest.mark.parametrize("command", ("check", "build"))
def test_runtime_projection_step_exhaustion_is_a_typed_static_refusal(
    tmp_path, run_cli, monkeypatch, command
):
    source = tmp_path / "model-source.json"
    source.write_text(json.dumps(_model_source()), encoding="utf-8")
    kernel, candidate_ldb = deepcopy(model_module.load_authorities())
    candidate_ldb["resources"]["max_runtime_projection_steps"] = 1
    boundary = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.accept.runtime-projection-step-boundary"
    )
    successor = next(
        vector
        for vector in candidate_ldb["vectors"]
        if vector["id"] == "model.refuse.runtime-projection-step-budget"
    )
    boundary["input"]["value"] = 1
    successor["input"]["value"] = 2
    _reidentify_language_bundle(candidate_ldb)
    assert admit_authorities(kernel, candidate_ldb).admitted is True
    monkeypatch.setattr(
        model_module, "load_authorities", lambda: (kernel, candidate_ldb)
    )

    output = tmp_path / "published"
    arguments = ["model", command, str(source)]
    if command == "build":
        arguments.extend(
            [
                "--out",
                str(output),
                "--invocation-key",
                "a" * 64,
            ]
        )
    exit_code, stdout, stderr = run_cli(arguments)

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.resource_exhausted"
    ]
    assert not output.exists()
