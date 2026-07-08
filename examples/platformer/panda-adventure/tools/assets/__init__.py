"""Asset pipeline — the Tool Script family that produces the game's binary assets.

A ``Tool Script`` (GAME-CONTEXT.md) that acquires and conforms the game's textures
(and, in later slices, sprites/audio/fonts), WITHOUT importing any game code —
game-agnostic core plus a per-game plug-in, exactly like ``tools/balancing/``
(gADR-0014). The core is the deep module the wave-3 asset round-outs
(#442/#443/#444/#445) reuse; there is deliberately NO shared ``tools/_core`` (the
two pipelines share the two-layer *pattern*, not code).

Two layers:

- **Game-agnostic core** — the reusable pipeline structure:
  - ``model`` — the plain value types (StyleDescriptor, AssetSpec, AcquireResult,
    ManifestEntry) the stages pass between them.
  - ``preprocess`` — compose the Style descriptor + the Scale spec's target
    dimensions into a per-asset ``asset spec`` and render it as a search query
    (search-download) or a generation prompt (generation): one spec, both modes.
  - ``acquire`` — the two-mode acquire interface (search-download + generation),
    with the network / API boundary injected so CI mocks it.
  - ``backends`` — generation's two independent backends: ``McpBackend`` (an
    external image-gen MCP channel; Gemini first) and ``BuiltinBackend`` (the
    running agent's own generation, delegated out-of-process).
  - ``postprocess`` — conform the acquired image to the pixel-art regime and the
    exact target size (downscale, palette-quantize, chroma-key crop) with Pillow.
  - ``manifest`` / ``emitter`` — read and (JSON-default) write the Asset manifest,
    the single record-of-source registry keyed by an asset ``id``.
  - ``pipeline`` / ``cli`` — orchestrate one asset end-to-end; the ``python -m
    assets`` on-demand driver.

- **Per-game plug-in** (Panda Adventure's instantiation) — JSON reading only:
  - ``game_config`` — map this game's ``panda_adventure.style.json`` and
    ``scale_spec.json`` into the core's types, and build the generation backends.
  - ``panda_adventure.style.json`` — the Style descriptor (keywords, bounded
    pixel-art palette, per-category hints), the format/licensing constraints, the
    configurable CC0/CC-BY sources, the generation channels, and the per-asset
    acquire recipes.
"""
