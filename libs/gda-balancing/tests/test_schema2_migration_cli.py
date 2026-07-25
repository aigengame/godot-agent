"""Public CLI vectors for limited Standard Schema 1.x source migration."""

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from gda_balancing.schema2.migration import CONVERTER_IDENTITY


def _member(receipt: dict, logical_name: str) -> dict:
    path = next(
        Path(item["locator"])
        for item in receipt["member_locators"]
        if item["logical_name"] == logical_name
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_model_migrate_publishes_a_buildable_source_and_audit_report(
    tmp_path: Path, run_cli
) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {
                    "name": "legacy.parameters",
                    "description": "Legacy authoring note",
                },
                "parameters": {"hit_points": 100},
            }
        ),
        encoding="utf-8",
    )
    migrated = tmp_path / "migrated.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(migrated),
            "--invocation-key",
            "1" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    assert [item["logical_name"] for item in receipt["member_locators"]] == [
        "migration-report",
        "model-source-package",
    ]
    source = json.loads(migrated.read_text(encoding="utf-8"))
    assert source == {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "legacy.parameters",
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
                "symbols": [
                    {
                        "symbol": "parameter.hit_points",
                        "type": "quantity",
                        "role": "parameter",
                        "representation": "Int",
                        "kind": "scalar",
                        "unit": "1",
                        "domain_kind": "closed-interval",
                        "domain": {"minimum": 100, "maximum": 100},
                        "numeric_policy": "exact-int64",
                    }
                ],
            }
        ],
    }
    report = _member(receipt, "migration-report")
    manifest = json.loads(Path(receipt["manifest_locator"]).read_text(encoding="utf-8"))
    source_member = next(
        item
        for item in manifest["members"]
        if item["logical_name"] == "model-source-package"
    )
    assert report["artifact_kind"] == "migration-report"
    assert report["source_schema_version"] == "1.0.0"
    assert report["target_schema_version"] == "2.0.0"
    assert report["output_identity"] == source_member["content_identity"]
    assert report["converter_identity"] == CONVERTER_IDENTITY
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    assert report["kernel_identity"] == authority["kernel"]["content_identity"]
    assert (
        report["language_bundle_identity"]
        == authority["language_bundle"]["content_identity"]
    )
    assert report["converter_identity"] == CONVERTER_IDENTITY
    assert report["mappings"] == [
        {
            "source_pointer": "/schema_version",
            "destination_pointer": "/schema_version",
            "mapping": "schema-major migration",
        },
        {
            "source_pointer": "/meta/name",
            "destination_pointer": "/manifest/id",
            "mapping": "preserve authored document name",
        },
        {
            "source_pointer": "/parameters/hit_points",
            "destination_pointer": "/modules/0/symbols/0",
            "mapping": "integral parameter to equal singleton Quantity domain",
        },
    ]
    assert len(report["defaults"]) == 4
    assert report["warnings"] == [
        {
            "code": "metadata.omitted",
            "source_pointer": "/meta/description",
            "message": "1.x descriptive metadata has no semantic 2.x target",
        }
    ]
    assert report["deprecated_constructs"] == []
    assert report["refusals"] == []

    built = run_cli(
        [
            "model",
            "build",
            str(migrated),
            "--out",
            str(tmp_path / "resolved.json"),
            "--invocation-key",
            "2" * 64,
        ]
    )
    assert (built[0], built[2]) == (0, "")


