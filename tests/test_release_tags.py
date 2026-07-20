"""Tag derivation is a single authority shared by every release call site."""

import json
from pathlib import Path

import pytest

import release_tags

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = json.loads((ROOT / "release-please-config.json").read_text())
REAL_MANIFEST = json.loads((ROOT / ".release-please-manifest.json").read_text())


def test_root_package_tag_matches_release_please_v_prefix():
    assert release_tags.derive_tag(REAL_CONFIG, ".", "0.8.1") == "v0.8.1"


def test_member_package_tag_carries_its_component():
    assert (
        release_tags.derive_tag(REAL_CONFIG, "libs/gda-balancing", "0.1.0")
        == "gda-balancing-v0.1.0"
    )


# A config whose top-level defaults differ from release-please's own, so a
# derivation that silently assumed the defaults would disagree with it.
SYNTHETIC_CONFIG = {
    "include-component-in-tag": False,
    "include-v-in-tag": False,
    "tag-separator": "/",
    "packages": {
        ".": {},
        "libs/gda-balancing": {
            "component": "gda-balancing",
            "include-component-in-tag": True,
        },
        "libs/overridden": {
            "component": "overridden",
            "include-component-in-tag": True,
            "include-v-in-tag": True,
            "tag-separator": "@",
        },
    },
}


def test_top_level_overrides_apply_to_a_package_that_states_nothing():
    assert release_tags.derive_tag(SYNTHETIC_CONFIG, ".", "0.8.2") == "0.8.2"


def test_package_inherits_the_top_level_separator_and_v_setting():
    assert (
        release_tags.derive_tag(SYNTHETIC_CONFIG, "libs/gda-balancing", "0.1.0")
        == "gda-balancing/0.1.0"
    )


def test_per_package_settings_beat_the_top_level_default():
    assert (
        release_tags.derive_tag(SYNTHETIC_CONFIG, "libs/overridden", "2.0.0")
        == "overridden@v2.0.0"
    )


def test_component_in_tag_without_a_component_fails_loudly():
    # release-please can resolve a component from other package metadata; this
    # module supports only an explicit `component`, so a config that would need
    # inference must fail rather than derive a tag release-please never mints.
    config = {"packages": {"libs/nameless": {"include-component-in-tag": True}}}

    with pytest.raises(release_tags.TagDerivationError) as excinfo:
        release_tags.derive_tag(config, "libs/nameless", "1.0.0")

    assert "libs/nameless" in str(excinfo.value)
    assert "component" in str(excinfo.value)


def test_an_undeclared_package_path_fails_loudly():
    with pytest.raises(release_tags.TagDerivationError):
        release_tags.derive_tag(REAL_CONFIG, "libs/not-a-package", "1.0.0")


def test_required_tags_skips_the_never_released_placeholder():
    manifest = {".": "0.8.1", "libs/gda-balancing": "0.0.0"}

    assert release_tags.required_tags(REAL_CONFIG, manifest) == ["v0.8.1"]


def test_required_tags_covers_every_released_package():
    manifest = {".": "0.8.1", "libs/gda-balancing": "0.1.0"}

    assert release_tags.required_tags(REAL_CONFIG, manifest) == [
        "v0.8.1",
        "gda-balancing-v0.1.0",
    ]


def test_the_real_config_and_manifest_derive_without_error():
    # Drift alarm: the shipped config must stay inside the supported contract.
    for path, version in REAL_MANIFEST.items():
        release_tags.derive_tag(REAL_CONFIG, path, version)

    assert release_tags.required_tags(REAL_CONFIG, REAL_MANIFEST) == ["v0.8.1"]


CONFIG_ARGS = [
    "--config",
    str(ROOT / "release-please-config.json"),
    "--manifest",
    str(ROOT / ".release-please-manifest.json"),
]


def test_main_prints_one_required_tag_per_line(capsys):
    exit_code = release_tags.main([*CONFIG_ARGS, "--required-tags"])

    assert exit_code == 0
    assert capsys.readouterr().out.split() == ["v0.8.1"]


def test_main_prints_a_single_derived_tag(capsys):
    exit_code = release_tags.main(
        [*CONFIG_ARGS, "--tag-for", "libs/gda-balancing", "--version", "0.1.0"]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "gda-balancing-v0.1.0"


def test_main_reports_a_derivation_failure_on_stderr(capsys, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"packages": {"libs/nameless": {"include-component-in-tag": True}}})
    )

    exit_code = release_tags.main(
        ["--config", str(config), "--tag-for", "libs/nameless", "--version", "1.0.0"]
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "libs/nameless" in captured.err
