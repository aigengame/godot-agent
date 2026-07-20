"""`design format` — canonical round-trip emission (bADR-0005; V11) and the
`--out` artifact-sink contract (bADR-0009).

`design format` runs a document through the same boundary funnel as
`design validate` and, on success, emits the *validated* document in canonical
form: every defined default materialized (V11), reserved sections excluded,
keys sorted. Feeding a formatted document back through `format` is idempotent,
and back through `validate` is accepted — the funnel accepts its own emission.
"""

import json
import os

import jsonschema

from gda_balancing.emit import canonical_json
from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA
from gda_balancing.schema.version import STRUCTURAL_SCHEMA_ID

_MINIMAL = '{"schema_version": "1.0.0", "meta": {"name": "smallest"}}'


def _doc(tmp_path, content, name="doc.json") -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _format(run_cli, tmp_path, content, name="doc.json"):
    return run_cli(["design", "format", _doc(tmp_path, content, name)])


def test_minimal_document_formats_to_canonical_form(run_cli, tmp_path):
    exit_code, stdout, stderr = _format(run_cli, tmp_path, _MINIMAL)
    assert (exit_code, stderr) == (0, "")
    payload = json.loads(stdout)
    # V11 (post PR #527 multi#4): an optional member is absent-or-typed, so an
    # absent optional (`$schema`, `meta.description`) is OMITTED — never emitted
    # as `null`. Only genuine domain defaults are materialized: the empty
    # `parameters`/`attributes`/`effects` sections (bADR-0006) stay present.
    assert payload == {
        "attributes": {"items": {}, "tiers": {}},
        "effects": {"items": {}, "stacking_types": {}},
        "meta": {"name": "smallest"},
        "parameters": {},
        "schema_version": "1.0.0",
    }
    # Canonical: re-rendering the parsed document reproduces the bytes.
    assert stdout == canonical_json(payload)


def _has_null(value) -> bool:
    """Any ``null`` anywhere in a parsed JSON value — an object member value, an
    array element, or the value itself."""
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_has_null(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_null(v) for v in value)
    return False


def test_formatted_minimal_document_has_no_null_members(run_cli, tmp_path):
    # optional≠nullable (PR #527 multi#4): canonical emission omits absent
    # optionals rather than materializing `null`, so NO serialized value is null
    # — while the genuine domain defaults (`accepts`, the empty sections) stay.
    _, stdout, _ = _format(run_cli, tmp_path, _MINIMAL)
    payload = json.loads(stdout)
    assert not _has_null(payload), payload
    # The domain defaults are still materialized, not dropped.
    assert payload["parameters"] == {}
    assert payload["attributes"] == {"items": {}, "tiers": {}}
    assert payload["effects"] == {"items": {}, "stacking_types": {}}


def test_formatted_attribute_materializes_accepts_but_omits_absent_facets(
    run_cli, tmp_path
):
    # An attribute declaring only the required facets: `accepts` is a genuine
    # domain default (materialized to `[]`), but the absent optional facets
    # (`bounds`, `category`, `tier`) are OMITTED, not emitted as `null`.
    content = (
        '{"schema_version": "1.0.0", "meta": {"name": "a"}, '
        '"attributes": {"items": {"power": {"domain": "number", '
        '"base": {"direct": 1}}}}}'
    )
    _, stdout, _ = _format(run_cli, tmp_path, content)
    payload = json.loads(stdout)
    assert not _has_null(payload), payload
    attribute = payload["attributes"]["items"]["power"]
    assert attribute["accepts"] == []  # domain default, materialized
    for absent in ("bounds", "category", "tier"):
        assert absent not in attribute


def test_out_writes_the_body_to_the_sink_and_emits_a_receipt(run_cli, tmp_path):
    # The no-`--out` stdout is the artifact body.
    _, body, _ = _format(run_cli, tmp_path, _MINIMAL)
    sink = tmp_path / "out" / "formatted.json"
    sink.parent.mkdir()
    exit_code, stdout, stderr = run_cli(
        ["design", "format", _doc(tmp_path, _MINIMAL), "--out", str(sink)]
    )
    assert (exit_code, stderr) == (0, "")
    # The artifact body — byte-identical to the no-`--out` stdout — went to the
    # sink; stdout carries only the receipt (bADR-0009).
    assert sink.read_bytes() == body.encode("utf-8")
    assert json.loads(stdout) == {
        "artifact": {"path": os.path.realpath(str(sink)), "bytes": sink.stat().st_size}
    }
    # Atomic write-then-rename leaves no temp litter beside the sink.
    assert [p.name for p in sink.parent.iterdir()] == ["formatted.json"]


# --- V11: absent default ≡ materialized default (bADR-0004a) -----------------


def test_v11_absent_accepts_equals_materialized_empty(run_cli, tmp_path):
    without = (
        '{"schema_version": "1.0.0", "meta": {"name": "v11"}, '
        '"attributes": {"items": {"a": {"domain": "number", "base": {"direct": 1}}}}}'
    )
    declared = (
        '{"schema_version": "1.0.0", "meta": {"name": "v11"}, '
        '"attributes": {"items": {"a": {"domain": "number", '
        '"base": {"direct": 1}, "accepts": []}}}}'
    )
    _, out_without, err_a = _format(run_cli, tmp_path, without, "without.json")
    _, out_declared, err_b = _format(run_cli, tmp_path, declared, "declared.json")
    assert err_a == "" and err_b == ""
    # Semantically equal inputs format to byte-identical canonical output.
    assert out_without == out_declared
    # The default is materialized explicitly (V11).
    assert json.loads(out_without)["attributes"]["items"]["a"]["accepts"] == []


