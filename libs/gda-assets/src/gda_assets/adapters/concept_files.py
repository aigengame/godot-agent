"""Bounded local brief and selected-reference handoff files."""

import hashlib
import json
from dataclasses import fields
from pathlib import Path
import shutil

from pydantic import TypeAdapter, ValidationError

from gda_assets.adapters.file_copy import copy_with_sha256
from gda_assets.adapters.files import validate_format
from gda_assets.adapters.prompt_files import read_bounded_file
from gda_assets.application.ports import PortFailure
from gda_assets.domain.concept import (
    ConceptBrief,
    ConceptBriefSnapshot,
    ConceptSelectRequest,
    ConceptSelection,
    SelectedConcept,
    ValidatedConceptCandidate,
    validate_brief,
)


_BRIEF_LIMIT = 1024 * 1024
_HANDOFF_LIMIT = 4 * 1024 * 1024
_PNG_LIMIT = 256 * 1024 * 1024
_BRIEF = TypeAdapter(ConceptBrief)
_SELECTION = TypeAdapter(ConceptSelection)


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors(include_input=False, include_url=False)
    )


def _brief_bytes(brief: ConceptBrief) -> bytes:
    value = _BRIEF.dump_json(brief, indent=2) + b"\n"
    if len(value) > _BRIEF_LIMIT:
        raise PortFailure("invalid_concept", "Concept brief exceeds 1 MiB")
    return value


def _snapshot(path: Path) -> ConceptBriefSnapshot:
    value = read_bounded_file(path, _BRIEF_LIMIT)
    return ConceptBriefSnapshot(path, hashlib.sha256(value).hexdigest(), len(value))


