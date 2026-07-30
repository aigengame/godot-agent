"""Generated, content-addressed projections of the admitted Schema 2.0 authority."""

from typing import cast

from gda_balancing.schema2.authority import packaged_authority_context
from gda_balancing.schema2.canonical import JsonValue, content_identity
from gda_balancing.schema2.wire_schema import wire_schema_identity_domain

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def _identified(domain: str, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {**body, "content_identity": content_identity(domain, cast(JsonValue, body))}


def _closed_authority_schema(
    artifact_kind: str,
    artifact: dict[str, JsonValue],
    identity_domain: str,
) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "$schema": _DRAFT_2020_12,
        "title": f"Exact admitted {artifact_kind}",
        "type": "object",
        "properties": {name: {} for name in artifact},
        "required": list(artifact),
        "const": artifact,
        "unevaluatedProperties": False,
    }
    digest = content_identity(identity_domain, cast(JsonValue, body))
    return {
        "$id": f"urn:gda-balancing:schema2:wire:{digest.removeprefix('sha256:')}",
        **body,
    }


def _identified_ldb_schema(
    artifact_kind: str,
    schema: dict[str, JsonValue],
    identity_domain: str,
) -> dict[str, JsonValue]:
    body = {key: value for key, value in schema.items() if key != "$id"}
    digest = content_identity(identity_domain, cast(JsonValue, body))
    return {
        "$id": f"urn:gda-balancing:schema2:wire:{digest.removeprefix('sha256:')}",
        **body,
    }


def wire_schema_projection(
    authorities: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Project the exact admitted Kernel and LDB into closed wire schemas."""
    if authorities is None:
        context = packaged_authority_context()
        authorities = {
            "kernel": cast(JsonValue, context.kernel),
            "language_bundle": cast(JsonValue, context.language_bundle),
        }
    kernel = cast(dict[str, JsonValue], authorities["kernel"])
    ldb = cast(dict[str, JsonValue], authorities["language_bundle"])
    public_ldb = getattr(ldb, "root", ldb)
    meta_format = cast(dict[str, JsonValue], kernel["meta_format"])
    root_projection = cast(
        dict[str, JsonValue],
        meta_format["authority_wire_schema_projection"],
    )
    root_identity_domains = cast(
        dict[str, JsonValue],
        root_projection["identity_domains"],
    )
    schemas: list[JsonValue] = [
        {
            "artifact_kind": "schema-major-kernel",
            "schema": _closed_authority_schema(
                "schema-major-kernel",
                kernel,
                cast(str, root_identity_domains["schema-major-kernel"]),
            ),
        },
        {
            "artifact_kind": "language-definition-bundle",
            "schema": _closed_authority_schema(
                "language-definition-bundle",
                cast(dict[str, JsonValue], public_ldb),
                cast(str, root_identity_domains["language-definition-bundle"]),
            ),
        },
    ]
    language = cast(dict[str, JsonValue], ldb["language"])
    for collection in ("wire_schemas", "artifact_wire_schemas"):
        for raw in cast(list[JsonValue], language.get(collection, [])):
            item = cast(dict[str, JsonValue], raw)
            artifact_kind = cast(str, item["artifact_kind"])
            schema = cast(dict[str, JsonValue], item["schema"])
            schemas.append(
                {
                    "artifact_kind": artifact_kind,
                    "schema": _identified_ldb_schema(
                        artifact_kind,
                        schema,
                        wire_schema_identity_domain(ldb, artifact_kind),
                    ),
                }
            )
    schemas.sort(
        key=lambda raw: cast(str, cast(dict[str, JsonValue], raw)["artifact_kind"])
    )
    body: dict[str, JsonValue] = {
        "artifact_kind": "wire-schema-projection",
        "kernel_identity": cast(str, kernel["content_identity"]),
        "language_bundle_identity": cast(str, ldb["content_identity"]),
        "schemas": schemas,
    }
    return _identified("wire-schema-projection-v2", body)


def diagnostic_catalog_projection(
    authorities: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Project the exact Kernel/LDB diagnostic inventories in stable order."""
    if authorities is None:
        context = packaged_authority_context()
        authorities = {
            "kernel": cast(JsonValue, context.kernel),
            "language_bundle": cast(JsonValue, context.language_bundle),
        }
    kernel = cast(dict[str, JsonValue], authorities["kernel"])
    ldb = cast(dict[str, JsonValue], authorities["language_bundle"])
    entries: list[dict[str, JsonValue]] = []
    for owner, artifact in (("kernel", kernel), ("language-bundle", ldb)):
        diagnostics = cast(list[JsonValue], artifact["diagnostics"])
        for raw_entry in diagnostics:
            entry = cast(dict[str, JsonValue], raw_entry)
            entries.append(
                {
                    "authority": owner,
                    "code": cast(str, entry["code"]),
                    "stage": cast(str, entry["stage"]),
                }
            )
    entries.sort(key=lambda item: (item["stage"], item["code"], item["authority"]))
    body: dict[str, JsonValue] = {
        "artifact_kind": "diagnostic-catalog-projection",
        "kernel_identity": cast(str, kernel["content_identity"]),
        "language_bundle_identity": cast(str, ldb["content_identity"]),
        "entries": cast(JsonValue, entries),
    }
    return _identified("diagnostic-catalog-projection-v2", body)
