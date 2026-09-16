"""The project-tree mutation report of ``gda export run`` (#839).

The native export runs the editor import pass over the project, so it creates the
cache and the sidecars beside the sources and can rewrite generated resources.
GDA-DF-067 saw about 14,000 such files reported as ``warnings: []``. These tests
drive the real recipe — :func:`gda.commands.export.run_export_operation` — with an
export runner that MUTATES the project the way the pass does, so every rule the
report states is exercised end to end: what is created, what counts as rewritten,
what is excluded, and what a file the walk cannot read does to a successful
export.

The recipe's own suite is ``tests/export/test_export_run_operation.py``; this one
is about the report the recipe now carries. The real-engine proof is
``tests/export/test_e2e_export_run.py``.
"""

import os
import threading
from pathlib import Path
from typing import Callable, Optional

import pytest
from pydantic import ValidationError

from gda.commands.export import (
    ExportRunMode,
    ExportRunResult,
    ProjectTreeMutations,
    render_export_run,
    run_export_operation,
)
from gda.errors import Failure
from gda.harness.install import install_harness
from gda.import_evidence import CACHE_ROOT_REL
from gda.runner import RunResult
from tests.support import ENGINE_BANNER, FakeRunner, minimal_project, sentinel

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


def test_created_files_are_classified_against_the_shared_cache_root(tmp_path):
    # AC1: an export against a cold cache reports the cache files and the sidecars
    # it created, each classified, with counts and bytes. The two classes are the
    # `resource import` vocabulary because they come from the same function, and
    # the reported root is the constant that function reads.
    project = minimal_project(tmp_path)
    _write(project / "icon.png", "png")

    def mutate() -> None:
        _write(project / CACHE_ROOT_REL / "imported" / "icon.png-ab.ctex", "12345")
        _write(project / CACHE_ROOT_REL / "uid_cache.bin", "uid")
        _write(project / "icon.png.import", "[remap]")

    mutations = _mutations(_export(project, mutate))

    assert mutations.cache_root == "res://" + CACHE_ROOT_REL
    assert [
        (entry.path, entry.classification, entry.size) for entry in mutations.created
    ] == [
        ("res://.godot/imported/icon.png-ab.ctex", "cache_owned", 5),
        ("res://.godot/uid_cache.bin", "cache_owned", 3),
        ("res://icon.png.import", "source_adjacent", 7),
    ]
    assert mutations.created_count == 3
    assert mutations.created_cache_owned == 2
    assert mutations.created_source_adjacent == 1
    assert mutations.created_bytes == 15
    assert mutations.modified == []


def test_the_classification_is_the_shared_function_not_a_local_rule(
    tmp_path, monkeypatch
):
    # #839's reuse criterion, pinned rather than described: the export path asks
    # `gda.import_evidence.classify_created_file` at BOTH of the places it needs a
    # verdict, and a rule restated at either one would stop asking.
    #
    # The settlement's use is visible in the answer — a stub verdict reaches the
    # report. The PRE-EXPORT walk's use is not: it only decides which files to
    # hash, and a wrongly hashed cache file is passed over by the settlement
    # anyway, so the stub RECORDS what it was asked about and the export runner
    # snapshots that record before it mutates anything. Whatever is in the
    # snapshot was asked during the first walk (PR #981 review found the second
    # half pinned by nothing).
    project = minimal_project(tmp_path)
    _write(project / "already_here.tres", "old")
    asked: list[str] = []
    asked_before_the_export: list[str] = []

    def recording_stub(rel: str) -> str:
        asked.append(rel)
        return "cache_owned"

    monkeypatch.setattr("gda.commands.export.classify_created_file", recording_stub)

    def mutate() -> None:
        asked_before_the_export.extend(asked)
        _write(project / "beside_the_source.import", "x")

    mutations = _mutations(_export(project, mutate))

    assert "already_here.tres" in asked_before_the_export
    assert [entry.classification for entry in mutations.created] == ["cache_owned"]
    assert mutations.created_cache_owned == 1
    assert mutations.created_source_adjacent == 0


def test_a_rewritten_file_is_modified_and_carries_both_sizes(tmp_path):
    # AC3, the reported half: the pass rewrites a generated resource, and the
    # record names it with the size it had and the size it has. `size_before` is
    # the fact only the pre-export walk can state.
    project = minimal_project(tmp_path)
    generated = _write(project / "i18n" / "ui.translation", "old bytes")

    mutations = _mutations(
        _export(
            project, lambda: generated.write_text("new bytes here", encoding="utf-8")
        )
    )

    assert [
        (entry.path, entry.size, entry.size_before) for entry in mutations.modified
    ] == [("res://i18n/ui.translation", 14, 9)]
    assert mutations.modified_count == 1
    assert mutations.modified_bytes == 14
    assert mutations.created == []


