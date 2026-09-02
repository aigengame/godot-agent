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

Since #802 the three gates are one function
(:func:`gda.project.containment_refusal`), so this module is no longer the only
thing holding three copies together: it is the OUTER guard over the one gate's
output, driven through each command's own entry point so a call site cannot quietly
stop routing through it. The last section pins that structurally as well.
"""

import ast
from pathlib import Path

import pytest

import gda.commands
import gda.project as project_module
from gda.commands.resource import _asset_res_path
from gda.commands.script import (
    ScriptValidateParams,
    _project_scoped_res_path,
    _script_validate_recipe,
    run_script_run_operation,
)
from gda.errors import Failure
from gda.project import (
    PROJECT_MARKER,
    containment_refusal,
    owning_project,
    path_outside_project,
)

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


# The OWNERSHIP half of the same question (#697), across the same three gates. The
# containment table above drives them from one spelling; this does the same for the
# half that was added later and had no shared row — each command was pinned only by
# its own test, so a gate could drift out of the convergence and only its own suite
# would notice (#799 review).
#
# The res:// and project-relative spellings are BOTH here because ownership anchors
# them differently on the way in (`_anchored_target`) and must still land on one
# answer.
OWNED_SPELLINGS = ["res://inner/main.gd", "inner/main.gd"]


@pytest.fixture
def nested(project: Path) -> Path:
    """The resolved project, with a second project nested one directory in."""
    inner = project / "inner"
    inner.mkdir()
    (inner / PROJECT_MARKER).write_text("config_version=5\n", encoding="utf-8")
    (inner / "main.gd").write_text("extends Node\n", encoding="utf-8")
    return inner


def _never_launched(*args, **kwargs):
    raise AssertionError("ownership must be decided before any engine launch")


def _ownership_refusals(project: Path, spelling: str) -> "list[tuple[str, object]]":
    """The three gates' answers, each at the level that BUILDS the envelope.

    Typed `object`, not the union of the three: each gate has its own success type
    and the point of every caller is the `isinstance(..., Failure)` narrowing, which
    is also the first assertion each of them makes.

    Unlike the containment table, which can ask the shared primitive directly, the
    ownership verdict is only interesting once a command has turned it into a
    refusal: the three coordinates and the re-issue sentence are built per call
    site, and that is where they drifted. Every one of these returns before an
    engine is needed — `script run`'s fake launch asserts it is never reached.
    """
    return [
        (
            "script validate",
            _script_validate_recipe(
                ScriptValidateParams(paths=[spelling]), project=project, godot=None
            ),
        ),
        (
            "script run",
            run_script_run_operation(
                script=spelling,
                godot=None,
                project=project,
                make_launch=_never_launched,
            ),
        ),
        ("resource import", _asset_res_path(project, spelling)),
    ]


@pytest.mark.parametrize("spelling", OWNED_SPELLINGS)
def test_every_gate_reaches_the_same_ownership_verdict(project, nested, spelling):
    # One nested project, three commands, one answer — asserted together for the
    # same reason the containment table is: the invariant is that they AGREE.
    for name, outcome in _ownership_refusals(project, spelling):
        assert isinstance(outcome, Failure), name
        assert outcome.error.code == "target_outside_project", name
        evidence = outcome.error.evidence
        assert evidence is not None, name
        assert evidence.owning_project == str(nested.resolve()), name
        assert evidence.target_location == str((nested / "main.gd").resolve()), name


@pytest.mark.parametrize("spelling", OWNED_SPELLINGS)
def test_every_gate_reports_the_resolved_project_root(project, nested, spelling):
    # `FailureEvidence.project_root` publishes "the project gda resolved for this
    # call, in its resolved form — the same value a successful result reports". One
    # gate did not: `_asset_res_path` reported the project as the caller spelled it,
    # so the same call answered `/tmp/…` from `resource import` and `/private/tmp/…`
    # from `script validate` on macOS (#799 review).
    #
    # The divergence is DRIVEN rather than inherited from the platform: `tmp_path`
    # is already resolved on macOS, so a fixture path alone cannot tell the two
    # readings apart and this row would pass either way. An `alias/..` hop is a
    # difference `resolve()` removes on every platform, which is what makes this an
    # assertion about the promised FORM instead of about a host's `/tmp`.
    (project.parent / "alias").mkdir()
    spelled = project.parent / "alias" / ".." / project.name

    for name, outcome in _ownership_refusals(spelled, spelling):
        assert isinstance(outcome, Failure), name
        assert outcome.error.evidence is not None, name
        assert outcome.error.evidence.project_root == str(project.resolve()), name


@pytest.mark.parametrize("spelling", OWNED_SPELLINGS)
def test_every_gate_states_the_same_reissue(project, nested, spelling):
    # The remediation is part of the shared answer too, not per-command prose: the
    # owner to pass AND the target to spell. `tests/test_e2e_res_containment.py`
    # proves the stated pair actually runs; this proves all three state it.
    for name, outcome in _ownership_refusals(project, spelling):
        assert isinstance(outcome, Failure), name
        assert (
            f"--project {nested.resolve()} and address the target as 'main.gd'"
            in outcome.error.message
        ), name


# --- The one gate (#802) -----------------------------------------------------
#
# Three call sites used to WRITE the composition above — ask ownership, build the
# four-coordinate refusal, ask containment, build the outside-root refusal — and
# the assertions before this point checked the three answers coordinate by
# coordinate. They now check the output of one function. What this section adds is
# what folding the three into it had to be checked FOR: that the site whose copy
# was ownership-only is unchanged by gaining the containment half, that the
# normalization the gate adopted answers the same on a relative `--project`, and
# that no command module can grow a fourth copy.


def _envelopes(project: Path, spelling: str) -> "dict[str, dict]":
    """The three gates' refusal envelopes for one target, keyed by command."""
    envelopes = {}
    for name, outcome in _ownership_refusals(project, spelling):
        assert isinstance(outcome, Failure), name
        envelopes[name] = outcome.error.model_dump()
    return envelopes


