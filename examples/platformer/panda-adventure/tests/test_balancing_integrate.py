"""Unit tests for the hand-rolled RK4 integrator (#440 — integration correctness).

The system-dynamics model is only as trustworthy as its integrator, so the
generic RK4 (``balancing.integrate``) is pinned against closed-form ODEs where
the exact answer is known — exponential growth/decay, ``sin`` from ``cos``, and
the logistic curve — plus its defining 4th-order convergence (halving the step
cuts the error by ~16×). Pure Python, no engine, no game code: the integrator
knows nothing about the game.
"""

from __future__ import annotations

import math

import pytest

from balancing.integrate import State, integrate, rk4_step


def _final(f, y0: State, t_end: float, dt: float) -> State:
    return integrate(f, y0, 0.0, t_end, dt)[1]


def test_exponential_growth() -> None:
    """dy/dt = y, y(0)=1 → y(1)=e, to RK4 accuracy."""
    y = _final(lambda t, y: (y[0],), (1.0,), 1.0, 1e-2)
    assert math.isclose(y[0], math.e, rel_tol=0.0, abs_tol=1e-8)


def test_exponential_decay() -> None:
    """dy/dt = -2y, y(0)=5 → y(t)=5 e^{-2t}."""
    y = _final(lambda t, y: (-2.0 * y[0],), (5.0,), 2.0, 1e-2)
    assert math.isclose(y[0], 5.0 * math.exp(-4.0), rel_tol=0.0, abs_tol=1e-8)


def test_sine_from_cosine() -> None:
    """dy/dt = cos(t), y(0)=0 → y(t)=sin(t): a time-DEPENDENT RHS (exercises the
    stage times, not just the state)."""
    y = _final(lambda t, y: (math.cos(t),), (0.0,), math.pi / 2, 1e-2)
    assert math.isclose(y[0], 1.0, rel_tol=0.0, abs_tol=1e-9)


def test_logistic_curve() -> None:
    """The logistic ODE dy/dt = r y (1 - y/K) — a first-order NONLINEAR ODE with
    a known closed form — integrates to its analytic value."""
    r, k, y0 = 1.0, 10.0, 1.0
    t_end = 5.0

    def f(t: float, y: State) -> tuple[float]:
        return (r * y[0] * (1.0 - y[0] / k),)

    analytic = k / (1.0 + (k - y0) / y0 * math.exp(-r * t_end))
    y = _final(f, (y0,), t_end, 1e-2)
    assert math.isclose(y[0], analytic, rel_tol=0.0, abs_tol=1e-6)


def test_coupled_system_circular_motion() -> None:
    """A 2-var coupled system dx/dt=y, dy/dt=-x traces the unit circle: after
    2π the state returns to the start (componentwise coupling works)."""
    y = _final(lambda t, s: (s[1], -s[0]), (1.0, 0.0), 2.0 * math.pi, 1e-3)
    assert math.isclose(y[0], 1.0, abs_tol=1e-6)
    assert math.isclose(y[1], 0.0, abs_tol=1e-6)


def test_fourth_order_convergence() -> None:
    """Halving the step cuts the global error by ~2^4 = 16× — the signature of a
    4th-order method (proves it is RK4, not a lower-order stepper)."""

    def err(dt: float) -> float:
        y = _final(lambda t, y: (y[0],), (1.0,), 1.0, dt)
        return abs(y[0] - math.e)

    coarse, fine = err(0.1), err(0.05)
    ratio = coarse / fine
    assert 12.0 < ratio < 20.0, f"convergence ratio {ratio} not ~16 (4th order)"


def test_single_step_matches_taylor() -> None:
    """One RK4 step of dy/dt=y from y=1 matches the 4th-order Taylor expansion
    1 + h + h²/2 + h³/6 + h⁴/24 exactly (the RK4 tableau reproduces it)."""
    h = 0.25
    (y1,) = rk4_step(lambda t, y: (y[0],), 0.0, (1.0,), h)
    taylor = 1 + h + h**2 / 2 + h**3 / 6 + h**4 / 24
    assert math.isclose(y1, taylor, rel_tol=0.0, abs_tol=1e-15)


def test_stop_predicate_ends_early() -> None:
    """The event ``stop`` predicate ends the drive at the first step whose new
    state satisfies it — far short of ``t_end`` (the generic stepper does not
    interpolate the crossing; ``dynamics`` layers that refinement on top)."""
    t, y = integrate(
        lambda t, y: (1.0,), (0.0,), 0.0, 100.0, 0.1, stop=lambda t, y: y[0] >= 1.0
    )
    assert y[0] >= 1.0
    assert t < 1.5  # ended right after crossing, not at t_end=100


def test_observer_samples_trajectory() -> None:
    """The per-step observer sees a monotonically advancing time trace."""
    samples: list[float] = []
    integrate(
        lambda t, y: (1.0,),
        (0.0,),
        0.0,
        1.0,
        0.25,
        observer=lambda t, y: samples.append(t),
    )
    assert samples[0] == 0.0
    assert samples == sorted(samples)
    assert math.isclose(samples[-1], 1.0)


def test_rejects_nonpositive_step() -> None:
    with pytest.raises(ValueError):
        integrate(lambda t, y: (0.0,), (0.0,), 0.0, 1.0, 0.0)
