"""Descriptor/invocation-indexed atomic publication with rehash-on-read."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from canonical import artifact, canonical_bytes, identity


IDENTITY_PATTERN = re.compile(r"sha256:([a-z0-9][a-z0-9-]*):([0-9a-f]{64})")


class PublicationError(Exception):
    pass


class InvocationConflict(Exception):
    pass


class DeliveryFailure(PublicationError):
    """The commit succeeded, but the result envelope was not delivered."""


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.committed = root / "committed"
        self.staging = root / "staging"
        self.committed.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    def preflight(
        self,
        descriptor_identity: str,
        invocation_key: str,
        canonical_input_identity: str,
    ) -> dict[str, Any] | None:
        destination = self._destination(descriptor_identity, invocation_key)
        if not destination.exists():
            return None
        recorded = self._read_and_verify(
            destination,
            expected_descriptor=descriptor_identity,
            expected_key=invocation_key,
        )
        if recorded["canonical_input_identity"] != canonical_input_identity:
            raise InvocationConflict(invocation_key)
        recorded["_idempotent_replay"] = True
        return recorded

    def publish(
        self,
        descriptor_identity: str,
        invocation_key: str,
        canonical_input_identity: str,
        set_kind: str,
        outcome: dict[str, Any],
        members: list[dict[str, Any]],
        *,
        fault: str = "none",
    ) -> dict[str, Any]:
        recorded = self.preflight(
            descriptor_identity, invocation_key, canonical_input_identity
        )
        if recorded is not None:
            return recorded
        self._verify_identity_string(canonical_input_identity, "command-input")
        member_ids: list[str] = []
        for member in members:
            self._verify_artifact(member)
            member_ids.append(member["identity"])
        if len(member_ids) != len(set(member_ids)):
            raise PublicationError("artifact.member-identity-duplicate")
        member_ids.sort()
        receipt = artifact(
            "publication-receipt",
            {
                "descriptor": descriptor_identity,
                "invocation_key": invocation_key,
                "canonical_input_identity": canonical_input_identity,
                "set_kind": set_kind,
                "outcome": outcome,
                "members": member_ids,
                "commit_protocol": "same-filesystem-directory-rename-v1",
            },
        )
        self._verify_artifact(receipt)
        commit_marker = artifact(
            "publication-commit-marker",
            {
                "descriptor": descriptor_identity,
                "invocation_key": invocation_key,
                "canonical_input_identity": canonical_input_identity,
                "publication_receipt": receipt["identity"],
            },
        )
        self._verify_artifact(commit_marker)
        record = {
            "descriptor": descriptor_identity,
            "invocation_key": invocation_key,
            "canonical_input_identity": canonical_input_identity,
            "set_kind": set_kind,
            "outcome": outcome,
            "members": members,
            "receipt": receipt,
        }
        destination = self._destination(descriptor_identity, invocation_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor_digest = descriptor_identity.rsplit(":", 1)[-1]
        stage = (
            self.staging
            / f"{descriptor_digest}.{invocation_key}.{secrets.token_hex(8)}"
        )
        stage.mkdir()
        try:
            artifacts_directory = stage / "artifacts"
            artifacts_directory.mkdir()
            for member in members:
                safe_identity = member["identity"].replace(":", "_")
                (artifacts_directory / f"{safe_identity}.json").write_bytes(
                    canonical_bytes(member) + b"\n"
                )
            (stage / "commit-marker.json").write_bytes(
                canonical_bytes(commit_marker) + b"\n"
            )
            (stage / "record.json").write_bytes(canonical_bytes(record) + b"\n")
            if fault == "before_commit":
                raise PublicationError("injected-before-commit")
            try:
                os.replace(stage, destination)
            except FileExistsError:
                raced = self.preflight(
                    descriptor_identity, invocation_key, canonical_input_identity
                )
                if raced is None:
                    raise PublicationError("artifact.commit-race") from None
                return raced
            if fault == "after_commit":
                raise DeliveryFailure(invocation_key)
            record["_idempotent_replay"] = False
            return record
        finally:
            if stage.exists():
                self._remove_tree(stage)

    def lookup(
        self, descriptor_identity: str, invocation_key: str
    ) -> dict[str, Any] | None:
        destination = self._destination(descriptor_identity, invocation_key)
        if not destination.exists():
            return None
        return self._read_and_verify(
            destination,
            expected_descriptor=descriptor_identity,
            expected_key=invocation_key,
        )

    def visible_keys(self) -> list[str]:
        visible: list[str] = []
        for descriptor_directory in self.committed.iterdir():
            if descriptor_directory.is_dir():
                for invocation_directory in descriptor_directory.iterdir():
                    if invocation_directory.is_dir():
                        visible.append(
                            f"{descriptor_directory.name}:{invocation_directory.name}"
                        )
        return sorted(visible)

    def _destination(self, descriptor_identity: str, invocation_key: str) -> Path:
        descriptor_match = self._verify_identity_string(
            descriptor_identity, "command-descriptor"
        )
        self._validate_key(invocation_key)
        return self.committed / descriptor_match.group(2) / invocation_key

    def _read_and_verify(
        self,
        directory: Path,
        *,
        expected_descriptor: str,
        expected_key: str,
    ) -> dict[str, Any]:
        try:
            marker = json.loads(
                (directory / "commit-marker.json").read_text(encoding="utf-8")
            )
            self._verify_artifact(marker)
            if marker["descriptor"] != expected_descriptor:
                raise PublicationError("artifact.marker-descriptor-mismatch")
            if marker["invocation_key"] != expected_key:
                raise PublicationError("artifact.marker-key-mismatch")
            record = json.loads((directory / "record.json").read_text(encoding="utf-8"))
            if record["descriptor"] != expected_descriptor:
                raise PublicationError("artifact.descriptor-mismatch")
            if record["invocation_key"] != expected_key:
                raise PublicationError("artifact.invocation-key-mismatch")
            self._verify_identity_string(
                record["canonical_input_identity"], "command-input"
            )
            members = record["members"]
            if not isinstance(members, list):
                raise PublicationError("artifact.member-container-invalid")
            member_ids: list[str] = []
            artifacts_directory = directory / "artifacts"
            for member in members:
                self._verify_artifact(member)
                member_ids.append(member["identity"])
                safe_identity = member["identity"].replace(":", "_")
                stored_member = json.loads(
                    (artifacts_directory / f"{safe_identity}.json").read_text(
                        encoding="utf-8"
                    )
                )
                if stored_member != member:
                    raise PublicationError("artifact.member-bytes-mismatch")
                self._verify_artifact(stored_member)
            if len(member_ids) != len(set(member_ids)):
                raise PublicationError("artifact.member-identity-duplicate")
            receipt = record["receipt"]
            self._verify_artifact(receipt)
            if receipt["descriptor"] != expected_descriptor:
                raise PublicationError("artifact.receipt-descriptor-mismatch")
            if receipt["invocation_key"] != expected_key:
                raise PublicationError("artifact.receipt-key-mismatch")
            if (
                receipt["canonical_input_identity"]
                != record["canonical_input_identity"]
            ):
                raise PublicationError("artifact.receipt-input-mismatch")
            if receipt["members"] != sorted(member_ids):
                raise PublicationError("artifact.receipt-member-set-mismatch")
            if receipt["set_kind"] != record["set_kind"]:
                raise PublicationError("artifact.receipt-set-kind-mismatch")
            if receipt["outcome"] != record["outcome"]:
                raise PublicationError("artifact.receipt-outcome-mismatch")
            if marker["canonical_input_identity"] != record["canonical_input_identity"]:
                raise PublicationError("artifact.marker-input-mismatch")
            if marker["publication_receipt"] != receipt["identity"]:
                raise PublicationError("artifact.marker-receipt-mismatch")
            return record
        except PublicationError:
            raise
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise PublicationError("artifact.committed-record-invalid") from error

    @staticmethod
    def _verify_artifact(value: Any) -> None:
        if not isinstance(value, dict) or not isinstance(value.get("identity"), str):
            raise PublicationError("artifact.identity-missing")
        match = IDENTITY_PATTERN.fullmatch(value["identity"])
        if match is None:
            raise PublicationError("artifact.identity-malformed")
        domain = match.group(1)
        kind_value = value.get("kind")
        if not isinstance(kind_value, str):
            raise PublicationError("artifact.kind-missing")
        domain_overrides: dict[str, str] = {
            "schema-major-kernel-specification": "kernel",
            "language-definition-bundle": "ldb",
        }
        expected_domain = domain_overrides.get(kind_value, kind_value)
        if domain != expected_domain:
            raise PublicationError("artifact.identity-domain-mismatch")
        bare = {key: item for key, item in value.items() if key != "identity"}
        if identity(domain, bare) != value["identity"]:
            raise PublicationError("artifact.identity-mismatch")

    @staticmethod
    def _verify_identity_string(value: str, expected_domain: str) -> re.Match[str]:
        match = IDENTITY_PATTERN.fullmatch(value)
        if match is None or match.group(1) != expected_domain:
            raise PublicationError("artifact.identity-domain-invalid")
        return match

    @staticmethod
    def _validate_key(value: str) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("invocation.key-invalid")

    def _remove_tree(self, directory: Path) -> None:
        artifacts = directory / "artifacts"
        if artifacts.exists():
            for path in artifacts.iterdir():
                path.unlink()
            artifacts.rmdir()
        record = directory / "record.json"
        if record.exists():
            record.unlink()
        marker = directory / "commit-marker.json"
        if marker.exists():
            marker.unlink()
        directory.rmdir()
