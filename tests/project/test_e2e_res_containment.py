"""E2E: one containment answer, against the real engine (#763, #697).

The unit-level pin (``tests/project/test_res_containment_consistency.py``) drives the
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
import re
import subprocess

import pytest

from tests.conftest import project_godot
from tests.support import GODOT, Gda

gda = Gda()

INSIDE_GD = """\
extends SceneTree

func _initialize() -> void:
\tprint("ran")
\tquit(0)
"""


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
    (project / "a").mkdir()
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

    validate = gda(
        "script",
        "validate",
        script,
        "--project",
        project,
        "--json",
    )
    run = gda(
        "script",
        "run",
        script,
        "--project",
        project,
        "--timeout",
        "60",
        "--json",
    )
    imported = gda(
        "resource",
        "import",
        asset,
        "--project",
        project,
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
def test_the_engine_spells_a_fully_collapsed_address_as_the_bare_scheme(
    containment_project, tmp_path
):
    # The empty-join parity claim, measured rather than asserted lexically. Every
    # other claim in `canonical_res_path`'s step-by-step docstring had an engine
    # arm; this one — `String::simplify_path` joining an empty segment vector back
    # to the bare drive (ustring.cpp:4223-4232) — did not, and it is the row #763
    # changed. Run the engine on `res://a/..` as an entry script and read which
    # address it names back: `res://`, not `res://.`, which is what gda now
    # produces for the same spelling.
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
            "res://a/..",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    combined = proc.stdout + proc.stderr
    assert "Can't load script: res://" in combined, combined
    assert "Can't load script: res://." not in combined, combined


@pytest.mark.e2e
def test_an_asset_a_nested_project_owns_is_refused_before_the_import_pass(tmp_path):
    # The engine's own reason for the `resource import` half (#697 re-review):
    # `EditorFileSystem::_should_skip_directory` skips a directory holding a nested
    # `project.godot`, so the asset cannot be imported into the outer project at
    # all. Measured before the fix, gda accepted the request, spent a pass and
    # returned `not_importable`; the second half here shows the outer project's own
    # asset still imports, so the refusal is about ownership and not about the
    # request shape.
    outer = tmp_path / "outer"
    vendor = outer / "vendor"
    vendor.mkdir(parents=True)
    (outer / "project.godot").write_text(project_godot("outer"), encoding="utf-8")
    (vendor / "project.godot").write_text(project_godot("vendor"), encoding="utf-8")
    (vendor / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (outer / "own.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    refused = gda(
        "resource",
        "import",
        "res://vendor/pic.png",
        "--project",
        str(outer),
        "--dry-run",
        "--json",
    )
    assert refused.returncode == 4, refused.stdout + refused.stderr
    error = json.loads(refused.stdout)["error"]
    assert error["code"] == "target_outside_project"
    assert error["evidence"]["owning_project"] == str(vendor.resolve())

    accepted = gda(
        "resource",
        "import",
        "res://own.png",
        "--project",
        str(outer),
        "--dry-run",
        "--json",
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert json.loads(accepted.stdout)["assets"][0]["path"] == "res://own.png"


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
    owned = gda(
        "script",
        "validate",
        str(inner / "main.gd"),
        "--project",
        str(inner),
        "--json",
    )
    assert owned.returncode == 0, owned.stdout + owned.stderr
    assert json.loads(owned.stdout)["valid"] is True

    # Against the outer one it is refused before the engine runs, and the owner to
    # pass is named in the typed evidence.
    refused = gda(
        "script",
        "validate",
        str(inner / "main.gd"),
        "--project",
        str(outer),
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

    refused = gda("script", "validate", "game/main.gd", "--json", cwd=workspace)

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

    proc = gda("script", "validate", "scratch.gd", "--json", cwd=tmp_path)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["valid"] is True
    assert data["project_root"] is None


# The two operands the ownership refusal names, read back out of the sentence a
# caller actually gets. Non-greedy up to the one literal that separates them, so
# a project path containing the phrase cannot swallow the target.
REISSUE = re.compile(
    r"--project (?P<project>.+?) and address the target as '(?P<target>[^']*)'"
)


@pytest.fixture
def owned_target_project(tmp_path):
    """`outer`, with a nested `inner` project holding a runnable script and an asset."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "project.godot").write_text(project_godot("outer"), encoding="utf-8")
    (inner / "project.godot").write_text(project_godot("inner"), encoding="utf-8")
    (inner / "main.gd").write_text(INSIDE_GD, encoding="utf-8")
    (inner / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return outer


# (argv head, the spelling that gets refused, extra argv). One row per refusing
# command, each addressing its own kind of target in its own accepted form.
REFUSING_COMMANDS = [
    (("script", "validate"), "inner/main.gd", ()),
    (("script", "run"), "inner/main.gd", ("--timeout", "60")),
    (("resource", "import"), "inner/pic.png", ("--dry-run",)),
]


@pytest.mark.e2e
@pytest.mark.parametrize(("head", "spelling", "extra"), REFUSING_COMMANDS)
def test_the_refusal_states_a_reissue_that_actually_runs(
    owned_target_project, head, spelling, extra
):
    # The #799 review's trap, as an executable test: a remediation is only a
    # remediation if following it verbatim WORKS. It did not. "Pass --project
    # <owner>" alone leaves the caller's own spelling in place, and that spelling
    # anchors at the project (ADR-0006), so the re-issue reached a file that is not
    # there — `path_not_found` for `validate`, `script_not_found` for `run` after a
    # full engine launch. The absolute `evidence.target_location` was no help
    # either: `script run` refuses it by ADR-0031's one-address rule.
    #
    # So this reads the two operands OUT of the message and runs them. Nothing here
    # knows the fixture's layout — if the sentence is wrong, the re-issue fails.
    outer = str(owned_target_project)
    refused = gda(*head, spelling, "--project", outer, *extra, "--json")
    assert refused.returncode == 4, refused.stdout + refused.stderr
    error = json.loads(refused.stdout)["error"]
    assert error["code"] == "target_outside_project"

    stated = REISSUE.search(error["message"])
    assert stated is not None, error["message"]

    reissued = gda(
        *head,
        stated["target"],
        "--project",
        stated["project"],
        *extra,
        "--json",
    )
    assert reissued.returncode == 0, reissued.stdout + reissued.stderr

    # And the half that says WHY the target had to be named beside the project:
    # the same re-issue with the caller's original spelling still fails, so the
    # sentence is not merely decorated with a value the caller already had.
    stale = gda(
        *head,
        spelling,
        "--project",
        stated["project"],
        *extra,
        "--json",
    )
    assert stale.returncode != 0, stale.stdout


@pytest.mark.e2e
def test_the_stated_reissue_survives_a_link_spelled_owner(tmp_path):
    # The spelling the resolved coordinates cannot produce. `outer/addons/vendored`
    # links at a checkout that is its own project, so the refusal reports the
    # owner and the location RESOLVED — both under `vendor/pkg`, neither naming
    # the link the caller typed. Subtracting one from the other would still work
    # here; what would not is the file-link case in the sibling unit test, and one
    # lexical rule serves both. This pins that the link-spelled arm is executable.
    outer = tmp_path / "outer"
    (outer / "addons").mkdir(parents=True)
    (outer / "project.godot").write_text(project_godot("outer"), encoding="utf-8")
    pkg = tmp_path / "vendor" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "project.godot").write_text(project_godot("pkg"), encoding="utf-8")
    (pkg / "vend.gd").write_text(INSIDE_GD, encoding="utf-8")
    (outer / "addons" / "vendored").symlink_to(pkg, target_is_directory=True)

    refused = gda(
        "script",
        "validate",
        "addons/vendored/vend.gd",
        "--project",
        str(outer),
        "--json",
    )
    assert refused.returncode == 4, refused.stdout + refused.stderr
    stated = REISSUE.search(json.loads(refused.stdout)["error"]["message"])
    assert stated is not None
    assert stated["target"] == "vend.gd"

    reissued = gda(
        "script",
        "validate",
        stated["target"],
        "--project",
        stated["project"],
        "--json",
    )
    assert reissued.returncode == 0, reissued.stdout + reissued.stderr
    assert json.loads(reissued.stdout)["valid"] is True
