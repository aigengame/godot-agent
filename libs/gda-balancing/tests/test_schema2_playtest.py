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
    reward_english = (
        _PLAYTEST / "ui" / "reward_run" / "localization" / "reward_run.en.tres"
    ).read_text(encoding="utf-8")
    reward_chinese = (
        _PLAYTEST
        / "ui"
        / "reward_run"
        / "localization"
        / "reward_run.zh_CN.tres"
    ).read_text(encoding="utf-8")
    assert '[&"", &"FREQUENCY_LABEL"]: [&"Rare reward frequency"]' in reward_english
    assert '[&"", &"FREQUENCY_LABEL"]: [&"稀有奖励出现频率"]' in reward_chinese

    key_pattern = re.compile(r'\[&"", &"([A-Z0-9_]+)"\]')
    for english_path in (_PLAYTEST / "ui").rglob("*.en.tres"):
        chinese_path = english_path.with_name(
            english_path.name.replace(".en.tres", ".zh_CN.tres")
        )
        assert chinese_path.is_file(), english_path
        english_keys = set(key_pattern.findall(english_path.read_text()))
        chinese_keys = set(key_pattern.findall(chinese_path.read_text()))
        assert english_keys == chinese_keys, english_path

    used_keys = set()
    all_translation_keys = set()
    for translation in (_PLAYTEST / "ui").rglob("*.en.tres"):
        all_translation_keys.update(key_pattern.findall(translation.read_text()))
    for script in (_PLAYTEST / "ui").rglob("*.gd"):
        used_keys.update(re.findall(r'tr\("([A-Z0-9_]+)"\)', script.read_text()))
    assert used_keys <= all_translation_keys


def test_playtest_uses_maintained_sources_without_an_intermediate_case_schema():
    assert not (_PLAYTEST / "generated").exists()
    assert not (_PLAYTEST / "tools" / "generate_reward_cases.py").exists()
    assert not (
        _PLAYTEST / "content" / "reward_run" / "reward_outcome_source.gd"
    ).exists()
    assert not (
        _PLAYTEST / "content" / "reward_run" / "reward_feedback_recorder.gd"
    ).exists()
    assert not (_PLAYTEST / "systems" / "playtest_session.gd").exists()

    main = (_PLAYTEST / "apps" / "reward_run" / "main.gd").read_text(
        encoding="utf-8"
    )
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


def test_playtest_has_explicit_local_launch_actions_and_no_standalone_export_claim():
    launch = _PLAYTEST / "scripts" / "run_reward_run.sh"
    assert launch.is_file()
    assert launch.stat().st_mode & os.X_OK
    source = launch.read_text(encoding="utf-8")
    assert "res://apps/reward_run/main.tscn" in source
    assert 'exec "$' in source
    assert "PyInstaller" not in source
    common = (_PLAYTEST / "scripts" / "run_playtest.sh").read_text(encoding="utf-8")
    assert "GDA_BALANCING_EXECUTABLE" in common
    assert "--gda-balancing-executable=" in common
    assert ".venv" not in common
    assert '"${arguments[@]}"' in common
    combat = _PLAYTEST / "scripts" / "run_combat_cast.sh"
    assert combat.is_file()
    assert combat.stat().st_mode & os.X_OK
    assert "res://apps/combat_cast/main.tscn" in combat.read_text(encoding="utf-8")
    assert not (_PLAYTEST / "scripts" / "export_macos.sh").exists()
    assert not (_PLAYTEST / "scripts" / "smoke_export_macos.sh").exists()
    assert not (_PLAYTEST / "export_presets.cfg").exists()


def test_reward_run_has_an_explicit_thin_application_entry():
    app = _PLAYTEST / "apps" / "reward_run"
    assert (app / "main.gd").is_file()
    assert (app / "main.tscn").is_file()
    assert not (_PLAYTEST / "main.gd").exists()
    assert not (_PLAYTEST / "main.tscn").exists()

    source = (app / "main.gd").read_text(encoding="utf-8")
    assert "GdaExecutionClient" in source
    assert "RewardRunController" in source
    assert 'preload("res://ui/' not in source
    assert "roguelike-reward-build" not in source
    assert "model-source.json" not in source
    assert "experiment.json" not in source

    combat_app = _PLAYTEST / "apps" / "combat_cast"
    assert (combat_app / "main.gd").is_file()
    assert (combat_app / "main.tscn").is_file()
    combat_source = (combat_app / "main.gd").read_text(encoding="utf-8")
    assert "GdaExecutionClient" in combat_source
    assert "CombatCastController" in combat_source
    assert "rpg-combat-cast" not in combat_source


def test_playtest_keeps_focused_runtime_behavior_proofs():
    expected = {
        "test_gda_execution_client.gd",
        "test_gda_execution_client_discovery.gd",
        "test_combat_consecutive_revisions_live.gd",
        "test_combat_cast_controller_live.gd",
        "test_combat_cast_controller_failure.gd",
        "test_combat_cast_main_live.gd",
        "test_combat_cast_view.gd",
        "test_playtest.gd",
        "test_reward_run_controller_failure.gd",
        "test_reward_run_controller_live.gd",
        "test_reward_run_documents.gd",
        "test_reward_run_live_trials.gd",
        "test_reward_run_main_live.gd",
        "test_reward_run_view.gd",
    }
    assert {path.name for path in (_PLAYTEST / "tests").glob("test_*.gd")} == expected


def test_playtest_scripts_share_one_test_case_module():
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
