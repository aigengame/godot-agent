"""The targets file and the adapter contract — the pipeline's whole per-game surface.

One JSON document (the **targets file**) wires a game into the pipeline without
touching the package. Its schema (every path is resolved relative to the targets
file's own directory, so a targets file is relocatable with its game):

- ``config_dir``   — the game's config-authority directory, handed verbatim to
  the adapter.
- ``adapter``      — the per-game adapter: a Python file exporting
  ``load_inputs(config_dir: Path) -> model.GameInputs`` that maps the game's
  on-disk config shape into the generic model. It consumes the pipeline's
  public ``model`` types and lives OUTSIDE this package.
- ``no_write_roots`` — optional: directory trees a report ``--out`` must never
  land in (the game's config-authority chain). The effective config dir itself
  is always protected — even under a ``--config-dir`` override — but the
  override's SURROUNDING tree is not: tree-level protection comes only from
  these declared roots, so to run against a copied project with full
  protection, use a targets file living with the copy.
- ``player_model`` — the design player-model assumptions (``fire_interval``,
  ``accuracy``, ``dodge_chance``, ``engagement_distance``).
- ``simulation``   — the Monte-Carlo controls (``dt``, ``max_time``, ``runs``,
  ``seed``).
- ``tolerance`` / ``waves`` — the validate-mode design targets: the relative
  tolerance and the per-wave TTK/TTD intents.
- ``sd_model``     — the predict-mode block: ``params`` (``dt``,
  ``max_wave_time``, ``growth_gain``, ``heal_threshold_frac``,
  ``heal_consume_rate``), ``cross_validation.tolerance``, and ``targets``
  (``growth`` checkpoints/final level, ``difficulty`` ramp expectations).

Any free-form documentation keys (model assumptions, notes) are the game's own;
the pipeline ignores what it does not know.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .dynamics import SdParams
from .model import SimConfig, Targets, WaveTarget


class ConfigError(Exception):
    """A refused or invalid per-game input (targets file or adapter), carrying
    a stable machine-readable ``code`` alongside the human ``detail``."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# The design player-model assumptions every targets file must supply — the
# inputs ``model.build_player_model`` consumes. Validated here (the schema
# home) so a missing key is a structured refusal, not a KeyError traceback.
PLAYER_MODEL_KEYS = ("fire_interval", "accuracy", "dodge_chance", "engagement_distance")


@dataclass(frozen=True)
class PipelineConfig:
    """One targets file parsed: where the game's config lives, which adapter
    maps it, the protected write roots, the player-model assumptions, the sim
    controls, and the validate design targets."""

    config_dir: str
    adapter: str
    no_write_roots: tuple[str, ...]
    player_model_params: dict[str, Any]
    sim: SimConfig
    targets: Targets


