"""The `schema` command group — Standard Schema self-description (bADR-0005).

``schema get <artifact>`` emits one of the two published self-description
artifacts verbatim, each generated from a single authority so it can never drift
from the validator (:mod:`gda_balancing.schema.artifacts`):

* ``structural`` — the JSON Schema 2020-12 document whose instances are Design
  documents (generated from the pydantic model);
* ``catalog`` — the semantic rule catalog, an index of the semantic phase's
  rules projected from the one rule registry (bADR-0005).

Each artifact document *is* the bare result — there is no wrapper (bADR-0008's
no-wrapper law) — so the output model is a ``RootModel`` that dumps the raw
object. An unknown artifact value binds into the input model and fails
validation → the usage `invalid_argument` boundary / exit 3, automatically
(bADR-0008).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema.artifacts import generate_catalog, generate_structural_schema


class SchemaGetInput(BaseModel):
    """`schema get` takes exactly the artifact name (``structural``/``catalog``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: Literal["structural", "catalog"]


class SchemaArtifact(RootModel[dict[str, Any]]):
    """A self-description artifact — the bare schema object, no wrapper
    (bADR-0008). The ``RootModel`` root dumps as the raw JSON object."""


def run_schema_get(inp: SchemaGetInput) -> SchemaArtifact:
    """Emit the requested artifact. Never refuses — a self-description artifact
    is always available for a bound (hence valid) artifact name."""
    if inp.artifact == "catalog":
        return SchemaArtifact(root=generate_catalog())
    return SchemaArtifact(root=generate_structural_schema())


SCHEMA_GET = CommandDescriptor(
    group="schema",
    command="get",
    description="Emit a Standard Schema self-description artifact (bADR-0005).",
    input_model=SchemaGetInput,
    output_model=SchemaArtifact,
    handler=run_schema_get,
    positional_field="artifact",
    fixtures=ConformanceFixtures(valid_args=("structural",)),
)
