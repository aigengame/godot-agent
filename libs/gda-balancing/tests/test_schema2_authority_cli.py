"""Public bootstrap surface for the permanent Standard Schema 2.0 authority.

These tests deliberately enter through dispatch: the first permanent language
authority is useful only if a consumer can retrieve and identify it without
importing implementation-private registries.
"""

import json
from dataclasses import replace
from copy import deepcopy

import jsonschema

from gda_balancing.commands.schema import SCHEMA_GET, schema_get_handler
from gda_balancing.schema2.canonical import content_identity
from gda_balancing.schema2.surface import schema2_error_envelope_schema


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
        "schema-major-kernel",
        "language-definition-bundle",
        "model-source-package",
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
        "random-variable",
    ):
        jsonschema.validate(
            {
                "schema_version": "2.0.0",
                "symbols": [
                    {
                        "symbol": role,
                        "role": role,
                        "representation": "signed-int64",
                        "kind": "scalar",
                        "unit": "1",
                        "domain": {"minimum": 0, "maximum": 100},
                        "numeric_policy": "exact-int64",
                    }
                ],
            },
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


def test_manifest_and_per_command_schema_are_one_descriptor_projection(run_cli):
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
    assert set(commands) == {"schema get", "manifest"}

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
        invocation = (
            ["schema", "get", "language-bundle"]
            if path == "schema get"
            else ["manifest"]
        )
        result_exit, result_stdout, result_stderr = run_cli(invocation)
        assert (result_exit, result_stderr) == (0, "")
        jsonschema.validate(json.loads(result_stdout), row["schema"]["success"])


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
    kernel["resources"]["max_diagnostics"] = 3
    for index in range(8):
        kernel["admission"]["laws"].append(
            {"id": f"mutant.{index}", "operation": f"unknown.{index}"}
        )

    # Reidentify the mutated pair independently so the failure reaches the
    # static operation/vector gates instead of stopping at ingress identity.
    kernel_body = {
        key: value for key, value in kernel.items() if key != "content_identity"
    }
    kernel["content_identity"] = content_identity("schema-major-kernel-v2", kernel_body)
    ldb["kernel_identity"] = kernel["content_identity"]
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
    jsonschema.validate(payload, schema2_error_envelope_schema())
    error = payload["error"]
    assert error["stage"] == "static"
    assert error["truncated"] is True
    assert len(error["diagnostics"]) == 3
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
