"""E2E: one containment answer, against the real engine (#763, #697).

The unit-level pin (``tests/test_res_containment_consistency.py``) drives the
three gates directly and proves they AGREE. This proves the agreement is the
ENGINE's: for every spelling below the three commands reach the same verdict, and
that verdict is what a real Godot 4.6.3 does with the same address.

Why it has to be e2e. The disagreement #763 reconciles was invisible to every unit
suite, and two of its halves are only true against a real engine:

- ``res://foo/../bar.gd`` collapses net-inside, and the engine really does load
  ``res://bar.gd`` for it. ``resource import`` refused that address while both
  script commands ran it; deciding for the authority means the accepted arm has to
  work, not merely be accepted;
- ``res://..\\outside.gd`` is the escape the engine treats as one — Godot folds
  ``\\`` to ``/`` across a ``res://`` address before it collapses anything
  (``String::simplify_path``, ustring.cpp:4192) — so the refusal is right only
  because the engine reads the separator that way.

The ownership arms (#697) are e2e for the reason GDA-DF-035 is a dogfooding report
rather than a unit fixture: the false ``res://`` dependency cascade is something a
real engine produces, and the claim is that gda now never lets it be produced.
"""

import json
import subprocess

import pytest

from gda.binary import resolve_godot_binary
from tests.conftest import project_godot
from tests.support import GDA_CMD

GODOT = resolve_godot_binary()

