"""Limited, auditable Standard Schema 1.x source conversion."""

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from typing import Any, cast

from gda_balancing.envelope import RefusalReport, UnreadableInputError
from gda_balancing.schema.funnel import validate
from gda_balancing.schema.funnel.preflight import MAX_DOCUMENT_BYTES
from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema.model.formula import DirectBase
from gda_balancing.schema2.canonical import JsonValue, canonical_bytes
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bound_diagnostics,
    reason_by_id,
)

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_SOURCE_IDENTITY_PREFIX = b"gda-balancing:design-document-source-v1:"
MAX_SOURCE_OBSERVATION_BYTES = 16 * 1024 * 1024

_CONVERTER_DEFAULTS: tuple[dict[str, JsonValue], ...] = (
    {
        "destination_pointer": "/manifest/version",
        "value": "1.0.0",
        "reason": "1.x has no package version",
    },
    {
        "destination_pointer": "/manifest/entry_module",
        "value": "main",
        "reason": "1.x has one root document",
    },
    {
        "destination_pointer": "/package_requirements/0",
        "value": "core.quantity@2.0.0",
        "reason": "all admitted mappings target the exact Quantity package",
    },
    {
        "destination_pointer": "/modules/0/imports/0",
        "value": "quantity=core.quantity@2.0.0#Quantity",
        "reason": "all admitted symbols use the exact Quantity constructor",
    },
)
_CONVERTER_WARNING_RULES: tuple[dict[str, JsonValue], ...] = (
    {
        "trigger": {
            "source_pointer": "/meta/description",
            "condition": "present",
        },
        "report": {
            "code": "metadata.omitted",
            "source_pointer": "/meta/description",
            "message": "1.x descriptive metadata has no semantic 2.x target",
        },
    },
    {
        "trigger": {
            "source_pointer": "/$schema",
            "condition": "present",
        },
        "report": {
            "code": "schema-reference.replaced",
            "source_pointer": "/$schema",
            "message": "The 1.x editor schema reference is replaced by 2.x authority",
        },
    },
)
_CONVERTER_MAPPING_RULES: tuple[dict[str, JsonValue], ...] = (
    {
        "id": "schema-major-migration",
        "source": "schema_version: admitted 1.0 patch version",
        "target": "schema_version=2.0.0",
        "report_mapping": "schema-major migration",
    },
    {
        "id": "document-name-to-manifest-id",
        "source": "meta.name: non-empty string",
        "target": "manifest.id with the exact authored value",
        "report_mapping": "preserve authored document name",
    },
    {
        "id": "integral-parameter-to-quantity",
        "source": ("parameters.<id>: finite, non-negative-zero integral signed-Int64"),
        "target": "Quantity parameter with an equal singleton Int64 domain",
        "report_mapping": "integral parameter to equal singleton Quantity domain",
    },
    {
        "id": "direct-attribute-to-quantity",
        "source": (
            "attributes.items.<id>: finite, non-negative-zero integral signed-Int64 "
            "direct number with no mutation, bounds, category, or tier facets"
        ),
        "target": "Quantity constant with an equal singleton Int64 domain",
        "report_mapping": (
            "unmodified integral direct attribute to constant singleton Quantity"
        ),
    },
)
_CONVERTER_SPECIFICATION_PAYLOAD: dict[str, JsonValue] = {
    "converter_version": "1.0.0",
    "input_identity_domain": "design-document-source-v1",
    "source_schema_line": "1.0",
    "target_schema_version": "2.0.0",
    "mapping_rules": [dict(item) for item in _CONVERTER_MAPPING_RULES],
    "ordering": (
        "parameters then attributes; identifiers ordered by their UTF-8 bytes; "
        "destination symbol indexes follow that order"
    ),
    "source_admission": (
        "the complete Standard Schema 1.0 boundary funnel must admit the bounded "
        "source observation before any mapping is claimed"
    ),
    "source_observation": {
        "regular_file_only": True,
        "max_bytes": MAX_SOURCE_OBSERVATION_BYTES,
        "parse_prefix_bytes": MAX_DOCUMENT_BYTES + 1,
    },
    "report_contract": {
        "defaults": [dict(item) for item in _CONVERTER_DEFAULTS],
        "warnings": [dict(item) for item in _CONVERTER_WARNING_RULES],
        "refusal_policy": (
            "report every bounded unsupported construct and publish no "
            "Model Source Package"
        ),
        "success_policy": (
            "publish one admitted Model Source Package and its migration report"
        ),
    },
    "target_limits": [
        "language-bundle.resources.max_source_bytes",
        "language-bundle.resources.max_symbols",
    ],
    "unsupported": [
        "fractional, negative-zero, or out-of-Int64 parameters",
        "attribute tiers, formulas, mutation channels, bounds, categories, and tiers",
        "effects and stacking types",
    ],
}


