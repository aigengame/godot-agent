"""One containment answer for a ``res://`` target, across every gate (#763).

Three commands ask one domain question — "does this target belong to the resolved
project?" — and each used to answer it its own way. On the single input
``res://../outside.gd`` they agreed by luck; on ``res://foo/../bar.gd`` they did
not, and NOTHING caught it, because each command's suite only ever asked its own
gate. That is what this module exists to prevent: it drives all three gates from
ONE spelling table, so a future change that fixes or breaks one of them without
the others fails here rather than in a user's project.

The gates, at the level where each makes the decision (no engine needed):

- ``script validate`` — :func:`gda.project.path_outside_project`, the ADR-0006
  authority, applied by its recipe to every path in the batch;
- ``script run`` — :func:`gda.commands.script._project_scoped_res_path`, its
  pre-launch address gate, which reaches the same rule through
  :func:`gda.project.res_escape_remainder` because it runs before project
  resolution;
- ``resource import`` — :func:`gda.commands.resource._asset_res_path`, which since
  #763 calls the authority itself instead of its own ``".." in parts`` check.

What is deliberately NOT uniform is stated as such below: ``script run`` refuses a
few shapes the other two accept, and those refusals are its own — verdict-matching
rules about how the engine echoes an address back on stderr, not containment.
"""

from pathlib import Path

import pytest

from gda.commands.resource import _asset_res_path
from gda.commands.script import _project_scoped_res_path
from gda.errors import Failure
from gda.project import PROJECT_MARKER, path_outside_project

# (spelling, contained) — the ONE verdict every gate must reach.
CONTAINMENT = [
    # Plain, and the three spellings that canonicalize to it. Every one of these
    # was accepted by both script gates and REFUSED by `resource import`, whose
    # gate inspected path parts before any collapsing (`res://foo/../bar.gd`,
    # net-inside) or read a leading slash as an absolute path (`res:///bar.gd`).
    ("res://bar.gd", True),
    ("res://foo/../bar.gd", True),
    ("res://./bar.gd", True),
    ("res:///bar.gd", True),
    ("res://a//..//bar.gd", True),
    # The separator the engine folds before it collapses anything
    # (`String::simplify_path`, ustring.cpp:4192). `resource import` split with
    # `PurePosixPath`, so this was ONE segment holding no `..` — admitted on POSIX,
    # and on native Windows the join reaches the parent directory.
    ("res://foo\\..\\bar.gd", True),
    # A filename that merely STARTS with two dots is a real file, not a traversal.
    ("res://..foo.gd", True),
    # Escapes: still climbing after the collapse, in both separators.
    ("res://../outside.gd", False),
    ("res://..", False),
    ("res://a/../../outside.gd", False),
    ("res://..\\outside.gd", False),
    ("res://a\\..\\..\\outside.gd", False),
]

# The canonical address the two gates that PRODUCE one must agree on. `script
# validate` produces none — it hands the path to the engine, which canonicalizes
# it itself — so it is absent here and present in the containment table above.
ALIASES = [
    ("res://bar.gd", "res://bar.gd"),
    ("res://foo/../bar.gd", "res://bar.gd"),
    ("res://./bar.gd", "res://bar.gd"),
    ("res:///bar.gd", "res://bar.gd"),
    ("res://a//..//bar.gd", "res://bar.gd"),
    ("res://foo\\..\\bar.gd", "res://bar.gd"),
    ("res://..foo.gd", "res://..foo.gd"),
]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    proj = tmp_path / "game"
    proj.mkdir()
    (proj / PROJECT_MARKER).write_text("config_version=5\n", encoding="utf-8")
    return proj


def _import_verdict(project: Path, spelling: str) -> "str | Failure":
    return _asset_res_path(project, spelling)


def _refused_as_outside(outcome: "str | Failure") -> bool:
    return (
        isinstance(outcome, Failure) and outcome.error.code == "target_outside_project"
    )


@pytest.mark.parametrize(("spelling", "contained"), CONTAINMENT)
def test_every_gate_reaches_the_same_containment_verdict(project, spelling, contained):
    # THE regression this module exists for. Asserting the three together in one
    # test — rather than three tests that happen to use the same input — is
    # deliberate: the invariant is that they AGREE, so a divergence must fail one
    # assertion, not silently pass two suites as it did before #763.
    validate = path_outside_project(spelling, project) is None
    run = _project_scoped_res_path(spelling)
    imported = _import_verdict(project, spelling)

    assert validate is contained, "script validate"
    assert _refused_as_outside(run) is not contained, "script run"
    assert _refused_as_outside(imported) is not contained, "resource import"


@pytest.mark.parametrize(("spelling", "canonical"), ALIASES)
def test_every_gate_that_produces_an_address_produces_the_same_one(
    project, spelling, canonical
):
    # Agreeing on the verdict is not enough: two gates hand an address onward — one
    # to the engine's `--script` argv, one to the import request — and a caller
    # reading both back must see one identity for one file.
    assert _project_scoped_res_path(spelling) == canonical
    assert _import_verdict(project, spelling) == canonical


def test_the_rules_that_stay_script_run_s_own_are_stated_here(project):
    # #763 acceptance: the PR must say which rules moved and which deliberately did
    # not, and this is that statement in executable form. Each of these is about
    # VERDICT MATCHING — keeping the canonical identity matchable against what the
    # engine echoes back on stderr — or about a script address naming a file rather
    # than a directory. None is containment, so none is imposed on the other gates,
    # and each is refused under `script run`'s own `invalid_path` ABI edge
    # (ADR-0031) rather than under the shared containment code.
    for spelling in (
        "res://",  # the project ROOT: a directory, not a script
        "res://.",  # ...and its second spelling, now folded to the first
        "res://bar.gd ",  # a trailing code point Godot's strip_edges removes
        "res://ba\nr.gd",  # an engine-log line boundary inside the address
        "user://x.gd",  # another engine scheme
    ):
        outcome = _project_scoped_res_path(spelling)
        assert isinstance(outcome, Failure), spelling
        assert outcome.error.code == "invalid_path", spelling
        # ...and the other two gates are NOT made to share them: the root address
        # is contained by both, and `user://` is refused by `resource import` for a
        # reason of its own (it names no project asset), never as an escape.
        assert not _refused_as_outside(_import_verdict(project, spelling)), spelling


def test_an_absolute_outside_path_is_one_question_asked_by_two_gates(project, tmp_path):
    # The row that looks like a divergence and is not, kept explicit so a reader
    # does not "fix" it: `script run` refuses EVERY absolute path as a FORM
    # question (ADR-0031 — its addresses are project-scoped, full stop, and it
    # never resolves one against the filesystem), while `resource import` accepts
    # an absolute path INSIDE the project and asks containment about it. So the two
    # codes differ here because the two questions do, and the containment answer
    # itself is still the one shared answer.
    inside = project / "pic.png"
    outside = tmp_path / "elsewhere.png"

    assert _refused_as_outside(_import_verdict(project, str(outside)))
    assert _import_verdict(project, str(inside)) == "res://pic.png"

    for spelling in (str(inside), str(outside)):
        outcome = _project_scoped_res_path(spelling)
        assert isinstance(outcome, Failure), spelling
        assert outcome.error.code == "invalid_path", spelling
