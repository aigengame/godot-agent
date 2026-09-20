"""``gda export run``'s use of the `Project tree inventory` (#839, #985).

The native export runs the editor import pass over the project, so it creates the
cache and the sidecars beside the sources and can rewrite generated resources.
GDA-DF-067 saw about 14,000 such files appear on disk while ``warnings`` stayed
empty. These tests drive the real recipe —
:func:`gda.commands.export.run_export_operation` — with an export runner that
MUTATES the project the way the pass does, and pin what only the export knows:
the artifact it keeps out of the walk, the report's published shape and counts,
its human rendering, and the success-only boundary the second walk sits behind.

The walk and the settlement under all of it belong to :mod:`gda.project_tree`,
whose rules are named one by one in ``tests/project_tree/`` — one package for the
module, none of its rule tests in a consumer's package. These ten stay HERE
because they change when this group's report changes, not when the module does
(#985, and PR #836's rule that test packages are drawn by reason to change). The
recipe's own suite is ``test_export_run_operation.py``; the real-engine proof is
``test_e2e_export_run.py``.
"""

import os
from pathlib import Path
from typing import Callable, Optional

import pytest
from pydantic import ValidationError

from gda.commands.export import (
    ExportRunMode,
    _artifact_to_exclude,
    ExportRunResult,
    ProjectTreeMutations,
    render_export_run,
    run_export_operation,
)
from gda.errors import Failure
from gda.harness.install import install_harness
from gda.import_evidence import CACHE_ROOT_REL
from gda.project_tree import ProjectTreeInventory
from gda.runner import RunResult
from tests.support import (
    ENGINE_BANNER,
    FakeRunner,
    minimal_project,
    sentinel,
    unlistable,
)

# The preset the canned `export get` resolve returns. `export run` resolves the
# preset through that sentinel op before it exports anything, so every test here
# needs one; the configured export_path puts the artifact INSIDE the project,
# which is the case the exclusion rules are about.
_PRESET = {
    "index": 0,
    "name": "Linux/X11",
    "platform": "Linux/X11",
    "runnable": True,
    "export_path": "build/game.x86_64",
    "templates_installed": True,
    "templates_version": "4.6.3.stable",
    "templates_root": "/data/Godot/export_templates",
    "templates_root_host": None,
}


def _get_runner() -> FakeRunner:
    """The canned ``export get`` resolve the recipe runs before every export."""
    return FakeRunner(
        RunResult(stdout=ENGINE_BANNER + sentinel(_PRESET), stderr="", exit_code=0)
    )


class MutatingExportRunner:
    """A fake native export that CHANGES the project, as the import pass does.

    The one seam this suite needs and :class:`tests.support.FakeExportRunner` does
    not have: the report is about what the tree looks like after the export, so the
    fake has to write the cache, the sidecars and the rewritten resources itself.
    """

    def __init__(
        self, mutate: Callable[[], object], *, exit_code: int = 0, stderr: str = ""
    ) -> None:
        self.mutate = mutate
        self.result = RunResult(stdout="", stderr=stderr, exit_code=exit_code)
        self.calls: list[tuple[str, str, str]] = []

    def run(self, preset: str, mode: str, output_path: str) -> RunResult:
        self.calls.append((preset, mode, output_path))
        self.mutate()
        return self.result


def _export(
    project: Path,
    mutate: Callable[[], object] = lambda: None,
    *,
    exit_code: int = 0,
    output_override: Optional[str] = None,
) -> "ExportRunResult | Failure":
    """Run the real recipe against ``project`` with a mutating export runner."""
    return run_export_operation(
        preset="Linux/X11",
        mode=ExportRunMode.RELEASE,
        output_override=output_override,
        godot="/tmp/Godot",
        project=project,
        make_runner=lambda binary, project=None: _get_runner(),
        make_export_runner=lambda binary, project=None: MutatingExportRunner(
            mutate, exit_code=exit_code
        ),
    )


