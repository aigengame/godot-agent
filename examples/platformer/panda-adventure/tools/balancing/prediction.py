"""Predict mode: the long-term SD balance-prediction report + MC cross-validation.

The system-dynamics counterpart of validate mode (``report``): it integrates the
whole-run growth/economy trajectory (``dynamics``) and renders it against the
difficulty/growth design targets, then cross-validates the macro model against
the Monte-Carlo micro engine on their overlapping domain. Like validate, it is a
PURE READ of the game's config authority — it builds a report object and writes
NOTHING back to config (the ``cli`` layer owns emission, and refuses an
``--out`` inside a protected tree).

Three sections:

- **Trajectory** — per wave: the SD clear/death time, the HP band, the accrued
  stocks (EXP/level, currency, items in/out), and the difficulty index. Plus
  the run verdict (did the designed kit clear the schedule?) and end stocks.
- **Design targets** — the growth curve (per-wave level checkpoints + a minimum
  final level) and the difficulty ramp (is the final wave the peak?) checked
  against the targets file's intent, mirroring validate's tolerance verdict.
- **Cross-validation** — per overlapping wave, the SD prediction in the reduced
  bare-brawl scenario (growth + healing off) vs the MC median it must not
  contradict: SD clear time ↔ MC median TTK where both clear, SD death time ↔ MC
  median TTD where both die, within the DOCUMENTED cross-validation tolerance
  (looser than the MC-level validate tolerance because the SD model is a
  deterministic mean-field aggregate — see ``dynamics``).

Exit contract (in ``cli``): 0 when the prediction meets its design targets AND
every overlapping wave cross-validates within tolerance; 1 when either fails; 2
for a refused/invalid input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import report
from .config import SdConfig
from .dynamics import (
    WaveOutcome,
    build_wave_dynamics,
    run_scenario,
    run_wave_overlap,
)
from .model import GameData, GrowthEconomy, PlayerModel, SimConfig, Targets

# --- Cross-validation against the MC engine ---------------------------------- #


@dataclass(frozen=True)
class CrossCheck:
    """One wave's SD↔MC cross-validation on their overlapping quantity.

    ``metric`` names which quantity the domains share on this wave — ``"ttk"``
    (both clear: SD clear time vs MC median TTK) or ``"ttd"`` (both die: SD death
    time vs MC median TTD). ``clearing_agreement`` is whether the two models agree
    on the outcome (clear vs die) at all; when they disagree, the metric compare
    is undefined (``within_tolerance`` is False)."""

    wave: int
    metric: str
    sd_value: float | None
    mc_value: float | None
    rel_error: float | None
    clearing_agreement: bool
    within_tolerance: bool
    mc_clear_rate: float
    mc_death_rate: float


def _cross_check(
    wave: int,
    sd: WaveOutcome,
    mc_ttk_median: float,
    mc_ttd_median: float,
    mc_clear_rate: float,
    mc_death_rate: float,
    tolerance: float,
) -> CrossCheck:
    """Compare one wave's SD overlap prediction to the MC medians.

    MC's majority outcome (clear_rate ≥ 0.5) is the reference; SD must agree on
    clearing, and match the median of whichever quantity is defined there (TTK if
    both clear, TTD if both die) within ``tolerance``.
    """
    mc_clears = mc_clear_rate >= 0.5
    clearing_agreement = sd.cleared == mc_clears
    if mc_clears:
        metric, sd_value, mc_value = "ttk", sd.clear_time, mc_ttk_median
    else:
        metric, sd_value, mc_value = "ttd", sd.death_time, mc_ttd_median
    rel_error: float | None = None
    within = False
    if clearing_agreement and sd_value is not None and mc_value not in (None, 0.0):
        rel_error = abs(sd_value - mc_value) / mc_value
        within = rel_error <= tolerance
    return CrossCheck(
        wave=wave,
        metric=metric,
        sd_value=sd_value,
        mc_value=mc_value,
        rel_error=rel_error,
        clearing_agreement=clearing_agreement,
        within_tolerance=within,
        mc_clear_rate=mc_clear_rate,
        mc_death_rate=mc_death_rate,
    )


# --- The prediction report --------------------------------------------------- #


@dataclass(frozen=True)
class PredictionReport:
    """The whole predict run: the SD trajectory, the design-target verdicts, and
    the MC cross-validation."""

    waves: tuple[WaveOutcome, ...]
    cleared_schedule: bool
    died_at_wave: int | None
    final_level: int
    final_hp: float
    final_currency: float
    final_items: dict[str, float]
    # Design-target verdicts.
    min_final_level: int
    final_level_ok: bool
    checkpoint_ok: bool
    final_wave_is_peak_expected: bool
    final_wave_is_peak_actual: bool
    final_wave_peak_ok: bool
    monotonic_ramp_expected: bool
    monotonic_ramp_actual: bool
    monotonic_ramp_ok: bool
    # Cross-validation.
    cross_validation_tolerance: float
    cross_checks: tuple[CrossCheck, ...]

    @property
    def design_targets_ok(self) -> bool:
        """Every growth/difficulty design target is met — including the
        monotonic-ramp target (a configured difficulty intent must gate the
        verdict, not just be reported)."""
        return (
            self.final_level_ok
            and self.checkpoint_ok
            and self.final_wave_peak_ok
            and self.monotonic_ramp_ok
        )

    @property
    def cross_validation_ok(self) -> bool:
        """Every overlapping wave agrees with MC within tolerance."""
        return all(
            c.clearing_agreement and c.within_tolerance for c in self.cross_checks
        )

    @property
    def ok(self) -> bool:
        """The overall predict verdict (design targets met AND MC-consistent)."""
        return self.design_targets_ok and self.cross_validation_ok


def run_prediction(
    game: GameData,
    econ: GrowthEconomy,
    player: PlayerModel,
    sim: SimConfig,
    sd: SdConfig,
) -> PredictionReport:
    """Integrate the SD trajectory, check the design targets, and cross-validate
    against the MC engine. Pure read; produces no config.
    """
    dynamics = build_wave_dynamics(game, econ, player)
    run = run_scenario(dynamics, sd.params, econ)

    # Design-target verdicts.
    final_level_ok = run.final_level >= sd.targets.min_final_level
    by_index = {o.index: o for o in run.waves}
    checkpoint_ok = all(
        (o := by_index.get(c.after_wave)) is not None
        and o.cleared
        and o.level_end >= c.min_level
        for c in sd.targets.level_checkpoints
    )
    difficulties = [o.difficulty for o in run.waves]
    peak_actual = bool(difficulties) and difficulties[-1] == max(difficulties)
    peak_ok = peak_actual == sd.targets.final_wave_is_peak
    monotonic_actual = all(a <= b for a, b in zip(difficulties, difficulties[1:]))
    monotonic_ramp_ok = monotonic_actual == sd.targets.expect_monotonic_ramp

    # Cross-validation against MC on the overlapping (bare-brawl) scenario.
    mc = report.run_validation(game, player, sim, _no_targets())
    mc_by_wave = {w.wave: w for w in mc.waves}
    checks: list[CrossCheck] = []
    for wd in dynamics:
        sd_overlap = run_wave_overlap(wd, sd.params, econ)
        m = mc_by_wave[wd.index]
        checks.append(
            _cross_check(
                wave=wd.index,
                sd=sd_overlap,
                mc_ttk_median=m.ttk.median,
                mc_ttd_median=m.ttd.median,
                mc_clear_rate=m.clear_rate,
                mc_death_rate=m.death_rate,
                tolerance=sd.cross_validation_tolerance,
            )
        )

    return PredictionReport(
        waves=run.waves,
        cleared_schedule=run.cleared_schedule,
        died_at_wave=run.died_at_wave,
        final_level=run.final_level,
        final_hp=run.final_hp,
        final_currency=run.final_currency,
        final_items=run.final_items,
        min_final_level=sd.targets.min_final_level,
        final_level_ok=final_level_ok,
        checkpoint_ok=checkpoint_ok,
        final_wave_is_peak_expected=sd.targets.final_wave_is_peak,
        final_wave_is_peak_actual=peak_actual,
        final_wave_peak_ok=peak_ok,
        monotonic_ramp_expected=sd.targets.expect_monotonic_ramp,
        monotonic_ramp_actual=monotonic_actual,
        monotonic_ramp_ok=monotonic_ramp_ok,
        cross_validation_tolerance=sd.cross_validation_tolerance,
        cross_checks=tuple(checks),
    )


def _no_targets() -> Targets:
    """A ``Targets`` with no per-wave design targets — the cross-validation only
    needs MC's MEASURED medians/rates, never the validate-mode target compare."""
    return Targets(waves=(), tolerance=0.0)


