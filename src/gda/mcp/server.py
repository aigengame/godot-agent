"""The gda-mcp low-level stdio Server (ADR-0011/0012/0013/0039, issue #193).

A *generated* server: at startup it introspects gda's aggregate schema dump
(``gda schema``) and registers one MCP tool per command — name
``<group>_<command>``, ``description`` ← the command's help, ``input_schema`` /
``output_schema`` ← the command's input/output schemas (ADR-0012's faithful
mirror). On a tool call it shells out to the installed gda, forwarding the tool
input *verbatim* via ``gda <group> <command> --params-json -`` (the object on
stdin; ADR-0015), and maps the result mechanically off gda's exit code
(ADR-0011):

- **exit 0** → the ``--json`` result dict, wrapped by :func:`_success_result`
  into ``structured_content`` plus a JSON ``TextContent`` block (SDK v2 removed
  v1's auto-wrap, so gda-mcp reproduces it — clients that render ``content``
  keep seeing output). SDK v2 validates ``structured_content`` against the
  tool's ``output_schema`` on the **client** side only (v1's server-side check
  is gone; a non-SDK client sees the result unvalidated — ADR-0039). gda-mcp
  does NOT re-validate either way (Design decision 5): gda's result and its
  ``output_schema`` share one Pydantic model, so conformance is by
  construction;
- **exit ≠ 0** → ``CallToolResult(is_error=True)`` carrying the full ``GdaError``
  envelope *verbatim* as JSON content — lossless, never flattened to prose, and
  kept out of ``structured_content`` / ``output_schema`` (an error result
  without ``structured_content`` bypasses the SDK's output validation).

One server serves **both protocol eras** (ADR-0039): pre-2026 clients complete
the legacy ``initialize`` handshake and keep the roots back-channel; 2026-07-28
clients get the stateless request/response path, where project resolution
degrades to env → cwd (see :func:`_session_root_dirs`).

Why the low-level ``Server`` and not MCPServer (né FastMCP): our schemas come
*from* gda (not from Python signatures), tools are discovered at runtime and
served by one generic dispatcher, and we need direct control of the
result/error channels — the inverse of MCPServer's "one tool = one decorated
Python function" assumption.

gda-mcp consumes only gda's public CLI ABI (``--json`` / exit code / ``GdaError``
envelope); it never imports a gda internal symbol.
"""

import json
import os
import warnings
from importlib.metadata import version
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import mcp.server.stdio
import mcp.types as types
from mcp.server import CacheHint, Server, ServerRequestContext
from mcp.shared.exceptions import MCPDeprecationWarning

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


def _success_result(payload: dict[str, Any]) -> types.CallToolResult:
    """Wrap gda's success dict the way SDK v1 used to (ADR-0011, ADR-0039).

    v1's ``call_tool`` decorator auto-wrapped a returned dict into
    ``structuredContent`` plus an indented-JSON ``TextContent`` block; v2 removed
    the auto-wrap, so gda-mcp reproduces it verbatim (``indent=2`` included) —
    dropping the ``content`` block would silently blank the result in every
    client that renders ``content`` rather than ``structured_content``.
    """
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2))],
        structured_content=payload,
        is_error=False,
    )


def _synthesized_error(message: str, result: GdaResult) -> types.CallToolResult:
    """gda-mcp's own ``is_error`` result when gda produced no usable envelope.

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
        is_error=True,
    )


def dispatch(
    runner: GdaRunner,
    argv: list[str],
    arguments: dict[str, Any],
    project: Optional[Path] = None,
) -> types.CallToolResult:
    """Forward one MCP tool call to gda and map the outcome (ADR-0011/0015).

    Returns the full :class:`~mcp.types.CallToolResult` for success and failure
    alike (SDK v2 has no auto-wrap to lean on). Never raises for a gda failure:
    an exception escaping the handler becomes a JSON-RPC protocol error on the
    client (``MCPError``, not a tool result at all), which would lose the
    structured envelope entirely, so failures are *returned* instead.
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
            return _success_result(json.loads(result.stdout))
        except json.JSONDecodeError:
            # exit 0 but non-JSON stdout: gda could not have honored ``--json``.
            # Treat as the can't-run / non-envelope edge rather than crash.
            return _synthesized_error(
                f"gda exited 0 but did not emit a JSON result for {' '.join(argv)!r}",
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
    # structured_content / output_schema.
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=result.stdout.strip())],
        is_error=True,
    )


async def _session_root_dirs(session) -> list[str]:
    """The client's advertised roots as local dir paths (ADR-0014 precedence 2).

    A server->client ``roots/list`` back-channel request, so it needs a
    connection that *has* a back-channel: the ``can_send_request`` guard skips
    2026-07-28 stateless connections outright (SEP-2577 retired the roots
    capability there; without the guard the call would raise
    ``NoBackChannelError`` on every first tool call). Legacy connections — every
    surveyed agent today — keep exactly the pre-migration behavior. Best-effort
    beyond that: skip clients that do not declare the roots capability, and
    degrade any failure to *no roots* (gda's own cwd resolution then applies)
    rather than breaking dispatch — roots is one optional precedence level,
    never a hard dependency.
    """
    if not session.can_send_request:
        return []
    if not session.check_client_capability(
        types.ClientCapabilities(roots=types.RootsCapability())
    ):
        return []
    try:
        # Deprecated as of 2026-07-28 (SEP-2577, 12-month window) but the only
        # roots channel legacy clients have; suppressed because stderr is the
        # agent-visible log stream for a stdio server (ADR-0039). The deprecated
        # wrapper warns synchronously at call time, so the filter block closes
        # BEFORE the await: warnings filters are process-global state, and a
        # block spanning a suspension could interleave with a concurrent
        # request's save/restore and leak the filter.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MCPDeprecationWarning)
            pending = session.list_roots()
        result = await pending
    except Exception:
        return []
    # A Root.uri is a file:// URI; recover the local path (percent-decoded).
    dirs = [unquote(urlparse(str(root.uri)).path) for root in result.roots]
    return [d for d in dirs if d]