def _mutations(outcome: "ExportRunResult | Failure") -> ProjectTreeMutations:
    """The report of a successful export, or a readable failure."""
    assert isinstance(outcome, ExportRunResult), outcome
    return outcome.project_tree_mutations


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_the_artifact_and_its_created_dirs_are_not_mutations(tmp_path):
    # AC4: the export's own output is not a mutation of the project — not the
    # artifact, not the files inside an artifact that is a DIRECTORY (a macOS
    # `.app` bundle), and not the parent directories gda created for it (#402),
    # which are directories and so are never reported by a walk over FILES.
    project = minimal_project(tmp_path)

    def mutate() -> None:
        bundle = project / "build" / "game.x86_64"
        _write(bundle / "Contents" / "MacOS" / "game", "binary")
        _write(bundle / "Contents" / "Info.plist", "plist")

    outcome = _export(project, mutate)
    mutations = _mutations(outcome)

    assert isinstance(outcome, ExportRunResult)
    assert outcome.created_dirs == [str(project / "build")]
    assert mutations.created == []
    assert mutations.created_count == 0
    assert mutations.skipped == 0


def test_the_export_destination_resolves_to_the_artifact_kept_out(tmp_path):
    # Output-path POLICY, and it is this GROUP's: the shared inventory takes a
    # `Path` and knows only how to keep it out, so what a destination string means
    # is decided here (PR #989 external review). The engine resolves `res://`
    # against the project root, so the report resolves it the same way; another
    # virtual scheme names nothing in this tree; a relative filesystem destination
    # is the project's, and an absolute one is taken as given, because a
    # destination outside the project can still be visible through a directory
    # link inside it.
    project = minimal_project(tmp_path)

    assert _artifact_to_exclude(project, "res://out.pck") == project / "out.pck"
    assert (
        _artifact_to_exclude(project, "res:///build/game.pck")
        == project / "build" / "game.pck"
    )
    assert _artifact_to_exclude(project, "res://") is None
    assert _artifact_to_exclude(project, "user://out.pck") is None
    assert _artifact_to_exclude(project, "") is None
    assert (
        _artifact_to_exclude(project, "build/game.x86_64")
        == project / "build" / "game.x86_64"
    )
    outside = tmp_path / "elsewhere" / "game.x86_64"
    assert _artifact_to_exclude(project, str(outside)) == outside


def test_a_res_output_artifact_is_the_output_not_a_mutation(tmp_path):
    # `--output res://out.pck` is a destination INSIDE the project: the engine
    # resolves `res://` against the project root, so the artifact lands in the tree
    # both walks cover. Dropping every `://` spelling put it in `created` as
    # `source_adjacent`, reproduced on a real pack export (PR #981 review round 3).
    project = minimal_project(tmp_path)

    outcome = _export(
        project,
        lambda: _write(project / "out.pck", "pack"),
        output_override="res://out.pck",
    )

    assert isinstance(outcome, ExportRunResult), outcome
    assert outcome.output_path == "res://out.pck"
    assert (project / "out.pck").is_file()
    assert _mutations(outcome).created == []
    assert _mutations(outcome).skipped == 0


@pytest.mark.parametrize("use_res_path", [True, False])
def test_an_output_under_a_directory_link_is_excluded_by_identity(
    tmp_path, use_res_path
):
    # Both spellings of the same destination resolve to one artifact path, which
    # the inventory then keeps out by its parent's filesystem identity and its own
    # name. The sibling beside it stays visible.
    project = minimal_project(tmp_path / "game")
    shared = tmp_path / "shared"
    shared.mkdir()
    (project / "assets").symlink_to(shared, target_is_directory=True)
    output = (
        "res://assets/out.pck" if use_res_path else str(project / "assets" / "out.pck")
    )

    def mutate() -> None:
        _write(shared / "out.pck", "pack")
        _write(shared / "sibling.import", "sidecar")

    mutations = _mutations(_export(project, mutate, output_override=output))

    assert [entry.path for entry in mutations.created] == [
        "res://assets/sibling.import"
    ]
    assert mutations.skipped == 0


