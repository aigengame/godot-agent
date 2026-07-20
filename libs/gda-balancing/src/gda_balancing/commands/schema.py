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

from gda_balancing.descriptors import (
    ArtifactReceipt,
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.schema.bundle import current_bundle


class SchemaGetInput(BaseModel):
    """`schema get` takes exactly the artifact name (``structural``/``catalog``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: Literal["structural", "catalog"]


class SchemaArtifact(RootModel[dict[str, Any] | ArtifactReceipt]):
    """A self-description artifact — the bare schema object, no wrapper
    (bADR-0008) — or, when ``--out`` was given, the :class:`ArtifactReceipt` the
    dispatch tail substitutes (bADR-0009). The union is the artifact-sink
    output-model contract; the body arm is the raw JSON object the ``RootModel``
    root dumps directly."""


def run_schema_get(inp: SchemaGetInput) -> SchemaArtifact:
    """Emit the requested artifact for the current (newest) schema line. Never
    refuses — a self-description artifact is always available for a bound (hence
    valid) artifact name. Self-description is line-agnostic, so it reads the
    newest bundle (:func:`~gda_balancing.schema.bundle.current_bundle`)."""
    bundle = current_bundle()
    if inp.artifact == "catalog":
        return SchemaArtifact(root=bundle.catalog())
    return SchemaArtifact(root=bundle.structural_schema())


SCHEMA_GET = CommandDescriptor(
    group="schema",
    command="get",
    description="Emit a Standard Schema self-description artifact (bADR-0005).",
    input_model=SchemaGetInput,
    output_model=SchemaArtifact,
    handler=run_schema_get,
    positional_field="artifact",
    # The self-description artifacts are artifacts too (bADR-0009): `--out`
    # redirects the emitted schema to the sink under the same artifact law.
    artifact_sink=True,
    fixtures=ConformanceFixtures(valid_args=("structural",)),
)
