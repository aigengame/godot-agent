from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from canonical import canonical_bytes, content_identity
from refusals import Refusal


class PrototypeStore:
    """A deliberately local, throwaway, content-addressed artifact store."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.index_path = root / "committed-index.json"

    @staticmethod
    def _filename(identity: str) -> str:
        if not identity.startswith("sha256:") or len(identity) != 71:
            raise Refusal(
                "ingress",
                "schema2.artifact.invalid-identity",
                "artifact identity must be sha256:<64 lowercase hex>",
                {"kind": "invocation"},
            )
        digest = identity.removeprefix("sha256:")
        if any(character not in "0123456789abcdef" for character in digest):
            raise Refusal(
                "ingress",
                "schema2.artifact.invalid-identity",
                "artifact identity must be sha256:<64 lowercase hex>",
                {"kind": "invocation"},
            )
        return digest + ".json"

    def _validated_payload(self, artifact: dict[str, Any]) -> tuple[str, bytes]:
        identity = str(artifact.get("identity"))
        expected = content_identity(
            {
                "artifact_kind": artifact.get("artifact_kind"),
                "content": artifact.get("content"),
            }
        )
        if identity != expected:
            raise Refusal(
                "resolution",
                "schema2.artifact.identity-mismatch",
                "artifact content does not match its claimed identity",
                {"kind": "artifact", "artifact_identity": identity, "pointer": ""},
            )
        return identity, canonical_bytes(artifact)

    def _committed_identities(self) -> set[str]:
        if not self.index_path.exists():
            return set()
        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Refusal(
                "ingress",
                "schema2.artifact.invalid-store-index",
                str(exc),
                {"kind": "invocation"},
            ) from exc
        if (
            not isinstance(index, dict)
            or index.get("format") != "schema2-prototype-store-index@1"
            or not isinstance(index.get("identities"), list)
        ):
            raise Refusal(
                "ingress",
                "schema2.artifact.invalid-store-index",
                "prototype store index has an invalid closed shape",
                {"kind": "invocation"},
            )
        return {str(identity) for identity in index["identities"]}

    def publish_batch(self, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Publish one invocation's artifacts behind one atomic visibility index."""

        validated = [self._validated_payload(artifact) for artifact in artifacts]
        identities = [identity for identity, _ in validated]
        if len(set(identities)) != len(identities):
            raise Refusal(
                "resolution",
                "schema2.artifact.duplicate-batch-identity",
                "one publish batch cannot contain duplicate artifact identities",
                {"kind": "invocation"},
            )
        self.root.mkdir(parents=True, exist_ok=True)
        committed = self._committed_identities()
        transaction = Path(
            tempfile.mkdtemp(prefix=".schema2-transaction-", dir=self.root)
        )
        created_destinations: list[Path] = []
        index_temporary = self.index_path.with_suffix(f".tmp-{os.getpid()}")
        try:
            for identity, payload in validated:
                destination = self.root / self._filename(identity)
                if destination.exists() and destination.read_bytes() != payload:
                    raise Refusal(
                        "resolution",
                        "schema2.artifact.store-collision",
                        "existing store entry has different bytes",
                        {
                            "kind": "artifact",
                            "artifact_identity": identity,
                            "pointer": "",
                        },
                    )
                (transaction / self._filename(identity)).write_bytes(payload)

            for identity, _ in validated:
                destination = self.root / self._filename(identity)
                if not destination.exists():
                    os.replace(transaction / self._filename(identity), destination)
                    created_destinations.append(destination)

            if os.environ.get("SCHEMA2_TRACER_STORE_FAULT") == "before-index":
                raise RuntimeError(
                    "prototype deterministic store fault before index commit"
                )

            next_index = {
                "format": "schema2-prototype-store-index@1",
                "identities": sorted(committed | set(identities)),
            }
            index_temporary.write_bytes(canonical_bytes(next_index))
            os.replace(index_temporary, self.index_path)
        except Exception:
            for destination in created_destinations:
                destination.unlink(missing_ok=True)
            index_temporary.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(transaction, ignore_errors=True)

        return [
            {
                "identity": identity,
                "prototype_store_path": str(self.root / self._filename(identity)),
                "size": len(payload),
            }
            for identity, payload in validated
        ]

    def put(self, artifact: dict[str, Any]) -> dict[str, Any]:
        return self.publish_batch([artifact])[0]

    def get(self, identity: str, expected_kind: str) -> dict[str, Any]:
        if identity not in self._committed_identities():
            raise Refusal(
                "ingress",
                "schema2.artifact.uncommitted",
                "artifact is not visible in the committed store index",
                {"kind": "artifact", "artifact_identity": identity, "pointer": ""},
            )
        path = self.root / self._filename(identity)
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Refusal(
                "ingress",
                "schema2.artifact.unreadable",
                str(exc),
                {"kind": "artifact", "artifact_identity": identity, "pointer": ""},
            ) from exc
        if artifact.get("artifact_kind") != expected_kind:
            raise Refusal(
                "ingress",
                "schema2.artifact.kind-mismatch",
                f"expected {expected_kind}",
                {
                    "kind": "artifact",
                    "artifact_identity": identity,
                    "pointer": "/artifact_kind",
                },
            )
        expected = content_identity(
            {
                "artifact_kind": artifact.get("artifact_kind"),
                "content": artifact.get("content"),
            }
        )
        if artifact.get("identity") != identity or expected != identity:
            raise Refusal(
                "ingress",
                "schema2.artifact.identity-mismatch",
                "stored artifact no longer matches its identity",
                {"kind": "artifact", "artifact_identity": identity, "pointer": ""},
            )
        return artifact
