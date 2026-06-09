"""Godot binary resolution: explicit flag > env override > default path."""

from pathlib import Path

import pytest

from gda.binary import DEFAULT_GODOT_BIN, GODOT_BIN_ENV, resolve_godot_binary


def test_explicit_argument_wins_over_env_and_default():
    env = {GODOT_BIN_ENV: "/from/env/Godot"}

    resolved = resolve_godot_binary("/explicit/Godot", env=env)

    assert resolved == Path("/explicit/Godot")


def test_env_override_used_when_no_explicit_argument():
    env = {GODOT_BIN_ENV: "/from/env/Godot"}

    resolved = resolve_godot_binary(None, env=env)

    assert resolved == Path("/from/env/Godot")


def test_falls_back_to_default_path_when_nothing_set():
    resolved = resolve_godot_binary(None, env={})

    assert resolved == Path(DEFAULT_GODOT_BIN).expanduser()


def test_explicit_empty_string_is_not_silently_swallowed():
    # An explicitly provided (even if empty) path must not silently fall back
    # to the env/default — that would hide a user mistake.
    with pytest.raises(ValueError):
        resolve_godot_binary("", env={GODOT_BIN_ENV: "/from/env/Godot"})
