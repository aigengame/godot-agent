"""The asset pipeline's plain dataclasses — the game-agnostic core's vocabulary.

The read-only value types the preprocess -> acquire -> postprocess -> emit stages
pass between them (gADR-0014). No IO, no game code, no Godot: just the shapes.

- ``StyleDescriptor`` — the machine-consumable style parameters shared across BOTH
  acquire modes (Style descriptor, GAME-CONTEXT): style keywords/prompt fragment,
  the bounded pixel-art palette, per-category hints, and the format/licensing
  constraints. A per-game plug-in input, loaded from ``*.style.json``.
- ``Source`` — one configurable open-asset source (search-download) or the marker
  of a generation channel; CC0/CC-BY only (never hardcoded, gADR-0014).
- ``AssetSpec`` — the preprocess output: the style descriptor composed with the
  Scale spec's target dimensions for ONE asset, rendered as a search query or a
  generation prompt (one spec, both modes, so style coheres).
- ``AcquireResult`` — what the acquire stage returns: the raw acquired file plus
  its recorded provenance and license (a pipeline invariant).
- ``ManifestEntry`` — one Asset manifest record: ``id -> {path, category,
  acquire_mode, source, license, license_url, target_dims}`` plus optional
  provenance detail (the source URL for search-download, the prompt/backend for
  generation). The single HOME of an asset's path; the JSON authority references
  the ``id`` and the builder composes ``id -> path`` (gADR-0014).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AcquireMode(str, Enum):
    """The two acquire modes (gADR-0014). Value is the manifest ``acquire_mode``."""

    SEARCH_DOWNLOAD = "search_download"
    GENERATION = "generation"


class GenerationBackendKind(str, Enum):
    """Generation's two independent backends (gADR-0014).

    ``MCP`` is a pluggable external MCP image-generation channel (Gemini being the
    first); ``BUILTIN`` is the running agent's own image generation, delegated
    out-of-process. An MCP channel is NOT the BuiltinBackend.
    """

    MCP = "mcp"
    BUILTIN = "builtin"


@dataclass(frozen=True)
class StyleDescriptor:
    """The shared art-direction input that makes mixed-source assets cohere.

    ``keywords``/``prompt_fragment`` seed the search query and generation prompt;
    ``palette`` is the bounded pixel-art palette postprocess quantizes to;
    ``category_hints`` refine per category; ``formats``/``allowed_licenses`` are
    the format/licensing constraints; ``chroma_key`` is the solid background color
    a generation backend is asked to render behind the subject so postprocess can
    key it out (Style descriptor, gADR-0014).
    """

    keywords: tuple[str, ...]
    prompt_fragment: str
    palette: tuple[str, ...]
    category_hints: dict[str, str]
    formats: tuple[str, ...]
    allowed_licenses: tuple[str, ...]
    chroma_key: str


@dataclass(frozen=True)
class Source:
    """One configurable acquire source (gADR-0014): CC0/CC-BY, never hardcoded."""

    name: str
    kind: str  # "search-download" | "generation"
    base_url: str
    default_license: str
    license_url: str


@dataclass(frozen=True)
class AssetSpec:
    """The preprocess output for ONE asset — the style + size composed together.

    Rendered as a search query (search-download) or a generation prompt
    (generation) by :mod:`preprocess`, so one spec drives both modes and the
    style coheres (gADR-0014).
    """

    id: str
    category: str
    target_dims: tuple[int, int]
    style: StyleDescriptor

    @property
    def category_hint(self) -> str:
        """The per-category style hint (empty when the category has none)."""
        return self.style.category_hints.get(self.category, "")


@dataclass(frozen=True)
class AcquireResult:
    """What the acquire stage returns before postprocess: the raw file + record.

    ``raw_path`` is the acquired file as-fetched/as-generated; postprocess conforms
    it and the emitter records the rest into the Asset manifest (gADR-0014). The
    license is a pipeline invariant — an acquire that cannot record one fails.
    """

    raw_path: Path
    acquire_mode: AcquireMode
    source: str
    license: str
    license_url: str
    source_url: str | None = None
    attribution: str | None = None
    prompt: str | None = None
    backend: str | None = None


@dataclass(frozen=True)
class FrameLayout:
    """How a packed spritesheet is tiled (gADR-0015): the per-frame box + grid.

    A sprite-frame set is committed as ONE spritesheet per animation state; this
    records how that sheet is laid out so the manifest carries it and the
    SpriteFrames deriver turns it into ``AtlasTexture`` regions. ``frame_dims`` is
    one frame's ``(width, height)``; ``columns``/``rows`` the grid the frames fill
    left-to-right then top-to-bottom; ``count`` the frame total
    (``<= columns * rows``). A value shape (no Pillow) so the manifest can carry
    it without pulling the packer's imaging dependency.
    """

    frame_dims: tuple[int, int]
    columns: int
    rows: int
    count: int


@dataclass(frozen=True)
class ManifestEntry:
    """One Asset manifest record (gADR-0014).

    The seven core fields (``path``/``category``/``acquire_mode``/``source``/
    ``license``/``license_url``/``target_dims``) plus optional provenance detail.
    ``path`` is the resource path the game loads (``res://...``); it is the single
    home of the asset's path (the authority references ``id``, the builder composes
    ``id -> path``). A sprite-set entry additionally carries its ``frame_layout``
    (gADR-0015) — the packed sheet's tiling, which a plain texture entry omits.
    """

    id: str
    path: str
    category: str
    acquire_mode: str
    source: str
    license: str
    license_url: str
    target_dims: tuple[int, int]
    source_url: str | None = None
    attribution: str | None = None
    prompt: str | None = None
    backend: str | None = None
    frame_layout: FrameLayout | None = None
