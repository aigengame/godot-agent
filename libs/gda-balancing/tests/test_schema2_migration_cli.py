"""Public CLI vectors for limited Standard Schema 1.x source migration."""

import json
from pathlib import Path


def test_model_migrate_publishes_a_buildable_source_and_audit_report(
    tmp_path: Path, run_cli
) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "meta": {"name": "legacy.parameters"},
                "parameters": {"hit_points": 100},
            }
        ),
        encoding="utf-8",
    )
    migrated = tmp_path / "migrated.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "migrate",
            str(legacy),
            "--out",
            str(migrated),
            "--invocation-key",
            "1" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    assert [item["logical_name"] for item in receipt["member_locators"]] == [
        "migration-report",
        "model-source-package",
    ]
    source = json.loads(migrated.read_text(encoding="utf-8"))
    assert source == {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "legacy.parameters",
            "version": "1.0.0",
            "entry_module": "main",
        },
        "package_requirements": [{"id": "core.quantity", "version": "2.0.0"}],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.0.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": [
                    {
                        "symbol": "parameter.hit_points",
                        "type": "quantity",
                        "role": "parameter",
                        "representation": "Int",
                        "kind": "scalar",
                        "unit": "1",
                        "domain_kind": "closed-interval",
                        "domain": {"minimum": 100, "maximum": 100},
                        "numeric_policy": "exact-int64",
                    }
                ],
            }
        ],
    }
    report_path = next(
        Path(item["locator"])
        for item in receipt["member_locators"]
        if item["logical_name"] == "migration-report"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["artifact_kind"] == "migration-report"
    assert report["source_schema_version"] == "1.0.0"
    assert report["target_schema_version"] == "2.0.0"
    assert report["output_identity"].startswith("sha256:")
    assert report["deprecated_constructs"] == []
    assert report["refusals"] == []

    built = run_cli(
        [
            "model",
            "build",
            str(migrated),
            "--out",
            str(tmp_path / "resolved.json"),
            "--invocation-key",
            "2" * 64,
        ]
    )
    assert (built[0], built[2]) == (0, "")
