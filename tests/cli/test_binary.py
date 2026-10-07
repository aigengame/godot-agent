"""Godot binary resolution: explicit flag > env override, with no built-in path."""

from pathlib import Path

import pytest

from gda.core.engine.binary import GODOT_BIN_ENV, resolve_godot_binary


def test_explicit_argument_wins_over_env():
    env = {GODOT_BIN_ENV: "/from/env/Godot"}

    resolved = resolve_godot_binary("/explicit/Godot", env=env)

    assert resolved == Path("/explicit/Godot")


def test_env_override_used_when_no_explicit_argument():
    env = {GODOT_BIN_ENV: "/from/env/Godot"}

    resolved = resolve_godot_binary(None, env=env)

    assert resolved == Path("/from/env/Godot")


@pytest.mark.parametrize("env", [{}, {GODOT_BIN_ENV: ""}], ids=["unset", "empty"])
def test_nothing_configured_raises_and_names_both_settings(env):
    # gda has no built-in engine path (#1130): with nothing named, resolution
    # fails and the reason says how to name one.
    with pytest.raises(ValueError) as excinfo:
        resolve_godot_binary(None, env=env)

    assert "--godot" in str(excinfo.value)
    assert GODOT_BIN_ENV in str(excinfo.value)


def test_explicit_empty_string_is_not_silently_swallowed():
    # An explicitly provided (even if empty) path must not silently fall back
    # to the env — that would hide a user mistake.
    with pytest.raises(ValueError):
        resolve_godot_binary("", env={GODOT_BIN_ENV: "/from/env/Godot"})