# --- Full-surface round-trip acceptance (bADR-0005) --------------------------

_FULL_SURFACE = {
    "schema_version": "1.0.0",
    "$schema": STRUCTURAL_SCHEMA_ID,
    "meta": {"name": "full", "description": "every base shape"},
    "parameters": {"scale": 2, "rate": 1.5},
    "attributes": {
        "tiers": {"primary": {"base": "direct", "accepts": ["allocation", "effects"]}},
        "items": {
            # direct base
            "power": {"domain": "number", "base": {"direct": 10}},
            "level": {"domain": "number", "base": {"direct": 3}},
            # direct base under a tier (allocation is legal only on a direct base)
            "str": {
                "domain": "number",
                "base": {"direct": 8},
                "accepts": ["allocation", "effects"],
                "tier": "primary",
            },
            # expression-tree base
            "strike": {
                "domain": "number",
                "base": {
                    "formula": {
                        "op": "add",
                        "args": [{"attr": "power"}, {"param": "scale"}],
                    }
                },
            },
            # named-form base
            "curve": {
                "domain": "number",
                "base": {
                    "formula": {
                        "form": "piecewise_linear",
                        "input": {"attr": "level"},
                        "points": [[1, 10], [5, 30]],
                    }
                },
            },
            # bounds (mandatory for a probability domain)
            "crit": {
                "domain": "probability",
                "base": {"direct": 0.3},
                "bounds": {"floor": 0, "cap": 1},
            },
        },
    },
    # Effects (bADR-0006): a stacking type + a timed effect with a continuous
    # modifier, a period, and stacking — magnitudes covering all three shapes
    # (a literal scalar, a named form, and an expression tree).
    "effects": {
        "stacking_types": {"combine": {"aggregation": "stack"}},
        "items": {
            "aura": {
                "modifiers": [
                    {
                        "target": "power",
                        "operation": "add",
                        "application": "continuous",
                        "magnitude": 5,
                    },
                    {
                        "target": "power",
                        "operation": "multiply",
                        "application": "continuous",
                        "magnitude": {
                            "op": "add",
                            "args": [{"literal": 1}, {"attr": "power"}],
                        },
                    },
                    {
                        "target": "str",
                        "operation": "add",
                        "application": "continuous",
                        "magnitude": {
                            "form": "linear",
                            "input": {"attr": "level"},
                            "base": 1,
                            "per_point": {"param": "rate"},
                        },
                    },
                ],
                "duration": {"timed": 10},
                "period": 1,
                "stacking": {"type": "combine", "lifetime": "independent"},
            }
        },
    },
}


def test_full_surface_document_round_trips_and_is_idempotent(run_cli, tmp_path):
    content = json.dumps(_FULL_SURFACE)
    exit_code, formatted, stderr = _format(run_cli, tmp_path, content, "full.json")
    assert (exit_code, stderr) == (0, "")

    # Feeding the OUTPUT back through `format` is byte-identical (idempotent
    # canonicalization).
    exit_2, reformatted, stderr_2 = _format(
        run_cli, tmp_path, formatted, "full-again.json"
    )
    assert (exit_2, stderr_2) == (0, "")
    assert reformatted == formatted

    # The funnel accepts its own canonical emission.
    exit_3, stdout_3, stderr_3 = run_cli(
        ["design", "validate", _doc(tmp_path, formatted, "full-validate.json")]
    )
    assert (exit_3, stderr_3) == (0, "")
    assert json.loads(stdout_3) == {"valid": True}


def test_reserved_sections_are_never_materialized(run_cli, tmp_path):
    _, formatted, _ = _format(run_cli, tmp_path, json.dumps(_FULL_SURFACE), "rs.json")
    payload = json.loads(formatted)
    for reserved in ("combat", "encounters", "builds", "growth", "economy", "targets"):
        assert reserved not in payload


def test_schema_reference_round_trips(run_cli, tmp_path):
    _, formatted, _ = _format(run_cli, tmp_path, json.dumps(_FULL_SURFACE), "sr.json")
    # The correct `$schema` survives canonical emission under its alias.
    assert json.loads(formatted)["$schema"] == STRUCTURAL_SCHEMA_ID


def test_refusing_document_is_a_refusal_envelope(run_cli, tmp_path):
    # A refused document takes the same funnel path as `design validate`:
    # `refusal` envelope on stdout, exit 2 (bADR-0004/0008).
    content = '{"schema_version": "9.0.0", "meta": {"name": "nope"}}'
    exit_code, stdout, stderr = _format(run_cli, tmp_path, content)
    assert (exit_code, stderr) == (2, "")
    payload = json.loads(stdout)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == "refusal"
    assert payload["error"]["refusals"][0]["code"] == "unsupported_schema_version"
