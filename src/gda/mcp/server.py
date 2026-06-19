"""The gda-mcp low-level stdio Server (ADR-0011/0012/0013, issue #193).

A *generated* server: at startup it introspects gda's aggregate schema dump
(``gda schema``) and registers one MCP tool per command — name
``<group>_<command>``, ``description`` ← the command's help, ``inputSchema`` /
``outputSchema`` ← the command's input/output schemas (ADR-0012's faithful
mirror). On a tool call it shells out to the installed gda, forwarding the tool
input *verbatim* via ``gda <group> <command> --params-json -`` (the object on
stdin; ADR-0015), and maps the result mechanically off gda's exit code
(ADR-0011):

- **exit 0** → the ``--json`` result dict; the SDK validates it against the
  tool's ``outputSchema`` and wraps it as ``structuredContent`` (Design
  decision 5 — gda-mcp does NOT re-validate: gda's result and its ``outputSchema``
  share one Pydantic model, so conformance is by construction);
- **exit ≠ 0** → ``CallToolResult(isError=True)`` carrying the full ``GdaError``
  envelope *verbatim* as JSON content — lossless, never flattened to prose, and
  kept out of ``structuredContent`` / ``outputSchema``.

Why the low-level ``Server`` and not FastMCP: our schemas come *from* gda (not
from Python signatures), tools are discovered at runtime and served by one
generic dispatcher, and we need direct control of the result/error channels —
the inverse of FastMCP's "one tool = one decorated Python function" assumption.

gda-mcp consumes only gda's public CLI ABI (``--json`` / exit code / ``GdaError``
envelope); it never imports a gda internal symbol.
"""

import json
import os
from importlib.metadata import version
from pathlib import Path
from typing import Any, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from gda.mcp.project_context import resolve_project_dir
from gda.mcp.runner import GdaResult, GdaRunner, SubprocessGdaRunner

SERVER_NAME = "gda-mcp"

# The category/code gda-mcp stamps on an error it had to synthesize itself —
# distinct from gda's own four categories so an agent can tell a gda-mcp-level
# failure (gda could not run, or emitted non-envelope output) from a gda one.
_ADAPTER_ERROR_CATEGORY = "adapter"
_ADAPTER_ERROR_CODE = "gda_invocation_failed"


def tool_name(command_name: str) -> str:
    """Map a manifest command name to its MCP tool name (ADR-0005).

    ``<group> <command>`` → ``<group>_<command>``: the space (group separator)
    and any hyphen (within a multi-word command like ``get-exports``) both become
    underscores, so ``scene get-exports`` → ``scene_get_exports`` while the bare
    meta command ``info`` stays ``info``.
    """
    return command_name.replace(" ", "_").replace("-", "_")


def _load_commands(runner: GdaRunner) -> list[dict[str, Any]]:
    """Introspect gda's whole-surface dump through the seam (ADR-0012).

    Spawns ``gda schema`` exactly once at startup and returns its per-command
    entries. A non-zero exit is fatal: without the dump there is no tool surface
    to serve, so fail loudly with gda's diagnostics rather than start empty.
    """
    result = runner.run(["schema"])
    if result.returncode != 0:
        raise RuntimeError(
            f"`gda schema` failed (exit {result.returncode}); gda-mcp cannot "
            f"build its tool surface.\n{result.stderr}"
        )
    return json.loads(result.stdout)["commands"]


def _parse_error_envelope(stdout: str) -> Optional[dict[str, Any]]:
    """Return gda's ``GdaError`` envelope if ``stdout`` is one, else ``None``.

    The discriminator for the ADR-0011 edge: a genuine non-zero gda failure emits
    ``{"error": {category, code, message, diagnostics}}`` on stdout, which is
    relayed verbatim; anything else (a Click usage error to stderr, a crash before
    the envelope, an unrelated string) is *not* an envelope and is synthesized by
    gda-mcp instead.
    """
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict) or "code" not in error or "category" not in error:
        return None
    return payload


def _synthesized_error(message: str, result: GdaResult) -> types.CallToolResult:
    """gda-mcp's own ``isError`` result when gda produced no usable envelope.

    The edge of ADR-0011: gda failed to even run (e.g. ``-m gda`` import failure)
    or emitted non-envelope output. gda-mcp synthesizes a structured error in the
    same ``{category, code, message, diagnostics}`` shape as a ``GdaError`` —
    stamped with the distinct ``adapter`` category — preserving gda's raw
    stderr/stdout as diagnostics so nothing is silently swallowed.
    """
    body = {
        "error": {
            "category": _ADAPTER_ERROR_CATEGORY,
            "code": _ADAPTER_ERROR_CODE,
            "message": message,
            "diagnostics": (result.stderr or result.stdout).strip(),
        }
    }
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(body))],
        isError=True,
    )


