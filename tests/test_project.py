"""Godot project resolution: explicit flag > env override > cwd (issue #32).

The resolved directory becomes the engine's ``--path`` so ``res://`` resolves
deterministically there. An explicitly named directory must actually be a Godot
project (hold a ``project.godot``); the cwd fallback only counts as a project
when it holds one, otherwise gda runs projectless (filesystem paths only) — the
behaviour before project context existed.
"""

import os
from pathlib import Path

import pytest

from gda.project import (
    GDA_PROJECT_ENV,
    PROJECT_MARKER,
    canonical_res_path,
    is_engine_virtual_path,
    owner_relative_target,
    owning_project,
    path_outside_project,
    target_location,
    project_anchored,
    res_escape_remainder,
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


def test_well_formed_engine_virtual_paths_are_not_outside(tmp_path):
    # res:// (and its user:// / uid:// siblings) address the project the engine
    # was launched with, so gda makes no filesystem statement about them
    # (ADR-0006). WELL-FORMED is the qualifier the name carries: a res:// spelling
    # that lexically escapes the namespace is not inside by construction and IS
    # refused — see test_a_res_dotdot_escape_is_outside below (#762).
    proj = _make_project(tmp_path / "game")

    assert path_outside_project("res://hero.gd", proj) is None
    assert path_outside_project("user://save.gd", proj) is None
    assert path_outside_project("uid://abc123", proj) is None


# --- a res:// spelling that LEXICALLY escapes the namespace (#762) ------------


def test_a_res_dotdot_escape_is_outside(tmp_path):
    # #762: `path_outside_project` used to short-circuit EVERY res:// string as
    # inside, so `res://../outside.gd` bypassed containment even though it names
    # a file one directory above the project root — exactly what the absolute
    # spelling of the same file is already refused for. The reported location
    # lets a caller compare the two spellings' refusals directly.
    proj = _make_project(tmp_path / "game")

    assert (
        path_outside_project("res://../outside.gd", proj)
        == (tmp_path / "outside.gd").resolve()
    )
    # The bare escape, with no filename after it, is refused the same way.
    assert path_outside_project("res://..", proj) == tmp_path.resolve()


def test_a_backslash_spelled_res_escape_is_outside(tmp_path):
    # The separator bypass (PR #766 round-2 review): Godot folds `\` to `/` across
    # a res:// address before it collapses anything (ustring.cpp:4192), so
    # `res://..\outside.gd` IS the escaping address to the engine — a real 4.6.3
    # run loads the file one directory above the project and reports it back as
    # `res://../outside.gd`. Reading the backslash as a filename character let this
    # spelling through the very check the slash spelling above is refused by.
    proj = _make_project(tmp_path / "game")

    assert (
        path_outside_project("res://..\\outside.gd", proj)
        == (tmp_path / "outside.gd").resolve()
    )
    # Mixed separators collapse together, exactly as the engine collapses them
    # after the fold: `a\..\..\outside.gd` is `a/../../outside.gd`, net one level up.
    assert (
        path_outside_project("res://a\\..\\..\\outside.gd", proj)
        == (tmp_path / "outside.gd").resolve()
    )


@pytest.mark.skipif(
    os.name != "posix", reason="`\\` is a filename character on POSIX only"
)
def test_a_backslash_in_a_filesystem_path_is_not_a_separator_on_posix(tmp_path):
    # The consequence of the boundary above, on THIS platform: `\` is a legal POSIX
    # filename character, so an ordinary path keeps it and is anchored under the
    # project as the single-segment name it is. Native Windows `pathlib` reads the
    # same string as a parent-directory escape and `path_outside_project` reports it
    # outside — correctly, by that platform's own rule. The claim under test is that
    # gda defers to the platform here, not that the string is inert everywhere.
    proj = _make_project(tmp_path / "game")

    assert path_outside_project("..\\outside.gd", proj) is None


def test_a_res_path_that_collapses_back_inside_is_not_outside(tmp_path):
    # A `..` a lexical collapse cancels out stays inside: `res://foo/../bar.gd`
    # normalizes to `res://bar.gd`, net-inside the namespace, exactly as Godot
    # itself would canonicalize the address. `resource import`'s own res://
    # gate (`_asset_res_path`) is stricter — it refuses ANY literal `..`
    # component regardless of net effect — and #763 tracks reconciling the two;
    # this authority's rule is decided here.
    proj = _make_project(tmp_path / "game")

    assert path_outside_project("res://foo/../bar.gd", proj) is None


def test_a_res_path_starting_with_two_dots_is_not_an_escape(tmp_path):
    # `res://..foo.gd` names a real file whose name merely starts with two dots,
    # not a traversal — the escape test is the first PATH SEGMENT, not a string
    # prefix.
    proj = _make_project(tmp_path / "game")

    assert path_outside_project("res://..foo.gd", proj) is None


def test_user_and_uid_paths_stay_inside_even_with_a_dotdot(tmp_path):
    # Only res:// gets the lexical escape check (#762): user:// and uid:// stay
    # inside by construction, unchanged — gda still cannot make a filesystem
    # statement about where either one really resolves.
    proj = _make_project(tmp_path / "game")

    assert path_outside_project("user://../outside.gd", proj) is None
    assert path_outside_project("uid://../abc123", proj) is None


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
    # CONTAINMENT still says "inside", and that is the point of keeping this pin
    # after #697: a script in a project nested under the resolved one really is in
    # the resolved project's tree, so this check — which asks only about the tree —
    # must keep saying so. What the file does NOT belong to is answered by
    # `owning_project` below, a separate question the ADR-0006 amendment adds
    # rather than a second opinion smuggled into this one.
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


# --- the res:// lexical primitives this module owns (#763) -------------------
#
# `canonical_res_path` and `res_escape_remainder` moved here from
# `gda.script_errors` with #763: they are pure lexical `res://` rules with several
# consumers (the stderr parser, `script run`'s address gate, `path_outside_project`
# itself), and leaving them in the stderr parser had ADR-0006's path authority
# importing FROM a diagnostics module. Their tests move with them.


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [
        ("res://bad.gd", "res://bad.gd"),
        ("res://sub/../bad.gd", "res://bad.gd"),
        ("res://./bad.gd", "res://bad.gd"),
        ("res://a//b.gd", "res://a/b.gd"),
        ("res://sub//..//bad.gd", "res://bad.gd"),
        ("res:///bad.gd", "res://bad.gd"),
        ("res://a/./b/../c.gd", "res://a/c.gd"),
        # Degenerate but well-defined: the bare scheme, and a path that cannot be
        # collapsed further without escaping the project root.
        ("res://", "res://"),
        ("res://../outside.gd", "res://../outside.gd"),
        # The engine-parity row #763 closes: when EVERY segment collapses away,
        # `String::simplify_path` joins an empty vector and returns the bare drive
        # (`res://`), while `posixpath.normpath` returns `.`. gda used to hand on
        # `res://.` — a second spelling of the project root that each consumer had
        # to know about, and `resource import` reported in a refusal message.
        # One root spelling leaves here now, the engine's own.
        ("res://.", "res://"),
        ("res://a/..", "res://"),
        ("res://./", "res://"),
        ("res://a/b/../..", "res://"),
        ("res://a\\..", "res://"),
        # ...and the root is NOT swallowed one level further: `res://..` still
        # climbs, because the engine disables its leading-`..` strip for a res://
        # address (`absolute_path` is forced false, ustring.cpp:4203).
        ("res://..", "res://.."),
        # A BACKSLASH is a separator inside a res:// address, not a filename
        # character: Godot folds `\` to `/` across the whole address before it
        # collapses anything (`String::simplify_path`, ustring.cpp:4192), so the
        # engine loads — and reports back — the slash spelling. Reading these as
        # ordinary filenames let `res://..\outside.gd` past the containment check
        # that already refuses `res://../outside.gd` (#762).
        ("res://a\\b.gd", "res://a/b.gd"),
        ("res://..\\outside.gd", "res://../outside.gd"),
        ("res://a\\..\\..\\outside.gd", "res://../outside.gd"),
        # The fold must run BEFORE the leading-slash strip, as the engine runs it
        # before its own empty-segment split — otherwise this one stays `res:///a.gd`.
        ("res://\\a.gd", "res://a.gd"),
        # Not a res:// address: normalizing an address is not validating one. A
        # filesystem path keeps its backslashes — POSIX allows `\` in a filename,
        # and the fold is the ENGINE's res:// rule, not the filesystem's.
        ("/abs/path.gd", "/abs/path.gd"),
        ("relative.gd", "relative.gd"),
        ("/abs/we\\ird.gd", "/abs/we\\ird.gd"),
        # The same two strings as the res:// rows above, MINUS the scheme, so the
        # contrast is one row apart: with `res://` the backslash is a separator the
        # engine folds, without it the string is a filename gda must not rewrite.
        ("a\\b.gd", "a\\b.gd"),
        ("..\\outside.gd", "..\\outside.gd"),
    ],
)
def test_canonical_res_path_collapses_lexically(spelling, canonical):
    assert canonical_res_path(spelling) == canonical
    # Idempotent: canonicalizing a canonical address changes nothing, which is what
    # lets every consumer apply it without coordinating.
    assert canonical_res_path(canonical) == canonical


