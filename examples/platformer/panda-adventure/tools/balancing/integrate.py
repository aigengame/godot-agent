"""A hand-rolled fixed-step RK4 integrator (game-agnostic, stdlib-only).

The system-dynamics half of the balancing pipeline integrates a first-order
nonlinear ODE system (``dynamics``) with the classical 4th-order Runge-Kutta
method. The pipeline stays pure-Python with NO dependency (no numpy/scipy), so
the integrator is hand-rolled here: a few lines of the textbook RK4 tableau
over a bare ``tuple[float, ...]`` state vector.

The integrator is deliberately generic — it knows nothing about stocks, flows,
or the game. A derivative function ``f(t, y) -> dy`` and a step size are all it
needs, so the same routine is pinned in unit tests against closed-form ODEs
(exponential growth, decay, ``sin``, the logistic curve) where its error is the
known ``O(dt^4)`` of RK4, independent of any game model (the "integration
correctness" the DoD asks for).

State is a plain ``tuple[float, ...]`` (immutable, hashable, trivially copyable);
the derivative returns a tuple of the same arity. The stepper does the four RK4
stage evaluations and the weighted combine; the driver loops fixed steps with an
optional event ``stop`` predicate and per-step ``observer`` so a caller can
detect a crossing (a wave cleared, the Player dead) and record a trajectory
without the integrator knowing what those mean.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

# A state vector and the derivative over it. Both are bare float tuples so the
# integrator depends on nothing (no numpy): the ODE system's shape is the
# caller's concern.
State = tuple[float, ...]
Deriv = Callable[[float, State], Sequence[float]]


def _axpy(y: State, dy: Sequence[float], h: float) -> State:
    """``y + h * dy`` componentwise — one RK4 stage displacement."""
    return tuple(yi + h * di for yi, di in zip(y, dy))


def rk4_step(f: Deriv, t: float, y: State, dt: float) -> State:
    """One classical RK4 step from ``(t, y)`` over ``dt`` (the 4th-order tableau).

    Evaluates the four stage slopes ``k1..k4`` and returns the weighted combine
    ``y + dt/6 (k1 + 2 k2 + 2 k3 + k4)``. Pure: ``f`` must not mutate ``y``.
    """
    k1 = f(t, y)
    k2 = f(t + 0.5 * dt, _axpy(y, k1, 0.5 * dt))
    k3 = f(t + 0.5 * dt, _axpy(y, k2, 0.5 * dt))
    k4 = f(t + dt, _axpy(y, k3, dt))
    return tuple(
        yi + (dt / 6.0) * (a + 2.0 * b + 2.0 * c + d)
        for yi, a, b, c, d in zip(y, k1, k2, k3, k4)
    )


def integrate(
    f: Deriv,
    y0: State,
    t0: float,
    t_end: float,
    dt: float,
    observer: Callable[[float, State], None] | None = None,
    stop: Callable[[float, State], bool] | None = None,
) -> tuple[float, State]:
    """Fixed-step RK4 from ``t0`` to ``t_end`` (or until ``stop`` fires).

    Steps ``dt`` at a time, clamping the final step so ``t`` lands exactly on
    ``t_end``. Before each step the ``observer`` (if given) sees the current
    ``(t, y)`` — the sampling hook for a trajectory record. After each step the
    ``stop`` predicate (if given) is checked on the NEW ``(t, y)``; the first
    ``True`` ends the drive and returns that state (event integration is layered
    on top of this in ``dynamics`` with a crossing refinement). Returns the final
    ``(t, y)``.
    """
    if dt <= 0.0:
        raise ValueError(f"dt must be positive, got {dt}")
    t, y = t0, y0
    while t < t_end:
        if observer is not None:
            observer(t, y)
        step = min(dt, t_end - t)
        y = rk4_step(f, t, y, step)
        t += step
        if stop is not None and stop(t, y):
            break
    if observer is not None:
        observer(t, y)
    return t, y
