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

> **Outcome (2026-07-08, #478).** The pre-wave-3 tooling slice landed the two pieces
> wave-3 needs first, both inside the asset-pipeline package so the round-outs reuse
> them without reinventing:
>
> - the **frames→sheet packer** (`tools/assets/packer.py` — loose frames → one sheet +
>   a manifest-recorded `FrameLayout`; horizontal strip by default, a near-square grid
>   past 8 frames) and a pure-Python **SpriteFrames deriver**
>   (`tools/assets/spriteframes.py` — the layout → a byte-stable, uid-free
>   `SpriteFrames.tres` of per-frame `AtlasTexture` regions, engine-proved to load in
>   Godot). The runtime sprite-render seam stays wave-3's (#442/#443, gADR-0014).
> - the **size-based Git-LFS gate** (`tools/assets/lifecycle.py` — the pure size/track
>   core plus a `git check-attr` predicate), with `T` as spec-data in
>   `panda_adventure.style.json`, `.gitattributes` seeded with the BGM `assets/music/**`
>   convention (gate-driven: `git lfs track` a path when the gate flags it), and Git LFS
>   materialized by CI (`lfs: true`) and the export path.
>
> The attribution generator, the export-import gate, and the orphan-prune step remain
> follow-up slices under this record.
>
> **Correction (2026-07-08).** Reproduction refuted the premise §5(c)'s export-import
> gate rested on. `gda export run` does NOT ship texture-less: a clean checkout (no
> `.godot/`) exported via `gda export run` **natively triggers a Godot import** — the
> engine's export command imports resources itself — regenerating the imported
> `.ctex` and packing the texture (verified for pack + release on Godot 4.6.3). The
> "export doesn't import" premise was a static-reading inference; the gda issue filed
> on it was withdrawn (cannot-reproduce). So the export-import follow-up (#479)
> narrows from a fix to a **defensive verification** that the shipped build carries
> its textures (an import-regression smoke), not a re-implementation of import.
> Orthogonal and still required: the size-based Git-LFS **byte** materialization on
> the export path (§5's commit rule) is a git-layer concern, unrelated to Godot
> import, and stands.
>
> **Refinement (2026-07-09, gADR-0016).** §2's "the frame layout (`frame_dims`,
> rows/cols, count) is recorded in the manifest" is refined for a MULTI-STATE
> character set by gADR-0016's Model S. There, the derived `SpriteFrames.tres` (not
> the loose sheets) is the asset the JSON authority references, so the set is ONE
> manifest entry whose `path` is that `.tres`; the per-state sheets are its committed
> backing and the per-frame **layout lives in the `.tres` regions, not the manifest**
> (the entry carries no `frame_layout`). §2's per-sheet `frame_layout` recording still
> holds for a single-state sheet entry (`pack_sprite_set`); a multi-state set folds
> the layout into the committed `.tres` instead. The one committed-sheet-per-animation
> -state storage rule (§2) is unchanged.
