"""Generation's two backends: an external MCP channel and the agent's own gen.

Generation derives two INDEPENDENT backends:

- :class:`McpBackend` — an MCP *client* that speaks to a pluggable external
  image-generation MCP channel over stdio (a Gemini stdio server being the
  first configured channel); more providers are added as new channels, never
  new acquire modes. The ``mcp`` / ``google-genai`` dependencies live in an
  optional live-only group CI does not install, so they are **lazy-imported**
  inside the methods here — importing this module never requires them, keeping
  CI collection green.
- :class:`BuiltinBackend` — the running agent's OWN built-in image generation,
  invoked out-of-process (the pipeline renders the prompt, the agent generates,
  the pipeline ingests). An agent WITHOUT the capability follows a configured
  fallback backend or raises a clear user-facing error — never a silent no-op.

Both satisfy the :class:`GenerationBackend` protocol; the acquire stage treats them
uniformly.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol


class GenerationError(RuntimeError):
    """A generation backend failed to produce the requested image."""


class BuiltinImageGenUnavailable(GenerationError):
    """The running agent has no built-in image generation and no fallback.

    Raised (never a silent no-op) when BuiltinBackend is asked to generate on
    an agent that cannot — the clear, user-facing failure a live test asserts
    on an agent with no native image generation.
    """


class GenerationBackend(Protocol):
    """A generation backend: render this prompt to an image file at ``out_path``.

    Raises :class:`GenerationError` (or a subclass) on any failure; on success the
    file at ``out_path`` exists and is a real image. ``name`` identifies the
    backend/channel for the manifest record.
    """

    @property
    def name(self) -> str: ...

    def generate(self, prompt: str, out_path: Path) -> None: ...


class McpBackend:
    """A generation backend backed by an external image-gen MCP channel.

    Launches the channel's MCP server over stdio, calls its ``generate_image``
    tool with the prompt and output path, and confirms the file was written. The
    channel is configurable (``command``/``tool``/``arguments``); the Gemini server
    is the first channel. ``mcp`` is lazy-imported so this module imports without
    the live-only group.
    """

    def __init__(
        self,
        channel: str,
        command: list[str],
        *,
        tool: str = "generate_image",
        arguments: dict[str, object] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 180.0,
    ) -> None:
        self._channel = channel
        self._command = command
        self._tool = tool
        self._arguments = dict(arguments or {})
        # The channel server reads its own API key from the environment, so pass
        # the current environment through by default (the key is NOT a config
        # value the pipeline ever stores).
        self._env = env if env is not None else {**os.environ}
        self._timeout = timeout

    @property
    def name(self) -> str:
        return f"mcp:{self._channel}"

    @property
    def model(self) -> str | None:
        """The concrete image model this channel is configured to use, if any.

        Read from the channel's ``arguments`` (e.g. the Gemini ``model``), so the
        acquire stage can record it as generation provenance. ``None``
        when the channel leaves the tool's own default model in force.
        """
        value = self._arguments.get("model")
        return str(value) if value is not None else None

    def generate(self, prompt: str, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = asyncio.run(self._call(prompt, out_path))
        except GenerationError:
            raise
        except Exception as exc:
            # Launch/transport/session failures (a missing server executable, a
            # broken stdio pipe, a protocol error during initialize) are
            # foreseeable channel failures, normalized HERE so every caller sees
            # the one GenerationError contract instead of a raw spawn error.
            # Process interrupts stay BaseException and pass through.
            raise GenerationError(
                f"MCP channel {self._channel!r} failed to start or communicate: {exc!r}"
            ) from exc
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise GenerationError(
                f"MCP channel {self._channel!r} returned no image at {out_path} "
                f"(tool said: {text})"
            )

    async def _call(self, prompt: str, out_path: Path) -> str:
        # Lazy import: the live-only group carries `mcp`; CI never installs it, so
        # importing this module must not need it.
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.shared.exceptions import MCPError

        params = StdioServerParameters(
            command=self._command[0],
            args=self._command[1:],
            env=self._env,
        )
        arguments: dict[str, object] = {
            "prompt": prompt,
            "output_path": str(out_path),
            **self._arguments,
        }
        # Bound the call with mcp's native per-request read timeout, so a hung
        # image-gen call cannot hang an on-demand acquire forever. Capture the
        # MCPError and raise AFTER the context exits cleanly — raising THROUGH the
        # anyio-backed `async with` teardown would surface a task-group
        # ExceptionGroup instead of our clear error.
        result = None
        error: MCPError | None = None
        # mode="legacy" keeps the pre-migration handshake (the v1 client spoke
        # `initialize`) and skips the default auto-mode discover probe — one
        # fewer round trip per acquire, identical behavior for any channel server.
        async with Client(stdio_client(params), mode="legacy") as client:
            try:
                result = await client.call_tool(
                    self._tool,
                    arguments,
                    read_timeout_seconds=self._timeout,
                )
            except MCPError as exc:
                error = exc
        if error is not None:
            raise GenerationError(
                f"MCP channel {self._channel!r} call to {self._tool!r} failed or "
                f"timed out (limit {self._timeout}s): {error}"
            ) from error
        return _content_text(result)


class BuiltinBackend:
    """The running agent's own image generation, delegated out-of-process.

    The pipeline renders the prompt and hands it to the agent's generator via a
    configured out-of-process ``command`` (which must write the image to
    ``out_path``). When no command is configured — the running agent has no
    built-in generator — a configured ``fallback`` backend is used, or, absent
    one, :class:`BuiltinImageGenUnavailable` is raised (never a silent no-op).
    """

    def __init__(
        self,
        *,
        command: list[str] | None = None,
        fallback: GenerationBackend | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 180.0,
    ) -> None:
        self._command = command
        self._fallback = fallback
        self._env = env if env is not None else {**os.environ}
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "builtin"

    @property
    def available(self) -> bool:
        """Whether this agent can generate in-process (a command is configured)."""
        return self._command is not None

    def generate(self, prompt: str, out_path: Path) -> None:
        import subprocess

        out_path.parent.mkdir(parents=True, exist_ok=True)
        if self._command is None:
            if self._fallback is not None:
                self._fallback.generate(prompt, out_path)
                return
            raise BuiltinImageGenUnavailable(
                "the running agent has no built-in image generation and no "
                "fallback backend is configured — set generation.builtin.command "
                "for a capable agent, or generation.builtin.fallback (e.g. an "
                "MCP image-gen channel) to delegate"
            )
        argv = [
            arg.replace("{prompt}", prompt).replace("{output}", str(out_path))
            for arg in self._command
        ]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                env=self._env,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GenerationError(
                f"builtin generation command timed out after {self._timeout}s: "
                f"{argv[0]}"
            ) from exc
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            # A missing/unrunnable executable or an unlaunchable argv is a
            # foreseeable backend failure: the one GenerationError contract,
            # never a raw FileNotFoundError out of the acquire path.
            raise GenerationError(
                f"builtin generation command could not run ({argv[0] if argv else '<empty>'}): {exc}"
            ) from exc
        if proc.returncode != 0:
            raise GenerationError(
                f"builtin generation command failed ({proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise GenerationError(
                f"builtin generation command wrote no image at {out_path}"
            )


def _content_text(result: object) -> str:
    """Flatten an MCP ``CallToolResult``'s content blocks into a text summary."""
    content = getattr(result, "content", None)
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)