def converter_specification(
    language_bundle: dict[str, Any],
) -> dict[str, JsonValue]:
    """Build the LDB-validated, independently rehashable converter artifact."""
    from gda_balancing.schema2.model import identified_artifact

    return identified_artifact(
        language_bundle,
        "source-converter-specification",
        _CONVERTER_SPECIFICATION_PAYLOAD,
    )


@dataclass(frozen=True)
class MigrationSuccess:
    input_identity: str
    source_schema_version: str
    source: dict[str, JsonValue]
    mappings: tuple[dict[str, JsonValue], ...]
    defaults: tuple[dict[str, JsonValue], ...]
    warnings: tuple[dict[str, JsonValue], ...]


@dataclass(frozen=True)
class MigrationFailure:
    input_identity: str
    source_schema_version: str | None
    mappings: tuple[dict[str, JsonValue], ...]
    defaults: tuple[dict[str, JsonValue], ...]
    warnings: tuple[dict[str, JsonValue], ...]
    deprecated_constructs: tuple[dict[str, JsonValue], ...]
    refusal: Schema2RefusalReport


def load_design_source_observation(path: str) -> tuple[bytes, str]:
    """Read one bounded parse observation while hashing the complete source."""
    digest = hashlib.sha256()
    digest.update(_SOURCE_IDENTITY_PREFIX)
    bounded = bytearray()
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise UnreadableInputError(f"input document is not a regular file: {path}")
        if metadata.st_size > MAX_SOURCE_OBSERVATION_BYTES:
            raise UnreadableInputError(
                "input document exceeds the "
                f"{MAX_SOURCE_OBSERVATION_BYTES}-byte observation cap: {path}"
            )
        observed = 0
        while observed <= MAX_SOURCE_OBSERVATION_BYTES:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAX_SOURCE_OBSERVATION_BYTES + 1 - observed),
            )
            if not chunk:
                break
            observed += len(chunk)
            if observed > MAX_SOURCE_OBSERVATION_BYTES:
                raise UnreadableInputError(
                    "input document grew beyond the "
                    f"{MAX_SOURCE_OBSERVATION_BYTES}-byte observation cap: {path}"
                )
            digest.update(chunk)
            remaining = MAX_DOCUMENT_BYTES + 1 - len(bounded)
            if remaining > 0:
                bounded.extend(chunk[:remaining])
    except OSError as err:
        raise UnreadableInputError(f"cannot read input document: {path}") from err
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return bytes(bounded), "sha256:" + digest.hexdigest()


