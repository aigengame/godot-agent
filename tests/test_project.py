"""Godot project resolution: explicit flag > env override > cwd (issue #32).

The resolved directory becomes the engine's ``--path`` so ``res://`` resolves
deterministically there. An explicitly named directory must actually be a Godot
project (hold a ``project.godot``); the cwd fallback only counts as a project
when it holds one, otherwise gda runs projectless (filesystem paths only) — the
behaviour before project context existed.
"""

from pathlib import Path

import pytest

from gda.project import (
    GDA_PROJECT_ENV,
    PROJECT_MARKER,
    is_engine_virtual_path,
    path_outside_project,
    project_anchored,
    resolve_project_dir,
)


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


# --- containment: does this target belong to the resolved project? (#658) -----


def test_path_inside_the_project_is_not_outside(tmp_path):
    proj = _make_project(tmp_path / "game")
    script = proj / "actors" / "hero.gd"

    assert path_outside_project(str(script), proj) is None


def test_path_in_a_sibling_tree_is_outside_and_reports_its_location(tmp_path):
    # The refusal's evidence: the caller must be able to name WHERE the target
    # actually is, so the check returns the resolved location rather than a bool.
    proj = _make_project(tmp_path / "game")
    script = tmp_path / "other" / "hero.gd"

    assert path_outside_project(str(script), proj) == script.resolve()


def test_engine_virtual_paths_are_never_outside(tmp_path):
    # res:// (and its user:// / uid:// siblings) address the project the engine
    # was launched with, so they are inside by construction — gda makes no
    # filesystem statement about them (ADR-0006).
    proj = _make_project(tmp_path / "game")

    assert path_outside_project("res://hero.gd", proj) is None
    assert path_outside_project("user://save.gd", proj) is None
    assert path_outside_project("uid://abc123", proj) is None


def test_a_colon_bearing_filesystem_path_is_not_treated_as_virtual(tmp_path):
    # A colon is a legal POSIX filename character, so "contains ://" is not a
    # scheme test: `/work/outside://deck.gd` is an ordinary filesystem path that
    # happens to hold the sequence, and it is OUTSIDE. Waving it through as
    # engine-virtual skipped containment entirely and the engine opened the
    # outside file.
    proj = _make_project(tmp_path / "game")
    odd = tmp_path / "outside:" / "deck.gd"

    assert is_engine_virtual_path(str(odd)) is False
    assert path_outside_project(str(odd), proj) == odd.resolve()
    # ...and the same sequence inside the project is still contained.
    assert path_outside_project(str(proj / "weird:" / "deck.gd"), proj) is None


def test_a_symlinked_project_spelling_still_contains_its_own_files(tmp_path):
    # The RESOLVED reading: the SAME directory reached by two spellings compares
    # equal. Without it the check would refuse every correct call made through a
    # symlinked project path — on macOS the temp dir alone (/tmp -> /private/tmp)
    # is such a spelling.
    proj = _make_project(tmp_path / "game")
    link = tmp_path / "game-link"
    link.symlink_to(proj, target_is_directory=True)

    assert path_outside_project(str(link / "hero.gd"), proj) is None
    assert path_outside_project(str(proj / "hero.gd"), link) is None


def test_a_directory_symlinked_into_the_project_is_inside(tmp_path):
    # The LEXICAL reading, and the regression that motivates it: the monorepo
    # shared-addon layout, where the project links a library that physically
    # lives outside it (game/addons/lib -> ../../libs/lib). The caller addressed
    # the file through the project's own tree and Godot follows the same link, so
    # the file IS in the project's res:// namespace. Judging it by its resolved
    # location alone would refuse a call that works, in a message naming a path
    # the caller never typed.
    proj = _make_project(tmp_path / "game")
    (proj / "addons").mkdir()
    library = tmp_path / "libs" / "cardlib"
    library.mkdir(parents=True)
    (library / "card.gd").write_text("extends Node\n", encoding="utf-8")
    (proj / "addons" / "cardlib").symlink_to(library, target_is_directory=True)

    assert path_outside_project(str(proj / "addons" / "cardlib" / "card.gd"), proj) is (
        None
    )


