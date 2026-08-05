"""The Schema 2.0 version tracer's independent compatibility axes.

Two distinct, never-conflated fields: `toolkit_version` (the installed
package version) and `supported_schema_line` (the supported Standard Schema
line, now `"2.0"`).
"""

import json
from dataclasses import replace
from importlib.metadata import version as package_version

from gda_balancing.interfaces.cli.version import VERSION, version_handler
from schema2_authority_support import mutable_authorities

SUPPORTED_SCHEMA_LINE = "2.0"


def test_version_reports_both_authorities_as_distinct_fields(run_cli):
    exit_code, stdout, stderr = run_cli(["version"])
    assert (exit_code, stderr) == (0, "")
    payload = json.loads(stdout)
    assert payload == {
        "supported_schema_line": SUPPORTED_SCHEMA_LINE,
        "toolkit_version": package_version("gda-balancing"),
    }


def test_version_output_is_canonical(run_cli):
    _, stdout, _ = run_cli(["version"])
    # Sorted keys, one document, one trailing LF (bADR-0005).
    assert stdout == (
        f'{{"supported_schema_line": "{SUPPORTED_SCHEMA_LINE}", '
        f'"toolkit_version": "{package_version("gda-balancing")}"}}\n'
    )


def test_supported_schema_line_is_a_required_string_not_nullable(run_cli):
    # optional≠nullable on the surface's own results (PR #527 multi#4): the
    # `--schema` output declares `supported_schema_line` as a plain required
    # string — no nullable `anyOf`/`{"type": "null"}` arm, no `null` default.
    _, stdout, _ = run_cli(["version", "--schema"])
    output = json.loads(stdout)["success"]
    field = output["properties"]["supported_schema_line"]
    assert field["type"] == "string"
    assert "anyOf" not in field and "default" not in field
    assert "supported_schema_line" in output["required"]


def test_version_refuses_an_unadmitted_language_bundle(run_cli):
    kernel, language_bundle = mutable_authorities()
    language_bundle["language"]["model_source_schema_versions"] = ["9.0.0"]
    descriptor = replace(
        VERSION,
        handler=version_handler(lambda: (kernel, language_bundle)),
    )

    exit_code, stdout, stderr = run_cli(["version"], registry=(descriptor,))

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["category"] == "refusal"
    assert error["stage"] in {"ingress", "static"}
    assert error["diagnostics"]
