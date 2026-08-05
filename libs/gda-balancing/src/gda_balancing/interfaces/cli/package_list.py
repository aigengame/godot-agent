"""CLI adapter for listing admitted Package Releases."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel

from gda_balancing.application.package_list import list_packages
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.domain.authority.package_projection import (
    language_bundle_identity_schema,
    package_descriptor_schema,
)
from gda_balancing.domain.authority.context import (
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.domain.authority.admission import BOOTSTRAP_REFUSAL_CATALOG
from gda_balancing.domain.diagnostics import Schema2RefusalReport


class PackageListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PackageListResult(RootModel[dict[str, Any]]):
    """The root-declared package inventory of one admitted LDB."""


def package_list_success_schema() -> dict[str, object]:
    """Project the authority-owned inventory members into the CLI response."""
    return {
        "type": "object",
        "properties": {
            "language_bundle_identity": language_bundle_identity_schema(),
            "packages": {"type": "array", "items": package_descriptor_schema()},
        },
        "required": ["language_bundle_identity", "packages"],
        "unevaluatedProperties": False,
    }


def package_list_handler(
    provider: AuthorityContextProvider,
) -> Callable[[PackageListInput], PackageListResult | Schema2RefusalReport]:
    def _run(_inp: PackageListInput) -> PackageListResult | Schema2RefusalReport:
        result = list_packages(provider)
        if isinstance(result, Schema2RefusalReport):
            return result
        return PackageListResult(root=dict(result))

    return _run


PACKAGE_LIST = CommandDescriptor(
    group="package",
    command="list",
    description="List Package Releases in the admitted Language Definition Bundle.",
    input_model=PackageListInput,
    output_model=PackageListResult,
    handler=package_list_handler(packaged_authority_context),
    fixtures=ConformanceFixtures(),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=package_list_success_schema,
)
