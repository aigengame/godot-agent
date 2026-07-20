"""`design validate` behavior — the boundary funnel end to end.

Drives the command end to end through ``run_cli`` (in-process dispatch, real
argv binding). A passing document validates as ``{"valid": true}``; every
refusal path asserts the exit code and the typed refusal codes/paths bADR-0004
and bADR-0004a fix (preflight V12, structural V1/V2, and the semantic phase's
V2/V3/V4/V12-reserved rules). Refusal envelopes are validated against the one
closed error schema, never inspected free-form.
"""

import json
import time

import jsonschema
import pytest

from gda_balancing.emit import canonical_json
from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA
from gda_balancing.formula import evaluate_bases
from gda_balancing.schema.funnel import validate
from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema.version import STRUCTURAL_SCHEMA_ID


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


def test_v1_minimal_document_validates(run_cli, minimal_design_path):
    # The committed minimal-document golden, validated through the CLI boundary.
    exit_code, stdout, stderr = run_cli(
        ["design", "validate", str(minimal_design_path)]
    )
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
    # The pointer names the offending element, never just the enclosing
    # collection (bADR-0004): a doubled top-level `meta` refuses at `/meta`.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "a"}, "meta": {"name": "b"}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("duplicate_object_key", "/meta")
    ]
    assert "meta" in refusals[0]["detail"]


def test_duplicate_keys_at_distinct_paths_do_not_collapse(run_cli, tmp_path):
    # A doubled nested `power` and a doubled top-level `meta`: two refusals at
    # their two distinct element pointers, ordered by path — not collapsed under
    # a single enclosing-collection dedup (bADR-0004 element precision).
    content = (
        '{"schema_version": "1.0.0", '
        '"parameters": {"power": 1, "power": 2}, '
        '"meta": {"name": "a"}, "meta": {"name": "b"}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("duplicate_object_key", "/meta"),
        ("duplicate_object_key", "/parameters/power"),
    ]


# --- Ingress caps -----------------------------------------------------------


def test_deep_nesting_is_a_refusal_not_a_crash(run_cli, tmp_path):
    # The depth pre-scan turns a pathologically deep document into a typed
    # refusal (exit 2), never a RecursionError (which would be exit 4). One past
    # the composed cap (96, #527): 97 raw brackets.
    content = "[" * 97 + "]" * 97
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


def test_huge_integer_is_number_not_finite_not_a_crash(run_cli, tmp_path):
    # A ~400-digit integer literal parses (JSON grammar admits it) but has no
    # finite IEEE-754 double — `float()` raises OverflowError. It is refused at
    # ingress as `number_not_finite` (exit 2), never a pydantic-conversion
    # engine-parity RuntimeError (exit 4).
    huge = "9" * 400
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "smallest"}, '
        '"parameters": {"p": ' + huge + "}}"
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "number_not_finite"
    assert refusals[0]["path"] == "/parameters/p"


def test_precision_losing_integer_is_accepted(run_cli, tmp_path):
    # An integer that converts to a finite double with mere precision loss is
    # fine — JSON numbers are doubles (bADR-0005), not a refusal.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "smallest"}, '
        '"parameters": {"p": 9007199254740993}}'
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, content)
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


def test_digit_limit_integer_is_malformed_json_not_a_crash(run_cli, tmp_path):
    # A 5000-digit integer trips CPython's integer-string conversion digit limit
    # INSIDE json.loads, which raises a bare ValueError (not a JSONDecodeError).
    # The parser guard catches ValueError, so it is a `malformed_json` refusal
    # (exit 2), never an uncaught crash (exit 4).
    huge = "1" * 5000
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "smallest"}, '
        '"parameters": {"p": ' + huge + "}}"
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "malformed_json"
    assert refusals[0]["path"] == ""


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


# --- Unicode ingress (escaped lone surrogates) ------------------------------


