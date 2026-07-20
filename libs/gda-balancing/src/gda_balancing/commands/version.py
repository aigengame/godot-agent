"""The `version` meta command — the first registered command (bADR-0007).

`version` self-describes both authorities as distinct fields, never a single
conflated string (bADR-0009): the toolkit package version and the supported
Standard Schema line (bADR-0001's major.minor line, e.g. ``"1.0"``). Now that
#504 lands the first validatable Standard Schema implementation,
``supported_schema_line`` reports the current (newest) line — the newest
registered bundle's line (:func:`~gda_balancing.schema.bundle.current_bundle`) —
never ``null``.
"""

from importlib.metadata import version as package_version

from pydantic import BaseModel, ConfigDict

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema.bundle import current_bundle


class VersionInput(BaseModel):
    """`version` takes no arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionResult(BaseModel):
    """The two never-conflated authorities (bADR-0009). Both are required,
    typed strings: ``supported_schema_line`` is no longer nullable now that #504
    lands the first validatable Standard Schema — optional≠nullable applies to
    the surface's own results too, so it is always present and always a string,
    never ``null`` (PR #527 multi#4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    toolkit_version: str
    supported_schema_line: str


def run_version(_: VersionInput) -> VersionResult:
    return VersionResult(
        toolkit_version=package_version("gda-balancing"),
        supported_schema_line=current_bundle().line,
    )


VERSION = CommandDescriptor(
    group=None,
    command="version",
    description=(
        "Report the toolkit package version and the supported Standard "
        "Schema line as distinct fields."
    ),
    input_model=VersionInput,
    output_model=VersionResult,
    handler=run_version,
    fixtures=ConformanceFixtures(valid_args=()),
)
