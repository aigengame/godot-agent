"""The releasing-type set and the member directory are derived, never restated."""

import json
from pathlib import Path

import pytest

import release_scope_guard

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = json.loads((ROOT / "release-please-config.json").read_text())


def test_a_packages_own_changelog_sections_override_the_top_level_ones():
    # release-please resolves `changelog-sections` per package with the
    # top-level value as the DEFAULT, so a package that declares its own is not
    # described by the top-level list at all.
    config = {
        "changelog-sections": [{"type": "feat", "section": "Features"}],
        "packages": {
            ".": {"exclude-paths": ["libs/member"]},
            "libs/member": {
                "changelog-sections": [{"type": "security", "section": "Security"}]
            },
        },
    }

    assert release_scope_guard.releasing_types(config, "libs/member") == {"security"}


SECURITY_ONLY = [{"type": "security", "section": "Security"}]


def test_a_type_visible_only_via_package_overrides_still_straddles_the_boundary():
    # The reviewer's repro: top-level makes only `feat` visible, but BOTH
    # packages override that with `security`. Reading only the top-level
    # sections called this title non-releasing and passed a PR that proposes
    # two Release PRs.
    config = {
        "changelog-sections": [{"type": "feat", "section": "Features"}],
        "packages": {
            ".": {
                "exclude-paths": ["libs/gda-balancing"],
                "changelog-sections": SECURITY_ONLY,
            },
            "libs/gda-balancing": {"changelog-sections": SECURITY_ONLY},
        },
    }

    result = release_scope_guard.verdict(
        "security(gda-balancing): patch a hole",
        ["libs/gda-balancing/pyproject.toml", "README.md"],
        config,
    )

    assert result.releasing is True
    assert result.ok is False


def test_a_type_a_package_hides_still_straddles_when_another_releases_it():
    # The conservative predicate: `feat` is hidden for the member but visible
    # for the root, so this PR bumps `gda` alone. An "only when it releases
    # BOTH" predicate would pass it — yet it reproduces exactly the original
    # harm, a member-scoped change bumping the root.
    # Top-level does not make `feat` visible either, so this case also rules out
    # reading the top-level list alone — all three candidate rules disagree here.
    config = {
        "changelog-sections": SECURITY_ONLY,
        "packages": {
            ".": {
                "exclude-paths": ["libs/gda-balancing"],
                "changelog-sections": [{"type": "feat", "section": "Features"}],
            },
            "libs/gda-balancing": {
                "changelog-sections": [
                    {"type": "feat", "section": "Features", "hidden": True},
                    *SECURITY_ONLY,
                ]
            },
        },
    }

    result = release_scope_guard.verdict("feat: x", MIXED, config)

    assert release_scope_guard.releasing_types(config, ".") == {"feat"}
    assert release_scope_guard.releasing_types(config, "libs/gda-balancing") == {
        "security"
    }
    assert result.releasing is True
    assert result.ok is False


def test_a_type_only_the_member_declares_still_straddles_the_boundary():
    config = {
        "changelog-sections": [{"type": "feat", "section": "Features"}],
        "packages": {
            ".": {"exclude-paths": ["libs/gda-balancing"]},
            "libs/gda-balancing": {
                "changelog-sections": [
                    {"type": "feat", "section": "Features"},
                    *SECURITY_ONLY,
                ]
            },
        },
    }

    result = release_scope_guard.verdict("security: x", MIXED, config)

    # The root inherits the top-level list, which never mentions `security`.
    assert release_scope_guard.releasing_types(config, ".") == {"feat"}
    assert result.releasing is True
    assert result.ok is False


def test_a_config_declaring_no_sections_falls_back_to_release_pleases_defaults():
    # release-please's own DEFAULT_CHANGELOG_SECTIONS, non-hidden entries.
    config = {"packages": {".": {"exclude-paths": ["libs/gda-balancing"]}}}

    assert release_scope_guard.releasing_types(config, ".") == {
        "feat",
        "fix",
        "perf",
        "revert",
    }


def test_the_shipped_config_resolves_the_same_sections_for_every_package():
    # Drift alarm: today's config declares no package-level override, so both
    # packages resolve to the one top-level list. If that ever stops holding,
    # this fails and the per-package resolution above is what keeps the guard
    # correct.
    for path in REAL_CONFIG["packages"]:
        assert release_scope_guard.releasing_types(REAL_CONFIG, path) == {
            "feat",
            "fix",
            "deps",
            "revert",
        }, path


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
