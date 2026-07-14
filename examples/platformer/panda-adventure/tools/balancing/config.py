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
  protection, use a targets file living with the copy. The run's own input
  artifacts — the targets file and the adapter file — are always protected.
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

# The message names of the typed accessor's JSON kinds. ``float`` means "any
# number" (bool excluded), matching JSON's single number type.
_KIND_NAMES = {
    str: "a string",
    int: "an integer",
    float: "a number",
    bool: "a boolean",
    list: "an array",
    dict: "an object",
}


def _invalid(path: Path, detail: str) -> ConfigError:
    return ConfigError("targets_invalid", f"targets file {path}: {detail}")


def _is_kind(value: Any, kind: type) -> bool:
    if kind is float:  # any JSON number; bool is not a number
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind is bool:
        return isinstance(value, bool)
    return isinstance(value, kind)


def _typed(
    path: Path, mapping: dict[str, Any], key: str, kind: type, where: str = ""
) -> Any:
    """The schema boundary's typed accessor: a missing key or a wrong-typed
    value (null included) refuses with ``targets_invalid`` at LOAD time —
    never a TypeError later during path resolution or the simulation."""
    label = f"{where}{key}"
    if key not in mapping:
        raise _invalid(path, f"missing the '{label}' key")
    value = mapping[key]
    if not _is_kind(value, kind):
        raise _invalid(
            path,
            f"'{label}' must be {_KIND_NAMES[kind]}, got {type(value).__name__}",
        )
    return value


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
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(
            "targets_unreadable", f"cannot read targets file {path}: {exc}"
        )
    except ValueError as exc:
        raise ConfigError(
            "targets_invalid", f"targets file {path} is not valid JSON: {exc}"
        )
    if not isinstance(doc, dict):
        raise ConfigError(
            "targets_invalid",
            f"targets file {path} must be a JSON object at the root, "
            f"got {type(doc).__name__}",
        )
    return doc


def load_pipeline_config(path: Path) -> PipelineConfig:
    """Parse a targets file (the per-game configuration) into a PipelineConfig.

    Every field is read through the typed accessor, so ANY malformed field —
    missing, null, or the wrong JSON type, at the root or nested — is a
    ``targets_invalid`` refusal here at the schema boundary.
    """
    doc = _read_targets_doc(path)
    player_model = _typed(path, doc, "player_model", dict)
    for key in PLAYER_MODEL_KEYS:
        _typed(path, player_model, key, float, "player_model.")
    sim = _typed(path, doc, "simulation", dict)
    waves: list[WaveTarget] = []
    for i, wave in enumerate(_typed(path, doc, "waves", list)):
        if not isinstance(wave, dict):
            raise _invalid(
                path, f"'waves[{i}]' must be an object, got {type(wave).__name__}"
            )
        where = f"waves[{i}]."
        waves.append(
            WaveTarget(
                wave=_typed(path, wave, "wave", int, where),
                ttk=_typed(path, wave, "ttk", float, where),
                ttd=_typed(path, wave, "ttd", float, where),
            )
        )
    roots = doc.get("no_write_roots", [])
    if not isinstance(roots, list) or any(not isinstance(r, str) for r in roots):
        raise _invalid(path, "'no_write_roots' must be an array of strings")
    return PipelineConfig(
        config_dir=_typed(path, doc, "config_dir", str),
        adapter=_typed(path, doc, "adapter", str),
        no_write_roots=tuple(roots),
        player_model_params=dict(player_model),
        sim=SimConfig(
            dt=_typed(path, sim, "dt", float, "simulation."),
            max_time=_typed(path, sim, "max_time", float, "simulation."),
            runs=_typed(path, sim, "runs", int, "simulation."),
            seed=_typed(path, sim, "seed", int, "simulation."),
        ),
        targets=Targets(
            waves=tuple(waves),
            tolerance=_typed(path, doc, "tolerance", float),
        ),
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
    """Parse the ``sd_model`` block of a targets file into an :class:`SdConfig`
    (typed like :func:`load_pipeline_config` — any malformed field refuses at
    the schema boundary)."""
    doc = _read_targets_doc(path)
    sd = _typed(path, doc, "sd_model", dict)
    p = _typed(path, sd, "params", dict, "sd_model.")
    cross = _typed(path, sd, "cross_validation", dict, "sd_model.")
    t = _typed(path, sd, "targets", dict, "sd_model.")
    growth = _typed(path, t, "growth", dict, "sd_model.targets.")
    difficulty = _typed(path, t, "difficulty", dict, "sd_model.targets.")
    checkpoints: list[LevelCheckpoint] = []
    for i, c in enumerate(
        _typed(path, growth, "checkpoints", list, "sd_model.targets.growth.")
    ):
        where = f"sd_model.targets.growth.checkpoints[{i}]"
        if not isinstance(c, dict):
            raise _invalid(path, f"'{where}' must be an object, got {type(c).__name__}")
        checkpoints.append(
            LevelCheckpoint(
                after_wave=_typed(path, c, "after_wave", int, f"{where}."),
                min_level=_typed(path, c, "min_level", int, f"{where}."),
            )
        )
    pw = "sd_model.params."
    return SdConfig(
        params=SdParams(
            dt=_typed(path, p, "dt", float, pw),
            max_wave_time=_typed(path, p, "max_wave_time", float, pw),
            growth_gain=_typed(path, p, "growth_gain", float, pw),
            heal_threshold_frac=_typed(path, p, "heal_threshold_frac", float, pw),
            heal_consume_rate=_typed(path, p, "heal_consume_rate", float, pw),
        ),
        cross_validation_tolerance=_typed(
            path, cross, "tolerance", float, "sd_model.cross_validation."
        ),
        targets=SdDesignTargets(
            min_final_level=_typed(
                path, growth, "min_final_level", int, "sd_model.targets.growth."
            ),
            level_checkpoints=tuple(checkpoints),
            final_wave_is_peak=_typed(
                path,
                difficulty,
                "final_wave_is_peak",
                bool,
                "sd_model.targets.difficulty.",
            ),
            expect_monotonic_ramp=_typed(
                path,
                difficulty,
                "expect_monotonic_ramp",
                bool,
                "sd_model.targets.difficulty.",
            ),
        ),
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
    """The paths a report must never land on: every configured
    ``no_write_roots`` tree (resolved against the targets file), the effective
    config dir itself — so a ``--config-dir`` override dir is protected too,
    though its surrounding tree is not (tree protection is declared config,
    never a code heuristic) — and the run's OWN input artifacts, the targets
    file and the adapter file, which are always protected against an ``--out``
    self-clobber regardless of declared roots."""
    roots = [resolve_against(targets_path.parent, r) for r in cfg.no_write_roots]
    roots.append(config_dir.resolve())
    roots.append(targets_path.resolve())
    roots.append(resolve_against(targets_path.parent, cfg.adapter))
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
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        # A broken adapter is a bad per-game input: a structured refusal, not
        # a traceback (process interrupts stay BaseException and pass through).
        raise ConfigError(
            "adapter_invalid", f"adapter {path} failed to import: {exc!r}"
        )
    if not callable(getattr(module, "load_inputs", None)):
        raise ConfigError(
            "adapter_invalid",
            f"adapter {path} does not export a callable load_inputs(config_dir)",
        )
    return module
