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
    # `gda.import_evidence.classify_created_file` for every verdict. A stub answer
    # therefore reaches the report; a rule restated here would ignore it.
    project = minimal_project(tmp_path)
    monkeypatch.setattr(
        "gda.commands.export.classify_created_file", lambda rel: "cache_owned"
    )

    mutations = _mutations(
        _export(project, lambda: _write(project / "beside_the_source.import", "x"))
    )

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
    # artifact, not the parent directories gda created for it (#402), and not the
    # files inside an artifact that is a DIRECTORY (a macOS `.app` bundle).
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


def test_a_file_the_walk_cannot_read_is_skipped_not_failed(tmp_path):
    # The disclosure rule: a vanished or unreadable file must not turn a SUCCESSFUL
    # export into a failure. Both sides are counted — one dangling link is there
    # before the export, one appears during it — and neither enters a list, because
    # "created" and "rewritten" are both claims the walk cannot make about it.
    project = minimal_project(tmp_path)
    os.symlink("nowhere", project / "before.tres")

    def mutate() -> None:
        os.symlink("nowhere", project / "during.tres")
        _write(project / "icon.png.import", "[remap]")

    outcome = _export(project, mutate)
    mutations = _mutations(outcome)

    assert mutations.skipped == 2
    assert [entry.path for entry in mutations.created] == ["res://icon.png.import"]
    assert mutations.modified == []


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

    def counting_walk(walk_project, excluded):
        walks.append(walk_project)
        return real_walk(walk_project, excluded)

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


def test_the_human_render_says_unchanged_when_the_export_touched_nothing(tmp_path):
    # A warm-cache export that changes nothing says so, rather than printing a row
    # of zeros or nothing at all — an absent line would read the same as an older
    # gda that could not tell.
    project = minimal_project(tmp_path)

    outcome = _export(project)
    assert isinstance(outcome, ExportRunResult), outcome

    assert render_export_run(outcome).splitlines() == [
        f"exported Linux/X11 (Linux/X11, release) -> {project / 'build' / 'game.x86_64'}",
        "  project tree: unchanged",
    ]


def test_an_unreadable_file_is_named_in_the_render(tmp_path):
    # The skipped count is the whole disclosure, and it reaches the human channel
    # too: an export that could not read part of the tree says so on the same line.
    project = minimal_project(tmp_path)
    os.symlink("nowhere", project / "dangling.tres")

    outcome = _export(project)
    assert isinstance(outcome, ExportRunResult), outcome

    assert render_export_run(outcome).splitlines()[-1].endswith("1 unreadable")


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
