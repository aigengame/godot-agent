"""The balancing pipeline CLI: ``python -m balancing {validate,predict} --targets <file>``.

Two modes over the SAME per-game targets file (see ``config`` for the schema),
both a PURE READ that writes NOTHING to the game's config:

- **validate** — runs the Monte-Carlo encounter simulation and emits a per-wave
  TTK/TTD-vs-targets report. Exit 0 when every targeted wave is within
  tolerance, 1 when any is out of tolerance.
- **predict** — integrates the long-term system-dynamics growth/economy
  trajectory and emits it against the difficulty/growth design targets, plus the
  MC cross-validation. Exit 0 when the prediction meets its design targets AND
  every overlapping wave cross-validates within tolerance, 1 otherwise.

The per-game wiring is entirely config-driven: the required ``--targets`` file
names the game's config dir, the adapter that maps it into the generic model,
and the protected write roots. Emission goes to stdout (text or ``--json``) or
an ``--out`` path. Every refused or invalid input — an ``--out`` inside a
protected root (including the targets/adapter files themselves), an unreadable
targets file, a broken adapter, or game config the adapter cannot map — is a
structured error on stderr with exit 2, distinct from the 0/1 verdict, and is
raised BEFORE anything runs (an ``--out`` that turns out unwritable is the one
write-time case, refused with the same envelope).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from . import config, model, prediction, report

# The usage/refusal exit code — distinct from the tolerance verdict (0/1).
EXIT_REFUSED = 2


def _fail(code: str, detail: str) -> int:
    """Print a structured refusal to stderr and return ``EXIT_REFUSED``."""
    print(json.dumps({"error": code, "detail": detail}), file=sys.stderr)
    return EXIT_REFUSED


def _check_out(out: Path | None, roots: list[Path]) -> None:
    """The shared no-write guard both modes run BEFORE the sim: an ``--out``
    inside a protected root raises the refusal. Resolves the path first so
    ``../`` cannot sneak in."""
    if out is None:
        return
    resolved = out.resolve()
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            raise config.ConfigError(
                "out_path_in_authority",
                f"--out {out} resolves into the protected config tree {root}; "
                "the balancing pipeline writes nothing to config — choose a "
                "path outside it",
            )


def _emit(doc: dict, text: str, out: Path | None, as_json: bool) -> None:
    """Emit a report: to ``--out`` as JSON, else JSON or text to stdout. An
    unwritable ``--out`` is a structured refusal like every other bad input."""
    if out is not None:
        try:
            out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise config.ConfigError(
                "out_unwritable", f"cannot write the report to --out {out}: {exc}"
            )
    elif as_json:
        print(json.dumps(doc, indent=2))
    else:
        print(text)


def _add_common_args(p: argparse.ArgumentParser) -> None:
    """The args every mode shares (both read the same targets file and emit the
    same way, writing nothing to config)."""
    p.add_argument(
        "--targets",
        type=Path,
        required=True,
        help="the per-game targets file (config dir, adapter, design targets)",
    )
    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="override the game's config-authority dir (default: the targets file's config_dir)",
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


def _sim_with_overrides(
    sim: model.SimConfig, seed: int | None, runs: int | None
) -> model.SimConfig:
    """Apply the ``--seed`` / ``--runs`` CLI overrides to a ``SimConfig``."""
    if seed is not None:
        sim = replace(sim, seed=seed)
    if runs is not None:
        sim = replace(sim, runs=runs)
    return sim


def _load_inputs(
    args: argparse.Namespace,
) -> tuple[config.PipelineConfig, model.GameInputs, model.SimConfig]:
    """The shared per-game front door both modes run, entirely from the targets
    file: parse it, resolve the config dir, run the no-write guard BEFORE the
    sim, then let the configured adapter map the game's config into the model.
    Every refusal raises a ``ConfigError`` (the structured exit-2 path)."""
    cfg = config.load_pipeline_config(args.targets)
    config_dir = config.resolve_config_dir(cfg, args.targets, args.config_dir)
    _check_out(args.out, config.forbidden_out_roots(cfg, args.targets, config_dir))
    adapter = config.load_adapter(cfg, args.targets)
    try:
        inputs: model.GameInputs = adapter.load_inputs(config_dir)
    except config.ConfigError:
        raise  # an adapter may speak the structured contract itself
    except Exception as exc:
        # Any adapter failure is a bad per-game input to THIS tool: a
        # structured refusal, never a traceback (process interrupts stay
        # BaseException and pass through).
        raise config.ConfigError(
            "game_config_invalid",
            f"the adapter failed to load the game config from {config_dir}: {exc!r}",
        )
    if not isinstance(inputs, model.GameInputs) or not isinstance(
        inputs.game, model.GameData
    ):
        # The return-shape half of the adapter contract (the callable half is
        # checked at load time): anything but a GameInputs with a GameData
        # inside is a broken adapter, refused with the same envelope.
        raise config.ConfigError(
            "adapter_invalid",
            "adapter load_inputs(config_dir) must return model.GameInputs "
            f"carrying a model.GameData, got {type(inputs).__name__}",
        )
    sim = _sim_with_overrides(cfg.sim, args.seed, args.runs)
    if sim.dt <= 0 or sim.max_time <= 0 or sim.runs <= 0:
        # Guards the file values AND the CLI overrides in one place: a
        # non-positive control would only crash later inside the sim.
        raise config.ConfigError(
            "sim_invalid",
            "simulation controls must be positive "
            f"(dt={sim.dt}, max_time={sim.max_time}, runs={sim.runs})",
        )
    return cfg, inputs, sim


def _run_validate(args: argparse.Namespace) -> int:
    cfg, inputs, sim = _load_inputs(args)
    player = model.build_player_model(inputs.game, cfg.player_model_params)

    result = report.run_validation(inputs.game, player, sim, cfg.targets)
    _emit(
        report.report_to_dict(result), report.format_text(result), args.out, args.json
    )
    return 0 if result.all_within_tolerance else 1


def _run_predict(args: argparse.Namespace) -> int:
    cfg, inputs, sim = _load_inputs(args)
    if inputs.economy is None:
        return _fail(
            "economy_missing",
            "predict needs growth/economy inputs, but the adapter returned "
            "GameInputs.economy = None (validate-only adapter)",
        )
    sd_config = config.load_sd_config(args.targets)
    player = model.build_player_model(inputs.game, cfg.player_model_params)

    result = prediction.run_prediction(
        inputs.game, inputs.economy, player, sim, sd_config
    )
    _emit(
        prediction.report_to_dict(result),
        prediction.format_text(result),
        args.out,
        args.json,
    )
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "predict":
            return _run_predict(args)
    except config.ConfigError as exc:
        return _fail(exc.code, exc.detail)
    return EXIT_REFUSED  # unreachable: subparser is required


if __name__ == "__main__":
    sys.exit(main())