@pytest.mark.parametrize(
    ("spelling", "escape"),
    [
        # Inside: nothing to report.
        ("res://hero.gd", None),
        ("res://a/b/hero.gd", None),
        ("res://", None),
        ("res://.", None),
        ("res://a/..", None),
        # A `..` a collapse cancels out is net-inside — the rule `resource import`
        # disagreed with until #763.
        ("res://foo/../bar.gd", None),
        # A filename that merely STARTS with two dots is a real file, not a
        # traversal: the test is the first SEGMENT, never a string prefix.
        ("res://..foo.gd", None),
        # Escapes, with the canonical remainder that is still climbing.
        ("res://..", ".."),
        ("res://../outside.gd", "../outside.gd"),
        ("res://a/../../outside.gd", "../outside.gd"),
        ("res://../..", "../.."),
        # ...and the same escapes spelled with the separator the engine folds.
        ("res://..\\outside.gd", "../outside.gd"),
        ("res://a\\..\\..\\outside.gd", "../outside.gd"),
    ],
)
def test_res_escape_remainder_is_the_one_lexical_containment_rule(spelling, escape):
    # The rule all three command gates now reach — two through
    # `path_outside_project`, `script run` directly because it runs before project
    # resolution. It reads the CANONICAL remainder, so the verdict cannot depend on
    # which of an address's equivalent spellings the caller typed.
    assert res_escape_remainder(spelling) == escape


