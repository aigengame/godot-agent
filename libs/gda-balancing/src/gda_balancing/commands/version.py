"""The `version` meta command — the first registered command (bADR-0007).

`version` self-describes both authorities as distinct fields, never a single
conflated string (bADR-0009): the toolkit package version and the supported
Standard Schema line (bADR-0001's major.minor line, e.g. ``"1.0"``).
``supported_schema_line`` is ``null`` until #504 lands the first validatable
Standard Schema implementation (adjudicated 2026-07-19 on #502).
"""

from importlib.metadata import version as package_version

from pydantic import BaseModel, ConfigDict

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures


class VersionInput(BaseModel):
    """`version` takes no arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    toolkit_version: str
    supported_schema_line: str | None = None


def run_version(_: VersionInput) -> VersionResult:
    return VersionResult(
        toolkit_version=package_version("gda-balancing"),
        supported_schema_line=None,
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
