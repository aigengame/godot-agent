"""The `Project tree inventory`: the walk and the settlement (#985).

:mod:`gda.project_tree` owns the one Python enumeration of a project's files and
the two-capture settlement over it — the fact behind ``gda export run``'s
`Project-tree mutation report` (#839) and ``gda resource import``'s ``created``
list (#668). These tests drive that interface directly: capture the tree, mutate
it the way an engine pass does, settle. One test names each rule the module's
docstring states.

Each adapter's own use of it is pinned with that adapter, because that is what
changes when the adapter changes: ``tests/export/test_export_tree_mutations.py``
for the export report's shape, renderer and success-only boundary, and
``tests/resource`` for the import's ``created`` list. The real-engine proofs are
``tests/export/test_e2e_export_run.py`` and
``tests/resource/test_e2e_resource_import.py``.
"""

import os
import threading
from pathlib import Path
from typing import Callable

import pytest

from gda.import_evidence import CACHE_ROOT_REL
from gda.project_tree import (
    ProjectTreeInventory,
    ProjectTreeSettlement,
)
from tests.support import minimal_project, unlistable


def _settle(
    project: Path,
    mutate: Callable[[], object] = lambda: None,
    *,
    artifact: Path | None = None,
    detect_rewrites: bool = True,
) -> ProjectTreeSettlement:
    """Capture ``project``, mutate it as an engine pass does, settle the two.

    ``artifact`` is the file the asking command has already resolved and wants
    kept out; the default is ``resource import``'s call, which keeps nothing out.
    Turning an export destination STRING into that path is the export group's
    policy and is tested there (`tests/export/test_export_tree_mutations.py`).
    """
    inventory = ProjectTreeInventory.capture(
        project,
        artifact=artifact,
        detect_rewrites=detect_rewrites,
    )
    mutate()
    return inventory.settle()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_created_files_are_classified_against_the_shared_cache_root(tmp_path):
    # Rule 6, and the shared vocabulary: the cache root is walked like any other
    # directory, and its files carry the `cache_owned` verdict `resource import`
    # reports for the files its own pass creates — from the same function, which
    # is also where the root is spelled.
    project = minimal_project(tmp_path)
    _write(project / "icon.png", "png")

    def mutate() -> None:
        _write(project / CACHE_ROOT_REL / "imported" / "icon.png-ab.ctex", "12345")
        _write(project / CACHE_ROOT_REL / "uid_cache.bin", "uid")
        _write(project / "icon.png.import", "[remap]")

    settled = _settle(project, mutate)

    assert [
        (entry.rel, entry.classification, entry.size) for entry in settled.created
    ] == [
        (".godot/imported/icon.png-ab.ctex", "cache_owned", 5),
        (".godot/uid_cache.bin", "cache_owned", 3),
        ("icon.png.import", "source_adjacent", 7),
    ]
    assert settled.modified == []
    assert settled.skipped == 0


def test_the_classification_is_the_shared_function_not_a_local_rule(
    tmp_path, monkeypatch
):
    # #839's reuse criterion, pinned rather than described: the module asks
    # `gda.import_evidence.classify_created_file` at BOTH of the places it needs a
    # verdict, and a rule restated at either one would stop asking.
    #
    # The settlement's use is visible in the answer — a stub verdict reaches the
    # created entry. The CAPTURE's use is not: it only decides which files to
    # hash, and a wrongly hashed cache file is passed over by the settlement
    # anyway, so the stub RECORDS what it was asked about and the mutation
    # snapshots that record before it changes anything. Whatever is in the
    # snapshot was asked during the first walk (PR #981 review found the second
    # half pinned by nothing).
    project = minimal_project(tmp_path)
    _write(project / "already_here.tres", "old")
    asked: list[str] = []
    asked_before_the_pass: list[str] = []

    def recording_stub(rel: str) -> str:
        asked.append(rel)
        return "cache_owned"

    monkeypatch.setattr("gda.project_tree.classify_created_file", recording_stub)

    def mutate() -> None:
        asked_before_the_pass.extend(asked)
        _write(project / "beside_the_source.import", "x")

    settled = _settle(project, mutate)

    assert "already_here.tres" in asked_before_the_pass
    assert [entry.classification for entry in settled.created] == ["cache_owned"]


