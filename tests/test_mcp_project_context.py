"""L1 fast tests for gda-mcp project-context resolution (issue #194, ADR-0014).

The pure resolver ``resolve_project_dir(env, roots, cwd)`` implements the
agent-neutral precedence ``GDA_PROJECT -> roots/list -> cwd`` with
``project.godot`` validation. No subprocess, no engine, no MCP session — the
precedence and validation are a pure function, asserted in isolation (the
ADR-0014 / #194 acceptance criterion).
"""

from pathlib import Path

from gda.mcp.project_context import resolve_project_dir


def _project(dir_path: Path) -> Path:
    """Mark ``dir_path`` a Godot project (a ``project.godot`` is all that counts)."""
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "project.godot").write_text("", encoding="utf-8")
    return dir_path


def test_gda_project_env_resolves_to_that_project(tmp_path):
    proj = _project(tmp_path)
    result = resolve_project_dir(
        env={"GDA_PROJECT": str(proj)}, roots=[], cwd=Path("/nonexistent")
    )
    assert result == proj


def test_root_resolves_when_gda_project_unset(tmp_path):
    proj = _project(tmp_path)
    result = resolve_project_dir(
        env={}, roots=[str(proj)], cwd=Path("/nonexistent")
    )
    assert result == proj


def test_cwd_used_when_it_is_a_project_and_nothing_else_resolves(tmp_path):
    proj = _project(tmp_path)
    result = resolve_project_dir(env={}, roots=[], cwd=proj)
    assert result == proj


def test_first_valid_root_wins_invalid_roots_skipped(tmp_path):
    not_a_project = tmp_path / "plain"
    not_a_project.mkdir()
    proj = _project(tmp_path / "game")
    later = _project(tmp_path / "other")
    result = resolve_project_dir(
        env={},
        roots=[str(not_a_project), str(proj), str(later)],
        cwd=Path("/nonexistent"),
    )
    assert result == proj


def test_nothing_resolves_to_none(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = resolve_project_dir(env={}, roots=[str(plain)], cwd=plain)
    assert result is None


def test_gda_project_takes_precedence_over_root(tmp_path):
    pinned = _project(tmp_path / "pinned")
    root = _project(tmp_path / "root")
    result = resolve_project_dir(
        env={"GDA_PROJECT": str(pinned)}, roots=[str(root)], cwd=Path("/nonexistent")
    )
    assert result == pinned


def test_invalid_gda_project_does_not_fall_through_to_root(tmp_path):
    # ADR-0006 strict explicit semantics: an explicitly set but invalid
    # GDA_PROJECT must NOT be silently shadowed by a roots/cwd candidate. The
    # resolver yields None and injects nothing, so gda inherits the explicit
    # GDA_PROJECT and surfaces its own typed error for project-taking commands.
    bad = tmp_path / "not-a-project"
    bad.mkdir()
    valid_root = _project(tmp_path / "game")
    result = resolve_project_dir(
        env={"GDA_PROJECT": str(bad)},
        roots=[str(valid_root)],
        cwd=Path("/nonexistent"),
    )
    assert result is None
