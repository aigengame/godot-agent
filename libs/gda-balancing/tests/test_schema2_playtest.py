import os
import re
from pathlib import Path


_SCHEMA2_EXAMPLES = Path(__file__).parents[1] / "examples" / "schema2"
_PLAYTEST = _SCHEMA2_EXAMPLES / "playtest"


def test_schema2_delivery_entries_share_maintained_authoring_sources():
    maintained_sources = {
        "roguelike-reward-build": {"model-source.json", "experiment.json"},
        "rpg-combat-cast": {
            "model-source.json",
            "experiment.json",
            "multi-time-experiment.json",
        },
        "rpg-periodic-effect": {
            "model-source.json",
            "experiment.json",
            "same-time-experiment.json",
        },
        "rpg-stat-composition": {"model-source.json", "experiment.json"},
        "structured-selection": {"model-source.json", "experiment.json"},
    }

    example_index = (_SCHEMA2_EXAMPLES / "README.md").read_text(encoding="utf-8")
    cli_index = (_SCHEMA2_EXAMPLES / "cli" / "README.md").read_text(encoding="utf-8")
    for example, filenames in maintained_sources.items():
        source_directory = _SCHEMA2_EXAMPLES / example
        assert source_directory.is_dir()
        assert filenames <= {path.name for path in source_directory.glob("*.json")}
        assert f"{example}/" in example_index
        assert f"../{example}/" in cli_index

    for delivery_directory in (_SCHEMA2_EXAMPLES / "cli", _PLAYTEST):
        copied_authorities = [
            path
            for path in delivery_directory.rglob("*.json")
            if path.name == "model-source.json" or "experiment" in path.name
        ]
        assert copied_authorities == []


def test_playtest_runtime_dependencies_point_downward():
    allowed_dependencies = {
        "addons": {"addons"},
        "apps": {"addons", "apps", "content", "systems", "ui"},
        "systems": {"systems"},
        "content": {"addons", "content", "systems"},
        "ui": {"content", "ui"},
    }
    dependency_pattern = re.compile(r"res://(addons|apps|systems|content|ui|tests)/")

    for owner, allowed in allowed_dependencies.items():
        for artifact in (_PLAYTEST / owner).rglob("*"):
            if artifact.suffix not in {".gd", ".tscn", ".tres"}:
                continue
            dependencies = set(dependency_pattern.findall(artifact.read_text()))
            assert dependencies <= allowed, (artifact, dependencies - allowed)

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
        _PLAYTEST / "ui" / "reward_run" / "localization" / "reward_run.zh_CN.tres"
    ).read_text(encoding="utf-8")
    assert '[&"", &"FREQUENCY_LABEL"]: [&"Rare reward frequency"]' in reward_english
    assert '[&"", &"FREQUENCY_LABEL"]: [&"稀有奖励出现频率"]' in reward_chinese
    assert (
        '[&"", &"COMBAT_APP_TITLE"]: [&"ARCANE DUEL"]'
        in (_PLAYTEST / "ui/combat_cast/localization/combat_cast.en.tres").read_text()
    )
    assert (
        '[&"", &"EFFECT_APP_TITLE"]: [&"诅咒时机"]'
        in (
            _PLAYTEST / "ui/periodic_effect/localization/periodic_effect.zh_CN.tres"
        ).read_text()
    )
    effect_english = (
        _PLAYTEST / "ui/periodic_effect/localization/periodic_effect.en.tres"
    ).read_text(encoding="utf-8")
    effect_chinese = (
        _PLAYTEST / "ui/periodic_effect/localization/periodic_effect.zh_CN.tres"
    ).read_text(encoding="utf-8")
    assert '[&"", &"EFFECT_DYNAMIC_NAME"]: [&"Dynamic Curse"]' in effect_english
    assert '[&"", &"EFFECT_FIXED_NAME"]: [&"Fixed Curse"]' in effect_english
    assert '[&"", &"EFFECT_DYNAMIC_NAME"]: [&"动态诅咒"]' in effect_chinese
    assert '[&"", &"EFFECT_FIXED_NAME"]: [&"定值诅咒"]' in effect_chinese
    assert (
        '[&"", &"EFFECT_FIXED_RULE"]: [&"This trial starts with a fresh target at '
        '%d Health. Damage is calculated once when cast; both pulses repeat it."]'
        in effect_english
    )
    assert (
        '[&"", &"EFFECT_FIXED_RULE"]: [&"本轮使用生命为 %d 的新目标。'
        '伤害只在施放时计算一次；两次脉冲都重复该伤害。"]' in effect_chinese
    )
    assert "Reactive Hex" not in effect_english
    assert "Locked Hex" not in effect_english
    assert "响应诅咒" not in effect_chinese
    assert "锁定诅咒" not in effect_chinese

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

    main = (_PLAYTEST / "apps" / "reward_run" / "main.gd").read_text(encoding="utf-8")
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

    maintained_documents = {
        "combat_cast/combat_cast_documents.gd": (
            "res://../rpg-combat-cast",
            "model-source.json",
            "experiment.json",
        ),
        "periodic_effect/periodic_effect_documents.gd": (
            "res://../rpg-periodic-effect",
            "model-source.json",
            "same-time-experiment.json",
        ),
        "stat_composition/stat_composition_documents.gd": (
            "res://../rpg-stat-composition",
            "model-source.json",
            "experiment.json",
        ),
    }
    for relative_path, expected_values in maintained_documents.items():
        source = (_PLAYTEST / "content" / relative_path).read_text(encoding="utf-8")
        for expected in expected_values:
            assert expected in source, (relative_path, expected)