# Every spelling `script run`'s address gate is asked about anywhere in this
# module: the shared containment table plus the shapes that stay its own.
SCRIPT_RUN_SPELLINGS = [spelling for spelling, _ in CONTAINMENT] + [
    "res://",
    "res://.",
    "res://bar.gd ",
    "res://ba\nr.gd",
    "user://x.gd",
    # ...and the OTHER form the address gate accepts, which the claim below covers
    # and this table did not (#807 review): a project-relative path, which
    # `_project_scoped_res_path` lifts to `res://` before canonicalizing it. Plain,
    # traversing-but-contained, and escaping.
    "inner/main.gd",
    "addons/lib/../lib/tool.gd",
    "../outside.gd",
]


@pytest.mark.parametrize("spelling", SCRIPT_RUN_SPELLINGS)
def test_the_containment_half_script_run_folded_in_is_inert(project, spelling):
    # #802's fold, VERIFIED rather than assumed. `script run`'s copy asked ownership
    # only, because its address gate has already decided containment; folding it
    # into the whole gate adds the containment half, and the claim is that the
    # addition can never fire. That is exactly this assertion: whatever address
    # survives `_project_scoped_res_path` — it returns only a canonical `res://`
    # whose `res_escape_remainder` is None, refusing every other spelling first —
    # is one `path_outside_project` reads through its lexical `res://` branch and
    # answers None for. So the folded gate can only ever return what the
    # ownership-only copy returned, which is what makes the fold behavior-identical
    # and not merely equivalent on the cases someone thought to try.
    #
    # The answer is lexical, so it does not depend on the fixture holding the file;
    # the project is here only because the gate takes one.
    address = _project_scoped_res_path(spelling)
    if isinstance(address, Failure):
        # Refused at the address gate, before the shared gate is reached at all.
        return
    assert path_outside_project(address, project) is None, address


