"""Gemini image-generation MCP server — the asset pipeline's first McpBackend channel.

An MCP (stdio) server exposing a single ``generate_image`` tool backed by Google's
Gemini image models. The asset pipeline's :class:`assets.backends.McpBackend` is an
MCP *client* that launches this server and calls the tool (gADR-0014): render a
prompt to a PNG on disk, which postprocess then conforms to the pixel-art regime.

The Gemini client is created LAZILY, at call time, from ``GEMINI_API_KEY`` in the
environment — importing this module never touches the key (so a missing key is a
clear tool error, not an import-time ``KeyError``). ``mcp`` and ``google-genai``
live in the pipeline's optional live-only dependency group; this server runs only
when a real generation is requested.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from google import genai
from google.genai import types
from mcp.server import MCPServer
from pydantic import Field

mcp = MCPServer("gemini-nano-banana")

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """The Gemini client, created lazily from ``GEMINI_API_KEY`` at first use."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set — the Gemini MCP channel needs an API "
                "key in the environment to generate images"
            )
        _client = genai.Client(api_key=api_key)
    return _client


@mcp.tool()
def generate_image(
    prompt: Annotated[
        str,
        Field(
            description=(
                "A detailed description of the image: subject, style "
                "(realistic / anime / oil painting), lighting, composition, and "
                "quality words (8k, detailed). Example: 'a futuristic Tokyo "
                "street at night, neon signs, heavy rain, cyberpunk style, "
                "photorealistic, 8k'"
            )
        ),
    ],
    output_path: Annotated[
        str,
        Field(
            description=(
                "Where to save the image, including the file name and extension, "
                "e.g. /tmp/result.png or ~/Desktop/output.png"
            ),
        ),
    ] = "./generated_image.png",
    model: Annotated[
        str,
        Field(
            description=(
                "Image model to use:\n"
                "- gemini-3.1-flash-image-preview: Nano Banana 2, fastest, the "
                "everyday default\n"
                "- gemini-3-pro-image-preview: Nano Banana Pro, professional "
                "quality\n"
                "- gemini-2.5-flash-image: Nano Banana original, lightweight/fast"
            ),
        ),
    ] = "gemini-3.1-flash-image-preview",
    aspect_ratio: Annotated[
        str,
        Field(
            description=(
                "Aspect ratio. 16:9 for landscape, 9:16 for portrait/phone "
                "wallpaper, 1:1 for square (default 1:1)"
            )
        ),
    ] = "1:1",
    image_size: Annotated[
        str,
        Field(description="Resolution: 512 / 1K / 2K / 4K (default 1K)"),
    ] = "1K",
) -> str:
    """Generate a brand-new image from a text ``prompt`` with Gemini and save it.

    Supports several aspect ratios and resolutions. Returns the saved file path on
    success, or an error description on failure.
    """
    try:
        response = _get_client().models.generate_content(
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size=image_size,
                ),
            ),
        )

        save_path = Path(output_path).expanduser().resolve()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        result_texts: list[str] = []
        image_saved = False

        for part in response.parts:
            if part.text is not None:
                result_texts.append(part.text)
            elif part.inline_data is not None:
                # Official recommendation: part.as_image() returns a PIL Image.
                image = part.as_image()
                image.save(str(save_path))
                result_texts.append(f"Image saved to: {save_path}")
                image_saved = True

        if not image_saved:
            result_texts.append(
                "No image data returned — check whether the prompt violates the "
                "content policy"
            )

        return "\n".join(result_texts)

    except Exception as exc:  # noqa: BLE001 — report any backend failure as text
        return f"Generation failed: {type(exc).__name__}: {exc}"


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
