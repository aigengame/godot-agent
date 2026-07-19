"""Argv binding and the dispatch tail — the bADR-0008 emission owner.

Everything here is a projection of the descriptor registry (bADR-0011):
command resolution, the binding law, per-command ``--schema``, and help. The
dispatch tail owns emission — handlers return outcomes as data and this
module maps them onto the invocation-result contract: success → canonical
result on stdout / exit 0; typed-refusal report → `refusal` envelope on
stdout / exit 2 (#504 lands the first producer); usage error → one `usage`
envelope on stderr / exit 3 with stdout empty; an unexpected exception → one
sanitized `internal` envelope on stderr / exit 4 (the sole internal path). A
bare traceback is never any invocation's output; ``--debug`` routes it into
``diagnostics``.
"""

import traceback
from collections.abc import Sequence
from typing import Any, TextIO

from pydantic import ValidationError

from gda_balancing.commands import REGISTRY
from gda_balancing.descriptors import CommandDescriptor, option_bindings
from gda_balancing.emit import canonical_json, model_payload
from gda_balancing.envelope import (
    ERROR_ENVELOPE_SCHEMA,
    EXIT_INTERNAL,
    EXIT_REFUSAL,
    EXIT_SUCCESS,
    EXIT_USAGE,
    RefusalReport,
    internal_envelope,
    refusal_envelope,
    usage_envelope,
)

_SCHEMA_FLAG = "--schema"
_HELP_FLAG = "--help"
_DEBUG_FLAG = "--debug"


