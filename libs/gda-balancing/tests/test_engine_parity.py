"""Engine-parity: the structural schema is strict enough that a structural pass
guarantees pydantic construction succeeds (bADR-0004/0005).

The published structural schema runs on Python's ``re`` (via ``jsonschema``),
while the document model is constructed by pydantic's Rust regex engine. The two
disagree on a trailing newline: ``$`` (and an unanchored ``pattern`` search)
match *before* a final ``\\n`` under Python ``re``, but not under Rust. Without
the artifact's newline guards, an id like ``"ab\\n"`` would pass the structural
phase and then crash model construction (exit 4) instead of being refused (exit
2). These tests pin that the guards hold — a near-miss id in either position, and
unknown/miscased keys, all land in ``{0, 2}``, never the internal path.

They also pin the historical 1.x structural projection itself against the
committed golden byte-for-byte, and the golden must stay portable
(ECMA-262 patterns only) and hardened (every ``patternProperties`` node closed).
"""

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA
from gda_balancing.emit import canonical_json
from gda_balancing.schema.bundle import current_bundle
from gda_balancing.schema.funnel.structural import structural
from gda_balancing.schema.model.document import DesignDocument

_GOLDEN = Path(__file__).parent / "goldens" / "structural_schema.json"

# The committed minimal-document golden, loaded once as the compose base for the
# parity vectors below (load-and-edit from the one fixture, not a re-inlined
# literal).
_VALID_MINIMAL = json.loads(
    (Path(__file__).parent / "fixtures" / "minimal_design.json").read_text(
        encoding="utf-8"
    )
)


def _doc(tmp_path, document: dict) -> str:
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def _refusals(stdout: str) -> list[dict]:
    payload = json.loads(stdout)
    jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
    assert payload["error"]["category"] == "refusal"
    return payload["error"]["refusals"]


# --- Trailing-newline divergence: a refusal (exit 2), never a crash (exit 4) --


def test_map_key_trailing_newline_is_a_refusal_not_a_crash(run_legacy_cli, tmp_path):
    # A valid attribute under a map key carrying a trailing newline. Python `re`
    # would let the key match the id patternProperties, so only the
    # propertyNames newline guard catches it — as a structural refusal pointing
    # at the offending entry, NEVER an exit-4 model-construction crash.
    document = {
        **_VALID_MINIMAL,
        "attributes": {"items": {"ab\n": {"domain": "number", "base": {"direct": 5}}}},
    }
    exit_code, stdout, _ = run_legacy_cli(
        ["design", "validate", _doc(tmp_path, document)]
    )
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert len(refusals) == 1
    assert refusals[0]["code"] == "structural_violation"
    assert refusals[0]["path"] == "/attributes/items/ab\n"


def test_scalar_id_trailing_newline_is_a_refusal_not_a_crash(run_legacy_cli, tmp_path):
    # A base-formula `attr` id carrying a trailing newline: the pattern node's
    # sibling newline guard refuses it structurally rather than passing it to a
    # crashing pydantic construction.
    document = {
        **_VALID_MINIMAL,
        "attributes": {
            "items": {
                "vit": {"domain": "number", "base": {"formula": {"attr": "ab\n"}}}
            }
        },
    }
    exit_code, stdout, _ = run_legacy_cli(
        ["design", "validate", _doc(tmp_path, document)]
    )
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert refusals
    assert all(r["code"] == "structural_violation" for r in refusals)


_DIVERGENCE_SWEEP = {
    "valid-minimal": _VALID_MINIMAL,
    "valid-attribute": {
        **_VALID_MINIMAL,
        "parameters": {"power": 10},
        "attributes": {
            "items": {"strike": {"domain": "number", "base": {"direct": 5}}}
        },
    },
    "newline-map-key": {
        **_VALID_MINIMAL,
        "attributes": {"items": {"ab\n": {"domain": "number", "base": {"direct": 1}}}},
    },
    "newline-parameter-key": {**_VALID_MINIMAL, "parameters": {"p\n": 1}},
    "newline-scalar-id": {
        **_VALID_MINIMAL,
        "attributes": {
            "items": {
                "vit": {"domain": "number", "base": {"formula": {"attr": "ab\n"}}}
            }
        },
    },
    "unknown-top-level-key": {**_VALID_MINIMAL, "surprise": {}},
    "wrong-enum-casing": {
        **_VALID_MINIMAL,
        "attributes": {"items": {"vit": {"domain": "Number", "base": {"direct": 1}}}},
    },
}


@pytest.mark.parametrize("document", _DIVERGENCE_SWEEP.values(), ids=_DIVERGENCE_SWEEP)
def test_divergence_sweep_never_takes_the_internal_path(
    document, run_legacy_cli, tmp_path
):
    # Every near-miss must resolve as a clean accept (0) or a typed refusal (2);
    # a structural-schema/pydantic disagreement would surface as exit 4.
    exit_code, _stdout, _stderr = run_legacy_cli(
        ["design", "validate", _doc(tmp_path, document)]
    )
    assert exit_code in (0, 2), f"unexpected exit {exit_code} (engine-parity break?)"


# --- OpNode reshape equivalence: schema verdict ⇔ model construction (#527) ---
#
# The linear reshape (single `$defs/OpNode`, arity by if/then) must give the SAME
# accept/reject verdict as the pydantic model's construction — both are local-shape
# checks, and structural-pass ⇒ construction-success is the funnel's load-bearing
# invariant (bADR-0004/0005). This battery pins that on a spread of valid trees and
# every arity/operator/node-kind violation the reshape could have loosened.

