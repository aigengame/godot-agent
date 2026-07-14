"""Panda Adventure's balancing plug-in — the per-game half of the pipeline.

The Balancing pipeline framework (``tools/balancing/``) is game-agnostic
(gADR-0011); everything Panda Adventure contributes lives HERE, outside the
framework package (gADR-0018):

- ``targets.json`` — the per-game configuration: where the JSON authority
  lives, which adapter maps it, the protected write roots (the whole ``data/``
  chain), the player-model assumptions, the sim controls, and the design
  targets (TTK/TTD per Wave, the SD growth/difficulty intent).
- ``adapter.py`` — the mapping from this game's JSON authority
  (``data/json/*.json``) into the framework's generic ``balancing.model``
  types, wired through the targets file's ``adapter`` key.

Run it from the ``tools/`` directory (which makes ``balancing`` importable)::

    python -m balancing validate --targets panda_balancing/targets.json
    python -m balancing predict  --targets panda_balancing/targets.json

or from the game root with ``PYTHONPATH=tools`` and
``--targets tools/panda_balancing/targets.json``. Rule parity with the shipped
GDScript seams is pinned by the golden fixtures in ``tests/`` (gADR-0011), not
by anything in the framework.
"""
