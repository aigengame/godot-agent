"""Public Model compiler tracer for Standard Schema 2.0 (#539)."""

import json
import os
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
from gda_balancing.schema2.surface import descriptor_identity


def _quantity_symbol(name: str, role: str) -> dict[str, Any]:
    return {
        "symbol": name,
        "type": "quantity",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
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
    assert json.loads(stdout)["error"]["diagnostics"][0]["code"] == (
        "language.source_contract_mismatch"
    )


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
        {key: value for key, value in receipt.items() if key != "content_identity"},
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
    assert sorted(path.name for path in tmp_path.iterdir()) == ["model-source.json"]


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
    index_before = (artifact_dir / "publication-index.json").read_bytes()

    rir = json.loads((artifact_dir / "rir-semantic-payload.json").read_text())
    rir["declarations"][0]["domain"]["maximum"] = 99
    _reidentify(rir, "rir-semantic-payload-v2")
    resolved = json.loads((artifact_dir / "resolved-model.json").read_text())
    resolved["rir_identity"] = rir["content_identity"]
    _reidentify(resolved, "resolved-model-v2")
    build_receipt = json.loads((artifact_dir / "build-receipt.json").read_text())
    build_receipt["rir_identity"] = rir["content_identity"]
    build_receipt["resolved_model_identity"] = resolved["content_identity"]
    _reidentify(build_receipt, "build-receipt-v2")
    for name, artifact in (
        ("rir-semantic-payload", rir),
        ("resolved-model", resolved),
        ("build-receipt", build_receipt),
    ):
        (artifact_dir / f"{name}.json").write_bytes(canonical_bytes(artifact))

    manifest = json.loads((artifact_dir / "artifact-set-manifest.json").read_text())
    replacements = {
        "rir-semantic-payload": rir["content_identity"],
        "resolved-model": resolved["content_identity"],
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
    assert (artifact_dir / "publication-index.json").read_bytes() == index_before

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


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
    assert lock["packages"] == [
        {
            "id": "core.quantity",
            "version": "2.0.0",
            "content_identity": lock["packages"][0]["content_identity"],
            "semantic_identity": lock["packages"][0]["semantic_identity"],
        }
    ]
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
    artifact["content_identity"] = content_identity(
        domain,
        {key: value for key, value in artifact.items() if key != "content_identity"},
    )


def _reidentify_language_bundle(language_bundle: dict[str, Any]) -> None:
    def exact_path(dotted: str) -> Any:
        value: Any = language_bundle
        for segment in dotted.split("."):
            value = value[segment]
        return value

    for package in language_bundle["language"]["packages"]:
        for entry in package["semantic_closure"]:
            entry["definitions"] = deepcopy(exact_path(entry["authority_path"]))
        package["semantic_identity"] = content_identity(
            "domain-package-semantic-closure-v2",
            cast(JsonValue, package["semantic_closure"]),
        )
        _reidentify(package, "domain-package-release-v2")
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
        artifacts["rir-semantic-payload"]["operation_projections"][0]["definition"][
            "id"
        ] = "quantity.reidentified"
        _reidentify(artifacts["rir-semantic-payload"], "rir-semantic-payload-v2")

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


def test_rir_identity_binds_the_full_selected_package_semantics(tmp_path):
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
    assert original_lock["content_identity"] != mutated_lock["content_identity"]
    assert original_rir["content_identity"] != mutated_rir["content_identity"]
    assert (
        original_rir["package_lock_semantic_identity"]
        == original_lock["semantic_identity"]
    )
    assert (
        mutated_rir["package_lock_semantic_identity"]
        == mutated_lock["semantic_identity"]
    )
