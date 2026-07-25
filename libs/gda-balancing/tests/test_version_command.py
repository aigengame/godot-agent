"""The Schema 2.0 version tracer's independent compatibility axes.

Two distinct, never-conflated fields: `toolkit_version` (the installed
package version) and `supported_schema_line` (the supported Standard Schema
line, now `"2.0"`).
"""

import json
from importlib.metadata import version as package_version

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
