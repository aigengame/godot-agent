import json
import re
from pathlib import Path


_PLAYTEST = Path(__file__).parents[1] / "examples" / "schema2" / "playtest"
_GENERATED = _PLAYTEST / "generated"


def test_playtest_runtime_dependencies_point_downward():
    allowed_dependencies = {
        "systems": {"systems"},
        "content": {"content", "systems"},
        "ui": {"ui", "content", "systems"},
    }
    dependency_pattern = re.compile(r"res://(addons|systems|content|ui)/")

    for owner, allowed in allowed_dependencies.items():
        for script in (_PLAYTEST / owner).rglob("*.gd"):
            dependencies = set(dependency_pattern.findall(script.read_text()))
            assert dependencies <= allowed, (script, dependencies - allowed)

    assert not (_PLAYTEST / "addons").exists()
    assert "[autoload]" not in (_PLAYTEST / "project.godot").read_text()


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
        assert (_GENERATED / reference["locator"]).resolve().is_file()

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
