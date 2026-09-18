"""The `Project tree inventory` (#985): one Python walk of a project's files.

Two commands must know what one engine pass did to the project tree, and both
answer by walking that tree in Python around the run: ``gda export run``'s
`Project-tree mutation report` (#839) and ``gda resource import``'s ``created``
list (#668). They used to ask that one question with two different walks —
``export run`` under the five rules PR #981 settled, ``resource import`` under a
bare ``Path.rglob("*")`` that does not descend a directory link — so the same
import pass reported two different file sets on a project with a linked-in
library. This module is that question's one owner: the walk, and the two-capture
settlement over it. Each command keeps what is its own — its published models,
its renderer, and, for ``export run``, the artifact it asked the engine to write.

What this module is NOT. Each of these answers a DIFFERENT question and stays
where it is:

* the engine-side ``res://`` walk in ``operations.gd`` — what this repository
  calls the project walk (ADR-0032, amended by #760 and #804). It answers what
  the ENGINE reaches, it is the engine's own code, and nothing here touches it;
* :mod:`gda.import_evidence`'s stale-sidecar gap scan, which predicts that same
  engine reachability from Python through ``_engine_skips_directory_of`` and
  keeps its own ``rglob("*.import")`` — the catalog records that scan's
  link-blindness as an accepted under-promise;
* a filesystem library, and not a file-set configuration. The per-call inputs
  are the two adapters' questions — the project root, the artifact to keep out,
  and a sink for a directory the walk cannot list — never options, filters or a
  strategy to pick (#985's scope guard).

**The rules, stated once.** They are W4's, as PR #981 shipped them for the
export report; they now decide both commands' answer.

1. **A directory link is followed**, because the engine's import scan follows
   one: a shared library directory linked into the project is content the pass
   reads and writes sidecars into. ``os.walk`` leaves such a directory out by
   default, and the export then created and rewrote files under it while the
   report said nothing about either (PR #981 review round 3). The policy is the
   project's decided one for the ``res://`` walk, ADR-0032's (#760): follow the
   link as the engine does, and identify what it reaches by FILESYSTEM IDENTITY
   — the ``(st_dev, st_ino)`` pair the engine's own ``DirAccess.is_equivalent``
   compares — rather than by its spelling. A directory is therefore walked ONCE,
   under the first spelling that reaches it. The entries are sorted, so the first
   spelling is the same on both captures, and a file is reported under that
   project-relative ``res://`` spelling even when it was addressed through
   another alias of the same directory.
2. **A cycle is not re-entered, and is not counted.** A link that leads back up
   the descent chain, or into a directory already walked, fails that identity
   test: ``sub/loop -> ..`` ends by rule instead of at the OS path limit. Nothing
   is unaccounted for — the content is reported under its first spelling — so a
   cycle never enters ``skipped``.
3. **Only a regular file is opened**, and the check comes BEFORE the open: a
   FIFO in the project tree blocks ``open()`` until a writer appears, which hung
   the whole command outside any timeout (PR #981 review round 2) — no result, no
   envelope, no exit. A socket or a device answers with an ``OSError`` instead,
   so the family reached the skipped channel by two routes and one of them was
   unbounded. ``Path.stat()`` follows a symlink, so a link at a regular file is
   still inventoried as one.
4. **An unlistable or unreadable entry is counted once** in the settlement's
   ``skipped``: an entry that is not a regular file, a vanished or unreadable
   file, a dangling symlink, or a directory that cannot be listed — whose whole
   subtree is then outside both lists. ``os.walk`` swallows a listing error by
   default, which would drop that subtree from the record AND from the one
   channel that says the record is incomplete.
5. **A top-level ``.git`` is excluded.** The engine never writes there, and
   hashing an object database would dominate the cost of a report about the
   project's own files. The exclusion is on whole path components, so
   ``.gitignore`` and ``.github/`` stay in.
6. **The cache root is walked like anything else.** Its files are what
   :func:`gda.import_evidence.classify_created_file` calls ``cache_owned``, and
   both commands report them as such.
7. **The engine's two skip markers are NOT applied.** A nested ``project.godot``
   and a ``.gdignore`` gate ``_should_descend`` in the engine-side walk and
   ``_engine_skips_directory_of`` in `Import evidence` (#804). Neither is
   consulted here, nor is that predicate's dot-prefix clause: this walk answers
   what gda ENUMERATES, not what the engine reaches (#54, #712). Applying them
   would empty the ``cache_owned`` half of both commands' ``created`` lists —
   the cache root is dot-prefixed — and would narrow the published "anywhere
   under the project" the two results promise.
"""

