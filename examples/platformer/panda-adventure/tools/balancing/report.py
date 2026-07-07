"""Validate mode: per-wave measured TTK/TTD vs design targets (gADR-0011, #437).

Runs the Monte-Carlo encounter simulation over every Wave, summarizes the
per-run samples, and checks each Wave's median TTK/TTD against its design target
within a configurable relative tolerance. This is a PURE READ of the JSON
authority: it produces a report object and writes NOTHING back to config — this
slice is validate-only. Emitting the report to stdout or an ``--out`` path is
the caller's job (``cli``); those paths are never a config file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import statistics
from .encounter import run_wave
from .model import GameData, PlayerModel, SimConfig, Targets, WaveTarget
from .statistics import Distribution


@dataclass(frozen=True)
class PipelineConfig:
    """One targets file parsed: where the config lives, the player-model
    assumptions, the sim controls, and the design targets."""

    config_dir: str
    player_model_params: dict[str, Any]
    sim: SimConfig
    targets: Targets


def load_pipeline_config(path: Path) -> PipelineConfig:
    """Parse a targets file (the per-game configuration) into a PipelineConfig."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    sim = doc["simulation"]
    return PipelineConfig(
        config_dir=doc["config_dir"],
        player_model_params=dict(doc["player_model"]),
        sim=SimConfig(
            dt=sim["dt"],
            max_time=sim["max_time"],
            runs=sim["runs"],
            seed=sim["seed"],
        ),
        targets=Targets(
            waves=tuple(
                WaveTarget(wave=w["wave"], ttk=w["ttk"], ttd=w["ttd"])
                for w in doc["waves"]
            ),
            tolerance=doc["tolerance"],
        ),
    )


@dataclass(frozen=True)
class WaveReport:
    """One Wave's validate result: the measured TTK/TTD distributions and clear/
    death rates, its targets, and whether the medians fall within tolerance
    (None when the Wave has no target — report only)."""

    wave: int
    ttk: Distribution
    ttd: Distribution
    clear_rate: float
    death_rate: float
    target_ttk: float | None
    target_ttd: float | None
    ttk_within_tolerance: bool | None
    ttd_within_tolerance: bool | None


@dataclass(frozen=True)
class ValidationReport:
    """The whole validate run: the tolerance used and one report per Wave."""

    tolerance: float
    runs: int
    seed: int
    waves: tuple[WaveReport, ...]

    @property
    def all_within_tolerance(self) -> bool:
        """True iff every Wave that HAS a target is within tolerance on both
        TTK and TTD. A run with no targets at all is vacuously within."""
        checks = [
            ok
            for w in self.waves
            for ok in (w.ttk_within_tolerance, w.ttd_within_tolerance)
            if ok is not None
        ]
        return all(checks)


def _within(measured: float, target: float | None, tolerance: float) -> bool | None:
    """Whether ``measured`` is within a symmetric ``tolerance`` band of the
    target (None target -> None, i.e. report-only)."""
    if target is None:
        return None
    return abs(measured - target) <= tolerance * target


def run_validation(
    game: GameData,
    player: PlayerModel,
    sim: SimConfig,
    targets: Targets,
) -> ValidationReport:
    """Simulate every Wave and compare the median TTK/TTD to its design target.

    Each Wave draws from its own ``seed + wave.index`` RNG stream, so the whole
    report is reproducible from ``sim.seed`` yet waves stay independent. Reads
    only; produces no config.
    """
    wave_reports: list[WaveReport] = []
    for wave in game.waves:
        samples = run_wave(
            player,
            wave,
            game.kinds,
            game.combat,
            sim.dt,
            sim.max_time,
            sim.runs,
            seed=sim.seed + wave.index,
        )
        ttk = statistics.summarize(samples.ttk)
        ttd = statistics.summarize(samples.ttd)
        target = targets.for_wave(wave.index)
        target_ttk = target.ttk if target else None
        target_ttd = target.ttd if target else None
        wave_reports.append(
            WaveReport(
                wave=wave.index,
                ttk=ttk,
                ttd=ttd,
                clear_rate=statistics.rate(samples.clears, samples.runs),
                death_rate=statistics.rate(samples.deaths, samples.runs),
                target_ttk=target_ttk,
                target_ttd=target_ttd,
                ttk_within_tolerance=_within(ttk.median, target_ttk, targets.tolerance),
                ttd_within_tolerance=_within(ttd.median, target_ttd, targets.tolerance),
            )
        )
    return ValidationReport(
        tolerance=targets.tolerance,
        runs=sim.runs,
        seed=sim.seed,
        waves=tuple(wave_reports),
    )


def _distribution_dict(d: Distribution) -> dict[str, Any]:
    return {
        "n": d.n,
        "mean": d.mean,
        "median": d.median,
        "p10": d.p10,
        "p90": d.p90,
        "min": d.minimum,
        "max": d.maximum,
        "stdev": d.stdev,
    }


def report_to_dict(report: ValidationReport) -> dict[str, Any]:
    """The report as a plain JSON-serializable dict (for ``--out`` / stdout)."""
    return {
        "tolerance": report.tolerance,
        "runs": report.runs,
        "seed": report.seed,
        "all_within_tolerance": report.all_within_tolerance,
        "waves": [
            {
                "wave": w.wave,
                "ttk": _distribution_dict(w.ttk),
                "ttd": _distribution_dict(w.ttd),
                "clear_rate": w.clear_rate,
                "death_rate": w.death_rate,
                "target_ttk": w.target_ttk,
                "target_ttd": w.target_ttd,
                "ttk_within_tolerance": w.ttk_within_tolerance,
                "ttd_within_tolerance": w.ttd_within_tolerance,
            }
            for w in report.waves
        ],
    }


def format_text(report: ValidationReport) -> str:
    """A compact human-readable rendering of the validate report."""

    def mark(ok: bool | None) -> str:
        return "  --" if ok is None else ("  OK" if ok else "FAIL")

    lines = [
        f"Balancing validate — {report.runs} runs, seed {report.seed}, "
        f"tolerance {report.tolerance:.0%}",
        f"{'wave':>4}  {'TTK(med)':>9} {'target':>7} {'':>4}  "
        f"{'TTD(med)':>9} {'target':>7} {'':>4}  {'clear':>5} {'death':>5}",
    ]
    for w in report.waves:
        tttk = "-" if w.target_ttk is None else f"{w.target_ttk:.1f}"
        tttd = "-" if w.target_ttd is None else f"{w.target_ttd:.1f}"
        lines.append(
            f"{w.wave:>4}  {w.ttk.median:>9.2f} {tttk:>7} {mark(w.ttk_within_tolerance)}  "
            f"{w.ttd.median:>9.2f} {tttd:>7} {mark(w.ttd_within_tolerance)}  "
            f"{w.clear_rate:>5.0%} {w.death_rate:>5.0%}"
        )
    lines.append(
        "RESULT: "
        + ("all within tolerance" if report.all_within_tolerance else "OUT OF TOLERANCE")
    )
    return "\n".join(lines)
