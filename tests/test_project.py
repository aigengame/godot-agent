"""Godot project resolution: explicit flag > env override > cwd (issue #32).

The resolved directory becomes the engine's ``--path`` so ``res://`` resolves
deterministically there. An explicitly named directory must actually be a Godot
project (hold a ``project.godot``); the cwd fallback only counts as a project
when it holds one, otherwise gda runs projectless (filesystem paths only) — the
behaviour before project context existed.
"""

from pathlib import Path

import pytest

from gda.project import GDA_PROJECT_ENV, PROJECT_MARKER, resolve_project_dir


def _make_project(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / PROJECT_MARKER).write_text("config_version=5\n", encoding="utf-8")
    return path


def test_explicit_project_wins_over_env_and_cwd(tmp_path):
    proj = _make_project(tmp_path / "explicit")
    env = {GDA_PROJECT_ENV: str(_make_project(tmp_path / "env"))}

    resolved = resolve_project_dir(str(proj), env=env, cwd=tmp_path)

    assert resolved == proj


def test_env_override_used_when_no_explicit(tmp_path):
    env_proj = _make_project(tmp_path / "env")
    env = {GDA_PROJECT_ENV: str(env_proj)}

    resolved = resolve_project_dir(None, env=env, cwd=tmp_path)

    assert resolved == env_proj


def test_cwd_used_when_it_is_a_project(tmp_path):
    proj = _make_project(tmp_path)

    resolved = resolve_project_dir(None, env={}, cwd=proj)

    assert resolved == proj


def test_projectless_when_cwd_has_no_project_marker(tmp_path):
    # No flag, no env, and the cwd is not a project: gda runs projectless
    # (filesystem paths only), preserving pre-project-context behaviour.
    resolved = resolve_project_dir(None, env={}, cwd=tmp_path)

    assert resolved is None


def test_explicit_non_project_dir_is_rejected(tmp_path):
    # A named directory that is not a Godot project is a mistake we surface,
    # not silently treat as projectless.
    with pytest.raises(ValueError):
        resolve_project_dir(str(tmp_path), env={}, cwd=tmp_path)


def test_explicit_empty_string_is_not_silently_swallowed(tmp_path):
    with pytest.raises(ValueError):
        resolve_project_dir("", env={GDA_PROJECT_ENV: str(_make_project(tmp_path))})
