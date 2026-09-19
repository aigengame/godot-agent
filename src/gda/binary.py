"""Godot binary resolution.

Resolution precedence (highest first):

1. An explicit path passed by the caller (the ``--godot`` flag).
2. The ``GDA_GODOT`` environment variable.
3. The local development default (the path documented in RULES.md).
"""

import os
from collections.abc import Mapping
from pathlib import Path

from gda.project import expand_user

GODOT_BIN_ENV = "GDA_GODOT"

# Local development default, per RULES.md.
DEFAULT_GODOT_BIN = "~/Applications/Godot.app/Contents/MacOS/Godot"


def resolve_godot_binary(
    explicit: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the Godot binary path using flag > env > default precedence.

    ``~`` is expanded through :func:`gda.project.expand_user`, which is total: a
    ``~unknownuser/…`` prefix this host cannot resolve stays literal, so the value
    is resolved as the ordinary path it names — exactly as a shell would. Where
    nothing carries that name the caller gets the ordinary ``binary_not_found``
    envelope instead of a ``RuntimeError`` traceback (#988); where something does,
    it is launched like any other binary.
    """
    if env is None:
        env = os.environ
    if explicit is not None:
        # An explicit (even if empty) value is a deliberate choice; an empty
        # one is a mistake we surface rather than silently override.
        if not explicit:
            raise ValueError("explicit Godot binary path is empty")
        raw = explicit
    else:
        raw = env.get(GODOT_BIN_ENV) or DEFAULT_GODOT_BIN
    return expand_user(Path(raw))
