from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "cli.py"
FIXTURES = ROOT / "fixtures"


def invoke(
    *arguments: str,
    params: dict[str, Any] | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    command = [sys.executable, str(CLI), *arguments]
    if params is not None:
        command.extend(
            [
                "--params-json",
                json.dumps(
                    params, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
            ]
        )
    process_environment = dict(os.environ)
    process_environment.update(environment or {})
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        check=False,
        env=process_environment,
    )


def decoded(output: bytes) -> dict[str, Any]:
    value = json.loads(output)
    assert isinstance(value, dict)
    return value


def stored(root: Path, identity: str) -> dict[str, Any]:
    path = root / f"{identity.removeprefix('sha256:')}.json"
    return decoded(path.read_bytes())


def assert_success(process: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    assert process.returncode == 0, process.stderr or process.stdout
    assert process.stderr == b""
    payload = decoded(process.stdout)
    assert payload["category"] == "success"
    return payload["result"]


def main() -> int:
    schema_commands = (("model", "build"), ("experiment", "run"), ("manifest",))
    for command in schema_commands:
        schema = assert_success(invoke(*command, "--schema"))
        assert set(schema["schema"]) == {"input", "success", "error"}
        assert schema["schema"]["error"]["refusal"]["exit"] == 2
        for outcome in ("input", "success"):
            shape = schema["schema"][outcome]
            assert set(shape["properties"]) == set(shape["required"])

    manifest = assert_success(invoke("manifest"))
    assert [entry["path"] for entry in manifest["commands"]] == [
        ["experiment", "run"],
        ["manifest"],
        ["model", "build"],
    ]
    for malformed in (
        invoke("manifest", params={"extra": True}),
        invoke("model", "build", params={}),
        invoke(
            "model",
            "build",
            params={
                "bundle_path": 7,
                "model_path": "unused",
                "prototype_store": "unused",
            },
        ),
    ):
        assert malformed.returncode == 3
        assert malformed.stdout == b""
        assert decoded(malformed.stderr)["error"]["category"] == "usage"

    with tempfile.TemporaryDirectory(prefix="schema2-tracer-e2e-") as temporary:
        temp_root = Path(temporary)
        success_store = temp_root / "success-store"
        build_params = {
            "bundle_path": str(FIXTURES / "language-bundle.json"),
            "model_path": str(FIXTURES / "rpg-model.json"),
            "prototype_store": str(success_store),
        }
        build = assert_success(invoke("model", "build", params=build_params))
        assert build["prototype_only"] is True
        assert len(build["receipts"]) == 4
        assert all(
            Path(receipt["prototype_store_path"]).is_file()
            for receipt in build["receipts"]
        )

        reversed_source = decoded((FIXTURES / "rpg-model.json").read_bytes())
        reversed_source["modules"] = list(reversed(reversed_source["modules"]))
        reversed_source_path = temp_root / "rpg-model-modules-reversed.json"
        reversed_source_path.write_text(
            json.dumps(
                reversed_source,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        reversed_build = assert_success(
            invoke(
                "model",
                "build",
                params={**build_params, "model_path": str(reversed_source_path)},
            )
        )
        assert reversed_build["ast_identity"] != build["ast_identity"]
        assert reversed_build["hir_identity"] != build["hir_identity"]
        assert reversed_build["package_lock_identity"] == build["package_lock_identity"]
        assert (
            reversed_build["resolved_model_identity"]
            == build["resolved_model_identity"]
        )

        experiment = decoded((FIXTURES / "experiment-success.json").read_bytes())
        assert experiment["resolved_model_identity"] == build["resolved_model_identity"]
        run_params = {
            "experiment_path": str(FIXTURES / "experiment-success.json"),
            "prototype_store": str(success_store),
        }
        first_run_process = invoke("experiment", "run", params=run_params)
        first_run = assert_success(first_run_process)
        second_run_process = invoke("experiment", "run", params=run_params)
        second_run = assert_success(second_run_process)
        assert first_run_process.stdout == second_run_process.stdout
        assert first_run == second_run

        rir = stored(success_store, build["resolved_model_identity"])
        assert rir["artifact_kind"] == "resolved-model-rir"
        assert "hir_identity" not in rir["content"]
        assert len(rir["content"]["handlers"]) == 3
        package_lock = stored(success_store, build["package_lock_identity"])
        assert "source_identity" not in package_lock["content"]

        trace = stored(success_store, first_run["trace_identity"])
        entries = trace["content"]["entries"]
        assert [entry["ordering"]["phase"] for entry in entries] == [
            "input",
            "transition",
            "observation",
        ]
        transition = entries[1]
        assert [draw["stream"] for draw in transition["rng_draws"]] == [
            "combat.hit",
            "combat.critical",
        ]
        assert transition["rng_draws"][0]["algorithm"] == "sha256-counter-v1"
        assert [signal["signal"] for signal in transition["signals"]] == [
            "game.combat.damage-resolved@1"
        ]
        assert transition["signals"][0]["payload"]["target"] == "goblin"
        assert "slime.team" in transition["reads"]
        written_slots = {
            (write["entity"], write["field"]) for write in transition["writes"]
        }
        assert written_slots == {
            ("goblin", "defeated"),
            ("goblin", "health"),
            ("goblin", "marked"),
            ("goblin", "shield"),
            ("mage", "mana"),
        }

        metrics = stored(success_store, first_run["metric_dataset_identity"])
        metric_values = {
            sample["definition_id"]: sample["value"]["value"]
            for sample in metrics["content"]["samples"]
        }
        assert metric_values == {
            "caster_mana": 6,
            "target_defeated": True,
            "target_health": 0,
            "target_marked": True,
        }
        assert len(first_run["evidence_assertion_identities"]) == 3
        evaluation_run = stored(success_store, first_run["evaluation_run_identity"])
        assert evaluation_run["content"]["evaluator_identity"].startswith("sha256:")
        assert all(
            sample["provenance"]["evaluator_identity"]
            == evaluation_run["content"]["evaluator_identity"]
            for sample in metrics["content"]["samples"]
        )
        for assertion_identity in first_run["evidence_assertion_identities"]:
            assertion = stored(success_store, assertion_identity)
            assert (
                assertion["content"]["evaluator_identity"]
                == evaluation_run["content"]["evaluator_identity"]
            )
            assert (
                assertion["content"]["tool_identity"]
                == evaluation_run["content"]["tool_identity"]
            )

        metric_negatives = (
            ("type", "Int", "schema2.evaluation.metric-type-mismatch"),
            ("unit", "game:not-mana", "schema2.evaluation.metric-unit-mismatch"),
            ("dimensions", [], "schema2.evaluation.metric-dimensions"),
            ("window", "unbounded", "schema2.evaluation.metric-policy"),
        )
        for field_name, bad_value, expected_code in metric_negatives:
            invalid_experiment = decoded(
                (FIXTURES / "experiment-success.json").read_bytes()
            )
            invalid_experiment["metrics"][0][field_name] = bad_value
            invalid_path = temp_root / f"experiment-invalid-{field_name}.json"
            invalid_path.write_text(
                json.dumps(
                    invalid_experiment,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            invalid_run = invoke(
                "experiment",
                "run",
                params={
                    "experiment_path": str(invalid_path),
                    "prototype_store": str(success_store),
                },
            )
            assert invalid_run.returncode == 2
            assert invalid_run.stderr == b""
            invalid_error = decoded(invalid_run.stdout)["error"]
            assert invalid_error["stage"] == "evaluation"
            assert invalid_error["diagnostics"][0]["code"] == expected_code

        static_refusal = invoke(
            "model",
            "build",
            params={
                "bundle_path": str(FIXTURES / "language-bundle.json"),
                "model_path": str(FIXTURES / "model-static-refusal.json"),
                "prototype_store": str(temp_root / "static-refusal-store"),
            },
        )
        assert static_refusal.returncode == 2
        assert static_refusal.stderr == b""
        static_error = decoded(static_refusal.stdout)["error"]
        assert static_error["stage"] == "static"
        assert (
            static_error["diagnostics"][0]["code"] == "schema2.static.add-type-mismatch"
        )

        # Prove that the LDB rule is executed, not just used as a diagnostic catalog.
        mutated_bundle = decoded((FIXTURES / "language-bundle.json").read_bytes())
        type_equal = next(
            rule for rule in mutated_bundle["rules"] if rule["id"] == "type.equal"
        )
        type_equal["premises"][0]["right"] = {
            "constant": "__mutated-rule-never-matches__"
        }
        mutated_path = temp_root / "mutated-language-bundle.json"
        mutated_path.write_text(
            json.dumps(
                mutated_bundle,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        rule_refusal = invoke(
            "model",
            "build",
            params={
                "bundle_path": str(mutated_path),
                "model_path": str(FIXTURES / "rpg-model.json"),
                "prototype_store": str(temp_root / "mutated-rule-store"),
            },
        )
        assert rule_refusal.returncode == 2
        rule_error = decoded(rule_refusal.stdout)["error"]
        assert rule_error["stage"] == "static"
        assert rule_error["diagnostics"][0]["code"] == "schema2.static.type-mismatch"

        banana_bundle = decoded((FIXTURES / "language-bundle.json").read_bytes())
        banana_bundle["rules"][0]["diagnostic"]["stage"] = "banana"
        banana_path = temp_root / "banana-diagnostic-stage-bundle.json"
        banana_path.write_text(
            json.dumps(
                banana_bundle,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        banana_refusal = invoke(
            "model",
            "build",
            params={
                "bundle_path": str(banana_path),
                "model_path": str(FIXTURES / "rpg-model.json"),
                "prototype_store": str(temp_root / "banana-store"),
            },
        )
        assert banana_refusal.returncode == 2
        banana_error = decoded(banana_refusal.stdout)["error"]
        assert banana_error["stage"] == "ingress"
        assert (
            banana_error["diagnostics"][0]["code"]
            == "schema2.bundle.invalid-diagnostic-stage"
        )

        runtime_profile_negatives = (
            ("max-events", "schema2.runtime.event-budget"),
            ("max-queue", "schema2.runtime.queue-budget"),
            ("max-zero-time-depth", "schema2.runtime.zero-time-depth-budget"),
            ("named-stream", "schema2.runtime.stream-not-admitted"),
        )
        for variant, expected_code in runtime_profile_negatives:
            profile_bundle = decoded((FIXTURES / "language-bundle.json").read_bytes())
            profile = profile_bundle["runtime_profiles"][0]
            if variant == "max-events":
                profile["budgets"]["max_events"] = 2
            elif variant == "max-queue":
                profile["budgets"]["max_queue"] = 0
            elif variant == "max-zero-time-depth":
                profile["budgets"]["max_zero_time_depth"] = 0
            else:
                profile["named_streams"] = ["combat.hit"]
            profile_bundle_path = temp_root / f"bundle-{variant}.json"
            profile_bundle_path.write_text(
                json.dumps(
                    profile_bundle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            profile_store = temp_root / f"store-{variant}"
            profile_build = assert_success(
                invoke(
                    "model",
                    "build",
                    params={
                        "bundle_path": str(profile_bundle_path),
                        "model_path": str(FIXTURES / "rpg-model.json"),
                        "prototype_store": str(profile_store),
                    },
                )
            )
            profile_experiment = decoded(
                (FIXTURES / "experiment-success.json").read_bytes()
            )
            profile_experiment["resolved_model_identity"] = profile_build[
                "resolved_model_identity"
            ]
            profile_experiment_path = temp_root / f"experiment-{variant}.json"
            profile_experiment_path.write_text(
                json.dumps(
                    profile_experiment,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            profile_run = invoke(
                "experiment",
                "run",
                params={
                    "experiment_path": str(profile_experiment_path),
                    "prototype_store": str(profile_store),
                },
            )
            assert profile_run.returncode == 2
            profile_error = decoded(profile_run.stdout)["error"]
            assert profile_error["stage"] == "runtime"
            assert profile_error["diagnostics"][0]["code"] == expected_code

        build_fault_store = temp_root / "build-fault-store"
        build_fault = invoke(
            "model",
            "build",
            params={**build_params, "prototype_store": str(build_fault_store)},
            environment={"SCHEMA2_TRACER_STORE_FAULT": "before-index"},
        )
        assert build_fault.returncode == 4
        assert build_fault.stdout == b""
        assert decoded(build_fault.stderr)["error"]["category"] == "internal"
        assert not (build_fault_store / "committed-index.json").exists()
        assert not list(build_fault_store.glob("*.json"))

        run_fault_experiment = decoded(
            (FIXTURES / "experiment-success.json").read_bytes()
        )
        run_fault_experiment["effective_seed"] += 1
        run_fault_path = temp_root / "experiment-store-fault.json"
        run_fault_path.write_text(
            json.dumps(
                run_fault_experiment,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        committed_index = success_store / "committed-index.json"
        index_before_fault = committed_index.read_bytes()
        files_before_fault = sorted(path.name for path in success_store.iterdir())
        run_fault = invoke(
            "experiment",
            "run",
            params={
                "experiment_path": str(run_fault_path),
                "prototype_store": str(success_store),
            },
            environment={"SCHEMA2_TRACER_STORE_FAULT": "before-index"},
        )
        assert run_fault.returncode == 4
        assert run_fault.stdout == b""
        assert decoded(run_fault.stderr)["error"]["category"] == "internal"
        assert committed_index.read_bytes() == index_before_fault
        assert (
            sorted(path.name for path in success_store.iterdir()) == files_before_fault
        )

        refusal_store = temp_root / "runtime-refusal-store"
        refusal_build = assert_success(
            invoke(
                "model",
                "build",
                params={**build_params, "prototype_store": str(refusal_store)},
            )
        )
        assert (
            refusal_build["resolved_model_identity"] == build["resolved_model_identity"]
        )
        stored_before = sorted(refusal_store.iterdir())
        runtime_refusal = invoke(
            "experiment",
            "run",
            params={
                "experiment_path": str(FIXTURES / "experiment-cursor-refusal.json"),
                "prototype_store": str(refusal_store),
            },
        )
        assert runtime_refusal.returncode == 2
        assert runtime_refusal.stderr == b""
        runtime_error = decoded(runtime_refusal.stdout)["error"]
        assert runtime_error["stage"] == "runtime"
        assert (
            runtime_error["diagnostics"][0]["code"] == "schema2.runtime.cursor-backward"
        )
        terminal = runtime_error["terminal_evidence"]
        assert (
            terminal["pre_event_state_identity"]
            == terminal["last_committed_state_identity"]
        )
        assert terminal["rng_counters_after_rollback"] == {}
        assert set(terminal["discarded_write_slots"]) == {
            "goblin.defeated",
            "goblin.health",
            "goblin.marked",
            "goblin.shield",
            "mage.mana",
        }
        assert sorted(refusal_store.iterdir()) == stored_before

        print(
            json.dumps(
                {
                    "checks": [
                        "descriptor-schemas-and-manifest",
                        "build-store-run",
                        "byte-identical-replay",
                        "typed-rpg-signal-metrics-evidence",
                        "semantic-normal-form-source-reordering",
                        "experiment-metric-negative-validation",
                        "static-refusal",
                        "bundle-rule-interpreted",
                        "closed-diagnostic-stages",
                        "runtime-profile-budgets-and-streams",
                        "atomic-batch-store-faults",
                        "runtime-atomic-rollback-and-cursor-refusal",
                    ],
                    "evaluation_run_identity": first_run["evaluation_run_identity"],
                    "resolved_model_identity": build["resolved_model_identity"],
                    "status": "passed",
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
