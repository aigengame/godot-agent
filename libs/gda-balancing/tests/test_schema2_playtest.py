import os
import re
from pathlib import Path


_PLAYTEST = Path(__file__).parents[1] / "examples" / "schema2" / "playtest"


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
    assert '[&"", &"FREQUENCY_LABEL"]: [&"Rare reward frequency"]' in english
    assert '[&"", &"FREQUENCY_LABEL"]: [&"稀有奖励出现频率"]' in chinese

    key_pattern = re.compile(r'\[&"", &"([A-Z0-9_]+)"\]')
    english_keys = set(key_pattern.findall(english))
    chinese_keys = set(key_pattern.findall(chinese))
    assert english_keys == chinese_keys

    used_keys = set()
    for script in (_PLAYTEST / "ui").glob("*.gd"):
        used_keys.update(re.findall(r'tr\("([A-Z0-9_]+)"\)', script.read_text()))
    assert used_keys <= english_keys


def test_playtest_uses_maintained_sources_without_an_intermediate_case_schema():
    assert not (_PLAYTEST / "generated").exists()
    assert not (_PLAYTEST / "tools" / "generate_reward_cases.py").exists()
    assert not (
        _PLAYTEST / "content" / "reward_run" / "reward_outcome_source.gd"
    ).exists()
    assert not (_PLAYTEST / "systems" / "playtest_session.gd").exists()

    main = (_PLAYTEST / "main.gd").read_text(encoding="utf-8")
    documents = (
        _PLAYTEST / "content" / "reward_run" / "reward_run_documents.gd"
    ).read_text(encoding="utf-8")
    assert "GdaExecutionClient" in main
    assert "roguelike-reward-build" not in main
    assert "model-source.json" not in main
    assert "experiment.json" not in main
    assert "reward_cases" not in main
    assert (
        'const MAINTAINED_SOURCE_DIRECTORY := "res://../roguelike-reward-build"'
        in documents
    )
    assert 'const MODEL_SOURCE_FILE := "model-source.json"' in documents
    assert 'const EXPERIMENT_FILE := "experiment.json"' in documents
    assert 'const PARAMETER_NAME := "rare_weight"' in documents


def test_playtest_has_one_local_launch_action_and_no_standalone_export_claim():
    launch = _PLAYTEST / "scripts" / "run_reward_run.sh"
    assert launch.is_file()
    assert launch.stat().st_mode & os.X_OK
    source = launch.read_text(encoding="utf-8")
    assert "GDA_BALANCING_EXECUTABLE" in source
    assert "--gda-balancing-executable=" in source
    assert ".venv" not in source
    assert 'exec "$' in source
    assert '"${arguments[@]}"' in source
    assert "PyInstaller" not in source
    assert not (_PLAYTEST / "scripts" / "export_macos.sh").exists()
    assert not (_PLAYTEST / "scripts" / "smoke_export_macos.sh").exists()
    assert not (_PLAYTEST / "export_presets.cfg").exists()


def test_playtest_keeps_focused_runtime_behavior_proofs():
    expected = {
        "test_gda_execution_client.gd",
        "test_gda_execution_client_discovery.gd",
        "test_playtest.gd",
        "test_reward_run_controller_failure.gd",
        "test_reward_run_controller_live.gd",
        "test_reward_run_documents.gd",
        "test_reward_run_live_trials.gd",
        "test_reward_run_main_live.gd",
        "test_reward_run_view.gd",
    }
    assert {path.name for path in (_PLAYTEST / "tests").glob("test_*.gd")} == expected


def test_playtest_godot_tests_share_one_test_case_module():
    support = _PLAYTEST / "tests" / "playtest_test_case.gd"
    assert support.is_file()

    for script in (_PLAYTEST / "tests").glob("test_*.gd"):
        source = script.read_text(encoding="utf-8")
        assert source.startswith('extends "res://tests/playtest_test_case.gd"\n')
        assert "func _expect(" not in source
        assert "func _finish(" not in source


def test_reward_trial_owns_gameplay_and_feedback_projections():
    content = _PLAYTEST / "content" / "reward_run"
    trial = content / "reward_trial.gd"
    assert trial.is_file()
    assert not (content / "reward_run_artifact_projector.gd").exists()

    controller = (content / "reward_run_controller.gd").read_text(encoding="utf-8")
    system = (_PLAYTEST / "systems" / "reward_run.gd").read_text(encoding="utf-8")
    assert "trial.gameplay_values()" in controller
    assert "trial.feedback_record()" in controller
    assert "provenance" not in system
    assert "revision" not in system
