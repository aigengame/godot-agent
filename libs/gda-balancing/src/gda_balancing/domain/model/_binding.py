"""Independent admission and detached ownership of one executable RIR input."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, cast

from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    parse_canonical_object,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport, reason_by_id
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.domain.model._admission import _standalone_rir_is_admitted
from gda_balancing.domain.model._resolution import _model_lowering, _refusal
from gda_balancing.infrastructure.atomic_files import (
    read_regular_bytes_following_symlink,
)


class RirAdmissionError(ValueError):
    """One exact RIR input failed its current Model-owned admission contract."""

    def __init__(self, reason: str, diagnostic: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.diagnostic = diagnostic
        self.message = message


@dataclass(frozen=True, init=False)
class AdmittedRir:
    """Canonical detached RIR bytes with their exact and semantic identities."""

    _canonical_rir: bytes
    content_identity: str
    semantic_identity: str

    def __init__(self) -> None:
        raise TypeError("AdmittedRir values come from Model RIR admission")

    def artifact(self) -> dict[str, Any]:
        """Materialize a detached artifact for one Experiment admission."""
        return parse_canonical_object(self._canonical_rir, artifact_name="RIR")


def _admission_error(
    context: AdmittedAuthorityContext, reason: str, message: str
) -> RirAdmissionError:
    definition = reason_by_id(context.language_bundle, reason)
    return RirAdmissionError(reason, cast(str, definition["diagnostic"]), message)


def admit_rir(
    value: dict[str, Any], *, authority_context: AdmittedAuthorityContext
) -> AdmittedRir:
    """Admit a supplied RIR against current owners, without producing wrappers."""
    try:
        data = canonical_bytes(cast(JsonValue, value))
        candidate = parse_canonical_object(data, artifact_name="RIR")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise _admission_error(
            authority_context,
            "model.reason.source-parse-failure",
            "RIR input is not canonical JSON data",
        ) from error
    if not _standalone_rir_is_admitted(candidate, authority_context):
        reason = cast(
            str, _model_lowering(authority_context.language_bundle)["admission_reason"]
        )
        raise _admission_error(
            authority_context, reason, "RIR input does not match its admitted semantics"
        )
    admitted = object.__new__(AdmittedRir)
    object.__setattr__(admitted, "_canonical_rir", data)
    object.__setattr__(admitted, "content_identity", candidate["content_identity"])
    object.__setattr__(admitted, "semantic_identity", candidate["semantic_identity"])
    return admitted


def read_rir(
    path: str, *, authority_context: AdmittedAuthorityContext
) -> AdmittedRir | Schema2RefusalReport:
    """Read one explicit public RIR file through the existing artifact ingress."""
    try:
        data = read_regular_bytes_following_symlink(Path(path))
    except OSError as error:
        raise UnreadableInputError(f"cannot read input document: {path}") from error
    identity = "sha256:" + hashlib.sha256(data).hexdigest()
    try:
        candidate = parse_canonical_object(data, artifact_name="RIR")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        reason = reason_by_id(
            authority_context.language_bundle, "model.reason.source-parse-failure"
        )
        return _refusal(
            cast(str, reason["diagnostic"]),
            identity,
            "",
            "RIR input is not canonical JSON data",
            authority_context.language_bundle,
        )
    try:
        return admit_rir(candidate, authority_context=authority_context)
    except RirAdmissionError as error:
        return _refusal(
            error.diagnostic,
            identity,
            "",
            error.message,
            authority_context.language_bundle,
        )
