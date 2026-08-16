import json
import re
from pathlib import Path


_PLAYTEST = Path(__file__).parents[1] / "examples" / "schema2" / "playtest"
_GENERATED = _PLAYTEST / "generated"


def test_playtest_runtime_dependencies_point_downward():
    allowed_dependencies = {
        "addons": {"addons"},
        "systems": {"systems"},
        "content": {"addons", "content", "systems"},
        "ui": {"content", "ui"},
    }
    dependency_pattern = re.compile(r"res://(addons|systems|content|ui)/")

    for owner, allowed in allowed_dependencies.items():
        for script in (_PLAYTEST / owner).rglob("*.gd"):
            dependencies = set(dependency_pattern.findall(script.read_text()))
            assert dependencies <= allowed, (script, dependencies - allowed)

    assert not (_PLAYTEST / "addons" / "gda_balancing_client" / "plugin.cfg").exists()
    project_settings = list(_PLAYTEST.glob("project.*"))
    assert len(project_settings) == 1
    assert "[autoload]" not in project_settings[0].read_text()


def test_playtest_player_settings_have_explicit_defaults_and_translations():
    project_path = next(_PLAYTEST.glob("project.*"))
    project = project_path.read_text(encoding="utf-8")
    assert "window/size/viewport_width=1920" in project
    assert "window/size/viewport_height=1080" in project
    assert "window/size/window_width_override=2560" in project
    assert "window/size/window_height_override=1440" in project

    english = (_PLAYTEST / "ui" / "localization" / "playtest.en.tres").read_text(
        encoding="utf-8"
    )
    chinese = (_PLAYTEST / "ui" / "localization" / "playtest.zh_CN.tres").read_text(
        encoding="utf-8"
    )
    assert 'locale = "en"' in english
    assert 'locale = "zh_CN"' in chinese
    assert '[&"", &"SETTINGS_RESOLUTION"]: [&"Resolution"]' in english
    assert '[&"", &"SETTINGS_RESOLUTION"]: [&"分辨率"]' in chinese
    assert '[&"", &"SETTINGS_LANGUAGE"]: [&"Language"]' in english
    assert '[&"", &"SETTINGS_LANGUAGE"]: [&"语言"]' in chinese

    key_pattern = re.compile(r'\[&"", &"([A-Z0-9_]+)"\]')
    english_keys = set(key_pattern.findall(english))
    chinese_keys = set(key_pattern.findall(chinese))
    assert english_keys == chinese_keys

    used_keys = set()
    for script in (_PLAYTEST / "ui").glob("*.gd"):
        used_keys.update(re.findall(r'tr\("([A-Z0-9_]+)"\)', script.read_text()))
    assert used_keys <= english_keys


def test_playtest_player_cases_hide_balancing_artifacts():
    player_cases = (_GENERATED / "reward_cases.json").read_text(encoding="utf-8")
    for internal_term in (
        "artifact",
        "experiment",
        "formula",
        "metric",
        "model",
        "package release",
        "rir",
        "trace",
        "typed value",
    ):
        assert internal_term not in player_cases.lower()

    parsed = json.loads(player_cases)
    assert parsed["schema_version"] == 1
    assert [trial["id"] for trial in parsed["trials"]] == [
        "trial-one",
        "trial-two",
    ]


def test_playtest_provenance_references_resolve_to_checked_in_evidence():
    provenance = json.loads(
        (_GENERATED / "evidence" / "playtest-provenance.json").read_text(
            encoding="utf-8"
        )
    )

    def assert_artifact_reference(reference):
        assert reference["identity"].startswith("sha256:")
        artifact_path = (_GENERATED / reference["locator"]).resolve()
        assert artifact_path.is_file()
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        if "content_identity" in artifact:
            assert reference["identity"] == artifact["content_identity"]

    for entry in provenance["entries"].values():
        assert_artifact_reference(entry["experiment"])
        assert_artifact_reference(entry["metrics"])
        assert_artifact_reference(entry["rng_observation"])
        for reference in entry["model"].values():
            assert_artifact_reference(reference)
        for reference in entry["runtime"].values():
            assert_artifact_reference(reference)


def test_playtest_export_excludes_maintainer_and_development_files():
    preset = (_PLAYTEST / "export_presets.cfg").read_text(encoding="utf-8")
    assert 'export_filter="all_resources"' in preset
    assert 'include_filter="generated/reward_cases.json"' in preset
    assert 'exclude_filter="build/*"' in preset
    assert (_PLAYTEST / "docs" / ".gdignore").is_file()
    assert (_PLAYTEST / "generated" / "evidence" / ".gdignore").is_file()
    assert (_PLAYTEST / "tests" / ".gdignore").is_file()