def _read_targets_doc(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(
            "targets_unreadable", f"cannot read targets file {path}: {exc}"
        )
    except ValueError as exc:
        raise ConfigError(
            "targets_invalid", f"targets file {path} is not valid JSON: {exc}"
        )


def load_pipeline_config(path: Path) -> PipelineConfig:
    """Parse a targets file (the per-game configuration) into a PipelineConfig."""
    doc = _read_targets_doc(path)
    player_model = dict(doc.get("player_model", {}))
    missing = [k for k in PLAYER_MODEL_KEYS if k not in player_model]
    if missing:
        raise ConfigError(
            "targets_invalid",
            f"targets file {path} player_model is missing {missing}",
        )
    try:
        sim = doc["simulation"]
        return PipelineConfig(
            config_dir=doc["config_dir"],
            adapter=doc["adapter"],
            no_write_roots=tuple(doc.get("no_write_roots", ())),
            player_model_params=player_model,
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
    except KeyError as exc:
        raise ConfigError(
            "targets_invalid", f"targets file {path} is missing the {exc} key"
        )


# --- The sd_model block (predict mode) ---------------------------------------- #


@dataclass(frozen=True)
class LevelCheckpoint:
    """A growth design checkpoint: the minimum level the player should have
    reached after clearing a given wave."""

    after_wave: int
    min_level: int


@dataclass(frozen=True)
class SdDesignTargets:
    """The growth/difficulty design intent the prediction is checked against.
    ``final_wave_is_peak`` states whether the schedule's LAST wave should be
    the difficulty peak; ``expect_monotonic_ramp`` whether the ramp should
    never dip."""

    min_final_level: int
    level_checkpoints: tuple[LevelCheckpoint, ...]
    final_wave_is_peak: bool
    expect_monotonic_ramp: bool


@dataclass(frozen=True)
class SdConfig:
    """The ``sd_model`` block of a targets file: the model params/levers, the
    cross-validation tolerance, and the design targets."""

    params: SdParams
    cross_validation_tolerance: float
    targets: SdDesignTargets


def load_sd_config(path: Path) -> SdConfig:
    """Parse the ``sd_model`` block of a targets file into an :class:`SdConfig`."""
    doc = _read_targets_doc(path)
    try:
        sd = doc["sd_model"]
        p = sd["params"]
        t = sd["targets"]
        growth = t["growth"]
        return SdConfig(
            params=SdParams(
                dt=p["dt"],
                max_wave_time=p["max_wave_time"],
                growth_gain=p["growth_gain"],
                heal_threshold_frac=p["heal_threshold_frac"],
                heal_consume_rate=p["heal_consume_rate"],
            ),
            cross_validation_tolerance=sd["cross_validation"]["tolerance"],
            targets=SdDesignTargets(
                min_final_level=growth["min_final_level"],
                level_checkpoints=tuple(
                    LevelCheckpoint(
                        after_wave=c["after_wave"], min_level=c["min_level"]
                    )
                    for c in growth["checkpoints"]
                ),
                final_wave_is_peak=t["difficulty"]["final_wave_is_peak"],
                expect_monotonic_ramp=t["difficulty"]["expect_monotonic_ramp"],
            ),
        )
    except KeyError as exc:
        raise ConfigError(
            "targets_invalid", f"targets file {path} is missing the {exc} key"
        )


# --- Path resolution + the adapter plug-in ------------------------------------ #


def resolve_against(base_dir: Path, value: str) -> Path:
    """Resolve a targets-file path value: absolute passes through, relative
    resolves against the targets file's own directory."""
    p = Path(value)
    return p.resolve() if p.is_absolute() else (base_dir / p).resolve()


def resolve_config_dir(
    cfg: PipelineConfig, targets_path: Path, override: Path | None
) -> Path:
    """The effective config-authority dir: the ``--config-dir`` override wins,
    else the targets file's ``config_dir`` resolved against the file."""
    if override is not None:
        return override.resolve()
    return resolve_against(targets_path.parent, cfg.config_dir)


def forbidden_out_roots(
    cfg: PipelineConfig, targets_path: Path, config_dir: Path
) -> list[Path]:
    """The directory trees a report must never land in: every configured
    ``no_write_roots`` entry (resolved against the targets file) plus the
    effective config dir itself — so a ``--config-dir`` override dir is
    protected too, though its surrounding tree is not (tree protection is
    declared config, never a code heuristic)."""
    roots = [resolve_against(targets_path.parent, r) for r in cfg.no_write_roots]
    roots.append(config_dir.resolve())
    return roots


def load_adapter(cfg: PipelineConfig, targets_path: Path) -> ModuleType:
    """Import the per-game adapter named by the targets file and check its
    contract (a callable ``load_inputs``). The adapter is game-side code
    consuming the pipeline's public ``model`` types — never the other way
    around."""
    path = resolve_against(targets_path.parent, cfg.adapter)
    if not path.is_file():
        raise ConfigError("adapter_not_found", f"adapter file {path} does not exist")
    spec = importlib.util.spec_from_file_location(
        f"_balancing_adapter_{path.stem}", path
    )
    if spec is None or spec.loader is None:
        raise ConfigError("adapter_invalid", f"cannot import adapter {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "load_inputs", None)):
        raise ConfigError(
            "adapter_invalid",
            f"adapter {path} does not export a callable load_inputs(config_dir)",
        )
    return module