def test_a_file_symlinked_into_the_project_is_inside(tmp_path):
    # The same rule for a single linked FILE, not just a linked directory.
    proj = _make_project(tmp_path / "game")
    shared = tmp_path / "shared" / "card.gd"
    shared.parent.mkdir(parents=True)
    shared.write_text("extends Node\n", encoding="utf-8")
    (proj / "card.gd").symlink_to(shared)

    assert path_outside_project(str(proj / "card.gd"), proj) is None


def test_a_dot_dot_escape_is_still_outside(tmp_path):
    # The lexical reading must not become an escape hatch: `..` is collapsed
    # textually, so a path that climbs out of the project is outside under BOTH
    # readings and stays refused.
    proj = _make_project(tmp_path / "game")
    escaped = str(proj / ".." / "elsewhere" / "hero.gd")

    assert (
        path_outside_project(escaped, proj)
        == (tmp_path / "elsewhere" / "hero.gd").resolve()
    )


def test_a_symlink_followed_by_dot_dot_does_not_pass_as_inside(tmp_path):
    # The lexical reading is only sound while no `..` is in play. With
    # `game/pivot -> ../outside/deep`, the input `game/pivot/../deck.gd` collapses
    # TEXTUALLY to `game/deck.gd` (inside) while really naming
    # `outside/deck.gd` — so trusting the lexical reading here accepted a target
    # that is genuinely outside, and the engine compiled it.
    proj = _make_project(tmp_path / "game")
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deck.gd").write_text("extends Node\n", encoding="utf-8")
    (proj / "pivot").symlink_to(outside / "deep", target_is_directory=True)

    bypass = str(proj / "pivot" / ".." / "deck.gd")

    assert path_outside_project(bypass, proj) == (outside / "deck.gd").resolve()


def test_a_relative_path_is_anchored_at_the_project_not_the_cwd(tmp_path, monkeypatch):
    # A relative target is anchored where the ENGINE anchors it: at the resolved
    # project. Launched with `--path <project>`, a one-shot op that opens
    # `deck.gd` opens `<project>/deck.gd` no matter where gda was invoked, and the
    # README promises the same. Anchoring at the invoker cwd instead refused an
    # ordinary `gda script validate deck.gd --project game` run from an ancestor
    # directory, which the engine validates fine.
    proj = _make_project(tmp_path / "game")
    monkeypatch.chdir(tmp_path)

    assert path_outside_project("deck.gd", proj) is None
    assert path_outside_project("scripts/deck.gd", proj) is None
    # A relative project spelling anchors identically.
    assert path_outside_project("deck.gd", Path("game")) is None
    # `..` still climbs out of the project, and is refused from either spelling.
    assert (
        path_outside_project("../elsewhere/hero.gd", proj)
        == (tmp_path / "elsewhere" / "hero.gd").resolve()
    )


def test_a_nonexistent_path_is_still_classified(tmp_path):
    # The check runs BEFORE the engine opens anything, so it must not depend on
    # the target existing (a missing file inside the project is the operation's
    # own path_not_found, reported by the engine as before).
    proj = _make_project(tmp_path / "game")

    assert path_outside_project(str(proj / "gone.gd"), proj) is None
    assert path_outside_project(str(tmp_path / "gone.gd"), proj) is not None


def test_a_project_nested_inside_the_resolved_one_is_not_refused(tmp_path):
    # The deliberate scope line (#658): a script in a project NESTED under the
    # resolved one is contained, so it is NOT refused — finding the nearest
    # project.godot is exactly the derivation ADR-0006 rejected, and waits on an
    # amendment. The mismatch stays visible through the result's project_root.
    outer = _make_project(tmp_path / "outer")
    _make_project(outer / "inner")

    assert path_outside_project(str(outer / "inner" / "deck.gd"), outer) is None


def test_project_anchored_matches_how_the_engine_addresses_a_path(tmp_path):
    # The one anchoring rule the containment check and the engine share: relative
    # at the project, absolute untouched. Pinned separately from containment so a
    # future caller (the op argv, a batch mode) reuses the same rule rather than
    # re-deciding it.
    proj = tmp_path / "game"
    absolute = tmp_path / "elsewhere" / "hero.gd"

    assert project_anchored("deck.gd", proj) == proj / "deck.gd"
    assert project_anchored("scripts/deck.gd", proj) == proj / "scripts" / "deck.gd"
    assert project_anchored(str(absolute), proj) == absolute
