"""Standard Schema 2.0 authority retrieval (bADR-0012/0021/0022).

``schema get`` exposes the admitted Kernel/LDB pair and the exact wire-schema
and Diagnostic-catalog projections generated from it. The packaged JSON
resources are language authority; this command admits them before emitting
anything and returns a stage-aware refusal if their identity, binding, closed
shape, executable vectors, or resource contract fails.
"""

from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.bootstrap import admit_authorities
from gda_balancing.schema2.canonical import JsonValue
from gda_balancing.schema2.diagnostics import Schema2RefusalReport, bootstrap_refusal
from gda_balancing.schema2.projections import (
    diagnostic_catalog_projection,
    wire_schema_projection,
)


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


AuthorityProvider = Callable[[], tuple[dict[str, Any], dict[str, Any]]]


def schema_get_handler(
    provider: AuthorityProvider,
) -> Callable[[SchemaGetInput], SchemaArtifact | Schema2RefusalReport]:
    """Build the retrieval handler around an injectable authority source.

    Production uses packaged resources; the conformance harness injects
    mutations through the same dispatch/descriptor boundary.
    """

    def _run(inp: SchemaGetInput) -> SchemaArtifact | Schema2RefusalReport:
        kernel, ldb = provider()
        admission = admit_authorities(kernel, ldb)
        if not admission.admitted:
            return bootstrap_refusal(admission)
        authorities: dict[str, JsonValue] = {
            "kernel": cast(JsonValue, kernel),
            "language_bundle": cast(JsonValue, ldb),
            "admission": {
                "admitted": True,
                "kernel_identity": admission.kernel_identity,
                "language_bundle_identity": admission.language_bundle_identity,
            },
        }
        if inp.artifact == "language-bundle":
            return SchemaArtifact(root=cast(dict[str, Any], authorities))
        if inp.artifact == "wire-schema":
            return SchemaArtifact(root=wire_schema_projection(authorities))
        return SchemaArtifact(root=diagnostic_catalog_projection(authorities))

    return _run


run_schema_get = schema_get_handler(load_authorities)


def schema_get_success_schema() -> dict[str, object]:
    """Exact closed success union for the three immutable retrieval results."""
    kernel, ldb = load_authorities()
    admission = admit_authorities(kernel, ldb)
    if not admission.admitted:
        raise RuntimeError("cannot project success schemas from refused authorities")
    authorities: dict[str, JsonValue] = {
        "kernel": cast(JsonValue, kernel),
        "language_bundle": cast(JsonValue, ldb),
        "admission": {
            "admitted": True,
            "kernel_identity": admission.kernel_identity,
            "language_bundle_identity": admission.language_bundle_identity,
        },
    }
    return {
        "oneOf": [
            {"const": authorities},
            {"const": wire_schema_projection(authorities)},
            {"const": diagnostic_catalog_projection(authorities)},
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
    refusal_stages=("ingress", "static"),
    success_schema=schema_get_success_schema,
)
