"""Install / uninstall the gda harness autoload in a project (ADR-0018).

``gda daemon start`` performs this **one-time, install-time write** (never a
per-launch mutation, which would race a concurrent editor and corrupt config):
it materializes the bundled harness under ``res://addons/`` and ensures its
``[autoload]`` entry in ``project.godot``. It is idempotent and order-preserving,
and reports whether it changed anything (``installed_harness``).

The write is Python-side because it happens *before* any engine session exists.
It mirrors the autoload semantics ``operations.gd`` uses for ``project
add-autoload`` (issue #119): the value is the ``res://`` path prefixed with ``*``
(the enabled-singleton form).

**Version self-sync (#225, D1).** ``_materialize`` prepends a leading GDScript
comment header ``# gda-harness-version: <N>`` (sourced from ``HARNESS_VERSION``,
NOT the package version — the harness changes far less often than ``gda`` ships).
Because that header is part of the materialized content, the version check **falls
out of the existing content-compare**: a mismatch re-materializes, a match is a
no-op (never an unconditional overwrite, which would bump mtime and trip the
concurrent-editor prompt). ``installed_harness_version`` reads the header back.

**Paired uninstall (#225, D2).** ``uninstall_harness`` removes the ``[autoload]``
entry **first**, then deletes the files — so a mid-failure leaves only a harmless
stray inert ``.gd``, never a dangling autoload pointing at a missing script (which an
exported game logs ``ERR_CONTINUE`` and skips at startup — error spam, not a hard
crash; ADR-0028). It is idempotent: a no-op success when the harness is not installed
(mirrors ``daemon stop``).

**Full reversal and its receipt (#654).** Uninstall now restores the project to its
pre-install state instead of leaving residue that keeps a tracked ``project.godot``
and ``addons/`` dirty after every live session:

- it deletes the engine-generated ``<harness>.gd.uid`` sidecar, which is what kept
  the addon directory non-empty (the empty-directory removal already existed);
- when dropping the harness entry leaves ``[autoload]`` with no keys, it drops the
  **section header** too, along with the blank separator the install appended.

Both are decided from the file's state at uninstall time — no pre-install snapshot
is recorded and no marker file is ever written into the project. Install and
uninstall each RETURN the exact set they touched (``created_paths`` /
``created_sections``, ``removed_paths`` / ``removed_sections``), which the
``daemon start`` / ``daemon uninstall`` results surface as the mutation receipt an
agent (or a reviewer) needs to audit what gda wrote into a tracked project.

**Line endings (#654).** ``project.godot`` is read and written with newline
translation OFF and rejoined with the terminator its FIRST line uses, so a CRLF
project file stays CRLF — Python's default text mode would otherwise silently
rewrite the whole file to LF on any autoload edit.

Three shapes of input still come back changed, so the byte-identity guarantee of
:func:`uninstall_harness` is scoped to exclude them:

- a file with MIXED terminators is normalized to its first one;
- a file with NO final terminator gains one (install terminates the line it
  appends after; uninstall has no way to know the file never ended in a break);
- a CR-only (classic-Mac) file comes back CRLF — ``_line_ending`` only tells
  ``\\r\\n`` from ``\\n``, while ``str.splitlines`` also splits a bare ``\\r``.

None is reachable for a ``project.godot`` the engine itself wrote: Godot's
``ConfigFile`` writer emits uniformly ``\\n``-terminated lines and always
terminates the last one. They need a hand-edited or tool-mangled file, so they are
documented rather than coded around — the code stays a plain line-oriented edit
instead of growing a per-line terminator model for inputs Godot cannot produce.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The autoload name and the res:// location the bundled harness is installed to.
HARNESS_AUTOLOAD_NAME = "GdaHarness"
HARNESS_ADDONS_DIR = "addons"
HARNESS_RES_DIR = f"{HARNESS_ADDONS_DIR}/gda_harness"
HARNESS_FILE = "gda_harness.gd"
HARNESS_RES_PATH = f"res://{HARNESS_RES_DIR}/{HARNESS_FILE}"

# The engine writes a `<script>.uid` sidecar next to every script it imports, so the
# harness install grows a file gda never wrote. It is still gda's footprint (it names
# gda's script), so uninstall removes it — without it the addon directory is never
# empty and the existing empty-directory removal never fires (GDA-DF-009, #654).
HARNESS_UID_FILE = f"{HARNESS_FILE}.uid"
HARNESS_UID_RES_PATH = f"res://{HARNESS_RES_DIR}/{HARNESS_UID_FILE}"
HARNESS_RES_DIR_PATH = f"res://{HARNESS_RES_DIR}"
HARNESS_ADDONS_RES_PATH = f"res://{HARNESS_ADDONS_DIR}"

# Bumped when the bundled harness changes; the daemon self-syncs the installed
# copy to it (#225). The installed copy declares its version in a leading header
# (`# gda-harness-version: <N>`); a mismatch re-materializes via the content
# compare. NOT the package version — the harness changes far less often.
HARNESS_VERSION = "16"

_VERSION_HEADER_PREFIX = "# gda-harness-version:"
_AUTOLOAD_HEADER = "[autoload]"
_PROJECT_FILE = "project.godot"
_BUNDLED_HARNESS = Path(__file__).parent / HARNESS_FILE


@dataclass(frozen=True)
class HarnessInstall:
    """The outcome of an ``install_harness`` call (#225, #654).

    ``changed`` is the existing ``installed_harness`` signal the daemon reports —
    True iff the file was (re)materialized OR the autoload entry was added/repointed.
    ``synced`` is True ONLY when an **already-installed** harness was rewritten to a
    new version/body (a stale→current resync — the ``harness_synced`` the daemon
    reports). A first install is NOT a sync: it is already visible via ``changed`` /
    ``installed_harness``, so ``synced`` stays False there. ``version`` is the
    version now installed on disk.

    ``created_paths`` / ``created_sections`` are the mutation receipt (#654): the
    ``res://`` paths THIS call brought into existence (outermost directory first) and
    the ``project.godot`` sections it added. Both are empty on an idempotent repeat
    install and on a version resync — nothing new appears there; the rewrite is what
    ``synced`` reports.

    The receipt says what this call CREATED, for the caller to REPORT. It is
    deliberately not the input to any undo: :class:`HarnessSnapshot` owns that, and
    owns it alone (PR #680 recheck 2). A receipt cannot describe how to reverse an
    install that rewrote a stale body or re-pointed an entry — those create nothing —
    and an install that fails part way through produces no receipt at all.
    """

    changed: bool
    synced: bool
    version: str
    created_paths: tuple[str, ...] = ()
    created_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class HarnessUninstall:
    """The outcome of an ``uninstall_harness`` call (#225, #654).

    ``removed`` is True iff anything was removed (the autoload entry, the files
    and/or a now-empty ``[autoload]`` section); False is the idempotent no-op when
    the harness was not installed.

    ``removed_paths`` / ``removed_sections`` are the removal receipt (#654): the
    ``res://`` paths deleted (innermost file first, the addon directory last) and the
    ``project.godot`` sections dropped. ``removed`` True with BOTH lists empty means
    the ``[autoload]`` ENTRY was the only thing left to remove — the harness files
    were already gone AND a sibling autoload keeps the section alive, so neither
    list has anything to report.
    """

    removed: bool
    removed_paths: tuple[str, ...] = ()
    removed_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ConfigEdit:
    """One ``project.godot`` edit: the new text, whether it changed, which sections.

    ``sections`` names the section headers the edit ADDED (``_ensure_autoload``) or
    DROPPED (``_remove_autoload``) — the half of the #654 mutation receipt that lives
    inside the config file, as opposed to the filesystem paths.
    """

    text: str
    changed: bool
    sections: tuple[str, ...] = ()


def _autoload_line() -> str:
    # Enabled-singleton form: the res:// path prefixed with "*" (issue #119).
    return f'{HARNESS_AUTOLOAD_NAME}="*{HARNESS_RES_PATH}"'


def _line_ending(text: str) -> str:
    """The terminator the text's FIRST line uses (``\\r\\n`` or ``\\n``).

    Rejoining with it keeps a CRLF ``project.godot`` CRLF (#654). A file with mixed
    terminators normalizes to its first one — the documented limit of the
    byte-identity guarantee.
    """
    index = text.find("\n")
    if index > 0 and text[index - 1] == "\r":
        return "\r\n"
    return "\n"


def _read_config(path: Path) -> str:
    """Read ``project.godot`` with newline translation OFF, so CRLF survives (#654)."""
    return path.read_text(encoding="utf-8", newline="")


def _write_config(path: Path, text: str) -> None:
    """Write ``project.godot`` verbatim — no newline translation on the way out."""
    path.write_text(text, encoding="utf-8", newline="")


def _split_config(text: str) -> tuple[list[str], str, str]:
    """A config text as (terminator-free lines, line ending, trailing terminator)."""
    eol = _line_ending(text)
    return text.splitlines(), eol, eol if text.endswith(("\n", "\r")) else ""


def _is_section_header(stripped: str) -> bool:
    """Whether a stripped config line is an INI section header (``[name]``)."""
    return stripped.startswith("[") and stripped.endswith("]")


def _version_header() -> str:
    return f"{_VERSION_HEADER_PREFIX} {HARNESS_VERSION}"


def _materialized_content() -> str:
    """The exact bytes the installed harness should hold: version header + body."""
    return f"{_version_header()}\n{_BUNDLED_HARNESS.read_text(encoding='utf-8')}"


def _harness_dest(project: Path) -> Path:
    return project / HARNESS_RES_DIR / HARNESS_FILE


def _harness_uid(project: Path) -> Path:
    return project / HARNESS_RES_DIR / HARNESS_UID_FILE


def harness_artifacts(project: Path) -> tuple[Path, ...]:
    """Every file in ``project`` that the harness install owns: script + ``.uid``.

    The ONLY enumeration of them, in deletion order (the script first, then the
    sidecar). Every consumer reads it rather than restating it: :func:`_remove_files`
    deletes exactly these, and :class:`HarnessSnapshot` captures exactly these (plus
    ``project.godot``) for both transactional callers — ``gda export run``'s strip
    (ADR-0028) and ``gda daemon start``'s failed-start restore. A second
    hand-maintained list would let them drift — a file one side removes but the
    other never captured would simply never come back, breaking the "left
    byte-identical" guarantee (#654; the drift risk was called out in PR #680 review,
    which is why removal now iterates this instead of its own tuple).
    """
    return (_harness_dest(project), _harness_uid(project))


def harness_directories(project: Path) -> tuple[Path, ...]:
    """The directories an install may create, outermost first.

    The companion of :func:`harness_artifacts` — ``install_harness``'s
    ``mkdir(parents=True)`` brings these into existence, so a transaction that has to
    undo an install needs to know which of them it made. Captured by
    :class:`HarnessSnapshot` as "did this exist beforehand?", which is what lets the
    restore remove the ones gda created and keep the ones the project already had.
    """
    return (project / HARNESS_ADDONS_DIR, project / HARNESS_RES_DIR)


def _res_path(project: Path, path: Path) -> str:
    """A project-internal path as the string results and diagnostics report it.

    ``res://…`` for everything inside the project tree, except ``project.godot``
    itself, which every other message in this area already calls by its plain name.
    """
    relative = path.relative_to(project).as_posix()
    return relative if relative == _PROJECT_FILE else f"res://{relative}"


@dataclass(frozen=True)
class HarnessSnapshot:
    """The EXACT pre-mutation bytes of every file a harness install or strip touches.

    The shared transactional mechanism behind both callers that must be able to hand
    a project back untouched:

    - ``gda export run`` (ADR-0028) strips the harness so it cannot reach the
      artifact, then restores this snapshot — NOT a fresh install, which would
      canonicalize a noncanonical autoload, synthesize one for a stray harness file
      that had none, or rewrite a stale body to the current version.
    - ``gda daemon start`` (#654, PR #680 recheck) installs the harness BEFORE the
      daemon exists, so a start that never comes ready restores this snapshot.

    Snapshot-EXACT is what makes the second caller correct, and a receipt of what the
    install created cannot substitute for it. An install that RE-MATERIALIZES a stale
    harness body, or RE-POINTS an existing autoload entry, creates nothing — so a
    receipt-driven rollback has no prior bytes to put back and silently leaves the
    rewrite in place. Only the bytes captured here can restore that.

    The file list is ``project.godot`` plus :func:`harness_artifacts`, and the
    directory list is :func:`harness_directories`, so neither can drift from what an
    install writes or an uninstall removes. An ABSENT file is recorded faithfully as
    ``None`` and restored by DELETION; an absent DIRECTORY is recorded the same way
    and restored by ``rmdir``. That is what makes a fresh install reversible by the
    same mechanism as a resync — and what makes the restore **receipt-independent**:
    it needs nothing from the operation it is undoing, so it can also undo an
    operation that failed PART WAY THROUGH and produced no receipt at all (PR #680
    recheck 2 — a ``project.godot`` that cannot be written leaves ``install_harness``
    raising after it has already materialized the harness file).

    Held in memory for the duration of one operation and never written to disk: the
    "no recorded pre-install state" rule of #654 is about persisted markers left in
    the user's project, which this never creates.
    """

    project: Path
    files: tuple[tuple[Path, Optional[bytes]], ...]
    absent_directories: tuple[Path, ...]

    @classmethod
    def capture(cls, project: Path) -> "HarnessSnapshot":
        paths = (project / _PROJECT_FILE, *harness_artifacts(project))
        return cls(
            project,
            tuple(
                (path, path.read_bytes() if path.exists() else None) for path in paths
            ),
            tuple(
                directory
                for directory in harness_directories(project)
                if not directory.is_dir()
            ),
        )

    def restore(self) -> tuple[str, ...]:
        """Put the project back as captured; returns a label per thing actually changed.

        A file absent at capture is deleted (the caller created it); otherwise its
        exact bytes are rewritten — but only when the current state differs, so a
        no-op restore touches nothing and cannot bump an mtime against a concurrent
        editor (ADR-0018). ``project.godot`` comes first, so a partially-completed
        restore never leaves an autoload entry pointing at a script already gone.

        Directories absent at capture are then removed innermost-first, and ONLY when
        empty — a directory that meanwhile acquired other content belongs to whoever
        put it there. A directory that already existed is never touched.
        """
        changed: list[str] = []
        for path, before in self.files:
            current = path.read_bytes() if path.exists() else None
            if current == before:
                continue
            label = _res_path(self.project, path)
            if before is None:
                path.unlink()
                changed.append(f"removed {label}")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(before)
                changed.append(f"restored {label}")
        for directory in reversed(self.absent_directories):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
                changed.append(f"removed {_res_path(self.project, directory)}")
        return tuple(changed)

    def pending(self) -> tuple[str, ...]:
        """The captured paths whose on-disk state still differs from the snapshot.

        What a caller reports when its own restore failed: the REAL residual delta,
        measured rather than predicted, so the user is told exactly what is left to
        put right by hand — files whose bytes differ, then directories that were
        absent at capture but still exist (a restore can fail after the files are
        already back, leaving only directory residue; PR #680 recheck 3).

        NEVER raises for a per-path I/O failure: this runs on error-reporting
        paths, where a thrown measurement would displace the original failure
        (PR #688 recheck). A path that cannot be read cannot be confirmed
        restored, so it IS residue — reported with the reason it could not be
        measured; the other paths stay individually measured.
        """
        residue: list[str] = []
        for path, before in self.files:
            label = _res_path(self.project, path)
            try:
                current = path.read_bytes() if path.exists() else None
            except OSError as exc:
                residue.append(f"{label} (state unmeasurable: {exc})")
                continue
            if current != before:
                residue.append(label)
        for directory in self.absent_directories:
            label = _res_path(self.project, directory)
            try:
                if directory.is_dir():
                    residue.append(label)
            except OSError as exc:
                residue.append(f"{label} (state unmeasurable: {exc})")
        return tuple(residue)


def installed_harness_version(project: Path) -> Optional[str]:
    """The version declared in the installed harness's header, or None if absent.

    Reads the leading ``# gda-harness-version: <N>`` comment ``_materialize``
    prepends. Returns None when no harness file is installed or its header is
    missing/unrecognized (treated as a mismatch -> re-materialize).
    """
    dest = _harness_dest(project)
    if not dest.exists():
        return None
    first = dest.read_text(encoding="utf-8").splitlines()[:1]
    if first and first[0].startswith(_VERSION_HEADER_PREFIX):
        return first[0][len(_VERSION_HEADER_PREFIX) :].strip()
    return None


def _materialize(project: Path) -> bool:
    """Write the bundled harness under res://addons; True iff it changed on disk.

    The destination content is the version header + the bundled body, so a version
    bump (or a body change) is a content difference — re-materialize only then,
    never unconditionally (an mtime bump would trip the concurrent-editor prompt).
    """
    dest = _harness_dest(project)
    content = _materialized_content()
    if dest.exists() and dest.read_text(encoding="utf-8") == content:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return True


def _ensure_autoload(text: str) -> _ConfigEdit:
    """Ensure the harness autoload line is present in ``[autoload]``.

    The "already present" decision is scoped to the ``[autoload]`` section: only an
    EXACT GdaHarness line *inside* ``[autoload]`` is a no-op. There is no global
    early return on the line appearing anywhere in the file, so a same-named key in
    another section is never consulted, re-pointed, or removed (PR #247 review).

    The returned :class:`_ConfigEdit` names the ``[autoload]`` section in
    ``sections`` when this call had to CREATE it — the half of the #654 receipt
    ``_remove_autoload`` mirrors when it drops the section again.
    """
    line = _autoload_line()
    lines, eol, trailing = _split_config(text)

    # Re-point an existing GdaHarness entry, or insert a fresh one — both scoped to
    # the [autoload] section, so a same-named key in another section is never
    # touched (PR #247 review; symmetric with _remove_autoload).
    section: Optional[str] = None
    autoload_header_index: Optional[int] = None
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        section = _section_of(stripped, section)
        if section != _AUTOLOAD_HEADER:
            continue
        if stripped == _AUTOLOAD_HEADER:
            if autoload_header_index is None:
                autoload_header_index = i
        elif stripped.startswith(f"{HARNESS_AUTOLOAD_NAME}="):
            # A GdaHarness entry inside [autoload]: a no-op when already exact,
            # otherwise re-point it in place.
            if stripped == line:
                return _ConfigEdit(text, False)
            lines[i] = line
            return _ConfigEdit(eol.join(lines) + trailing, True)

    # An existing [autoload] section with no GdaHarness entry — insert right after
    # its header, preserving any sibling autoloads.
    if autoload_header_index is not None:
        lines.insert(autoload_header_index + 1, line)
        return _ConfigEdit(eol.join(lines) + trailing, True)

    # No [autoload] section — append one at EOF (sections may appear in any order).
    # The leading blank line is the section separator ``_drop_emptied_autoload_sections``
    # takes back when uninstall empties the section again (#654).
    base = text if text.endswith(("\n", "\r")) else text + eol
    return _ConfigEdit(
        f"{base}{eol}{_AUTOLOAD_HEADER}{eol}{eol}{line}{eol}",
        True,
        (_AUTOLOAD_HEADER,),
    )


def _created_paths(project: Path) -> tuple[str, ...]:
    """The ``res://`` paths a materialize would CREATE, outermost directory first.

    Read BEFORE ``_materialize`` runs: whatever is missing now is exactly what its
    ``mkdir(parents=True)`` + write brings into existence, so this is the install
    half of the #654 receipt. Empty when the harness file already exists (an
    idempotent repeat install or a version resync creates nothing).
    """
    return tuple(
        res_path
        for path, res_path in (
            (project / HARNESS_ADDONS_DIR, HARNESS_ADDONS_RES_PATH),
            (project / HARNESS_RES_DIR, HARNESS_RES_DIR_PATH),
            (_harness_dest(project), HARNESS_RES_PATH),
        )
        if not path.exists()
    )


def install_harness(project: Path) -> HarnessInstall:
    """Idempotently install the harness autoload into ``project`` (#225, #654).

    Returns a :class:`HarnessInstall`: ``changed`` (the ``installed_harness`` the
    daemon reports — ``True`` on a first install or a re-materialize/re-point),
    ``synced`` (``True`` only when an **already-installed** harness was rewritten to
    a new version/body — the ``harness_synced`` the daemon reports), the ``version``
    now on disk, and the ``created_paths`` / ``created_sections`` receipt naming
    exactly what this call added to the project (#654).
    """
    existed = _harness_dest(project).exists()
    created_paths = _created_paths(project)
    materialized = _materialize(project)
    project_godot = project / _PROJECT_FILE
    edit = _ensure_autoload(_read_config(project_godot))
    if edit.changed:
        _write_config(project_godot, edit.text)
    return HarnessInstall(
        changed=materialized or edit.changed,
        # A *resync*, not a first install: the file must have already existed AND
        # been rewritten (stale version/body → current). A first install rewrites
        # too, but is reported by ``changed`` / ``installed_harness`` (PR #247 review).
        synced=existed and materialized,
        version=HARNESS_VERSION,
        created_paths=created_paths if materialized else (),
        created_sections=edit.sections,
    )


def _section_of(stripped: str, current: Optional[str]) -> Optional[str]:
    """The active INI section after a stripped line, or ``current`` if unchanged.

    A section header is ``[name]``; any other line leaves the section as-is. Used to
    scope harness-key edits to ``[autoload]`` so a same-named key in another section
    of ``project.godot`` is never touched (PR #247 review).
    """
    if _is_section_header(stripped):
        return stripped
    return current


def _drop_emptied_autoload_sections(
    lines: list[str], headers: set[int]
) -> tuple[list[str], tuple[str, ...]]:
    """Drop the named ``[autoload]`` sections if now key-less; (lines, dropped).

    ``headers`` holds the ``lines`` indices of the ``[autoload]`` headers a harness
    entry was actually removed from — the ONLY sections this may drop. A section gda
    emptied would otherwise survive as a bare header, keeping a tracked
    ``project.godot`` modified after every live session (GDA-DF-020, #654), but an
    unrelated ``[autoload]`` section that was ALREADY empty before this call is none
    of gda's business and stays (PR #680 review). Scoping the removal to the touched
    section is what makes "a pre-existing empty section is not gda's to remove" true
    of the code and not just of the docs.

    Deletes in DESCENDING index order so removing a later span cannot shift the
    index of one not yet visited.
    """
    kept = list(lines)
    dropped: list[str] = []
    for index in sorted(headers, reverse=True):
        span = _emptied_autoload_span(kept, index)
        if span is None:
            continue  # a sibling autoload survives -> the section stays
        del kept[span[0] : span[1]]
        dropped.append(_AUTOLOAD_HEADER)
    return kept, tuple(dropped)


def _emptied_autoload_span(lines: list[str], index: int) -> Optional[tuple[int, int]]:
    """The ``[start, end)`` slice to delete for a key-less ``[autoload]``, else None.

    The section spans its header at ``index`` up to the next section header (or EOF),
    so removing it takes the blank lines inside it. When it ran to EOF the span also
    takes the ONE blank separator line in front of it, because nothing follows to be
    separated from — together that is the exact inverse of the
    ``\\n[autoload]\\n\\n<entry>\\n`` ``_ensure_autoload`` appends, so the file returns
    to its pre-install bytes. A mid-file section keeps that separator: it still
    divides the two neighbours.
    """
    if index >= len(lines) or lines[index].strip() != _AUTOLOAD_HEADER:
        return None
    end = index + 1
    while end < len(lines) and not _is_section_header(lines[end].strip()):
        end += 1
    if any(line.strip() for line in lines[index + 1 : end]):
        return None
    start = index
    if end == len(lines) and start > 0 and not lines[start - 1].strip():
        start -= 1
    return start, end


def _remove_autoload(text: str) -> _ConfigEdit:
    """Drop the harness autoload line from ``project.godot`` text.

    Removes only the ``GdaHarness=...`` line **inside the ``[autoload]`` section**,
    leaving any sibling autoloads intact (the inverse of ``_ensure_autoload``). A
    same-named key in another section is left untouched. When that empties the
    section the harness entry sat in, the header goes too
    (:func:`_drop_emptied_autoload_sections`, #654) and the returned
    :class:`_ConfigEdit` names it in ``sections``.
    """
    lines, eol, trailing = _split_config(text)
    section: Optional[str] = None
    kept: list[str] = []
    # The `kept` index of the [autoload] header now in scope, and the headers a
    # harness entry was actually dropped from — only those may lose their section.
    header_index: Optional[int] = None
    emptied: set[int] = set()
    for raw in lines:
        stripped = raw.strip()
        section = _section_of(stripped, section)
        if section == _AUTOLOAD_HEADER:
            if stripped == _AUTOLOAD_HEADER:
                header_index = len(kept)
            elif stripped.startswith(f"{HARNESS_AUTOLOAD_NAME}="):
                if header_index is not None:
                    emptied.add(header_index)
                continue  # drop the autoload entry only
        kept.append(raw)
    if len(kept) == len(lines):
        return _ConfigEdit(text, False)
    kept, dropped = _drop_emptied_autoload_sections(kept, emptied)
    return _ConfigEdit(eol.join(kept) + trailing, True, dropped)


def _remove_files(project: Path) -> tuple[str, ...]:
    """Delete the harness file, its ``.uid`` sidecar and the emptied addon dir.

    Iterates :func:`harness_artifacts` — the single authority for what the install
    owns — and derives the receipt from the same entries, so adding an artifact
    there extends deletion, the receipt and ADR-0028's export snapshot at once
    (PR #680 review). Returns the ``res://`` paths actually removed (the filesystem
    half of the #654 receipt). The engine writes the ``.uid`` sidecar itself, but it
    names gda's script, so it is gda's footprint — and until it goes the addon
    directory is never empty, so the directory removal below never fires
    (GDA-DF-009).

    ``res://addons`` is deliberately left alone even when this empties it, for two
    reasons that do NOT apply to the ``[autoload]`` section this module does remove.
    An empty directory is invisible to git, so it causes none of the tracked-file
    churn that motivated #654 — there is nothing to clean up. And ``addons/`` is the
    shared Godot-convention directory: another addon may be about to populate it, and
    removing it under that addon buys nothing. Install still reports it in
    ``created_paths`` when gda made it, so the one path this does not reverse is on
    the receipt.
    """
    removed: list[str] = []
    for path in harness_artifacts(project):
        if path.exists():
            path.unlink()
            removed.append(_res_path(project, path))
    addon_dir = project / HARNESS_RES_DIR
    if addon_dir.is_dir() and not any(addon_dir.iterdir()):
        addon_dir.rmdir()
        removed.append(HARNESS_RES_DIR_PATH)
    return tuple(removed)


def uninstall_harness(project: Path) -> HarnessUninstall:
    """Idempotently remove the harness autoload and files from ``project`` (#225, #654).

    Crash-safe ordering (ADR-0018, D2): strip the ``[autoload]`` entry **first**
    (a single atomic ``write_text``), then delete the files — so a mid-failure
    leaves only a harmless stray inert ``.gd``, never a dangling autoload pointing
    at a missing script (which an exported game logs ``ERR_CONTINUE`` and skips at
    startup — error spam, not a hard crash; ADR-0028). Returns a
    :class:`HarnessUninstall`; ``removed`` is ``False`` (a no-op success) when
    nothing is installed (mirrors ``daemon stop``).

    **Byte-identity (#654).** After ``install_harness`` → ``uninstall_harness``,
    ``project.godot`` holds its pre-install bytes: the entry, the ``[autoload]``
    section gda appended and that section's blank separator all come back off, and
    the file's own line terminator is preserved. Scoped to exclude the three
    malformed-input shapes the module docstring enumerates (mixed terminators, no
    final terminator, CR-only), none of which Godot's own writer can produce.

    Two states are outside the guarantee by design:

    - the ``[autoload]`` section the harness entry sat in is dropped even if it was
      ALREADY empty before the install. Closing this one WOULD need recorded
      pre-install state, which this module refuses to write into the project — and
      Godot's own ``ConfigFile`` writer never emits an empty section, so the input
      is degenerate. (An empty ``[autoload]`` section the harness never joined is a
      different matter and IS left alone — see
      :func:`_drop_emptied_autoload_sections`.)
    - an ``addons/`` directory gda created is left in place. Here the reason is not
      missing state (uninstall could infer it just as well as it infers the empty
      section) but that removal would buy nothing: see :func:`_remove_files`.
    """
    project_godot = project / _PROJECT_FILE
    edit = _ConfigEdit("", False)
    if project_godot.exists():
        edit = _remove_autoload(_read_config(project_godot))
        if edit.changed:
            _write_config(project_godot, edit.text)
    removed_paths = _remove_files(project)
    return HarnessUninstall(
        removed=edit.changed or bool(removed_paths),
        removed_paths=removed_paths,
        removed_sections=edit.sections,
    )
