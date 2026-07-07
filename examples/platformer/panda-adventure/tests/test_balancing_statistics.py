"""Unit tests for the pipeline's deterministic statistics stages (#437 AC5).

These stages have no randomness of their own — a fixed sample list always
summarizes to the same distribution — so they are pinned on small,
hand-computable inputs. Fast tier, no engine.
"""

from __future__ import annotations

import math

import pytest

from balancing.statistics import Distribution, percentile, rate, summarize


def test_summarize_known_values() -> None:
    """A fixed list summarizes to hand-checked statistics."""
    d = summarize([1.0, 2.0, 3.0, 4.0, 5.0])
    assert isinstance(d, Distribution)
    assert d.n == 5
    assert d.mean == 3.0
    assert d.median == 3.0
    assert d.minimum == 1.0
    assert d.maximum == 5.0
    # p10 of [1..5] by linear interpolation over ranks 0..4: 0.10*4 = 0.4 ->
    # 1 + 0.4*(2-1) = 1.4; p90: 0.90*4 = 3.6 -> 4 + 0.6*(5-4) = 4.6.
    assert math.isclose(d.p10, 1.4)
    assert math.isclose(d.p90, 4.6)
    assert math.isclose(d.stdev, math.sqrt(2.0))  # population stdev of 1..5


def test_summarize_single_sample() -> None:
    """A one-element set has zero spread and every quantile equal to it."""
    d = summarize([7.5])
    assert (d.n, d.mean, d.median, d.p10, d.p90, d.minimum, d.maximum) == (
        1, 7.5, 7.5, 7.5, 7.5, 7.5, 7.5,
    )
    assert d.stdev == 0.0


def test_percentile_endpoints_and_interior() -> None:
    samples = [10.0, 20.0, 30.0, 40.0]
    assert percentile(samples, 0.0) == 10.0
    assert percentile(samples, 100.0) == 40.0
    # rank = 0.5*3 = 1.5 -> 20 + 0.5*(30-20) = 25.
    assert math.isclose(percentile(samples, 50.0), 25.0)


def test_percentile_is_order_independent() -> None:
    """Percentile sorts internally, so input order does not matter."""
    a = percentile([5.0, 1.0, 3.0, 2.0, 4.0], 25.0)
    b = percentile([1.0, 2.0, 3.0, 4.0, 5.0], 25.0)
    assert a == b


def test_percentile_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        percentile([], 50.0)
    with pytest.raises(ValueError):
        percentile([1.0], 101.0)


def test_summarize_rejects_empty() -> None:
    with pytest.raises(ValueError):
        summarize([])


def test_rate() -> None:
    assert rate(5, 200) == 0.025
    assert rate(0, 0) == 0.0
    assert rate(3, 3) == 1.0
