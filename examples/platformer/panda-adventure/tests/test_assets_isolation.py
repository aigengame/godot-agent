"""The framework/plug-in isolation gate for the Asset pipeline (gADR-0019).

gADR-0014 positions the pipeline as a reusable, game-agnostic asset;
gADR-0019 splits everything Panda Adventure contributes into the
``tools/panda_assets/`` plug-in (the gADR-0018 shape) and pins the framework
package clean. These tests are that pin: the framework must not import game
code, must not speak this game's vocabulary (no panda terms, no gADR/doc
references, no game items/props), and must carry no per-game config file — a
regression here means a coupling leaked back in. Fast tier, no engine.

One deliberate deviation from the balancing gate (gADR-0019): **Godot is NOT a
forbidden word here.** The balancing framework is engine-agnostic math, but the
asset pipeline's derivers TARGET Godot resource formats (``SpriteFrames``
``.tres``, an AngelCode ``.fnt`` loaded as a ``FontFile``) — the engine is the
framework's output format, not a game identity leak. Importing an engine
binding (or ``gda``) is still forbidden: the framework emits text/PNG, it never
drives an engine.
"""

from __future__ import annotations

import re

import build_config

FRAMEWORK_DIR = build_config.GAME_DIR / "tools" / "assets"

# Imports that would couple the framework to this game, its tooling, or an
# engine process. Pillow/mcp are the framework's own (dev/live) dependencies.
_FORBIDDEN_IMPORTS = (
    "import gda",
    "from gda",
    "import godot",
    "import build_config",
    "from build_config",
    "import panda_assets",
    "from panda_assets",
    "import panda_balancing",
    "from panda_balancing",
)

# Game/domain vocabulary the framework must describe generically instead
# (word-boundary, case-insensitive): this game's name, its docs/decision
# records, its scripting language, and its items/actors/props. "sprite",
# "font", "palette", "godot" etc. are the framework's own vocabulary and stay
# allowed (see the module docstring for the Godot deviation).
_FORBIDDEN_WORDS = re.compile(
    r"\b(panda|gadr|game-context|gdscript|spacesuit|laser|bun|wine|boss"
    r"|gravity|hud|obstacle|crate|pickup)\b",
    re.IGNORECASE,
)


def _framework_sources() -> list:
    files = sorted(FRAMEWORK_DIR.glob("*.py"))
    assert files, f"no framework sources found under {FRAMEWORK_DIR}"
    return files


def test_framework_imports_no_game_code() -> None:
    """The framework is pure-Python and game-agnostic: no Godot binding, no gda,
    no game builder, no per-game plug-in — only stdlib, its own dependencies
    (Pillow, the lazy-imported mcp client), and sibling modules."""
    for path in _framework_sources():
        source = path.read_text(encoding="utf-8")
        for needle in _FORBIDDEN_IMPORTS:
            assert needle not in source, f"{path.name} imports game code: {needle!r}"


def test_framework_speaks_no_game_vocabulary() -> None:
    """The framework's code and docs stay in its own pipeline vocabulary — every
    per-game term lives in the plug-in (style config + font build), not the
    package."""
    for path in _framework_sources():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hit = _FORBIDDEN_WORDS.search(line)
            assert hit is None, (
                f"{path.name}:{i} uses game vocabulary {hit.group(0)!r}: {line.strip()}"
            )


def test_framework_carries_no_per_game_config() -> None:
    """No per-game configuration file lives inside the framework package — the
    style config is the plug-in's (``tools/panda_assets/style.json``)."""
    strays = [p.name for p in FRAMEWORK_DIR.iterdir() if p.suffix == ".json"]
    assert strays == [], f"per-game config inside the framework package: {strays}"