def test_a_touched_file_whose_content_is_equal_is_not_modified(tmp_path):
    # AC3, the other half: the import pass touches far more files than it rewrites,
    # and a changed timestamp alone would bury the few rewrites the record is
    # about. The file below is a CANDIDATE (its mtime moved) and is then cleared by
    # its digest.
    project = minimal_project(tmp_path)
    touched = _write(project / "i18n" / "ui.translation", "same bytes")

    def mutate() -> None:
        touched.write_text("same bytes", encoding="utf-8")
        later = os.stat(touched).st_mtime_ns + 5_000_000_000
        os.utime(touched, ns=(later, later))

    mutations = _mutations(_export(project, mutate))

    assert mutations.modified == []
    assert mutations.modified_count == 0
    assert mutations.modified_bytes == 0


def test_a_rewrite_that_keeps_the_size_and_the_timestamp_is_not_a_candidate(tmp_path):
    # The candidate rule's declared blind spot, pinned so it stays a decision. Only
    # a file whose size or mtime moved is hashed after the export; that is what
    # bounds the cost on a tree the pass touches wholesale. A rewrite that restores
    # both is invisible — no engine pass does this, but the rule says so out loud.
    project = minimal_project(tmp_path)
    resource = _write(project / "generated.tres", "aaaa")
    before = os.stat(resource)

    def mutate() -> None:
        resource.write_text("bbbb", encoding="utf-8")
        os.utime(resource, ns=(before.st_atime_ns, before.st_mtime_ns))

    mutations = _mutations(_export(project, mutate))

    assert mutations.modified == []
    assert resource.read_text(encoding="utf-8") == "bbbb"


def test_a_pre_existing_cache_file_is_never_reported_as_rewritten(tmp_path):
    # The cache is reported as ONE unit through `cache_root`: a pre-existing cache
    # file is not hashed before the export and cannot enter `modified`. Hashing the
    # cache would cost more than the fact is worth — the dogfooding case holds
    # about 1.1 GiB there — and the record is about the tracked files beside it.
    project = minimal_project(tmp_path)
    cached = _write(project / CACHE_ROOT_REL / "uid_cache.bin", "old cache")

    mutations = _mutations(
        _export(project, lambda: cached.write_text("rewritten cache", encoding="utf-8"))
    )

    assert mutations.modified == []
    assert mutations.created == []


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


def test_a_res_output_artifact_is_the_output_not_a_mutation(tmp_path):
    # `--output res://out.pck` is a destination INSIDE the project: the engine
    # resolves `res://` against the project root, so the artifact lands in the
    # tree both walks cover. Dropping every `://` spelling put it in `created` as
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


def test_a_top_level_git_directory_is_not_walked(tmp_path):
    # The engine does not write to `.git`, and hashing an object database would
    # dominate the cost of a report about the project's own files — the same
    # ground `resource import`'s walker drops it on.
    project = minimal_project(tmp_path)
    _write(project / ".git" / "HEAD", "ref: refs/heads/main")

    mutations = _mutations(
        _export(
            project, lambda: _write(project / ".git" / "objects" / "ab" / "cd", "x")
        )
    )

    assert mutations.created == []
    assert mutations.skipped == 0


def test_a_directory_link_is_walked_as_the_engine_reads_it(tmp_path):
    # The engine's import scan follows a directory link, so a shared library
    # linked into the project is content the pass writes sidecars into and rewrites
    # generated resources in. `os.walk` leaves it out by default, and the report
    # then stated neither — with `skipped` at zero, so nothing said the record was
    # incomplete (PR #981 review round 3, measured on a real pack export).
    project = minimal_project(tmp_path / "game")
    shared = tmp_path / "shared"
    _write(shared / "ui.csv", "keys,en\nGREET,Hello\n")
    generated = _write(shared / "ui.en.translation", "old")
    (project / "assets").symlink_to(shared, target_is_directory=True)

    def mutate() -> None:
        _write(shared / "ui.csv.import", "[remap]")
        generated.write_text("rewritten bytes", encoding="utf-8")

    mutations = _mutations(_export(project, mutate))

    # Reported under the spelling the walk reached them by, which is the res://
    # path the engine names them by too.
    assert [entry.path for entry in mutations.created] == ["res://assets/ui.csv.import"]
    assert [entry.path for entry in mutations.modified] == [
        "res://assets/ui.en.translation"
    ]
    assert mutations.modified[0].size_before == 3
    assert mutations.skipped == 0