@pytest.mark.parametrize("spelling", OWNED_SPELLINGS)
def test_every_gate_answers_a_relative_project_spelling_identically(
    project, nested, spelling, monkeypatch
):
    # The row the #802 normalization needs. The gate adopts `resource import`'s
    # cwd-absolutized form (#738) for all three sites, where the two script sites
    # used to hand `owning_project` / `path_outside_project` the project AS SPELLED.
    # The two spellings were measured to agree on a relative `--project` — every
    # probe the gate makes anchors a relative path at the cwd, `Path.resolve()` and
    # `os.path.abspath` alike — and this is that measurement kept executable,
    # against the ABSOLUTE spelling's own answer rather than a restated expectation.
    #
    # It does NOT discriminate between those two normalizations, and cannot: they
    # agree, which is the finding that let the gate adopt one of them. What it holds
    # is the agreement itself — a future normalization that anchored anywhere but the
    # cwd fails here. The other way to break the normalization, RESOLVING the project
    # before the probes rather than after, is invisible to these rows and is pinned
    # by `test_the_gate_reads_the_project_as_spelled_rather_than_pre_resolved`
    # instead (#807 review).
    absolute = _envelopes(project, spelling)

    monkeypatch.chdir(project.parent)
    assert _envelopes(Path(project.name), spelling) == absolute
    # ...and the two spellings a relative one can also carry, which the two
    # normalizations reach by different routes (`Path("./game")` drops the `.`
    # before the join; `alias/../game` keeps a `..` both readings then see).
    (project.parent / "alias").mkdir()
    assert _envelopes(Path(f"./{project.name}"), spelling) == absolute
    assert _envelopes(Path("alias") / ".." / project.name, spelling) == absolute


@pytest.fixture
def monorepo(project: Path) -> Path:
    """``project`` with two sibling directories symlinked in (#807 review).

    The shared-addon layout :func:`gda.project.path_outside_project`'s ``..`` guard
    exists for, and the only input that can tell the gate's two halves — and its
    two candidate normalizations — apart. ``addons/lib`` links to a tree that IS a
    project, so ownership fires on it; ``addons/plain`` links to one that is not,
    so ownership is silent and containment decides alone. Returns the sibling tree.
    """
    libs = project.parent / "libs"
    (libs / "lib").mkdir(parents=True)
    (libs / "lib" / PROJECT_MARKER).write_text("config_version=5\n", encoding="utf-8")
    (libs / "lib" / "tool.gd").write_text("extends Node\n", encoding="utf-8")
    (libs / "plain").mkdir()
    (libs / "plain" / "tool.gd").write_text("extends Node\n", encoding="utf-8")
    (project / "addons").mkdir()
    (project / "addons" / "lib").symlink_to(Path("../../libs/lib"))
    (project / "addons" / "plain").symlink_to(Path("../../libs/plain"))
    return libs


def test_ownership_wins_when_both_halves_of_the_gate_fire(project, monorepo):
    # The ordering pin (#807 review). The gate's own docstring used to argue that
    # the two halves never both fire; they can, because their bounds differ —
    # `owning_project` stops its walk by a lexical reading it always consults, while
    # `path_outside_project` withholds the lexical reading when either side carries
    # a `..`. This target satisfies both at once: it is lexically inside `project`,
    # it resolves into a sibling tree that is its OWN project, and the `..` in its
    # spelling is what keeps containment from reading it lexically.
    #
    # Ownership must win, because it is the half that names the project to re-issue
    # against and the spelling to use. Swapping the two halves in the gate answers
    # the bare outside-root refusal on the two gates that take a filesystem path,
    # while `script run` — whose canonical `res://` address makes the containment
    # half inert — keeps answering ownership. So the assertions below are both
    # halves of the same pin: the right diagnosis, and all three still agreeing.
    target = "addons/lib/../lib/tool.gd"
    assert owning_project(target, project) is not None, "ownership half fires"
    assert path_outside_project(target, project) is not None, "containment half too"

    envelopes = _envelopes(project, target)
    for name, envelope in envelopes.items():
        assert envelope["code"] == "target_outside_project", name
        assert envelope["evidence"]["owning_project"] == str(
            (monorepo / "lib").resolve()
        ), name
    values = list(envelopes.values())
    assert values[1:] == values[:-1]