def test_res_escape_remainder_ignores_a_non_res_string():
    # It normalizes and reads an ADDRESS; it does not validate a filesystem path.
    # A bare `..` is a filesystem escape that `path_outside_project`'s anchored
    # reading catches — not this rule's job, and quietly treating it as one would
    # make `res://` the only scheme with a lexical check into a scheme-blind one.
    assert res_escape_remainder("../outside.gd") is None
    assert res_escape_remainder("user://../outside.gd") is None


# --- ownership: is the RESOLVED project actually the target's owner? (#697) ---


def test_a_nested_project_owns_its_own_scripts(tmp_path):
    # GDA-DF-035 reading 2, at the seam: the target is inside the resolved
    # project's tree, so containment says "inside", and yet `outer/inner` is what
    # its `res://` references mean. Compiling it against `outer` is what produced
    # the false dependency cascade. `owning_project` is the half that sees it.
    outer = _make_project(tmp_path / "outer")
    inner = _make_project(outer / "inner")

    assert owning_project(str(inner / "main.gd"), outer) == inner
    # ...through every spelling of the same file the commands accept.
    assert owning_project("inner/main.gd", outer) == inner
    assert owning_project("res://inner/main.gd", outer) == inner
    assert owning_project("res://a/../inner/main.gd", outer) == inner


def test_the_resolved_project_owning_its_own_script_is_not_a_refusal(tmp_path):
    # The walk STOPS at the resolved project, so the ordinary call — the one every
    # other test in this file is about — reports no owner. Without the stop, every
    # correct invocation would find the resolved project's own marker and refuse.
    proj = _make_project(tmp_path / "game")

    assert owning_project(str(proj / "hero.gd"), proj) is None
    assert owning_project("scripts/hero.gd", proj) is None
    assert owning_project("res://scripts/hero.gd", proj) is None
    assert owning_project("res://", proj) is None


