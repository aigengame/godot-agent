"""The releasing-type set and the member directory are derived, never restated."""

import json
from pathlib import Path

import pytest

import release_scope_guard

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = json.loads((ROOT / "release-please-config.json").read_text())


def test_releasing_types_are_the_visible_changelog_sections():
    # Every non-hidden section is release-producing: release-please's default
    # versioning strategy patch-bumps such a commit, so `deps` and `revert`
    # count exactly as much as `feat` and `fix`.
    assert release_scope_guard.releasing_types(REAL_CONFIG) == {
        "feat",
        "fix",
        "deps",
        "revert",
    }


def test_a_config_without_changelog_sections_fails_loudly():
    with pytest.raises(release_scope_guard.ScopeGuardConfigError):
        release_scope_guard.releasing_types({"packages": {".": {}}})


RELEASING = {"feat", "fix", "deps", "revert"}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Plain releasing types.
        ("feat: add a thing", True),
        ("fix: repair a thing", True),
        # The two the hard-coded guard used to miss (F2).
        ("deps: bump pydantic", True),
        ("revert: undo the thing", True),
        # Scoped forms.
        ("feat(gda-balancing): add a thing", True),
        ("deps(gda-balancing): bump pydantic", True),
        # Non-releasing types.
        ("chore: tidy up", False),
        ("docs: explain a thing", False),
        ("refactor(scripts): move a thing", False),
        ("perf: speed a thing up", False),
        # A breaking marker bumps on ANY type, including unknown ones.
        ("chore!: drop python 3.12", True),
        ("wibble!: something unknown", True),
        ("chore(scripts)!: drop a helper", True),
        ("feat!: change the surface", True),
        # An unknown type without a breaking marker bumps nothing.
        ("wibble: something unknown", False),
        # Unparseable headers cannot bump anything.
        ("just some words", False),
        ("", False),
        ("feat add a thing", False),
        (": no type at all", False),
        ("feat(unclosed: scope", False),
        # Case-insensitive, as release-please's parser is.
        ("FEAT: shouting", True),
        ("Fix: capitalized", True),
    ],
)
def test_is_releasing_title(title, expected):
    assert release_scope_guard.is_releasing_title(title, RELEASING) is expected


def test_member_dirs_come_from_the_root_packages_exclude_paths():
    assert release_scope_guard.member_dirs(REAL_CONFIG) == ["libs/gda-balancing"]


def test_a_root_package_without_exclude_paths_fails_loudly():
    with pytest.raises(release_scope_guard.ScopeGuardConfigError):
        release_scope_guard.member_dirs({"packages": {".": {}}})


MEMBER_ONLY = ["libs/gda-balancing/src/gda_balancing/cli.py"]
ROOT_ONLY = ["src/gda/cli.py", "README.md"]
MIXED = [*MEMBER_ONLY, *ROOT_ONLY]


def _verdict(title, files):
    return release_scope_guard.verdict(title, files, REAL_CONFIG)


@pytest.mark.parametrize(
    "title",
    ["feat: x", "fix: x", "deps: x", "revert: x", "wibble!: x", "feat(scope): x"],
)
@pytest.mark.parametrize(
    ("files", "ok"),
    [
        (MEMBER_ONLY, True),
        (ROOT_ONLY, True),
        (MIXED, False),
        ([], True),
    ],
)
def test_releasing_titles_only_fail_when_they_straddle_the_member_boundary(
    title, files, ok
):
    result = _verdict(title, files)

    assert result.releasing is True
    assert result.ok is ok


@pytest.mark.parametrize("title", ["chore: x", "docs: x", "wibble: x", "nonsense"])
@pytest.mark.parametrize("files", [MEMBER_ONLY, ROOT_ONLY, MIXED, []])
def test_a_non_releasing_title_is_always_a_no_op(title, files):
    result = _verdict(title, files)

    assert result.releasing is False
    assert result.ok is True


def test_the_offending_paths_are_the_ones_outside_the_member_directory():
    result = _verdict("feat: x", MIXED)

    assert result.inside == MEMBER_ONLY
    assert result.outside == ROOT_ONLY
    assert result.touches_member is True


def test_a_sibling_directory_sharing_the_prefix_is_not_inside_the_member():
    # release-please matches `path + "/"`, so `libs/gda-balancing-extra` is a
    # different directory — a releasing PR touching both straddles the boundary.
    files = ["libs/gda-balancing/x.py", "libs/gda-balancing-extra/x.py"]

    result = _verdict("feat: x", files)

    assert result.inside == ["libs/gda-balancing/x.py"]
    assert result.outside == ["libs/gda-balancing-extra/x.py"]
    assert result.ok is False


def test_a_file_named_like_the_member_directory_is_not_inside_it():
    result = _verdict("feat: x", ["libs/gda-balancing"])

    assert result.inside == []
    assert result.outside == ["libs/gda-balancing"]


def test_a_failing_verdict_explains_how_to_split_the_pr():
    message = _verdict("feat: x", MIXED).message()

    assert "src/gda/cli.py" in message
    assert "split" in message.lower()


def _main(title, files, tmp_path):
    listing = tmp_path / "changed-files.txt"
    listing.write_text("\n".join(files) + "\n")
    return release_scope_guard.main(
        [
            "--config",
            str(ROOT / "release-please-config.json"),
            "--title",
            title,
            "--changed-files",
            str(listing),
        ]
    )


def test_main_passes_a_releasing_member_only_pr(capsys, tmp_path):
    exit_code = _main("feat(gda-balancing): add a thing", MEMBER_ONLY, tmp_path)

    assert exit_code == 0
    assert "confined to" in capsys.readouterr().out


def test_main_fails_a_releasing_pr_that_straddles_the_boundary(capsys, tmp_path):
    exit_code = _main("deps: bump pydantic everywhere", MIXED, tmp_path)

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "src/gda/cli.py" in captured.err
    assert "splitting the PR" in captured.err


def test_main_ignores_blank_lines_in_the_changed_file_listing(capsys, tmp_path):
    listing = tmp_path / "changed-files.txt"
    listing.write_text("\n\nlibs/gda-balancing/x.py\n\n")

    exit_code = release_scope_guard.main(
        [
            "--config",
            str(ROOT / "release-please-config.json"),
            "--title",
            "feat: x",
            "--changed-files",
            str(listing),
        ]
    )

    assert exit_code == 0
    assert "confined to" in capsys.readouterr().out