def test_a_rewritten_file_is_modified_and_carries_both_sizes(tmp_path):
    # The reported half of the rewrite rule: the pass rewrites a generated
    # resource, and the settlement names it with the size it had and the size it
    # has. `size_before` is the fact only the first capture can state.
    project = minimal_project(tmp_path)
    generated = _write(project / "i18n" / "ui.translation", "old bytes")

    settled = _settle(
        project, lambda: generated.write_text("new bytes here", encoding="utf-8")
    )

    assert [
        (entry.rel, entry.size, entry.size_before) for entry in settled.modified
    ] == [("i18n/ui.translation", 14, 9)]
    assert settled.created == []


def test_a_touched_file_whose_content_is_equal_is_not_modified(tmp_path):
    # The other half: the import pass touches far more files than it rewrites, and
    # a changed timestamp alone would bury the few rewrites the record is about.
    # The file below is a CANDIDATE (its mtime moved) and is then cleared by its
    # digest.
    project = minimal_project(tmp_path)
    touched = _write(project / "i18n" / "ui.translation", "same bytes")

    def mutate() -> None:
        touched.write_text("same bytes", encoding="utf-8")
        later = os.stat(touched).st_mtime_ns + 5_000_000_000
        os.utime(touched, ns=(later, later))

    assert _settle(project, mutate).modified == []


def test_a_rewrite_that_keeps_the_size_and_the_timestamp_is_not_a_candidate(tmp_path):
    # The candidate rule's declared blind spot, pinned so it stays a decision. Only
    # a file whose size or mtime moved is hashed after the run; that is what bounds
    # the cost on a tree the pass touches wholesale. A rewrite that restores both
    # is invisible — no engine pass does this, but the rule says so out loud.
    project = minimal_project(tmp_path)
    resource = _write(project / "generated.tres", "aaaa")
    before = os.stat(resource)

    def mutate() -> None:
        resource.write_text("bbbb", encoding="utf-8")
        os.utime(resource, ns=(before.st_atime_ns, before.st_mtime_ns))

    assert _settle(project, mutate).modified == []
    assert resource.read_text(encoding="utf-8") == "bbbb"


def test_a_pre_existing_cache_file_is_never_reported_as_rewritten(tmp_path):
    # The cache is reported as ONE unit: a pre-existing cache file is not hashed by
    # the capture and cannot enter `modified`. Hashing the cache would cost more
    # than the fact is worth — the dogfooding case holds about 1.1 GiB there — and
    # the record is about the tracked files beside it.
    project = minimal_project(tmp_path)
    cached = _write(project / CACHE_ROOT_REL / "uid_cache.bin", "old cache")

    settled = _settle(
        project, lambda: cached.write_text("rewritten cache", encoding="utf-8")
    )

    assert settled.modified == []
    assert settled.created == []


def test_a_capture_without_rewrites_reports_only_what_was_created(tmp_path):
    # The one consumer-specific gate the module carries (#985's scope guard):
    # `resource import` asks what the pass created and pays no hash for the
    # answer, so a rewritten file is neither reported nor read. The created half
    # is identical to the export's, which is the point of one owner.
    project = minimal_project(tmp_path)
    generated = _write(project / "ui.translation", "old bytes")

    def mutate() -> None:
        generated.write_text("new bytes here", encoding="utf-8")
        _write(project / "icon.png.import", "[remap]")

    settled = _settle(project, mutate, detect_rewrites=False)

    assert [entry.rel for entry in settled.created] == ["icon.png.import"]
    assert settled.modified == []
    assert settled.skipped == 0


def test_an_artifact_under_a_directory_link_is_excluded_by_identity(tmp_path):
    # The artifact is kept out by its PARENT's filesystem identity and its own
    # name, so the path the asking command resolved need not be the spelling the
    # walk reaches it by. The sibling beside it stays visible.
    project = minimal_project(tmp_path / "game")
    shared = tmp_path / "shared"
    shared.mkdir()
    (project / "assets").symlink_to(shared, target_is_directory=True)

    def mutate() -> None:
        _write(shared / "out.pck", "pack")
        _write(shared / "sibling.import", "sidecar")

    settled = _settle(project, mutate, artifact=project / "assets" / "out.pck")

    assert [entry.rel for entry in settled.created] == ["assets/sibling.import"]
    assert settled.skipped == 0


