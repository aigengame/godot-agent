"""Asset pipeline framework — the game-agnostic core that produces binary assets.

A reusable pipeline that acquires and conforms a game's textures, sprites,
fonts, and audio WITHOUT importing any game code: the framework package
contains no game. Everything a game contributes — its style config, sources,
generation channels, and per-asset acquire recipes — lives in a sibling
plug-in package and is wired in through configuration alone (the CLI's
required ``--config`` style file), so pointing the pipeline at a different
game needs no framework edits. That isolation is pinned by a fast test gate
(no game imports, no game vocabulary, no per-game config file in this
package). Godot is the framework's TARGET, not a game coupling: the derivers
emit Godot resource formats (``SpriteFrames`` ``.tres``, AngelCode ``.fnt``)
by design.

Modules:

- ``config`` — the style-config schema home: parse the per-game style file
  into the framework's types, with typed structured refusals for malformed
  input; the config surface (size-spec reads, asset paths, backend factories).
- ``model`` — the plain value types (StyleDescriptor, AssetSpec, AcquireResult,
  ManifestEntry) the stages pass between them.
- ``preprocess`` — compose the Style descriptor + the size spec's target
  dimensions into a per-asset ``asset spec`` and render it as a search query
  (search-download) or a generation prompt (generation): one spec, both modes.
- ``acquire`` — the two-mode acquire interface (search-download + generation),
  with the network / API boundary injected so CI mocks it.
- ``backends`` — generation's two independent backends: ``McpBackend`` (an
  external image-gen MCP channel) and ``BuiltinBackend`` (the running agent's
  own generation, delegated out-of-process).
- ``postprocess`` — conform the acquired image to the pixel-art regime and the
  exact target size (downscale, palette-quantize, chroma-key crop) with Pillow.
- ``packer`` / ``spriteframes`` — pack loose frames into one spritesheet, and
  derive the byte-stable Godot ``SpriteFrames`` resource from its layout.
- ``fonts`` — derive a byte-stable AngelCode ``.fnt`` from a glyph sheet + grid.
- ``lifecycle`` — asset-lifecycle governance: the size-based Git-LFS gate and
  the license/acquire-mode consistency gate.
- ``manifest`` / ``emitter`` — read and (JSON-default) write the Asset manifest,
  the single record-of-source registry keyed by an asset ``id``.
- ``pipeline`` / ``cli`` — orchestrate one asset end-to-end; the ``python -m
  assets`` on-demand driver.
"""
