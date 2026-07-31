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

    def test_schema_get_key_path(self):
        result = _run("schema", "get", "language-bundle")
        assert (result.returncode, result.stderr) == (0, "")
        artifact = json.loads(result.stdout)
        assert artifact["admission"]["admitted"] is True
        assert (
            artifact["language_bundle"]["kernel_identity"]
            == artifact["kernel"]["content_identity"]
        )