def test_a_projectless_call_still_finds_the_target_s_owner(tmp_path, monkeypatch):
    # GDA-DF-035 reading 1: a project nested in a plain workspace, validated from
    # the ancestor. Nothing resolves, so containment has no root to be outside of
    # and used to pass the file through to a projectless engine — where its res://
    # references resolved against nothing and produced the same false cascade, with
    # `project_root: null` as the only clue. With no project to stop at the walk
    # runs to the filesystem root, and the owner is named.
    workspace = tmp_path / "workspace"
    game = _make_project(workspace / "game")
    monkeypatch.chdir(workspace)

    assert owning_project(str(game / "main.gd"), None) == game
    assert owning_project("game/main.gd", None) == game


def test_a_projectless_standalone_script_has_no_owner(tmp_path, monkeypatch):
    # ...and the mode ADR-0006 keeps: a loose .gd that no project.godot claims is
    # still validated projectless by filesystem path. The probe must not turn the
    # documented fallback into a refusal for the files it exists to serve.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scratch.gd").write_text("extends Node\n", encoding="utf-8")

    assert owning_project(str(tmp_path / "scratch.gd"), None) is None
    assert owning_project("scratch.gd", None) is None


def test_a_symlinked_in_library_that_is_no_project_has_no_owner(tmp_path):
    # The monorepo shared-addon layout `path_outside_project` deliberately accepts
    # (game/addons/cardlib -> ../../libs/cardlib) must not be refused by the OTHER
    # half. The library is a plain directory: nothing between the file and `game`
    # claims it, so `game` stays its owner and the call still works.
    proj = _make_project(tmp_path / "game")
    (proj / "addons").mkdir()
    library = tmp_path / "libs" / "cardlib"
    library.mkdir(parents=True)
    (library / "card.gd").write_text("extends Node\n", encoding="utf-8")
    (proj / "addons" / "cardlib").symlink_to(library, target_is_directory=True)

    assert owning_project(str(proj / "addons" / "cardlib" / "card.gd"), proj) is None


def test_a_symlinked_in_PROJECT_is_owned_by_it_like_a_nested_one(tmp_path):
    # The known edge #697 recorded from PR #695's round 2, decided here: a symlink
    # inside project P pointing at a directory that is its own project Q used to be
    # accepted and compiled against P. It is the LINK-SPELLED instance of the
    # nested-under-resolved boundary above, so it gets the same answer — the
    # spelling a caller reached the file through does not change which project's
    # `res://` root that file's own references mean.
    proj = _make_project(tmp_path / "game")
    (proj / "addons").mkdir()
    vendored = _make_project(tmp_path / "libs" / "demo")
    (vendored / "card.gd").write_text("extends Node\n", encoding="utf-8")
    (proj / "addons" / "demo").symlink_to(vendored, target_is_directory=True)

    # The PROBE answers in the caller's own spelling, because the walk is lexical —
    # that is what keeps the plain-library case above inside. What the ENVELOPE
    # reports is that answer RESOLVED (every call site passes `owner.resolve()`),
    # so a caller reading `evidence.owning_project` sees `libs/demo`, not
    # `game/addons/demo`. Deliberate, and the two are one directory either way:
    # `target_location` and `project_root` are both published resolved
    # (`FailureEvidence`), and a refusal that mixed forms would let a caller
    # compare two coordinates that are not in the same coordinate system. The
    # spelling the caller typed is not lost — the re-issue target is derived from
    # it, below.
    assert owning_project(str(proj / "addons" / "demo" / "card.gd"), proj) == (
        proj / "addons" / "demo"
    )
    assert (
        owner_relative_target(
            str(proj / "addons" / "demo" / "card.gd"),
            proj,
            proj / "addons" / "demo",
        )
        == "card.gd"
    )