def test_an_artifact_is_excluded_when_the_walk_uses_another_link_spelling(tmp_path):
    # The walk reaches the directory under `a_alias` first, and the artifact names
    # it `z_assets`. Two path strings would not match; the identity pair does.
    project = minimal_project(tmp_path)
    target = project / "z_assets"
    target.mkdir()
    (project / "a_alias").symlink_to(target, target_is_directory=True)

    settled = _settle(
        project,
        lambda: _write(target / "out.pck", "pack"),
        artifact=target / "out.pck",
    )

    assert settled.created == []
    assert settled.skipped == 0


def test_a_top_level_git_directory_is_not_walked(tmp_path):
    # Rule 5. The engine does not write to `.git`, and hashing an object database
    # would dominate the cost of a record about the project's own files.
    project = minimal_project(tmp_path)
    _write(project / ".git" / "HEAD", "ref: refs/heads/main")

    settled = _settle(
        project, lambda: _write(project / ".git" / "objects" / "ab" / "cd", "x")
    )

    assert settled.created == []
    assert settled.skipped == 0


def test_the_exclusions_match_whole_path_components(tmp_path):
    # The exclusions are PREFIX-of-path-components, never prefix-of-string. That
    # separator is what keeps `.gitignore` and `.github/` out of the `.git`
    # exclusion — and it is what makes a file the run writes BESIDE the artifact
    # visible, which the export report states as a boundary.
    project = minimal_project(tmp_path)
    (project / "build").mkdir()

    def mutate() -> None:
        _write(project / ".git" / "objects" / "ab", "object")
        _write(project / ".gitignore", "*.tmp")
        _write(project / ".github" / "ci.yml", "on: push")
        _write(project / "build" / "game.x86_64", "binary")
        _write(project / "build" / "game.x86_64.pck", "pack")

    settled = _settle(project, mutate, artifact=project / "build" / "game.x86_64")

    assert [entry.rel for entry in settled.created] == [
        ".github/ci.yml",
        ".gitignore",
        "build/game.x86_64.pck",
    ]


def test_a_directory_link_is_walked_as_the_engine_reads_it(tmp_path):
    # Rule 1. The engine's import scan follows a directory link, so a shared
    # library linked into the project is content the pass writes sidecars into and
    # rewrites generated resources in. `os.walk` leaves it out by default, and the
    # export report then stated neither — with `skipped` at zero, so nothing said
    # the record was incomplete (PR #981 review round 3, measured on a real pack
    # export).
    project = minimal_project(tmp_path / "game")
    shared = tmp_path / "shared"
    _write(shared / "ui.csv", "keys,en\nGREET,Hello\n")
    generated = _write(shared / "ui.en.translation", "old")
    (project / "assets").symlink_to(shared, target_is_directory=True)

    def mutate() -> None:
        _write(shared / "ui.csv.import", "[remap]")
        generated.write_text("rewritten bytes", encoding="utf-8")

    settled = _settle(project, mutate)

    # Reported under the spelling the walk reached them by, which is the res://
    # path the engine names them by too.
    assert [entry.rel for entry in settled.created] == ["assets/ui.csv.import"]
    assert [entry.rel for entry in settled.modified] == ["assets/ui.en.translation"]
    assert settled.modified[0].size_before == 3
    assert settled.skipped == 0


def test_a_link_that_leads_back_up_the_chain_is_not_re_entered(tmp_path):
    # Rule 2. Identity, not spelling: `sub/loop -> ..` reaches a directory the walk
    # has already walked, so it is not re-entered and the walk ends by rule rather
    # than at the OS path limit. The content under the loop is reported ONCE, under
    # its first spelling, and a cycle is not unaccounted content — `skipped` stays
    # at zero.
    #
    # Run on a thread with a deadline, like the FIFO test: a regression that walks
    # the cycle must read RED rather than wedge the suite.
    project = minimal_project(tmp_path / "game")
    _write(project / "sub" / "asset.tres", "[gd_resource]")
    (project / "sub" / "loop").symlink_to("..", target_is_directory=True)
    outcome: list[ProjectTreeSettlement] = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            _settle(project, lambda: _write(project / "sub" / "asset.tres.import", "x"))
        ),
        daemon=True,
    )

    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive(), "the walk did not terminate on a symlink cycle"

    assert [entry.rel for entry in outcome[0].created] == ["sub/asset.tres.import"]
    assert outcome[0].modified == []
    assert outcome[0].skipped == 0


