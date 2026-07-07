"""The deterministic statistics stages of the pipeline (game-agnostic).

Pure aggregation over the per-run TTK/TTD samples the Monte-Carlo encounter
simulation produces: no randomness of its own, so a fixed sample list always
summarizes to the same distribution. These are the "deterministic statistics
stages" the pipeline-seam unit tests pin on fixed inputs (#437).

Percentiles use linear interpolation between the two nearest ranks (the
"inclusive"/numpy-default method), so p0 is the min and p100 is the max and a
small hand-computable list has exact, testable quantiles.
"""

from __future__ import annotations

import statistics as _stats
from dataclasses import dataclass


@dataclass(frozen=True)
class Distribution:
    """A summary of one sample set: count, central tendency, spread, and the
    p10/p90 tails that frame a TTK/TTD band."""

    n: int
    mean: float
    median: float
    p10: float
    p90: float
    minimum: float
    maximum: float
    stdev: float


def percentile(samples: list[float], q: float) -> float:
    """The ``q``-th percentile (0..100) by linear interpolation between ranks.

    Deterministic and dependency-free. ``q == 0`` returns the min, ``q == 100``
    the max; an interior ``q`` interpolates between the two bracketing sorted
    samples. Raises on an empty list or a ``q`` outside [0, 100].
    """
    if not samples:
        raise ValueError("percentile of an empty sample set")
    if not 0.0 <= q <= 100.0:
        raise ValueError(f"percentile q must be in [0, 100], got {q}")
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (q / 100.0) * (len(ordered) - 1)
    low = int(rank)
    frac = rank - low
    if low + 1 >= len(ordered):
        return ordered[-1]
    return ordered[low] + frac * (ordered[low + 1] - ordered[low])


def summarize(samples: list[float]) -> Distribution:
    """Reduce a sample list to a :class:`Distribution`. Raises on an empty list
    (an encounter always yields at least one run)."""
    if not samples:
        raise ValueError("cannot summarize an empty sample set")
    return Distribution(
        n=len(samples),
        mean=_stats.fmean(samples),
        median=_stats.median(samples),
        p10=percentile(samples, 10.0),
        p90=percentile(samples, 90.0),
        minimum=min(samples),
        maximum=max(samples),
        stdev=_stats.pstdev(samples) if len(samples) > 1 else 0.0,
    )


def rate(hits: int, total: int) -> float:
    """A simple hit rate in [0, 1] (e.g. clear rate, death rate). 0 total -> 0."""
    return hits / total if total else 0.0