class _ProjectResolver:
    """Resolves and caches the server's one target project (ADR-0014).

    Resolution is deferred to the first tool call because precedence level 2
    (``roots/list``) is a server->client request needing a live session, then
    cached (one ``server : project``). On a client ``roots/list_changed``
    notification the cache is invalidated, so the next tool call re-runs the full
    precedence against the now-active roots (#209) — a pinned ``GDA_PROJECT`` still
    wins because :func:`resolve_project_dir` reads env first.
    """

    def __init__(self, env, cwd: Path) -> None:
        self._env = env
        self._cwd = cwd
        self._resolved = False
        self._project: Optional[Path] = None

    def invalidate(self) -> None:
        """Drop the cached project so the next ``resolve`` re-runs the precedence."""
        self._resolved = False
        self._project = None

    async def resolve(self, session) -> Optional[Path]:
        if not self._resolved:
            roots = await _session_root_dirs(session)
            self._project = resolve_project_dir(self._env, roots, self._cwd)
            self._resolved = True
        return self._project


def build_server(runner: GdaRunner) -> Server:
    """Introspect the dump → register one tool per command → wire the dispatcher.

    The pure schema→tool transform (ADR-0012): gda-mcp carries no per-command
    knowledge, so it stays correct as gda's surface grows without edits here.
    """
    commands = _load_commands(runner)
    # The server's one target project (ADR-0014), resolved lazily on the first
    # tool call (precedence 2, roots/list, needs a live session) and cached. The
    # resolved dir reaches gda via the GDA_PROJECT env channel on every dispatch
    # (mechanism D), so meta commands ignore it. A client roots/list_changed
    # invalidates the cache so the next call re-resolves (#209).
    resolver = _ProjectResolver(os.environ, Path.cwd())
    tools = [
        types.Tool(
            name=tool_name(entry["name"]),
            description=entry["description"],
            input_schema=entry["input"],
            output_schema=entry["output"],
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

    async def _list_tools(
        ctx: ServerRequestContext, params: Optional[types.PaginatedRequestParams]
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    # No input validation happens SDK-side (v2 dropped v1's opt-out jsonschema
    # check entirely): gda owns input validation (ADR-0015 — gda-mcp forwards
    # verbatim and gda's params model validates), so invalid params surface as
    # gda's structured ``invalid_params`` envelope, not an SDK prose error.
    async def _call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        argv = argv_by_tool.get(params.name)
        if argv is None:
            # The SDK only routes registered tool names here; this is defensive.
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text", text=f"unknown tool: {params.name!r}"
                    )
                ],
                is_error=True,
            )
        project = await resolver.resolve(ctx.session)
        return dispatch(runner, argv, params.arguments or {}, project)

    # A client roots/list_changed means the active project may have moved (#209):
    # invalidate the cache so the next tool call re-runs the ADR-0014 precedence
    # against the now-current roots. We only invalidate here, never resolve —
    # lazy re-resolution in _call_tool keeps resolve_project_dir the single
    # source of precedence (so a pinned GDA_PROJECT, read first there, still
    # wins) and cannot race an in-flight call. Legacy-only by nature: 2026-07-28
    # connections never deliver the notification (SEP-2577).
    async def _on_roots_list_changed(
        ctx: ServerRequestContext, params: Optional[types.NotificationParams]
    ) -> None:
        resolver.invalidate()

    # Registering on_roots_list_changed warns at construction time (the roots
    # capability is deprecated, SEP-2577); suppressed for the same stderr-is-log
    # reason as the list_roots call above (ADR-0039).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MCPDeprecationWarning)
        server = Server(
            SERVER_NAME,
            version=version("gda"),
            on_list_tools=_list_tools,
            on_call_tool=_call_tool,
            on_roots_list_changed=_on_roots_list_changed,
            # The tool surface is immutable for the process's lifetime (built
            # once from the startup dump, ADR-0012) and depends on no user,
            # auth, or project (ADR-0014 keeps the project out of the surface)
            # — so tools/list is safely cacheable for a long TTL at public
            # scope. Forward-compat only: the hint reaches 2026-07-28 clients;
            # pre-2026 clients see identical uncached traffic (#602).
            cache_hints={"tools/list": CacheHint(ttl_ms=3_600_000, scope="public")},
        )
    return server


def run_stdio() -> None:
    """Serve gda-mcp over stdio (ADR-0013): the console-script run loop.

    Builds the server once (introspecting the dump — ADR-0012's single startup
    ``gda`` subprocess) and serves it over the stdio transport every surveyed
    agent registers (``command`` + ``args``). gda and gda-mcp share one version
    (ADR-0008), so the ``version`` advertised at construction is gda's; one run
    loop serves both protocol eras (ADR-0039).
    """
    import anyio

    server = build_server(SubprocessGdaRunner.default())

    async def _serve() -> None:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    anyio.run(_serve)
