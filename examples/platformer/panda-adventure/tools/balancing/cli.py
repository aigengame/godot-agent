"""The balancing pipeline CLI: ``python -m balancing validate ...`` (#437).

Validate mode reads the JSON authority and a targets file, runs the Monte-Carlo
encounter simulation, and emits a per-wave TTK/TTD-vs-targets report — to stdout
(text or ``--json``) or to an ``--out`` path. It writes NOTHING to config: an
``--out`` path inside the game's ``data/`` tree (the whole authority chain —
authored JSON, schemas, derived Resources) or inside the configured authority
dir is REFUSED with a structured error before anything runs. Exit status: 0 when
every targeted wave is within tolerance, 1 when any is out of tolerance (a
usable CI gate), 2 for a refused/invalid input — distinct from the verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import game_config, report

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
                "the Balancing pipeline's validate mode writes nothing to "
                "config (gADR-0011) — choose a path outside data/"
            )
    return None


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="balancing", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser(
        "validate",
        help="report per-wave TTK/TTD vs design targets (writes nothing to config)",
    )
    validate.add_argument(
        "--targets",
        type=Path,
        default=_DEFAULT_TARGETS,
        help="targets file (default: the committed panda_adventure targets)",
    )
    validate.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="override the JSON authority dir (default: the targets file's config_dir)",
    )
    validate.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the JSON report to this path (never a config file); default stdout",
    )
    validate.add_argument(
        "--seed", type=int, default=None, help="override the base seed"
    )
    validate.add_argument(
        "--runs", type=int, default=None, help="override the run count"
    )
    validate.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON (default: human-readable text)",
    )
    return parser


def _run_validate(args: argparse.Namespace) -> int:
    cfg = report.load_pipeline_config(args.targets)
    config_dir = (
        args.config_dir
        if args.config_dir is not None
        else _resolve_config_dir(cfg.config_dir, args.targets)
    )
    # The no-write guard runs BEFORE the sim: a forbidden --out is refused with
    # a structured error and EXIT_REFUSED — never the tolerance verdict.
    if args.out is not None:
        reason = _refuse_authority_out(args.out, config_dir)
        if reason is not None:
            print(
                json.dumps({"error": "out_path_in_authority", "detail": reason}),
                file=sys.stderr,
            )
            return EXIT_REFUSED
    game = game_config.load_game_data(config_dir)
    player = game_config.build_player_model(game, cfg.player_model_params)
    sim = cfg.sim
    if args.seed is not None:
        sim = type(sim)(dt=sim.dt, max_time=sim.max_time, runs=sim.runs, seed=args.seed)
    if args.runs is not None:
        sim = type(sim)(dt=sim.dt, max_time=sim.max_time, runs=args.runs, seed=sim.seed)

    result = report.run_validation(game, player, sim, cfg.targets)

    if args.out is not None:
        args.out.write_text(
            json.dumps(report.report_to_dict(result), indent=2) + "\n", encoding="utf-8"
        )
    elif args.json:
        print(json.dumps(report.report_to_dict(result), indent=2))
    else:
        print(report.format_text(result))
    return 0 if result.all_within_tolerance else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "validate":
        return _run_validate(args)
    return 2  # unreachable: subparser is required


if __name__ == "__main__":
    sys.exit(main())
