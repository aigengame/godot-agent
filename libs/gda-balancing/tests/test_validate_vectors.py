"""`design validate` behavior — the preflight phase of the boundary funnel.

Drives the command end to end through ``run_cli`` (in-process dispatch, real
argv binding). A passing document validates as ``{"valid": true}``; every
refusal path asserts the exit code and the typed refusal codes/paths bADR-0004
and bADR-0004a (V1, V12) fix. Refusal envelopes are validated against the one
closed error schema, never inspected free-form.
"""

import json

import jsonschema

from gda_balancing.emit import canonical_json
from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA

_MINIMAL = '{"schema_version": "1.0.0", "meta": {"name": "smallest"}}'


def _doc(tmp_path, content, name="doc.json") -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _run(run_cli, tmp_path, content, name="doc.json"):
    return run_cli(["design", "validate", _doc(tmp_path, content, name)])


def _refusals(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == "refusal"
    return payload["error"]["refusals"]


# --- Passing documents -----------------------------------------------------


def test_v1_minimal_document_validates(run_cli, tmp_path):
    exit_code, stdout, stderr = _run(run_cli, tmp_path, _MINIMAL)
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


def test_v12_patch_is_ignored_for_acceptance(run_cli, tmp_path):
    # A declared patch component never affects validity (bADR-0001): 1.0.999
    # resolves to the supported 1.0 line.
    content = '{"schema_version": "1.0.999", "meta": {"name": "smallest"}}'
    exit_code, stdout, stderr = _run(run_cli, tmp_path, content)
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


# --- Version dispatch (V12) -------------------------------------------------


def test_v12_newer_minor_is_unsupported(run_cli, tmp_path):
    content = '{"schema_version": "1.7.0", "meta": {"name": "smallest"}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert len(refusals) == 1
    assert refusals[0]["code"] == "unsupported_schema_version"
    assert refusals[0]["path"] == "/schema_version"


def test_non_semver_version_is_malformed(run_cli, tmp_path):
    content = '{"schema_version": "1.0", "meta": {"name": "smallest"}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "malformed_schema_version"
    assert refusals[0]["path"] == "/schema_version"


def test_missing_version_is_malformed(run_cli, tmp_path):
    content = '{"meta": {"name": "smallest"}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "malformed_schema_version"
    assert refusals[0]["path"] == "/schema_version"


# --- Parse and duplicate-key preflight -------------------------------------


def test_unparseable_text_is_malformed_json(run_cli, tmp_path):
    exit_code, stdout, _ = _run(run_cli, tmp_path, '{"schema_version": "1.0.0"')
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "malformed_json"
    assert refusals[0]["path"] == ""


def test_duplicate_object_key_is_refused(run_cli, tmp_path):
    # Duplicate keys cannot come from json.dumps — a lenient parser would
    # silently keep the last; the funnel must detect and refuse (bADR-0002).
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "a"}, "meta": {"name": "b"}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "duplicate_object_key"
    assert refusals[0]["path"] == ""
    assert "meta" in refusals[0]["detail"]


# --- Ingress caps -----------------------------------------------------------


def test_deep_nesting_is_a_refusal_not_a_crash(run_cli, tmp_path):
    # The depth pre-scan turns a pathologically deep document into a typed
    # refusal (exit 2), never a RecursionError (which would be exit 4).
    content = "[" * 65 + "]" * 65
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "nesting_too_deep"


def test_oversized_collection_is_refused(run_cli, tmp_path):
    oversized = {f"k{i}": 0 for i in range(10_001)}
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "smallest"},
        "parameters": oversized,
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    codes = {r["code"] for r in _refusals(stdout)}
    assert "collection_too_large" in codes


def test_non_finite_number_is_refused_at_its_path(run_cli, tmp_path):
    # 1e999 parses to inf — no finite double, and canonical emission forbids
    # it (bADR-0005). Refused at ingress, at the value's own pointer.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "smallest"}, '
        '"parameters": {"p": 1e999}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "number_not_finite"
    assert refusals[0]["path"] == "/parameters/p"


def test_oversized_document_is_refused(run_cli, tmp_path):
    padding = "x" * (10 * 1024 * 1024 + 100)
    content = '{"schema_version": "1.0.0", "meta": {"name": "' + padding + '"}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "document_too_large"
    assert refusals[0]["path"] == ""


def test_report_all_is_ordered_by_path(run_cli, tmp_path):
    # Two non-finite values in insertion order b, a; the report is ordered by
    # instance path, so /parameters/a precedes /parameters/b (bADR-0004).
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "smallest"}, '
        '"parameters": {"b": 1e999, "a": 1e999}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [r["path"] for r in refusals] == ["/parameters/a", "/parameters/b"]
    assert {r["code"] for r in refusals} == {"number_not_finite"}


# --- Usage boundary (bADR-0008) --------------------------------------------


def test_nonexistent_path_is_a_usage_error(run_cli, tmp_path):
    exit_code, stdout, stderr = run_cli(
        ["design", "validate", str(tmp_path / "absent.json")]
    )
    assert (exit_code, stdout) == (3, "")
    error = json.loads(stderr)["error"]
    jsonschema.validate(json.loads(stderr), ERROR_ENVELOPE_SCHEMA)
    assert (error["category"], error["code"]) == ("usage", "unreadable_input")


def test_directory_path_is_a_usage_error(run_cli, tmp_path):
    exit_code, stdout, stderr = run_cli(["design", "validate", str(tmp_path)])
    assert (exit_code, stdout) == (3, "")
    error = json.loads(stderr)["error"]
    jsonschema.validate(json.loads(stderr), ERROR_ENVELOPE_SCHEMA)
    assert (error["category"], error["code"]) == ("usage", "unreadable_input")
