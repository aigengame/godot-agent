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

They also pin the published artifact itself: ``schema get structural`` must
reproduce the committed golden byte-for-byte, and the golden must stay portable
(ECMA-262 patterns only) and hardened (every ``patternProperties`` node closed).
"""

import json
from pathlib import Path

import jsonschema
import pytest

from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA

_GOLDEN = Path(__file__).parent / "goldens" / "structural_schema.json"

_VALID_MINIMAL = {"schema_version": "1.0.0", "meta": {"name": "smallest"}}


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


def test_map_key_trailing_newline_is_a_refusal_not_a_crash(run_cli, tmp_path):
    # A valid attribute under a map key carrying a trailing newline. Python `re`
    # would let the key match the id patternProperties, so only the
    # propertyNames newline guard catches it — as a structural refusal pointing
    # at the offending entry, NEVER an exit-4 model-construction crash.
    document = {
        **_VALID_MINIMAL,
        "attributes": {"items": {"ab\n": {"domain": "number", "base": {"direct": 5}}}},
    }
    exit_code, stdout, _ = run_cli(["design", "validate", _doc(tmp_path, document)])
    assert exit_code == 2  # specifically NOT 4
    refusals = _refusals(stdout)
    assert len(refusals) == 1
    assert refusals[0]["code"] == "structural_violation"
    assert refusals[0]["path"] == "/attributes/items/ab\n"


def test_scalar_id_trailing_newline_is_a_refusal_not_a_crash(run_cli, tmp_path):
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
    exit_code, stdout, _ = run_cli(["design", "validate", _doc(tmp_path, document)])
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
def test_divergence_sweep_never_takes_the_internal_path(document, run_cli, tmp_path):
    # Every near-miss must resolve as a clean accept (0) or a typed refusal (2);
    # a structural-schema/pydantic disagreement would surface as exit 4.
    exit_code, _stdout, _stderr = run_cli(
        ["design", "validate", _doc(tmp_path, document)]
    )
    assert exit_code in (0, 2), f"unexpected exit {exit_code} (engine-parity break?)"


# --- The published artifact: golden snapshot + portability/hardening ---------


def test_schema_get_structural_matches_golden(run_cli):
    # Byte-for-byte against the committed golden. To regenerate after a reviewed
    # model change, overwrite it deliberately and review the diff:
    #   uv run gda-balancing schema get structural \
    #     > libs/gda-balancing/tests/goldens/structural_schema.json
    exit_code, stdout, stderr = run_cli(["schema", "get", "structural"])
    assert (exit_code, stderr) == (0, "")
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
