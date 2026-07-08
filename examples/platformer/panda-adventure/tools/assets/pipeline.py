"""Orchestration: preprocess -> acquire -> postprocess -> emit for one asset.

The reusable spine the CLI and the ``acquire_live`` tests both drive (gADR-0014).
Given an asset id from the per-game config, it composes the spec, fulfils it
through the chosen acquire mode/backend, conforms the result to the pixel-art
regime and the Scale spec size, and records the Asset manifest entry. The network /
generation boundary is injected (``fetch`` / ``backend``), so a caller can mock it
or run it for real.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from . import acquire, game_config, preprocess
from .acquire import AcquireError, Fetch, default_fetch
from .backends import GenerationBackend
from .emitter import Emitter, JsonManifestEmitter
from .game_config import StyleConfig
from .model import AcquireMode, AcquireResult, AssetSpec, ManifestEntry
from .postprocess import postprocess_image

# The default license recorded for a generated asset (the pipeline authored it).
_GENERATED_LICENSE = "CC0"
_GENERATED_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def _request(config: StyleConfig, asset_id: str) -> dict[str, Any]:
    if asset_id not in config.assets:
        raise KeyError(
            f"asset {asset_id!r} is not declared in the style config's 'assets'"
        )
    return config.assets[asset_id]


def build_spec_for(
    config: StyleConfig, asset_id: str, game_root: Path = game_config.GAME_ROOT
) -> AssetSpec:
    """Preprocess: the composed :class:`AssetSpec` for one configured asset."""
    request = _request(config, asset_id)
    dims = game_config.target_dims(config, request["scale_key"], game_root)
    return preprocess.build_asset_spec(
        asset_id, request["category"], dims, config.style
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
        source_name = str(recipe["source"])
        if source_name not in config.sources:
            raise AcquireError(f"unknown source {source_name!r} in the style config")
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
    config: StyleConfig, recipe: dict[str, Any], game_root: Path
) -> GenerationBackend:
    """The generation backend named by the recipe (``mcp:<channel>`` | ``builtin``)."""
    backend = str(recipe.get("backend", "builtin"))
    if backend == "builtin":
        return game_config.make_builtin_backend(config, game_root)
    if backend.startswith("mcp:"):
        return game_config.make_mcp_backend(config, backend[len("mcp:") :], game_root)
    raise AcquireError(f"unknown generation backend {backend!r} in the recipe")


def acquire_asset(
    config: StyleConfig,
    asset_id: str,
    *,
    game_root: Path = game_config.GAME_ROOT,
    mode: AcquireMode | None = None,
    backend: GenerationBackend | None = None,
    fetch: Fetch = default_fetch,
    raw_dir: Path | None = None,
    emitter: Emitter | None = None,
    emit: bool = True,
) -> ManifestEntry:
    """Run the whole pipeline for ``asset_id`` and return the manifest entry.

    ``mode``/``backend`` override the recipe (the live tests force a specific
    mode/backend); ``fetch`` is the injected search-download boundary; ``emit``
    controls whether the manifest fragment is written (the tests emit into a temp
    manifest to avoid a committed orphan).
    """
    request = _request(config, asset_id)
    recipe = dict(request["acquire"])
    category = request["category"]
    spec = build_spec_for(config, asset_id, game_root)
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
        game_root=game_root,
    )

    out_path = game_config.asset_output_path(config, category, asset_id, game_root)
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
        path=game_config.asset_resource_path(config, category, asset_id),
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
    )
    if emit:
        (emitter or JsonManifestEmitter(game_root, config.assets_root)).emit(entry)
    return entry
