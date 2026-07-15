---
status: accepted
---

# Asset-pipeline framework/plug-in split: gADR-0018's shape applied, with deviations

gADR-0018 moved the Balancing pipeline's per-game half out of the framework
package; gADR-0014 carried an outcome note naming the same migration for the
asset pipeline as an open follow-up. Until now `tools/assets/` kept the
pre-split layout: the per-game plug-in in-package (`game_config.py` +
`panda_adventure.style.json`), framework modules importing `game_config` for
defaults (the CLI's default style path, `pipeline`/`hud_font_build` defaulting
`game_root` to the package-derived `GAME_ROOT`), a user-agent string naming the
game, and a package docstring documenting the per-game half as part of the
package. This record applies the gADR-0018 split to assets (#495).

We decide four things:

- **The framework package contains no game.** `tools/assets/` keeps only the
  generic pipeline (model, preprocess, the two-mode acquire, the generation
  backends, postprocess, packer/spriteframes/fonts derivers, lifecycle gates,
  manifest/emitter, pipeline, CLI) plus a new `config.py` — the style-config
  schema home, the mirror of `balancing/config.py`. It never imports game code,
  names no game identity vocabulary, and carries no per-game config file,
  pinned by the fast gate `tests/test_assets_isolation.py` (imports +
  vocabulary + stray-config). **Deviation from the balancing gate:** *Godot is
  not a forbidden word here.* Balancing is engine-agnostic math; the asset
  pipeline's derivers TARGET Godot resource formats (`SpriteFrames` `.tres`,
  the AngelCode `.fnt` Godot loads as a `FontFile`) — the engine is the
  framework's output format, not a game identity leak. Importing an engine
  binding (or `gda`, or the game builder) stays forbidden.

- **Everything Panda Adventure contributes lives in the sibling plug-in
  `tools/panda_assets/`**: `style.json` (ex-`panda_adventure.style.json` — the
  Style descriptor, constraints, sources, generation channels, and per-asset
  recipes) and `font_build.py` (ex-`hud_font_build.py` — the HUD font's
  one-shot build, whose every hardcode — the `hud_font` id, the Press Start 2P
  source, the `hud_font_size` scale key — is this game's contribution). The
  plug-in exposes `STYLE_PATH`, the one home of "where is this game's style
  config" for in-process consumers (`build_config`, the tests).

- **The wiring is config-only, through the same deep-module surface.** The CLI
  takes a required `--config` style file; that file names the game's
  `game_root` (resolved relative to the style file, gADR-0018's idiom — the
  config is relocatable with its game), and `assets_root`/`scale_spec` resolve
  against that root. Every framework default that used to come from the
  package's location now comes from the loaded config; `--game-root` (and the
  `game_root=` parameter) stays as an explicit override for isolated roots. A
  bad input — a malformed style file, an asset/source/channel/backend the
  config does not declare, an unreadable size spec — is a structured
  `ConfigError` (typed accessor + single path-resolve funnel, the gADR-0018
  hardening pattern), surfaced by the CLI as a JSON envelope on stderr with
  exit 2. The acquire user-agent is generic. **Deviations:** *(a) no Python
  adapter* — balancing needed `adapter.py` to map a game's config shape into
  its model; here the style config doubles as the adapter's data, so the
  per-game contribution is pure data parsed by the framework's own schema home.
  The per-game CODE that does exist (`font_build.py`) is a build script the
  game runs directly (`python -m panda_assets.font_build`), not a hook the
  framework loads from a config key. *(b) no `no_write_roots` analogue* —
  balancing is a pure read whose one write (`--out`) must be guarded away from
  the config authority; the asset pipeline's PURPOSE is to write into the game
  tree (`assets/**` + the manifest) at the configured root, so a declared
  protected-roots list has nothing to protect.

- **The license-gate semantics are unchanged.** `validate_asset_licenses`
  still resolves the download allowlist per category (global CC0/CC-BY ∪ the
  category's extension, OFL for fonts only), still requires a generation entry
  to record a non-download backend token, and the per-asset `model` +
  `_DEFAULT_IMAGE_MODEL` provenance contract is untouched — only the modules'
  doc references moved out of the framework's prose.

Consequences: reusing the pipeline for another game = one style config (plus
whatever one-shot build scripts that game wants beside it), no framework edits.
The style schema gained a required `game_root`; the CLI invocation changed
(`python -m assets --config tools/panda_assets/style.json …` — the old
zero-argument default is gone) and the font rebuild command is now
`PYTHONPATH=tools python -m panda_assets.font_build`. gADR-0014's outcome note
is updated to done; its in-package layout prose describes the pre-split state.
