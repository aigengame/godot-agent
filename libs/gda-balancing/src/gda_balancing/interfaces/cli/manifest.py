"""The descriptor-derived Standard Schema 2.0 Surface manifest command."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.interfaces.cli.surface import (
    surface_manifest,
    surface_manifest_success_schema,
)


class ManifestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestOutput(RootModel[dict[str, Any]]):
    pass


RegistryProvider = Callable[[], tuple[CommandDescriptor, ...]]


def manifest_descriptor(registry_provider: RegistryProvider) -> CommandDescriptor:
    """Bind the Surface manifest to the composition root's one registry."""

    def run_manifest(_inp: ManifestInput) -> ManifestOutput:
        return ManifestOutput(root=surface_manifest(registry_provider()))

    return CommandDescriptor(
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
