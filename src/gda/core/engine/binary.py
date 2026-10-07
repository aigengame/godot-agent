"""Godot binary resolution.

Resolution precedence (highest first):

1. An explicit path passed by the caller (the ``--godot`` flag).
2. The ``GDA_GODOT`` environment variable.

There is no built-in fallback: a Godot install has no path that holds on every
machine, so when neither names a binary, resolution fails and says how to name one
(#1130).
"""

import os
from collections.abc import Mapping
from pathlib import Path

from gda.core.project.paths import expand_user

GODOT_BIN_ENV = "GDA_GODOT"

NOT_CONFIGURED = f"none is configured; pass --godot PATH or set {GODOT_BIN_ENV}"


def resolve_godot_binary(
    explicit: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the Godot binary path using flag > env precedence.

    Raises ``ValueError`` when no binary is named: an explicit EMPTY value, or no
    flag and an unset or empty ``$GDA_GODOT``.

    ``~`` is expanded through :func:`gda.core.project.paths.expand_user`, which owns the rule
    for a ``~user`` this host cannot resolve. Here the outcome is the ordinary path
    the value names, exactly as a shell would read it: where nothing carries that
    name the caller gets the ordinary ``binary_not_found`` envelope instead of a
    ``RuntimeError`` traceback (#988), and where something does, it is launched
    like any other binary.
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
        # An unset and an empty variable are the same intent: nothing is named.
        raw = env.get(GODOT_BIN_ENV)
        if not raw:
            raise ValueError(NOT_CONFIGURED)
    return expand_user(Path(raw))
