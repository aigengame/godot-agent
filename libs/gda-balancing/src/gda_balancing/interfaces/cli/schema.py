"""Standard Schema 2.0 authority retrieval (bADR-0012/0021/0022).

``schema get`` exposes the admitted Kernel/LDB pair and the exact wire-schema
and Diagnostic-catalog projections generated from it. The packaged JSON
resources are language authority; this command admits them before emitting
anything and returns a stage-aware refusal if their identity, binding, closed
shape, executable vectors, or resource contract fails.
"""

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.application.schema_get import get_schema
from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.interfaces.cli.package import (
    package_release_success_schema,
    package_vector_set_success_schema,
)
from gda_balancing.schema2.authority import (
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.schema2.bootstrap import (
    BOOTSTRAP_REFUSAL_CATALOG,
    SCHEMA2_REFUSAL_STAGES,
)
from gda_balancing.schema2.diagnostics import Schema2RefusalReport


class SchemaGetInput(BaseModel):
    """Select one delivered Standard Schema 2.0 authority projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: Literal[
        "language-bundle",
        "wire-schema",
        "diagnostic-catalog",
    ]


class SchemaArtifact(RootModel[dict[str, Any]]):
    """One stdout-only authority/projection result; descriptor schema is exact."""


def schema_get_handler(
    provider: AuthorityContextProvider,
) -> Callable[[SchemaGetInput], SchemaArtifact | Schema2RefusalReport]:
    """Build the retrieval handler around an injectable authority source.

    Production uses packaged resources; the conformance harness injects
    mutations through the same dispatch/descriptor boundary.
    """

    def _run(inp: SchemaGetInput) -> SchemaArtifact | Schema2RefusalReport:
        result = get_schema(provider, inp.artifact)
        if isinstance(result, Schema2RefusalReport):
            return result
        return SchemaArtifact(root=result.root)

    return _run


run_schema_get = schema_get_handler(packaged_authority_context)


def schema_get_refusal_catalog() -> tuple[tuple[str, str], ...]:
    """Return the non-self-hosted Kernel bootstrap refusal vocabulary."""
    return BOOTSTRAP_REFUSAL_CATALOG


def schema_get_success_schema() -> dict[str, object]:
    """Closed result shapes projected from the admitted authority contracts."""
    identity = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    admission = {
        "type": "object",
        "properties": {
            "admitted": {"const": True},
            "kernel_identity": identity,
            "language_bundle_identity": identity,
        },
        "required": [
            "admitted",
            "kernel_identity",
            "language_bundle_identity",
        ],
        "unevaluatedProperties": False,
    }
    authority_result = {
        "type": "object",
        "properties": {
            "kernel": {},
            "language_bundle": {},
            "package_releases": {
                "type": "array",
                "items": package_release_success_schema(),
            },
            "package_conformance_vector_sets": {
                "type": "array",
                "items": package_vector_set_success_schema(),
            },
            "admission": admission,
        },
        "required": [
            "kernel",
            "language_bundle",
            "package_releases",
            "package_conformance_vector_sets",
            "admission",
        ],
        "unevaluatedProperties": False,
    }
    projection_base = {
        "kernel_identity": identity,
        "language_bundle_identity": identity,
        "content_identity": identity,
    }
    wire_projection = {
        "type": "object",
        "properties": {
            "artifact_kind": {"const": "wire-schema-projection"},
            **projection_base,
            "schemas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "artifact_kind": {"type": "string", "minLength": 1},
                        "schema": {},
                    },
                    "required": ["artifact_kind", "schema"],
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": [
            "artifact_kind",
            "kernel_identity",
            "language_bundle_identity",
            "schemas",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }
    diagnostic_projection = {
        "type": "object",
        "properties": {
            "artifact_kind": {"const": "diagnostic-catalog-projection"},
            **projection_base,
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "authority": {"enum": ["kernel", "language-bundle"]},
                        "code": {"type": "string", "minLength": 1},
                        "stage": {"enum": list(SCHEMA2_REFUSAL_STAGES)},
                    },
                    "required": ["authority", "code", "stage"],
                    "unevaluatedProperties": False,
                },
            },
        },
        "required": [
            "artifact_kind",
            "kernel_identity",
            "language_bundle_identity",
            "entries",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }
    return {
        "oneOf": [
            authority_result,
            wire_projection,
            diagnostic_projection,
        ]
    }


SCHEMA_GET = CommandDescriptor(
    group="schema",
    command="get",
    description="Emit a Standard Schema 2.0 language authority or projection.",
    input_model=SchemaGetInput,
    output_model=SchemaArtifact,
    handler=run_schema_get,
    positional_field="artifact",
    artifact_sink=False,
    fixtures=ConformanceFixtures(valid_args=("language-bundle",)),
    schema_major=2,
    structured_params=True,
    refusal_catalog=schema_get_refusal_catalog(),
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=schema_get_success_schema,
)
