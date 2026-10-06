"""The `Project-tree mutation report` records (#839, #1073).

Split out of the shared contract core by ADR-0045 §2: the one shape the two
groups that run the editor import pass publish for what it did to the project
tree.
"""

from pydantic import BaseModel, Field, model_validator

from gda.core.project.import_evidence import CACHE_ROOT_REL, CreatedFileClass
from gda.core.project.project_tree import ProjectTreeSettlement


# The project-tree mutation report (#839) is published by TWO groups since #1073:
# ``export run`` and ``project scan`` both run the editor import pass over the
# project, so both report what it did to the tree with this one shape. A shape no
# single group owns lives in this core (ADR-0040 §5). The class names are the ones
# ``export run`` has always published, so its ``$defs`` keys do not move.


# ``classification`` is gda.core.project.import_evidence.classify_created_file's verdict.
class ExportCreatedFile(BaseModel):
    """One file an engine run added to the project tree (#839).

    ``classification`` is the same ``cache_owned`` / ``source_adjacent`` verdict
    ``resource import`` reports, from the same function, because ``export run``
    and ``project scan`` run the same editor import pass. ``size`` is what the
    file holds after the run, and the entries' sizes add up to ``created_bytes``.
    """

    path: str = Field(description="The created file's res:// path.")
    classification: CreatedFileClass = Field(
        description="cache_owned (under the cache root) or source_adjacent."
    )
    size: int = Field(description="The created file's size in bytes.")


class ExportModifiedFile(BaseModel):
    """One pre-existing project file an engine run rewrote (#839).

    Content, never timestamps: the import pass touches files it does not rewrite,
    and that noise would bury the few generated resources the record is about.
    ``size_before`` is the fact only the walk before the run can state — after the
    run the earlier bytes are gone.
    """

    path: str = Field(description="The rewritten file's res:// path.")
    size: int = Field(description="The file's size in bytes after the run.")
    size_before: int = Field(description="The file's size in bytes before the run.")


