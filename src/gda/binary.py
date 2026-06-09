"""Godot binary resolution.

Resolution precedence (highest first):

1. An explicit path passed by the caller (the ``--godot`` flag).
2. The ``GDA_GODOT`` environment variable.
3. The local development default (the path documented in RULES.md).
"""

import os
from collections.abc import Mapping
from pathlib import Path

GODOT_BIN_ENV = "GDA_GODOT"

# Local development default, per RULES.md.
DEFAULT_GODOT_BIN = "~/Applications/Godot.app/Contents/MacOS/Godot"


def resolve_godot_binary(
    explicit: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the Godot binary path using flag > env > default precedence."""
    if env is None:
        env = os.environ
    raw = explicit or env.get(GODOT_BIN_ENV) or DEFAULT_GODOT_BIN
    return Path(raw).expanduser()
