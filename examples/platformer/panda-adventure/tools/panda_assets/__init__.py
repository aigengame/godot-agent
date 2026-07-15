"""Panda Adventure's asset plug-in — the per-game half of the pipeline.

The Asset pipeline framework (``tools/assets/``) is game-agnostic (gADR-0014);
everything Panda Adventure contributes lives HERE, outside the framework
package (gADR-0019, applying gADR-0018's framework/plug-in split):

- ``style.json`` — the per-game configuration: the Style descriptor (keywords,
  bounded pixel-art palette, per-category hints), the format/licensing
  constraints (CC0/CC-BY globally, OFL for fonts), the configurable sources,
  the generation channels, the ``game_root`` every path resolves against, and
  the per-asset acquire recipes.
- ``font_build.py`` — the HUD bitmap-font build (P2-S9, #445): this game's
  one-shot acquisition script, wiring Press Start 2P through the framework's
  deep modules. The plug-in-CODE analogue of ``panda_balancing/adapter.py`` —
  per-game Python living beside the per-game data.

Run the pipeline from the game root with ``PYTHONPATH=tools``::

    PYTHONPATH=tools python -m assets --config tools/panda_assets/style.json list
    PYTHONPATH=tools python -m panda_assets.font_build

Unlike the Balancing plug-in there is no Python adapter module: the style
config IS the per-game contribution (pure data), parsed by the framework's own
schema home ``assets/config.py`` — the deviation gADR-0019 records.
"""

from __future__ import annotations

from pathlib import Path

# The committed per-game style config — the ONE path consumers (the tests, the
# JSON -> Resource builder) resolve this game's asset configuration from.
STYLE_PATH = Path(__file__).resolve().parent / "style.json"