class _UsageError(Exception):
    """Dispatch-internal control flow for the invocation surface.

    Raised only before the handler runs (handlers never see usage errors);
    the dispatch tail maps it to the `usage` envelope / exit 3.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def dispatch(
    argv: Sequence[str],
    stdout: TextIO,
    stderr: TextIO,
    *,
    registry: tuple[CommandDescriptor, ...] = REGISTRY,
) -> int:
    """Run one invocation; returns the exit code, never raises or exits.

    ``registry`` defaults to the real surface; the conformance harness
    substitutes a copy with a raising handler to drive the `internal` row
    (bADR-0011's fault-injection seam — production has no fault path).
    """
    try:
        return _dispatch(list(argv), stdout, registry)
    except _UsageError as err:
        stderr.write(canonical_json(usage_envelope(err.code, err.message)))
        return EXIT_USAGE
    except Exception as exc:
        diagnostics = traceback.format_exc() if _DEBUG_FLAG in argv else None
        message = f"the toolkit failed unexpectedly ({type(exc).__name__})"
        stderr.write(canonical_json(internal_envelope(message, diagnostics)))
        return EXIT_INTERNAL


def _dispatch(
    argv: list[str], stdout: TextIO, registry: tuple[CommandDescriptor, ...]
) -> int:
    if not argv:
        raise _UsageError(
            "missing_command",
            "no command named; expected `gda-balancing <command>` "
            "(`gda-balancing help` lists the surface)",
        )
    head = argv[0]
    if head == "help" or head == _HELP_FLAG:
        stdout.write(_render_help(registry))
        return EXIT_SUCCESS

    groups = {d.group for d in registry if d.group is not None}
    if head in groups:
        if len(argv) < 2 or argv[1].startswith("-"):
            raise _UsageError(
                "missing_command", f"group {head!r} named with no command"
            )
        descriptor = next(
            (d for d in registry if d.group == head and d.command == argv[1]), None
        )
        if descriptor is None:
            raise _UsageError("unknown_command", f"unknown command: {head} {argv[1]}")
        tail = argv[2:]
    else:
        descriptor = next(
            (d for d in registry if d.group is None and d.command == head), None
        )
        if descriptor is None:
            raise _UsageError("unknown_command", f"unknown command: {head}")
        tail = argv[1:]

    # Bare `--schema` wins over any other argument (bADR-0009).
    if _SCHEMA_FLAG in tail:
        stdout.write(canonical_json(_schema_projection(descriptor)))
        return EXIT_SUCCESS
    if _HELP_FLAG in tail:
        stdout.write(_render_command_help(descriptor))
        return EXIT_SUCCESS

    values = _bind(descriptor, tail)
    try:
        input_obj = descriptor.input_model(**values)
    except ValidationError as err:
        raise _UsageError("invalid_argument", _summarize(err)) from err

    outcome = descriptor.handler(input_obj)
    if isinstance(outcome, RefusalReport):
        stdout.write(canonical_json(refusal_envelope(outcome)))
        return EXIT_REFUSAL
    if not isinstance(outcome, descriptor.output_model):
        # The declared output model is authoritative at runtime, not merely
        # descriptive: a handler that returns anything else is a toolkit bug
        # and takes the unexpected-exception path (`internal` / exit 4) —
        # success stdout can never contradict the descriptor's own --schema.
        raise TypeError(
            f"handler returned {type(outcome).__name__}, not the declared "
            f"output model {descriptor.output_model.__name__}"
        )
    stdout.write(canonical_json(model_payload(outcome)))
    return EXIT_SUCCESS


def _bind(descriptor: CommandDescriptor, tail: list[str]) -> dict[str, str]:
    """Apply the binding law to the command tail (bADR-0011).

    Every option is valued (``--name value`` or ``--name=value``); no v1
    input model declares a boolean flag. ``--debug`` is the dispatch-owned
    global flag and is skipped here.
    """
    options = option_bindings(descriptor)
    values: dict[str, str] = {}
    positionals: list[str] = []
    i = 0
    while i < len(tail):
        token = tail[i]
        if token == _DEBUG_FLAG:
            i += 1
            continue
        if token.startswith("--"):
            name, eq, inline_value = token.partition("=")
            field = options.get(name)
            if field is None:
                raise _UsageError("unknown_argument", f"unknown argument: {name}")
            if field in values:
                raise _UsageError(
                    "argument_conflict", f"argument named more than once: {name}"
                )
            if eq:
                values[field] = inline_value
            else:
                i += 1
                if i >= len(tail):
                    raise _UsageError("invalid_argument", f"missing value for {name}")
                values[field] = tail[i]
        else:
            positionals.append(token)
        i += 1

    allowed_positionals = 0 if descriptor.positional_field is None else 1
    if len(positionals) > allowed_positionals:
        raise _UsageError(
            "unknown_argument",
            f"unexpected argument: {positionals[allowed_positionals]}",
        )
    if positionals and descriptor.positional_field is not None:
        values[descriptor.positional_field] = positionals[0]
    return values


def _schema_projection(descriptor: CommandDescriptor) -> dict[str, Any]:
    """The per-command ``--schema`` object (bADR-0009).

    ``error`` is the one closed envelope schema, byte-identical across every
    command because it is the same constant rendered canonically.
    """
    return {
        "input": descriptor.input_model.model_json_schema(),
        "output": descriptor.output_model.model_json_schema(),
        "error": ERROR_ENVELOPE_SCHEMA,
    }


def _summarize(err: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(loc) for loc in e['loc']) or 'input'}: {e['msg']}"
        for e in err.errors()
    ]
    return "invalid argument value: " + "; ".join(parts)


def _command_path(descriptor: CommandDescriptor) -> str:
    return (
        f"{descriptor.group} {descriptor.command}"
        if descriptor.group
        else descriptor.command
    )


def _render_help(registry: tuple[CommandDescriptor, ...]) -> str:
    """Top-level help — the surface's one human-facing exemption (bADR-0007)."""
    lines = [
        "gda-balancing — game numeric design & balancing toolkit",
        "",
        "usage: gda-balancing <command> [options]",
        "",
        "commands:",
    ]
    width = max(len(_command_path(d)) for d in registry)
    for descriptor in registry:
        lines.append(
            f"  {_command_path(descriptor):<{width}}  {descriptor.description}"
        )
    lines += [
        "",
        "`gda-balancing <command> --help` describes one command;",
        "`gda-balancing <command> --schema` emits its JSON input/output/error contract.",
    ]
    return "\n".join(lines) + "\n"


def _render_command_help(descriptor: CommandDescriptor) -> str:
    path = _command_path(descriptor)
    usage = f"usage: gda-balancing {path}"
    if descriptor.positional_field is not None:
        usage += f" <{descriptor.positional_field.replace('_', '-')}>"
    options = option_bindings(descriptor)
    if options:
        usage += " [options]"
    lines = [usage, "", descriptor.description]
    if options:
        lines += ["", "options:"]
        lines += [f"  {name} <value>" for name in sorted(options)]
    lines += ["", "flags: --schema (emit the JSON contract), --debug, --help"]
    return "\n".join(lines) + "\n"
