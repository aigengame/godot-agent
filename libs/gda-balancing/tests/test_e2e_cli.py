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

from gda_balancing.envelope import ERROR_ENVELOPE_SCHEMA


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

    def test_formula_to_experiment_public_key_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GDA_BALANCING_STORE_DIR", str(tmp_path / "store"))
        monkeypatch.setenv("GDA_BALANCING_ANCHOR_KEY", "a" * 64)
        example = Path(__file__).parents[1] / "examples" / "schema2" / "rpg-combat-cast"
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
        assert (
            next(
                row["value"]
                for row in metrics["samples"]
                if row["metric"] == "target_health_remaining"
            )
            == 12
        )
        assert (
            next(
                row["value"]
                for row in metrics["samples"]
                if row["metric"] == "damage_dealt"
            )
            == 4
        )
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
            (0, "input", 0, 0),
            (0, "transition", 0, 1),
            (1, "transition", 0, 3),
            (2, "transition", 0, 2),
            (2, "observation", 0, 5),
            (2, "observation", 0, 6),
        ]
        input_event, plan_event, scheduled_cast, root_cast = events[:4]
        assert trace["root_event_map"] == [
            {
                "scenario": "multi-cast",
                "root_event_ref": "raise-defense",
                "event_id": input_event["event_id"],
            },
            {
                "scenario": "multi-cast",
                "root_event_ref": "plan-casts",
                "event_id": plan_event["event_id"],
            },
            {
                "scenario": "multi-cast",
                "root_event_ref": "retry-cast",
                "event_id": root_cast["event_id"],
            },
        ]
        assert scheduled_cast["parent_event_id"] == plan_event["event_id"]
        assert plan_event["schedules"][0]["event_id"] == scheduled_cast["event_id"]
        assert plan_event["schedules"][1]["outcome"] == "canceled"
        assert (
            plan_event["cancellations"][0]["event_id"]
            == (plan_event["schedules"][1]["event_id"])
        )
        assert root_cast["outcome"]["id"] == "cast-resolved"
        assert len(snapshots) == len(events) + 1
        assert all(
            event["snapshot_before_identity"] == snapshots[index]["snapshot_identity"]
            and event["snapshot_after_identity"]
            == snapshots[index + 1]["snapshot_identity"]
            for index, event in enumerate(events)
        )
        assert events[-1]["state_after"] == [
            {"name": "actor_mana", "value": 26},
            {"name": "target_health", "value": 12},
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

    def test_schema_get_key_path(self):
        result = _run("schema", "get", "language-bundle")
        assert (result.returncode, result.stderr) == (0, "")
        artifact = json.loads(result.stdout)
        assert artifact["admission"]["admitted"] is True
        assert (
            artifact["language_bundle"]["kernel_identity"]
            == artifact["kernel"]["content_identity"]
        )