def test_the_gate_reads_the_project_as_spelled_rather_than_pre_resolved(
    project, monorepo
):
    # The other half of the normalization claim, which the spelling-equality rows
    # above cannot carry (#807 review). `project_absolute` absolutizes the project
    # but does NOT resolve it, because the double reading belongs to the probes:
    # `path_outside_project` withholds its lexical reading when either side carries
    # a `..`, so whether the PROJECT was spelled with one changes the verdict on a
    # symlinked-in target. Pre-resolving here would strip the `..` before the probe
    # ever reads it, re-enable the lexical reading, and turn this refusal into an
    # acceptance — with every other assertion in this module still green.
    #
    # `script run` is absent for the reason its own inertness test states: it reaches
    # the gate with a canonical `res://` address, which `path_outside_project`
    # answers on the escape rule alone and never reads through the filesystem.
    target = "addons/plain/tool.gd"
    (project.parent / "alias").mkdir()
    spelled = project.parent / "alias" / ".." / project.name

    # Spelled without a `..`, the lexical reading stands and the target is inside...
    assert containment_refusal(target, project) is None
    assert _import_verdict(project, target) == "res://addons/plain/tool.gd"
    # ...spelled through one, it is not, and both filesystem-path gates say so.
    for name, outcome in (
        (
            "script validate",
            _script_validate_recipe(
                ScriptValidateParams(paths=[target]), project=spelled, godot=None
            ),
        ),
        ("resource import", _import_verdict(spelled, target)),
    ):
        assert isinstance(outcome, Failure), name
        assert outcome.error.code == "target_outside_project", name


@pytest.mark.parametrize("spelling", OWNED_SPELLINGS)
def test_the_three_gates_now_emit_ONE_envelope(project, nested, spelling):
    # The sharpest form of the invariant, and the one only #802 makes checkable: the
    # three commands do not merely agree on the code and the coordinates, they emit
    # the same envelope — because one function builds it. `script run` reaches the
    # gate with the canonical `res://` address rather than the caller's spelling, so
    # this is also the statement that the anchoring makes the two forms one target.
    envelopes = list(_envelopes(project, spelling).values())
    assert envelopes[1:] == envelopes[:-1]


#: The two builders that construct a `target_outside_project` refusal once a project
#: is RESOLVED. #802's first acceptance criterion is that no command module calls
#: either: the gate owns the ordering AND the envelopes, so a command states only
#: which target it is asking about. Named here rather than inferred, so adding a
#: builder is a change this test makes someone look at.
#:
#: `gda.errors.script_escapes_project_failure` is the recorded EXCLUSION, not an
#: omission (#807 review): it builds the same code from `gda.commands.script`, and
#: legitimately, because it is `script run`'s pre-resolution address gate (ADR-0031)
#: — it decides on the spelling alone, before there is a project to be outside of,
#: and so holds none of the coordinates the gate below reports. The set is therefore
#: "the builders a command must route through the gate for", not "every builder of
#: the code".
CONTAINMENT_REFUSAL_BUILDERS = {
    "target_outside_project_failure",
    "target_owned_by_another_project_failure",
}


def _called_names(node: ast.AST) -> "set[str]":
    """Every name called under ``node``, plain or module-qualified.

    `ast.Attribute` is read as well as `ast.Name` because the guard below is a
    STRUCTURAL claim: `gda.errors.target_outside_project_failure(...)` is the same
    fourth copy as the bare name, and it passed the name-only form (#807 review).
    """
    names: set[str] = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Name):
            names.add(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            names.add(call.func.attr)
    return names


def test_no_command_module_builds_a_containment_refusal_itself():
    # The structural half of "one gate". The behavioural tests above would still
    # pass if a command grew a fourth copy that happened to agree today — which is
    # how the copies drifted in the first place (#763, then #799). Read out of the
    # source, over the whole `gda.commands` package rather than the three modules
    # that used to do it, because a NEW command asking the same question is exactly
    # the case that must route through the gate — recursively, so a future
    # `gda/commands/<group>/` subpackage is scanned too (#807 review).
    package = Path(gda.commands.__file__).parent
    offenders = {
        module.name
        for module in sorted(package.rglob("*.py"))
        if _called_names(ast.parse(module.read_text(encoding="utf-8")))
        & CONTAINMENT_REFUSAL_BUILDERS
    }

    assert offenders == set()


def test_the_gate_is_where_both_refusals_are_built():
    # The other side of the same claim: the builders did not simply lose their
    # callers. `gda.project.containment_refusal` is the one function that calls both,
    # so the ordering rule its docstring records is the ordering every command gets.
    source = ast.parse(Path(project_module.__file__).read_text(encoding="utf-8"))
    gate = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "containment_refusal"
    )

    assert _called_names(gate) & CONTAINMENT_REFUSAL_BUILDERS == (
        CONTAINMENT_REFUSAL_BUILDERS
    )