import hashlib
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG

from gda.import_evidence import CreatedFileClass, classify_created_file

# Read in chunks so a large asset costs no memory. The digest decides ONE thing —
# whether a file's bytes changed between the two captures — and is never
# published, so blake2b is gda's own choice here rather than a contract with
# anybody.
_HASH_CHUNK = 1 << 20

# The one top-level directory the walk drops (rule 5).
_VCS_DIR = ".git"

# The one virtual scheme that names a path INSIDE the project (ADR-0006). Both
# `--output res://out.pck` and a preset `export_path` may spell the destination
# this way, and the engine resolves it against the project root — so the walk has
# to resolve it the same way before it can exclude the artifact (#981 round 3).
_RES_SCHEME = "res://"


@dataclass(frozen=True)
class FileFacts:
    """What a capture records about one file (#839).

    ``digest`` is ``None`` for a file under the cache root — those are never
    hashed, so they can never enter ``modified``; the cache is reported as one
    unit. It is ``None`` for every file of a capture that was not asked to detect
    rewrites at all.
    """

    size: int
    mtime_ns: int
    digest: str | None


@dataclass(frozen=True)
class CreatedFile:
    """One file the tree gained between the two captures (#985).

    ``rel`` is the project-relative posix path — the form
    :func:`gda.import_evidence.classify_created_file` reads, and the form each
    command prefixes with ``res://`` for its own result.
    """

    rel: str
    classification: CreatedFileClass
    size: int


@dataclass(frozen=True)
class RewrittenFile:
    """One pre-existing file whose CONTENT changed between the captures (#839).

    ``size_before`` is the fact only the first capture can state — after the run
    the earlier bytes are gone.
    """

    rel: str
    size: int
    size_before: int


@dataclass(frozen=True)
class ProjectTreeSettlement:
    """What the second capture found: created, rewritten, and unaccounted for.

    ``modified`` is empty for a capture taken without ``detect_rewrites``, which
    took no digest to compare against; such a caller asks only what the run
    created. ``skipped`` is a COUNT, not a path list: the remedy is to repair the
    tree and run again for a complete record.
    """

    created: list[CreatedFile]
    modified: list[RewrittenFile]
    skipped: int


def _digest_file(path: Path) -> str:
    """The content digest the two captures compare (#839)."""
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_facts(path: Path, *, digest: bool) -> FileFacts | None:
    """One REGULAR file's facts, or ``None`` when there are none to take (#839).

    A file that vanished between the walk and the read, a dangling symlink, an
    unreadable one: none of them is a reason to fail a run that SUCCEEDED, so the
    caller counts it as skipped and reports nothing about it.

    An entry that is not a regular file takes that same path, and the check comes
    BEFORE the open — rule 3 of the module docstring.
    """
    try:
        st = path.stat()
        if not S_ISREG(st.st_mode):
            return None
        content = _digest_file(path) if digest else None
    except OSError:
        return None
    return FileFacts(size=st.st_size, mtime_ns=st.st_mtime_ns, digest=content)


def artifact_to_exclude(project: Path, output_path: str) -> Path | None:
    """The artifact a run writes, resolved as the engine resolves it (#839).

    A ``res://`` destination is relative to the project; other virtual paths
    cannot name an artifact in this tree. Filesystem destinations can be outside
    the project but visible through a directory link inside it. The walk reports
    the first project-relative spelling that reaches each directory, which need
    not match the destination's spelling — which is why it compares the output
    parent's filesystem identity and the artifact's name, not two path strings
    (see :func:`walk_project_files`). This also excludes an ``.app`` subtree
    without hiding the files beside it.

    ``resource import`` writes no artifact and asks nothing of this function.
    """
    if output_path.startswith(_RES_SCHEME):
        rest = output_path[len(_RES_SCHEME) :].lstrip("/")
        return project / rest if rest else None
    if not output_path or "://" in output_path:
        return None
    path = Path(output_path)
    return path if path.is_absolute() else project / path