def _is_utf8_encodable(text: str) -> bool:
    """The crash-class invariant: canonical emission is UTF-8 (ensure_ascii=
    False, bADR-0005), so every emitted byte string must encode — a lone
    surrogate leaking into a path/detail would re-create the very
    UnicodeEncodeError the guard prevents."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def test_surrogate_string_value_is_string_not_unicode(run_cli, tmp_path):
    # json.loads accepts an escaped lone surrogate ("\ud800"); canonical
    # emission cannot encode it, so `design format` would crash (exit 4) at
    # output. Preflight refuses it as `string_not_unicode` at the value's path
    # (exit 2), and the refusal envelope itself stays UTF-8 encodable.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x", "description": "\\ud800"}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "string_not_unicode"
    assert refusals[0]["path"] == "/meta/description"


def test_surrogate_object_key_is_string_not_unicode(run_cli, tmp_path):
    # A lone surrogate in a KEY is refused at the offending member's enclosing
    # element (embedding the raw surrogate in the pointer would re-create the
    # UnicodeEncodeError this guard exists to prevent — so the deepest safely
    # encodable pointer is reported). The refusal envelope stays UTF-8 encodable.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"parameters": {"\\ud800": 1}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "string_not_unicode"
    assert refusals[0]["path"] == "/parameters"


def test_surrogate_key_with_non_finite_descendant_is_refused_not_a_crash(
    run_cli, tmp_path
):
    # The finding-2 hole (#527 recheck-2): a surrogate KEY combined with a
    # descendant violation. The key refuses `string_not_unicode` at the enclosing
    # element; the walk must NOT then recurse into the surrogate-keyed subtree
    # (whose value 1e999 is non-finite) with the raw surrogate in the pointer
    # tokens — that built a surrogate-bearing Refusal.path → pydantic
    # ValidationError → exit 4. It is refused at `/parameters` (exit 2), and the
    # envelope stays UTF-8 encodable.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"parameters": {"\\ud800": 1e999}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("string_not_unicode", "/parameters")
    ]


def test_duplicated_surrogate_key_is_refused_at_a_safe_path(run_cli, tmp_path):
    # The duplicate-key sibling of the finding-2 hole: a *duplicated* surrogate
    # key built the key-bearing `duplicate_object_key` pointer before validating
    # the key's encodability → surrogate-bearing Refusal.path → exit 4. Report-all
    # must survive an unaddressable key (#527 recheck-3, F1): the duplication is
    # STILL reported — `duplicate_object_key` at the enclosing safe element
    # (`/parameters`, the deepest safely-encodable pointer), the surrogate key
    # escaped into the detail (never a raw surrogate in path OR detail) — while
    # the same key also refuses `string_not_unicode` there. No refusal names a
    # surrogate pointer; the whole envelope stays UTF-8 encodable.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"parameters": {"\\ud800": 1, "\\ud800": 2}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    # No refusal names a surrogate pointer or carries one in its detail; the
    # enclosing element is the deepest safely-encodable one.
    assert all(_is_utf8_encodable(r["path"]) for r in refusals)
    assert all(_is_utf8_encodable(r["detail"]) for r in refusals)
    # BOTH the duplication and the non-encodability are reported, at the safe path.
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("duplicate_object_key", "/parameters"),
        ("string_not_unicode", "/parameters"),
    ]
    # The duplicate refusal names the offending key — escaped, so encodable.
    dup = next(r for r in refusals if r["code"] == "duplicate_object_key")
    assert "\\ud800" in dup["detail"]


def test_surrogate_key_deep_subtree_reports_no_surrogate_path(run_cli, tmp_path):
    # A surrogate key over a DEEP subtree carrying several violations. The subtree
    # cannot be addressed safely, so the walk stops at the surrogate member and
    # reports only `string_not_unicode` at the enclosing element — NO refusal path
    # may contain a surrogate, and the whole envelope must stay UTF-8 encodable.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"parameters": {"\\ud800": {"a": 1e999, "b": {"c": 1e999, "d": "\\ud801"}}}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    assert all(_is_utf8_encodable(r["path"]) for r in refusals)
    assert all(_is_utf8_encodable(r["detail"]) for r in refusals)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("string_not_unicode", "/parameters")
    ]


def test_sibling_surrogate_keys_aggregate_into_one_named_refusal(run_cli, tmp_path):
    # The recheck-4 Required finding: two DISTINCT unrepresentable sibling keys
    # each minted a generic `string_not_unicode` at the same safe ancestor with
    # the same detail, so report-all's (code, path) dedup collapsed them into ONE
    # refusal that named NEITHER key. The key-caused refusal must aggregate per
    # (safe ancestor, code) with ALL escaped offending keys in the detail, so no
    # distinct offending key can be dropped.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"parameters": {"\\ud800": 1, "\\ud801": 2}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    assert all(_is_utf8_encodable(r["path"]) for r in refusals)
    assert all(_is_utf8_encodable(r["detail"]) for r in refusals)
    # Exactly one string_not_unicode at the ancestor, naming BOTH escaped keys.
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("string_not_unicode", "/parameters")
    ]
    detail = refusals[0]["detail"]
    assert "\\ud800" in detail and "\\ud801" in detail


def test_duplicated_sibling_surrogate_keys_lose_nothing(run_cli, tmp_path):
    # Both unrepresentable sibling keys are ALSO duplicated. Without aggregation
    # the second key's `duplicate_object_key` (and `string_not_unicode`) vanished
    # under (code, path) dedup. Aggregated: one `duplicate_object_key` and one
    # `string_not_unicode`, each at `/parameters` naming BOTH escaped keys —
    # nothing lost, no surrogate in any path or detail.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"parameters": {"\\ud800": 1, "\\ud800": 2, "\\ud801": 3, "\\ud801": 4}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    assert all(_is_utf8_encodable(r["path"]) for r in refusals)
    assert all(_is_utf8_encodable(r["detail"]) for r in refusals)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("duplicate_object_key", "/parameters"),
        ("string_not_unicode", "/parameters"),
    ]
    for refusal in refusals:
        assert "\\ud800" in refusal["detail"] and "\\ud801" in refusal["detail"]


def test_surrogate_keys_under_different_ancestors_stay_separate(run_cli, tmp_path):
    # Surrogate keys under DIFFERENT ancestors have distinct safe pointers, so
    # they naturally stay separate refusals — one per ancestor, each naming only
    # its own offending key.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"parameters": {"\\ud800": 1}, "effects": {"\\ud801": 1}}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    refusals = _refusals(stdout)
    assert all(_is_utf8_encodable(r["path"]) for r in refusals)
    assert all(_is_utf8_encodable(r["detail"]) for r in refusals)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("string_not_unicode", "/effects"),
        ("string_not_unicode", "/parameters"),
    ]
    by_path = {r["path"]: r["detail"] for r in refusals}
    assert (
        "\\ud800" in by_path["/parameters"] and "\\ud801" not in by_path["/parameters"]
    )
    assert "\\ud801" in by_path["/effects"] and "\\ud800" not in by_path["/effects"]


def test_surrogate_document_never_reaches_format_emission(run_cli, tmp_path):
    # `design format` runs the same funnel; the surrogate document is refused at
    # preflight, so it never reaches canonical emission — exit 2, never the
    # exit-4 UnicodeEncodeError the guard prevents, and stdout is encodable.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x", "description": "\\ud800"}}'
    )
    path = _doc(tmp_path, content)
    exit_code, stdout, stderr = run_cli(["design", "format", path])
    assert exit_code == 2  # specifically NOT 4
    assert _is_utf8_encodable(stdout)
    assert {r["code"] for r in _refusals(stdout)} == {"string_not_unicode"}


# --- Semver anchor (the runtime `\Z` fix) ----------------------------------


def test_trailing_newline_schema_version_is_malformed(run_cli, tmp_path):
    # Python's `re` lets `$` match before a trailing newline, so "1.0.0\n" once
    # parsed as the line "1.0" and was accepted. The runtime anchor is `\Z`
    # (true end of string), so a trailing newline is a malformed version, never
    # a smuggled acceptance (a preflight refusal, terminal before structural).
    content = '{"schema_version": "1.0.0\\n", "meta": {"name": "smallest"}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "malformed_schema_version"
    assert refusals[0]["path"] == "/schema_version"


# --- Structural phase (bADR-0004; V1 closed envelope, V2 typed nodes) -------


def test_v1_unknown_top_level_key_refuses_at_the_element(run_cli, tmp_path):
    # V1: the envelope is closed — an unknown top-level key is a structural
    # refusal at the KEY (element precision), not just at the document root.
    content = '{"schema_version": "1.0.0", "meta": {"name": "smallest"}, "extra": {}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert len(refusals) == 1
    assert refusals[0]["code"] == "structural_violation"
    assert refusals[0]["path"] == "/extra"


def test_type_violation_reports_the_offending_scalar_path(run_cli, tmp_path):
    # `meta.name` typed wrong: the pointer reaches the scalar, not the object.
    content = '{"schema_version": "1.0.0", "meta": {"name": 5}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals[0]["code"] == "structural_violation"
    assert refusals[0]["path"] == "/meta/name"


def test_wrong_typed_attribute_entry_refuses_within_its_element(run_cli, tmp_path):
    # A bad enum on one attribute refuses at that attribute's subtree, never at
    # the enclosing `items` map (bADR-0004 element precision).
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "x"},
        "attributes": {"items": {"vit": {"domain": "bogus", "base": {"direct": 5}}}},
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert all(r["code"] == "structural_violation" for r in refusals)
    assert any(r["path"].startswith("/attributes/items/vit") for r in refusals)


def test_v2_untyped_formula_ref_is_a_structural_refusal(run_cli, tmp_path):
    # V2's negative: an untyped `{"ref": ...}` node kind does not exist — the
    # closed node union refuses it structurally (never a semantic reference
    # check on a well-formed node).
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "x"},
        "attributes": {
            "items": {
                "vit": {"domain": "number", "base": {"formula": {"ref": "power"}}}
            }
        },
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals
    assert all(r["code"] == "structural_violation" for r in refusals)


# --- Semantic phase: V2 positive + seam (bADR-0002/0003/0004) ---------------

_V2_DOCUMENT = {
    "schema_version": "1.0.0",
    "meta": {"name": "v2"},
    "parameters": {"power": 10},
    "attributes": {
        "items": {
            "power": {"domain": "number", "base": {"direct": 5}},
            "strike": {
                "domain": "number",
                "base": {
                    "formula": {
                        "op": "add",
                        "args": [{"attr": "power"}, {"param": "power"}],
                    }
                },
            },
        }
    },
}


def test_v2_full_document_validates(run_cli, tmp_path):
    # `power` is declared in both namespaces; the typed nodes disambiguate, and
    # the document clears the whole funnel (preflight → structural → semantic).
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(_V2_DOCUMENT))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


def test_v2_definition_time_finals_through_the_seam():
    # A validated document is the seam's precondition; `validate` is the funnel's
    # public face. strike = power(5) + param power(10) = 15.
    outcome = validate(json.dumps(_V2_DOCUMENT).encode("utf-8"))
    assert isinstance(outcome, DesignDocument)
    assert evaluate_bases(outcome) == {"power": 5.0, "strike": 15.0}


# --- V3: strictly-increasing form points (semantic) -------------------------


def test_v3_non_increasing_points_are_refused(run_cli, tmp_path):
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "v3"},
        "attributes": {
            "items": {
                "level": {"domain": "number", "base": {"direct": 3}},
                "curve": {
                    "domain": "number",
                    "base": {
                        "formula": {
                            "form": "piecewise_linear",
                            "input": {"attr": "level"},
                            "points": [[5, 30], [1, 10]],
                        }
                    },
                },
            }
        },
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("form_points_not_increasing", "/attributes/items/curve/base/formula/points")
    ]


# --- V4: tier-pattern satisfaction, exact-set accepts (semantic) ------------


def test_v4_tier_pattern_exact_set_matching(run_cli, tmp_path):
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "v4"},
        "attributes": {
            "tiers": {
                "primary": {"base": "direct", "accepts": ["allocation", "effects"]}
            },
            "items": {
                "str": {
                    "domain": "number",
                    "base": {"direct": 8},
                    "accepts": ["allocation", "effects"],
                    "tier": "primary",
                },
                "agi": {
                    "domain": "number",
                    "base": {"direct": 8},
                    "accepts": ["allocation"],
                    "tier": "primary",
                },
            },
        },
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    # `str` conforms (exactly {allocation, effects}); only `agi` is refused.
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("tier_pattern_unsatisfied", "/attributes/items/agi")
    ]


# --- Unique accepts channels (structural, both engines) ---------------------


def test_duplicate_accepts_on_attribute_is_a_structural_refusal(run_cli, tmp_path):
    # A repeated contribution channel declares nothing new — the `uniqueItems`
    # guard on the published array refuses it structurally (exit 2), never a
    # pydantic-construction crash (exit 4). The pointer reaches the offending
    # array element, not the enclosing attribute.
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "dup"},
        "attributes": {
            "items": {
                "power": {
                    "domain": "number",
                    "base": {"direct": 10},
                    "accepts": ["effects", "effects"],
                }
            }
        },
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert all(r["code"] == "structural_violation" for r in refusals)
    assert any(r["path"] == "/attributes/items/power/accepts" for r in refusals), (
        refusals
    )


def test_duplicate_accepts_on_tier_pattern_is_a_structural_refusal(run_cli, tmp_path):
    # The tier pattern's `accepts` facet carries the same uniqueness guard.
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "dup-tier"},
        "attributes": {
            "tiers": {"primary": {"accepts": ["allocation", "allocation"]}},
        },
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert all(r["code"] == "structural_violation" for r in refusals)
    assert any(r["path"] == "/attributes/tiers/primary/accepts" for r in refusals), (
        refusals
    )


# --- Facet validity: bounds domain rules + direct-base domain (semantic) ----
#
# bADR-0002: bounds are mandatory on percentage/probability and must *narrow
# within* the domain; probability's value space is pinned to [0, 1]. These
# vectors are the PR #527 review probes the funnel used to wrongly accept.


def _attr_document(attr: dict, *, attr_id: str = "crit", name: str = "facet") -> dict:
    return {
        "schema_version": "1.0.0",
        "meta": {"name": name},
        "attributes": {"items": {attr_id: attr}},
    }


def test_probability_empty_bounds_is_refused(run_cli, tmp_path):
    # `bounds: {}` on a probability attribute narrows nothing — it declares the
    # object without either side, voiding the domain's bounds obligation. Only
    # `bounds_empty` fires (the object is present, so `bounds_required` does not).
    document = _attr_document(
        {"domain": "probability", "base": {"direct": 0.3}, "bounds": {}}
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("bounds_empty", "/attributes/items/crit/bounds")
    ]


def test_probability_bounds_outside_domain_is_refused(run_cli, tmp_path):
    # floor -1 and cap 2 both exceed the domain's [0, 1] space: a probability
    # bound may only narrow within it, never past it.
    document = _attr_document(
        {
            "domain": "probability",
            "base": {"direct": 0.3},
            "bounds": {"floor": -1, "cap": 2},
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("bounds_outside_domain", "/attributes/items/crit/bounds")
    ]


def test_number_inverted_bounds_is_refused(run_cli, tmp_path):
    # floor 100 > cap 0 clamps every value to an empty range. On a `number`
    # attribute no other bounds rule applies, so `bounds_inverted` fires alone.
    document = _attr_document(
        {"domain": "number", "base": {"direct": 5}, "bounds": {"floor": 100, "cap": 0}},
        attr_id="span",
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("bounds_inverted", "/attributes/items/span/bounds")
    ]


def test_probability_direct_base_outside_domain_is_refused(run_cli, tmp_path):
    # A probability `direct` base of 2 is outside the domain's [0, 1] value
    # space. Valid bounds are supplied so the pre-existing `bounds_required`
    # rule does not co-fire — isolating the new `base_outside_domain` check.
    document = _attr_document(
        {
            "domain": "probability",
            "base": {"direct": 2},
            "bounds": {"floor": 0, "cap": 1},
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("base_outside_domain", "/attributes/items/crit/base")
    ]


# --- Positive guards: the shapes bADR-0002 explicitly permits ---------------


def test_probability_bounds_narrowing_within_domain_is_valid(run_cli, tmp_path):
    # A crit-chance cap of 0.5: bounds that narrow *within* [0, 1] are exactly
    # what the domain's mandatory bounds are for.
    document = _attr_document(
        {
            "domain": "probability",
            "base": {"direct": 0.3},
            "bounds": {"floor": 0, "cap": 0.5},
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


def test_number_bounds_with_only_floor_is_valid(run_cli, tmp_path):
    # A single-sided bound declares something, so it is not empty; `number` is
    # unbounded, so a lone floor is legal.
    document = _attr_document(
        {"domain": "number", "base": {"direct": 5}, "bounds": {"floor": 0}},
        attr_id="span",
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


def test_probability_formula_base_overshooting_domain_still_validates(
    run_cli, tmp_path
):
    # The finding-3 document (#527 recheck-2) is LEGAL: a probability formula base
    # of 2 with a declared floor of 0 passes the funnel (the base_outside_domain
    # rule is static/direct-base-only). Overshoot is a *value* concern the
    # definition-time clamp handles (see the seam tests), not a validation defect
    # — so validation stays exit 0 and the funnel/format path is unchanged.
    document = _attr_document(
        {
            "domain": "probability",
            "base": {"formula": {"literal": 2}},
            "bounds": {"floor": 0},
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


@pytest.mark.parametrize("boundary", [0, 1])
def test_probability_direct_base_at_domain_boundary_is_valid(
    run_cli, tmp_path, boundary
):
    # [0, 1] is inclusive: a direct base of exactly 0 or 1 is inside the space.
    document = _attr_document(
        {
            "domain": "probability",
            "base": {"direct": boundary},
            "bounds": {"floor": 0, "cap": 1},
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


# --- V12: reserved section refused until designed (semantic) ----------------


def test_v12_reserved_section_is_refused(run_cli, tmp_path):
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "reserved"},
        "builds": {},
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("reserved_section_present", "/builds")
    ]


# --- $schema agreement (bADR-0001, semantic) --------------------------------


def test_schema_reference_disagreement_is_refused(run_cli, tmp_path):
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "x"}, '
        '"$schema": "urn:something-else"}'
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("schema_reference_disagreement", "/$schema")
    ]


def test_schema_reference_agreement_validates(run_cli, tmp_path):
    content = json.dumps(
        {
            "schema_version": "1.0.0",
            "meta": {"name": "x"},
            "$schema": STRUCTURAL_SCHEMA_ID,
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, content)
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


# --- Optional members are absent-or-typed, never null (PR #527 multi#4) ------
#
# An optional member is either absent or carries a typed value — an explicit
# `null` is neither. The published structural schema drops the pydantic `X |
# None` null arm, so a member present-but-null refuses *structurally* (exit 2)
# rather than being coerced to the field default. This holds uniformly for every
# optional member; the reserved sections keep their permissive carve-out.


def test_explicit_null_schema_reference_is_a_structural_refusal(run_cli, tmp_path):
    # `$schema` is optional, but present-and-null is neither absent nor a string:
    # the null arm is gone from the published schema, so it refuses structurally
    # at `/$schema` — never a smuggled acceptance via coercion to `None` (which
    # the semantic $schema-agreement rule, keyed on `is not None`, would miss).
    content = '{"schema_version": "1.0.0", "meta": {"name": "x"}, "$schema": null}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("structural_violation", "/$schema")
    ]


def test_explicit_null_optional_field_is_a_structural_refusal(run_cli, tmp_path):
    # The same contract on a nested optional: `meta.description` present-and-null
    # is a structural refusal (uniform — null is not a value), not a document
    # that quietly formats back with `"description": null`.
    content = '{"schema_version": "1.0.0", "meta": {"name": "x", "description": null}}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("structural_violation", "/meta/description")
    ]


def test_explicit_null_reserved_section_is_still_reserved(run_cli, tmp_path):
    # The reserved sections keep their permissive `{}` schema (null passes
    # structurally) so the semantic `reserved_section_present` — which reads the
    # raw key, not the value — remains the owner: an explicit `"builds": null`
    # refuses as a reserved section, exactly as `"builds": {}` does.
    content = '{"schema_version": "1.0.0", "meta": {"name": "x"}, "builds": null}'
    exit_code, stdout, _ = _run(run_cli, tmp_path, content)
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("reserved_section_present", "/builds")
    ]


# --- Base-formula acyclicity (bADR-0002, semantic) --------------------------


def test_mutual_base_formula_cycle_refuses_both_bases(run_cli, tmp_path):
    document = {
        "schema_version": "1.0.0",
        "meta": {"name": "cycle"},
        "attributes": {
            "items": {
                "alpha": {"domain": "number", "base": {"formula": {"attr": "beta"}}},
                "beta": {"domain": "number", "base": {"formula": {"attr": "alpha"}}},
            }
        },
    }
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("base_formula_cycle", "/attributes/items/alpha/base"),
        ("base_formula_cycle", "/attributes/items/beta/base"),
    ]


# --- Expression-tree limits & linear-time validation (bADR-0003, #527) -------


def _tree_document(name: str, formula: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "meta": {"name": name},
        "attributes": {
            "items": {"t": {"domain": "number", "base": {"formula": formula}}}
        },
    }


def _unary_chain(depth: int) -> dict:
    """A ``floor`` chain of expression-tree depth ``depth`` (``depth - 1`` ops
    around a literal leaf)."""
    node: dict = {"literal": 1}
    for _ in range(depth - 1):
        node = {"op": "floor", "args": [node]}
    return node


# A deliberately generous wall-clock ceiling. Post-fix the reshaped OpNode schema
# recurses `args.items` once per level, so a legal depth-32 tree validates in
# ~milliseconds; pre-fix it was ~3**depth (>10 s at depth 12, unrunnable at 32),
# so any near-instant bound is a decisive regression guard. 5 s absorbs a loaded
# CI box without ever admitting the exponential path.
_LATENCY_CEILING_SECONDS = 5.0


def test_max_depth_expression_tree_validates_in_linear_time(run_cli, tmp_path):
    # A depth-32 unary chain is the deepest legal formula (bADR-0003). It clears
    # the composed nesting cap (#527: 96 ≥ its ~68 JSON levels) and validates —
    # and must do so fast, or the exponential validator has regressed.
    document = _tree_document("deep", _unary_chain(32))
    start = time.perf_counter()
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    elapsed = time.perf_counter() - start
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})
    assert elapsed < _LATENCY_CEILING_SECONDS, f"validation took {elapsed:.2f}s"


def test_deep_expression_tree_is_refused(run_cli, tmp_path):
    # A depth-33 tree exceeds the semantic depth cap (> 32). Now that the nesting
    # cap composes (#527) it clears preflight and the linear structural phase, so
    # the semantic `expression_tree_too_deep` rule — no longer shadowed by
    # `nesting_too_deep` — is what refuses it, at the formula pointer. Still fast.
    document = _tree_document("t", _unary_chain(33))
    start = time.perf_counter()
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    elapsed = time.perf_counter() - start
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("expression_tree_too_deep", "/attributes/items/t/base/formula")
    ]
    assert elapsed < _LATENCY_CEILING_SECONDS, f"validation took {elapsed:.2f}s"


def test_max_size_wide_tree_validates_in_linear_time(run_cli, tmp_path):
    # 255 literal args + 1 `add` = 256 nodes == the cap (not > 256): valid. A wide
    # tree validates each arg once, so it too is linear in node count.
    wide = {"op": "add", "args": [{"literal": 1} for _ in range(255)]}
    document = _tree_document("wide", wide)
    start = time.perf_counter()
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    elapsed = time.perf_counter() - start
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})
    assert elapsed < _LATENCY_CEILING_SECONDS, f"validation took {elapsed:.2f}s"


def test_wide_expression_tree_exceeding_node_cap_is_refused(run_cli, tmp_path):
    # 256 literal args + 1 `add` = 257 nodes > 256, but only depth 2 — so it
    # exercises the node-count limit, and its JSON nesting is shallow enough to
    # clear preflight and reach the semantic phase.
    wide = {"op": "add", "args": [{"literal": 1} for _ in range(256)]}
    document = _tree_document("wide", wide)
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("expression_tree_too_large", "/attributes/items/t/base/formula")
    ]


# --- Operator arity strictness (the reshape must preserve it, both engines) --

_ARITY_VIOLATIONS = {
    "nary-underfull": {"op": "add", "args": [{"literal": 1}]},
    "binary-overfull": {
        "op": "subtract",
        "args": [{"literal": 1}, {"literal": 2}, {"literal": 3}],
    },
    "binary-underfull": {"op": "power", "args": [{"literal": 1}]},
    "unary-overfull": {"op": "floor", "args": [{"literal": 1}, {"literal": 2}]},
}


@pytest.mark.parametrize(
    "formula", _ARITY_VIOLATIONS.values(), ids=_ARITY_VIOLATIONS.keys()
)
def test_operator_arity_violation_is_a_structural_refusal(formula, run_cli, tmp_path):
    # The reshaped OpNode carries arity as if/then `args`-count clauses (n-ary
    # ≥ 2, binary/unary exactly 2/1). A wrong arg count is a *structural* refusal
    # (exit 2) — proving the linear reshape kept arity strictness that the pydantic
    # model enforces too (the accept ⇔ construct equivalence is pinned in
    # test_engine_parity.py).
    document = _tree_document("t", formula)
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert refusals
    assert all(r["code"] == "structural_violation" for r in refusals)


# --- Effects: V5 instant vs persistent stacking (bADR-0006) -----------------


def _effects_document(effects: dict, *, name: str = "fx") -> dict:
    """A valid document with a `power` target attribute plus the given effects
    section — the enclosing document for the effect vectors."""
    return {
        "schema_version": "1.0.0",
        "meta": {"name": name},
        "attributes": {
            "items": {
                "power": {
                    "domain": "number",
                    "base": {"direct": 10},
                    "accepts": ["effects"],
                }
            }
        },
        "effects": effects,
    }


def test_v5_instant_effect_declaring_stacking_is_refused(run_cli, tmp_path):
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "burst": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "one_shot",
                            "magnitude": 5,
                        }
                    ],
                    "duration": "instant",
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("instant_effect_forbids_stacking", "/effects/items/burst/stacking")
    ]


def test_v5_timed_effect_without_stacking_is_refused(run_cli, tmp_path):
    document = _effects_document(
        {
            "items": {
                "buff": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": 5,
                        }
                    ],
                    "duration": {"timed": 10},
                }
            }
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("persistent_effect_requires_stacking", "/effects/items/buff")
    ]


def test_v5_timed_all_one_shot_with_stacking_is_valid_but_inert(run_cli, tmp_path):
    # A timed effect whose modifiers are all one_shot still declares stacking:
    # valid but inert (one_shot deltas are never selection-gated), not a defect.
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "buff": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "one_shot",
                            "magnitude": 5,
                        }
                    ],
                    "duration": {"timed": 10},
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


# --- Effects: V6 `period` legality (bADR-0006) ------------------------------


def test_v6_all_one_shot_declaring_period_is_refused(run_cli, tmp_path):
    document = _effects_document(
        {
            "items": {
                "strike": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "one_shot",
                            "magnitude": 5,
                        }
                    ],
                    "duration": "instant",
                    "period": 1,
                }
            }
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("period_forbidden_when_all_one_shot", "/effects/items/strike/period")
    ]


def test_v6_continuous_only_with_period_is_valid(run_cli, tmp_path):
    # A continuous-only effect may declare `period`: its continuous magnitudes
    # re-evaluate at each tick boundary (bADR-0006).
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "aura": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": 5,
                        }
                    ],
                    "duration": {"timed": 10},
                    "period": 1,
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


def test_v6_period_below_minimum_granularity_is_refused(run_cli, tmp_path):
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "aura": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": 5,
                        }
                    ],
                    "duration": {"timed": 10},
                    "period": 0.01,
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("period_below_minimum_granularity", "/effects/items/aura/period")
    ]


def test_v6_granularity_and_tick_budget_report_all(run_cli, tmp_path):
    # timed 100 with period 0.005 violates granularity (< 0.05) AND the tick
    # budget (100 / 0.005 = 20000 > 10000): report-all lists BOTH refusals.
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "aura": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": 5,
                        }
                    ],
                    "duration": {"timed": 100},
                    "period": 0.005,
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    codes = {r["code"] for r in _refusals(stdout)}
    assert codes == {"period_below_minimum_granularity", "tick_budget_exceeded"}


def test_v6_continuous_only_tick_budget_is_refused(run_cli, tmp_path):
    # A timed 600 s continuous-only effect with period 0.05 → 12000 ticks >
    # 10000: the budget applies to ANY timed effect declaring `period`.
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "aura": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": 5,
                        }
                    ],
                    "duration": {"timed": 600},
                    "period": 0.05,
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("tick_budget_exceeded", "/effects/items/aura/period")
    ]


# --- Effects: magnitude formula references (bADR-0006/0003) -----------------


def test_magnitude_referencing_its_own_target_is_valid(run_cli, tmp_path):
    # A magnitude may reference its own target attribute — magnitudes are exempt
    # from base-formula acyclicity (bADR-0003); declaredness still applies.
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "regen": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": {"attr": "power"},
                        }
                    ],
                    "duration": "infinite",
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


def test_magnitude_referencing_undeclared_attribute_is_refused(run_cli, tmp_path):
    document = _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "regen": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": {"attr": "nonexistent"},
                        }
                    ],
                    "duration": "infinite",
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        (
            "attribute_reference_undefined",
            "/effects/items/regen/modifiers/0/magnitude",
        )
    ]


# --- Effects: magnitude shares EVERY formula rule (#527 recheck-1) -----------
#
# A formula-capable magnitude (bADR-0003/0006) is a first-class formula consumer,
# so the form-field rules and the expression-tree caps apply to it exactly as they
# do to an attribute base — "no consumer gets a private formula dialect" (bADR-0003).
# Before #527's fix these rules iterated attribute bases only, so a broken magnitude
# form/tree slipped through the funnel. Each vector below is a document valid
# except for its one magnitude formula defect.


def _magnitude_effect_document(magnitude, *, name: str = "mag") -> dict:
    """A valid persistent effect on `power` whose sole modifier carries the given
    magnitude — the enclosing document for a magnitude-formula vector."""
    return _effects_document(
        {
            "stacking_types": {"combine": {"aggregation": "stack"}},
            "items": {
                "regen": {
                    "modifiers": [
                        {
                            "target": "power",
                            "operation": "add",
                            "application": "continuous",
                            "magnitude": magnitude,
                        }
                    ],
                    "duration": "infinite",
                    "stacking": {"type": "combine", "lifetime": "independent"},
                }
            },
        },
        name=name,
    )


def test_magnitude_lookup_table_empty_is_form_points_insufficient(run_cli, tmp_path):
    # An empty lookup_table magnitude has no entries — `form_points_insufficient`
    # fires at the magnitude's `table`, the same rule that guards an attribute base.
    document = _magnitude_effect_document(
        {"form": "lookup_table", "input": {"attr": "power"}, "table": []}
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        (
            "form_points_insufficient",
            "/effects/items/regen/modifiers/0/magnitude/table",
        )
    ]


def test_magnitude_deep_expression_tree_is_refused(run_cli, tmp_path):
    # A depth-33 tree magnitude exceeds the depth cap (> 32); the refusal names the
    # magnitude's formula root, mirroring the attribute-base tree-cap pointer.
    document = _magnitude_effect_document(_unary_chain(33))
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("expression_tree_too_deep", "/effects/items/regen/modifiers/0/magnitude")
    ]


def test_magnitude_wide_expression_tree_is_refused(run_cli, tmp_path):
    # 256 literal args + 1 `add` = 257 nodes > 256: `expression_tree_too_large`
    # at the magnitude's formula root.
    wide = {"op": "add", "args": [{"literal": 1} for _ in range(256)]}
    document = _magnitude_effect_document(wide)
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        ("expression_tree_too_large", "/effects/items/regen/modifiers/0/magnitude")
    ]


def test_magnitude_piecewise_non_increasing_points_is_refused(run_cli, tmp_path):
    # A piecewise_linear magnitude with non-increasing x — `form_points_not_increasing`
    # at the magnitude's `points`.
    document = _magnitude_effect_document(
        {
            "form": "piecewise_linear",
            "input": {"attr": "power"},
            "points": [[5, 30], [1, 10]],
        }
    )
    exit_code, stdout, _ = _run(run_cli, tmp_path, json.dumps(document))
    assert exit_code == 2
    refusals = _refusals(stdout)
    assert [(r["code"], r["path"]) for r in refusals] == [
        (
            "form_points_not_increasing",
            "/effects/items/regen/modifiers/0/magnitude/points",
        )
    ]


def test_valid_named_form_magnitude_still_validates(run_cli, tmp_path):
    # The positive guard: a well-formed piecewise_linear magnitude (strictly
    # increasing points) clears every magnitude formula rule and the document is
    # valid — the fix refuses broken magnitudes without rejecting sound ones.
    document = _magnitude_effect_document(
        {
            "form": "piecewise_linear",
            "input": {"attr": "power"},
            "points": [[1, 10], [5, 30]],
        }
    )
    exit_code, stdout, stderr = _run(run_cli, tmp_path, json.dumps(document))
    assert (exit_code, stderr) == (0, "")
    assert stdout == canonical_json({"valid": True})


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