def test_a_link_that_leads_back_up_the_chain_is_not_re_entered(tmp_path):
    # Identity, not spelling: `sub/loop -> ..` reaches a directory the walk has
    # already walked, so it is not re-entered and the walk ends by rule rather
    # than at the OS path limit. The content under the loop is reported ONCE,
    # under its first spelling, and a cycle is not unaccounted content — `skipped`
    # stays at zero.
    #
    # Run on a thread with a deadline, like the FIFO test: a regression that walks
    # the cycle must read RED rather than wedge the suite.
    project = minimal_project(tmp_path / "game")
    _write(project / "sub" / "asset.tres", "[gd_resource]")
    (project / "sub" / "loop").symlink_to("..", target_is_directory=True)
    outcome: list = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            _export(project, lambda: _write(project / "sub" / "asset.tres.import", "x"))
        ),
        daemon=True,
    )

    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive(), "the walk did not terminate on a symlink cycle"

    mutations = _mutations(outcome[0])
    assert [entry.path for entry in mutations.created] == [
        "res://sub/asset.tres.import"
    ]
    assert mutations.modified == []
    assert mutations.skipped == 0


def test_a_file_the_walk_cannot_read_is_skipped_not_failed(tmp_path):
    # The disclosure rule: a vanished or unreadable file must not turn a SUCCESSFUL
    # export into a failure. All three shapes are counted and none enters a list,
    # because "created" and "rewritten" are both claims the walk cannot make about
    # a file it never read. The third one is the reason the settlement asks first
    # whether the pre-export walk could read the path at all: the link RESOLVES
    # after the export, so a settlement that only asked "was this path recorded?"
    # would announce a file the project already had as one the export created.
    project = minimal_project(tmp_path)
    os.symlink("nowhere", project / "before.tres")
    os.symlink("target.tres", project / "resolves.tres")

    def mutate() -> None:
        os.symlink("nowhere", project / "during.tres")
        _write(project / "target.tres", "generated")
        _write(project / "icon.png.import", "[remap]")

    outcome = _export(project, mutate)
    mutations = _mutations(outcome)

    assert mutations.skipped == 3
    assert [entry.path for entry in mutations.created] == [
        "res://icon.png.import",
        "res://target.tres",
    ]
    assert mutations.modified == []


def _unlistable(directory: Path) -> bool:
    """Make ``directory`` unlistable, and say whether the platform agreed."""
    directory.chmod(0o000)
    try:
        os.listdir(directory)
    except OSError:
        return True
    directory.chmod(0o755)
    return False


def test_a_directory_the_walk_cannot_list_is_counted_not_ignored(tmp_path):
    # `os.walk` swallows a listdir failure by default, which would drop the whole
    # subtree from the report AND from the one channel that says the record is
    # incomplete. The directory is counted once — not its unknown contents, which
    # neither walk ever saw (PR #981 review).
    project = minimal_project(tmp_path)
    locked = project / "locked"
    _write(locked / "secret.tres", "old")
    if not _unlistable(locked):
        pytest.skip("this platform lets the owner list a mode-000 directory")

    try:
        mutations = _mutations(_export(project))
    finally:
        locked.chmod(0o755)

    assert mutations.skipped == 1
    assert mutations.created == []
    assert mutations.modified == []


def test_a_file_under_a_locked_directory_is_not_announced_as_created(tmp_path):
    # The readable-after case, which is the one that states a FALSE fact rather
    # than an incomplete one: the pre-export walk could not list the directory, so
    # a file the project already had must not be reported as one the export
    # created once the directory opens up.
    project = minimal_project(tmp_path)
    locked = project / "locked"
    _write(locked / "secret.tres", "old")
    if not _unlistable(locked):
        pytest.skip("this platform lets the owner list a mode-000 directory")

    try:
        mutations = _mutations(_export(project, lambda: locked.chmod(0o755)))
    finally:
        locked.chmod(0o755)

    assert [entry.path for entry in mutations.created] == []
    assert mutations.modified == []
    assert mutations.skipped == 1


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFOs only")
def test_a_non_regular_entry_is_counted_and_never_opened(tmp_path):
    # The inventory reads REGULAR files only. A FIFO answers `stat` like any file
    # and then blocks `open()` until a writer appears, which hung the whole
    # command — outside every timeout, with no result and no envelope (PR #981
    # review round 2). Sockets and devices reached the skipped channel already,
    # by raising instead of blocking; the rule is now one rule for the family.
    #
    # The export runs on a thread with a deadline, so a regression reads RED here
    # instead of wedging the suite.
    project = minimal_project(tmp_path)
    fifo = project / "pipe.dat"
    os.mkfifo(fifo)
    outcome: list = []
    worker = threading.Thread(
        target=lambda: outcome.append(_export(project)), daemon=True
    )

    worker.start()
    worker.join(timeout=15)
    if worker.is_alive():
        # Release the blocked reader so the worker can unwind, then fail.
        try:
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        worker.join(timeout=5)
        raise AssertionError("the inventory opened a FIFO and blocked on it")

    mutations = _mutations(outcome[0])
    assert mutations.skipped == 1
    assert mutations.created == []
    assert mutations.modified == []


