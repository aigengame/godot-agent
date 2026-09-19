"""A ``~user`` this host cannot resolve is a literal name, never a traceback (#988).

``Path.expanduser()`` raises ``RuntimeError`` for a ``~unknownuser/…`` prefix, and
four caller-supplied path options expanded a tilde on their own: ``--godot``,
``--user-data-root``, ``skill --install --dir``, and ``export``'s two artifact
paths. Each printed a Rich traceback and exited 1 with no `Error envelope` at all,
breaking the ADR-0002 / ADR-0004 invariant that every gda failure is typed. They
now share the project resolver's total expansion
(:func:`gda.project.expand_user`), which keeps such a value literal the way bash
and ``os.path.expanduser`` do.

These arms live TOGETHER because they are one rule with one authority, and because
the rule is only legible as a set: the amendment to #988 splits the four into two
outcome classes, and a reader has to see both to know which one an option is in.

- A READ address answers through its own resolution, because nothing carries that
  literal name: ``--godot`` gives the ordinary ``binary_not_found``.
- A WRITE destination is an ordinary relative directory under the invocation cwd,
  created where it can be: ``--user-data-root``, ``--dir`` and ``--output``. A
  literal ``~unknownuser`` directory beside the caller is the outcome, not a
  defect — it is what the shell does with the same value.

No new error code, no path-existence check, no per-command guard: the fix is the
shared helper, and these are the gates that keep it shared.
"""

import json

import pytest
from typer.testing import CliRunner

from gda.cli import app
from gda.commands.export import (
    normalize_export_output_path,
    normalize_smoke_artifact_path,
)
from gda.runner import USER_DATA_ROOT_ENV, set_user_data_root

# A user name no host resolves. Digits keep it out of the way of a real account.
UNKNOWN_USER = "~unknownuser988"


@pytest.fixture(autouse=True)
def _no_root_override():
    """Keep the process-wide ``--user-data-root`` override off between arms."""
    set_user_data_root(None)
    yield
    set_user_data_root(None)


def test_an_unresolvable_home_on_godot_is_the_binary_not_found_envelope(
    tmp_path, monkeypatch
):
    # The READ class. The literal name reaches the spawn, no file carries it, and
    # the runner synthesizes its existing not-found result — so the caller reads
    # the envelope it would get for any missing binary, at exit 127, with the value
    # it passed echoed back. Before #988 this was a RuntimeError traceback at exit 1.
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