def test_the_reissue_target_is_lexical_so_a_file_link_still_has_one(tmp_path):
    # Why the respelling subtracts the LEXICAL pair and not the resolved one. A
    # file link inside a nested project points its resolved location out of that
    # project, so `target_location.relative_to(owning_project)` — the subtraction a
    # caller can do from the published coordinates, and the obvious way to write
    # this helper — raises instead of answering. The lexical pair cannot: the owner
    # is always a lexical ancestor of the lexical target, by construction of the
    # walk that found it. And `link.gd` is the spelling that WORKS, because the
    # engine walks the project directory too.
    outer = _make_project(tmp_path / "outer")
    inner = _make_project(outer / "inner")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.gd").write_text("extends Node\n", encoding="utf-8")
    (inner / "link.gd").symlink_to(elsewhere / "x.gd")

    assert owning_project("inner/link.gd", outer) == inner
    assert owner_relative_target("inner/link.gd", outer, inner) == "link.gd"
    # The resolved subtraction, shown failing on the same input.
    with pytest.raises(ValueError):
        target_location("inner/link.gd", outer).relative_to(inner.resolve())


def test_the_reissue_target_answers_the_same_for_every_accepted_spelling(tmp_path):
    # `res://`, project-relative and absolute all address one file, so they must
    # produce one re-issue — the three refusing commands take different subsets of
    # them and the sentence is shared.
    outer = _make_project(tmp_path / "outer")
    inner = _make_project(outer / "inner")
    (inner / "sub").mkdir()

    for spelling in (
        "res://inner/sub/main.gd",
        "inner/sub/main.gd",
        str(inner / "sub" / "main.gd"),
    ):
        assert owner_relative_target(spelling, outer, inner) == "sub/main.gd", spelling


def test_the_reissue_target_of_a_projectless_call_is_relative_to_the_owner(
    tmp_path, monkeypatch
):
    # The projectless GDA-DF-035 reading: no root resolved, so the target anchors
    # at gda's cwd and the owner is found by walking to the filesystem root. The
    # re-issue still has to be the owner-relative spelling, not the cwd-relative
    # one the caller typed.
    monkeypatch.chdir(tmp_path)
    game = _make_project(tmp_path / "workspace" / "game")
    (game / "main.gd").write_text("extends Node\n", encoding="utf-8")

    assert owning_project("workspace/game/main.gd", None) == game
    assert owner_relative_target("workspace/game/main.gd", None, game) == "main.gd"


def test_ownership_says_nothing_about_the_other_engine_schemes(tmp_path):
    # user:// addresses the engine's own data directory and uid:// is an opaque
    # identifier: neither has a position in a project tree to walk up from, so
    # neither can be owned by a project other than the resolved one.
    outer = _make_project(tmp_path / "outer")
    _make_project(outer / "inner")

    assert owning_project("user://save.gd", outer) is None
    assert owning_project("uid://abc123", outer) is None
    assert owning_project("user://save.gd", None) is None


def test_ownership_is_reported_never_adopted(tmp_path):
    # The line the ADR-0006 amendment draws, pinned as behaviour rather than prose:
    # the probe RETURNS the owner it found, and resolution is untouched by it —
    # `resolve_project_dir` still answers flag > env > cwd, so one call keeps
    # exactly one root no matter how many owners a batch names.
    outer = _make_project(tmp_path / "outer")
    inner = _make_project(outer / "inner")

    assert owning_project(str(inner / "main.gd"), outer) == inner
    assert resolve_project_dir(str(outer), env={}, cwd=inner) == outer


def test_a_project_and_a_target_spelled_through_different_paths_have_one_owner(
    tmp_path,
):
    # The regression the ownership walk introduced and this pins closed: the STOP
    # test must see through a symlinked spelling the way containment already does.
    # With the project named through a link and the target named resolved (macOS
    # `/tmp` -> `/private/tmp` produces exactly this from any tool that realpaths a
    # listing), a purely lexical stop walked PAST the resolved project, found its
    # marker, and refused a correct call by naming the very project that was
    # passed — `owning_project == project` is a machine-checkable impossibility for
    # a code that means "a DIFFERENT project owns this".
    real = _make_project(tmp_path / "real" / "game")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real", target_is_directory=True)

    assert owning_project(str(real / "main.gd"), link / "game") is None
    assert owning_project(str(link / "game" / "main.gd"), real) is None


