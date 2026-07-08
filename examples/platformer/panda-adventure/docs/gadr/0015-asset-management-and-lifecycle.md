---
status: accepted
---

# Asset management & lifecycle: storage, naming, size-based commit, and wave-close hygiene

gADR-0014 built the asset pipeline and the per-category `Asset manifest`. As Phase 2's
wave-3 fills Level 1 with many produced assets (item textures, Player and enemy sprite
sets, terrain tiles, VFX, audio, fonts), the *governance* around those files — where they
live, how they are named, how they are committed, how they are versioned, and how their
lifecycle is kept clean — must be settled before the volume lands, or wave-3 accretes
inconsistency. This record settles it, decided in the 2026-07-08 grilling interview,
building directly on gADR-0014 and gADR-0013 (the pixel-art regime).

We decide five things:

- **Storage and naming: `assets/<category>/<id>.<ext>`, flat within a category, keyed
  by a stable semantic id.** The manifest `id` is a stable semantic slug —
  `<entity>[_<variant>][_<state>]` (`obstacle_crate`, `player_run`,
  `enemy_monster_minion_walk`, `bun`, `wall_span`) — derived from the asset spec (what
  the asset *is*), and **stable across re-acquisition**: it is the authority's foreign
  key (gADR-0014), so it never changes because the source or the art changed. The file is
  `<id>.<ext>`; the category is the directory and its manifest fragment. Renaming an asset
  is therefore a deliberate manifest+authority migration, never a casual file move.

- **Sprite-frame sets are committed as one spritesheet per animation state, not loose
  frames.** A set is ONE sheet (`player_run.png`) whose frame layout (`frame_dims`,
  rows/cols, count) is recorded in the manifest; the builder derives the Godot
  `SpriteFrames` / `AtlasTexture` regions. Rationale: far fewer committed files (wave-3
  has many sets), one `.import` per set, atlas- and pixel-grid-friendly (gADR-0013).
  Because open-asset sources often deliver frames as **loose files (B-form)**, the sprite
  postprocess includes a reusable **frames→sheet packer** tool: loose frames in → one
  packed sheet + layout out (default a horizontal strip, a grid past a frame-count
  threshold). The acquire boundary may yield loose frames; the *committed artifact is
  always the sheet (A-form)*.

- **Commit method is size-based and uniform across categories — never category-based.** A
  large binary can appear in any category (a BGM track, a 2K/4K background texture), so
  the plain-git-vs-Git-LFS boundary is a single **size threshold `T` (default 1 MB;
  spec-data, revisable)** applied uniformly: an `assets/**` file `>= T` is tracked by Git
  LFS; below `T` it stays plain git. A config-gate **size check** enforces it mechanically
  — it fails if any `assets/**` binary `>= T` is committed outside LFS — so the policy is
  a gate, not a note. Git LFS is set up **before wave-3's first large asset**, so a large
  file is born in LFS and is never committed to plain git and migrated later (which
  rewrites history — the failure mode this decision exists to avoid). Rationale: pixel-art
  textures and SFX are KB-scale (plain git); BGM and any large backdrop cross `T` (LFS) —
  one rule, no per-category special-casing.

- **Versioning is in-place under the stable id.** Re-acquiring or regenerating an asset
  updates the file in place under its stable id — git history *is* the version history;
  the manifest records only the CURRENT provenance, never its own history. Generated
  assets are not byte-reproducible (the backend exposes no seed), so the manifest records
  the prompt/backend for audit and approximate re-generation; downloaded assets are
  re-fetchable from the recorded `source_url`. A `style_version` in the `Style descriptor`
  gates a deliberate bulk re-acquire when the shared style changes.

- **Lifecycle hygiene is enforced at wave-close, not left to memory.** (a) **Orphan
  prune** — gADR-0014's `validate_asset_refs` soft orphan report drives a wave-close prune
  of any manifest entry (and its file) no authority references, so no dead asset ships.
  (b) **Attribution aggregation** — an `ATTRIBUTIONS.md` is generated from the manifest's
  `attribution`/`license` fields at wave-close/export (a pipeline invariant, never
  hand-maintained), so CC-BY compliance is auditable. (c) **Export imports assets** —
  because `.godot/` (the import cache) is gitignored and only `.import` is committed,
  `gda export run` MUST trigger a Godot import so the shipped `.app` carries the textures;
  a missing import is a build fault (the read-side counterpart of the test-side import
  fixture #439 added), gate-checked at export. (d) **Generated-content licensing** — a
  generated asset records its backend's usage terms per manifest entry, distinct from a
  CC0 download's license.

Consequences: wave-3's asset round-outs (#442/#443/#444/#445) and their consumers
(#446/#447/#448) all conform to one storage/naming/commit/lifecycle scheme. The
frames→sheet packer, the Git-LFS size gate, the attribution generator, the export-import
gate, and the orphan-prune step are one-time asset-lifecycle infrastructure that must land
**before** the bulk assets — captured as a dedicated pre-wave-3 tooling slice. The
id-stability rule makes an asset rename a deliberate migration; the size-based LFS rule
means the first over-`T` asset is born in LFS with no history rewrite.
