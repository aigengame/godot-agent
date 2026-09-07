"""The import-evidence adapter: one asset's cache verdict, as the engine reads it.

Lifted out of ``gda.commands.resource`` (#741) so the engine-parity contract
below has a seam of its own. ADR-0040 keeps a group module's whole command slice
(params/result models, render, recipe, command body) in the group and hosts
non-command engine knowledge in the core, as ``binary`` and ``display`` already
do; the dependency direction stays commands -> core only, so nothing here
imports Typer, the CLI, or the wire models.

The adapter answers with EVIDENCE only — the four states below. A settlement
(``imported`` / ``not_importable`` / ``failed``) is the command's post-pass
verdict over the same artifacts, never something this module can return.

One asset's evidence state, read as the engine's own reimport test reads it.

A faithful adaptation of ``EditorFileSystem::_test_for_reimport`` (#738
review), in the engine's own order: an unparseable or ``valid=false``
sidecar is ``invalid`` (the engine SKIPS these rather than retrying), and
so is an unparseable ``.md5`` receipt — the engine's receipt parse-error
branch is the same deliberate skip, never a re-import (#738 re-review 5);
gda's receipt grammar covers the quoted-string assignments the engine
writes plus VariantParser spacing, ``;`` comments, JSON-style escapes
(lone UTF-16 surrogates excluded, as VariantParser rejects them), and
repeated assignments (the last value wins). Broader Variant value syntax errs
toward ``invalid``, the no-pass direction the contract sanctions; a
``keep``/``skip`` importer is ``cached``; the pre-UID format, a missing
remap/destination file, a ``source_file`` naming a different source (a
copied sidecar), a missing ``.md5`` receipt (located at the PATH-derived
import base, as the engine locates it), or a ``source_md5`` /
``dest_md5`` disagreeing with the actual bytes are all ``stale`` (the
engine WOULD re-import). ``cached`` needs POSITIVE evidence: a keep/skip
importer, or the path-derived receipt present and matching — with any
DECLARED destinations also present and digest-checked; a sidecar
declaring none but carrying a matching receipt passes the same checks
(#738 re-review 4; the engine's own pass leaves it untouched when the
declared remainder below is controlled — verified live). A sidecar with no importer line proves nothing
and is conservatively ``stale`` (#738 re-review 2). The checks the engine makes
from its own state — whether the DECLARED importer still exists (its
registry is open: import plugins add names, so no offline list can be
authoritative), its format version, its project-settings validity, and
the editor cache's expected sidecar MD5 — cannot be read from the
project's artifacts, so a sidecar drifted in those dimensions can look
``cached`` here until any pass runs; the contract names that remainder,
and its direction: it can delay a re-import until the next pass, never
spend a pass the engine would not.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

EvidenceStatus = Literal["cached", "missing", "stale", "invalid"]
"""The four states the adapter can read from a project's own artifacts."""

CreatedFileClass = Literal["cache_owned", "source_adjacent"]
"""Which side of the cache root a file the engine pass created falls on."""

# The engine's cache directory, project-relative: the single authority for that
# layout, read by every consumer rather than spelled again (#741). `resource
# import` reports it as the explicit `cache_root` and classifies created files
# against it; `export run`'s tree-mutation report reuses the same rule (#839).
CACHE_ROOT_REL = ".godot"


@dataclass(frozen=True)
class AssetEvidence:
    """One asset's evidence verdict and the sidecar facts behind it.

    ``sidecar`` is the ``res://`` path of the ``.import`` sidecar that was read,
    or ``None`` when the asset has none; ``dest_files`` are the destinations that
    sidecar declares, in the engine's own order (empty when there is no sidecar
    or it declares none).
    """

    status: EvidenceStatus
    sidecar: "str | None" = None
    dest_files: list[str] = field(default_factory=list)


