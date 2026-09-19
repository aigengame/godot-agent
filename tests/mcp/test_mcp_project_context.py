"""L1 fast tests for gda-mcp project-context resolution (issue #194, ADR-0014).

The pure resolver ``resolve_project_dir(env, roots, cwd)`` implements the
agent-neutral precedence ``GDA_PROJECT -> roots/list -> cwd`` with
``project.godot`` validation. No subprocess, no engine, no MCP session — the
precedence and validation are a pure function, asserted in isolation (the
ADR-0014 / #194 acceptance criterion).
"""

from pathlib import Path

from gda.mcp.project_context import resolve_project_dir
from tests.support import minimal_project


def test_gda_project_env_resolves_to_that_project(tmp_path):
    proj = minimal_project(tmp_path)
    result = resolve_project_dir(
        env={"GDA_PROJECT": str(proj)}, roots=[], cwd=Path("/nonexistent")
    )
    assert result == proj


def test_root_resolves_when_gda_project_unset(tmp_path):
    proj = minimal_project(tmp_path)
    result = resolve_project_dir(env={}, roots=[str(proj)], cwd=Path("/nonexistent"))
    assert result == proj


def test_cwd_used_when_it_is_a_project_and_nothing_else_resolves(tmp_path):
    proj = minimal_project(tmp_path)
    result = resolve_project_dir(env={}, roots=[], cwd=proj)
    assert result == proj


def test_first_valid_root_wins_invalid_roots_skipped(tmp_path):
    not_a_project = tmp_path / "plain"
    not_a_project.mkdir()
    proj = minimal_project(tmp_path / "game")
    later = minimal_project(tmp_path / "other")
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
    pinned = minimal_project(tmp_path / "pinned")
    root = minimal_project(tmp_path / "root")
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
    valid_root = minimal_project(tmp_path / "game")
    result = resolve_project_dir(
        env={"GDA_PROJECT": str(bad)},
        roots=[str(valid_root)],
        cwd=Path("/nonexistent"),
    )
    assert result is None


def test_an_unresolvable_home_in_gda_project_resolves_to_none(tmp_path):
    # `Path.expanduser()` raises `RuntimeError` for a `~unknownuser/…` prefix this
    # host cannot resolve, which killed the resolution instead of answering it
    # (#988). The value names no home, so it is kept literal; nothing on disk
    # carries that name here, so the strict explicit path above yields None and
    # gda inherits the pin and surfaces its own typed error.
    #
    # Guarded inside this module rather than routed through
    # `gda.project.expand_user`: ADR-0011 keeps gda-mcp free of any `gda` internal
    # symbol, which is why `GDA_PROJECT_ENV` and `PROJECT_MARKER` are local too.
    valid_root = minimal_project(tmp_path / "game")

    result = resolve_project_dir(
        env={"GDA_PROJECT": "~nosuchuser999/p"},
        roots=[str(valid_root)],
        cwd=tmp_path,
    )

    assert result is None


def test_an_unresolvable_home_in_gda_project_still_resolves_a_literal_project(
    tmp_path, monkeypatch
):
    # The other half: the literal name is a real address, so a directory that
    # actually carries it and holds a `project.godot` resolves like any other. This
    # is what tells the guard from a blanket refusal of every `~` value.
    literal = minimal_project(tmp_path / "~nosuchuser999" / "p")
    monkeypatch.chdir(tmp_path)

    result = resolve_project_dir(
        env={"GDA_PROJECT": "~nosuchuser999/p"}, roots=[], cwd=tmp_path
    )

    assert result == Path("~nosuchuser999/p")
    assert (literal / "project.godot").is_file()
