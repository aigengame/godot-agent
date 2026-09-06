"""`schema get` argument binding (bADR-0008/0011).

The artifact name binds into the input model; an unknown value fails model
validation at the usage boundary, so `schema get bogus` is a usage
`invalid_argument` / exit 3 automatically — no bespoke handling. Current artifact content is exercised
by the authority CLI tests.
"""

import json
import jsonschema

from gda_balancing.interfaces.cli.envelope import ERROR_ENVELOPE_SCHEMA


def test_unknown_artifact_is_a_usage_error(run_cli):
    exit_code, stdout, stderr = run_cli(["schema", "get", "bogus"])
    assert (exit_code, stdout) == (3, "")
    payload = json.loads(stderr)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == "usage"
    assert payload["error"]["code"] == "invalid_argument"


def test_schema_get_is_stdout_only(run_cli):
    # bADR-0021: retrieval commands can remain stdout-only and therefore do
    # not advertise or accept an artifact publication sink.
    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "language-bundle", "--out", "authority.json"]
    )
    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "unknown_argument"


def test_current_surface_excludes_retired_schema1_commands_and_authority(run_cli):
    for command in (
        ["design", "validate"],
        ["design", "format"],
        ["model", "migrate"],
        ["model", "reverse"],
    ):
        exit_code, stdout, stderr = run_cli([*command, "retired-input.json"])
        assert (exit_code, stdout) == (3, "")
        assert json.loads(stderr)["error"]["code"] == "unknown_command"

    exit_code, stdout, stderr = run_cli(["manifest"])
    assert (exit_code, stderr) == (0, "")
    commands = {
        (row["group"], row["command"]) for row in json.loads(stdout)["commands"]
    }
    assert ("model", "migrate") not in commands

    exit_code, stdout, stderr = run_cli(["schema", "get", "language-bundle"])
    assert (exit_code, stderr) == (0, "")
    packages = {release["id"] for release in json.loads(stdout)["package_releases"]}
    assert "tooling.migration" not in packages

    exit_code, stdout, stderr = run_cli(["schema", "get", "wire-schema"])
    assert (exit_code, stderr) == (0, "")
    artifact_kinds = {item["artifact_kind"] for item in json.loads(stdout)["schemas"]}
    assert artifact_kinds.isdisjoint(
        {"migration-report", "migration-refusal-report", "model-migrate-command-input"}
    )
