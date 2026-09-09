"""Read one caller-supplied public preview result as a comparison baseline."""

from pathlib import Path
import os
import stat

from pydantic import BaseModel, ConfigDict, ValidationError

from gda_assets.application.ports import PortFailure
from gda_assets.domain.preview_result import PreviewResult


_MAX_BASELINE_BYTES = 4 * 1024 * 1024


class _PreviewEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    preview: PreviewResult


def read_preview_baseline(path: Path) -> PreviewResult:
    """Parse a bounded, explicit ``{"preview": ...}`` public result envelope."""
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("preview baseline must be a regular file")
        with path.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("preview baseline must be a regular file")
            payload = stream.read(_MAX_BASELINE_BYTES + 1)
        if len(payload) > _MAX_BASELINE_BYTES:
            raise ValueError("preview baseline exceeds 4 MiB")
        return _PreviewEnvelope.model_validate_json(payload, strict=True).preview
    except ValidationError as exc:
        first = exc.errors(include_input=False, include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"]) or "preview"
        raise PortFailure(
            "invalid_preview_baseline",
            f"Invalid preview baseline at {location}: {first['msg']}",
        ) from exc
    except (OSError, ValueError) as exc:
        raise PortFailure(
            "invalid_preview_baseline", f"Invalid preview baseline: {exc}"
        ) from exc