# --- Rendering --------------------------------------------------------------- #


def _wave_dict(o: WaveOutcome) -> dict[str, Any]:
    return {
        "wave": o.index,
        "cleared": o.cleared,
        "died": o.died,
        "clear_time": o.clear_time,
        "death_time": o.death_time,
        "hp_start": o.hp_start,
        "hp_end": o.hp_end,
        "hp_min": o.hp_min,
        "exp_end": o.exp_end,
        "exp_gained": o.exp_gained,
        "level_end": o.level_end,
        "currency_end": o.currency_end,
        "items_start": dict(o.items_start),
        "items_end": dict(o.items_end),
        "difficulty": o.difficulty,
    }


def _cross_dict(c: CrossCheck) -> dict[str, Any]:
    return {
        "wave": c.wave,
        "metric": c.metric,
        "sd_value": c.sd_value,
        "mc_value": c.mc_value,
        "rel_error": c.rel_error,
        "clearing_agreement": c.clearing_agreement,
        "within_tolerance": c.within_tolerance,
        "mc_clear_rate": c.mc_clear_rate,
        "mc_death_rate": c.mc_death_rate,
    }


def report_to_dict(report: PredictionReport) -> dict[str, Any]:
    """The prediction as a plain JSON-serializable dict (for ``--out`` / stdout)."""
    return {
        "cleared_schedule": report.cleared_schedule,
        "died_at_wave": report.died_at_wave,
        "final_level": report.final_level,
        "final_hp": report.final_hp,
        "final_currency": report.final_currency,
        "final_items": dict(report.final_items),
        "design_targets": {
            "min_final_level": report.min_final_level,
            "final_level_ok": report.final_level_ok,
            "checkpoint_ok": report.checkpoint_ok,
            "final_wave_is_peak_expected": report.final_wave_is_peak_expected,
            "final_wave_is_peak_actual": report.final_wave_is_peak_actual,
            "final_wave_peak_ok": report.final_wave_peak_ok,
            "monotonic_ramp_expected": report.monotonic_ramp_expected,
            "monotonic_ramp_actual": report.monotonic_ramp_actual,
            "monotonic_ramp_ok": report.monotonic_ramp_ok,
            "all_ok": report.design_targets_ok,
        },
        "cross_validation": {
            "tolerance": report.cross_validation_tolerance,
            "all_ok": report.cross_validation_ok,
            "waves": [_cross_dict(c) for c in report.cross_checks],
        },
        "ok": report.ok,
        "waves": [_wave_dict(o) for o in report.waves],
    }


