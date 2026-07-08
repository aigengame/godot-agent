"""Generation's two backends: an external MCP channel and the agent's own gen.

Generation derives two INDEPENDENT backends (gADR-0014):

- :class:`McpBackend` — an MCP *client* that speaks to a pluggable external
  image-generation MCP channel over stdio. ``scripts/mcp/gemini_img_gen.py``
  (Gemini) is the first channel; more are added as new channels, never new acquire
  modes. The ``mcp`` / ``google-genai`` dependencies live in the optional live-only
  group CI does not install, so they are **lazy-imported** inside the methods here
  — importing this module never requires them, keeping CI collection green.
- :class:`BuiltinBackend` — the running agent's OWN built-in image generation,
  invoked out-of-process (the pipeline renders the prompt, the agent generates, the
  pipeline ingests). An agent WITHOUT the capability (Claude Code has none) follows
  a configured fallback backend or raises a clear user-facing error — never a
  silent no-op.

Both satisfy the :class:`GenerationBackend` protocol; the acquire stage treats them
uniformly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class GenerationError(RuntimeError):
    """A generation backend failed to produce the requested image."""


class BuiltinImageGenUnavailable(GenerationError):
    """The running agent has no built-in image generation and no fallback.

    Raised (never a silent no-op, gADR-0014) when BuiltinBackend is asked to
    generate on an agent that cannot — the clear, user-facing failure the demo's
    live test asserts on Claude Code.
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

    def generate(self, prompt: str, out_path: Path) -> None:
        import asyncio

        out_path.parent.mkdir(parents=True, exist_ok=True)
        text = asyncio.run(self._call(prompt, out_path))
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise GenerationError(
                f"MCP channel {self._channel!r} returned no image at {out_path} "
                f"(tool said: {text})"
            )

    async def _call(self, prompt: str, out_path: Path) -> str:
        # Lazy import: the live-only group carries `mcp`; CI never installs it, so
        # importing this module must not need it (gADR-0014).
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

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
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(self._tool, arguments)
        return _content_text(result)


class BuiltinBackend:
    """The running agent's own image generation, delegated out-of-process.

    The pipeline renders the prompt and hands it to the agent's generator via a
    configured out-of-process ``command`` (which must write the image to
    ``out_path``). When no command is configured — the running agent has no
    built-in generator, e.g. Claude Code — a configured ``fallback`` backend is
    used, or, absent one, :class:`BuiltinImageGenUnavailable` is raised (never a
    silent no-op, gADR-0014).
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
                "for a capable agent, or generation.builtin.fallback (e.g. the "
                "Gemini MCP channel) to delegate (gADR-0014)"
            )
        argv = [
            arg.replace("{prompt}", prompt).replace("{output}", str(out_path))
            for arg in self._command
        ]
        proc = subprocess.run(
            argv, capture_output=True, text=True, env=self._env, timeout=self._timeout
        )
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