def test_a_file_the_walk_cannot_read_is_skipped_not_failed(tmp_path):
    # Rule 4's file half, and the disclosure rule behind it: a vanished or
    # unreadable file must not turn a SUCCESSFUL run into a failure. All three
    # shapes are counted and none enters a list, because "created" and "rewritten"
    # are both claims the walk cannot make about a file it never read. The third
    # one is why the settlement asks first whether the capture could read the path
    # at all: the link RESOLVES after the pass, so a settlement that only asked
    # "was this path recorded?" would announce a file the project already had as
    # one the run created.
    project = minimal_project(tmp_path)
    os.symlink("nowhere", project / "before.tres")
    os.symlink("target.tres", project / "resolves.tres")

    def mutate() -> None:
        os.symlink("nowhere", project / "during.tres")
        _write(project / "target.tres", "generated")
        _write(project / "icon.png.import", "[remap]")

    settled = _settle(project, mutate)

    assert settled.skipped == 3
    assert [entry.rel for entry in settled.created] == [
        "icon.png.import",
        "target.tres",
    ]
    assert settled.modified == []


def test_a_directory_the_walk_cannot_list_is_counted_once_per_inode(tmp_path):
    # Rule 4's directory half, and its identity clause (#990). `os.walk` swallows
    # a listdir failure by default, which would drop the whole subtree from the
    # record AND from the one channel that says the record is incomplete. It also
    # reports the failure INSTEAD of yielding the directory, so rule 1 never sees
    # the failing path: the same inode reached directly and through a directory
    # link was counted twice for one unreadable subtree. The settlement asks for
    # the identity itself — a mode-000 directory still answers `stat`, because its
    # PARENT is listable — so the count is 1 here and was 2 before.
    project = minimal_project(tmp_path)
    locked = project / "locked"
    _write(locked / "secret.tres", "old")
    (project / "alias").symlink_to(locked, target_is_directory=True)
    if not unlistable(locked):
        pytest.skip("this platform lets the owner list a mode-000 directory")

    try:
        settled = _settle(project)
    finally:
        locked.chmod(0o755)

    assert settled.skipped == 1
    assert settled.created == []
    assert settled.modified == []


