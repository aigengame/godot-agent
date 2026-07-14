---
status: accepted
---

# Asset pipeline architecture: a standalone Tool Script, an id-referenced manifest, and a two-mode acquire interface

P2-S1 (#439) builds the asset-pipeline walking skeleton — the tracer that forks
the whole asset track (#442/#443/#444/#445 all depend on it). GAME-CONTEXT already
names the vocabulary (Tool Script, Asset pipeline, asset spec, Asset manifest, Style
descriptor, acquire modes); this record settles the *architecture* those terms
stand on, decided in the 2026-07-07 P2-S1 grilling interview (HITL). It is the asset
analogue of gADR-0011 (the Balancing pipeline) and reuses gADR-0013's authority
patterns.

> **Outcome note (2026-07-14).** The Balancing-pipeline layout this record cites
> as its mirror ("`tools/balancing/`'s core + `game_config` +
> `panda_adventure.targets.json`") has since changed: gADR-0018 moved balancing's
> per-game half out to the sibling plug-in `tools/panda_balancing/` (adapter +
> targets). The two-layer *pattern* decided here is unchanged; the asset
> pipeline still keeps its plug-in in-package, and migrating it to the
> gADR-0018 split is an open follow-up.

We decide six things:

- **A standalone `tools/assets/` package, mirroring the Balancing pipeline's
  two-layer shape — NOT a shared `tools/_core`.** Game-agnostic core (asset-spec
  build, the acquire interface, postprocess, the emitter, the manifest writer) plus
  a per-game plug-in config, exactly like `tools/balancing/`'s core + `game_config`
  + `panda_adventure.targets.json`. The "Tool Script framework" is a shared
  *pattern* (the two layers), not shared code: balancing's core is domain-specific
  (encounter simulation, TTK/TTD statistics) and shares no genuine primitive with
  preprocess→acquire→postprocess today. A premature `tools/_core` was rejected as
  speculative generality — extract by rule-of-three if a real common primitive
  emerges. The deep module to get right is *inside* `tools/assets/` (the core
  #442/#443/#444/#445 reuse), not between assets and balancing.

- **The asset manifest single-homes each asset's path; the JSON authority
  references by a manifest `id` (a foreign key), never a raw path; the builder
  composes id → path at build time.** The manifest (`assets/manifest/<category>.json`,
  per-category fragments) is the one home of `id → {path, category, acquire_mode,
  source, license, license_url, target_dims}`. `build_config.py` gains
  `compose_asset_refs`, resolving id → path into the derived `.tres` — the game and
  `view_builder` still read a resolved path and never read the manifest. This is
  gADR-0013's "one authored home, N derived projections" applied to assets. The
  rejected alternative — the path stored in BOTH the authority and the manifest,
  reconciled by a cross-check — is exactly the duplicate-authority drift the
  one-authority convention (gADR-0008) exists to prevent.

- **Manifest↔authority consistency is enforced by the EXISTING config gate, not a
  bespoke checker.** Three mechanical checks join the schema/semantic/freshness gate,
  mirroring `validate_scale_semantics`'s two-way integrity: (1) **FK integrity** —
  every asset id referenced in any authority exists in the manifest (no
  referenced-but-unprovenanced/unlicensed asset ships); (2) **no dangling** — every
  manifest entry's path exists on disk; (3) **freshness** — the committed `.tres`
  are byte-identical to a fresh build from `authority + manifest`, so a manifest
  path change re-derives and drift goes red. Plus a soft **orphan report** (manifest
  entries no authority references — a warning; wave-close DoD requires zero). The
  manifest is a **record source** (its provenance/license/source are not derivable),
  so the pipeline authors it and it is integrity-checked, NOT freshness-gated.

- **The shared style descriptor is a pipeline-only per-game config, orthogonal to
  the Scale spec.** The machine-consumable style parameters (shared style
  keywords/prompt fragment, bounded pixel-art palette, per-category style hints) and
  the format/licensing constraints live in `tools/assets/panda_adventure.style.json`
  — inside the pipeline package (mirroring `panda_adventure.targets.json`), NOT in
  `data/json/` and never derived to a Resource, because the game reads assets, not
  their style. The qualitative art direction lives in the GDD's art-style chapter
  (the gADR-0013 GDD/JSON split applied to *look* rather than *size*). Preprocess
  composes the style descriptor + the Scale spec's target dimensions + format/
  licensing into the per-asset `asset spec`, which renders as a search query
  (search-download) or a generation prompt (generation) — one spec, both modes, so
  style coheres. `style_spec`/style is single-authority for look; `scale_spec` stays
  single-authority for dimensions; they are orthogonal and never cross-check.

- **Acquire is an interface with two modes; generation derives two backends; the
  source is configurable; and the "both modes exercised for real" AC is NOT
  relaxed.** `SearchDownload` fulfils a spec from a **configurable** open-asset
  source (CC0/CC-BY only, recorded in the per-game config — Kenney.nl and
  OpenGameArt for Panda Adventure — never hardcoded). `Generation` derives
  **`McpBackend`** — a pluggable family of external MCP image-generation channels,
  `scripts/mcp/gemini_img_gen.py` (Gemini) being the first, more added later — and
  **`BuiltinBackend`** — the running agent's own built-in image-generation
  capability, invoked out-of-process (delegated: the pipeline renders the prompt,
  the agent generates, the pipeline ingests + postprocesses). An agent without the
  capability follows a configured fallback or raises a clear user-facing error —
  never a silent no-op. The two generation backends are independent (an MCP channel
  is not the BuiltinBackend). Live acquire runs carry an **`acquire_live`** pytest
  marker, deselected in CI (network, API keys, cost) and triggered on demand; CI's
  unit tests mock the acquire boundary. Postprocess (Pillow) is a CI dependency
  (the dev group); the generation-channel dependencies (`mcp`, `google-genai`) live
  in an optional live-only group CI does not install, lazy-imported so CI collection
  never requires them.

- **The tracer (#439) wires ONE texture — the Obstacle — end-to-end via
  SearchDownload, filling an existing field rather than adding one.** P2-S2 (#436)
  already authored the `*_asset` reference fields across the configs
  (`obstacle_asset`, `background_asset`, …), all empty, awaiting the first asset
  slice. So #439 authors `gravity_config.json`'s `obstacle_asset` = the manifest id,
  regenerates + commits the derived `.tres`, and implements `view_builder`'s
  `_apply_visual` asset branch (replacing the P2-S2 `push_error` stub with texture
  rendering at the resolved path); the schema comment's "the view seam resolves" is
  corrected to "the builder resolves." The Obstacle is chosen over the backdrop
  (which renders via a separate clear-color path) or the Player (scale-tween
  complexity): static, and it flows through the existing `apply_box → _apply_visual`
  seam at its `scale_spec` size.

Consequences: wave-3's four asset round-outs (#442/#443/#444/#445) reuse the stable
core and own disjoint per-category manifest fragments, so they fan out 4-way — the
residual watch is #442↔#443 sharing the `view_builder` sprite branch (one owns it,
the other flags). Generation is really exercised (Gemini via McpBackend, with
`GEMINI_API_KEY` present), but BuiltinBackend's real run is agent-conditional:
Claude Code has no native imagegen, so its `acquire_live` test asserts the
fallback/error path there and the real-generation assertion runs only on a capable
agent. The generation path carries an optional-dependency and on-demand-test cost
the fast CI never pays. Adding an image-gen provider later is a new McpBackend
channel, not a new acquire mode. Rule drift between an asset reference and its
provenance now goes red at the config gate rather than shipping an unlicensed asset.

The tracer's SearchDownload resolves a **preconfigured, license-verified source URL**
from the per-game acquire recipe rather than driving a live search over the rendered
search query — the query is authored (preprocess composes it, and it is what a live
search would submit), but wiring a live open-asset search API is a deliberate
follow-up, so the tracer stays reproducible. The config gate (`validate_asset_refs`)
is wired INTO the build path (`build_all`/`main`), not just tests: a referenced id
with no manifest entry, a referenced entry missing a required provenance/license
field, or a dangling manifest path fails the build before any `.tres` is written.

> **Amendment (2026-07-10, P2-S9/#445 — user-approved):** the "CC0/CC-BY only"
> sourcing restriction above is the **global** rule and stands unchanged for every
> image category (textures, sprites, vfx, audio). It gains ONE category-scoped
> exception: **fonts may additionally be OFL** (the SIL Open Font License — a
> permissive *font* license, the natural terms for a downloaded pixel/bitmap font
> such as Press Start 2P). This is data, not a code special-case: the Style
> descriptor carries a `constraints.category_licenses` map (`{"fonts": ["OFL"]}`),
> the license/acquire-mode gate (gADR-0015 §5d, `validate_asset_licenses`) resolves
> the download-license allowlist **per category** (global ∪ the category's
> extension), and a non-font OFL entry still fails. OFL is deliberately kept OUT of
> the global `allowed_licenses`.