def test_playtest_has_explicit_local_launch_actions_and_no_standalone_export_claim():
    launch_scenes = {
        "run_reward_run.sh": "res://apps/reward_run/main.tscn",
        "run_combat_cast.sh": "res://apps/combat_cast/main.tscn",
        "run_periodic_effect.sh": "res://apps/periodic_effect/main.tscn",
        "run_stat_composition.sh": "res://apps/stat_composition/main.tscn",
    }
    for filename, scene in launch_scenes.items():
        launch = _PLAYTEST / "scripts" / filename
        assert launch.is_file()
        assert launch.stat().st_mode & os.X_OK
        source = launch.read_text(encoding="utf-8")
        assert scene in source
        assert 'exec "$' in source
        assert "PyInstaller" not in source
    common = (_PLAYTEST / "scripts" / "run_playtest.sh").read_text(encoding="utf-8")
    assert "GDA_BALANCING_EXECUTABLE" in common
    assert "--gda-balancing-executable=" in common
    assert ".venv" not in common
    assert '"${arguments[@]}"' in common
    assert not (_PLAYTEST / "scripts" / "export_macos.sh").exists()
    assert not (_PLAYTEST / "scripts" / "smoke_export_macos.sh").exists()
    assert not (_PLAYTEST / "export_presets.cfg").exists()


def test_each_playtest_has_an_explicit_thin_application_entry():
    assert not (_PLAYTEST / "main.gd").exists()
    assert not (_PLAYTEST / "main.tscn").exists()
    app_modules = {
        "reward_run": ("RewardRunController", "RewardRun"),
        "combat_cast": ("CombatCastController", "CombatDuel"),
        "periodic_effect": ("PeriodicEffectController", "PeriodicEffectTimeline"),
        "stat_composition": ("StatCompositionController", None),
    }
    assert {path.name for path in (_PLAYTEST / "apps").iterdir()} == set(app_modules)
    for app_name, (controller_name, system_name) in app_modules.items():
        app = _PLAYTEST / "apps" / app_name
        assert (app / "main.gd").is_file()
        assert (app / "main.tscn").is_file()
        source = (app / "main.gd").read_text(encoding="utf-8")
        assert "GdaExecutionClient" in source
        assert controller_name in source
        if system_name is None:
            assert "res://systems/" not in source
        else:
            assert system_name in source
            assert "res://systems/" in source
        assert 'preload("res://ui/' not in source
        assert "model-source.json" not in source
        assert "experiment.json" not in source


