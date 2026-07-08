"""Panda Adventure plug-in: load the Style descriptor + per-asset acquire recipes.

The ONE per-game module of the asset pipeline (gADR-0014's per-game configuration,
the analogue of ``balancing/game_config.py``). It knows this game's on-disk shape —
``panda_adventure.style.json`` (the Style descriptor, the CC0/CC-BY sources, the
generation channels, and the per-asset acquire recipes) and ``scale_spec.json`` (the
single size authority, gADR-0013) — and maps them into the game-agnostic core's
:class:`~assets.model.StyleDescriptor` / :class:`~assets.model.Source` and the
target dimensions preprocess composes. It reads JSON only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backends import BuiltinBackend, GenerationBackend, McpBackend
from .model import Source, StyleDescriptor

# The committed per-game config, next to this module (the balancing targets idiom).
DEFAULT_STYLE_PATH = Path(__file__).resolve().parent / "panda_adventure.style.json"
# tools/assets/ -> tools/ -> <game root>.
GAME_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class StyleConfig:
    """The whole per-game asset configuration, parsed from ``*.style.json``."""

    style: StyleDescriptor
    sources: dict[str, Source]
    assets: dict[str, dict[str, Any]]
    assets_root: str
    scale_spec_rel: str
    generation: dict[str, Any]
    lfs_size_threshold_bytes: int


def load_style_config(path: Path = DEFAULT_STYLE_PATH) -> StyleConfig:
    """Parse the per-game style config into a :class:`StyleConfig`."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    style_doc = doc["style"]
    constraints = doc["constraints"]
    style = StyleDescriptor(
        keywords=tuple(style_doc["keywords"]),
        prompt_fragment=style_doc["prompt_fragment"],
        palette=tuple(style_doc["palette"]),
        category_hints=dict(style_doc.get("category_hints", {})),
        formats=tuple(constraints["formats"]),
        allowed_licenses=tuple(constraints["allowed_licenses"]),
        chroma_key=constraints["chroma_key"],
    )
    sources = {
        src["name"]: Source(
            name=src["name"],
            kind=src["kind"],
            base_url=src["base_url"],
            default_license=src["default_license"],
            license_url=src["license_url"],
        )
        for src in doc["sources"]
    }
    return StyleConfig(
        style=style,
        sources=sources,
        assets=dict(doc["assets"]),
        assets_root=doc.get("assets_root", "assets"),
        scale_spec_rel=doc.get("scale_spec", "data/json/scale_spec.json"),
        generation=dict(doc.get("generation", {})),
        lfs_size_threshold_bytes=int(
            doc.get("lifecycle", {}).get("lfs_size_threshold_bytes", 1_048_576)
        ),
    )


def target_dims(
    config: StyleConfig, scale_key: str, game_root: Path = GAME_ROOT
) -> tuple[int, int]:
    """The asset's exact pixel dimensions from the Scale spec (gADR-0013)."""
    scale = json.loads((game_root / config.scale_spec_rel).read_text(encoding="utf-8"))
    if scale_key not in scale:
        raise KeyError(
            f"scale key {scale_key!r} is not in {config.scale_spec_rel} "
            "(gADR-0013 is the single size authority)"
        )
    dims = scale[scale_key]
    return (int(dims[0]), int(dims[1]))


def asset_resource_path(config: StyleConfig, category: str, asset_id: str) -> str:
    """The ``res://`` path the produced asset lands at and the manifest records."""
    return f"res://{config.assets_root}/{category}/{asset_id}.png"


def asset_output_path(
    config: StyleConfig, category: str, asset_id: str, game_root: Path = GAME_ROOT
) -> Path:
    """The on-disk path :func:`asset_resource_path` resolves to."""
    return game_root / config.assets_root / category / f"{asset_id}.png"


def make_mcp_backend(
    config: StyleConfig, channel: str, game_root: Path = GAME_ROOT
) -> McpBackend:
    """Build the MCP generation backend for a configured channel (e.g. Gemini)."""
    import sys

    channels = config.generation.get("mcp", {}).get("channels", {})
    if channel not in channels:
        raise KeyError(f"no MCP generation channel {channel!r} in the style config")
    spec = channels[channel]
    command = [
        part.replace("{python}", sys.executable).replace("{game_root}", str(game_root))
        for part in spec["command"]
    ]
    return McpBackend(
        channel=channel,
        command=command,
        tool=spec.get("tool", "generate_image"),
        arguments=dict(spec.get("arguments", {})),
    )


def make_builtin_backend(
    config: StyleConfig, game_root: Path = GAME_ROOT
) -> BuiltinBackend:
    """Build the BuiltinBackend, wiring its configured fallback if any."""
    spec = config.generation.get("builtin", {})
    command = spec.get("command")
    fallback: GenerationBackend | None = None
    fallback_channel = spec.get("fallback")
    if fallback_channel:
        fallback = make_mcp_backend(config, fallback_channel, game_root)
    return BuiltinBackend(command=command, fallback=fallback)
