"""Public CLI vectors for limited Standard Schema 1.x source migration."""

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

import gda_balancing.domain.migration as migration_module
from gda_balancing.interfaces.cli.descriptors import RefusalDetailSpec
from gda_balancing.schema.funnel.preflight import MAX_DOCUMENT_BYTES
from gda_balancing.schema.version import STRUCTURAL_SCHEMA_ID
from gda_balancing.domain.authority.graph import (
    LanguageBundleIndex,
    derive_language_index,
)
from gda_balancing.domain.canonical import canonical_bytes, content_identity
from gda_balancing.domain.migration import MAX_SOURCE_OBSERVATION_BYTES
from gda_balancing.domain.model.semantics import verify_artifact


def _member(receipt: dict, logical_name: str) -> dict:
    path = next(
        Path(item["locator"])
        for item in receipt["member_locators"]
        if item["logical_name"] == logical_name
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _source_bytes_identity(data: bytes) -> str:
    return (
        "sha256:"
        + hashlib.sha256(b"gda-balancing:design-document-source-v1:" + data).hexdigest()
    )


def _language_index(authority: dict[str, Any]) -> LanguageBundleIndex:
    kernel = cast(dict[str, Any], authority["kernel"])
    root = cast(dict[str, Any], authority["language_bundle"])
    releases = cast(list[dict[str, Any]], authority["package_releases"])
    vector_sets = cast(
        list[dict[str, Any]], authority["package_conformance_vector_sets"]
    )
    package_sizes = [len(canonical_bytes(cast(Any, release))) for release in releases]
    vector_set_sizes = [
        len(canonical_bytes(cast(Any, vector_set))) for vector_set in vector_sets
    ]
    return derive_language_index(
        root,
        releases,
        vector_sets,
        cast(list[str], kernel["admission"]["required_language_members"]),
        root_byte_size=len(canonical_bytes(cast(Any, root))),
        package_byte_sizes=package_sizes,
        vector_set_byte_sizes=vector_set_sizes,
        descriptor_order=cast(
            list[str],
            kernel["meta_format"]["language_bundle"]["package_descriptor"][
                "canonical_order"
            ],
        ),
    )


def _reidentify_artifact(artifact: dict[str, Any], language_bundle: dict) -> None:
    contract = next(
        item
        for item in language_bundle["language"]["artifact_contracts"]
        if item["artifact_kind"] == artifact["artifact_kind"]
    )
    artifact["content_identity"] = content_identity(
        contract["identity_domain"],
        {
            key: value
            for key, value in artifact.items()
            if key != "content_identity"
            and key not in contract["identity_excluded_members"]
        },
    )


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
        "package_requirements": [{"id": "core.quantity", "version": "2.1.0"}],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.1.0",
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
                        "value_policy": {"mode": "model-fixed", "value": 100},
                    }
                ],
            }
        ],
        "entrypoints": [],
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
    converter = report["converter_specification"]
    assert report["converter_identity"] == converter["content_identity"]
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    language_bundle = _language_index(authority)
    assert report["kernel_identity"] == authority["kernel"]["content_identity"]
    assert (
        report["language_bundle_identity"]
        == authority["language_bundle"]["content_identity"]
    )
    assert verify_artifact(
        cast(dict[str, Any], converter),
        language_bundle,
    )
    assert verify_artifact(report, language_bundle)
    tampered_report = deepcopy(report)
    tampered_report["converter_specification"]["mapping_rules"][0]["report_mapping"] = (
        "forged mapping"
    )
    _reidentify_artifact(tampered_report, language_bundle)
    assert verify_artifact(tampered_report, language_bundle) is False
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
            "value_policy": {"mode": "model-fixed", "value": 25},
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