_EQUIVALENCE_TREES = {
    # accepted by both
    "literal": {"literal": 5},
    "attr": {"attr": "power"},
    "param": {"param": "hp"},
    "nary-2": {"op": "add", "args": [{"literal": 1}, {"literal": 2}]},
    "nary-4": {"op": "min", "args": [{"literal": i} for i in range(4)]},
    "binary-2": {"op": "power", "args": [{"attr": "power"}, {"literal": 2}]},
    "unary-1": {"op": "floor", "args": [{"literal": 1}]},
    "nested": {
        "op": "add",
        "args": [{"op": "floor", "args": [{"literal": 1}]}, {"param": "hp"}],
    },
    "deep-legal": None,  # filled below (depth-8 chain)
    # rejected by both — arity
    "nary-1": {"op": "add", "args": [{"literal": 1}]},
    "binary-1": {"op": "subtract", "args": [{"literal": 1}]},
    "binary-3": {
        "op": "divide",
        "args": [{"literal": 1}, {"literal": 2}, {"literal": 3}],
    },
    "unary-0": {"op": "ceil", "args": []},
    "unary-2": {"op": "round", "args": [{"literal": 1}, {"literal": 2}]},
    # rejected by both — closure
    "unknown-op": {"op": "frobnicate", "args": [{"literal": 1}]},
    "untyped-node": {"ref": "power"},
    "op-without-args": {"op": "add"},
}


def _chain(depth: int) -> dict:
    node: dict = {"literal": 1}
    for _ in range(depth - 1):
        node = {"op": "floor", "args": [node]}
    return node


_EQUIVALENCE_TREES["deep-legal"] = _chain(8)


def _as_document(formula: dict) -> dict:
    return {
        **_VALID_MINIMAL,
        "attributes": {
            "items": {"t": {"domain": "number", "base": {"formula": formula}}}
        },
    }


@pytest.mark.parametrize(
    "formula", _EQUIVALENCE_TREES.values(), ids=_EQUIVALENCE_TREES.keys()
)
def test_reshaped_schema_verdict_matches_model_construction(formula):
    document = _as_document(formula)
    schema_accepts = not structural(document)
    try:
        DesignDocument.model_validate(document)
        model_accepts = True
    except ValidationError:
        model_accepts = False
    assert schema_accepts == model_accepts, (
        f"engine disagreement: structural={schema_accepts} model={model_accepts}"
    )


# --- The published artifact: golden snapshot + portability/hardening ---------


def test_historical_structural_projection_matches_golden():
    # Byte-for-byte against the committed golden. To regenerate after a reviewed
    # model change, overwrite it deliberately and review the diff:
    # This remains an internal 1.x regression fixture after the 2.0 public
    # `schema get` surface replaces the historical structural/catalog tokens.
    stdout = canonical_json(current_bundle().structural_schema())
    assert stdout.encode("utf-8") == _GOLDEN.read_bytes()


def test_golden_is_portable_and_hardened():
    text = _GOLDEN.read_text(encoding="utf-8")
    schema = json.loads(text)
    # `$id` embeds the Standard Schema version.
    assert "1.0.0" in schema["$id"]
    # Titles stripped for snapshot stability across pydantic versions.
    assert '"title"' not in text
    # ECMA-262 portability: `\Z` may never appear in a published pattern.
    assert "\\Z" not in text
    # Every patternProperties node is closed with additionalProperties: false.
    pattern_nodes: list[dict] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if "patternProperties" in node:
                pattern_nodes.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    assert pattern_nodes
    assert all(node.get("additionalProperties") is False for node in pattern_nodes)


def test_golden_is_absent_or_typed_never_nullable():
    # optional≠nullable (PR #527 multi#4): the published schema drops every
    # pydantic `X | None` null arm and `"default": null` annotation, so an
    # explicit `null` refuses structurally. This is a structural-shape guard on
    # the golden — not a shared pattern string — matching the two-engine posture.
    schema = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    null_arms: list[object] = []
    null_defaults: list[object] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("default", "sentinel") is None:
                null_defaults.append(node)
            for keyword in ("anyOf", "oneOf"):
                arms = node.get(keyword)
                if isinstance(arms, list) and {"type": "null"} in arms:
                    null_arms.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    assert null_arms == []
    assert null_defaults == []
    # The reserved-section carve-out is untouched: each stays the permissive `{}`
    # (an explicit `null` clears the structural phase, and the semantic
    # `reserved_section_present` rule — keyed on the raw key — owns the refusal).
    reserved = ("combat", "encounters", "builds", "growth", "economy", "targets")
    for section in reserved:
        assert schema["properties"][section] == {}


def test_golden_op_node_is_the_linear_shape():
    # The reshape (#527): the golden carries ONE `$defs/OpNode` object whose
    # `args.items` recurses the node union exactly once, with arity as if/then
    # clauses — and NO exponential-prone three-variant operator `oneOf` (its
    # OpenAPI `op` discriminator, which jsonschema evaluates by descending every
    # branch's `args`) survives anywhere.
    schema = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    defs = schema["$defs"]
    assert not (set(defs) & {"NaryOp", "BinaryOp", "UnaryOp"})
    op_node = defs["OpNode"]
    assert op_node["properties"]["args"]["items"] == {"$ref": "#/$defs/Node"}
    assert [c["then"]["properties"]["args"] for c in op_node["allOf"]] == [
        {"minItems": 2},
        {"minItems": 2, "maxItems": 2},
        {"minItems": 1, "maxItems": 1},
    ]
    assert defs["Node"]["oneOf"][0] == {"$ref": "#/$defs/OpNode"}
    # No operator discriminator (the exponential fingerprint) anywhere.
    op_discriminators: list[object] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            disc = node.get("discriminator")
            if isinstance(disc, dict) and disc.get("propertyName") == "op":
                op_discriminators.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    assert op_discriminators == []