def format_text(report: PredictionReport) -> str:
    """A compact human-readable rendering of the prediction report."""

    def mark(ok: bool) -> str:
        return "OK" if ok else "FAIL"

    def opt(v: float | None, fmt: str) -> str:
        return "-" if v is None else format(v, fmt)

    items = sorted(report.final_items)
    item_headers = "".join(f" {name[:5]:>5}" for name in items)
    lines = [
        "Balancing predict — long-term SD trajectory vs design + MC cross-validation",
        f"{'wave':>4}  {'clear':>7} {'death':>7}  {'HP end':>7} {'HP min':>7}  "
        f"{'EXP':>6} {'Lv':>3}  {'cur':>6}{item_headers}  {'diff':>6}",
    ]
    for o in report.waves:
        item_cells = "".join(f" {o.items_end.get(name, 0.0):>5.2f}" for name in items)
        lines.append(
            f"{o.index:>4}  {opt(o.clear_time, '7.2f')} {opt(o.death_time, '7.2f')}  "
            f"{o.hp_end:>7.1f} {o.hp_min:>7.1f}  {o.exp_end:>6.0f} {o.level_end:>3}  "
            f"{o.currency_end:>6.0f}{item_cells}  {o.difficulty:>6.3f}"
        )
    verdict = (
        f"cleared the schedule (final level {report.final_level})"
        if report.cleared_schedule
        else f"DIED at wave {report.died_at_wave} (final level {report.final_level})"
    )
    lines.append(f"RUN: {verdict}")
    lines.append(
        f"DESIGN: final level {report.final_level} >= {report.min_final_level} "
        f"[{mark(report.final_level_ok)}]  checkpoints [{mark(report.checkpoint_ok)}]  "
        f"final-wave-is-peak {report.final_wave_is_peak_actual} "
        f"(want {report.final_wave_is_peak_expected}) [{mark(report.final_wave_peak_ok)}]  "
        f"monotonic-ramp {report.monotonic_ramp_actual} "
        f"(want {report.monotonic_ramp_expected}) [{mark(report.monotonic_ramp_ok)}]"
    )
    lines.append(
        f"CROSS-VALIDATION vs MC (tolerance {report.cross_validation_tolerance:.0%}):"
    )
    for c in report.cross_checks:
        err = "-" if c.rel_error is None else f"{c.rel_error:.1%}"
        ok = c.clearing_agreement and c.within_tolerance
        lines.append(
            f"{c.wave:>4}  {c.metric.upper()}  SD {opt(c.sd_value, '7.2f')} vs "
            f"MC {opt(c.mc_value, '7.2f')}  err {err:>6}  "
            f"(MC clear {c.mc_clear_rate:.0%}/death {c.mc_death_rate:.0%})  [{mark(ok)}]"
        )
    lines.append(
        "RESULT: "
        + (
            "prediction meets design targets and is MC-consistent"
            if report.ok
            else "PREDICTION FAILED (design target or MC cross-validation)"
        )
    )
    return "\n".join(lines)