def test_a_same_size_rewrite_with_a_newer_timestamp_is_reported(tmp_path):
    # The candidate gate is size OR timestamp, and this is the timestamp half: a
    # rewrite of the same length still moves the mtime, so the file is compared
    # and its changed bytes reach `modified`. A size-only gate would drop every
    # same-size rewrite — the record's headline fact — and stay green everywhere
    # else, because the e2e's translations grow (PR #981 review round 2).
    project = minimal_project(tmp_path)
    generated = _write(project / "ui.translation", "aaaa")

    def mutate() -> None:
        generated.write_text("bbbb", encoding="utf-8")
        later = os.stat(generated).st_mtime_ns + 5_000_000_000
        os.utime(generated, ns=(later, later))

    mutations = _mutations(_export(project, mutate))

    assert [
        (entry.path, entry.size, entry.size_before) for entry in mutations.modified
    ] == [("res://ui.translation", 4, 4)]


def test_the_exclusions_match_whole_path_components(tmp_path):
    # The exclusions are PREFIX-of-path-components, never prefix-of-string. That
    # separator is what keeps `.gitignore` and `.github/` out of the `.git`
    # exclusion — and it is what makes a file the export writes BESIDE the
    # artifact visible, which the PR body states as a boundary of this report.
    #
    # The artifact's parent exists already, so gda creates no directory and the
    # only excluded output path is the artifact itself; that is the case in which
    # the sibling is reported at all.
    project = minimal_project(tmp_path)
    (project / "build").mkdir()

    def mutate() -> None:
        _write(project / ".git" / "objects" / "ab", "object")
        _write(project / ".gitignore", "*.tmp")
        _write(project / ".github" / "ci.yml", "on: push")
        _write(project / "build" / "game.x86_64", "binary")
        _write(project / "build" / "game.x86_64.pck", "pack")

    outcome = _export(project, mutate)
    assert isinstance(outcome, ExportRunResult), outcome
    assert outcome.created_dirs == []

    assert [entry.path for entry in _mutations(outcome).created] == [
        "res://.github/ci.yml",
        "res://.gitignore",
        "res://build/game.x86_64.pck",
    ]


def test_a_deleted_file_is_reported_nowhere(tmp_path):
    # The report covers what the pass ADDS and REWRITES. A deletion is neither, and
    # inventing a third list for something the export does not do would be scope
    # the record cannot fill.
    project = minimal_project(tmp_path)
    doomed = _write(project / "stale.import", "[remap]")

    mutations = _mutations(_export(project, doomed.unlink))

    assert mutations.created == []
    assert mutations.modified == []
    assert mutations.skipped == 0


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
    # walk is settled on the success branch only, so a failure does not pay for it
    # — counted here rather than described, since "we skip the work" is exactly the
    # kind of claim that rots.
    from gda.commands.export import _walk_project as real_walk

    project = minimal_project(tmp_path)
    walks: list[Path] = []

    def counting_walk(walk_project, excluded, on_unreadable_dir=None):
        walks.append(walk_project)
        return real_walk(walk_project, excluded, on_unreadable_dir)

    monkeypatch.setattr("gda.commands.export._walk_project", counting_walk)

    failed = _export(
        project, lambda: _write(project / "icon.png.import", "x"), exit_code=1
    )
    assert isinstance(failed, Failure), failed
    assert failed.error.code == "export_failed"
    assert len(walks) == 1

    succeeded = _export(project, lambda: _write(project / "other.import", "x"))
    assert isinstance(succeeded, ExportRunResult), succeeded
    assert len(walks) == 3


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
