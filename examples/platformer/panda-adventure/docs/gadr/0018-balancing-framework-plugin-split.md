---
status: accepted
---

# Balancing framework/plug-in split: the per-game half moves out of the package

gADR-0011 positioned the Balancing pipeline as a first-class reusable asset —
"input-driven core, per-game configuration" — but the realized layout kept the
per-game half *inside* the framework package: `tools/balancing/` carried
`game_config.py` (this game's JSON mapping), `panda_adventure.targets.json`
(this game's design intent), a CLI whose defaults hardcoded this game's targets
file and `data/` tree, and — deeper — the SD model's state vector named this
game's items (`BUN`/`WINE` stocks, `bun_hp_restore`, `boss_is_peak`). A 2026-07
architecture review judged that coupling incompatible with the module's stated
positioning: the package was game-agnostic in name, per-game in content.

We decide four things:

- **The framework package contains no game.** `tools/balancing/` keeps only the
  generic pipeline (model, rules, both engines, statistics, reports, targets
  schema, CLI). It never imports game code, names no game vocabulary (items,
  actors, docs, engine), and carries no per-game config file. That isolation is
  pinned by a fast test gate (`tests/test_balancing_isolation.py`) — imports,
  vocabulary, and stray config are all regressions, not style. *Mechanic*
  vocabulary is a different category: waves, archetypes, the warp/blink kit,
  and slow fields are the reference combat model's own feature names —
  data-driven and presence-gated, usable or ignorable by any game — i.e. the
  framework's genre scope, not a game identity leak. This game's GAME-CONTEXT
  binding Warp to its Boss does not make the mechanic panda-specific, so the
  vocabulary gate deliberately checks identity terms, not mechanic terms.
- **Everything Panda Adventure contributes lives in the sibling plug-in
  `tools/panda_balancing/`**: `adapter.py` (the JSON-authority → generic-model
  mapping, ex-`game_config.py`) and `targets.json` (ex-
  `panda_adventure.targets.json`). The parity fixtures/tests that pin the rules
  against the shipped GDScript seams stay in `tests/` (gADR-0011 unchanged).
- **The wiring is config-only, through a deep-module surface.** The CLI takes a
  required `--targets` file; that file names the game's `config_dir`, the
  `adapter` (a Python file exporting `load_inputs(config_dir) -> GameInputs`,
  resolved relative to the targets file), and the protected `no_write_roots`
  (this game: the whole `data/` chain — the guard policy moves from code to
  config). The old code's heuristic that auto-protected a `--config-dir`
  override's parent when it was *named* `data` is deliberately dropped:
  protection is declared config, never a path-name heuristic — the override
  dir itself stays protected, and a copied project gets full-tree protection
  by carrying its own targets file. The adapter consumes only the framework's
  public `model` types; a game plugs in without touching package internals,
  and a bad input is a structured exit-2 refusal, not a traceback.
- **The SD economy goes generic.** Stocks are `Q`/`HP`/`EXP`/`CURRENCY` plus
  one stock per tracked drop item; the adapter binds `currency_item` ("gold"),
  `heal_item` ("bun") and its restore amount. Wine is just a tracked
  inflow-only stock; `boss_is_peak` becomes `final_wave_is_peak` (what the
  check actually tests). Report JSON follows (`final_currency`, `final_items`,
  `items_end`).

Consequences: reusing the pipeline for another game = one targets file + one
adapter file, no framework edits. The targets schema changed
(`adapter`/`no_write_roots` added; paths now resolve relative to the targets
file; `heal_consume_rate`, `final_wave_is_peak` renamed) — its single schema
home is `balancing/config.py`. The asset pipeline still keeps its per-game
plug-in in-package (gADR-0014's "exactly like `tools/balancing/`" now describes
the *old* layout); migrating it to this split is a follow-up decision, not made
here.
