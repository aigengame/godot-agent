"""Anchored prototype-local atomic publication with rehash-on-lookup."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from canonical import artifact, canonical_bytes, verify_artifact


class PublicationError(Exception):
    pass


class InvocationConflict(PublicationError):
    pass


class ArtifactStore:
    """Treat ``anchors`` as the prototype's trusted publication index boundary."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.staging = root / "staging"
        self.committed = root / "committed"
        self.anchors = root / "anchors"
        self.staging.mkdir(parents=True, exist_ok=True)
        self.committed.mkdir(parents=True, exist_ok=True)
        self.anchors.mkdir(parents=True, exist_ok=True)

    def lookup(self, invocation_key: str) -> dict[str, Any] | None:
        anchor_path = self.anchors / f"{invocation_key}.json"
        if not anchor_path.exists():
            return None
        destination = self.committed / invocation_key
        try:
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            receipt = json.loads(
                (destination / "receipt.json").read_text(encoding="utf-8")
            )
            record = json.loads(
                (destination / "record.json").read_text(encoding="utf-8")
            )
            for value, code in (
                (anchor, "publication.anchor-invalid"),
                (receipt, "publication.receipt-invalid"),
                (record, "publication.record-invalid"),
            ):
                if not verify_artifact(value):
                    raise PublicationError(code)
            if (
                anchor["publication_receipt"] != receipt["identity"]
                or anchor["publication_record"] != record["identity"]
            ):
                raise PublicationError("publication.anchor-binding-mismatch")
            if record["publication_receipt"] != receipt["identity"]:
                raise PublicationError("publication.record-receipt-mismatch")
            metadata = (
                "descriptor_identity",
                "invocation_key",
                "canonical_input_identity",
                "outcome_name",
                "set_kind",
            )
            for field in metadata:
                if receipt[field] != record[field]:
                    raise PublicationError(f"publication.metadata-mismatch:{field}")
            if record["invocation_key"] != invocation_key:
                raise PublicationError("publication.invocation-key-mismatch")
            members: list[dict[str, Any]] = []
            member_ids: list[str] = []
            for member_id in receipt["members"]:
                filename = member_id.replace(":", "_") + ".json"
                member = json.loads(
                    (destination / "members" / filename).read_text(encoding="utf-8")
                )
                if member.get("identity") != member_id or not verify_artifact(member):
                    raise PublicationError("publication.member-invalid")
                members.append(member)
                member_ids.append(member_id)
            if member_ids != receipt["members"] or record["members"] != member_ids:
                raise PublicationError("publication.member-set-invalid")
            return {
                "descriptor_identity": record["descriptor_identity"],
                "invocation_key": record["invocation_key"],
                "canonical_input_identity": record["canonical_input_identity"],
                "outcome_name": record["outcome_name"],
                "set_kind": record["set_kind"],
                "envelope": record["envelope"],
                "members": members,
                "receipt": receipt,
                "record": record,
                "anchor": anchor,
            }
        except PublicationError:
            raise
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise PublicationError("publication.committed-set-invalid") from error

    def publish(
        self,
        descriptor_identity: str,
        invocation_key: str,
        canonical_input_identity: str,
        outcome_name: str,
        set_kind: str,
        envelope: dict[str, Any],
        members: list[dict[str, Any]],
        *,
        fault: str = "none",
    ) -> dict[str, Any]:
        prior = self.lookup(invocation_key)
        if prior is not None:
            if (
                prior["descriptor_identity"] != descriptor_identity
                or prior["canonical_input_identity"] != canonical_input_identity
            ):
                raise InvocationConflict("invocation.key-conflict")
            return prior
        for member in members:
            if not verify_artifact(member):
                raise PublicationError("publication.member-invalid")
        member_ids = sorted(member["identity"] for member in members)
        if len(member_ids) != len(set(member_ids)):
            raise PublicationError("publication.member-duplicate")
        receipt = artifact(
            "publication-receipt",
            {
                "descriptor_identity": descriptor_identity,
                "invocation_key": invocation_key,
                "canonical_input_identity": canonical_input_identity,
                "outcome_name": outcome_name,
                "set_kind": set_kind,
                "members": member_ids,
                "commit_protocol": "anchored-directory-rename-probe-v2",
            },
        )
        record = artifact(
            "publication-record",
            {
                "descriptor_identity": descriptor_identity,
                "invocation_key": invocation_key,
                "canonical_input_identity": canonical_input_identity,
                "outcome_name": outcome_name,
                "set_kind": set_kind,
                "members": member_ids,
                "envelope": envelope,
                "publication_receipt": receipt["identity"],
            },
        )
        anchor = artifact(
            "publication-anchor",
            {
                "invocation_key": invocation_key,
                "publication_receipt": receipt["identity"],
                "publication_record": record["identity"],
            },
        )
        stage = self.staging / f"{invocation_key}.{uuid.uuid4().hex}"
        destination = self.committed / invocation_key
        anchor_stage = self.staging / f"{invocation_key}.{uuid.uuid4().hex}.anchor"
        try:
            (stage / "members").mkdir(parents=True)
            for member in members:
                filename = member["identity"].replace(":", "_") + ".json"
                (stage / "members" / filename).write_bytes(
                    canonical_bytes(member) + b"\n"
                )
            (stage / "receipt.json").write_bytes(canonical_bytes(receipt) + b"\n")
            (stage / "record.json").write_bytes(canonical_bytes(record) + b"\n")
            anchor_stage.write_bytes(canonical_bytes(anchor) + b"\n")
            if fault == "before_commit":
                raise PublicationError("publication.injected-before-commit")
            os.replace(stage, destination)
            os.replace(anchor_stage, self.anchors / f"{invocation_key}.json")
            published = self.lookup(invocation_key)
            if published is None:
                raise PublicationError("publication.anchor-not-visible")
            return published
        finally:
            if stage.exists():
                shutil.rmtree(stage)
            if anchor_stage.exists():
                anchor_stage.unlink()

    def visible_keys(self) -> list[str]:
        return sorted(path.stem for path in self.anchors.glob("*.json"))