def test_ownership_says_nothing_about_a_target_outside_the_resolved_tree(tmp_path):
    # Ownership is the SECOND half of one question, asked only of a target that is
    # in the resolved tree; everything else is containment's. Without the bound the
    # walk started outside the tree and could name an unrelated ancestor project as
    # the "owner" of a target whose real problem is that it escaped — and, for the
    # degenerate spellings that name the project directory itself, it started at
    # the project's PARENT and so could never reach its own stop.
    workspace = _make_project(tmp_path / "ws")
    game = _make_project(workspace / "game")

    # Escapes, res:// and filesystem alike: no owner here, refused by containment.
    for escaping in ("res://../x.gd", "../x.gd", "res://a/../../x.gd"):
        assert owning_project(escaping, game) is None, escaping
        assert path_outside_project(escaping, game) is not None, escaping
    # The project directory named as a target, in every spelling that collapses to
    # it. `""` is the real-world shape (an unset `gda script validate "$F"`), and it
    # used to be reported as OWNED BY the workspace above.
    for degenerate in ("", ".", "./", "sub/..", "res://", "res://.", "res://sub/.."):
        assert owning_project(degenerate, game) is None, degenerate


def test_target_location_anchors_a_res_address_in_the_namespace_it_names(tmp_path):
    # The coordinate `evidence.target_location` carries has to name a real place —
    # it is what a caller walks up from. Handing a `res://` string to a filesystem
    # anchoring made `Path("res://inner/main.gd")` the RELATIVE `res:/inner/main.gd`
    # and reported `<project>/res:/inner/main.gd`, a directory that does not exist.
    project = _make_project(tmp_path / "game")

    assert target_location("res://inner/main.gd", project) == (
        (project / "inner" / "main.gd").resolve()
    )
    # Every spelling of one file lands on one location, because it goes through the
    # same canonicalizer the containment rule uses.
    assert target_location("res://a/../inner/main.gd", project) == (
        (project / "inner" / "main.gd").resolve()
    )
    assert target_location("inner/main.gd", project) == (
        (project / "inner" / "main.gd").resolve()
    )
    assert target_location(str(project / "inner" / "main.gd"), project) == (
        (project / "inner" / "main.gd").resolve()
    )


# --- The main-scene precondition for a live session launch (#829) -------------


def _project_with(tmp_path, text: str):
    (tmp_path / "project.godot").write_text(text, encoding="utf-8")
    return tmp_path


def test_main_scene_undefined_is_the_empty_or_absent_setting(tmp_path):
    from gda.project import MAIN_SCENE_UNDEFINED, main_scene_unrunnable

    absent = _project_with(
        tmp_path, 'config_version=5\n\n[application]\n\nconfig/name="t"\n'
    )
    verdict = main_scene_unrunnable(absent, None)
    assert verdict is not None and verdict.code == MAIN_SCENE_UNDEFINED
    assert (
        "application/run/main_scene" in verdict.reason and "--scene" in verdict.reason
    )

    empty = _project_with(
        tmp_path, 'config_version=5\n\n[application]\n\nrun/main_scene=""\n'
    )
    assert main_scene_unrunnable(empty, None) is not None
    # An empty value with a trailing comment is still empty (`;` starts a comment).
    commented_empty = _project_with(
        tmp_path,
        'config_version=5\n\n[application]\n\nrun/main_scene="" ; disabled for now\n',
    )
    assert main_scene_unrunnable(commented_empty, None) is not None
    # No [application] section at all reads the same way.
    bare = _project_with(tmp_path, "config_version=5\n")
    assert main_scene_unrunnable(bare, None) is not None


def test_a_declared_main_scene_or_a_selector_is_runnable(tmp_path):
    from gda.project import main_scene_unrunnable

    for text in (
        'config_version=5\n\n[application]\n\nconfig/name="t"\n'
        'run/main_scene="res://main.tscn"\n\n[debug]\n\nfile_logging/enable_file_logging=false\n',
        # A quoted key is engine-valid; a trailing comment after the value too.
        'config_version=5\n\n[application]\n\n"run/main_scene"="res://main.tscn"\n',
        'config_version=5\n\n[application]\n\nrun/main_scene="res://a;b.tscn" ; the game\n',
        # A section header with a trailing comment; a CRLF file.
        'config_version=5\n\n[application] ; the game\n\nrun/main_scene="res://main.tscn"\n',
        'config_version=5\r\n\r\n[application]\r\n\r\nrun/main_scene="res://a.tscn"\r\n',
    ):
        assert main_scene_unrunnable(_project_with(tmp_path, text), None) is None, text
    # The selector wins over an undefined main scene; an EMPTY selector is no selector.
    undefined = _project_with(tmp_path, "config_version=5\n")
    assert main_scene_unrunnable(undefined, "res://other.tscn") is None
    assert main_scene_unrunnable(undefined, "") is not None


