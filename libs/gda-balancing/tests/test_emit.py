"""The canonical-emission seam's own contract (bADR-0005).

Every emitted document flows through this one seam, so its properties are
pinned here: strict JSON (non-finite numbers raise instead of emitting the
non-JSON ``NaN``/``Infinity`` tokens), sorted keys, a single trailing LF,
non-ASCII passthrough, and the absent-or-typed contract's ``model_payload``
precondition (PR #527 multi#4).
"""

import math

import pytest

from gda_balancing.interfaces.cli.schema import SchemaArtifact
from gda_balancing.interfaces.cli.rendering import canonical_json, model_payload
from gda_balancing.schema.artifacts import generate_catalog, generate_structural_schema


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_never_serialize(value):
    with pytest.raises(ValueError):
        canonical_json({"value": value})


def test_canonical_properties():
    assert canonical_json({"b": 1, "a": {"d": None, "c": "é"}}) == (
        '{"a": {"c": "é", "d": null}, "b": 1}\n'
    )


def _contains_none(value) -> bool:
    """Whether a ``None`` appears anywhere — as a member value, an array element,
    or the value itself."""
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_contains_none(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_none(v) for v in value)
    return False


@pytest.mark.parametrize("artifact", [generate_structural_schema(), generate_catalog()])
def test_artifact_payload_carries_no_none(artifact):
    # `model_payload` now dumps with `exclude_none=True`. The dict-rooted artifact
    # models (structural schema, catalog) are emitted verbatim, but only because
    # §1's null-arm stripping leaves NO `None` in them — this precondition is what
    # keeps `exclude_none` from ever silently dropping a schema member. Asserted
    # on the real artifacts, through the exact emission path.
    payload = model_payload(SchemaArtifact(root=artifact))
    assert not _contains_none(payload), payload
