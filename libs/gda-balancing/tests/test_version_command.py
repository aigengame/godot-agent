"""The version tracer's own contract (bADR-0007/0009 + #502 adjudications).

Two distinct, never-conflated fields: `toolkit_version` (the installed
package version) and `supported_schema_line` (`null` until #504 lands the
first validatable Standard Schema implementation).
"""

import json
from importlib.metadata import version as package_version


def test_version_reports_both_authorities_as_distinct_fields(run_cli):
    exit_code, stdout, stderr = run_cli(["version"])
    assert (exit_code, stderr) == (0, "")
    payload = json.loads(stdout)
    assert payload == {
        "supported_schema_line": None,
        "toolkit_version": package_version("gda-balancing"),
    }


def test_version_output_is_canonical(run_cli):
    _, stdout, _ = run_cli(["version"])
    # Sorted keys, one document, one trailing LF (bADR-0005).
    assert stdout == (
        '{"supported_schema_line": null, '
        f'"toolkit_version": "{package_version("gda-balancing")}"}}\n'
    )
