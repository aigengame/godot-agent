"""The balancing pipeline CLI: ``python -m balancing {validate,predict} ...``.

Two modes over the SAME JSON authority + targets file, both a PURE READ that
writes NOTHING to config (gADR-0011):

- **validate** (#437) — runs the Monte-Carlo encounter simulation and emits a
  per-Wave TTK/TTD-vs-targets report. Exit 0 when every targeted Wave is within
  tolerance, 1 when any is out of tolerance.
- **predict** (#440) — integrates the long-term system-dynamics growth/economy
  trajectory and emits it against the difficulty/growth design targets, plus the
  MC cross-validation. Exit 0 when the prediction meets its design targets AND
  every overlapping Wave cross-validates within tolerance, 1 otherwise.

Emission goes to stdout (text or ``--json``) or an ``--out`` path. An ``--out``
inside the game's ``data/`` tree (the whole authority chain — authored JSON,
schemas, derived Resources) or inside the configured authority dir is REFUSED
with a structured error before anything runs (exit 2, distinct from the verdict).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import game_config, prediction, report

# Default targets file (this game's per-game configuration), next to this module.
_DEFAULT_TARGETS = Path(__file__).resolve().parent / "panda_adventure.targets.json"
# The game root is tools/balancing/ -> tools/ -> <game>. config_dir is resolved
# against it when the targets file gives a relative path.
_GAME_ROOT = Path(__file__).resolve().parents[2]

# The usage/refusal exit code — distinct from the tolerance verdict (0/1).
EXIT_REFUSED = 2


def forbidden_out_roots(config_dir: Path) -> list[Path]:
    """The directory trees a report must never land in (gADR-0011: this slice
    writes nothing to config).

    The game's whole ``data/`` tree is forbidden — not just ``data/json``: it
    is the config authority CHAIN (authored JSON + the schemas that validate it
    + the derived ``data/generated`` Resources), and no report legitimately
    belongs anywhere in it. The resolved authority dir itself (and its parent
    ``data/`` tree, for a copied project root) is forbidden too, so a
    ``--config-dir`` pointing at an e2e copy is equally protected.
    """
    roots = [(_GAME_ROOT / "data").resolve(), config_dir.resolve()]
    if config_dir.resolve().parent.name == "data":
        roots.append(config_dir.resolve().parent)
    return roots


def _refuse_authority_out(out: Path, config_dir: Path) -> str | None:
    """The reason ``--out`` is refused (a path inside an authority tree), or
    None when it is safe. Resolves the path first so ``../`` cannot sneak in."""
    resolved = out.resolve()
    for root in forbidden_out_roots(config_dir):
        if resolved == root or resolved.is_relative_to(root):
            return (
                f"--out {out} resolves into the config authority tree {root}; "
                "the Balancing pipeline writes nothing to config "
                "(gADR-0011) — choose a path outside data/"
            )
    return None


def _guard_out(out: Path | None, config_dir: Path) -> int | None:
    """The shared no-write guard both modes run BEFORE the sim: if ``out`` lands
    in an authority tree, print the structured error and return ``EXIT_REFUSED``;
    otherwise None (safe to proceed)."""
    if out is None:
        return None
    reason = _refuse_authority_out(out, config_dir)
    if reason is None:
        return None
    print(
        json.dumps({"error": "out_path_in_authority", "detail": reason}),
        file=sys.stderr,
    )
    return EXIT_REFUSED


def _emit(doc: dict, text: str, out: Path | None, as_json: bool) -> None:
    """Emit a report: to ``--out`` as JSON, else JSON or text to stdout."""
    if out is not None:
        out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    elif as_json:
        print(json.dumps(doc, indent=2))
    else:
        print(text)


def _resolve_config_dir(config_dir: str, targets_path: Path) -> Path:
    """Resolve the targets file's ``config_dir`` to an absolute path.

    Absolute paths pass through; a relative path resolves against the game root
    (so the committed ``data/json`` default works from any CWD), then falls back
    to the targets file's own directory.
    """
    p = Path(config_dir)
    if p.is_absolute():
        return p
    from_root = _GAME_ROOT / p
    if from_root.exists():
        return from_root
    return (targets_path.parent / p).resolve()


def _add_common_args(p: argparse.ArgumentParser) -> None:
    """The args every mode shares (both read the same authority + targets file and
    emit the same way, writing nothing to config)."""
    p.add_argument(
        "--targets",
        type=Path,
        default=_DEFAULT_TARGETS,
        help="targets file (default: the committed panda_adventure targets)",
    )
    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="override the JSON authority dir (default: the targets file's config_dir)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the JSON report to this path (never a config file); default stdout",
    )
    p.add_argument("--seed", type=int, default=None, help="override the base seed")
    p.add_argument("--runs", type=int, default=None, help="override the run count")
    p.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON (default: human-readable text)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="balancing", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser(
        "validate",
        help="report per-wave TTK/TTD vs design targets (writes nothing to config)",
    )
    _add_common_args(validate)
    predict = sub.add_parser(
        "predict",
        help="long-term SD growth/economy prediction + MC cross-validation "
        "(writes nothing to config)",
    )
    _add_common_args(predict)
    return parser


def _sim_with_overrides(sim, seed: int | None, runs: int | None):
    """Apply the ``--seed`` / ``--runs`` CLI overrides to a ``SimConfig``."""
    if seed is not None:
        sim = type(sim)(dt=sim.dt, max_time=sim.max_time, runs=sim.runs, seed=seed)
    if runs is not None:
        sim = type(sim)(dt=sim.dt, max_time=sim.max_time, runs=runs, seed=sim.seed)
    return sim


def _run_validate(args: argparse.Namespace) -> int:
    cfg = report.load_pipeline_config(args.targets)
    config_dir = (
        args.config_dir
        if args.config_dir is not None
        else _resolve_config_dir(cfg.config_dir, args.targets)
    )
    # The no-write guard runs BEFORE the sim: a forbidden --out is refused with
    # a structured error and EXIT_REFUSED — never the tolerance verdict.
    refused = _guard_out(args.out, config_dir)
    if refused is not None:
        return refused
    game = game_config.load_game_data(config_dir)
    player = game_config.build_player_model(game, cfg.player_model_params)
    sim = _sim_with_overrides(cfg.sim, args.seed, args.runs)

    result = report.run_validation(game, player, sim, cfg.targets)
    _emit(
        report.report_to_dict(result), report.format_text(result), args.out, args.json
    )
    return 0 if result.all_within_tolerance else 1


def _run_predict(args: argparse.Namespace) -> int:
    cfg = report.load_pipeline_config(args.targets)
    sd_config = prediction.load_sd_config(args.targets)
    config_dir = (
        args.config_dir
        if args.config_dir is not None
        else _resolve_config_dir(cfg.config_dir, args.targets)
    )
    # The same no-write guard as validate, BEFORE anything runs (gADR-0011).
    refused = _guard_out(args.out, config_dir)
    if refused is not None:
        return refused
    game = game_config.load_game_data(config_dir)
    econ = game_config.load_growth_economy(config_dir)
    player = game_config.build_player_model(game, cfg.player_model_params)
    sim = _sim_with_overrides(cfg.sim, args.seed, args.runs)

    result = prediction.run_prediction(game, econ, player, sim, sd_config)
    _emit(
        prediction.report_to_dict(result),
        prediction.format_text(result),
        args.out,
        args.json,
    )
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "validate":
        return _run_validate(args)
    if args.command == "predict":
        return _run_predict(args)
    return 2  # unreachable: subparser is required


if __name__ == "__main__":
    sys.exit(main())