def test_a_file_beside_the_artifact_is_reported_in_a_gda_created_parent(tmp_path):
    # The exclusion is the artifact and its OWN subtree, one rule for both cases.
    # A Linux preset with `binary_format/embed_pck=false` writes `game.pck` beside
    # the binary, and that file IS something the export left in the project. Before
    # round 3 it was reported when `build/` existed already and silently dropped
    # when gda created it — the same call, two answers.
    project = minimal_project(tmp_path)

    def mutate() -> None:
        _write(project / "build" / "game.x86_64", "binary")
        _write(project / "build" / "game.x86_64.pck", "pack")

    outcome = _export(project, mutate)

    assert isinstance(outcome, ExportRunResult), outcome
    assert outcome.created_dirs == [str(project / "build")]
    assert [entry.path for entry in _mutations(outcome).created] == [
        "res://build/game.x86_64.pck"
    ]
    assert _mutations(outcome).skipped == 0


def test_the_created_and_rewritten_entries_carry_the_published_res_spelling(tmp_path):
    # The adapter's own rule: the module answers in project-relative paths, and the
    # report publishes `res://` ones, with the counts and the byte totals derived
    # from its own lists. A created file carries the shared classifier's verdict
    # and its size; a rewritten one carries both sizes.
    project = minimal_project(tmp_path)
    generated = _write(project / "i18n" / "ui.translation", "old bytes")

    def mutate() -> None:
        _write(project / CACHE_ROOT_REL / "uid_cache.bin", "uid")
        _write(project / "icon.png.import", "[remap]")
        generated.write_text("new bytes here", encoding="utf-8")

    mutations = _mutations(_export(project, mutate))

    assert mutations.cache_root == "res://" + CACHE_ROOT_REL
    assert [
        (entry.path, entry.classification, entry.size) for entry in mutations.created
    ] == [
        ("res://.godot/uid_cache.bin", "cache_owned", 3),
        ("res://icon.png.import", "source_adjacent", 7),
    ]
    assert [
        (entry.path, entry.size, entry.size_before) for entry in mutations.modified
    ] == [("res://i18n/ui.translation", 14, 9)]
    assert (mutations.created_count, mutations.created_bytes) == (2, 10)
    assert (mutations.created_cache_owned, mutations.created_source_adjacent) == (1, 1)
    assert (mutations.modified_count, mutations.modified_bytes) == (1, 14)


def test_the_harness_strip_and_restore_is_not_a_mutation(tmp_path):
    # `export run` strips the dev-only harness before the native export and
    # restores it byte for byte afterwards (ADR-0028). That is gda's own
    # bookkeeping, not something the export did to the project, so the walks are
    # taken AROUND it: the harness files are present in both, with equal content,
    # and the restore's fresh timestamps meet the content rule rather than the
    # timestamp.
    project = minimal_project(tmp_path)
    install_harness(project)

    mutations = _mutations(_export(project))

    assert mutations.created == []
    assert mutations.modified == []
    assert mutations.skipped == 0


def test_a_failed_export_reports_no_mutations_and_pays_for_no_second_walk(
    tmp_path, monkeypatch
):
    # The report is a property of a COMPLETED export: a non-zero native export
    # answers through the error envelope, which carries no such record. The second
    # walk is the SETTLEMENT, and the recipe settles on the success branch only,
    # so a failure does not pay for it — counted here rather than described, since
    # "we skip the work" is exactly the kind of claim that rots.
    #
    # Counted at the seam this group actually uses: `settle` is the public method
    # `classify_export_run` calls, so this test knows nothing about the module's
    # internals (PR #989 review round 2).
    real_settle = ProjectTreeInventory.settle
    project = minimal_project(tmp_path)
    settlements: list[ProjectTreeInventory] = []

    def counting_settle(inventory: ProjectTreeInventory):
        settlements.append(inventory)
        return real_settle(inventory)

    monkeypatch.setattr(ProjectTreeInventory, "settle", counting_settle)

    failed = _export(
        project, lambda: _write(project / "icon.png.import", "x"), exit_code=1
    )
    assert isinstance(failed, Failure), failed
    assert failed.error.code == "export_failed"
    assert settlements == []

    succeeded = _export(project, lambda: _write(project / "other.import", "x"))
    assert isinstance(succeeded, ExportRunResult), succeeded
    assert len(settlements) == 1


