"""One detached exact Resolved Model binding for Experiment admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from gda_balancing.domain.artifacts import verify_artifact
from gda_balancing.domain.authority.context import AdmittedAuthorityContext
from gda_balancing.domain.canonical import (
    JsonValue,
    canonical_bytes,
    parse_canonical_object,
)
from gda_balancing.domain.model._admission import admit_resolved_model
from gda_balancing.domain.publication import find_published_artifacts


EXACT_RESOLVED_MODEL_BINDING_MEMBERS = (
    ("build-receipt", "build-receipt"),
    ("package-lock", "package-lock"),
    ("resolved-model", "resolved-model"),
    ("rir-semantic-payload", "rir-semantic-payload"),
)

_MEMBER_KINDS = dict(EXACT_RESOLVED_MODEL_BINDING_MEMBERS)


class ExactResolvedModelBindingError(ValueError):
    """One required member or relationship failed exact binding admission."""

    def __init__(
        self,
        reason: Literal[
            "member-set-mismatch",
            "member-admission-failed",
            "resolved-model-admission-failed",
            "build-receipt-binding-mismatch",
        ],
        member: str | None,
        message: str,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.member = member
        self.message = message


@dataclass(frozen=True, init=False)
class ExactResolvedModelBinding:
    """Canonical detached bytes for one admitted four-member Model binding."""

    _canonical_members: tuple[tuple[str, bytes], ...]
    resolved_model_identity: str

    def __init__(self) -> None:
        raise TypeError(
            "ExactResolvedModelBinding values come from Model binding admission"
        )

    def artifacts(self) -> dict[str, dict[str, Any]]:
        """Materialize a detached copy for one Experiment admission."""
        return {
            name: parse_canonical_object(data, artifact_name=name)
            for name, data in self._canonical_members
        }


def project_compiled_model_binding(
    artifacts: dict[str, dict[str, JsonValue]],
    authority_context: AdmittedAuthorityContext,
) -> ExactResolvedModelBinding:
    """Project verified compiler output into the exact Experiment Model binding."""
    selected: dict[str, dict[str, Any]] = {}
    for name in _MEMBER_KINDS:
        artifact = artifacts.get(name)
        if artifact is None:
            raise ExactResolvedModelBindingError(
                "member-set-mismatch",
                name,
                f"exact Model binding has no {name} member",
            )
        selected[name] = cast(dict[str, Any], artifact)
    return admit_exact_resolved_model_binding(selected, authority_context)


def resolve_published_model_binding(
    identities: dict[str, str],
    authority_context: AdmittedAuthorityContext,
) -> ExactResolvedModelBinding:
    """Acquire and admit one committed exact Model binding in one traversal."""
    requested_names = set(_MEMBER_KINDS)
    if set(identities) != requested_names:
        missing = sorted(requested_names - set(identities))
        extra = sorted(set(identities) - requested_names)
        member = missing[0] if missing else extra[0]
        raise ExactResolvedModelBindingError(
            "member-set-mismatch",
            member,
            "exact published Model request member set is not closed",
        )
    artifacts = find_published_artifacts(
        tuple(
            (logical_name, artifact_kind, identities[logical_name])
            for logical_name, artifact_kind in EXACT_RESOLVED_MODEL_BINDING_MEMBERS
        ),
        authority_context.language_bundle,
    )
    return admit_exact_resolved_model_binding(artifacts, authority_context)


def admit_exact_resolved_model_binding(
    artifacts: dict[str, dict[str, Any]],
    authority_context: AdmittedAuthorityContext,
) -> ExactResolvedModelBinding:
    """Detach and admit exactly the four artifacts required by Experiment."""
    names = set(artifacts)
    expected_names = set(_MEMBER_KINDS)
    if names != expected_names:
        missing = sorted(expected_names - names)
        extra = sorted(names - expected_names)
        member = missing[0] if missing else extra[0]
        raise ExactResolvedModelBindingError(
            "member-set-mismatch",
            member,
            "exact Model binding member set is not closed",
        )

    detached: dict[str, dict[str, Any]] = {}
    canonical_members: list[tuple[str, bytes]] = []
    for name, expected_kind in _MEMBER_KINDS.items():
        artifact = artifacts[name]
        try:
            data = canonical_bytes(cast(JsonValue, artifact))
            candidate = parse_canonical_object(data, artifact_name=name)
        except (TypeError, ValueError, UnicodeError) as error:
            raise ExactResolvedModelBindingError(
                "member-admission-failed",
                name,
                f"exact Model binding member is not canonical: {name}",
            ) from error
        if candidate.get("artifact_kind") != expected_kind or not verify_artifact(
            candidate, authority_context.language_bundle
        ):
            raise ExactResolvedModelBindingError(
                "member-admission-failed",
                name,
                f"exact Model binding member failed admission: {name}",
            )
        detached[name] = candidate
        canonical_members.append((name, data))

    if not admit_resolved_model(
        {
            "package-lock": detached["package-lock"],
            "resolved-model": detached["resolved-model"],
            "rir-semantic-payload": detached["rir-semantic-payload"],
        },
        authority_context=authority_context,
    ).admitted:
        raise ExactResolvedModelBindingError(
            "resolved-model-admission-failed",
            None,
            "exact Model binding does not contain one admitted Resolved Model",
        )

    build = detached["build-receipt"]
    expected_build_bindings = {
        "kernel_identity": authority_context.kernel["content_identity"],
        "language_bundle_identity": authority_context.language_bundle[
            "content_identity"
        ],
        "package_lock_identity": detached["package-lock"]["content_identity"],
        "resolved_model_identity": detached["resolved-model"]["content_identity"],
        "rir_identity": detached["rir-semantic-payload"]["content_identity"],
    }
    if any(
        build.get(member) != expected
        for member, expected in expected_build_bindings.items()
    ):
        raise ExactResolvedModelBindingError(
            "build-receipt-binding-mismatch",
            "build-receipt",
            "Build receipt does not bind the exact Resolved Model members",
        )

    binding = object.__new__(ExactResolvedModelBinding)
    object.__setattr__(binding, "_canonical_members", tuple(canonical_members))
    object.__setattr__(
        binding,
        "resolved_model_identity",
        cast(str, detached["resolved-model"]["content_identity"]),
    )
    return binding
