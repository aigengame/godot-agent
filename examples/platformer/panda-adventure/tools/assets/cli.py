"""The asset pipeline CLI: ``python -m assets <command>`` (gADR-0014).

The on-demand driver for the acquire stage (a live operation — network / API keys /
cost — never a CI gate). Commands:

- ``acquire <id>`` — run preprocess -> acquire -> postprocess -> emit for one
  configured asset, writing the produced asset file and its Asset manifest record.
  ``--mode``/``--backend`` override the recipe; ``--no-emit`` skips the manifest.
- ``query <id>`` / ``prompt <id>`` — print the rendered search query / generation
  prompt for an asset (inspect what a mode would ask for, no acquire).
- ``list`` — list the configured assets and their recipes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import game_config, pipeline, preprocess
from .game_config import StyleConfig
from .manifest import entry_to_dict
from .model import AcquireMode


def _load(args: argparse.Namespace) -> StyleConfig:
    return game_config.load_style_config(args.config)


def _run_acquire(args: argparse.Namespace) -> int:
    config = _load(args)
    backend = None
    if args.backend:
        backend = pipeline._default_backend(
            config, {"backend": args.backend}, args.game_root
        )
    entry = pipeline.acquire_asset(
        config,
        args.id,
        game_root=args.game_root,
        mode=AcquireMode(args.mode) if args.mode else None,
        backend=backend,
        emit=not args.no_emit,
    )
    print(json.dumps({args.id: entry_to_dict(entry)}, indent=2, ensure_ascii=False))
    return 0


def _run_query(args: argparse.Namespace) -> int:
    config = _load(args)
    spec = pipeline.build_spec_for(config, args.id, args.game_root)
    print(preprocess.render_search_query(spec))
    return 0


def _run_prompt(args: argparse.Namespace) -> int:
    config = _load(args)
    spec = pipeline.build_spec_for(config, args.id, args.game_root)
    print(preprocess.render_generation_prompt(spec))
    return 0


def _run_list(args: argparse.Namespace) -> int:
    config = _load(args)
    print(json.dumps(config.assets, indent=2, ensure_ascii=False))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assets", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=game_config.DEFAULT_STYLE_PATH,
        help="the per-game style config (default: the committed panda_adventure one)",
    )
    parser.add_argument(
        "--game-root",
        type=Path,
        default=game_config.GAME_ROOT,
        help="the game root the assets/scale spec resolve against",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    acquire_cmd = sub.add_parser("acquire", help="acquire one configured asset")
    acquire_cmd.add_argument("id", help="the asset id from the style config")
    acquire_cmd.add_argument(
        "--mode", choices=[m.value for m in AcquireMode], default=None
    )
    acquire_cmd.add_argument(
        "--backend", default=None, help="generation backend (mcp:<channel> | builtin)"
    )
    acquire_cmd.add_argument(
        "--no-emit", action="store_true", help="do not write the manifest fragment"
    )
    acquire_cmd.set_defaults(func=_run_acquire)

    query_cmd = sub.add_parser("query", help="print an asset's search query")
    query_cmd.add_argument("id")
    query_cmd.set_defaults(func=_run_query)

    prompt_cmd = sub.add_parser("prompt", help="print an asset's generation prompt")
    prompt_cmd.add_argument("id")
    prompt_cmd.set_defaults(func=_run_prompt)

    list_cmd = sub.add_parser("list", help="list the configured assets")
    list_cmd.set_defaults(func=_run_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
