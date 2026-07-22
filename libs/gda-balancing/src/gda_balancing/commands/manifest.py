"""The descriptor-derived Standard Schema 2.0 Surface manifest command."""

from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema2.surface import (
    surface_manifest,
    surface_manifest_success_schema,
)


class ManifestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestOutput(RootModel[dict[str, Any]]):
    pass


def run_manifest(_inp: ManifestInput) -> ManifestOutput:
    # Runtime import avoids a second registry and the commands-package import
    # cycle: the live assembled registry is the sole projection source.
    from gda_balancing.commands import REGISTRY

    return ManifestOutput(root=surface_manifest(REGISTRY))


MANIFEST = CommandDescriptor(
    group=None,
    command="manifest",
    description="Emit the delivered Standard Schema 2.0 command surface.",
    input_model=ManifestInput,
    output_model=ManifestOutput,
    handler=run_manifest,
    fixtures=ConformanceFixtures(),
    schema_major=2,
    structured_params=True,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=surface_manifest_success_schema,
)