def migrate_design_source(
    data: bytes,
    language_bundle: dict[str, Any],
    *,
    input_identity: str,
) -> MigrationSuccess | MigrationFailure:
    """Convert the currently admitted semantics-preserving 1.x subset."""
    outcome = validate(data)
    if isinstance(outcome, RefusalReport):
        return _migration_failure(
            input_identity,
            None,
            (),
            (),
            (),
            _source_refusal(outcome, input_identity, language_bundle),
        )
    assert isinstance(outcome, DesignDocument)
    raw = cast(dict[str, Any], json.loads(data))

    diagnostics: list[Schema2Diagnostic] = []
    symbols: list[dict[str, JsonValue]] = []
    max_source_bytes = cast(int, language_bundle["resources"]["max_source_bytes"])
    max_symbols = cast(int, language_bundle["resources"]["max_symbols"])
    mappings: list[dict[str, JsonValue]] = [
        _mapping(
            "/schema_version",
            "/schema_version",
            _mapping_report_text("schema-major-migration"),
        ),
    ]
    defaults = tuple(dict(item) for item in _CONVERTER_DEFAULTS)
    warnings: list[dict[str, JsonValue]] = []
    if outcome.meta.description is not None:
        warnings.append(_warning_report("metadata.omitted"))
    if "$schema" in raw:
        warnings.append(_warning_report("schema-reference.replaced"))

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
    else:
        mappings.append(
            _mapping(
                "/meta/name",
                "/manifest/id",
                _mapping_report_text("document-name-to-manifest-id"),
            )
        )

    for name in sorted(outcome.parameters, key=lambda item: item.encode("utf-8")):
        value = outcome.parameters[name]
        pointer = f"/parameters/{_escape(name)}"
        if not _is_exact_int64(value):
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
        if len(symbols) >= max_symbols:
            diagnostics.append(
                _diagnostic(
                    language_bundle,
                    "migration.reason.target-limit-exceeded",
                    input_identity,
                    pointer,
                    "The migrated source would exceed the admitted 2.x symbol limit",
                )
            )
            continue
        index = len(symbols)
        symbols.append(_quantity_symbol(f"parameter.{name}", "parameter", integer))
        mappings.append(
            _mapping(
                pointer,
                f"/modules/0/symbols/{index}",
                _mapping_report_text("integral-parameter-to-quantity"),
            )
        )

    for name in sorted(outcome.attributes.tiers, key=lambda item: item.encode("utf-8")):
        diagnostics.append(
            _diagnostic(
                language_bundle,
                "migration.reason.deprecated-construct",
                input_identity,
                f"/attributes/tiers/{_escape(name)}",
                "A 1.x attribute tier has no semantics-preserving 2.x mapping",
            )
        )
    for name in sorted(outcome.attributes.items, key=lambda item: item.encode("utf-8")):
        attribute = outcome.attributes.items[name]
        pointer = f"/attributes/items/{_escape(name)}"
        direct = (
            attribute.base.direct if isinstance(attribute.base, DirectBase) else None
        )
        if (
            direct is None
            or attribute.domain != "number"
            or attribute.accepts
            or attribute.bounds is not None
            or attribute.category is not None
            or attribute.tier is not None
            or not _is_exact_int64(direct)
        ):
            diagnostics.append(
                _diagnostic(
                    language_bundle,
                    "migration.reason.deprecated-construct",
                    input_identity,
                    pointer,
                    "Only an unmodified integral direct number attribute has an "
                    "exact mapping in the current 2.x Quantity package",
                )
            )
            continue
        if len(symbols) >= max_symbols:
            diagnostics.append(
                _diagnostic(
                    language_bundle,
                    "migration.reason.target-limit-exceeded",
                    input_identity,
                    pointer,
                    "The migrated source would exceed the admitted 2.x symbol limit",
                )
            )
            continue
        index = len(symbols)
        symbols.append(_quantity_symbol(f"attribute.{name}", "constant", int(direct)))
        mappings.append(
            _mapping(
                pointer,
                f"/modules/0/symbols/{index}",
                _mapping_report_text("direct-attribute-to-quantity"),
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
        return _migration_failure(
            input_identity,
            outcome.schema_version,
            tuple(mappings),
            defaults,
            tuple(warnings),
            _bounded_refusal(diagnostics, language_bundle),
        )
    if not symbols:
        return _migration_failure(
            input_identity,
            outcome.schema_version,
            tuple(mappings),
            defaults,
            tuple(warnings),
            _bounded_refusal(
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
            ),
        )

    source: dict[str, JsonValue] = {
        "schema_version": "2.0.0",
        "manifest": cast(
            JsonValue,
            {
                "id": outcome.meta.name,
                "version": "1.0.0",
                "entry_module": "main",
            },
        ),
        "package_requirements": cast(
            JsonValue, [{"id": "core.quantity", "version": "2.0.0"}]
        ),
        "modules": cast(
            JsonValue,
            [
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
        ),
        "entrypoints": cast(JsonValue, []),
    }
    if len(canonical_bytes(source)) > max_source_bytes:
        return _migration_failure(
            input_identity,
            outcome.schema_version,
            tuple(mappings),
            defaults,
            tuple(warnings),
            _bounded_refusal(
                [
                    _diagnostic(
                        language_bundle,
                        "migration.reason.target-limit-exceeded",
                        input_identity,
                        "",
                        "The migrated source would exceed the admitted 2.x byte limit",
                    )
                ],
                language_bundle,
            ),
        )
    return MigrationSuccess(
        input_identity=input_identity,
        source_schema_version=outcome.schema_version,
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
        "value_policy": {"mode": "model-fixed", "value": value},
    }


def _mapping(source: str, destination: str, rule: str) -> dict[str, JsonValue]:
    return {
        "source_pointer": source,
        "destination_pointer": destination,
        "mapping": rule,
    }


def _mapping_report_text(rule_id: str) -> str:
    matches = [
        cast(str, rule["report_mapping"])
        for rule in _CONVERTER_MAPPING_RULES
        if rule["id"] == rule_id
    ]
    if len(matches) != 1:
        raise ValueError(f"exact converter mapping rule unavailable: {rule_id}")
    return matches[0]


def _warning_report(code: str) -> dict[str, JsonValue]:
    matches = [
        cast(dict[str, JsonValue], rule["report"])
        for rule in _CONVERTER_WARNING_RULES
        if cast(dict[str, JsonValue], rule["report"]).get("code") == code
    ]
    if len(matches) != 1:
        raise ValueError(f"exact converter warning rule unavailable: {code}")
    return dict(matches[0])


def _is_exact_int64(value: float) -> bool:
    return (
        value.is_integer()
        and _INT64_MIN <= value <= _INT64_MAX
        and not (value == 0.0 and math.copysign(1.0, value) < 0.0)
    )


def _migration_failure(
    input_identity: str,
    source_schema_version: str | None,
    mappings: tuple[dict[str, JsonValue], ...],
    defaults: tuple[dict[str, JsonValue], ...],
    warnings: tuple[dict[str, JsonValue], ...],
    refusal: Schema2RefusalReport,
) -> MigrationFailure:
    deprecated_constructs = tuple(
        cast(
            dict[str, JsonValue],
            {
                "source_pointer": diagnostic.primary.pointer,
                "diagnostic_code": diagnostic.code,
                "remediation": "Re-author or remove this construct before migration",
            },
        )
        for diagnostic in refusal.diagnostics
        if diagnostic.code == "migration.deprecated_construct"
    )
    return MigrationFailure(
        input_identity=input_identity,
        source_schema_version=source_schema_version,
        mappings=mappings,
        defaults=defaults,
        warnings=warnings,
        deprecated_constructs=deprecated_constructs,
        refusal=refusal,
    )


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _reason(language_bundle: dict[str, Any], reason_id: str) -> tuple[str, str]:
    reason = reason_by_id(language_bundle, reason_id)
    return cast(str, reason["diagnostic"]), cast(str, reason["stage"])


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
    normalized_pointer = (
        pointer if pointer.startswith("/") else f"/{pointer}" if pointer else "/"
    )
    return Schema2Diagnostic(
        code=code,
        message=message,
        primary=ArtifactLocation(
            content_identity=input_identity,
            pointer=normalized_pointer,
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
    ordered, bounded = bound_diagnostics(
        diagnostics,
        cast(int, language_bundle["resources"]["max_diagnostics"]),
    )
    return Schema2RefusalReport(
        stage="migration",
        diagnostics=ordered,
        truncated=truncated or bounded,
    )
