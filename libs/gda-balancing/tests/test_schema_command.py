"""`schema get` argument binding (bADR-0008/0011).

The artifact name binds into the input model; an unknown value fails model
validation at the usage boundary, so `schema get bogus` is a usage
`invalid_argument` / exit 3 automatically — no bespoke handling. (The artifact
*content* and golden are pinned in test_engine_parity.py.)
"""

import json
import os

import jsonschema

from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA


def test_unknown_artifact_is_a_usage_error(run_cli):
    exit_code, stdout, stderr = run_cli(["schema", "get", "bogus"])
    assert (exit_code, stdout) == (3, "")
    payload = json.loads(stderr)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == "usage"
    assert payload["error"]["code"] == "invalid_argument"


def test_schema_get_is_an_artifact_sink(run_cli, tmp_path):
    # The self-description artifacts are artifacts too (bADR-0009): `--out`
    # redirects the schema to the sink and stdout carries the receipt.
    _, body, _ = run_cli(["schema", "get", "structural"])
    sink = tmp_path / "structural.json"
    exit_code, stdout, stderr = run_cli(
        ["schema", "get", "structural", "--out", str(sink)]
    )
    assert (exit_code, stderr) == (0, "")
    assert sink.read_bytes() == body.encode("utf-8")
    assert json.loads(stdout) == {
        "artifact": {"path": os.path.realpath(str(sink)), "bytes": sink.stat().st_size}
    }
