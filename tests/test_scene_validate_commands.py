"""S3: ``gda scene validate`` through the full CLI pipeline against a fake runner (#664).

The static half of #664 (dogfooding GDA-DF-040): a sentinel op like the rest of the
``scene`` group, exercised here with canned engine output — Typer → runner → sentinel
parse → typed model → JSON — plus the one part that is NOT the engine's, the
``project_root`` its recipe stamps on the verdict (the #658 rule applied to the scene
group, where every problem reported is a ``res://`` resolution outcome).
"""

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from gda.cli import app
from gda.commands.scene import SceneProblemKind, SceneStartupStatus
from tests.support import (
    assert_operation_error,
    invoke_cli,
    minimal_project,
    sentinel,
)

# One invalid verdict as the engine reports it: the op's own payload, WITHOUT the
# project_root the CLI adds afterwards.
INVALID_PAYLOAD = {
    "path": "res://main.tscn",
    "valid": False,
    "problems": [
        {
            "kind": "missing_resource",
            "scene": "res://main.tscn",
            "path": "res://gone.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        },
        {
            "kind": "unloadable_resource",
            "scene": "res://main.tscn",
            "path": "res://art/hero.png",
            "type": "Texture2D",
            "nodes": ["Body/Sprite"],
            "message": "the file exists but no ResourceLoader can open it",
        },
    ],
}

# A COMPOSED verdict (#721): the parent is sound on its own, and both problems
# were found in the scenes it instances — one a broken dependency, one the cycle
# that stopped the walk.
COMPOSED_PAYLOAD = {
    "path": "res://parent.tscn",
    "valid": False,
    "problems": [
        {
            "kind": "missing_resource",
            "scene": "res://child.tscn",
            "path": "res://gone.gd",
            "type": "Script",
            "nodes": ["."],
            "message": "the referenced file does not exist",
        },
        {
            "kind": "cyclic_instance",
            "scene": "res://child.tscn",
            "path": "res://parent.tscn",
            "type": "PackedScene",
            "nodes": ["Loop"],
            "message": "the scene at this path is an ancestor in the instancing chain",
        },
    ],
}

VALID_PAYLOAD = {"path": "res://main.tscn", "valid": True, "problems": []}


def test_valid_scene_reports_the_verdict_and_exits_zero(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    result, fake = invoke_cli(
        monkeypatch,
        ["scene", "validate", "res://main.tscn", "--project", str(project), "--json"],
        stdout=sentinel(VALID_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "path": "res://main.tscn",
        "valid": True,
        "problems": [],
        # Always present, never inferred: the root the res:// dependencies were
        # resolved against (#658's rule, #664's application of it).
        "project_root": str(project.resolve()),
    }
    assert fake.calls == [("scene-validate", {"path": "res://main.tscn"})]


def test_invalid_scene_is_a_successful_operation_with_problems(monkeypatch, tmp_path):
    # THE CRUX: an invalid scene exits 0 with valid=false — the verdict is read from
    # the result, never from the process status (the script validate contract, applied
    # to scenes).
    project = minimal_project(tmp_path)
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "validate", "res://main.tscn", "--project", str(project), "--json"],
        stdout=sentinel(INVALID_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert [problem["kind"] for problem in data["problems"]] == [
        "missing_resource",
        "unloadable_resource",
    ]
    # Each problem names the dependency, what the scene declared it to be, and which
    # nodes reference it — the three facts an agent acts on.
    assert data["problems"][0]["path"] == "res://gone.gd"
    assert data["problems"][0]["type"] == "Script"
    assert data["problems"][1]["nodes"] == ["Body/Sprite"]


def test_projectless_run_reports_a_null_project_root(monkeypatch, tmp_path):
    # Projectless is a legitimate context (ADR-0006's fallback), and the key is still
    # present so an agent reads it unconditionally.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "validate", "/tmp/loose.tscn", "--json"],
        stdout=sentinel(VALID_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["project_root"] is None


def test_params_json_drives_the_same_recipe(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    result, fake = invoke_cli(
        monkeypatch,
        [
            "scene",
            "validate",
            "--params-json",
            json.dumps({"path": "res://main.tscn"}),
            "--project",
            str(project),
            "--json",
        ],
        stdout=sentinel(VALID_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert fake.calls == [("scene-validate", {"path": "res://main.tscn"})]
    assert json.loads(result.stdout)["project_root"] == str(project.resolve())


def test_human_output_leads_with_the_verdict_then_the_evidence(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "validate", "res://main.tscn", "--project", str(project)],
        stdout=sentinel(INVALID_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    # Conclusion first, then the project (a wrong root explains every problem under
    # it), then one block per problem.
    assert lines[0] == "invalid res://main.tscn (2 problems)"
    assert lines[1] == f"  project: {project.resolve()}"
    assert lines[2] == "  missing_resource: res://gone.gd (Script)"
    assert lines[3] == "    the referenced file does not exist"
    assert lines[4] == "    nodes: ."


def test_a_composed_verdict_attributes_each_problem_to_the_scene_it_was_found_in(
    monkeypatch, tmp_path
):
    # The #721 crux on the CLI side: a verdict about `parent.tscn` whose problems
    # both live in `child.tscn`. Without `scene` an agent reads them as the
    # parent's, and each problem's `nodes` — relative to the scene that owns
    # them — resolve against the wrong tree.
    project = minimal_project(tmp_path)
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "validate", "res://parent.tscn", "--project", str(project), "--json"],
        stdout=sentinel(COMPOSED_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert [problem["scene"] for problem in data["problems"]] == [
        "res://child.tscn",
        "res://child.tscn",
    ]
    # The cycle is a verdict kind of its own, not a message an agent has to parse.
    assert data["problems"][1]["kind"] == SceneProblemKind.CYCLIC_INSTANCE.value
    assert data["problems"][1]["path"] == "res://parent.tscn"


def test_human_output_names_the_sub_scene_a_problem_was_found_in(monkeypatch, tmp_path):
    project = minimal_project(tmp_path)
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "validate", "res://parent.tscn", "--project", str(project)],
        stdout=sentinel(COMPOSED_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "invalid res://parent.tscn (2 problems)"
    assert lines[2] == "  missing_resource: res://gone.gd (Script)"
    # The owning file, before the message: `nodes: .` below means the root of
    # child.tscn, not of the scene that was validated.
    assert lines[3] == "    in res://child.tscn"
    assert lines[5] == "    nodes: ."


def test_human_output_stays_silent_about_the_scene_the_command_was_given(
    monkeypatch, tmp_path
):
    # The `in` line is attribution, not decoration: an ordinary single-file verdict
    # would only be made longer by repeating the path already in its headline.
    project = minimal_project(tmp_path)
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "validate", "res://main.tscn", "--project", str(project)],
        stdout=sentinel(INVALID_PAYLOAD),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "    in " not in result.stdout


def test_an_operation_failure_is_still_an_error_envelope(monkeypatch, tmp_path):
    # The shared addressing ladder does not fork for validate: a missing file is a
    # refusal, not a verdict.
    project = minimal_project(tmp_path)
    payload = {
        "error": {"code": "path_not_found", "message": "scene file does not exist"}
    }
    result, _ = invoke_cli(
        monkeypatch,
        ["scene", "validate", "res://gone.tscn", "--project", str(project), "--json"],
        stdout=sentinel(payload),
        exit_code=1,
    )

    assert_operation_error(result, "path_not_found")


# --- The cross-language enum contract (#664) --------------------------------
#
# `operations.gd` WRITES these strings into the sentinel and the pydantic enums
# READ them, so a drift in either spelling turns a real verdict into a
# `contract_violation` at parse time. Pinned the way every other cross-language
# mirror in this repo is (cf. `VALIDATE_MARKER` in tests/test_script_commands.py):
# scrape the const VALUES out of the payload, so the pin survives any change to
# where they are used and fails only when the CONTRACT moves. It is a non-e2e test
# on purpose — the drift is invisible without a real engine otherwise, and the e2e
# tier does not run in PR CI.

_SCENE_PROBLEM_CONST = re.compile(
    r'^const SCENE_PROBLEM_[A-Z_]+ := "(.*)"$', re.MULTILINE
)
_SCENE_STARTUP_CONST = re.compile(
    r'^const SCENE_STARTUP_[A-Z_]+ := "(.*)"$', re.MULTILINE
)


def _operations_consts(pattern: re.Pattern[str]) -> set[str]:
    operations = (
        Path(__file__).resolve().parents[1] / "src" / "gda" / "ops" / "operations.gd"
    )
    found = set(pattern.findall(operations.read_text(encoding="utf-8")))
    assert found, "no matching consts found in operations.gd"
    return found


def test_scene_problem_kinds_mirror_the_operations_gd_consts():
    assert _operations_consts(_SCENE_PROBLEM_CONST) == {
        kind.value for kind in SceneProblemKind
    }


def test_scene_startup_statuses_mirror_the_operations_gd_consts():
    # `timeout` is gda's OWN verdict — no engine ever reports it, so it is
    # deliberately absent from the GDScript side and excluded here. Every value the
    # ENGINE can send must have a member; a member gda mints itself must not need one.
    assert _operations_consts(_SCENE_STARTUP_CONST) == {
        status.value for status in SceneStartupStatus
    } - {SceneStartupStatus.TIMEOUT.value}


def test_the_rendered_help_keeps_the_bracketed_scene_file_tokens():
    # `[gd_scene]` / `[ext_resource]` / `[sub_resource]` look exactly like Rich
    # style tags, so an unescaped docstring RENDERS without them — the published
    # help read "no complete  header" (#720 recheck ×2). Pin the rendered output,
    # not the source: the escape is load-bearing.

    from tests.support import plain_text

    result = CliRunner().invoke(app, ["scene", "validate", "--help"])

    assert result.exit_code == 0, result.stdout
    text = " ".join(plain_text(result.stdout).split())
    assert "no complete [gd_scene] header" in text
    assert "an unresolvable [ext_resource] referenced from a [sub_resource]" in text
