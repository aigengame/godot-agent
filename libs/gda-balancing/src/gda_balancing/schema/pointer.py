"""RFC 6901 JSON Pointer construction (bADR-0004 refusal paths).

Every refusal names the offending element by an RFC 6901 instance pointer —
never just the enclosing collection. `""` addresses the whole document; each
reference token escapes ``~`` as ``~0`` and ``/`` as ``~1``.
"""


def escape(token: str) -> str:
    """Escape one reference token (order matters: ``~`` first)."""
    return token.replace("~", "~0").replace("/", "~1")


def build(*tokens: str | int) -> str:
    """Build a pointer from raw tokens; no tokens addresses the document."""
    return "".join(
        "/" + (str(token) if isinstance(token, int) else escape(token))
        for token in tokens
    )