def _under(rel: str, prefixes: tuple[str, ...]) -> bool:
    """Whether ``rel`` is one of ``prefixes`` or sits under one.

    On whole path components, never on the string: that separator is what keeps
    ``.gitignore`` and ``.github/`` out of the ``.git`` exclusion.
    """
    return any(rel == prefix or rel.startswith(prefix + "/") for prefix in prefixes)


def walk_project_files(
    project: Path,
    *,
    artifact: Path | None = None,
    on_unreadable_dir: Callable[[str], None] | None = None,
) -> Iterator[tuple[str, Path]]:
    """Every file under ``project`` as ``(project-relative posix path, path)``.

    The walk of the module docstring's seven rules, and the three inputs are the
    whole of what a caller may say: the project root, the optional ``artifact``
    to keep out of the answer (excluded by its PARENT's filesystem identity and
    its own name, so an alias of that parent cannot smuggle it back in), and
    ``on_unreadable_dir``, which receives the project-relative path of a
    directory the walk cannot list or cannot stat.

    An excluded subtree is PRUNED rather than filtered out per file: an ``.app``
    bundle holds thousands of files, and walking it would spend the report's
    budget on entries it then drops. The function still yields everything it CAN
    read when a corner of the tree is unreadable — that is not a reason to fail a
    run that succeeded; the caller decides what the sink's paths mean for its own
    result.
    """

    def note(error: OSError) -> None:
        if on_unreadable_dir is None:
            return
        filename = getattr(error, "filename", None)
        if filename is None:
            return
        try:
            on_unreadable_dir(Path(filename).relative_to(project).as_posix())
        except ValueError:
            return

    artifact_parent_id: tuple[int, int] | None = None
    if artifact is not None:
        try:
            parent = artifact.parent.stat()
            artifact_parent_id = (parent.st_dev, parent.st_ino)
        except OSError:
            # A parent absent before the run can exist in the second capture.
            pass
    walked: set[tuple[int, int]] = set()
    for dirpath, dirnames, filenames in os.walk(
        project, onerror=note, followlinks=True
    ):
        base = Path(dirpath)
        rel_dir = base.relative_to(project).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        # The identity test is asked of the directory the walk HAS reached, not of
        # the children it is about to descend into: that is what makes the answer
        # depth-first ("the first spelling") rather than breadth-first, and it is
        # also the one place a followed link can be recognized whatever its shape.
        try:
            status = base.stat()
        except OSError as error:
            note(error)
            dirnames[:] = []
            continue
        identity = (status.st_dev, status.st_ino)
        if identity in walked:
            dirnames[:] = []
            continue
        walked.add(identity)
        artifact_name = (
            artifact.name
            if artifact is not None and identity == artifact_parent_id
            else None
        )
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name != artifact_name and not _under(prefix + name, (_VCS_DIR,))
        )
        for name in filenames:
            rel = prefix + name
            if name != artifact_name and not _under(rel, (_VCS_DIR,)):
                yield rel, base / name