def test_the_human_render_summarizes_the_counts(tmp_path):
    # The human channel gets the counts, never the entries: a cold-cache export
    # creates thousands of cache files, and printing them would bury the export the
    # line is reporting. The JSON result carries the lists.
    project = minimal_project(tmp_path)
    generated = _write(project / "ui.translation", "old")

    def mutate() -> None:
        _write(project / CACHE_ROOT_REL / "uid_cache.bin", "uid")
        _write(project / "icon.png.import", "[remap]")
        generated.write_text("rewritten", encoding="utf-8")

    outcome = _export(project, mutate)
    assert isinstance(outcome, ExportRunResult), outcome

    rendered = render_export_run(outcome)

    assert rendered.splitlines()[-1] == (
        "  project tree: 2 created (1 under res://.godot, 1 beside the sources, "
        "10 bytes), 1 rewritten (9 bytes)"
    )
    assert "res://icon.png.import" not in rendered


def test_the_quiet_render_names_the_scope_it_vouches_for(tmp_path):
    # An export that changed nothing the report covers says exactly that, rather
    # than "unchanged": a warm export rewrites its own cache bookkeeping on every
    # run, and the walks deliberately do not compare those files, so the bare word
    # would claim more than the report holds (PR #981 review measured a warm export
    # rewriting `.godot/editor/filesystem_cache10` under an "unchanged" line).
    project = minimal_project(tmp_path)

    outcome = _export(project)
    assert isinstance(outcome, ExportRunResult), outcome

    assert render_export_run(outcome).splitlines() == [
        f"exported Linux/X11 (Linux/X11, release) -> {project / 'build' / 'game.x86_64'}",
        f"  project tree: unchanged outside res://{CACHE_ROOT_REL}",
    ]


def test_an_unreadable_file_is_named_in_the_render(tmp_path):
    # The skipped count is the whole disclosure, and it reaches the human channel
    # too — on the quiet line as much as on the counted one, because a record that
    # could not read part of the tree must not print as a clean one.
    project = minimal_project(tmp_path)
    os.symlink("nowhere", project / "dangling.tres")

    outcome = _export(project)
    assert isinstance(outcome, ExportRunResult), outcome

    assert render_export_run(outcome).splitlines()[-1] == (
        f"  project tree: unchanged outside res://{CACHE_ROOT_REL}, 1 unreadable"
    )


def test_one_unreadable_inode_is_counted_once_in_the_published_report(tmp_path):
    # #990's declared behaviour delta, on this command's own published count: an
    # unreadable directory that a link inside the project reaches a second time is
    # ONE entry the report could not account for, not two. The report has counted
    # spellings since #839 and #985 kept that while it moved the walk; the count
    # here was 2 before and is 1 now.
    project = minimal_project(tmp_path)
    locked = project / "locked"
    _write(locked / "secret.tres", "old")
    (project / "alias").symlink_to(locked, target_is_directory=True)
    if not unlistable(locked):
        pytest.skip("this platform lets the owner list a mode-000 directory")

    try:
        mutations = _mutations(_export(project))
    finally:
        locked.chmod(0o755)

    assert mutations.skipped == 1
    assert (mutations.created, mutations.modified) == ([], [])


def test_the_counts_must_match_the_reported_lists():
    # gda's own invariant: the counts exist so a caller can read the summary
    # without walking a list of thousands of cache files, which is worth nothing
    # unless the two agree.
    report = {
        "created": [
            {
                "path": "res://icon.png.import",
                "classification": "source_adjacent",
                "size": 7,
            }
        ],
        "created_count": 1,
        "created_cache_owned": 0,
        "created_source_adjacent": 1,
        "created_bytes": 99,
    }

    with pytest.raises(ValidationError):
        ProjectTreeMutations.model_validate(report)


def test_the_default_report_is_the_one_an_unchanged_export_produces():
    # The field is additive (AC6): a result built without it carries the report of
    # an export that changed nothing, and that report still names the cache root.
    empty = ProjectTreeMutations()

    assert empty.cache_root == "res://" + CACHE_ROOT_REL
    assert (empty.created, empty.modified) == ([], [])
    assert (empty.created_count, empty.modified_count, empty.skipped) == (0, 0, 0)