def test_a_file_under_a_locked_directory_is_not_announced_as_created(tmp_path):
    # The readable-after case, which states a FALSE fact rather than an incomplete
    # one: the capture could not list the directory, so a file the project already
    # had must not be reported as one the run created once the directory opens up.
    project = minimal_project(tmp_path)
    locked = project / "locked"
    _write(locked / "secret.tres", "old")
    if not unlistable(locked):
        pytest.skip("this platform lets the owner list a mode-000 directory")

    try:
        settled = _settle(project, lambda: locked.chmod(0o755))
    finally:
        locked.chmod(0o755)

    assert settled.created == []
    assert settled.modified == []
    assert settled.skipped == 1


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFOs only")
def test_a_non_regular_entry_is_counted_and_never_opened(tmp_path):
    # Rule 3. The inventory reads REGULAR files only. A FIFO answers `stat` like
    # any file and then blocks `open()` until a writer appears, which hung the
    # whole command — outside every timeout, with no result and no envelope (PR
    # #981 review round 2). Sockets and devices reached the skipped channel
    # already, by raising instead of blocking; the rule is now one rule for the
    # family.
    #
    # The capture runs on a thread with a deadline, so a regression reads RED here
    # instead of wedging the suite.
    project = minimal_project(tmp_path)
    fifo = project / "pipe.dat"
    os.mkfifo(fifo)
    outcome: list[ProjectTreeSettlement] = []
    worker = threading.Thread(
        target=lambda: outcome.append(_settle(project)), daemon=True
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

    assert outcome[0].skipped == 1
    assert outcome[0].created == []
    assert outcome[0].modified == []


def test_the_engines_skip_markers_are_not_applied(tmp_path):
    # Rule 7, whose statement and reason are `gda.project_tree`'s docstring: this
    # walk takes neither of the engine's two skip markers, because the engine
    # writes its OWN `.gdignore` into the project data directory (ADR-0032's #804
    # amendment carries that fact and the engine source).
    #
    # The case that reason is about is the one a marker rule alone gets wrong, so
    # it is the case seeded here: skipping on that marker would prune
    # `res://.godot` and empty the `cache_owned` half of both commands' `created`
    # lists — the published "anywhere under the project" on four surfaces. A
    # dot-prefixed directory stays in for the separate reason #54 and #712
    # decided.
    project = minimal_project(tmp_path)
    minimal_project(project / "vendor" / "inner")
    _write(project / "ignored" / ".gdignore", "")
    _write(project / ".hidden" / "keep.txt", "kept")
    _write(project / CACHE_ROOT_REL / ".gdignore", "")

    def mutate() -> None:
        _write(project / "vendor" / "inner" / "icon.png.import", "[remap]")
        _write(project / "ignored" / "asset.tres.import", "[remap]")
        _write(project / ".hidden" / "note.import", "[remap]")
        _write(project / CACHE_ROOT_REL / "imported" / "icon.png-ab.ctex", "12345")

    settled = _settle(project, mutate)

    assert [(entry.rel, entry.classification) for entry in settled.created] == [
        (".godot/imported/icon.png-ab.ctex", "cache_owned"),
        (".hidden/note.import", "source_adjacent"),
        ("ignored/asset.tres.import", "source_adjacent"),
        ("vendor/inner/icon.png.import", "source_adjacent"),
    ]
    assert settled.skipped == 0


def test_a_same_size_rewrite_with_a_newer_timestamp_is_reported(tmp_path):
    # The candidate gate is size OR timestamp, and this is the timestamp half: a
    # rewrite of the same length still moves the mtime, so the file is compared and
    # its changed bytes reach `modified`. A size-only gate would drop every
    # same-size rewrite — the record's headline fact — and stay green everywhere
    # else, because the e2e's translations grow (PR #981 review round 2).
    project = minimal_project(tmp_path)
    generated = _write(project / "ui.translation", "aaaa")

    def mutate() -> None:
        generated.write_text("bbbb", encoding="utf-8")
        later = os.stat(generated).st_mtime_ns + 5_000_000_000
        os.utime(generated, ns=(later, later))

    settled = _settle(project, mutate)

    assert [
        (entry.rel, entry.size, entry.size_before) for entry in settled.modified
    ] == [("ui.translation", 4, 4)]


def test_a_deleted_file_is_reported_nowhere(tmp_path):
    # The settlement covers what the pass ADDS and REWRITES. A deletion is neither,
    # and inventing a third list for something the run does not do would be scope
    # the record cannot fill.
    project = minimal_project(tmp_path)
    doomed = _write(project / "stale.import", "[remap]")

    settled = _settle(project, doomed.unlink)

    assert settled.created == []
    assert settled.modified == []
    assert settled.skipped == 0


def test_a_spelling_that_vanishes_between_the_captures_does_not_split_one_inode(
    tmp_path,
):
    # The identity is taken WHEN the failure is observed (rule 4). Before this
    # pin the settlement re-stat'ed the first capture's spellings, so `alias`
    # removed after the capture became an unidentified spelling beside `locked`'s
    # inode: one observed inode counted twice.
    project = minimal_project(tmp_path / "proj")
    locked = project / "locked"
    locked.mkdir()
    (locked / "hidden.txt").write_text("x", encoding="utf-8")
    (project / "alias").symlink_to(locked, target_is_directory=True)
    if not unlistable(locked):
        pytest.skip("this platform lists a mode-000 directory")
    try:
        inventory = ProjectTreeInventory.capture(project, detect_rewrites=False)
        (project / "alias").unlink()
        assert inventory.settle().skipped == 1
    finally:
        locked.chmod(0o755)


def test_a_spelling_retargeted_to_a_second_unreadable_inode_counts_both(tmp_path):
    # Rule 4's other half: the identity is taken at EVERY observation, not only
    # at a spelling's first. Before this pin the helper recorded a spelling once,
    # so `alias` retargeted after the capture to a second unreadable directory
    # was never sampled again, and an inode observed failing went uncounted
    # (external re-review). The second directory is OUTSIDE the project so that
    # only the retargeted link reaches it.
    project = minimal_project(tmp_path / "proj")
    locked = project / "locked"
    locked.mkdir()
    (locked / "hidden.txt").write_text("x", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    alias = project / "alias"
    alias.symlink_to(locked, target_is_directory=True)
    try:
        if not (unlistable(locked) and unlistable(other)):
            pytest.skip("this platform lists a mode-000 directory")
        inventory = ProjectTreeInventory.capture(project, detect_rewrites=False)
        alias.unlink()
        alias.symlink_to(other, target_is_directory=True)
        assert inventory.settle().skipped == 2
    finally:
        locked.chmod(0o755)
        other.chmod(0o755)