class ProjectTreeMutations(BaseModel):
    """The project-tree mutation report of one engine run (#839, #1073).

    Published by ``gda export run`` and ``gda project scan``. Both run the editor
    import pass over the project, so a run against a cold cache creates the whole
    cache tree plus the sidecars beside the sources, and can rewrite generated
    resources that are tracked in git. None of that was observable in the export
    result before (GDA-DF-067: about 14,000 new files and two to four rewritten
    ``.translation`` resources appeared on disk while ``warnings`` stayed empty).
    The report is DISCLOSURE — the run deletes and restores nothing — so an agent
    can review, stage or restore the tree without a manual git snapshot.

    What it covers, and what it deliberately leaves out:

    * ``created`` is every file the tree gained, ANYWHERE under the project,
      classified against ``cache_root`` so the cache half can be cleaned as one
      unit. A directory link is walked as the engine reads it, once each: the
      shared assets directory a monorepo links in is content the import pass
      writes into.
    * ``modified`` is every pre-existing file OUTSIDE ``cache_root`` whose CONTENT
      changed. A pre-existing file is a CANDIDATE only when its size or timestamp
      moved, so a rewrite that preserves both is not seen. A pre-existing cache
      file stays out altogether: the cache is reported as one unit, a warm run
      rewrites its bookkeeping files every time, and hashing it beforehand would
      cost far more than the fact is worth (the dogfooding case holds about
      1.1 GiB there). So an unchanged ``modified`` says nothing about the cache.
    * For ``export run``, the artifact and everything under it are out of both
      lists — a directory artifact such as a macOS ``.app`` bundle included. A
      top-level ``.git`` directory, which the engine never writes to, is out for
      both commands. The exclusion stops there: a file the export writes BESIDE the
      artifact (a Linux binary with ``binary_format/embed_pck=false`` gets a
      ``game.pck`` next to it) is a created file like any other.
    * Deletions are not reported: the pass adds and rewrites.
    * ``skipped`` counts what neither walk could account for — an entry that is
      not a regular file (a FIFO, a socket, a device), a vanished or unreadable
      file, a dangling symlink, a directory that cannot be listed (whose whole
      subtree is then outside both lists). gda never opens a non-regular entry.
      None of it fails a run that succeeded; it is a COUNT, not a path list, so
      the remedy is to repair the tree and run again for a complete record.

    The report covers the engine's DEFAULT cache directory. A project that sets
    ``application/config/use_hidden_project_data_directory=false`` keeps its cache
    under ``godot/``, whose files then read as ``source_adjacent``; that case is
    out of scope for this report (#839).
    """

    cache_root: str = Field(
        default="res://" + CACHE_ROOT_REL,
        description=(
            f"The cache root created files are classified against "
            f"(res://{CACHE_ROOT_REL})."
        ),
    )
    created: list[ExportCreatedFile] = Field(
        default_factory=list,
        description=(
            "Every file the run added anywhere under the project, classified, "
            "ordered by path. Directory links are walked as the engine reads "
            "them, once each."
        ),
    )
    modified: list[ExportModifiedFile] = Field(
        default_factory=list,
        description=(
            "Every pre-existing file outside the cache root whose content the "
            "run rewrote, ordered by path. Only a file whose size or timestamp "
            "moved is compared, so a rewrite that preserves both is not reported; "
            "rewrites inside the cache root are not reported at all."
        ),
    )
    created_count: int = Field(default=0, description="Files the run created.")
    created_cache_owned: int = Field(
        default=0, description="Created files under the cache root."
    )
    created_source_adjacent: int = Field(
        default=0, description="Created files beside the sources."
    )
    created_bytes: int = Field(
        default=0, description="Total size in bytes of the created files."
    )
    modified_count: int = Field(default=0, description="Files the run rewrote.")
    modified_bytes: int = Field(
        default=0,
        description="Total size in bytes of the rewritten files after the run.",
    )
    skipped: int = Field(
        default=0,
        description=(
            "What neither list could account for: entries that are not regular "
            "files, or could not be read — including a directory whose whole "
            "subtree is then uncovered. A count only; repair the tree and run "
            "again for a complete record."
        ),
    )

    @model_validator(mode="after")
    def _counts_match_the_lists(self) -> "ProjectTreeMutations":
        # gda's own invariant, not input validation: the counts exist so a caller
        # can read the summary without walking a list that holds thousands of cache
        # files, which is only worth anything while the two agree (the #732 lesson,
        # as `resource import` pins it for its own summary).
        owned = sum(
            1 for entry in self.created if entry.classification == "cache_owned"
        )
        if (
            self.created_count,
            self.created_cache_owned,
            self.created_source_adjacent,
            self.created_bytes,
            self.modified_count,
            self.modified_bytes,
        ) != (
            len(self.created),
            owned,
            len(self.created) - owned,
            sum(entry.size for entry in self.created),
            len(self.modified),
            sum(entry.size for entry in self.modified),
        ):
            raise ValueError("the mutation counts must match the reported lists.")
        return self

    @classmethod
    def from_settlement(
        cls, settlement: "ProjectTreeSettlement"
    ) -> "ProjectTreeMutations":
        """The published report of one settled `Project tree inventory` (#839).

        A rendering, not a second rule: the entries take the ``res://`` spelling
        the result publishes, and the counts are derived here — they are this
        result's own summary of its own lists, which the validator above then pins
        to them.
        """
        created = [
            ExportCreatedFile(
                path="res://" + entry.rel,
                classification=entry.classification,
                size=entry.size,
            )
            for entry in settlement.created
        ]
        modified = [
            ExportModifiedFile(
                path="res://" + entry.rel,
                size=entry.size,
                size_before=entry.size_before,
            )
            for entry in settlement.modified
        ]
        owned = sum(1 for entry in created if entry.classification == "cache_owned")
        return cls(
            created=created,
            modified=modified,
            created_count=len(created),
            created_cache_owned=owned,
            created_source_adjacent=len(created) - owned,
            created_bytes=sum(entry.size for entry in created),
            modified_count=len(modified),
            modified_bytes=sum(entry.size for entry in modified),
            skipped=settlement.skipped,
        )
