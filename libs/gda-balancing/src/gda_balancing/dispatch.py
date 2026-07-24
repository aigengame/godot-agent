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
the versioned internal-envelope debug member.
"""

import json
import os
import tempfile
import traceback
from collections.abc import Sequence
from typing import Any, TextIO

import jsonschema
from pydantic import BaseModel, ValidationError

from gda_balancing.commands import REGISTRY
from gda_balancing.descriptors import (
    ArtifactReceipt,
    ArtifactSpec,
    CommandDescriptor,
    option_bindings,
)
from gda_balancing.emit import canonical_json, model_payload
from gda_balancing.envelope import (
    ERROR_ENVELOPE_SCHEMA,
    EXIT_INTERNAL,
    EXIT_REFUSAL,
    EXIT_SUCCESS,
    EXIT_USAGE,
    RefusalReport,
    UnreadableInputError,
    UsageError,
    internal_envelope,
    refusal_envelope,
    usage_envelope,
)
from gda_balancing.path_contracts import reject_input_aliasing
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
    refusal_envelope as schema2_refusal_envelope,
)

_SCHEMA_FLAG = "--schema"
_HELP_FLAG = "--help"
_DEBUG_FLAG = "--debug"
_OUT_FLAG = "--out"


class _UsageError(UsageError):
    """Dispatch-internal control flow for the invocation surface.

    The dispatch tail maps it to the `usage` envelope / exit 3.
    """


def dispatch(
    argv: Sequence[str],
    stdout: TextIO,
    stderr: TextIO,
    *,
    registry: tuple[CommandDescriptor, ...] = REGISTRY,
    stdin: TextIO | None = None,
) -> int:
    """Run one invocation; returns the exit code, never raises or exits.

    ``registry`` defaults to the real surface; the conformance harness
    substitutes a copy with a raising handler to drive the `internal` row
    (bADR-0011's fault-injection seam — production has no fault path).
    """
    try:
        return _dispatch(list(argv), stdout, registry, stdin)
    except UsageError as err:
        stderr.write(canonical_json(usage_envelope(err.code, err.message)))
        return EXIT_USAGE
    except UnreadableInputError as err:
        # The funnel's loader raised before any document bytes were read: a
        # usage error at the funnel's ingress (bADR-0008), not a refusal.
        stderr.write(canonical_json(usage_envelope("unreadable_input", str(err))))
        return EXIT_USAGE
    except Exception as exc:
        diagnostics = traceback.format_exc() if _DEBUG_FLAG in argv else None
        message = f"the toolkit failed unexpectedly ({type(exc).__name__})"
        envelope = internal_envelope(message, diagnostics)
        descriptor = _descriptor_for_invocation(argv, registry)
        if descriptor is not None and descriptor.schema_major == 2 and diagnostics:
            envelope["error"]["debug"] = envelope["error"].pop("diagnostics")
        stderr.write(canonical_json(envelope))
        return EXIT_INTERNAL


def _descriptor_for_invocation(
    argv: Sequence[str], registry: tuple[CommandDescriptor, ...]
) -> CommandDescriptor | None:
    """Resolve only descriptor identity for versioned internal serialization."""
    if not argv:
        return None
    head = argv[0]
    groups = {item.group for item in registry if item.group is not None}
    if head in groups:
        if len(argv) < 2:
            return None
        return next(
            (
                item
                for item in registry
                if item.group == head and item.command == argv[1]
            ),
            None,
        )
    return next(
        (item for item in registry if item.group is None and item.command == head),
        None,
    )


def _dispatch(
    argv: list[str],
    stdout: TextIO,
    registry: tuple[CommandDescriptor, ...],
    stdin: TextIO | None,
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
        if descriptor.schema_major == 2:
            from gda_balancing.schema2.surface import command_schema_projection

            stdout.write(canonical_json(command_schema_projection(descriptor)))
        else:
            stdout.write(canonical_json(_schema_projection(descriptor)))
        return EXIT_SUCCESS
    if _HELP_FLAG in tail:
        stdout.write(_render_command_help(descriptor))
        return EXIT_SUCCESS

    try:
        return _invoke_descriptor(descriptor, tail, stdout, stdin)
    except UsageError as err:
        if descriptor.schema_major == 2 and err.code not in descriptor.usage_codes:
            raise TypeError(
                "dispatch produced a Schema 2.x usage outcome absent from its descriptor"
            ) from err
        raise
    except UnreadableInputError as err:
        if (
            descriptor.schema_major == 2
            and "unreadable_input" not in descriptor.usage_codes
        ):
            raise TypeError(
                "dispatch produced a Schema 2.x usage outcome absent from its descriptor"
            ) from err
        raise


def _invoke_descriptor(
    descriptor: CommandDescriptor,
    tail: list[str],
    stdout: TextIO,
    stdin: TextIO | None,
) -> int:
    """Invoke a resolved descriptor inside its declared usage boundary."""
    try:
        values, out = _bind(descriptor, tail, stdin)
        input_obj = descriptor.input_model(**values)
    except ValidationError as err:
        raise _UsageError("invalid_argument", _summarize(err)) from err

    outcome = descriptor.handler(input_obj)
    if isinstance(outcome, RefusalReport):
        stdout.write(canonical_json(refusal_envelope(outcome)))
        return EXIT_REFUSAL
    if isinstance(outcome, Schema2RefusalReport):
        observed = {(item.code, outcome.stage) for item in outcome.diagnostics}
        if not observed <= set(descriptor.refusal_catalog):
            raise TypeError(
                "handler returned a Schema 2.x refusal absent from its descriptor"
            )
        stdout.write(canonical_json(schema2_refusal_envelope(outcome)))
        return EXIT_REFUSAL
    if type(outcome) is not descriptor.output_model:
        # The declared output model is authoritative at runtime, not merely
        # descriptive, and the check is EXACT identity: an isinstance check
        # would admit a subclass whose extra fields serialize past the closed
        # (additionalProperties: false) output schema. Any other return is a
        # toolkit bug and takes the unexpected-exception path (`internal` /
        # exit 4) — success stdout can never contradict the descriptor's own
        # --schema.
        raise TypeError(
            f"handler returned {type(outcome).__name__}, not the declared "
            f"output model {descriptor.output_model.__name__}"
        )
    payload = model_payload(outcome)
    if descriptor.schema_major == 2 and descriptor.success_schema is not None:
        jsonschema.validate(payload, descriptor.success_schema())
    body = canonical_json(payload)
    if descriptor.artifact_sink and out is not None:
        # The BODY arm goes to the sink; stdout carries the receipt (bADR-0009).
        # The sink is written BEFORE stdout, and an unwritable sink raises
        # `_UsageError` (exit 3) while stdout is still untouched — so the
        # exit-3-implies-empty-stdout law holds even on a write failure.
        receipt = _write_artifact(descriptor, out, body)
        stdout.write(canonical_json(model_payload(receipt)))
        return EXIT_SUCCESS
    stdout.write(body)
    return EXIT_SUCCESS


def _bind(
    descriptor: CommandDescriptor, tail: list[str], stdin: TextIO | None
) -> tuple[dict[str, Any], str | None]:
    """Apply the binding law to the command tail (bADR-0011); return the bound
    model values and the ``--out`` sink path (``None`` when absent).

    Every option is valued (``--name value`` or ``--name=value``); no v1 input
    model declares a boolean flag. ``--debug`` is dispatch-owned. For a legacy
    ``artifact_sink`` command, ``--out`` is also dispatch-owned and returned
    separately; for an ``artifact_set`` command it is an ordinary descriptor
    input field and is bound through ``option_bindings``.
    """
    structured = _structured_params(descriptor, tail, stdin)
    if structured is not None:
        return structured, None

    options = option_bindings(descriptor)
    values: dict[str, Any] = {}
    positionals: list[str] = []
    out: str | None = None
    i = 0
    while i < len(tail):
        token = tail[i]
        if token == _DEBUG_FLAG:
            i += 1
            continue
        name, eq, inline_value = token.partition("=")
        if name == _OUT_FLAG and descriptor.artifact_sink:
            if out is not None:
                raise _UsageError(
                    "argument_conflict", f"argument named more than once: {name}"
                )
            if eq:
                out = inline_value
            else:
                i += 1
                if i >= len(tail):
                    raise _UsageError("invalid_argument", f"missing value for {name}")
                out = tail[i]
            i += 1
            continue
        if token.startswith("--"):
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

    if out is not None and descriptor.positional_field is not None:
        reject_input_aliasing(out, values.get(descriptor.positional_field))
    return values, out


def _structured_params(
    descriptor: CommandDescriptor, tail: list[str], stdin: TextIO | None
) -> dict[str, Any] | None:
    """Decode the descriptor input object from ``--params-json`` when used.

    The flag is one alternate presentation of the same input model, never a
    second parameter authority.  It is therefore mutually exclusive with
    positional and individual options; ``--schema`` has already returned
    before this function can read stdin.
    """
    flag = "--params-json"
    indices = [
        index
        for index, token in enumerate(tail)
        if token == flag or token.startswith(flag + "=")
    ]
    if not indices:
        return None
    if not descriptor.structured_params:
        raise _UsageError("unknown_argument", f"unknown argument: {flag}")
    if len(indices) > 1:
        raise _UsageError("argument_conflict", f"argument named more than once: {flag}")

    index = indices[0]
    token = tail[index]
    consumed = 1
    if token.startswith(flag + "="):
        source = token.partition("=")[2]
    else:
        if index + 1 >= len(tail):
            raise _UsageError("invalid_argument", f"missing value for {flag}")
        source = tail[index + 1]
        consumed = 2
    remaining = [
        item
        for offset, item in enumerate(tail)
        if not index <= offset < index + consumed and item != _DEBUG_FLAG
    ]
    if remaining:
        raise _UsageError(
            "argument_conflict",
            "--params-json is mutually exclusive with individual arguments",
        )
    text = stdin.read() if source == "-" and stdin is not None else source
    if source == "-" and stdin is None:
        text = ""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as err:
        raise _UsageError(
            "invalid_argument", "--params-json is not valid JSON"
        ) from err
    if not isinstance(value, dict):
        raise _UsageError("invalid_argument", "--params-json must contain an object")
    return value


def _write_artifact(descriptor: CommandDescriptor, out: str, body: str) -> BaseModel:
    """Write the artifact ``body`` to the sink atomically and return the receipt
    as the descriptor's declared output model (bADR-0009).

    The write is atomic — a temp file in the sink's own directory, then
    ``os.replace`` — so a failed invocation leaves no partial file and an
    existing destination is overwritten wholesale. Any ``OSError`` (unwritable
    directory, replace failure) is a usage `unwritable_output`; the temp file is
    cleaned up first, and stdout is still untouched, so the exit-3 stdout-empty
    law holds.
    """
    body_bytes = body.encode("utf-8")
    directory = os.path.dirname(out) or "."
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
            tmp_name = handle.name
            handle.write(body_bytes)
        os.replace(tmp_name, out)
    except OSError as err:
        if tmp_name is not None and os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise _UsageError(
            "unwritable_output", f"cannot write output file: {out}"
        ) from err
    return descriptor.output_model(
        root=ArtifactReceipt(
            artifact=ArtifactSpec(path=os.path.realpath(out), bytes=len(body_bytes))
        )
    )


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
