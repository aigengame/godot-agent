"""Result parser for the ADR-0002 sentinel contract.

A headless Godot process interleaves its banner, warnings and stray ``print()``
output into stdout. The GDScript operation emits exactly one result payload
wrapped in unique sentinels::

    <<<GDA:RESULT>>>{...json...}<<<GDA:END>>>

``parse_result`` extracts the bytes between the sentinels and parses them as
JSON, ignoring everything else on stdout. The payload echoes user-controlled
content (a path, and later node names / script source), so it may itself contain
the literal end sentinel; the real terminator is the *last* end sentinel, since
the operation emits exactly one result (ADR-0002).
"""

import json
from typing import Any

RESULT_BEGIN = "<<<GDA:RESULT>>>"
RESULT_END = "<<<GDA:END>>>"


def parse_result(stdout: str) -> Any:
    """Extract and parse the sentinel-delimited JSON result from ``stdout``."""
    start = stdout.find(RESULT_BEGIN)
    if start == -1:
        raise ValueError("no GDA result sentinel found in stdout")
    payload_start = start + len(RESULT_BEGIN)
    # The last end sentinel after the payload start, not the first: the payload
    # may contain sentinel-shaped content, but the real terminator is last since
    # exactly one result is emitted (issue #34).
    end = stdout.rfind(RESULT_END, payload_start)
    if end == -1:
        raise ValueError("unterminated GDA result sentinel in stdout")
    payload = stdout[payload_start:end].strip()
    if not payload:
        raise ValueError("empty GDA result payload between sentinels")
    return json.loads(payload)


def build_result(payload: Any) -> str:
    """Wrap ``payload`` as the ADR-0002 sentinel result string — the inverse of
    :func:`parse_result`.

    The single place the sentinel string is constructed. The engine op, the daemon,
    and the live client all emit ``<<<GDA:RESULT>>>{json}<<<GDA:END>>>`` followed by
    a trailing newline (matching what every emitter wrote before this was shared), so
    a relayed or synthesized result is byte-identical to a real engine run's.
    """
    return f"{RESULT_BEGIN}{json.dumps(payload)}{RESULT_END}\n"


def error_envelope(code: str, message: str, probe: dict | None = None) -> dict:
    """The ADR-0002 operation-error payload — ``{"error": {"code", "message"}}``.

    The one place that envelope dict is built (it mirrors
    :class:`~gda.models.OperationErrorEnvelope`); wrap it with :func:`build_result`
    to synthesize a sentinel error result.

    ``probe`` is the OPTIONAL live-channel extension (#667): the daemon relays a
    windowed refusal that a HOST PROBE decided, and the probe context has to survive
    the relay or the authoritative lazy-launch path would report a strictly poorer
    failure than the CLI fail-fast does. The key is omitted entirely when absent, so
    every other envelope on this wire — and the whole GDScript-emitted headless
    sentinel, whose model stays ``extra="forbid"`` with no ``probe`` — is
    byte-identical to before. Only the live envelope model
    (:class:`~gda.models.LiveErrorEnvelope`) accepts it.
    """
    error: dict = {"code": code, "message": message}
    if probe is not None:
        error["probe"] = probe
    return {"error": error}
