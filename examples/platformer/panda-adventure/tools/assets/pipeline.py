"""Orchestration: preprocess -> acquire -> postprocess -> emit for one asset.

The reusable spine the CLI and a game's live acquire tests both drive. Given an
asset id from the per-game style config, it composes the spec, fulfils it
through the chosen acquire mode/backend, conforms the result to the pixel-art
regime and the configured size spec, and records the Asset manifest entry. The
network / generation boundary is injected (``fetch`` / ``backend``), so a
caller can mock it or run it for real. A recipe that names something the style
config does not declare (an asset id, a source, a backend) is a structured
:class:`~assets.config.ConfigError` refusal, not a stray ``KeyError``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from . import acquire, preprocess
from .acquire import Fetch, default_fetch
from .backends import GenerationBackend
from .config import (
    ConfigError,
    StyleConfig,
    asset_output_path,
    asset_resource_path,
    make_builtin_backend,
    make_mcp_backend,
    target_dims,
)
from .emitter import Emitter, JsonManifestEmitter
from .model import AcquireMode, AcquireResult, AssetSpec, ManifestEntry
from .packer import pack_frames
from .postprocess import postprocess_image

# The default license recorded for a generated asset: its BACKEND's usage terms,
# NOT a download license (a generated asset is authored under the generator's
# terms, distinct from an open-license download). Gemini is the default
# generation backend today; a recipe overrides these per asset, and a future
# backend records its own terms. The license gate rejects a generated asset
# that carries a download license instead.
_GENERATED_LICENSE = "Gemini-Generated"
_GENERATED_LICENSE_URL = "https://ai.google.dev/gemini-api/terms"


def _request(config: StyleConfig, asset_id: str) -> dict[str, Any]:
    if asset_id not in config.assets:
        raise ConfigError(
            "asset_unknown",
            f"asset {asset_id!r} is not declared in the style config's 'assets' "
            f"({config.path})",
        )
    return config.assets[asset_id]


def build_spec_for(
    config: StyleConfig, asset_id: str, game_root: Path | None = None
) -> AssetSpec:
    """Preprocess: the composed :class:`AssetSpec` for one configured asset."""
    request = _request(config, asset_id)
    scale_key = request.get("scale_key")
    if scale_key is None:
        raise ConfigError(
            "config_invalid",
            f"asset {asset_id!r} has no 'scale_key' in the style config "
            f"({config.path}) — a spec-driven acquire needs its size-spec box",
        )
    dims = target_dims(config, scale_key, game_root)
    return preprocess.build_asset_spec(
        asset_id,
        request["category"],
        dims,
        config.style,
        subject=request.get("subject"),
        hint=request.get("category_hint"),
    )


def _acquire(
    config: StyleConfig,
    spec: AssetSpec,
    recipe: dict[str, Any],
    raw_dest: Path,
    *,
    mode: AcquireMode,
    backend: GenerationBackend | None,
    fetch: Fetch,
    game_root: Path,
) -> AcquireResult:
    if mode is AcquireMode.SEARCH_DOWNLOAD:
        source_name = recipe.get("source")
        if source_name is None:
            raise ConfigError(
                "config_invalid",
                f"asset {spec.id!r} search-download recipe names no 'source' "
                f"({config.path})",
            )
        if source_name not in config.sources:
            raise ConfigError(
                "source_unknown",
                f"unknown source {source_name!r} in the style config ({config.path})",
            )
        return acquire.search_download(
            spec,
            recipe,
            config.sources[source_name],
            raw_dest,
            allowed_licenses=config.style.allowed_licenses,
            fetch=fetch,
        )
    if backend is None:
        backend = _default_backend(config, recipe, game_root)
    prompt = preprocess.render_generation_prompt(spec)
    return acquire.generate(
        spec,
        prompt,
        backend,
        raw_dest,
        license_name=str(recipe.get("license", _GENERATED_LICENSE)),
        license_url=str(recipe.get("license_url", _GENERATED_LICENSE_URL)),
    )


def _default_backend(
    config: StyleConfig, recipe: dict[str, Any], game_root: Path | None = None
) -> GenerationBackend:
    """The generation backend named by the recipe (``mcp:<channel>`` | ``builtin``).

    The recipe's per-asset ``model`` is threaded into the MCP backend (recipe wins;
    the pipeline default applies when omitted) so a shared channel never dictates a
    sibling asset's model.
    """
    backend = str(recipe.get("backend", "builtin"))
    if backend == "builtin":
        return make_builtin_backend(config, game_root)
    if backend.startswith("mcp:"):
        model = recipe.get("model")
        return make_mcp_backend(
            config,
            backend[len("mcp:") :],
            game_root,
            model=str(model) if model is not None else None,
        )
    raise ConfigError(
        "backend_unknown",
        f"unknown generation backend {backend!r} in the recipe "
        "(expected 'builtin' or 'mcp:<channel>')",
    )


def acquire_asset(
    config: StyleConfig,
    asset_id: str,
    *,
    game_root: Path | None = None,
    mode: AcquireMode | None = None,
    backend: GenerationBackend | None = None,
    fetch: Fetch = default_fetch,
    raw_dir: Path | None = None,
    emitter: Emitter | None = None,
    emit: bool = True,
) -> ManifestEntry:
    """Run the whole pipeline for ``asset_id`` and return the manifest entry.

    ``game_root`` overrides the style config's own root (an isolated test root);
    ``mode``/``backend`` override the recipe (the live tests force a specific
    mode/backend); ``fetch`` is the injected search-download boundary; ``emit``
    controls whether the manifest fragment is written (the tests emit into a temp
    manifest to avoid a committed orphan).
    """
    root = game_root if game_root is not None else config.game_root
    request = _request(config, asset_id)
    recipe = dict(request["acquire"])
    category = request["category"]
    spec = build_spec_for(config, asset_id, root)
    acquire_mode = mode or AcquireMode(recipe.get("mode", "search_download"))

    raw_root = Path(raw_dir) if raw_dir is not None else Path(tempfile.mkdtemp())
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_dest = raw_root / f"{asset_id}.raw.png"
    result = _acquire(
        config,
        spec,
        recipe,
        raw_dest,
        mode=acquire_mode,
        backend=backend,
        fetch=fetch,
        game_root=root,
    )

    out_path = asset_output_path(config, category, asset_id, root)
    chroma = config.style.chroma_key if acquire_mode is AcquireMode.GENERATION else None
    postprocess_image(
        result.raw_path,
        out_path,
        spec.target_dims,
        config.style.palette,
        chroma_key=chroma,
    )

    entry = ManifestEntry(
        id=asset_id,
        path=asset_resource_path(config, category, asset_id),
        category=category,
        acquire_mode=result.acquire_mode.value,
        source=result.source,
        license=result.license,
        license_url=result.license_url,
        target_dims=spec.target_dims,
        source_url=result.source_url,
        attribution=result.attribution,
        prompt=result.prompt,
        backend=result.backend,
        model=result.model,
    )
    if emit:
        (emitter or JsonManifestEmitter(root, config.assets_root)).emit(entry)
    return entry


def pack_sprite_set(
    frame_paths: list[Path],
    out_path: Path,
    resource_path: str,
    asset_id: str,
    category: str,
    *,
    source: str,
    license_name: str,
    license_url: str,
    target_dims: tuple[int, int] | None = None,
    acquire_mode: str = "search_download",
    source_url: str | None = None,
    attribution: str | None = None,
    emitter: Emitter | None = None,
) -> ManifestEntry:
    """Orchestrate a sprite set: loose frames -> committed sheet + manifest entry.

    The pipeline's sprite-set entry point, so an acquire slice reuses the
    pack+record choreography instead of re-inventing it: packs ``frame_paths``
    into one spritesheet at ``out_path`` (:func:`assets.packer.pack_frames`),
    then builds and — when an ``emitter`` is given — writes the
    :class:`~assets.model.ManifestEntry` carrying the frame layout plus the
    provenance/license invariant (``target_dims`` defaults to the packed frame
    box). The Godot ``SpriteFrames`` derivation stays a separate,
    independently-callable step (:func:`assets.spriteframes.derive_spriteframes`);
    the network/generation acquire of the frames and the runtime sprite render
    are out of scope here.
    """
    layout = pack_frames(frame_paths, out_path)
    entry = ManifestEntry(
        id=asset_id,
        path=resource_path,
        category=category,
        acquire_mode=acquire_mode,
        source=source,
        license=license_name,
        license_url=license_url,
        target_dims=target_dims or layout.frame_dims,
        source_url=source_url,
        attribution=attribution,
        frame_layout=layout,
    )
    if emitter is not None:
        emitter.emit(entry)
    return entry