INSIDE_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("ran")
\tquit(0)
"""


def _run_gda(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*GDA_CMD, *args], capture_output=True, text=True)


def _code(proc: subprocess.CompletedProcess) -> "str | None":
    try:
        return json.loads(proc.stdout)["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None


@pytest.fixture
def containment_project(tmp_path):
    """A project with an inside script and asset, plus outside twins one level up."""
    project = tmp_path / "game"
    (project / "foo").mkdir(parents=True)
    (project / "project.godot").write_text(project_godot(), encoding="utf-8")
    (project / "bar.gd").write_text(INSIDE_GD, encoding="utf-8")
    (project / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "outside.gd").write_text(INSIDE_GD, encoding="utf-8")
    (tmp_path / "outside.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return project


# (spelling template, contained). `{n}` is the basename the command needs, so one
# table serves a script command and an asset command.
SPELLINGS = [
    ("res://{n}", True),
    # Net-inside: refused by `resource import` alone until #763.
    ("res://foo/../{n}", True),
    ("res://./{n}", True),
    # Leading slash: refused by `resource import` alone, with a message about a
    # `..` the address does not contain. Godot's `split("/", false)` drops the
    # empty segment.
    ("res:///{n}", True),
    # Repeated separators collapse, as `simplify_path`'s `//`-run loop does. The
    # intermediate directory here is a REAL one, deliberately: gda's answer is
    # lexical, but `script validate` hands the spelling to the engine unchanged and
    # the engine's file access resolves `..` through the filesystem — so
    # `res://nosuchdir/../bar.gd` is a truthful `path_not_found` from the engine
    # even though it is lexically net-inside. That is not a containment verdict and
    # is not this slice's to change (the op-side spelling is #775's territory);
    # this table is about what gda decides.
    ("res://foo//..//{n}", True),
    # The separator the engine folds. Inside here...
    ("res://foo\\..\\{n}", True),
    # ...and the escape there, which `resource import` used to admit (one
    # `PurePosixPath` segment, no `..` in it) and only a later existence check
    # stopped — on Windows it would have reached the parent directory.
    ("res://..\\outside{ext}", False),
    ("res://../outside{ext}", False),
    ("res://a\\..\\..\\outside{ext}", False),
]


@pytest.mark.e2e
@pytest.mark.parametrize(("template", "contained"), SPELLINGS)
def test_the_three_commands_agree_on_a_res_spelling(
    containment_project, template, contained
):
    project = str(containment_project)
    script = template.format(n="bar.gd", ext=".gd")
    asset = template.format(n="pic.png", ext=".png")

    validate = _run_gda(
        "script",
        "validate",
        script,
        "--project",
        project,
        "--godot",
        str(GODOT),
        "--json",
    )
    run = _run_gda(
        "script",
        "run",
        script,
        "--project",
        project,
        "--godot",
        str(GODOT),
        "--timeout",
        "60",
        "--json",
    )
    imported = _run_gda(
        "resource",
        "import",
        asset,
        "--project",
        project,
        "--godot",
        str(GODOT),
        "--dry-run",
        "--json",
    )

    if contained:
        # The engine really resolves it: `validate` compiles the file, `run`
        # executes it and reports the ONE canonical address, `import` names the
        # same asset. Accepting an address that then fails to load would be a
        # different bug wearing the same green.
        assert validate.returncode == 0, validate.stdout + validate.stderr
        assert json.loads(validate.stdout)["valid"] is True
        assert run.returncode == 0, run.stdout + run.stderr
        ran = json.loads(run.stdout)
        assert ran["path"] == "res://bar.gd", ran
        assert "ran" in ran["stdout"]
        assert imported.returncode == 0, imported.stdout + imported.stderr
        assert json.loads(imported.stdout)["assets"][0]["path"] == "res://pic.png"
    else:
        # ONE code, from three commands, on every spelling of the escape — the
        # thing #763 exists to make true. Before: `project_not_found`,
        # `invalid_path` and `invalid_params` (or, for the backslash spelling,
        # admission followed by a "does not exist" refusal).
        for name, proc in (
            ("validate", validate),
            ("run", run),
            ("import", imported),
        ):
            assert proc.returncode == 4, name + ": " + proc.stdout + proc.stderr
            assert _code(proc) == "target_outside_project", name + ": " + proc.stdout


@pytest.mark.e2e
def test_the_engine_agrees_the_escape_leaves_the_project(containment_project, tmp_path):
    # The claim under the refusal, measured rather than assumed: the address gda
    # refuses is the one the engine would resolve OUTSIDE the project. Run the
    # engine directly (no gda gate in the way) on the backslash spelling and read
    # back which file it loaded — the engine reports the slash spelling of the
    # parent-directory path, which is exactly why folding `\` is not cosmetic.
    (tmp_path / "outside.gd").write_text(
        "extends SceneTree\n\nfunc _initialize() -> void:\n\tprint("
        '"OUTSIDE RAN")\n\tquit(0)\n',
        encoding="utf-8",
    )
    log = tmp_path / "engine.log"

    proc = subprocess.run(
        [
            str(GODOT),
            "--headless",
            "--log-file",
            str(log),
            "--path",
            str(containment_project),
            "--script",
            "res://..\\outside.gd",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert "OUTSIDE RAN" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.e2e
def test_a_script_a_nested_project_owns_is_refused_instead_of_falsely_invalid(tmp_path):
    # GDA-DF-035 reading 2, reproduced and then closed. `outer` and `outer/inner`
    # are both projects; `inner/main.gd` preloads `res://local_dep.gd`, which
    # exists beside it. Validated with `--project outer` the engine reported
    # `Parse Error: Preload file "res://local_dep.gd" does not exist.` — a file
    # that is perfectly valid in its own project. The engine still would; gda no
    # longer asks it.
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "project.godot").write_text(project_godot("outer"), encoding="utf-8")
    (inner / "project.godot").write_text(project_godot("inner"), encoding="utf-8")
    (inner / "local_dep.gd").write_text("extends RefCounted\n", encoding="utf-8")
    (inner / "main.gd").write_text(
        'extends Node\n\nconst Dep := preload("res://local_dep.gd")\n', encoding="utf-8"
    )

    # Against its OWN project the verdict is the true one, and stays reachable.
    owned = _run_gda(
        "script",
        "validate",
        str(inner / "main.gd"),
        "--project",
        str(inner),
        "--godot",
        str(GODOT),
        "--json",
    )
    assert owned.returncode == 0, owned.stdout + owned.stderr
    assert json.loads(owned.stdout)["valid"] is True

    # Against the outer one it is refused before the engine runs, and the owner to
    # pass is named in the typed evidence.
    refused = _run_gda(
        "script",
        "validate",
        str(inner / "main.gd"),
        "--project",
        str(outer),
        "--godot",
        str(GODOT),
        "--json",
    )
    assert refused.returncode == 4, refused.stdout + refused.stderr
    error = json.loads(refused.stdout)["error"]
    assert error["code"] == "target_outside_project"
    assert error["evidence"]["owning_project"] == str(inner.resolve())
    # No engine ran, so the false cascade does not exist to be misread.
    assert "diagnostics" not in json.loads(refused.stdout)


@pytest.mark.e2e
def test_a_projectless_call_on_an_owned_script_is_refused(tmp_path):
    # GDA-DF-035 reading 1, the EXACT dogfooded invocation: a project nested in a
    # plain workspace, validated from the ancestor. Nothing resolved, the file went
    # to a projectless engine, and its `res://` preload resolved against nothing —
    # the same cascade, with `project_root: null` as the only clue.
    workspace = tmp_path / "workspace"
    game = workspace / "game"
    game.mkdir(parents=True)
    (game / "project.godot").write_text(project_godot("game"), encoding="utf-8")
    (game / "local_dep.gd").write_text("extends RefCounted\n", encoding="utf-8")
    (game / "main.gd").write_text(
        'extends Node\n\nconst Dep := preload("res://local_dep.gd")\n', encoding="utf-8"
    )

    refused = subprocess.run(
        [
            *GDA_CMD,
            "script",
            "validate",
            "game/main.gd",
            "--godot",
            str(GODOT),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=str(workspace),
    )

    assert refused.returncode == 4, refused.stdout + refused.stderr
    error = json.loads(refused.stdout)["error"]
    assert error["code"] == "target_outside_project"
    assert error["evidence"]["owning_project"] == str(game.resolve())
    # No root resolved, so that coordinate is omitted rather than invented.
    assert "project_root" not in error["evidence"]


@pytest.mark.e2e
def test_a_standalone_script_is_still_validated_projectless(tmp_path):
    # The boundary the refusal above must not cross: ADR-0006's projectless
    # fallback still serves the files it was written for — a loose `.gd` that no
    # project.godot claims.
    scratch = tmp_path / "scratch.gd"
    scratch.write_text(
        "extends Node\n\nfunc go() -> int:\n\treturn 1\n", encoding="utf-8"
    )

    proc = subprocess.run(
        [*GDA_CMD, "script", "validate", "scratch.gd", "--godot", str(GODOT), "--json"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["valid"] is True
    assert data["project_root"] is None
