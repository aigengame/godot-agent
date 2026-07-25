"""Public bootstrap surface for the permanent Standard Schema 2.0 authority.

These tests deliberately enter through dispatch: the first permanent language
authority is useful only if a consumer can retrieve and identify it without
importing implementation-private registries.
"""

import json
from dataclasses import replace
from copy import deepcopy
from typing import get_args

import jsonschema
import pytest

import gda_balancing.schema2.authority as authority_module
import gda_balancing.schema2.bootstrap as bootstrap_module
import gda_balancing.commands.schema as schema_command_module
from gda_balancing.commands.manifest import MANIFEST
from gda_balancing.commands.model import MODEL_BUILD, MODEL_CHECK
from gda_balancing.commands.schema import SCHEMA_GET, schema_get_handler
from gda_balancing.schema2.canonical import content_identity
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    RefusalStage,
    Schema2Diagnostic,
    Schema2RefusalReport,
)
from gda_balancing.schema2.surface import schema2_error_envelope_schema


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

    exit_code, stdout, stderr = run_cli(["schema", "get", "language-bundle"])
    assert (exit_code, stderr) == (2, "")
    assert json.loads(stdout)["error"]["stage"] == "ingress"


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


def test_schema_introspection_does_not_read_runtime_authorities(monkeypatch, run_cli):
    def fail_if_loaded():
        raise AssertionError("introspection read runtime authority")

    monkeypatch.setattr(schema_command_module, "load_authorities", fail_if_loaded)

    for argv in (["schema", "get", "--schema"], ["manifest"]):
        exit_code, stdout, stderr = run_cli(argv)
        assert (exit_code, stderr) == (0, "")
        assert json.loads(stdout)


def test_language_bundle_returns_the_admitted_kernel_and_ldb(run_cli):
    exit_code, stdout, stderr = run_cli(["schema", "get", "language-bundle"])

    assert (exit_code, stderr) == (0, "")
    authority = json.loads(stdout)
    assert set(authority) == {"kernel", "language_bundle", "admission"}
    assert authority["kernel"]["artifact_kind"] == "schema-major-kernel"
    assert authority["language_bundle"]["artifact_kind"] == "language-definition-bundle"
    assert (
        authority["language_bundle"]["kernel_identity"]
        == authority["kernel"]["content_identity"]
    )
    assert authority["admission"] == {
        "admitted": True,
        "kernel_identity": authority["kernel"]["content_identity"],
        "language_bundle_identity": authority["language_bundle"]["content_identity"],
    }


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
        "experiment-specification",
        "genre-coverage-matrix",
        "golden-scenario",
        "model-build-command-input",
        "package-lock",
        "publication-index",
        "negative-vector",
        "resolution-receipt",
        "resolved-model",
        "rir-semantic-payload",
        "schema-major-kernel",
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
    expected = sorted(
        [
            {"authority": owner, "code": entry["code"], "stage": entry["stage"]}
            for owner, artifact in (
                ("kernel", authority["kernel"]),
                ("language-bundle", authority["language_bundle"]),
            )
            for entry in artifact["diagnostics"]
        ],
        key=lambda entry: (entry["stage"], entry["code"], entry["authority"]),
    )
    assert catalog["entries"] == expected
    assert len({entry["code"] for entry in catalog["entries"]}) == len(expected)


def test_manifest_and_per_command_schema_are_one_descriptor_projection(
    run_cli, tmp_path
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
        "manifest",
        "model check",
        "model build",
        "template list",
        "template get",
        "template instantiate",
    }

    for path, row in commands.items():
        schema_exit, schema_stdout, schema_stderr = run_cli([*path.split(), "--schema"])
        assert (schema_exit, schema_stderr) == (0, "")
        assert json.loads(schema_stdout) == row["schema"]
        assert row["descriptor_identity"].startswith("sha256:")
        assert set(row["schema"]) == {
            "artifact_kind",
            "content_identity",
            "descriptor_identity",
            "error",
            "input",
            "profile_identity",
            "success",
        }
        if path == "schema get":
            invocation = ["schema", "get", "language-bundle"]
        elif path == "manifest":
            invocation = ["manifest"]
        elif path == "template list":
            invocation = ["template", "list"]
        elif path == "template get":
            invocation = [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        elif path == "template instantiate":
            invocation = [
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
        else:
            descriptor = MODEL_BUILD if path == "model build" else MODEL_CHECK
            source = tmp_path / f"{path.replace(' ', '-')}.json"
            source.write_text(
                descriptor.fixtures.valid_document or "", encoding="utf-8"
            )
            invocation = ["model", path.split()[1], str(source)]
            if descriptor.artifact_set:
                invocation.extend(
                    [
                        "--out",
                        str(tmp_path / "manifest-build-output"),
                        "--invocation-key",
                        "a" * 64,
                    ]
                )
        result_exit, result_stdout, result_stderr = run_cli(invocation)
        assert (result_exit, result_stderr) == (0, "")
        jsonschema.validate(json.loads(result_stdout), row["schema"]["success"])


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
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    kernel = deepcopy(authority["kernel"])
    ldb = deepcopy(authority["language_bundle"])
    diagnostic_cap = kernel["resources"]["max_diagnostics"]
    for index in range(diagnostic_cap + 2):
        ldb["vectors"].append(
            {
                "expect": {},
                "id": f"mutant.{index}",
                "input": {"facts": [], "judgment": "missing"},
                "rule": "quantity.declare",
            }
        )

    # Reidentify only the mutable LDB; the Schema-major Kernel stays exact.
    ldb_body = {key: value for key, value in ldb.items() if key != "content_identity"}
    ldb["content_identity"] = content_identity(
        "language-definition-bundle-v2", ldb_body
    )

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
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    kernel = authority["kernel"]
    ldb = authority["language_bundle"]
    nested: object = "leaf"
    for _ in range(kernel["resources"]["max_nesting_depth"] + 1):
        nested = [nested]
    ldb["vectors"][0]["unused_host_payload"] = nested
    ldb_body = {key: value for key, value in ldb.items() if key != "content_identity"}
    ldb["content_identity"] = content_identity(
        "language-definition-bundle-v2", ldb_body
    )
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
