"""The canonical-emission seam's own contract (bADR-0005).

Every emitted document flows through this one seam, so its properties are
pinned here: strict JSON (non-finite numbers raise instead of emitting the
non-JSON ``NaN``/``Infinity`` tokens), sorted keys, a single trailing LF,
and non-ASCII passthrough.
"""

import math

import pytest

from gda_balancing.interfaces.cli.rendering import canonical_json


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_never_serialize(value):
    with pytest.raises(ValueError):
        canonical_json({"value": value})


def test_canonical_properties():
    assert canonical_json({"b": 1, "a": {"d": None, "c": "é"}}) == (
        '{"a": {"c": "é", "d": null}, "b": 1}\n'
    )