class ConceptFiles:
    def read_brief(self, path: Path) -> ConceptBrief:
        try:
            content = read_bounded_file(path.resolve(strict=True), _BRIEF_LIMIT)
            raw = json.loads(content)
            expected = {item.name for item in fields(ConceptBrief)}
            if not isinstance(raw, dict) or set(raw) - expected:
                raise ValueError(
                    "Concept brief must be an object with only documented fields"
                )
            brief = _BRIEF.validate_json(content, strict=True)
            validate_brief(brief)
            return brief
        except ValidationError as exc:
            raise PortFailure(
                "invalid_concept",
                f"Invalid concept brief fields: {_validation_message(exc)}",
            ) from exc
        except (OSError, ValueError, PortFailure) as exc:
            if isinstance(exc, PortFailure) and exc.code == "invalid_concept":
                raise
            raise PortFailure(
                "invalid_concept", f"Invalid concept brief: {exc}"
            ) from exc

    def save_brief(self, record: Path, brief: ConceptBrief) -> ConceptBriefSnapshot:
        path = record / "concept-brief.json"
        try:
            with path.open("xb") as stream:
                stream.write(_brief_bytes(brief))
            return _snapshot(path)
        except PortFailure:
            raise
        except OSError as exc:
            raise PortFailure(
                "concept_select_failed", f"Could not save concept brief: {exc}"
            ) from exc

    def load_brief(self, record: Path) -> tuple[ConceptBrief, ConceptBriefSnapshot]:
        try:
            root = record.resolve(strict=True)
            path = root / "concept-brief.json"
            return self.read_brief(path), _snapshot(path)
        except PortFailure as exc:
            raise PortFailure(
                "invalid_concept", f"Invalid saved concept brief: {exc}"
            ) from exc
        except OSError as exc:
            raise PortFailure(
                "invalid_concept", f"Concept record is unavailable: {exc}"
            ) from exc

    def create_handoff(
        self,
        request: ConceptSelectRequest,
        brief: ConceptBrief,
        brief_snapshot: ConceptBriefSnapshot,
        candidates: tuple[ValidatedConceptCandidate, ...],
    ) -> ConceptSelection:
        root = request.handoff.absolute()
        try:
            root.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise PortFailure(
                "destination_conflict", f"Concept handoff destination exists: {root}"
            ) from exc
        try:
            brief_bytes = _brief_bytes(brief)
            if (
                len(brief_bytes) != brief_snapshot.size_bytes
                or hashlib.sha256(brief_bytes).hexdigest() != brief_snapshot.sha256
            ):
                raise PortFailure(
                    "invalid_concept", "Saved concept brief changed before selection"
                )
            brief_path = root / "concept-brief.json"
            brief_path.write_bytes(brief_bytes)
            references = root / "references"
            references.mkdir()
            selected = []
            for index, item in enumerate(candidates):
                source = item.output.file.path
                target = references / f"{index:03d}-{source.name}"
                try:
                    digest, size = copy_with_sha256(
                        source, target, max_bytes=_PNG_LIMIT
                    )
                    validate_format(target)
                    from PIL import Image

                    with Image.open(target) as image:
                        width, height = image.size
                except (OSError, PortFailure) as exc:
                    raise PortFailure(
                        "invalid_concept_candidate",
                        f"Candidate PNG is unavailable or invalid: {source}",
                    ) from exc
                if (
                    digest != item.output.file.sha256
                    or size != item.output.file.size_bytes
                ):
                    raise PortFailure(
                        "invalid_concept_candidate",
                        "Candidate bytes differ from their registered facts",
                    )
                if item.output.file.width is None or item.output.file.height is None:
                    raise PortFailure(
                        "invalid_concept_candidate",
                        "Candidate PNG dimensions are unavailable",
                    )
                if (width, height) != (
                    item.output.file.width,
                    item.output.file.height,
                ):
                    raise PortFailure(
                        "invalid_concept_candidate",
                        "Candidate PNG dimensions differ from registered facts",
                    )
                selected.append(
                    SelectedConcept(
                        index,
                        str(item.candidate.record),
                        item.candidate.output,
                        item.resolved_prompt_sha256,
                        target,
                        digest,
                        size,
                        item.output.file.width,
                        item.output.file.height,
                        True,
                    )
                )
            selection = ConceptSelection(
                1,
                root,
                brief,
                ConceptBriefSnapshot(
                    brief_path,
                    hashlib.sha256(brief_path.read_bytes()).hexdigest(),
                    brief_path.stat().st_size,
                ),
                tuple(selected),
            )
            self._write_handoff(selection)
            return selection
        except (OSError, PortFailure) as exc:
            shutil.rmtree(root, ignore_errors=True)
            if isinstance(exc, PortFailure):
                raise
            raise PortFailure(
                "concept_select_failed", f"Could not create concept handoff: {exc}"
            ) from exc

    def _write_handoff(self, selection: ConceptSelection) -> None:
        value = _SELECTION.dump_python(selection, mode="json")
        value["handoff"] = "."
        value["brief_snapshot"]["path"] = "concept-brief.json"
        for raw, selected in zip(value["selected"], selection.selected):
            raw["path"] = str(selected.path.relative_to(selection.handoff))
        encoded = json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"
        if len(encoded) > _HANDOFF_LIMIT:
            raise PortFailure("invalid_concept", "Concept handoff exceeds 4 MiB")
        (selection.handoff / "handoff.json").write_bytes(encoded)

    def load_handoff(self, path: Path) -> ConceptSelection:
        try:
            root = path.resolve(strict=True)
            selection = _SELECTION.validate_json(
                read_bounded_file(root / "handoff.json", _HANDOFF_LIMIT), strict=True
            )
            brief_path = root / selection.brief_snapshot.path
            selected = tuple(
                SelectedConcept(**{**item.__dict__, "path": root / item.path})
                for item in selection.selected
            )
            selection = ConceptSelection(
                **{
                    **selection.__dict__,
                    "handoff": root,
                    "brief_snapshot": ConceptBriefSnapshot(
                        brief_path,
                        selection.brief_snapshot.sha256,
                        selection.brief_snapshot.size_bytes,
                    ),
                    "selected": selected,
                }
            )
            self._verify(selection)
            return selection
        except ValidationError as exc:
            raise PortFailure(
                "invalid_concept_handoff",
                f"Invalid concept handoff fields: {_validation_message(exc)}",
            ) from exc
        except (OSError, ValueError, PortFailure) as exc:
            if isinstance(exc, PortFailure) and exc.code == "invalid_concept_handoff":
                raise
            raise PortFailure(
                "invalid_concept_handoff", f"Invalid concept handoff: {exc}"
            ) from exc

    def _verify(self, selection: ConceptSelection) -> None:
        if not selection.selected or len(selection.selected) > 8:
            raise ValueError("Concept handoff selection count is invalid")
        if not selection.brief_snapshot.path.resolve().is_relative_to(
            selection.handoff
        ):
            raise ValueError("Concept brief snapshot escapes its handoff")
        brief = read_bounded_file(selection.brief_snapshot.path, _BRIEF_LIMIT)
        if (
            hashlib.sha256(brief).hexdigest() != selection.brief_snapshot.sha256
            or len(brief) != selection.brief_snapshot.size_bytes
        ):
            raise ValueError("Concept brief changed")
        validate_brief(selection.brief)
        if _BRIEF.validate_json(brief, strict=True) != selection.brief:
            raise ValueError("Concept brief facts differ")
        for index, item in enumerate(selection.selected):
            if (
                item.index != index
                or item.generation_completed_by_caller is not True
                or not item.path.resolve().is_relative_to(selection.handoff)
            ):
                raise ValueError("Concept selected reference metadata is invalid")
            data = read_bounded_file(item.path, _PNG_LIMIT)
            validate_format(item.path)
            from PIL import Image

            with Image.open(item.path) as image:
                dimensions = image.size
            if (
                len(data) != item.size_bytes
                or hashlib.sha256(data).hexdigest() != item.sha256
                or dimensions != (item.width, item.height)
            ):
                raise ValueError("Concept selected reference changed")