def classify_created_file(rel: str) -> CreatedFileClass:
    """Which side of the cache root a created file falls on (#741).

    ``rel`` is a project-relative posix path. A file under the project's
    ``.godot/`` is ``cache_owned``; anything else the engine pass wrote beside
    the sources (an asset's ``.import`` sidecar, a script's ``.uid``) is
    ``source_adjacent``.
    """
    return (
        "cache_owned"
        if rel == CACHE_ROOT_REL or rel.startswith(CACHE_ROOT_REL + "/")
        else "source_adjacent"
    )


_DEST_FILES_LINE = re.compile(r"^dest_files=(\[.*\])$", re.MULTILINE)
_INVALID_LINE = re.compile(r"^valid=false$", re.MULTILINE)
_RECEIPT_ASSIGNMENT_LINE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:\\.|[^"\\])*")\s*(?:;.*)?$'
)
_IMPORTER_LINE = re.compile(r'^importer="([^"]*)"$', re.MULTILINE)
_UID_LINE = re.compile(r'^uid="[^"]*"$', re.MULTILINE)
_SOURCE_FILE_LINE = re.compile(r'^source_file="([^"]*)"$', re.MULTILINE)
_PATH_LINE = re.compile(r'^path[.\w]*="([^"]*)"$', re.MULTILINE)
_FILES_LINE = re.compile(r"^files=(\[.*\])$", re.MULTILINE)
# The engine keeps ONE `.md5` receipt per asset at `<import base>.md5`, where
# the import base is DERIVED FROM THE ASSET PATH — `.godot/imported/
# <filename>-<md5 of the res:// path>` (ResourceFormatImporter::
# get_import_base_path) — independent of whether the sidecar declares any
# destinations. Deriving it the same way (verified against a real import's
# hash) is what lets the verdict follow the engine on a no-destination
# sidecar (#738 re-review 4).


def _parse_receipt_assignments(text: str) -> "dict[str, str] | None":
    """Parse gda's documented VariantParser-compatible receipt subset.

    Godot writes quoted-string assignments. Its parser also permits spacing,
    ``;`` comments, JSON-style escapes, and repeated keys; assignments are
    applied in order, so the last value wins. A broader Variant value returns
    ``None`` so the caller takes the contract's conservative no-pass direction
    — as does a lone UTF-16 surrogate escape, which json accepts but
    VariantParser rejects (the engine's parse-error skip).
    """
    assignments: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        assignment = _RECEIPT_ASSIGNMENT_LINE.match(line)
        if assignment is None:
            return None
        try:
            value = json.loads(assignment.group(2))
        except (TypeError, ValueError):
            return None
        if any("\ud800" <= ch <= "\udfff" for ch in value):
            # json.loads accepts a LONE UTF-16 surrogate escape; VariantParser
            # rejects it ("unpaired lead/trail surrogate", TK_ERROR) — the
            # engine's deliberate skip. Paired surrogates decode to a real
            # code point on both sides, so any surrogate left in the decoded
            # value is lone by construction. Stay on the no-pass side.
            return None
        assignments[assignment.group(1)] = value
    return assignments


# The two marker files the engine's scan skips a directory on. Named here, not
# spelled inline, because the same two literals are declared a second time in
# ``operations.gd`` (``NESTED_PROJECT_MARKER`` / ``GDIGNORE_MARKER``) for the walk
# — one rule, two languages. ``test_the_two_spellings_of_the_skip_markers_agree``
# reads both files and fails if they drift apart (#808 review).
NESTED_PROJECT_MARKER = "project.godot"
GDIGNORE_MARKER = ".gdignore"