@dataclass(frozen=True)
class ProjectTreeInventory:
    """One capture of the project tree, and its settlement against a second (#985).

    Captured before the engine runs, settled after it: :meth:`settle` walks the
    tree a second time and reports the difference. The two halves live in one
    object because the second walk is meaningless without the first — a file is
    ``created`` only against a recorded tree, and ``modified`` only against a
    recorded digest.
    """

    project: Path
    artifact: Path | None
    files: dict[str, FileFacts]
    unreadable: frozenset[str]
    # The directories the first capture could not list, kept apart from the rest
    # because they are PREFIXES: the settlement must pass over everything beneath
    # one. A file under such a directory existed before the run, so reporting it
    # as created once the directory becomes readable would state a fact the
    # captures never observed (PR #981 review).
    unlistable_dirs: tuple[str, ...]
    # The one consumer-specific gate the module carries, and #985's scope guard
    # names it as the only one allowed: `export run` asks for rewrites and pays
    # the capture's hash of every file outside the cache root, because a
    # rewritten file's earlier bytes exist only before the run; `resource import`
    # asks only what the pass created and pays nothing for the answer.
    detect_rewrites: bool

    @classmethod
    def capture(
        cls,
        project: Path,
        *,
        artifact: Path | None = None,
        detect_rewrites: bool,
    ) -> "ProjectTreeInventory":
        """Record the tree as it stands before the engine runs (#839)."""
        files: dict[str, FileFacts] = {}
        unreadable: set[str] = set()
        unlistable: set[str] = set()
        for rel, path in walk_project_files(
            project, artifact=artifact, on_unreadable_dir=unlistable.add
        ):
            # The shared classifier decides what to hash, asked of a file that
            # already exists: `cache_owned` is "under the cache root", the one
            # thing this capture needs to know about it. Asking it here is what
            # keeps the cache-root rule spelled once (#741) — neither command
            # states a rule of its own, here or in the settlement below.
            facts = _file_facts(
                path,
                digest=detect_rewrites and classify_created_file(rel) != "cache_owned",
            )
            if facts is None:
                unreadable.add(rel)
            else:
                files[rel] = facts
        return cls(
            project=project,
            artifact=artifact,
            files=files,
            unreadable=frozenset(unreadable | unlistable),
            unlistable_dirs=tuple(sorted(unlistable)),
            detect_rewrites=detect_rewrites,
        )

    def settle(self) -> ProjectTreeSettlement:
        """Walk the tree again and report what the run changed (#839).

        The rules, in the order the loop asks them: a path the first capture
        could not read is accounted for as skipped and nothing more (calling it
        created would be a guess); a path that was not there is ``created`` and
        carries the shared classifier's verdict; a pre-existing cache file is
        passed over, because the cache is reported as one unit; and a
        pre-existing file elsewhere is a CANDIDATE only when its size or mtime
        moved, and enters ``modified`` only when its digest then differs. The
        candidate rule is what bounds the cost — the import pass touches far more
        files than it rewrites — and it is also this settlement's one blind spot:
        a rewrite that preserves both the size and the timestamp is not seen.

        A caller that did not ask for rewrites stops at ``created``: it holds no
        digest to compare, so every pre-existing file is passed over.

        A directory neither walk could list is counted once, and everything
        beneath it is passed over: the first capture never read those files, so
        the settlement can state nothing about them either way.
        """
        created: list[CreatedFile] = []
        modified: list[RewrittenFile] = []
        skipped = set(self.unreadable)
        for rel, path in walk_project_files(
            self.project, artifact=self.artifact, on_unreadable_dir=skipped.add
        ):
            if rel in skipped or _under(rel, self.unlistable_dirs):
                continue
            before = self.files.get(rel)
            if before is None:
                facts = _file_facts(path, digest=False)
                if facts is None:
                    skipped.add(rel)
                    continue
                created.append(
                    CreatedFile(
                        rel=rel,
                        classification=classify_created_file(rel),
                        size=facts.size,
                    )
                )
                continue
            if not self.detect_rewrites:
                continue
            if classify_created_file(rel) == "cache_owned":
                continue
            after = _file_facts(path, digest=False)
            if after is None:
                skipped.add(rel)
                continue
            if (after.size, after.mtime_ns) == (before.size, before.mtime_ns):
                continue
            hashed = _file_facts(path, digest=True)
            if hashed is None or hashed.digest is None:
                skipped.add(rel)
                continue
            if hashed.digest == before.digest:
                continue
            modified.append(
                RewrittenFile(rel=rel, size=hashed.size, size_before=before.size)
            )
        created.sort(key=lambda entry: entry.rel)
        modified.sort(key=lambda entry: entry.rel)
        return ProjectTreeSettlement(
            created=created, modified=modified, skipped=len(skipped)
        )
