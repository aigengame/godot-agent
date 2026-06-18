"""gda-mcp: a generated stdio MCP server over the gda CLI (issue #193).

gda's MCP adapter (ADR-0011/0012/0013): it introspects gda's aggregate schema
dump and exposes one MCP tool per command, shelling out to the installed gda for
each call over gda's public CLI ABI. It ships inside the one ``gda`` distribution
behind the optional ``gda[mcp]`` extra — gda core never imports ``mcp``, and this
package's :func:`main` entry point guards the import so ``gda-mcp`` without the
extra fails with an actionable message rather than an opaque ImportError.

This module stays deliberately lean (no ``mcp`` import at load time): the import
guard in :func:`main` must run *before* any SDK-dependent code, so all of that
lives in :mod:`gda.mcp.server`, imported only after the guard passes.
"""

import sys

# The actionable failure when the optional ``mcp`` SDK is absent (ADR-0013): the
# ``gda-mcp`` console script is declared in every install, but only ``gda[mcp]``
# installs the SDK it needs. Point the user at the fix instead of letting a bare
# ImportError escape.
_MISSING_MCP_MESSAGE = (
    "gda-mcp requires the optional 'mcp' extra, which is not installed.\n"
    "Install it with:    pip install 'gda[mcp]'\n"
    "or run without installing:    uvx --from 'gda[mcp]' gda-mcp\n"
)


def main() -> int:
    """The ``gda-mcp`` console-script entry point (ADR-0013).

    Lean by design: it guards the optional ``mcp`` import (so a plain ``gda``
    install fails with an actionable message, not an opaque traceback), then
    hands off to the server, which owns all the SDK-dependent logic. Returns the
    process exit code; ``console_scripts`` wraps the return value in
    ``sys.exit``.
    """
    try:
        import mcp  # noqa: F401
    except ImportError:
        sys.stderr.write(_MISSING_MCP_MESSAGE)
        return 1
    # Imported lazily, AFTER the guard: gda.mcp.server imports the SDK at module
    # load, so importing it before the guard would surface the bare ImportError
    # this guard exists to replace.
    from gda.mcp.server import run_stdio

    run_stdio()
    return 0