def _engine_skips_directory_of(project: Path, rel: str) -> bool:
    """Whether the engine's own scan never reaches ``rel`` (#804).

    Two clauses of ``EditorFileSystem``'s scan decide this, and the prediction
    needs BOTH because the scan asks them in order:

    * ``_scan_new_dir`` drops every **dot-prefixed directory** before it
      consults the skip rule at all (``editor/file_system/
      editor_file_system.cpp:1157-1168``, line numbers from the 4.6.3-stable
      tag) — so ``res://.hidden/h.png`` is unreachable however ordinary it
      looks. This clause subsumes the ``.godot`` cache and a ``.git`` checkout,
      at any depth rather than at the project root alone;
    * ``_should_skip_directory`` (same file, ``3460-3480``) then skips a
      directory holding a ``project.godot`` — another project inside this one —
      or a ``.gdignore`` marker.

    Every directory ABOVE ``rel`` up to (but never including) the project root
    is asked, because one marker hides the whole subtree.

    **This is not the walk's rule, and must not be read as it.** The same two
    markers gate ``_should_descend`` in ``operations.gd``, but that walk answers
    a different question — what gda ENUMERATES — and deliberately keeps hidden
    and dot-prefixed directories in (#54, #712). This predicate answers what the
    ENGINE reaches, so it drops them. Two further divergences are known and
    stated rather than chased: ``Path.rglob`` does not descend a symlinked
    directory while the walk does (#760), so a stale asset behind a link is not
    predicted — an omission, never a false promise, and the real run's
    ``created`` list stays authoritative; and the OS "hidden" attribute the
    engine also honours (``DirAccess::current_is_hidden``) has no portable
    Python reading, so only the dot-prefix half of that clause is modelled.

    Cost: the ancestors are re-probed per sidecar and memoized nowhere — 2000
    sidecars at depth 4 cost ~16k ``stat`` calls, measured at 0.11 s. A cache
    was declined for the same reason the walk declines one: the state would buy
    nothing at this size.
    """
    parts = Path(rel).parent.parts
    for depth in range(1, len(parts) + 1):
        if parts[depth - 1].startswith("."):
            return True
        directory = project.joinpath(*parts[:depth])
        if (directory / NESTED_PROJECT_MARKER).is_file():
            return True
        if (directory / GDIGNORE_MARKER).is_file():
            return True
    return False


