"""Root workflow wiring regressions for the gda-balancing CI policy."""

import json
from pathlib import Path
import subprocess
import sys


_ROOT = Path(__file__).parents[1]
_WORKFLOW = _ROOT / ".github/workflows/ci.yml"
_RELEASE_WORKFLOW = _ROOT / ".github/workflows/release.yml"
_POLICY = _ROOT / "libs/gda-balancing/tools/ci.py"


def test_scope_diff_preserves_both_sides_of_cross_boundary_renames(tmp_path):
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    assert 'git diff --name-only --no-renames "$BASE_SHA" "$HEAD_SHA"' in workflow

    repository = tmp_path / "repository"
    source = repository / "libs/gda-balancing/source.py"
    destination = repository / "docs/source.py"
    source.parent.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", repository], check=True)
    subprocess.run(
        ["git", "-C", repository, "config", "user.email", "ci@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", repository, "config", "user.name", "CI test"],
        check=True,
    )
    subprocess.run(["git", "-C", repository, "add", "."], check=True)
    subprocess.run(
        ["git", "-C", repository, "commit", "-q", "-m", "source"], check=True
    )
    source.rename(destination)
    subprocess.run(["git", "-C", repository, "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", repository, "commit", "-q", "-m", "rename"], check=True
    )

    changed = subprocess.run(
        [
            "git",
            "-C",
            repository,
            "diff",
            "--name-only",
            "--no-renames",
            "HEAD^",
            "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert changed == [
        "docs/source.py",
        "libs/gda-balancing/source.py",
    ]

    classification = subprocess.run(
        [sys.executable, _POLICY, "classify", *changed],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(classification.stdout)["required"] is True

    policy_guard = subprocess.run(
        [
            sys.executable,
            _POLICY,
            "classify",
            "tests/test_balancing_ci_wiring.py",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(policy_guard.stdout)["required"] is True


def test_scheduled_unfiltered_run_has_an_isolated_non_cancelling_group():
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]

    assert "github.event_name == 'schedule'" in concurrency
    assert "github.event_name == 'workflow_dispatch'" in concurrency
    assert "format('{0}-{1}', github.event_name, github.run_id)" in concurrency
    assert "github.event_name == 'pull_request'" in concurrency
    assert "github.event_name == 'push'" in concurrency


def test_workflow_derives_shards_budgets_and_smoke_paths_from_policy():
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    release = _RELEASE_WORKFLOW.read_text(encoding="utf-8")
    action = (_ROOT / ".github/actions/setup-python-env/action.yml").read_text(
        encoding="utf-8"
    )

    assert "required-test-shards" in workflow
    assert "process-timeout required" in workflow
    assert "process-timeout unfiltered" in workflow
    assert "shard-paths smoke" in workflow
    assert "libs/gda-balancing/tests/test_e2e_cli.py" not in workflow
    assert "python3 libs/gda-balancing/tools/ci.py" not in workflow
    assert "\n    timeout-minutes: 1\n" not in workflow
    assert 'default: "latest"' in action
    assert 'uv-version: "0.11.19"' in workflow
    assert "process-timeout unfiltered" in release
    assert "verify-outcomes" in release