def test_model_migrate_preserves_an_unmodified_integral_direct_attribute(
    tmp_path: Path, run_cli
) -> None:
    legacy = tmp_path / "legacy-attribute.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {"name": "legacy.attribute"},
                "attributes": {
                    "items": {
                        "armor": {
                            "domain": "number",
                            "base": {"direct": 25},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    migrated = tmp_path / "migrated-attribute.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(migrated),
            "--invocation-key",
            "3" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    source = json.loads(migrated.read_text(encoding="utf-8"))
    assert source["modules"][0]["symbols"] == [
        {
            "symbol": "attribute.armor",
            "type": "quantity",
            "role": "constant",
            "representation": "Int",
            "kind": "scalar",
            "unit": "1",
            "domain_kind": "closed-interval",
            "domain": {"minimum": 25, "maximum": 25},
            "numeric_policy": "exact-int64",
        }
    ]
    receipt = json.loads(stdout)
    report = _member(receipt, "migration-report")
    assert report["mappings"][-1] == {
        "source_pointer": "/attributes/items/armor",
        "destination_pointer": "/modules/0/symbols/0",
        "mapping": "unmodified integral direct attribute to constant singleton Quantity",
    }


def test_model_migrate_refuses_the_target_symbol_limit_without_partial_artifacts(
    tmp_path: Path, run_cli
) -> None:
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    max_symbols = authority["language_bundle"]["resources"]["max_symbols"]
    legacy = tmp_path / "legacy-over-limit.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {"name": "legacy.over-limit"},
                "parameters": {
                    f"parameter_{index:04d}": index for index in range(max_symbols + 1)
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "migrated-over-limit"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(output),
            "--invocation-key",
            "4" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "migration"
    assert [item["code"] for item in error["diagnostics"]] == [
        "migration.target_limit_exceeded"
    ]
    assert output.exists() is False


def test_model_migrate_refusal_emits_an_auditable_report_without_a_source(
    tmp_path: Path, run_cli
) -> None:
    legacy = tmp_path / "legacy-partial.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {
                    "name": "legacy.partial",
                    "description": "Preserve this omission in the audit",
                },
                "parameters": {
                    "exact": 10,
                    "lossy": 1.5,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(output),
            "--invocation-key",
            "9" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    envelope = json.loads(stdout)
    error_schema = json.loads(run_cli(["model", "migrate", "--schema"])[1])["error"]
    jsonschema.validate(envelope, error_schema)
    error = envelope["error"]
    report = error["migration_report"]
    assert report["artifact_kind"] == "migration-refusal-report"
    assert report["status"] == "refused"
    assert report["source_schema_version"] == "1.0.0"
    assert report["target_schema_version"] == "2.0.0"
    assert "output_identity" not in report
    assert report["mappings"] == [
        {
            "source_pointer": "/schema_version",
            "destination_pointer": "/schema_version",
            "mapping": "schema-major migration",
        },
        {
            "source_pointer": "/meta/name",
            "destination_pointer": "/manifest/id",
            "mapping": "preserve authored document name",
        },
        {
            "source_pointer": "/parameters/exact",
            "destination_pointer": "/modules/0/symbols/0",
            "mapping": "integral parameter to equal singleton Quantity domain",
        },
    ]
    assert len(report["defaults"]) == 4
    assert report["warnings"] == [
        {
            "code": "metadata.omitted",
            "source_pointer": "/meta/description",
            "message": "1.x descriptive metadata has no semantic 2.x target",
        }
    ]
    assert report["deprecated_constructs"] == [
        {
            "source_pointer": "/parameters/lossy",
            "diagnostic_code": "migration.deprecated_construct",
            "remediation": "Re-author or remove this construct before migration",
        }
    ]
    assert report["refusals"] == error["diagnostics"]
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    report_schema = next(
        item["schema"]
        for item in authority["language_bundle"]["language"]["artifact_wire_schemas"]
        if item["artifact_kind"] == "migration-refusal-report"
    )
    jsonschema.validate(report, report_schema)
    assert report["kernel_identity"] == authority["kernel"]["content_identity"]
    assert (
        report["language_bundle_identity"]
        == authority["language_bundle"]["content_identity"]
    )
    assert output.exists() is False


def test_model_migrate_refusal_report_binds_diagnostic_truncation(
    tmp_path: Path, run_cli
) -> None:
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    max_diagnostics = authority["language_bundle"]["resources"]["max_diagnostics"]
    legacy = tmp_path / "legacy-many-refusals.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {"name": "legacy.many-refusals"},
                "parameters": {
                    f"lossy_{index:04d}": index + 0.5
                    for index in range(max_diagnostics + 1)
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(output),
            "--invocation-key",
            "a" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    report = error["migration_report"]
    assert error["truncated"] is True
    assert report["truncated"] is True
    assert len(report["refusals"]) == max_diagnostics
    assert len(report["deprecated_constructs"]) == max_diagnostics
    assert output.exists() is False


def test_model_migrate_refusal_report_never_claims_a_failed_mapping(
    tmp_path: Path, run_cli
) -> None:
    legacy = tmp_path / "legacy-empty-name.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {"name": ""},
                "parameters": {"exact": 10},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(output),
            "--invocation-key",
            "b" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    report = json.loads(stdout)["error"]["migration_report"]
    assert [item["source_pointer"] for item in report["mappings"]] == [
        "/schema_version",
        "/parameters/exact",
    ]
    assert [item["source_pointer"] for item in report["deprecated_constructs"]] == [
        "/meta/name"
    ]
    assert output.exists() is False


def test_clean_forward_surface_exposes_no_1x_or_reverse_authority(
    tmp_path: Path, run_cli
) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        '{"schema_version":"1.0.0","meta":{"name":"legacy"}}',
        encoding="utf-8",
    )

    version_exit, version_stdout, version_stderr = run_cli(["version"])
    assert (version_exit, version_stderr) == (0, "")
    version = json.loads(version_stdout)
    assert version["supported_schema_line"] == "2.0"
    assert version["toolkit_version"] != "2.0.0"

    for invocation in (
        ["design", "validate", str(legacy)],
        ["design", "format", str(legacy)],
        ["model", "reverse", str(legacy)],
    ):
        exit_code, stdout, stderr = run_cli(invocation)
        assert (exit_code, stdout) == (3, "")
        assert json.loads(stderr)["error"]["code"] == "unknown_command"


def test_model_migrate_binds_exact_input_identity_and_is_repeatable(
    tmp_path: Path, run_cli
) -> None:
    original_bytes = (
        b'{"schema_version":"1.0.0","meta":{"name":"legacy.identity"},'
        b'"parameters":{"power":10}}'
    )
    original = tmp_path / "legacy-identity.json"
    original.write_bytes(original_bytes)
    first_output = tmp_path / "first.json"
    first_invocation = [
        "model",
        "migrate",
        str(original),
        "--out",
        str(first_output),
        "--invocation-key",
        "5" * 64,
    ]

    first = run_cli(first_invocation)
    retry = run_cli(first_invocation)

    assert (first[0], first[2]) == (0, "")
    assert retry == first
    assert original.read_bytes() == original_bytes
    first_receipt = json.loads(first[1])
    first_report = _member(first_receipt, "migration-report")
    assert first_report["input_identity"] == (
        "sha256:"
        + hashlib.sha256(
            b"gda-balancing:design-document-source-v1:" + original_bytes
        ).hexdigest()
    )

    second_output = tmp_path / "second.json"
    second = run_cli(
        [
            "model",
            "migrate",
            str(original),
            "--out",
            str(second_output),
            "--invocation-key",
            "6" * 64,
        ]
    )
    assert (second[0], second[2]) == (0, "")
    second_report = _member(json.loads(second[1]), "migration-report")
    assert second_output.read_bytes() == first_output.read_bytes()
    assert second_report["content_identity"] == first_report["content_identity"]

    equivalent_bytes = (
        b'{\n  "parameters": {"power": 10},\n'
        b'  "meta": {"name": "legacy.identity"},\n'
        b'  "schema_version": "1.0.0"\n}\n'
    )
    equivalent = tmp_path / "legacy-identity-equivalent.json"
    equivalent.write_bytes(equivalent_bytes)
    equivalent_output = tmp_path / "equivalent.json"
    equivalent_result = run_cli(
        [
            "model",
            "migrate",
            str(equivalent),
            "--out",
            str(equivalent_output),
            "--invocation-key",
            "7" * 64,
        ]
    )
    assert (equivalent_result[0], equivalent_result[2]) == (0, "")
    equivalent_report = _member(json.loads(equivalent_result[1]), "migration-report")
    assert equivalent_output.read_bytes() == first_output.read_bytes()
    assert equivalent_report["output_identity"] == first_report["output_identity"]
    assert equivalent_report["input_identity"] != first_report["input_identity"]
    assert equivalent_report["content_identity"] != first_report["content_identity"]

    before_conflict = first_output.read_bytes()
    conflict = run_cli(
        [
            "model",
            "migrate",
            str(equivalent),
            "--out",
            str(first_output),
            "--invocation-key",
            "5" * 64,
        ]
    )
    assert (conflict[0], conflict[1]) == (3, "")
    assert json.loads(conflict[2])["error"]["code"] == "invocation_key_conflict"
    assert first_output.read_bytes() == before_conflict


@pytest.mark.parametrize(
    ("source_bytes", "code", "pointer"),
    (
        (
            b'{"schema_version":"1.0.0","meta":{"name":"legacy.lossy"},'
            b'"parameters":{"power":1.5}}',
            "migration.deprecated_construct",
            "/parameters/power",
        ),
        (
            b'{"schema_version":"1.0.0","meta":{"name":"legacy.empty"}}',
            "migration.no_mappable_construct",
            "/",
        ),
        (
            b"{",
            "migration.source_invalid",
            "/",
        ),
    ),
)
def test_model_migrate_emits_typed_negative_vectors_without_partial_output(
    tmp_path: Path,
    run_cli,
    source_bytes: bytes,
    code: str,
    pointer: str,
) -> None:
    source = tmp_path / f"{code}.json"
    source.write_bytes(source_bytes)
    output = tmp_path / f"{code}.output"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(source),
            "--out",
            str(output),
            "--invocation-key",
            hashlib.sha256(code.encode()).hexdigest(),
        ]
    )

    assert (exit_code, stderr) == (2, "")
    envelope = json.loads(stdout)
    error_schema = json.loads(run_cli(["model", "migrate", "--schema"])[1])["error"]
    jsonschema.validate(envelope, error_schema)
    error = envelope["error"]
    assert error["stage"] == "migration"
    assert [item["code"] for item in error["diagnostics"]] == [code]
    assert [item["primary"]["pointer"] for item in error["diagnostics"]] == [pointer]
    assert source.read_bytes() == source_bytes
    assert output.exists() is False


def test_model_migrate_reports_the_exact_accepted_1x_patch_version(
    tmp_path: Path, run_cli
) -> None:
    source = tmp_path / "legacy-patch.json"
    source.write_text(
        '{"schema_version":"1.0.999","meta":{"name":"legacy.patch"},'
        '"parameters":{"power":10}}',
        encoding="utf-8",
    )
    output = tmp_path / "migrated-patch.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(source),
            "--out",
            str(output),
            "--invocation-key",
            "8" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    report = _member(json.loads(stdout), "migration-report")
    assert report["source_schema_version"] == "1.0.999"
    assert report["target_schema_version"] == "2.0.0"
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "2.0.0"