def asset_state(project: Path, res_path: str) -> AssetEvidence:
    """One asset's evidence state; the module docstring states the contract."""
    rel = res_path[len("res://") :]
    sidecar_fs = project / (rel + ".import")
    if not sidecar_fs.is_file():
        return AssetEvidence(status="missing")
    sidecar_res = res_path + ".import"

    def state(
        status: EvidenceStatus, dests: "list[str] | None" = None
    ) -> AssetEvidence:
        return AssetEvidence(
            status=status,
            sidecar=sidecar_res,
            dest_files=dests or [],
        )

    try:
        text = sidecar_fs.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # The engine's parse-error branch: skip, never auto-reimport.
        return state("invalid")
    if _INVALID_LINE.search(text):
        return state("invalid")
    importer = _IMPORTER_LINE.search(text)
    if importer is None:
        # No importer DECLARED: nothing proves this sidecar's cache.
        # Conservatively stale (#738 re-review 2). Whether a declared name
        # still RESOLVES is engine state (an open registry) — part of the
        # declared remainder, not decidable here.
        return state("stale")
    if importer.group(1) in ("keep", "skip"):
        return state("cached")
    dest_match = _DEST_FILES_LINE.search(text)
    dests: list[str] = []
    if dest_match is not None:
        try:
            dests = [str(d) for d in json.loads(dest_match.group(1))]
        except ValueError:
            return state("invalid")
    if _UID_LINE.search(text) is None:
        return state("stale", dests)  # pre-UID format: the engine re-imports
    # Every remap/destination reference must exist (path=, path.<variant>=,
    # files=[...], dest_files=[...] — the engine's to_check set).
    to_check = list(dests)
    to_check.extend(_PATH_LINE.findall(text))
    files_match = _FILES_LINE.search(text)
    if files_match is not None:
        try:
            to_check.extend(str(f) for f in json.loads(files_match.group(1)))
        except ValueError:
            return state("invalid")
    for ref in to_check:
        if ref.startswith("res://") and not (project / ref[len("res://") :]).is_file():
            return state("stale", dests)
    source_file = _SOURCE_FILE_LINE.search(text)
    if source_file is not None and source_file.group(1) != res_path:
        return state("stale", dests)  # a copied sidecar names another source
    # The engine's one .md5 receipt per asset, at the path-derived import
    # base — read whether or not destinations are declared, exactly as
    # _test_for_reimport reads it. A missing receipt is what the engine
    # re-imports; a present, matching one is the POSITIVE evidence a cached
    # verdict needs — including for a sidecar that declares no destinations,
    # which the engine leaves untouched (#738 re-review 4, verified live).
    receipt = (
        project
        / CACHE_ROOT_REL
        / "imported"
        / (
            Path(rel).name
            + "-"
            + hashlib.md5(res_path.encode("utf-8")).hexdigest()
            + ".md5"
        )
    )
    if not receipt.is_file():
        return state("stale", dests)
    receipt_text = receipt.read_text(encoding="utf-8", errors="replace")
    # The engine parses the receipt with VariantParser, and ANY parse error
    # is the same deliberate skip as a valid=false sidecar ("skip and let
    # user attempt manual reimport to avoid reimport loop") — never a
    # re-import (#738 re-review 5). Parse assignments in engine order: Godot's
    # VariantParser applies every assignment, so repeated keys are last-write-
    # wins (#738 re-review 6). The engine writes quoted-string values; accept
    # that public subset plus its spacing/comments/escapes, while broader
    # Variant values conservatively take the sanctioned no-pass direction.
    assignments = _parse_receipt_assignments(receipt_text)
    if assignments is None:
        return state("invalid", dests)
    recorded_source = assignments.get("source_md5")
    if recorded_source is None:
        # Parseable but lacking source_md5: the engine's "Lacks md5, so
        # just reimport" — a pass state, unlike the parse error above.
        return state("stale", dests)
    if hashlib.md5((project / rel).read_bytes()).hexdigest() != recorded_source:
        return state("stale", dests)
    recorded_dest = assignments.get("dest_md5")
    if dests and recorded_dest:
        # The engine's multi-file digest: one MD5 over every destination's
        # bytes, in the sidecar's order (FileAccess::get_multiple_md5).
        ctx = hashlib.md5()
        for dest in dests:
            dest_fs = project / dest[len("res://") :]
            if dest_fs.is_file():
                ctx.update(dest_fs.read_bytes())
        if ctx.hexdigest() != recorded_dest:
            return state("stale", dests)
    return state("cached", dests)


def project_import_gaps(project: Path, requested: set[str]) -> list[str]:
    """Other assets the project-wide pass WILL re-import (#738 review).

    The dry-run inventory's project-wide half: every asset OUTSIDE the request
    whose committed sidecar fails an engine check (``stale``) — the states the
    engine's own reimport test acts on. ``invalid`` sidecars are EXCLUDED: the
    engine deliberately skips a previously failed import (verified against a
    live pass — the invalid sidecar's bytes stay untouched). Assets with NO
    sidecar (and the ``.uid`` sidecars the pass may generate) cannot be
    predicted from here — the engine decides those — so the real run's
    ``created`` list stays the authoritative inventory, and the contract says
    so.

    An asset the engine's scan never reaches is not a gap either (#804): the
    pass skips a nested project's, a ``.gdignore``d and a dot-prefixed
    directory's contents, so predicting a re-import there promised work the
    engine will not do. That one predicate replaced the ``.godot``/``.git``
    prefix test this loop used to make, which was the same clause spelled for
    two directories at the project root only (#808 review).
    """
    gaps: list[str] = []
    for sidecar in sorted(project.rglob("*.import")):
        rel = sidecar.relative_to(project).as_posix()
        if _engine_skips_directory_of(project, rel):
            continue
        res_path = "res://" + rel[: -len(".import")]
        if res_path in requested:
            continue
        source = project / rel[: -len(".import")]
        if not source.is_file():
            continue
        if asset_state(project, res_path).status == "stale":
            gaps.append(res_path)
    return gaps
