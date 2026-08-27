"""The e2e tier — the CLI as real subprocesses.

Family convention (gda's ``test_e2e_*`` naming): end-to-end tests live in
their own module. Unlike gda's engine-backed e2e, this tier has no external
dependency and runs fast, so it stays in the standard CI job — no marker
gating.

Two claims, both unprovable in-process:

* **Packaging** — the installed console script and ``python -m`` entry agree
  and separate their streams (the claim #502 exists to prove).
* **Key user path** (RULES DoD: automated e2e on the path an agent actually
  drives) — migrate authored 1.x source, build the resulting 2.x Model Source,
  get typed migration refusals, and read the self-description; through the
  installed entry point, OS argv/streams, and real files. The in-process
  conformance rows prove the behavior; these prove the same commands survive
  the process boundary.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema

from gda_balancing.interfaces.cli.envelope import ERROR_ENVELOPE_SCHEMA
from rpg_combat_test_support import (
    combat_action_assignment_names,
    one_action_experiment,
)

_RPG_COMBAT_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "schema2" / "rpg-combat-cast"
)
_RPG_PERIODIC_EFFECT_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "schema2" / "rpg-periodic-effect"
)
_ROGUELIKE_REWARD_BUILD_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "schema2" / "roguelike-reward-build"
)
_RPG_STAT_COMPOSITION_EXAMPLE = (
    Path(__file__).parents[1] / "examples" / "schema2" / "rpg-stat-composition"
)


def _console_script() -> str:
    script = shutil.which("gda-balancing")
    assert script is not None, (
        "console script `gda-balancing` not on PATH — this package is its own "
        "uv project, so run the suite from its environment: "
        "`uv run --project libs/gda-balancing pytest libs/gda-balancing/tests` "
        "(the entry point is what this e2e tier exists to prove)"
    )
    return script


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_console_script(), *argv], capture_output=True, text=True)


def test_experiment_run_descriptor_defers_operation_refusal_catalog_at_import():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                (
                    "import json",
                    "import gda_balancing.domain.model",
                    "import gda_balancing.domain.authority.context as authority",
                    "original = authority.packaged_authority_context",
                    "calls = {'count': 0}",
                    "def observed():",
                    "    calls['count'] += 1",
                    "    return original()",
                    "authority.packaged_authority_context = observed",
                    "from gda_balancing.interfaces.cli.experiment_run import EXPERIMENT_RUN",
                    "print(json.dumps({'operation_catalog_calls': calls['count'], 'deferred': EXPERIMENT_RUN.refusal_catalog_provider is not None}))",
                )
            ),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed == {
        "operation_catalog_calls": 0,
        "deferred": True,
    }


def _receipt_members(receipt: dict) -> dict[str, Path]:
    return {
        row["logical_name"]: Path(row["locator"]) for row in receipt["member_locators"]
    }


def _run_experiment_variant(
    tmp_path: Path,
    experiment: dict,
    *,
    name: str,
    invocation_key: str,
) -> tuple[dict, dict]:
    specification_path = tmp_path / f"{name}.json"
    specification_path.write_text(json.dumps(experiment), encoding="utf-8")
    result = _run(
        "experiment",
        "run",
        str(specification_path),
        "--out",
        str(tmp_path / name),
        "--invocation-key",
        invocation_key,
    )
    assert (result.returncode, result.stderr) == (0, ""), result.stdout
    receipt = json.loads(result.stdout)
    trace = json.loads(
        _receipt_members(receipt)["event-trace"].read_text(encoding="utf-8")
    )
    return receipt, trace


def _bind_experiment_to_build(experiment: dict, receipt: dict) -> None:
    build_record = json.loads(
        _receipt_members(receipt)["build-receipt"].read_text(encoding="utf-8")
    )
    experiment["kernel_identity"] = build_record["kernel_identity"]
    experiment["language_bundle_identity"] = build_record["language_bundle_identity"]
    experiment["model"] = {
        "source_identity": build_record["source_identity"],
        "build_receipt_identity": build_record["content_identity"],
        "resolved_model_identity": build_record["resolved_model_identity"],
        "package_lock_identity": build_record["package_lock_identity"],
        "rir_identity": build_record["rir_identity"],
    }


def _build_reciprocal_example(
    tmp_path: Path,
    *,
    invocation_key: str,
    output_name: str = "reciprocal-model",
) -> tuple[Path, dict]:
    result = _run(
        "model",
        "build",
        str(_RPG_COMBAT_EXAMPLE / "model-source.json"),
        "--out",
        str(tmp_path / output_name),
        "--invocation-key",
        invocation_key,
    )
    assert (result.returncode, result.stderr) == (0, ""), result.stdout
    return _RPG_COMBAT_EXAMPLE, json.loads(result.stdout)


def _build_periodic_effect_example(
    tmp_path: Path,
    *,
    invocation_key: str,
    output_name: str = "periodic-model",
) -> dict:
    result = _run(
        "model",
        "build",
        str(_RPG_PERIODIC_EFFECT_EXAMPLE / "model-source.json"),
        "--out",
        str(tmp_path / output_name),
        "--invocation-key",
        invocation_key,
    )
    assert (result.returncode, result.stderr) == (0, ""), result.stdout
    return json.loads(result.stdout)


def _one_way_variant(baseline: dict, identifier: str) -> dict:
    return one_action_experiment(
        baseline,
        identifier,
        root_event_ref="player-attacks-enemy",
    )


class TestEntryPoints:
    def test_both_entry_points_agree_on_the_valid_row(self):
        console = _run("version")
        module = subprocess.run(
            [sys.executable, "-m", "gda_balancing", "version"],
            capture_output=True,
            text=True,
        )
        assert (console.returncode, console.stderr) == (0, "")
        assert (module.returncode, module.stderr) == (0, "")
        assert console.stdout == module.stdout
        json.loads(console.stdout)

    def test_stream_separation_end_to_end(self):
        result = _run()
        assert (result.returncode, result.stdout) == (3, "")
        payload = json.loads(result.stderr)
        jsonschema.validate(payload, ERROR_ENVELOPE_SCHEMA)
        assert payload["error"]["category"] == "usage"
        assert payload["error"]["code"] == "missing_command"


class TestKeyUserPath:
    def test_migrate_then_build_key_path(self, tmp_path):
        legacy = tmp_path / "legacy.json"
        legacy.write_text(
            '{"schema_version":"1.0.0","meta":{"name":"e2e.migration"},'
            '"parameters":{"health":100}}',
            encoding="utf-8",
        )
        migrated = tmp_path / "migrated.json"

        conversion = _run(
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(migrated),
            "--invocation-key",
            "1" * 64,
        )

        assert (conversion.returncode, conversion.stderr) == (0, "")
        receipt = json.loads(conversion.stdout)
        assert [item["logical_name"] for item in receipt["member_locators"]] == [
            "migration-report",
            "model-source-package",
        ]
        assert (
            json.loads(migrated.read_text(encoding="utf-8"))["schema_version"]
            == "2.0.0"
        )

        built = _run(
            "model",
            "build",
            str(migrated),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "2" * 64,
        )
        assert (built.returncode, built.stderr) == (0, "")

    def test_migration_refusal_key_path(self, tmp_path):
        legacy = tmp_path / "legacy-lossy.json"
        legacy.write_text(
            '{"schema_version":"1.0.0","meta":{"name":"e2e.refusal"},'
            '"parameters":{"health":1.5}}',
            encoding="utf-8",
        )
        output = tmp_path / "must-not-exist.json"

        result = _run(
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(output),
            "--invocation-key",
            "3" * 64,
        )

        assert (result.returncode, result.stderr) == (2, "")
        payload = json.loads(result.stdout)
        schema = json.loads(_run("model", "migrate", "--schema").stdout)["error"]
        jsonschema.validate(payload, schema)
        assert payload["error"]["category"] == "refusal"
        assert payload["error"]["stage"] == "migration"
        assert [item["code"] for item in payload["error"]["diagnostics"]] == [
            "migration.deprecated_construct"
        ]
        assert payload["error"]["migration_report"]["status"] == "refused"
        assert output.exists() is False

    def test_formula_model_build_then_inspect_key_path(self, tmp_path):
        source = (
            Path(__file__).parents[1]
            / "examples"
            / "schema2"
            / "rpg-combat-cast"
            / "model-source.json"
        )
        built = _run(
            "model",
            "build",
            str(source),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "4" * 64,
        )
        assert (built.returncode, built.stderr) == (0, "")
        receipt = tmp_path / "build-receipt.json"
        receipt.write_text(built.stdout, encoding="utf-8")

        inspected = _run(
            "model",
            "inspect",
            str(receipt),
            "--format",
            "indented",
        )

        assert (inspected.returncode, inspected.stderr) == (0, "")
        explanation = json.loads(inspected.stdout)
        assert {row["id"] for row in explanation["formula_explanations"]} == {
            "effective-accuracy",
            "mitigated-damage",
        }
        assert "game.combat.cast-v1" in {
            row["id"] for row in explanation["operation_explanations"]
        }

    def test_roguelike_reward_build_key_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        source_path = _ROGUELIKE_REWARD_BUILD_EXAMPLE / "model-source.json"
        checked = _run("model", "check", str(source_path))
        assert (checked.returncode, checked.stderr) == (0, ""), checked.stdout

        built = _run(
            "model",
            "build",
            str(source_path),
            "--out",
            str(tmp_path / "roguelike-model"),
            "--invocation-key",
            "5" * 64,
        )
        assert (built.returncode, built.stderr) == (0, ""), built.stdout
        receipt_path = tmp_path / "roguelike-model-set-receipt.json"
        receipt_path.write_text(built.stdout, encoding="utf-8")

        inspected = _run(
            "model",
            "inspect",
            str(receipt_path),
            "--format",
            "indented",
        )
        assert (inspected.returncode, inspected.stderr) == (0, ""), inspected.stdout
        explanation = json.loads(inspected.stdout)
        assert {row["id"] for row in explanation["formula_explanations"]} == {
            "rare-threshold"
        }
        assert {row["id"] for row in explanation["operation_explanations"]} == {
            "game.generation.select-reward-v1",
            "game.build.replace-reward-v1",
            "quantity.floor-zero",
            "quantity.identity",
            "quantity.less-than",
            "quantity.maximum",
            "quantity.subtract",
        }

        checked_in_experiment_path = _ROGUELIKE_REWARD_BUILD_EXAMPLE / "experiment.json"
        checked_experiment = _run(
            "experiment", "check", str(checked_in_experiment_path)
        )
        assert (checked_experiment.returncode, checked_experiment.stderr) == (
            0,
            "",
        ), checked_experiment.stdout
        experiment = json.loads(checked_in_experiment_path.read_text(encoding="utf-8"))

        baseline_receipt, baseline_trace = _run_experiment_variant(
            tmp_path,
            experiment,
            name="roguelike-baseline",
            invocation_key="6" * 64,
        )
        baseline_metrics = json.loads(
            _receipt_members(baseline_receipt)["metric-dataset"].read_text(
                encoding="utf-8"
            )
        )
        baseline_receipt_path = tmp_path / "roguelike-baseline-set-receipt.json"
        baseline_receipt_path.write_text(json.dumps(baseline_receipt), encoding="utf-8")
        replay_comparison_path = tmp_path / "roguelike-replay-comparison.json"
        replayed = _run(
            "experiment",
            "replay",
            str(checked_in_experiment_path),
            "--original-experiment-run-artifact-set-receipt",
            str(baseline_receipt_path),
            "--out",
            str(replay_comparison_path),
            "--invocation-key",
            "8" * 64,
        )
        assert (replayed.returncode, replayed.stderr) == (0, ""), replayed.stdout
        assert json.loads(replayed.stdout)["claim_state"] == "candidate"
        assert (
            json.loads(replay_comparison_path.read_text(encoding="utf-8"))["result"]
            == "matched"
        )

        tuned = json.loads(json.dumps(experiment))
        tuned["id"] = "roguelike.reward-build-feedback.lower-rare-weight"
        next(
            row
            for row in tuned["scenarios"][0]["assignments"]
            if row["target"]["name"] == "rare_weight"
        )["value"] = 2
        tuned_path = tmp_path / "roguelike-tuned.json"
        tuned_path.write_text(json.dumps(tuned), encoding="utf-8")
        checked_tuned = _run("experiment", "check", str(tuned_path))
        assert (checked_tuned.returncode, checked_tuned.stderr) == (
            0,
            "",
        ), checked_tuned.stdout
        tuned_receipt, tuned_trace = _run_experiment_variant(
            tmp_path,
            tuned,
            name="roguelike-tuned",
            invocation_key="7" * 64,
        )
        tuned_metrics = json.loads(
            _receipt_members(tuned_receipt)["metric-dataset"].read_text(
                encoding="utf-8"
            )
        )

        baseline_events = [
            event for event in baseline_trace["events"] if event["operation"]
        ]
        tuned_events = [event for event in tuned_trace["events"] if event["operation"]]
        assert [event["operation"] for event in baseline_events] == [
            "game.generation.select-reward-v1",
            "game.build.replace-reward-v1",
        ]
        assert [event["outcome"] for event in baseline_events] == [
            {"id": "selected", "kind": "success"},
            {"id": "replaced", "kind": "success"},
        ]
        assert [event["outcome"] for event in tuned_events] == [
            {"id": "selected", "kind": "success"},
            {"id": "replaced", "kind": "success"},
        ]

        def reward_result(events: list[dict]) -> dict:
            reward_fact = next(
                row for row in events[0]["facts"] if row["name"] == "reward_result"
            )
            typed_reward = reward_fact["value"]
            return typed_reward["value"]

        assert reward_result(baseline_events)["selected"] == {"key": "volatile_crown"}
        assert reward_result(tuned_events)["selected"] == {"key": "steady_guard"}
        assert baseline_events[0]["rng_draws"] == tuned_events[0]["rng_draws"]
        assert baseline_events[0]["rng_draws"][0]["value"] == 3
        assert {row["metric"]: row["value"] for row in baseline_metrics["samples"]} == {
            "build_score": 90,
            "reward_score": 80,
        }
        assert {row["metric"]: row["value"] for row in tuned_metrics["samples"]} == {
            "build_score": 30,
            "reward_score": 20,
        }
        assert (
            baseline_trace["experiment_identity"] != tuned_trace["experiment_identity"]
        )

    def test_rpg_combat_model_exposes_two_directional_cast_entrypoints(self, tmp_path):
        _example, receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="5" * 64,
        )
        rir_path = next(
            Path(row["locator"])
            for row in receipt["member_locators"]
            if row["logical_name"] == "rir-semantic-payload"
        )
        rir = json.loads(rir_path.read_text(encoding="utf-8"))
        entrypoints = {row["id"]: row["operation"] for row in rir["entrypoints"]}

        assert entrypoints == {
            "combat.enemy-attacks-player": {
                "package": "game.combat",
                "version": "2.1.0",
                "id": "game.combat.eligible-cast-v1",
            },
            "combat.enemy-attacks-player-without-eligibility": {
                "package": "game.combat",
                "version": "2.1.0",
                "id": "game.combat.cast-v1",
            },
            "combat.player-attacks-enemy-and-cancels-counterattack": {
                "package": "game.combat",
                "version": "2.1.0",
                "id": "game.combat.cast-and-cancel-v1",
            },
            "combat.player-attacks-enemy": {
                "package": "game.combat",
                "version": "2.1.0",
                "id": "game.combat.eligible-cast-v1",
            },
            "combat.player-attacks-enemy-without-eligibility": {
                "package": "game.combat",
                "version": "2.1.0",
                "id": "game.combat.cast-v1",
            },
            "combat.player-plans-attacks": {
                "package": "game.combat",
                "version": "2.1.0",
                "id": "game.combat.plan-casts-v1",
            },
        }
        directional_bindings = {
            row["id"]: {
                argument["port"]["name"]: argument["operand"]["symbol"]["name"]
                for argument in row["arguments"]
                if argument["operand"]["kind"] == "symbol"
            }
            for row in rir["entrypoints"]
        }
        assert directional_bindings == {
            "combat.enemy-attacks-player": {
                "actor_health": "enemy_health",
                "actor_resource": "enemy_mana",
                "action_cost": "enemy_action_cost",
                "accuracy": "enemy_effective_accuracy",
                "base_damage": "enemy_base_damage",
                "critical_threshold": "enemy_critical_threshold",
                "hit_defense": "player_defense",
                "damage_mitigation": "player_defense",
                "defeat_threshold": "defeat_threshold",
                "target_health": "player_health",
            },
            "combat.enemy-attacks-player-without-eligibility": {
                "actor_resource": "enemy_mana",
                "action_cost": "enemy_action_cost",
                "accuracy": "enemy_effective_accuracy",
                "base_damage": "enemy_base_damage",
                "critical_threshold": "enemy_critical_threshold",
                "hit_defense": "player_defense",
                "damage_mitigation": "player_defense",
                "target_health": "player_health",
            },
            "combat.player-attacks-enemy-and-cancels-counterattack": {
                "actor_resource": "player_mana",
                "action_cost": "player_action_cost",
                "accuracy": "player_effective_accuracy",
                "base_damage": "player_base_damage",
                "critical_threshold": "player_critical_threshold",
                "hit_defense": "enemy_defense",
                "damage_mitigation": "enemy_defense",
                "target_health": "enemy_health",
            },
            "combat.player-attacks-enemy": {
                "actor_health": "player_health",
                "actor_resource": "player_mana",
                "action_cost": "player_action_cost",
                "accuracy": "player_effective_accuracy",
                "base_damage": "player_base_damage",
                "critical_threshold": "player_critical_threshold",
                "hit_defense": "enemy_defense",
                "damage_mitigation": "enemy_defense",
                "defeat_threshold": "defeat_threshold",
                "target_health": "enemy_health",
            },
            "combat.player-attacks-enemy-without-eligibility": {
                "actor_resource": "player_mana",
                "action_cost": "player_action_cost",
                "accuracy": "player_effective_accuracy",
                "base_damage": "player_base_damage",
                "critical_threshold": "player_critical_threshold",
                "hit_defense": "enemy_defense",
                "damage_mitigation": "enemy_defense",
                "target_health": "enemy_health",
            },
            "combat.player-plans-attacks": {
                "actor_resource": "player_mana",
                "action_cost": "player_action_cost",
                "accuracy": "player_effective_accuracy",
                "base_damage": "player_base_damage",
                "critical_threshold": "player_critical_threshold",
                "hit_defense": "enemy_defense",
                "damage_mitigation": "enemy_defense",
                "target_health": "enemy_health",
            },
        }
        cancel_entrypoint = next(
            row
            for row in rir["entrypoints"]
            if row["id"] == "combat.player-attacks-enemy-and-cancels-counterattack"
        )
        cancel_operand = next(
            row
            for row in cancel_entrypoint["arguments"]
            if row["port"]["name"] == "cancel_target"
        )["operand"]
        assert cancel_operand == {
            "kind": "event-reference",
            "name": "counterattack",
            "identity": cancel_operand["identity"],
        }
        assert cancel_operand["identity"].startswith("sha256:")
        derived_formula_bindings = {
            row["site"]["resolved_symbol"]["name"]: row["formula"]["identity"]
            for row in rir["formula_bindings"]
            if row["site"]["kind"] == "derived-symbol"
        }
        assert {
            "player_effective_accuracy",
            "enemy_effective_accuracy",
        } <= derived_formula_bindings.keys()
        assert len(set(derived_formula_bindings.values())) == 1
        explanation = json.loads(
            _receipt_members(receipt)["model-explanation"].read_text(encoding="utf-8")
        )
        accuracy_explanation = next(
            row
            for row in explanation["formula_explanations"]
            if row["id"] == "effective-accuracy"
        )
        assert {
            operand["operand"]["resolved_symbol"]["name"]
            for site in accuracy_explanation["evaluation_sites"]
            for operand in site["operands"]
            if operand["operand"]["kind"] == "symbol"
        } == {"enemy_accuracy", "player_accuracy"}

    def test_rpg_combat_keeps_external_input_and_multi_time_scheduling_public(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="6" * 64,
        )
        companion = json.loads(
            (example / "multi-time-experiment.json").read_text(encoding="utf-8")
        )

        receipt, trace = _run_experiment_variant(
            tmp_path,
            companion,
            name="multi-time-companion",
            invocation_key="7" * 64,
        )

        assert [row["root_event_ref"] for row in trace["root_event_map"]] == [
            "raise-enemy-defense",
            "plan-player-casts",
            "retry-player-cast",
        ]
        assert [
            (
                event.get("root_event_ref"),
                event["ordering_key"]["logical_time"],
                event["ordering_key"]["phase"],
            )
            for event in trace["events"]
            if event["ordering_key"]["phase"] != "observation"
        ] == [
            ("raise-enemy-defense", 0, "input"),
            ("plan-player-casts", 0, "transition"),
            (None, 1, "transition"),
            ("retry-player-cast", 2, "transition"),
        ]
        planner = trace["events"][1]
        assert planner["outcome"] == {"id": "planned", "kind": "success"}
        assert planner["cancellations"][0]["outcome"] == "canceled"
        snapshots = json.loads(
            _receipt_members(receipt)["snapshot-series"].read_text(encoding="utf-8")
        )["snapshots"]
        assert len(snapshots) == len(trace["events"]) + 1

    def test_periodic_effect_runs_one_complete_lifecycle_through_public_events(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        build_receipt = _build_periodic_effect_example(
            tmp_path,
            invocation_key="8" * 64,
        )
        experiment = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "experiment.json").read_text(
                encoding="utf-8"
            )
        )
        build_record = json.loads(
            _receipt_members(build_receipt)["build-receipt"].read_text(encoding="utf-8")
        )
        assert {
            "kernel_identity": experiment["kernel_identity"],
            "language_bundle_identity": experiment["language_bundle_identity"],
            **experiment["model"],
        } == {
            "kernel_identity": build_record["kernel_identity"],
            "language_bundle_identity": build_record["language_bundle_identity"],
            "source_identity": build_record["source_identity"],
            "build_receipt_identity": build_record["content_identity"],
            "resolved_model_identity": build_record["resolved_model_identity"],
            "package_lock_identity": build_record["package_lock_identity"],
            "rir_identity": build_record["rir_identity"],
        }

        receipt, trace = _run_experiment_variant(
            tmp_path,
            experiment,
            name="periodic-effect",
            invocation_key="9" * 64,
        )

        lifecycle = [
            (
                event["entrypoint"]["id"]
                if event.get("entrypoint") is not None
                else event["operation"],
                event["ordering_key"]["logical_time"],
            )
            for event in trace["events"]
            if event["ordering_key"]["phase"] == "transition"
            and event["operation"].startswith("game.effect.")
        ]
        assert lifecycle == [
            ("effect.apply-snapshot-periodic", 0),
            ("game.effect.tick-snapshot-periodic-v1", 1),
            ("game.effect.tick-snapshot-periodic-v1", 2),
            ("game.effect.expire-periodic-v1", 3),
        ]
        instance_ids = {
            next(
                row["value"]
                for row in event["state_after"]
                if row["name"] == "effect_instance_id"
            )
            for event in trace["events"]
            if event["ordering_key"]["phase"] == "transition"
        }
        assert len(instance_ids) == 1
        assert next(iter(instance_ids)) > 0
        snapshots = json.loads(
            _receipt_members(receipt)["snapshot-series"].read_text(encoding="utf-8")
        )["snapshots"]
        assert len(snapshots) == len(trace["events"]) + 1

    def test_stat_composition_runs_the_golden_attack_and_replays_exactly(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        built = _run(
            "model",
            "build",
            str(_RPG_STAT_COMPOSITION_EXAMPLE / "model-source.json"),
            "--out",
            str(tmp_path / "stat-composition-model"),
            "--invocation-key",
            "1" * 64,
        )
        assert (built.returncode, built.stderr) == (0, ""), built.stdout
        build_receipt = json.loads(built.stdout)
        build_receipt_path = tmp_path / "stat-composition-model-set-receipt.json"
        build_receipt_path.write_text(json.dumps(build_receipt), encoding="utf-8")
        experiment = json.loads(
            (_RPG_STAT_COMPOSITION_EXAMPLE / "experiment.json").read_text(
                encoding="utf-8"
            )
        )
        build_record = json.loads(
            _receipt_members(build_receipt)["build-receipt"].read_text(encoding="utf-8")
        )
        assert {
            "kernel_identity": experiment["kernel_identity"],
            "language_bundle_identity": experiment["language_bundle_identity"],
            **experiment["model"],
        } == {
            "kernel_identity": build_record["kernel_identity"],
            "language_bundle_identity": build_record["language_bundle_identity"],
            "source_identity": build_record["source_identity"],
            "build_receipt_identity": build_record["content_identity"],
            "resolved_model_identity": build_record["resolved_model_identity"],
            "package_lock_identity": build_record["package_lock_identity"],
            "rir_identity": build_record["rir_identity"],
        }
        assert experiment["runtime"]["required_evaluator"]["rng_algorithms"] == [
            "splitmix64-v1"
        ]
        assert experiment["scenarios"][0]["named_streams"] == []

        receipts = []
        traces = []
        for name, key in (("golden-first", "2" * 64), ("golden-replay", "3" * 64)):
            receipt, trace = _run_experiment_variant(
                tmp_path,
                experiment,
                name=name,
                invocation_key=key,
            )
            receipts.append(receipt)
            traces.append(trace)

        assert traces[0] == traces[1]
        members = _receipt_members(receipts[0])
        dataset = json.loads(members["metric-dataset"].read_text(encoding="utf-8"))
        evaluation_run = json.loads(
            members["evaluation-run"].read_text(encoding="utf-8")
        )
        assert {sample["metric"]: sample["value"] for sample in dataset["samples"]} == {
            "attack_damage": 50,
            "build_damage": 8,
            "damage_dealt": 50,
            "effect_damage": 10,
            "pre_buff_damage": 40,
            "progression_damage": 12,
            "target_health": 70,
        }
        assert all(sample["within_target"] for sample in dataset["samples"])

        run_receipt_path = tmp_path / "golden-first-set-receipt.json"
        run_receipt_path.write_text(json.dumps(receipts[0]), encoding="utf-8")
        verified = _run(
            "evidence",
            "verify",
            "--claim-kind",
            "evaluable",
            "--source",
            str(_RPG_STAT_COMPOSITION_EXAMPLE / "model-source.json"),
            "--specification",
            str(tmp_path / "golden-first.json"),
            "--model-build-artifact-set-receipt",
            str(build_receipt_path),
            "--experiment-run-artifact-set-receipt",
            str(run_receipt_path),
        )
        assert (verified.returncode, verified.stderr) == (0, ""), verified.stdout
        candidate = json.loads(verified.stdout)
        assert candidate["claim_kind"] == "evaluable"
        assert candidate["claim_state"] == "candidate"
        assert candidate["producing_outcome"] == "success"
        assert candidate["model_source_identity"] == build_record["source_identity"]
        assert candidate["experiment_identity"] == evaluation_run["experiment_identity"]
        assert (
            candidate["model_build_artifact_set_receipt_identity"]
            == (build_receipt["content_identity"])
        )
        assert (
            candidate["experiment_run_artifact_set_receipt_identity"]
            == (receipts[0]["content_identity"])
        )

    def test_stat_composition_boundary_vectors_use_the_shared_experiment(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        built = _run(
            "model",
            "build",
            str(_RPG_STAT_COMPOSITION_EXAMPLE / "model-source.json"),
            "--out",
            str(tmp_path / "stat-composition-model"),
            "--invocation-key",
            "4" * 64,
        )
        assert (built.returncode, built.stderr) == (0, ""), built.stdout
        baseline = json.loads(
            (_RPG_STAT_COMPOSITION_EXAMPLE / "experiment.json").read_text(
                encoding="utf-8"
            )
        )
        _bind_experiment_to_build(baseline, json.loads(built.stdout))
        vectors = (
            (
                "rpg.stat.round-down-boundary-v1",
                10,
                {
                    "attack_damage": 52,
                    "build_damage": 10,
                    "damage_dealt": 52,
                    "effect_damage": 10,
                    "pre_buff_damage": 42,
                    "progression_damage": 12,
                    "target_health": 68,
                },
            ),
            (
                "rpg.stat.cap-exact-boundary-v1",
                16,
                {
                    "attack_damage": 60,
                    "build_damage": 16,
                    "damage_dealt": 60,
                    "effect_damage": 12,
                    "pre_buff_damage": 48,
                    "progression_damage": 12,
                    "target_health": 60,
                },
            ),
            (
                "rpg.stat.cap-clamped-boundary-v1",
                18,
                {
                    "attack_damage": 60,
                    "build_damage": 18,
                    "damage_dealt": 60,
                    "effect_damage": 12,
                    "pre_buff_damage": 50,
                    "progression_damage": 12,
                    "target_health": 60,
                },
            ),
        )

        for index, (vector_id, weapon_bonus, expected) in enumerate(vectors, start=5):
            experiment = json.loads(json.dumps(baseline))
            experiment["id"] = vector_id
            scenario = experiment["scenarios"][0]
            next(
                row
                for row in scenario["assignments"]
                if row["target"]["name"] == "weapon_damage_bonus"
            )["value"] = weapon_bonus
            for metric in experiment["metrics"]:
                value = expected[metric["id"]]
                metric["target"] = {"minimum": value, "maximum": value}
            receipt, _trace = _run_experiment_variant(
                tmp_path,
                experiment,
                name=vector_id,
                invocation_key=str(index) * 64,
            )
            dataset = json.loads(
                _receipt_members(receipt)["metric-dataset"].read_text(encoding="utf-8")
            )
            assert {
                sample["metric"]: sample["value"] for sample in dataset["samples"]
            } == expected, vector_id
            assert all(sample["within_target"] for sample in dataset["samples"]), (
                vector_id
            )

    def test_periodic_effect_snapshot_and_live_policies_observe_same_time_order(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        build_receipt = _build_periodic_effect_example(
            tmp_path,
            invocation_key="a" * 64,
            output_name="periodic-policy-model",
        )
        baseline = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "same-time-experiment.json").read_text(
                encoding="utf-8"
            )
        )
        build_record = json.loads(
            _receipt_members(build_receipt)["build-receipt"].read_text(encoding="utf-8")
        )
        assert baseline["model"] == {
            "source_identity": build_record["source_identity"],
            "build_receipt_identity": build_record["content_identity"],
            "resolved_model_identity": build_record["resolved_model_identity"],
            "package_lock_identity": build_record["package_lock_identity"],
            "rir_identity": build_record["rir_identity"],
        }

        def run_policy(
            *, policy: str, combat_priority: int, name: str, key: str
        ) -> tuple[dict, dict]:
            experiment = json.loads(json.dumps(baseline))
            experiment["id"] = f"example.rpg-periodic-effect.{name}"
            experiment["scenarios"][0]["event_plan"][0]["entrypoint"] = (
                f"effect.apply-{policy}-periodic"
            )
            experiment["scenarios"][0]["event_plan"][1]["priority"] = combat_priority
            return _run_experiment_variant(
                tmp_path,
                experiment,
                name=name,
                invocation_key=key,
            )

        live_receipt, live_combat_first = run_policy(
            policy="live",
            combat_priority=0,
            name="live-combat-first",
            key="b" * 64,
        )
        live_tick_first_receipt, live_tick_first = run_policy(
            policy="live",
            combat_priority=-1,
            name="live-tick-first",
            key="c" * 64,
        )
        _snapshot_receipt, snapshot_combat_first = run_policy(
            policy="snapshot",
            combat_priority=0,
            name="snapshot-combat-first",
            key="d" * 64,
        )
        _snapshot_tick_first_receipt, snapshot_tick_first = run_policy(
            policy="snapshot",
            combat_priority=-1,
            name="snapshot-tick-first",
            key="e" * 64,
        )

        def time_one_operations(trace: dict) -> list[str]:
            return [
                event["operation"]
                for event in trace["events"]
                if event["ordering_key"]["phase"] == "transition"
                and event["ordering_key"]["logical_time"] == 1
            ]

        assert time_one_operations(live_combat_first) == [
            "game.combat.cast-v1",
            "game.effect.tick-live-periodic-v1",
        ]
        assert time_one_operations(live_tick_first) == [
            "game.effect.tick-live-periodic-v1",
            "game.combat.cast-v1",
        ]

        def terminal_health(trace: dict) -> int:
            expiry = next(
                event
                for event in trace["events"]
                if event["operation"] == "game.effect.expire-periodic-v1"
            )
            return next(
                row["value"]
                for row in expiry["state_after"]
                if row["name"] == "target_health"
            )

        assert terminal_health(live_combat_first) == 85
        assert terminal_health(live_tick_first) == 75
        assert terminal_health(snapshot_combat_first) == 60
        assert terminal_health(snapshot_tick_first) == 60

        def effect_formula_evaluations(trace: dict) -> list[dict]:
            return [
                evaluation
                for event in trace["events"]
                for evaluation in event["formula_evaluations"]
                if evaluation["operation"]["package"] == "game.effect"
            ]

        live_combat_evaluations = effect_formula_evaluations(live_combat_first)
        live_tick_evaluations = effect_formula_evaluations(live_tick_first)
        assert [
            (
                evaluation["operation"]["id"],
                {
                    argument["parameter"]: argument["value"]
                    for argument in evaluation["arguments"]
                },
                evaluation["result"],
            )
            for evaluation in live_combat_evaluations
        ] == [
            (
                "game.effect.tick-live-periodic-v1",
                {"current_value": 90, "threshold": 85},
                5,
            ),
            (
                "game.effect.tick-live-periodic-v1",
                {"current_value": 85, "threshold": 85},
                0,
            ),
        ]
        assert [evaluation["result"] for evaluation in live_tick_evaluations] == [
            15,
            0,
        ]
        snapshot_evaluations = effect_formula_evaluations(snapshot_combat_first)
        assert [
            (evaluation["operation"]["id"], evaluation["result"])
            for evaluation in snapshot_evaluations
        ] == [("game.effect.apply-snapshot-periodic-v1", 15)]
        assert all(
            evaluation["context"] == {"phase": "event", "frame": "pre-event-snapshot"}
            and evaluation["frame_identity"]
            == next(
                event["snapshot_before_identity"]
                for event in live_combat_first["events"]
                if evaluation in event["formula_evaluations"]
            )
            for evaluation in live_combat_evaluations
        )

        def metric_health(receipt: dict) -> int:
            metric_dataset = json.loads(
                _receipt_members(receipt)["metric-dataset"].read_text(encoding="utf-8")
            )
            return next(
                sample["value"]
                for sample in metric_dataset["samples"]
                if sample["metric"] == "target_health_remaining"
            )

        assert metric_health(live_receipt) == 85
        assert metric_health(live_tick_first_receipt) == 75

    def test_periodic_effect_formula_only_edit_changes_only_dependent_identities(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        baseline_build = _build_periodic_effect_example(
            tmp_path,
            invocation_key="1" * 64,
            output_name="baseline-periodic-model",
        )
        tuned_source = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "model-source.json").read_text(
                encoding="utf-8"
            )
        )
        magnitude = next(
            formula
            for formula in tuned_source["modules"][0]["formulas"]
            if formula["id"] == "periodic-magnitude"
        )
        raw_magnitude = next(
            node for node in magnitude["body"]["nodes"] if node["id"] == "raw_magnitude"
        )
        left, right = raw_magnitude["arguments"]
        left["operand"], right["operand"] = right["operand"], left["operand"]
        magnitude["expression"] = (
            "let raw_magnitude = threshold - current_value;\n"
            "let magnitude = floor_zero(raw_magnitude);\n"
            "magnitude"
        )
        tuned_source_path = tmp_path / "tuned-model-source.json"
        tuned_source_path.write_text(json.dumps(tuned_source), encoding="utf-8")
        tuned_result = _run(
            "model",
            "build",
            str(tuned_source_path),
            "--out",
            str(tmp_path / "tuned-periodic-model"),
            "--invocation-key",
            "2" * 64,
        )
        assert (tuned_result.returncode, tuned_result.stderr) == (0, ""), (
            tuned_result.stdout,
            tuned_result.stderr,
        )
        tuned_build = json.loads(tuned_result.stdout)

        baseline_record = json.loads(
            _receipt_members(baseline_build)["build-receipt"].read_text(
                encoding="utf-8"
            )
        )
        tuned_record = json.loads(
            _receipt_members(tuned_build)["build-receipt"].read_text(encoding="utf-8")
        )
        assert (
            baseline_record["kernel_identity"],
            baseline_record["language_bundle_identity"],
            baseline_record["package_lock_identity"],
        ) == (
            tuned_record["kernel_identity"],
            tuned_record["language_bundle_identity"],
            tuned_record["package_lock_identity"],
        )
        assert baseline_record["source_identity"] != tuned_record["source_identity"]
        assert baseline_record["rir_identity"] != tuned_record["rir_identity"]
        assert (
            baseline_record["resolved_model_identity"]
            != tuned_record["resolved_model_identity"]
        )
        baseline_rir = json.loads(
            _receipt_members(baseline_build)["rir-semantic-payload"].read_text(
                encoding="utf-8"
            )
        )
        tuned_rir = json.loads(
            _receipt_members(tuned_build)["rir-semantic-payload"].read_text(
                encoding="utf-8"
            )
        )

        def effect_binding(rir: dict) -> dict:
            return next(
                binding
                for binding in rir["formula_bindings"]
                if binding["site"]["kind"] == "operation-slot"
                and binding["site"]["operation"]["id"]
                == "game.effect.apply-snapshot-periodic-v1"
            )

        baseline_binding = effect_binding(baseline_rir)
        tuned_binding = effect_binding(tuned_rir)
        assert (
            baseline_binding["formula"]["identity"]
            != tuned_binding["formula"]["identity"]
        )
        assert (
            baseline_binding["site"]["operation"] == tuned_binding["site"]["operation"]
        )

        experiment = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "experiment.json").read_text(
                encoding="utf-8"
            )
        )
        experiment["metrics"][0]["target"] = {"minimum": 0, "maximum": 1000}
        _bind_experiment_to_build(experiment, baseline_build)
        baseline_receipt, baseline_trace = _run_experiment_variant(
            tmp_path,
            experiment,
            name="baseline-formula-run",
            invocation_key="3" * 64,
        )
        tuned_experiment = json.loads(json.dumps(experiment))
        _bind_experiment_to_build(tuned_experiment, tuned_build)
        tuned_receipt, tuned_trace = _run_experiment_variant(
            tmp_path,
            tuned_experiment,
            name="tuned-formula-run",
            invocation_key="4" * 64,
        )

        assert (
            baseline_trace["experiment_identity"] != tuned_trace["experiment_identity"]
        )
        assert (
            baseline_trace["resolved_runtime_profile_identity"]
            != tuned_trace["resolved_runtime_profile_identity"]
        )
        baseline_profile = json.loads(
            _receipt_members(baseline_receipt)["resolved-runtime-profile"].read_text(
                encoding="utf-8"
            )
        )
        tuned_profile = json.loads(
            _receipt_members(tuned_receipt)["resolved-runtime-profile"].read_text(
                encoding="utf-8"
            )
        )
        assert (
            baseline_profile["evaluator_manifest_identity"],
            baseline_profile["runtime_profile_definition_identity"],
            baseline_profile["runtime_profile"],
        ) == (
            tuned_profile["evaluator_manifest_identity"],
            tuned_profile["runtime_profile_definition_identity"],
            tuned_profile["runtime_profile"],
        )
        assert baseline_trace["content_identity"] != tuned_trace["content_identity"]
        assert (
            json.loads(
                _receipt_members(baseline_receipt)["metric-dataset"].read_text(
                    encoding="utf-8"
                )
            )["content_identity"]
            != json.loads(
                _receipt_members(tuned_receipt)["metric-dataset"].read_text(
                    encoding="utf-8"
                )
            )["content_identity"]
        )

        def terminal_health(trace: dict) -> int:
            expiry = next(
                event
                for event in trace["events"]
                if event["operation"] == "game.effect.expire-periodic-v1"
            )
            return next(
                row["value"]
                for row in expiry["state_after"]
                if row["name"] == "target_health"
            )

        assert terminal_health(baseline_trace) == 70
        assert terminal_health(tuned_trace) == 100
        assert [
            evaluation["result"]
            for event in baseline_trace["events"]
            for evaluation in event["formula_evaluations"]
            if evaluation["operation"]["package"] == "game.effect"
        ] == [15]
        assert [
            evaluation["result"]
            for event in tuned_trace["events"]
            for evaluation in event["formula_evaluations"]
            if evaluation["operation"]["package"] == "game.effect"
        ] == [0]

    def test_periodic_effect_refuses_an_unbound_magnitude_formula(self, tmp_path):
        source = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "model-source.json").read_text(
                encoding="utf-8"
            )
        )
        source["formula_bindings"] = [
            binding
            for binding in source["formula_bindings"]
            if binding["site"].get("operation", {}).get("id")
            != "game.effect.apply-snapshot-periodic-v1"
        ]
        source_path = tmp_path / "unbound-periodic-formula.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        output = tmp_path / "must-not-build"

        result = _run(
            "model",
            "build",
            str(source_path),
            "--out",
            str(output),
            "--invocation-key",
            "5" * 64,
        )

        assert (result.returncode, result.stderr) == (2, "")
        error = json.loads(result.stdout)["error"]
        assert error["stage"] == "static"
        assert [row["code"] for row in error["diagnostics"]] == [
            "language.formula_binding_missing"
        ]
        assert output.exists() is False

    def test_periodic_effect_formula_overflow_rolls_back_the_apply_event(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        source = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "model-source.json").read_text(
                encoding="utf-8"
            )
        )
        threshold_symbol = next(
            symbol
            for symbol in source["modules"][0]["symbols"]
            if symbol["symbol"] == "magnitude_threshold"
        )
        threshold_symbol["domain"]["minimum"] = -(1 << 63)
        source_path = tmp_path / "overflow-periodic-model.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        built = _run(
            "model",
            "build",
            str(source_path),
            "--out",
            str(tmp_path / "overflow-periodic-model"),
            "--invocation-key",
            "6" * 64,
        )
        assert (built.returncode, built.stderr) == (0, ""), built.stdout
        build_receipt = json.loads(built.stdout)
        rir = json.loads(
            _receipt_members(build_receipt)["rir-semantic-payload"].read_text(
                encoding="utf-8"
            )
        )
        site_identity = next(
            binding["site"]["identity"]
            for binding in rir["formula_bindings"]
            if binding["site"]["kind"] == "operation-slot"
            and binding["site"]["operation"]["id"]
            == "game.effect.apply-snapshot-periodic-v1"
        )
        experiment = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "experiment.json").read_text(
                encoding="utf-8"
            )
        )
        _bind_experiment_to_build(experiment, build_receipt)
        next(
            assignment
            for assignment in experiment["scenarios"][0]["assignments"]
            if assignment["target"]["name"] == "magnitude_threshold"
        )["value"] = -(1 << 63)
        specification = tmp_path / "overflow-periodic-experiment.json"
        specification.write_text(json.dumps(experiment), encoding="utf-8")

        result = _run(
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "overflow-periodic-run"),
            "--invocation-key",
            "7" * 64,
        )

        assert (result.returncode, result.stderr) == (2, "")
        error = json.loads(result.stdout)["error"]
        assert error["stage"] == "runtime"
        assert [row["code"] for row in error["diagnostics"]] == [
            "runtime.numeric_overflow"
        ]
        terminal_receipt = error["terminal_audit"]
        assert {row["logical_name"] for row in terminal_receipt["member_locators"]} == {
            "evaluator-capability-manifest",
            "reproduction-receipt",
            "resolved-runtime-profile",
            "runtime-terminal-audit",
        }
        audit = json.loads(
            _receipt_members(terminal_receipt)["runtime-terminal-audit"].read_text(
                encoding="utf-8"
            )
        )
        assert audit["committed_trace_prefix"] == []
        assert audit["refusing_event"]["operation"] == (
            "game.effect.apply-snapshot-periodic-v1"
        )
        assert audit["refusing_event"]["reason"] == "runtime.numeric_overflow"
        assert audit["refusing_event"]["evaluation_site_identity"] == site_identity
        assert audit["rollback"]["committed"] is False
        assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"]
        assert all(
            record["event_spec"]["kind"] != "scheduled-transition"
            for record in audit["event_catalog_prefix"]
        )

    def test_periodic_effect_refuses_state_outside_the_receiving_resource_domain(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        build_receipt = _build_periodic_effect_example(
            tmp_path,
            invocation_key="6" * 64,
        )
        experiment = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "experiment.json").read_text(
                encoding="utf-8"
            )
        )
        _bind_experiment_to_build(experiment, build_receipt)
        next(
            assignment
            for assignment in experiment["scenarios"][0]["assignments"]
            if assignment["target"]["name"] == "magnitude_threshold"
        )["value"] = 0
        specification = tmp_path / "periodic-resource-domain.json"
        specification.write_text(json.dumps(experiment), encoding="utf-8")

        result = _run(
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "periodic-resource-domain-run"),
            "--invocation-key",
            "7" * 64,
        )

        assert (result.returncode, result.stderr) == (2, "")
        error = json.loads(result.stdout)["error"]
        assert error["stage"] == "runtime"
        assert [row["code"] for row in error["diagnostics"]] == [
            "runtime.numeric_overflow"
        ]
        audit = json.loads(
            _receipt_members(error["terminal_audit"])[
                "runtime-terminal-audit"
            ].read_text(encoding="utf-8")
        )
        assert audit["refusing_event"]["operation"] == (
            "game.effect.tick-snapshot-periodic-v1"
        )
        assert audit["refusing_event"]["reason"] == "runtime.numeric_overflow"
        assert [event["operation"] for event in audit["committed_trace_prefix"]] == [
            "game.effect.apply-snapshot-periodic-v1",
            "game.effect.tick-snapshot-periodic-v1",
        ]
        assert audit["rollback"]["committed"] is False
        assert audit["rollback"]["state_before"] == audit["rollback"]["state_after"]
        assert (
            next(
                row["value"]
                for row in audit["rollback"]["state_after"]
                if row["name"] == "target_health"
            )
            == 0
        )

    def test_periodic_effect_schedule_budget_refuses_and_discards_apply_buffers(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        build_receipt = _build_periodic_effect_example(
            tmp_path,
            invocation_key="8" * 64,
            output_name="queue-boundary-model",
        )
        experiment = json.loads(
            (_RPG_PERIODIC_EFFECT_EXAMPLE / "same-time-experiment.json").read_text(
                encoding="utf-8"
            )
        )
        _bind_experiment_to_build(experiment, build_receipt)
        apply = experiment["scenarios"][0]["event_plan"][0]
        apply["entrypoint"] = "effect.apply-snapshot-periodic"
        experiment["scenarios"][0]["event_plan"] = [apply] + [
            {
                "kind": "transition-invocation",
                "root_event_ref": f"future-combat-{index:03d}",
                "logical_time": 10,
                "priority": 0,
                "entrypoint": "combat.damage-target",
                "payload": [],
            }
            for index in range(127)
        ]
        specification = tmp_path / "queue-boundary-experiment.json"
        specification.write_text(json.dumps(experiment), encoding="utf-8")

        result = _run(
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "queue-boundary-run"),
            "--invocation-key",
            "9" * 64,
        )

        assert (result.returncode, result.stderr) == (2, "")
        error = json.loads(result.stdout)["error"]
        assert error["stage"] == "runtime"
        assert [row["code"] for row in error["diagnostics"]] == [
            "runtime.queue_limit_exceeded"
        ]
        audit = json.loads(
            _receipt_members(error["terminal_audit"])[
                "runtime-terminal-audit"
            ].read_text(encoding="utf-8")
        )
        assert audit["committed_trace_prefix"] == []
        assert audit["refusing_event"]["operation"] == (
            "game.effect.apply-snapshot-periodic-v1"
        )
        assert audit["refusing_event"]["reason"] == "runtime.queue_limit_exceeded"
        assert audit["rollback"]["state_after"] == audit["rollback"]["state_before"]
        assert (
            next(
                row["value"]
                for row in audit["rollback"]["state_after"]
                if row["name"] == "effect_instance_id"
            )
            == 0
        )
        assert all(
            record["event_spec"]["kind"] != "scheduled-transition"
            for record in audit["event_catalog_prefix"]
        )
        assert audit["budget_counters"]["queue_events"] == 127

    def test_formula_to_experiment_public_key_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example = _RPG_COMBAT_EXAMPLE
        source = json.loads((example / "model-source.json").read_text())
        module = source["modules"][0]
        formula = next(
            row for row in module["formulas"] if row["id"] == "mitigated-damage"
        )
        request_context = {
            "schema_version": source["schema_version"],
            "package_requirements": source["package_requirements"],
            "module": {"id": module["id"], "imports": module["imports"]},
        }

        render_request = {
            **request_context,
            "formula": {
                key: value for key, value in formula.items() if key != "expression"
            },
        }
        render_source = tmp_path / "formula-render.json"
        render_source.write_text(json.dumps(render_request), encoding="utf-8")
        rendered = _run("formula", "render", str(render_source))
        assert (rendered.returncode, rendered.stderr) == (0, "")
        rendered_pair = json.loads(rendered.stdout)

        parse_request = {
            **request_context,
            "formula": {
                **{key: value for key, value in formula.items() if key != "body"},
                "expression": (
                    " let raw_damage = ((damage_before_defense - mitigation)); "
                    "let damage = floor_zero(((raw_damage))); damage "
                ),
            },
        }
        parse_source = tmp_path / "formula-parse.json"
        parse_source.write_text(json.dumps(parse_request), encoding="utf-8")
        parsed = _run("formula", "parse", str(parse_source))
        assert (parsed.returncode, parsed.stderr) == (0, "")
        parsed_pair = json.loads(parsed.stdout)
        assert parsed_pair == rendered_pair
        assert {key: parsed_pair[key] for key in ("body", "expression")} == {
            "body": formula["body"],
            "expression": formula["expression"],
        }
        assert parsed_pair["kernel_identity"].startswith("sha256:")
        assert parsed_pair["language_bundle_identity"].startswith("sha256:")

        source_path = example / "model-source.json"
        checked = _run("model", "check", str(source_path))
        assert (checked.returncode, checked.stderr) == (0, "")

        drifted = json.loads(json.dumps(source))
        drifted["modules"][0]["formulas"][0]["expression"] += " "
        drifted_path = tmp_path / "model-source-drifted.json"
        drifted_path.write_text(json.dumps(drifted), encoding="utf-8")
        refused = _run("model", "check", str(drifted_path))
        assert (refused.returncode, refused.stderr) == (2, "")
        diagnostic = json.loads(refused.stdout)["error"]["diagnostics"][0]
        assert diagnostic["code"] == "language.formula_notation_mismatch"
        assert diagnostic["primary"]["pointer"] == ("/modules/0/formulas/0/expression")

        built = _run(
            "model",
            "build",
            str(source_path),
            "--out",
            str(tmp_path / "resolved-model.json"),
            "--invocation-key",
            "b" * 64,
        )
        assert (built.returncode, built.stderr) == (0, "")
        build_receipt = json.loads(built.stdout)
        receipt_path = tmp_path / "model-set-receipt.json"
        receipt_path.write_text(built.stdout, encoding="utf-8")
        model_members = {
            row["logical_name"]: Path(row["locator"])
            for row in build_receipt["member_locators"]
        }

        inspected = _run("model", "inspect", str(receipt_path), "--format", "indented")
        assert (inspected.returncode, inspected.stderr) == (0, "")
        explanation = json.loads(inspected.stdout)
        source_expressions = {
            row["id"]: row["expression"] for row in module["formulas"]
        }
        explanation_pairs = {
            row["id"]: (row["body"], row["expression"])
            for row in explanation["formula_explanations"]
        }
        rir = json.loads(model_members["rir-semantic-payload"].read_text())
        rir_pairs = {
            row["id"]: (row["body"], row["expression"]) for row in rir["formulas"]
        }
        assert explanation_pairs == rir_pairs
        assert {
            identifier: expression
            for identifier, (_body, expression) in rir_pairs.items()
        } == source_expressions
        assert rir["content_identity"] != rir["semantic_identity"]

        experiment_path = example / "experiment.json"
        experiment_checked = _run("experiment", "check", str(experiment_path))
        assert (experiment_checked.returncode, experiment_checked.stderr) == (0, "")
        run = _run(
            "experiment",
            "run",
            str(experiment_path),
            "--out",
            str(tmp_path / "evaluation-run.json"),
            "--invocation-key",
            "c" * 64,
        )
        assert (run.returncode, run.stderr) == (0, "")
        run_receipt = json.loads(run.stdout)
        run_members = {
            row["logical_name"]: Path(row["locator"])
            for row in run_receipt["member_locators"]
        }
        metrics = json.loads(run_members["metric-dataset"].read_text())
        trace = json.loads(run_members["event-trace"].read_text())
        snapshots = json.loads(run_members["snapshot-series"].read_text())["snapshots"]
        assert {row["metric"]: row["value"] for row in metrics["samples"]} == {
            "enemy_damage_dealt": 14,
            "enemy_health_remaining": 63,
            "enemy_resource_remaining": 23,
            "player_damage_dealt": 37,
            "player_health_remaining": 86,
            "player_resource_remaining": 26,
        }
        assert {row["metric"]: row["dimensions"] for row in metrics["samples"]} == {
            "enemy_damage_dealt": [
                {"name": "entity", "value": "enemy"},
                {"name": "role", "value": "attacker"},
            ],
            "enemy_health_remaining": [
                {"name": "entity", "value": "enemy"},
                {"name": "role", "value": "defender"},
            ],
            "enemy_resource_remaining": [
                {"name": "entity", "value": "enemy"},
                {"name": "role", "value": "attacker"},
            ],
            "player_damage_dealt": [
                {"name": "entity", "value": "player"},
                {"name": "role", "value": "attacker"},
            ],
            "player_health_remaining": [
                {"name": "entity", "value": "player"},
                {"name": "role", "value": "defender"},
            ],
            "player_resource_remaining": [
                {"name": "entity", "value": "player"},
                {"name": "role", "value": "attacker"},
            ],
        }
        events = trace["events"]
        assert [
            (
                event["ordering_key"]["logical_time"],
                event["ordering_key"]["phase"],
                event["ordering_key"]["priority"],
                event["ordering_key"]["enqueue_sequence"],
            )
            for event in events
        ] == [
            (0, "transition", 0, 0),
            (0, "transition", 0, 1),
            (0, "observation", 0, 2),
            (0, "observation", 0, 3),
            (0, "observation", 0, 4),
            (0, "observation", 0, 5),
            (0, "observation", 0, 6),
            (0, "observation", 0, 7),
        ]
        player_attack, enemy_attack = events[:2]
        assert trace["root_event_map"] == [
            {
                "scenario": "reciprocal-cast",
                "root_event_ref": "player-attacks-enemy",
                "event_id": player_attack["event_id"],
            },
            {
                "scenario": "reciprocal-cast",
                "root_event_ref": "enemy-attacks-player",
                "event_id": enemy_attack["event_id"],
            },
        ]
        assert [event["entrypoint"]["id"] for event in events[:2]] == [
            "combat.player-attacks-enemy",
            "combat.enemy-attacks-player",
        ]
        assert all(
            event["outcome"] == {"id": "cast-resolved", "kind": "success"}
            for event in events[:2]
        )
        assert (
            player_attack["entrypoint"]["identity"]
            != enemy_attack["entrypoint"]["identity"]
        )
        assert all(
            call["call_site_identity"].startswith("sha256:")
            and all(
                argument["formal_port_identity"].startswith("sha256:")
                and argument["actual_operand_identity"].startswith("sha256:")
                for argument in call["arguments"]
            )
            for event in events[:2]
            for call in event["calls"]
        )
        assert [draw["stream"] for draw in player_attack["rng_draws"]] == [
            "hit",
            "critical",
        ]
        assert [draw["stream"] for draw in enemy_attack["rng_draws"]] == [
            "hit",
            "critical",
        ]
        assert enemy_attack["state_before"] == player_attack["state_after"]
        player_facts = {row["name"] for row in player_attack["facts"]}
        enemy_facts = {row["name"] for row in enemy_attack["facts"]}
        assert "player_damage_dealt" in player_facts
        assert "player_damage_dealt" not in enemy_facts
        assert "enemy_damage_dealt" in enemy_facts
        assert len(snapshots) == len(events) + 1
        assert all(
            event["snapshot_before_identity"] == snapshots[index]["snapshot_identity"]
            and event["snapshot_after_identity"]
            == snapshots[index + 1]["snapshot_identity"]
            for index, event in enumerate(events)
        )
        assert events[-1]["state_after"] == [
            {"name": "enemy_health", "value": 63},
            {"name": "enemy_mana", "value": 23},
            {"name": "player_health", "value": 86},
            {"name": "player_mana", "value": 26},
        ]
        recovered = _run(
            "experiment",
            "run",
            str(experiment_path),
            "--out",
            str(tmp_path / "evaluation-run.json"),
            "--invocation-key",
            "c" * 64,
        )
        assert (recovered.returncode, recovered.stderr) == (0, "")
        assert json.loads(recovered.stdout) == run_receipt

    def test_reciprocal_combat_distinguishes_priority_from_admission_order(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="d" * 64,
        )
        baseline = json.loads((example / "experiment.json").read_text(encoding="utf-8"))

        def run_independently_twice(
            experiment: dict,
            *,
            name: str,
            first_key: str,
            second_key: str,
        ) -> tuple[dict, dict]:
            first_receipt, first_trace = _run_experiment_variant(
                tmp_path,
                experiment,
                name=f"{name}-first",
                invocation_key=first_key,
            )
            first_member_bytes = {
                logical_name: path.read_bytes()
                for logical_name, path in _receipt_members(first_receipt).items()
            }
            second_receipt, second_trace = _run_experiment_variant(
                tmp_path,
                experiment,
                name=f"{name}-second",
                invocation_key=second_key,
            )
            second_member_bytes = {
                logical_name: path.read_bytes()
                for logical_name, path in _receipt_members(second_receipt).items()
            }
            assert second_trace == first_trace
            assert second_member_bytes == first_member_bytes
            return first_receipt, first_trace

        _baseline_receipt, baseline_trace = run_independently_twice(
            baseline,
            name="ordering-baseline",
            first_key="e" * 64,
            second_key="f" * 64,
        )

        priority_variant = json.loads(json.dumps(baseline))
        priority_variant["scenarios"][0]["event_plan"][1]["priority"] = 1
        _priority_receipt, priority_trace = run_independently_twice(
            priority_variant,
            name="priority-vector",
            first_key="1" * 64,
            second_key="2" * 64,
        )

        assert [
            (row["root_event_ref"], row["event_id"])
            for row in priority_trace["root_event_map"]
        ] == [
            ("player-attacks-enemy", priority_trace["root_event_map"][0]["event_id"]),
            ("enemy-attacks-player", priority_trace["root_event_map"][1]["event_id"]),
        ]
        priority_events = [
            event
            for event in priority_trace["events"]
            if event["operation"] is not None
        ]
        assert [
            (
                event["root_event_ref"],
                event["ordering_key"]["priority"],
                event["ordering_key"]["enqueue_sequence"],
            )
            for event in priority_events
        ] == [
            ("enemy-attacks-player", 1, 1),
            ("player-attacks-enemy", 0, 0),
        ]

        admission_variant = json.loads(json.dumps(baseline))
        admission_variant["scenarios"][0]["event_plan"].reverse()
        _admission_receipt, admission_trace = run_independently_twice(
            admission_variant,
            name="admission-order-vector",
            first_key="3" * 64,
            second_key="4" * 64,
        )
        admission_events = [
            event
            for event in admission_trace["events"]
            if event["operation"] is not None
        ]
        assert [row["root_event_ref"] for row in admission_trace["root_event_map"]] == [
            "enemy-attacks-player",
            "player-attacks-enemy",
        ]
        assert [
            (
                event["root_event_ref"],
                event["ordering_key"]["priority"],
                event["ordering_key"]["enqueue_sequence"],
            )
            for event in admission_events
        ] == [
            ("enemy-attacks-player", 0, 0),
            ("player-attacks-enemy", 0, 1),
        ]
        assert (
            len(
                {
                    baseline_trace["content_identity"],
                    priority_trace["content_identity"],
                    admission_trace["content_identity"],
                }
            )
            == 3
        )

    def test_reciprocal_combat_can_explicitly_cancel_an_admitted_root_event(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="1" * 64,
        )
        cancellation = json.loads(
            (example / "experiment.json").read_text(encoding="utf-8")
        )
        cancellation["id"] = "example.rpg-combat-cast.explicit-cancellation"
        cancellation["metrics"] = cancellation["metrics"][:2]
        requirements = cancellation["runtime"]["required_evaluator"]
        requirements["instruction_nodes"].append("cancel")
        requirements["effects"].append("event.cancel")
        first_root, second_root = cancellation["scenarios"][0]["event_plan"]
        first_root["entrypoint"] = (
            "combat.player-attacks-enemy-and-cancels-counterattack"
        )
        first_root["event_references"] = [
            {
                "name": "counterattack",
                "root_event_ref": second_root["root_event_ref"],
            }
        ]

        receipt, trace = _run_experiment_variant(
            tmp_path,
            cancellation,
            name="explicit-cancellation",
            invocation_key="2" * 64,
        )

        root_ids = {
            row["root_event_ref"]: row["event_id"] for row in trace["root_event_map"]
        }
        transition_events = [
            event for event in trace["events"] if event["operation"] is not None
        ]
        assert [event["root_event_ref"] for event in transition_events] == [
            "player-attacks-enemy"
        ]
        event = transition_events[0]
        assert event["outcome"] == {
            "id": "cast-resolved-and-canceled",
            "kind": "success",
        }
        assert event["cancellations"] == [
            {
                "call_site_identity": event["cancellations"][0]["call_site_identity"],
                "event_id": root_ids["enemy-attacks-player"],
                "outcome": "canceled",
            }
        ]
        assert root_ids["enemy-attacks-player"] not in {
            row["event_id"] for row in trace["events"]
        }
        assert event["state_after"] == [
            {"name": "enemy_health", "value": 63},
            {"name": "enemy_mana", "value": 30},
            {"name": "player_health", "value": 100},
            {"name": "player_mana", "value": 26},
        ]
        snapshots = json.loads(
            _receipt_members(receipt)["snapshot-series"].read_text(encoding="utf-8")
        )["snapshots"]
        assert snapshots[1]["continuation"]["pending_event_count"] == 0

    def test_reciprocal_event_reference_refuses_active_root_as_not_pending(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="3" * 64,
        )
        active = json.loads((example / "experiment.json").read_text(encoding="utf-8"))
        active["id"] = "example.rpg-combat-cast.cancel-active-root"
        first_root = active["scenarios"][0]["event_plan"][0]
        first_root["entrypoint"] = (
            "combat.player-attacks-enemy-and-cancels-counterattack"
        )
        first_root["event_references"] = [
            {
                "name": "counterattack",
                "root_event_ref": first_root["root_event_ref"],
            }
        ]
        requirements = active["runtime"]["required_evaluator"]
        requirements["instruction_nodes"].append("cancel")
        requirements["effects"].append("event.cancel")
        specification = tmp_path / "cancel-active-root.json"
        specification.write_text(json.dumps(active), encoding="utf-8")

        result = _run(
            "experiment",
            "run",
            str(specification),
            "--out",
            str(tmp_path / "cancel-active-root"),
            "--invocation-key",
            "4" * 64,
        )

        assert (result.returncode, result.stderr) == (2, "")
        error = json.loads(result.stdout)["error"]
        assert (error["stage"], error["diagnostics"][0]["code"]) == (
            "runtime",
            "runtime.cancel_active",
        )
        assert set(_receipt_members(error["terminal_audit"])) == {
            "evaluator-capability-manifest",
            "reproduction-receipt",
            "resolved-runtime-profile",
            "runtime-terminal-audit",
        }

    def test_reciprocal_combat_does_not_infer_defeat_or_cancel_eligibility(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="3" * 64,
        )
        no_cancellation = json.loads(
            (example / "experiment.json").read_text(encoding="utf-8")
        )
        no_cancellation["id"] = "example.rpg-combat-cast.no-inferred-defeat"
        no_cancellation["scenarios"][0]["event_plan"][0]["entrypoint"] = (
            "combat.player-attacks-enemy-without-eligibility"
        )
        no_cancellation["scenarios"][0]["event_plan"][1]["entrypoint"] = (
            "combat.enemy-attacks-player-without-eligibility"
        )
        no_cancellation["scenarios"][0]["assignments"] = [
            row
            for row in no_cancellation["scenarios"][0]["assignments"]
            if row["target"]["name"] != "defeat_threshold"
        ]
        no_cancellation["runtime"]["required_evaluator"]["instruction_nodes"].remove(
            "guard-block"
        )
        no_cancellation["runtime"]["required_evaluator"]["instruction_nodes"].remove(
            "require"
        )
        enemy_health = next(
            row
            for row in no_cancellation["scenarios"][0]["assignments"]
            if row["target"]["name"] == "enemy_health"
        )
        enemy_health["value"] = 37

        _receipt, trace = _run_experiment_variant(
            tmp_path,
            no_cancellation,
            name="no-inferred-defeat",
            invocation_key="4" * 64,
        )

        transition_events = [
            event for event in trace["events"] if event["operation"] is not None
        ]
        assert [event["root_event_ref"] for event in transition_events] == [
            "player-attacks-enemy",
            "enemy-attacks-player",
        ]
        first_event, second_event = transition_events
        assert first_event["state_after"] == second_event["state_before"]
        assert {row["name"]: row["value"] for row in second_event["state_before"]}[
            "enemy_health"
        ] == 0
        assert all(event["cancellations"] == [] for event in transition_events)
        assert all(
            event["outcome"] == {"id": "cast-resolved", "kind": "success"}
            for event in transition_events
        )
        assert {row["name"]: row["value"] for row in second_event["state_after"]}[
            "player_health"
        ] == 86

    def test_reciprocal_combat_revisions_stop_on_explicit_defeat(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="5" * 64,
        )
        baseline = json.loads((example / "experiment.json").read_text(encoding="utf-8"))
        _bind_experiment_to_build(baseline, build_receipt)
        state = {
            row["target"]["name"]: row["value"]
            for row in baseline["scenarios"][0]["assignments"]
        }
        traces = []
        outcomes = []
        actions = ("player-attacks-enemy", "enemy-attacks-player")

        for index in range(1, 7):
            root_event_ref = actions[(index - 1) % 2]
            revision = one_action_experiment(
                baseline,
                f"example.rpg-combat-cast.action-{index}",
                root_event_ref=root_event_ref,
                include_damage_metric=False,
            )
            for assignment in revision["scenarios"][0]["assignments"]:
                assignment["value"] = state[assignment["target"]["name"]]
            _receipt, trace = _run_experiment_variant(
                tmp_path,
                revision,
                name=f"combat-action-{index}",
                invocation_key="6789ab"[index - 1] * 64,
            )
            traces.append(trace)
            transition = next(
                event for event in trace["events"] if event["operation"] is not None
            )
            outcomes.append(transition["outcome"]["id"])
            state.update(
                {row["name"]: row["value"] for row in transition["state_after"]}
            )
            if transition["outcome"]["id"] == "target-defeated":
                break

        assert len(traces) == 5
        assert outcomes == [
            "cast-resolved",
            "cast-resolved",
            "cast-resolved",
            "cast-resolved",
            "target-defeated",
        ]
        terminal_event = next(
            event for event in traces[-1]["events"] if event["operation"] is not None
        )
        assert {row["name"]: row["integer"] for row in terminal_event["facts"]}[
            "player_damage_dealt"
        ] == 26
        assert state == {
            "enemy_health": 0,
            "enemy_mana": 16,
            "player_health": 72,
            "player_mana": 8,
            "defeat_threshold": 0,
            "enemy_accuracy": 1000,
            "enemy_action_cost": 7,
            "enemy_base_damage": 20,
            "enemy_critical_threshold": 0,
            "enemy_defense": 8,
            "player_accuracy": 1000,
            "player_action_cost": 9,
            "player_base_damage": 45,
            "player_critical_threshold": 0,
            "player_defense": 6,
        }

    def test_rpg_combat_example_distinguishes_one_way_and_alternative_outcomes(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="6" * 64,
        )
        baseline = json.loads((example / "experiment.json").read_text(encoding="utf-8"))

        one_way = _one_way_variant(
            baseline,
            "example.rpg-combat-cast.one-way",
        )
        one_way_receipt, one_way_trace = _run_experiment_variant(
            tmp_path,
            one_way,
            name="one-way",
            invocation_key="7" * 64,
        )
        one_way_event = next(
            event for event in one_way_trace["events"] if event["operation"] is not None
        )
        assert one_way_event["outcome"] == {"id": "cast-resolved", "kind": "success"}
        assert one_way_event["state_after"] == [
            {"name": "enemy_health", "value": 63},
            {"name": "player_health", "value": 100},
            {"name": "player_mana", "value": 26},
        ]

        def metric_values(receipt: dict) -> dict[str, int]:
            dataset = json.loads(
                _receipt_members(receipt)["metric-dataset"].read_text(encoding="utf-8")
            )
            return {row["metric"]: row["value"] for row in dataset["samples"]}

        assert metric_values(one_way_receipt) == {
            "enemy_health_remaining": 63,
            "player_damage_dealt": 37,
            "player_resource_remaining": 26,
        }

        def alternative_variant(identifier: str, assignment: str, value: int) -> dict:
            variant = json.loads(json.dumps(one_way))
            variant["id"] = f"example.rpg-combat-cast.{identifier}"
            variant["metrics"] = [
                metric
                for metric in variant["metrics"]
                if metric["observation"]["source"] == "snapshot"
            ]
            next(
                row
                for row in variant["scenarios"][0]["assignments"]
                if row["target"]["name"] == assignment
            )["value"] = value
            return variant

        miss = alternative_variant("miss", "player_accuracy", 0)
        next(
            row
            for row in miss["scenarios"][0]["assignments"]
            if row["target"]["name"] == "enemy_defense"
        )["value"] = 1000
        miss_receipt, miss_trace = _run_experiment_variant(
            tmp_path,
            miss,
            name="miss",
            invocation_key="8" * 64,
        )
        miss_event = next(
            event for event in miss_trace["events"] if event["operation"] is not None
        )
        assert miss_event["outcome"] == {"id": "miss", "kind": "gameplay-alternative"}
        assert miss_event["state_after"] == miss_event["state_before"]
        assert [draw["stream"] for draw in miss_event["rng_draws"]] == ["hit"]
        assert metric_values(miss_receipt) == {
            "enemy_health_remaining": 100,
            "player_resource_remaining": 35,
        }

        insufficient = alternative_variant("insufficient-resource", "player_mana", 0)
        insufficient_receipt, insufficient_trace = _run_experiment_variant(
            tmp_path,
            insufficient,
            name="insufficient-resource",
            invocation_key="9" * 64,
        )
        insufficient_event = next(
            event
            for event in insufficient_trace["events"]
            if event["operation"] is not None
        )
        assert insufficient_event["outcome"] == {
            "id": "insufficient-resource",
            "kind": "gameplay-alternative",
        }
        assert insufficient_event["state_after"] == insufficient_event["state_before"]
        assert insufficient_event["rng_draws"] == []
        assert metric_values(insufficient_receipt) == {
            "enemy_health_remaining": 100,
            "player_resource_remaining": 0,
        }

    def test_one_way_scenario_does_not_evaluate_an_unselected_literal_formula_site(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example = _RPG_COMBAT_EXAMPLE
        baseline = json.loads((example / "experiment.json").read_text(encoding="utf-8"))
        _example, normal_build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="a" * 64,
            output_name="normal-model",
        )
        normal = _one_way_variant(
            baseline,
            "example.rpg-combat-cast.selected-site-control",
        )
        _bind_experiment_to_build(normal, normal_build_receipt)
        normal_receipt, normal_trace = _run_experiment_variant(
            tmp_path,
            normal,
            name="selected-site-control",
            invocation_key="b" * 64,
        )

        source = json.loads((example / "model-source.json").read_text(encoding="utf-8"))
        enemy_binding = next(
            binding
            for binding in source["formula_bindings"]
            if binding["site"].get("symbol") == "enemy_effective_accuracy"
        )
        literal_formula = json.loads(
            json.dumps(
                next(
                    formula
                    for formula in source["modules"][0]["formulas"]
                    if formula["id"] == "effective-accuracy"
                )
            )
        )
        literal_formula["id"] = "literal-accuracy"
        literal_formula["parameters"] = []
        literal_formula["body"] = {
            "nodes": [],
            "result": {"kind": "literal", "value": 7},
        }
        literal_formula["expression"] = "7"
        source["modules"][0]["formulas"].append(literal_formula)
        enemy_binding["formula"]["id"] = "literal-accuracy"
        enemy_binding["arguments"] = []
        literal_source = tmp_path / "unselected-literal-formula-model.json"
        literal_source.write_text(json.dumps(source), encoding="utf-8")
        literal_build = _run(
            "model",
            "build",
            str(literal_source),
            "--out",
            str(tmp_path / "literal-model"),
            "--invocation-key",
            "c" * 64,
        )
        assert (literal_build.returncode, literal_build.stderr) == (0, "")
        literal = _one_way_variant(
            baseline,
            "example.rpg-combat-cast.unselected-literal-site",
        )
        _bind_experiment_to_build(literal, json.loads(literal_build.stdout))
        literal_receipt, literal_trace = _run_experiment_variant(
            tmp_path,
            literal,
            name="unselected-literal-site",
            invocation_key="d" * 64,
        )

        def terminal_node_steps(receipt: dict) -> int:
            snapshots = json.loads(
                _receipt_members(receipt)["snapshot-series"].read_text(encoding="utf-8")
            )["snapshots"]
            return snapshots[-1]["continuation"]["resource_ledger"]["node_steps"]

        assert terminal_node_steps(literal_receipt) == terminal_node_steps(
            normal_receipt
        )
        assert [
            (event["outcome"], event["state_after"])
            for event in literal_trace["events"]
        ] == [
            (event["outcome"], event["state_after"]) for event in normal_trace["events"]
        ]

    def test_one_actor_bound_value_changes_only_its_reciprocal_feedback(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="a" * 64,
        )
        baseline = json.loads((example / "experiment.json").read_text(encoding="utf-8"))
        baseline_receipt, baseline_trace = _run_experiment_variant(
            tmp_path,
            baseline,
            name="baseline-feedback",
            invocation_key="b" * 64,
        )
        tuned = json.loads(json.dumps(baseline))
        tuned["id"] = "example.rpg-combat-cast.player-damage-tuned"
        next(
            row
            for row in tuned["scenarios"][0]["assignments"]
            if row["target"]["name"] == "player_base_damage"
        )["value"] = 55
        tuned_receipt, tuned_trace = _run_experiment_variant(
            tmp_path,
            tuned,
            name="tuned-feedback",
            invocation_key="c" * 64,
        )

        assert tuned["kernel_identity"] == baseline["kernel_identity"]
        assert tuned["language_bundle_identity"] == baseline["language_bundle_identity"]
        assert tuned["model"] == baseline["model"]
        assert tuned["runtime"] == baseline["runtime"]
        assert tuned_trace["content_identity"] != baseline_trace["content_identity"]
        baseline_metrics = json.loads(
            _receipt_members(baseline_receipt)["metric-dataset"].read_text(
                encoding="utf-8"
            )
        )
        tuned_metrics = json.loads(
            _receipt_members(tuned_receipt)["metric-dataset"].read_text(
                encoding="utf-8"
            )
        )
        baseline_values = {
            row["metric"]: row["value"] for row in baseline_metrics["samples"]
        }
        tuned_values = {row["metric"]: row["value"] for row in tuned_metrics["samples"]}
        assert {
            metric: tuned_values[metric]
            for metric in tuned_values
            if tuned_values[metric] != baseline_values[metric]
        } == {
            "enemy_health_remaining": 53,
            "player_damage_dealt": 47,
        }
        assert [
            event["outcome"]
            for event in tuned_trace["events"]
            if event["operation"] is not None
        ] == [
            {"id": "cast-resolved", "kind": "success"},
            {"id": "cast-resolved", "kind": "success"},
        ]

    def test_reciprocal_combat_refuses_invalid_authored_event_contracts(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example, _build_receipt = _build_reciprocal_example(
            tmp_path,
            invocation_key="d" * 64,
        )
        baseline = json.loads((example / "experiment.json").read_text(encoding="utf-8"))

        duplicate_root = json.loads(json.dumps(baseline))
        duplicate_root["scenarios"][0]["event_plan"][1]["root_event_ref"] = (
            duplicate_root["scenarios"][0]["event_plan"][0]["root_event_ref"]
        )
        undeclared_entrypoint = json.loads(json.dumps(baseline))
        undeclared_entrypoint["scenarios"][0]["event_plan"][0]["entrypoint"] = (
            "combat.host-invented"
        )
        missing_assignment = json.loads(json.dumps(baseline))
        missing_assignment["scenarios"][0]["assignments"].pop()
        incompatible_payload = json.loads(json.dumps(baseline))
        incompatible_payload["scenarios"][0]["event_plan"][0]["payload"] = [
            {
                "target": baseline["scenarios"][0]["assignments"][0]["target"],
                "value": 35,
            }
        ]
        authored_phase = json.loads(json.dumps(baseline))
        authored_phase["scenarios"][0]["event_plan"][0]["phase"] = "transition"
        ambiguous_root_order = json.loads(json.dumps(baseline))
        ambiguous_root_order["scenarios"][0]["event_plan"] = {
            "player": ambiguous_root_order["scenarios"][0]["event_plan"][0],
            "enemy": ambiguous_root_order["scenarios"][0]["event_plan"][1],
        }

        backward_time = json.loads(json.dumps(baseline))
        backward_time["id"] = "example.rpg-combat-cast.backward-time"
        backward_root = backward_time["scenarios"][0]["event_plan"][0]
        backward_root["entrypoint"] = "combat.player-plans-attacks"
        backward_root["logical_time"] = 3
        backward_time["scenarios"][0]["event_plan"] = [backward_root]
        backward_time["scenarios"][0]["assignments"] = [
            row
            for row in backward_time["scenarios"][0]["assignments"]
            if row["target"]["name"]
            in combat_action_assignment_names("player-attacks-enemy")
            - {"defeat_threshold", "player_health"}
        ]
        backward_time["runtime"]["required_evaluator"]["instruction_nodes"].extend(
            ["cancel", "schedule"]
        )
        backward_time["runtime"]["required_evaluator"]["instruction_nodes"].remove(
            "guard-block"
        )
        backward_time["runtime"]["required_evaluator"]["instruction_nodes"].remove(
            "require"
        )
        backward_time["runtime"]["required_evaluator"]["instruction_nodes"].sort()
        backward_time["runtime"]["required_evaluator"]["effects"].extend(
            ["event.cancel", "event.schedule"]
        )
        backward_time["runtime"]["required_evaluator"]["effects"].sort()
        for index, (name, variant, stage, code) in enumerate(
            (
                (
                    "duplicate-root",
                    duplicate_root,
                    "static",
                    "language.source_contract_mismatch",
                ),
                (
                    "undeclared-entrypoint",
                    undeclared_entrypoint,
                    "resolution",
                    "language.resolution_binding_mismatch",
                ),
                (
                    "missing-assignment",
                    missing_assignment,
                    "static",
                    "language.source_contract_mismatch",
                ),
                (
                    "incompatible-payload",
                    incompatible_payload,
                    "static",
                    "language.source_contract_mismatch",
                ),
                (
                    "authored-phase",
                    authored_phase,
                    "static",
                    "language.source_contract_mismatch",
                ),
                (
                    "backward-time",
                    backward_time,
                    "runtime",
                    "runtime.schedule_backward",
                ),
                (
                    "ambiguous-root-order",
                    ambiguous_root_order,
                    "static",
                    "language.source_contract_mismatch",
                ),
            )
        ):
            specification = tmp_path / f"{name}.json"
            specification.write_text(json.dumps(variant), encoding="utf-8")
            output = tmp_path / f"{name}-artifacts"
            result = _run(
                "experiment",
                "run",
                str(specification),
                "--out",
                str(output),
                "--invocation-key",
                f"{index + 1:064x}",
            )
            assert (result.returncode, result.stderr) == (2, ""), (
                name,
                result.stdout,
                result.stderr,
            )
            error = json.loads(result.stdout)["error"]
            assert (error["stage"], error["diagnostics"][0]["code"]) == (
                stage,
                code,
            )
            if stage == "runtime":
                assert set(_receipt_members(error["terminal_audit"])) == {
                    "evaluator-capability-manifest",
                    "reproduction-receipt",
                    "resolved-runtime-profile",
                    "runtime-terminal-audit",
                }
                assert output.exists()
            else:
                assert not output.exists()

    def test_schema_get_key_path(self):
        result = _run("schema", "get", "language-bundle")
        assert (result.returncode, result.stderr) == (0, "")
        artifact = json.loads(result.stdout)
        assert artifact["admission"]["admitted"] is True
        assert (
            artifact["language_bundle"]["kernel_identity"]
            == artifact["kernel"]["content_identity"]
        )