def dispatch(
    runner: GdaRunner,
    argv: list[str],
    arguments: dict[str, Any],
    project: Optional[Path] = None,
) -> dict[str, Any] | types.CallToolResult:
    """Forward one MCP tool call to gda and map the outcome (ADR-0011/0015).

    Returns the success result *dict* (the SDK validates it against the tool's
    ``outputSchema`` and wraps it as ``structuredContent``) or a
    :class:`~mcp.types.CallToolResult` for a failure. Never raises for a gda
    failure: the low-level SDK flattens an exception to a prose ``isError``
    string, which would lose the structured envelope, so failures are *returned*
    as a ``CallToolResult`` instead.
    """
    params_json = json.dumps(arguments)
    # Verbatim passthrough (ADR-0015): the input object goes to gda on stdin via
    # ``--params-json -``; ``--json`` makes gda emit the machine-readable result.
    # gda-mcp builds no per-command argv beyond the command name — no binding
    # knowledge — so new commands/params reach the surface with no gda-mcp change.
    result = runner.run(
        [*argv, "--params-json", "-", "--json"], stdin=params_json, project=project
    )

    if result.returncode == 0:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # exit 0 but non-JSON stdout: gda could not have honored ``--json``.
            # Treat as the can't-run / non-envelope edge rather than crash.
            return _synthesized_error(
                "gda exited 0 but did not emit a JSON result for "
                f"{' '.join(argv)!r}",
                result,
            )

    envelope = _parse_error_envelope(result.stdout)
    if envelope is None:
        return _synthesized_error(
            f"gda failed (exit {result.returncode}) without a structured error "
            f"envelope for {' '.join(argv)!r}",
            result,
        )
    # Relay gda's envelope verbatim and losslessly (ADR-0011): the exact JSON gda
    # emitted, carrying {category, code, message, diagnostics}, kept out of
    # structuredContent / outputSchema.
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=result.stdout.strip())],
        isError=True,
    )


def build_server(runner: GdaRunner) -> Server:
    """Introspect the dump → register one tool per command → wire the dispatcher.

    The pure schema→tool transform (ADR-0012): gda-mcp carries no per-command
    knowledge, so it stays correct as gda's surface grows without edits here.
    """
    commands = _load_commands(runner)
    # Resolve the server's one target project (ADR-0014). env + cwd only for now;
    # the MCP roots/list precedence level (a live server->client request) is wired
    # in a later slice. The resolved dir reaches gda via the GDA_PROJECT env
    # channel on every dispatch (mechanism D), so meta commands ignore it.
    project = resolve_project_dir(os.environ, [], Path.cwd())
    tools = [
        types.Tool(
            name=tool_name(entry["name"]),
            description=entry["description"],
            inputSchema=entry["input"],
            outputSchema=entry["output"],
        )
        for entry in commands
    ]
    # Map each MCP tool name back to its gda command argv. Built from the dump's
    # own ``name`` (split on spaces), NOT by reversing tool_name — that mapping is
    # not injective (an underscore could have been a space OR a hyphen), so the
    # dump's name is the only exact source of the argv to dispatch.
    argv_by_tool = {
        tool_name(entry["name"]): entry["name"].split(" ") for entry in commands
    }

    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return tools

    # validate_input=False: gda owns input validation (ADR-0015 — gda-mcp forwards
    # verbatim and gda's params model validates), so invalid params surface as
    # gda's structured ``invalid_params`` envelope, not the SDK's prose error.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]):
        argv = argv_by_tool.get(name)
        if argv is None:
            # The SDK only routes registered tool names here; this is defensive.
            return types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=f"unknown tool: {name!r}")
                ],
                isError=True,
            )
        return dispatch(runner, argv, arguments or {}, project)

    return server


def run_stdio() -> None:
    """Serve gda-mcp over stdio (ADR-0013): the console-script run loop.

    Builds the server once (introspecting the dump — ADR-0012's single startup
    ``gda`` subprocess) and serves it over the stdio transport every surveyed
    agent registers (``command`` + ``args``). gda and gda-mcp share one version
    (ADR-0008), so the advertised ``server_version`` is gda's.
    """
    import anyio

    server = build_server(SubprocessGdaRunner.default())

    async def _serve() -> None:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name=SERVER_NAME,
                    server_version=version("gda"),
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    anyio.run(_serve)
