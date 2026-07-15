"""The asset pipeline CLI: ``python -m assets --config <style.json> <command>``.

The on-demand driver for the acquire stage (a live operation — network / API keys /
cost — never a CI gate). The per-game wiring is entirely config-driven: the
required ``--config`` style file names everything the game contributes (its root,
sources, generation channels, and per-asset recipes); ``--game-root`` overrides
the config's own root (e.g. to acquire into an isolated copy). Commands:

- ``acquire <id>`` — run preprocess -> acquire -> postprocess -> emit for one
  configured asset, writing the produced asset file and its Asset manifest record.
  ``--mode``/``--backend`` override the recipe; ``--no-emit`` skips the manifest.
- ``query <id>`` / ``prompt <id>`` — print the rendered search query / generation
  prompt for an asset (inspect what a mode would ask for, no acquire).
- ``list`` — list the configured assets and their recipes.

Every refused or invalid input — an unreadable or malformed style config, an
asset/source/backend the config does not declare, or a license outside the
configured allowlist — is a structured error on stderr with exit 2, never a
traceback. A generation backend that is unavailable or fails (no builtin
image generation and no fallback, a failed or timed-out channel call) gets
the same envelope: the CLI's failure surface is uniformly machine-readable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, pipeline, preprocess
from .acquire import AcquireError
from .backends import GenerationError
from .config import ConfigError, StyleConfig
from .manifest import entry_to_dict
from .model import AcquireMode

# The usage/refusal exit code — distinct from a successful run (0).
EXIT_REFUSED = 2


def _fail(code: str, detail: str) -> int:
    """Print a structured refusal to stderr and return ``EXIT_REFUSED``."""
    print(json.dumps({"error": code, "detail": detail}), file=sys.stderr)
    return EXIT_REFUSED


def _load(args: argparse.Namespace) -> StyleConfig:
    return config.load_style_config(args.config)


def _run_acquire(args: argparse.Namespace) -> int:
    cfg = _load(args)
    backend = None
    if args.backend:
        backend = pipeline._default_backend(
            cfg, {"backend": args.backend}, args.game_root
        )
    entry = pipeline.acquire_asset(
        cfg,
        args.id,
        game_root=args.game_root,
        mode=AcquireMode(args.mode) if args.mode else None,
        backend=backend,
        emit=not args.no_emit,
    )
    print(json.dumps({args.id: entry_to_dict(entry)}, indent=2, ensure_ascii=False))
    return 0


def _run_query(args: argparse.Namespace) -> int:
    cfg = _load(args)
    spec = pipeline.build_spec_for(cfg, args.id, args.game_root)
    print(preprocess.render_search_query(spec))
    return 0


def _run_prompt(args: argparse.Namespace) -> int:
    cfg = _load(args)
    spec = pipeline.build_spec_for(cfg, args.id, args.game_root)
    print(preprocess.render_generation_prompt(spec))
    return 0


def _run_list(args: argparse.Namespace) -> int:
    cfg = _load(args)
    print(json.dumps(cfg.assets, indent=2, ensure_ascii=False))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assets", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="the per-game style config file (the pipeline's whole per-game surface)",
    )
    parser.add_argument(
        "--game-root",
        type=Path,
        default=None,
        help="override the game root the assets/size spec resolve against "
        "(default: the style config's own game_root)",
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
    try:
        return int(args.func(args))
    except ConfigError as exc:
        return _fail(exc.code, exc.detail)
    except AcquireError as exc:
        # A refused acquire input (a disallowed license, a recipe with no URL,
        # an empty fetch): the same structured envelope as a config refusal.
        return _fail("acquire_refused", str(exc))
    except GenerationError as exc:
        # A generation backend failure (an agent with no builtin image gen and
        # no fallback, a failed or timed-out channel call): a runtime capability
        # gap rather than a bad input, but the same envelope — the CLI never
        # surfaces a traceback for a foreseeable failure mode.
        return _fail("generation_failed", str(exc))


if __name__ == "__main__":
    sys.exit(main())
