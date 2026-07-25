"""Limited, auditable Standard Schema 1.x source conversion."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.envelope import RefusalReport
from gda_balancing.schema.funnel import validate
from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema2.canonical import JsonValue, content_identity
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
)

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_SOURCE_IDENTITY_PREFIX = b"gda-balancing:design-document-source-v1:"

CONVERTER_SPECIFICATION: dict[str, JsonValue] = {
    "artifact_kind": "source-converter-specification",
    "artifact_version": "1.0.0",
    "source_schema_line": "1.0",
    "target_schema_version": "2.0.0",
    "mappings": [
        {
            "source": "parameters.<id>: integral finite scalar",
            "target": "Quantity parameter with an equal singleton Int64 domain",
        }
    ],
    "defaults": [
        {"destination": "manifest.version", "value": "1.0.0"},
        {"destination": "manifest.entry_module", "value": "main"},
        {"destination": "package_requirements", "value": "core.quantity@2.0.0"},
        {"destination": "module.imports", "value": "quantity=core.quantity@2.0.0"},
    ],
    "unsupported": [
        "fractional or out-of-Int64 parameters",
        "attribute tiers and declarations",
        "effects and stacking types",
    ],
}
CONVERTER_IDENTITY = content_identity(
    "source-converter-specification-v1", CONVERTER_SPECIFICATION
)


@dataclass(frozen=True)
class MigrationSuccess:
    input_identity: str
    source: dict[str, JsonValue]
    mappings: tuple[dict[str, JsonValue], ...]
    defaults: tuple[dict[str, JsonValue], ...]
    warnings: tuple[dict[str, JsonValue], ...]


def source_bytes_identity(data: bytes) -> str:
    """Bind the exact input bytes, not only their parsed semantic value."""
    return "sha256:" + hashlib.sha256(_SOURCE_IDENTITY_PREFIX + data).hexdigest()


def migrate_design_source(
    data: bytes, language_bundle: dict[str, Any]
) -> MigrationSuccess | Schema2RefusalReport:
    """Convert the currently admitted semantics-preserving 1.x subset."""
    input_identity = source_bytes_identity(data)
    outcome = validate(data)
    if isinstance(outcome, RefusalReport):
        return _source_refusal(outcome, input_identity, language_bundle)
    assert isinstance(outcome, DesignDocument)
    raw = cast(dict[str, Any], json.loads(data))

    diagnostics: list[Schema2Diagnostic] = []
    symbols: list[dict[str, JsonValue]] = []
    mappings: list[dict[str, JsonValue]] = [
        _mapping("/schema_version", "/schema_version", "schema-major migration"),
        _mapping("/meta/name", "/manifest/id", "preserve authored document name"),
    ]

    if not outcome.meta.name:
        diagnostics.append(
            _diagnostic(
                language_bundle,
                "migration.reason.deprecated-construct",
                input_identity,
                "/meta/name",
                "An empty 1.x document name has no valid 2.x manifest identity",
            )
        )

    for name in sorted(outcome.parameters, key=lambda item: item.encode("utf-8")):
        value = outcome.parameters[name]
        pointer = f"/parameters/{_escape(name)}"
        if not value.is_integer() or not _INT64_MIN <= value <= _INT64_MAX:
            diagnostics.append(
                _diagnostic(
                    language_bundle,
                    "migration.reason.deprecated-construct",
                    input_identity,
                    pointer,
                    "Only an integral signed-Int64 1.x parameter has an exact "
                    "mapping in the current 2.x Quantity package",
                )
            )
            continue
        integer = int(value)
        index = len(symbols)
        symbols.append(_quantity_symbol(f"parameter.{name}", "parameter", integer))
        mappings.append(
            _mapping(
                pointer,
                f"/modules/0/symbols/{index}",
                "integral parameter to equal singleton Quantity domain",
            )
        )

    attributes = raw.get("attributes", {})
    if isinstance(attributes, dict):
        for collection in ("tiers", "items"):
            values = attributes.get(collection, {})
            if not isinstance(values, dict):
                continue
            for name in sorted(values, key=lambda item: item.encode("utf-8")):
                diagnostics.append(
                    _diagnostic(
                        language_bundle,
                        "migration.reason.deprecated-construct",
                        input_identity,
                        f"/attributes/{collection}/{_escape(name)}",
                        "The current 2.x tracer has no semantics-preserving mapping "
                        f"for 1.x attribute {collection}",
                    )
                )
    effects = raw.get("effects", {})
    if isinstance(effects, dict):
        for collection in ("stacking_types", "items"):
            values = effects.get(collection, {})
            if not isinstance(values, dict):
                continue
            for name in sorted(values, key=lambda item: item.encode("utf-8")):
                diagnostics.append(
                    _diagnostic(
                        language_bundle,
                        "migration.reason.deprecated-construct",
                        input_identity,
                        f"/effects/{collection}/{_escape(name)}",
                        "The current 2.x tracer has no semantics-preserving mapping "
                        f"for 1.x effect {collection}",
                    )
                )

    if diagnostics:
        return _bounded_refusal(diagnostics, language_bundle)
    if not symbols:
        return _bounded_refusal(
            [
                _diagnostic(
                    language_bundle,
                    "migration.reason.no-mappable-construct",
                    input_identity,
                    "",
                    "The 1.x source contains no construct that can form a valid "
                    "2.x Model Source Package",
                )
            ],
            language_bundle,
        )

    source: dict[str, JsonValue] = {
        "schema_version": "2.0.0",
        "manifest": {
            "id": outcome.meta.name,
            "version": "1.0.0",
            "entry_module": "main",
        },
        "package_requirements": [{"id": "core.quantity", "version": "2.0.0"}],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.0.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": symbols,
            }
        ],
    }
    defaults = (
        _default("/manifest/version", "1.0.0", "1.x has no package version"),
        _default("/manifest/entry_module", "main", "1.x has one root document"),
        _default(
            "/package_requirements/0",
            "core.quantity@2.0.0",
            "all admitted mappings target the exact Quantity package",
        ),
        _default(
            "/modules/0/imports/0",
            "quantity=core.quantity@2.0.0#Quantity",
            "all admitted symbols use the exact Quantity constructor",
        ),
    )
    warnings: list[dict[str, JsonValue]] = []
    if outcome.meta.description is not None:
        warnings.append(
            {
                "code": "metadata.omitted",
                "source_pointer": "/meta/description",
                "message": "1.x descriptive metadata has no semantic 2.x target",
            }
        )
    if "$schema" in raw:
        warnings.append(
            {
                "code": "schema-reference.replaced",
                "source_pointer": "/$schema",
                "message": "The 1.x editor schema reference is replaced by 2.x authority",
            }
        )
    return MigrationSuccess(
        input_identity=input_identity,
        source=source,
        mappings=tuple(mappings),
        defaults=defaults,
        warnings=tuple(warnings),
    )


def _quantity_symbol(name: str, role: str, value: int) -> dict[str, JsonValue]:
    return {
        "symbol": name,
        "type": "quantity",
        "role": role,
        "representation": "Int",
        "kind": "scalar",
        "unit": "1",
        "domain_kind": "closed-interval",
        "domain": {"minimum": value, "maximum": value},
        "numeric_policy": "exact-int64",
    }


def _mapping(source: str, destination: str, rule: str) -> dict[str, JsonValue]:
    return {
        "source_pointer": source,
        "destination_pointer": destination,
        "mapping": rule,
    }


def _default(destination: str, value: str, reason: str) -> dict[str, JsonValue]:
    return {
        "destination_pointer": destination,
        "value": value,
        "reason": reason,
    }


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _reason(language_bundle: dict[str, Any], reason_id: str) -> tuple[str, str]:
    matches = [
        reason
        for reason in cast(list[dict[str, Any]], language_bundle["language"]["reasons"])
        if reason.get("id") == reason_id
    ]
    if len(matches) != 1:
        raise ValueError(f"exact migration reason unavailable: {reason_id}")
    return cast(str, matches[0]["diagnostic"]), cast(str, matches[0]["stage"])


def _diagnostic(
    language_bundle: dict[str, Any],
    reason_id: str,
    input_identity: str,
    pointer: str,
    message: str,
) -> Schema2Diagnostic:
    code, stage = _reason(language_bundle, reason_id)
    if stage != "migration":
        raise ValueError("migration reason belongs to the wrong refusal stage")
    return Schema2Diagnostic(
        code=code,
        message=message,
        primary=ArtifactLocation(
            content_identity=input_identity,
            pointer=pointer,
        ),
    )


def _source_refusal(
    report: RefusalReport,
    input_identity: str,
    language_bundle: dict[str, Any],
) -> Schema2RefusalReport:
    diagnostics = [
        _diagnostic(
            language_bundle,
            "migration.reason.source-invalid",
            input_identity,
            item.path,
            f"1.x source refusal {item.code}: {item.detail}",
        )
        for item in report.refusals
    ]
    return _bounded_refusal(diagnostics, language_bundle, truncated=report.truncated)


def _bounded_refusal(
    diagnostics: list[Schema2Diagnostic],
    language_bundle: dict[str, Any],
    *,
    truncated: bool = False,
) -> Schema2RefusalReport:
    unique = {
        (item.code, item.primary.pointer, item.primary.content_identity): item
        for item in diagnostics
    }
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            item.primary.pointer,
            item.code,
            item.primary.content_identity,
        ),
    )
    limit = cast(int, language_bundle["resources"]["max_diagnostics"])
    return Schema2RefusalReport(
        stage="migration",
        diagnostics=tuple(ordered[:limit]),
        truncated=truncated or len(ordered) > limit,
    )