def test_playtest_hides_protocol_and_authority_details_from_gameplay_layers():
    forbidden = re.compile(
        r"\b(kernel|ldb|experiment|formula|artifact|identity|http|session|revision|diagnostic|provenance)\b",
        re.IGNORECASE,
    )
    for layer in ["systems", "ui"]:
        for script in (_PLAYTEST / layer).rglob("*.gd"):
            assert forbidden.search(script.read_text(encoding="utf-8")) is None, script


def test_playtest_common_modules_have_multiple_real_app_consumers():
    app_sources = [path.read_text() for path in (_PLAYTEST / "apps").glob("*/main.gd")]
    controller_sources = [
        path.read_text() for path in (_PLAYTEST / "content").glob("*/*_controller.gd")
    ]
    assert sum("GdaExecutionClient" in source for source in app_sources) == 4
    assert sum("PlaytestFeedbackFile" in source for source in controller_sources) == 4
    assert (
        sum(
            "run_playtest.sh" in path.read_text()
            for path in (_PLAYTEST / "scripts").glob("run_*.sh")
        )
        == 4
    )
    client = (
        _PLAYTEST / "addons/gda_balancing_client/gda_execution_client.gd"
    ).read_text()
    assert re.search(r"\b(reward|combat|effect)\b", client, re.IGNORECASE) is None
    shell = (_PLAYTEST / "ui/playtest_shell.gd").read_text()
    assert 'DisplayServer.clipboard_set(JSON.stringify(payload, "\\t"))' in shell
    assert "ProjectSettings.globalize_path(path)" in shell


def test_playtest_documentation_covers_each_player_and_maintainer_path():
    overview = (_PLAYTEST / "README.md").read_text(encoding="utf-8")
    maintained_examples = {
        "roguelike-reward-build": (
            "run_reward_run.sh",
            "test_reward_run_main_live.gd",
            "model-source.json",
            "experiment.json",
        ),
        "rpg-combat-cast": (
            "run_combat_cast.sh",
            "test_combat_cast_main_live.gd",
            "model-source.json",
            "experiment.json",
        ),
        "rpg-periodic-effect": (
            "run_periodic_effect.sh",
            "test_periodic_effect_main_live.gd",
            "model-source.json",
            "same-time-experiment.json",
        ),
        "rpg-stat-composition": (
            "run_stat_composition.sh",
            "test_stat_composition_main_live.gd",
            "model-source.json",
            "experiment.json",
        ),
    }
    for example, required_terms in maintained_examples.items():
        tutorial = (_PLAYTEST.parent / example / "README.md").read_text(
            encoding="utf-8"
        )
        for required in required_terms:
            assert required in overview, ("overview", required)
            assert required in tutorial, (example, required)
        assert "opaque maintainer provenance" in " ".join(tutorial.split())


def test_playtest_keeps_focused_runtime_behavior_proofs():
    required = {
        "test_gda_execution_client.gd",
        "test_gda_execution_client_discovery.gd",
        "test_periodic_effect_live_trials.gd",
        "test_periodic_effect_controller_live.gd",
        "test_periodic_effect_controller_failure.gd",
        "test_periodic_effect_main_live.gd",
        "test_periodic_effect_view.gd",
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
        "test_stat_composition_controller_failure.gd",
        "test_stat_composition_controller_live.gd",
        "test_stat_composition_documents.gd",
        "test_stat_composition_main_live.gd",
        "test_stat_composition_view.gd",
    }
    actual = {path.name for path in (_PLAYTEST / "tests").glob("test_*.gd")}
    assert required <= actual


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