def test_model_migrate_refuses_an_oversized_target_without_internal_error(
    tmp_path: Path, run_cli
) -> None:
    legacy = tmp_path / "legacy-target-too-large.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {"name": "legacy.target-too-large"},
                "parameters": {
                    f"parameter_{index:04d}_{'x' * 180}": index for index in range(3000)
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
            "d" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "migration"
    assert [item["code"] for item in error["diagnostics"]] == [
        "migration.target_limit_exceeded"
    ]
    assert error["migration_report"]["status"] == "refused"
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
    language_bundle = _language_index(authority)
    report_schema = next(
        item["schema"]
        for item in language_bundle["language"]["artifact_wire_schemas"]
        if item["artifact_kind"] == "migration-refusal-report"
    )
    jsonschema.validate(report, report_schema)
    assert report["kernel_identity"] == authority["kernel"]["content_identity"]
    assert (
        report["language_bundle_identity"]
        == authority["language_bundle"]["content_identity"]
    )
    converter = report["converter_specification"]
    assert report["converter_identity"] == converter["content_identity"]
    assert verify_artifact(
        cast(dict[str, Any], converter),
        language_bundle,
    )
    assert verify_artifact(report, language_bundle)
    tampered_report = deepcopy(report)
    tampered_report["converter_identity"] = "sha256:" + "0" * 64
    _reidentify_artifact(tampered_report, language_bundle)
    assert verify_artifact(tampered_report, language_bundle) is False
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


def test_model_migrate_preserves_the_first_source_refusal_at_a_shared_path(
    tmp_path: Path, run_cli
) -> None:
    source = tmp_path / "legacy-shared-refusal-path.json"
    source.write_text(
        '{"schema_version":"1.0.0","meta":{"name":"legacy.shared-path"},'
        '"parameters":{"\\ud800":1,"\\ud800":2}}',
        encoding="utf-8",
    )
    output = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(source),
            "--out",
            str(output),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stderr) == (2, "")
    diagnostics = json.loads(stdout)["error"]["diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["primary"]["pointer"] == "/parameters"
    assert "duplicate_object_key" in diagnostics[0]["message"]
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


@pytest.mark.parametrize(
    ("legacy_body", "pointer"),
    (
        ({"parameters": {"signed_zero": -0.0}}, "/parameters/signed_zero"),
        (
            {
                "attributes": {
                    "items": {
                        "signed_zero": {
                            "domain": "number",
                            "base": {"direct": -0.0},
                        }
                    }
                }
            },
            "/attributes/items/signed_zero",
        ),
    ),
)
def test_model_migrate_refuses_negative_zero_without_partial_output(
    tmp_path: Path, run_cli, legacy_body: dict, pointer: str
) -> None:
    source = tmp_path / "legacy-negative-zero.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {"name": "legacy.negative-zero"},
                **legacy_body,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(source),
            "--out",
            str(output),
            "--invocation-key",
            hashlib.sha256(pointer.encode()).hexdigest(),
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert [item["code"] for item in error["diagnostics"]] == [
        "migration.deprecated_construct"
    ]
    assert [item["primary"]["pointer"] for item in error["diagnostics"]] == [pointer]
    assert output.exists() is False


def test_oversized_input_identity_hashes_the_complete_source_not_its_bounded_prefix(
    tmp_path: Path, run_cli
) -> None:
    shared_prefix = b" " * (MAX_DOCUMENT_BYTES + 1)
    sources = [shared_prefix + suffix for suffix in (b"first-suffix", b"second-suffix")]
    reports = []

    for index, source_bytes in enumerate(sources, start=1):
        source = tmp_path / f"oversized-{index}.json"
        source.write_bytes(source_bytes)
        output = tmp_path / f"must-not-exist-{index}.json"
        exit_code, stdout, stderr = run_cli(
            [
                "model",
                "migrate",
                str(source),
                "--out",
                str(output),
                "--invocation-key",
                str(index + 3) * 64,
            ]
        )
        assert (exit_code, stderr) == (2, "")
        reports.append(json.loads(stdout)["error"]["migration_report"])
        assert reports[-1]["input_identity"] == _source_bytes_identity(source_bytes)
        assert output.exists() is False

    assert reports[0]["input_identity"] != reports[1]["input_identity"]
    assert reports[0]["content_identity"] != reports[1]["content_identity"]


def test_migration_diagnostics_are_reachable_only_from_model_migrate(run_cli) -> None:
    manifest = json.loads(run_cli(["manifest"])[1])
    catalogs = {
        (item["group"], item["command"]): item["execution"]["refusal_catalog"]
        for item in manifest["commands"]
    }
    migration_codes = {
        item["code"]
        for item in catalogs[("model", "migrate")]
        if item["stage"] == "migration"
    }
    assert migration_codes == {
        "migration.deprecated_construct",
        "migration.no_mappable_construct",
        "migration.source_invalid",
        "migration.target_limit_exceeded",
    }
    for command, catalog in catalogs.items():
        if command == ("model", "migrate"):
            continue
        assert all(item["stage"] != "migration" for item in catalog)


def test_converter_identity_covers_the_reported_defaults_and_warnings(
    tmp_path: Path, run_cli
) -> None:
    source = tmp_path / "legacy-converter-contract.json"
    source.write_text(
        json.dumps(
            {
                "$schema": STRUCTURAL_SCHEMA_ID,
                "schema_version": "1.0.0",
                "meta": {
                    "name": "legacy.converter-contract",
                    "description": "omitted",
                },
                "parameters": {"power": 10},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "migrated.json"
    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(source),
            "--out",
            str(output),
            "--invocation-key",
            "f" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    report = _member(json.loads(stdout), "migration-report")
    specification = cast(dict[str, Any], report["converter_specification"])
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    language_bundle = _language_index(authority)
    contract = next(
        item
        for item in language_bundle["language"]["artifact_contracts"]
        if item["artifact_kind"] == "source-converter-specification"
    )
    identity_body = {
        key: value
        for key, value in specification.items()
        if key != "content_identity"
        and key not in contract["identity_excluded_members"]
    }
    assert specification["content_identity"] == content_identity(
        contract["identity_domain"], identity_body
    )
    assert report["converter_identity"] == specification["content_identity"]
    assert verify_artifact(specification, language_bundle)
    assert verify_artifact(report, language_bundle)
    assert specification["source_observation"] == {
        "regular_file_only": True,
        "max_bytes": MAX_SOURCE_OBSERVATION_BYTES,
        "parse_prefix_bytes": MAX_DOCUMENT_BYTES + 1,
    }
    assert specification["target_limits"] == [
        "language-bundle.resources.max_source_bytes",
        "language-bundle.resources.max_symbols",
    ]
    tampered_report = deepcopy(report)
    tampered_report["converter_specification"]["mapping_rules"][0]["report_mapping"] = (
        "forged mapping"
    )
    _reidentify_artifact(tampered_report, language_bundle)
    assert verify_artifact(tampered_report, language_bundle) is False
    report_schemas = {
        item["artifact_kind"]: item["schema"]
        for item in language_bundle["language"]["artifact_wire_schemas"]
        if item["artifact_kind"] in {"migration-report", "migration-refusal-report"}
    }
    for schema in report_schemas.values():
        assert schema["properties"]["converter_identity"] == {
            "const": specification["content_identity"]
        }
        assert schema["properties"]["converter_specification"] == {
            "const": specification
        }
    report_contract = cast(dict[str, Any], specification["report_contract"])
    assert report["defaults"] == report_contract["defaults"]
    assert [warning["code"] for warning in report["warnings"]] == [
        "metadata.omitted",
        "schema-reference.replaced",
    ]
    assert report["warnings"] == [
        item["report"]
        for item in cast(list[dict[str, Any]], report_contract["warnings"])
    ]
    mapping_rules = cast(list[dict[str, Any]], specification["mapping_rules"])
    assert {item["mapping"] for item in report["mappings"]} <= {
        item["report_mapping"] for item in mapping_rules
    }


def test_refusal_detail_extension_is_closed_to_the_migration_report() -> None:
    with pytest.raises(ValueError, match="migration-report"):
        RefusalDetailSpec(
            stage="migration",
            field_name=cast(Any, "ambient_extension"),
            schema=lambda: {},
        )


@pytest.mark.parametrize("special_source", ("device", "fifo"))
def test_source_observation_never_reads_a_non_regular_file(
    tmp_path: Path,
    special_source: str,
    monkeypatch,
) -> None:
    if special_source == "device":
        source = Path("/dev/zero")
        if not source.exists():
            pytest.skip("/dev/zero is unavailable")
    else:
        source = tmp_path / "legacy.fifo"
        os.mkfifo(source)
    reads = 0

    def forbidden_read(_descriptor: int, _size: int) -> bytes:
        nonlocal reads
        reads += 1
        raise AssertionError("non-regular input reached os.read")

    monkeypatch.setattr(migration_module.os, "read", forbidden_read)

    with pytest.raises(migration_module.MigrationInputError):
        migration_module.load_design_source_observation(str(source))

    assert reads == 0


@pytest.mark.parametrize("special_source", ("device", "fifo"))
def test_model_migrate_rejects_non_regular_sources_without_blocking(
    tmp_path: Path,
    special_source: str,
) -> None:
    if special_source == "device":
        source = Path("/dev/zero")
        if not source.exists():
            pytest.skip("/dev/zero is unavailable")
    else:
        source = tmp_path / "legacy.fifo"
        os.mkfifo(source)
    output = tmp_path / f"{special_source}.output"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gda_balancing",
            "model",
            "migrate",
            str(source),
            "--out",
            str(output),
            "--invocation-key",
            hashlib.sha256(special_source.encode()).hexdigest(),
        ],
        check=False,
        capture_output=True,
        text=True,
        # This is a deadlock watchdog, not a cold-process latency budget. The
        # semantic assertions below prove that the CLI rejects before reading
        # the device/FIFO; allow for Python startup variance on hosted runners.
        timeout=5,
    )

    assert (completed.returncode, completed.stdout) == (3, "")
    assert json.loads(completed.stderr)["error"]["code"] == "unreadable_input"
    assert output.exists() is False


def test_model_migrate_rejects_a_regular_file_beyond_the_observation_cap(
    tmp_path: Path,
    run_cli,
) -> None:
    source = tmp_path / "too-large-to-observe.json"
    with source.open("wb") as handle:
        handle.truncate(MAX_SOURCE_OBSERVATION_BYTES + 1)
    output = tmp_path / "must-not-exist.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(source),
            "--out",
            str(output),
            "--invocation-key",
            "e" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "unreadable_input"
    assert output.exists() is False
