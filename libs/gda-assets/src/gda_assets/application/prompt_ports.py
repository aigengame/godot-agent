"""Local persistence required by prompt-record use cases."""

from pathlib import Path
from typing import Literal, Protocol

from gda_assets.domain.prompt import (
    JsonScalar,
    PromptOutputRequest,
    PromptOptionKey,
    PromptRecord,
)


class PromptFilesPort(Protocol):
    def read_text(self, path: Path) -> str: ...

    def create(
        self,
        record: Path,
        *,
        mode: Literal["plain", "template"],
        authored_text: str | None,
        template: Path | None,
        template_content: str | None,
        style: Path | None,
        style_content: str | None,
        variables: dict[str, str],
        resolved_prompt: str,
        references: tuple[Path, ...],
        producer: str | None,
        requested_options: dict[PromptOptionKey, JsonScalar],
        revised_from: str | None = None,
    ) -> PromptRecord: ...

    def read(self, record: Path) -> PromptRecord: ...

    def add_output(
        self, record: PromptRecord, request: PromptOutputRequest
    ) -> PromptRecord: ...