def test_an_override_defers_to_the_engine(tmp_path):
    # Which feature-tagged override applies is the engine's call (its feature set),
    # and an override.cfg can set or clear the value: with either present the
    # verdict refuses nothing, whatever the base key says (#831 review).
    from gda.project import main_scene_unrunnable

    for text in (
        'config_version=5\n\n[application]\n\nrun/main_scene.macos="res://main.tscn"\n',
        'config_version=5\n\n[application]\n\nrun/main_scene=""\nrun/main_scene.macos="res://m.tscn"\n',
        'config_version=5\n\n[application]\n\nrun/main_scene="res://m.tscn"\nrun/main_scene.macos=""\n',
        'config_version=5\n\n[application]\n\nrun/main_scene="uid://c1abc"\nrun/main_scene.windows="res://m.tscn"\n',
    ):
        assert main_scene_unrunnable(_project_with(tmp_path, text), None) is None, text
    overlay = _project_with(tmp_path, "config_version=5\n")
    (overlay / "override.cfg").write_text(
        '[application]\n\nrun/main_scene="res://main.tscn"\n', encoding="utf-8"
    )
    assert main_scene_unrunnable(overlay, None) is None


def test_a_uid_main_scene_needs_the_active_uid_cache(tmp_path):
    # The sibling engine alert (#829 review): Godot 4.4+ writes the setting as a
    # uid:// and resolves it through the UID cache under the project data
    # directory, which a fresh clone does not have — the engine then alerts "could
    # not be resolved from UID". Mirrors the engine's own condition: refused only
    # while the ONE cache the engine reads is absent.
    from gda.project import MAIN_SCENE_UNRESOLVED, main_scene_unrunnable

    project = _project_with(
        tmp_path, 'config_version=5\n\n[application]\n\nrun/main_scene="uid://c1abc"\n'
    )
    verdict = main_scene_unrunnable(project, None)
    assert verdict is not None and verdict.code == MAIN_SCENE_UNRESOLVED
    assert "uid_cache.bin" in verdict.reason and "gda resource import" in verdict.reason
    # A stray cache under the INACTIVE (non-hidden) directory does not count.
    (project / "godot").mkdir()
    (project / "godot" / "uid_cache.bin").write_bytes(b"")
    assert main_scene_unrunnable(project, None) is not None
    (project / ".godot").mkdir()
    (project / ".godot" / "uid_cache.bin").write_bytes(b"")
    assert main_scene_unrunnable(project, None) is None

    # With the non-hidden data directory selected, `godot/` is the one that counts.
    (project / ".godot" / "uid_cache.bin").unlink()
    (project / "godot" / "uid_cache.bin").unlink()
    _project_with(
        tmp_path,
        "config_version=5\n\n[application]\n\nconfig/use_hidden_project_data_directory=false\n"
        'run/main_scene="uid://c1abc"\n',
    )
    assert main_scene_unrunnable(project, None) is not None
    (project / "godot" / "uid_cache.bin").write_bytes(b"")
    assert main_scene_unrunnable(project, None) is None


def test_an_unreadable_project_file_is_no_verdict(tmp_path):
    # Not a decision about the scene: the harness install reports the permission
    # failure as its own, in the order an existing daemon test pins.
    from gda.project import main_scene_unrunnable

    project = _project_with(tmp_path, "config_version=5\n")
    (project / "project.godot").write_bytes(b"\xff\xfe not utf-8")
    assert main_scene_unrunnable(project, None) is None
    missing = tmp_path / "nowhere"
    missing.mkdir()
    assert main_scene_unrunnable(missing, None) is None
