"""A ``~user`` this host cannot resolve is a literal name, never a traceback (#988).

``Path.expanduser()`` raises ``RuntimeError`` for a ``~unknownuser/…`` prefix, and
seven sites in ``src/gda`` expanded a tilde on their own. Each printed a Rich
traceback and exited 1 with no `Error envelope` at all, breaking the ADR-0002 /
ADR-0004 invariant that every gda failure is typed. They now share the project
resolver's total expansion (:func:`gda.project.expand_user`), which keeps such a
value literal the way bash and ``os.path.expanduser`` do.

These arms live TOGETHER because they are one rule with one authority, and because
the rule is only legible as a set: the four caller-supplied OPTIONS split into two
outcome classes, and a reader has to see both to know which one an option is in.

- A READ address is resolved as the literal path it names, and what is there
  decides: ``--godot`` gives the ordinary ``binary_not_found`` when nothing
  carries that name, and launches the file when something does.
- A WRITE destination is an ordinary relative directory under the invocation cwd,
  created where it can be: ``--user-data-root``, ``--dir`` and ``--output``. A
  literal ``~unknownuser`` directory beside the caller is the outcome, not a
  defect — it is what the shell does with the same value.

The last three arms are a different shape: they RE-EXPAND a path
``resolve_project_dir`` already expanded, so they raise only when a directory
literally named ``~unknownuser…`` exists and holds a ``project.godot`` — the
resolver then hands the literal on and the second expansion refuses it. The
remedy is the same one helper, so they belong to the same rule.

No new error code, no path-existence check, no per-command guard: the fix is the
shared helper, and these are the gates that keep it shared.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.export import (
    normalize_export_output_path,
    normalize_smoke_artifact_path,
)
from gda.daemon.discovery import daemon_paths
from gda.runner import USER_DATA_ROOT_ENV, RunResult, set_user_data_root
from tests.support import invoke_cli, sentinel

# A user name no host resolves. Digits keep it out of the way of a real account.
UNKNOWN_USER = "~unknownuser988"

# What a project addressed by that literal name needs to BE one, so the resolver
# accepts it and hands the literal on to the site under test.
LITERAL_PROJECT = f"{UNKNOWN_USER}/p"


def _literal_project(tmp_path: Path) -> Path:
    """Make ``<tmp_path>/~unknownuser988/p`` a Godot project and return it."""
    project = tmp_path / UNKNOWN_USER / "p"
    project.mkdir(parents=True)
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    return project


@pytest.fixture(autouse=True)
def _no_root_override():
    """Keep the process-wide ``--user-data-root`` override off between arms."""
    set_user_data_root(None)
    yield
    set_user_data_root(None)


def test_an_unresolvable_home_on_godot_is_the_binary_not_found_envelope(
    tmp_path, monkeypatch
):
    # The READ class. The literal name reaches the spawn as the relative path it
    # is; a temporary cwd holds no such file, so the runner synthesizes its existing
    # not-found result — the envelope any missing binary gives, at exit 127, with the
    # value the caller passed echoed back. Before #988 this was a RuntimeError
    # traceback at exit 1. It is the ABSENCE that decides: a real file under that
    # literal name would be launched like any other binary.
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app, ["info", "--godot", f"{UNKNOWN_USER}/godot", "--json"]
    )

    assert result.exit_code == 127, result.stdout
    err = json.loads(result.stdout)["error"]
    assert err["category"] == "environment"
    assert err["code"] == "binary_not_found"
    assert f"{UNKNOWN_USER}/godot" in err["message"]


def test_an_unresolvable_home_on_the_user_data_root_is_a_directory_under_the_cwd(
    tmp_path, monkeypatch
):
    # The WRITE class, on the option that is prepared BEFORE the spawn: the root is
    # taken as the relative directory it literally names, the placement is created
    # under it, and the run then fails on the binary alone. Both halves are asserted
    # because either alone would pass a fix that dropped the option on the floor.
    monkeypatch.delenv(USER_DATA_ROOT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "--user-data-root",
            f"{UNKNOWN_USER}/data",
            "info",
            "--godot",
            "/nonexistent/godot",
            "--json",
        ],
    )

    assert result.exit_code == 127, result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "binary_not_found"
    assert (tmp_path / UNKNOWN_USER / "data" / "logs" / "godot.log").exists()


def test_an_unresolvable_home_on_the_skill_install_dir_writes_under_the_cwd(
    tmp_path, monkeypatch
):
    # The WRITE class, on the option that succeeds: the install creates the literal
    # directory beside the caller and reports the file it wrote there. A relative
    # `--dir` has always been reported as the caller spelled it, so the literal name
    # on `installed_path` is that same rule, not a new disclosure.
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app, ["skill", "--install", "--dir", f"{UNKNOWN_USER}/skills", "--json"]
    )

    assert result.exit_code == 0, result.stdout
    installed = tmp_path / UNKNOWN_USER / "skills" / "SKILL.md"
    assert installed.is_file()
    assert json.loads(result.stdout)["installed_path"] == (
        f"{UNKNOWN_USER}/skills/SKILL.md"
    )


def test_an_unresolvable_home_on_the_export_output_reaches_the_typed_refusal(
    tmp_path, monkeypatch
):
    # The WRITE class, on the option whose value is normalized by a pydantic
    # validator: the value is accepted, so the command body runs on and answers with
    # the next typed refusal it reaches. Before #988 the validator itself raised, so
    # no body ran at all.
    #
    # The refusal chosen is `--project` naming a directory that is not a Godot
    # project, because `resolve_project_dir` raises it CLI-side, before the engine is
    # asked for anything. Letting the command run PROJECTLESS instead makes the
    # outcome depend on the host: with an engine installed it reaches the operation's
    # own `project_not_found`, and on a machine without one it reaches
    # `binary_not_found` first (CI, run 35435970121).
    monkeypatch.delenv("GDA_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    not_a_project = tmp_path / "not-a-godot-project"
    not_a_project.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "export",
            "run",
            "--preset",
            "nosuch",
            "--output",
            f"{UNKNOWN_USER}/x",
            "--project",
            str(not_a_project),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["code"] == "project_not_found"


def test_both_export_path_normalizers_keep_an_unresolvable_home_literal(
    tmp_path, monkeypatch
):
    # The shared half under both annotations, pinned directly: one total expansion,
    # then the ordinary absolutization. The smoke wrapper carried its own guard for
    # this (#979) while `--output` crashed; the guard now lives on the half they
    # share, so this asserts the pair rather than either one.
    monkeypatch.chdir(tmp_path)
    expected = str(tmp_path / UNKNOWN_USER / "x")

    assert normalize_export_output_path(f"{UNKNOWN_USER}/x") == expected
    assert normalize_smoke_artifact_path(f"{UNKNOWN_USER}/x") == expected


# --------------------------------------------------------------------------
# The three re-expansion sites: a project the resolver already expanded
# --------------------------------------------------------------------------


def test_scene_validate_accepts_a_project_whose_literal_name_starts_with_a_tilde(
    tmp_path, monkeypatch
):
    # `_scene_validate_recipe` expanded the resolved project a SECOND time to stamp
    # `project_root` on the verdict. The resolver had already kept the literal name,
    # so the second expansion is the one that refused it. Engine-free: the runner
    # seam is the fake `invoke_cli` injects.
    project = _literal_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result, _ = invoke_cli(
        monkeypatch,
        [
            "scene",
            "validate",
            "res://main.tscn",
            "--project",
            LITERAL_PROJECT,
            "--json",
        ],
        stdout=sentinel({"path": "res://main.tscn", "valid": True, "problems": []}),
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["project_root"] == str(project.resolve())


def test_scene_preflight_accepts_a_project_whose_literal_name_starts_with_a_tilde(
    tmp_path, monkeypatch
):
    # The same second expansion in `run_scene_preflight_operation`, which stamps the
    # same field on the preflight verdict. This channel does not go through
    # `cmd.emit`, so its engine step is `gda.commands.scene.launch` — canned here.
    project = _literal_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    ready = sentinel({"path": "res://main.tscn", "status": "ready"})
    monkeypatch.setattr(
        "gda.commands.scene.launch",
        lambda binary, args, *, cwd, timeout, timeout_label="Godot", watch=None: (
            RunResult(stdout=ready, stderr="", exit_code=0)
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "scene",
            "preflight",
            "res://main.tscn",
            "--project",
            LITERAL_PROJECT,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["project_root"] == str(project.resolve())


def test_daemon_paths_accept_a_project_whose_literal_name_starts_with_a_tilde(
    tmp_path, monkeypatch
):
    # `daemon_paths` expands its `project` argument again to canonicalize it, and
    # every daemon command derives its socket, pidfile and session log from the
    # result — so the same literal name refused `gda daemon status --project` before
    # any daemon was contacted. Called directly: the derivation is pure, and the
    # value it returns is what the rest of the identity is keyed on.
    project = _literal_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert daemon_paths(Path(LITERAL_PROJECT)).project == project.resolve()
