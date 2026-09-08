"""Local file and authoring capabilities required by concept workflows."""

from pathlib import Path
from typing import Protocol

from gda_assets.domain.concept import (
    ConceptAuthoringResult,
    ConceptAuthorRequest,
    ConceptBrief,
    ConceptBriefSnapshot,
    ConceptSelectRequest,
    ConceptSelection,
    ValidatedConceptCandidate,
)


class ConceptFilesPort(Protocol):
    def read_brief(self, path: Path) -> ConceptBrief: ...

    def save_brief(self, record: Path, brief: ConceptBrief) -> ConceptBriefSnapshot: ...

    def load_brief(self, record: Path) -> tuple[ConceptBrief, ConceptBriefSnapshot]: ...

    def create_handoff(
        self,
        request: ConceptSelectRequest,
        brief: ConceptBrief,
        brief_snapshot: ConceptBriefSnapshot,
        candidates: tuple[ValidatedConceptCandidate, ...],
    ) -> ConceptSelection: ...

    def load_handoff(self, path: Path) -> ConceptSelection: ...


class ConceptAuthoringPort(Protocol):
    def author(
        self, request: ConceptAuthorRequest, selection: ConceptSelection
    ) -> ConceptAuthoringResult: ...
