"""The Schema 2.0 `version` meta command."""

from importlib.metadata import version as package_version
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from gda_balancing.descriptors import CommandDescriptor, ConformanceFixtures
from gda_balancing.schema2.authority import load_authorities


class VersionInput(BaseModel):
    """`version` takes no arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionResult(BaseModel):
    """The independently versioned toolkit and current forward Schema line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    toolkit_version: str
    supported_schema_line: str


def run_version(_: VersionInput) -> VersionResult:
    _, language_bundle = load_authorities()
    versions = cast(
        list[str],
        cast(dict[str, Any], language_bundle["language"])[
            "model_source_schema_versions"
        ],
    )
    parsed = [tuple(int(part) for part in version.split(".")) for version in versions]
    if not parsed or any(len(version) != 3 for version in parsed):
        raise ValueError("LDB model source version inventory is not semantic versioned")
    newest = max(parsed)
    return VersionResult(
        toolkit_version=package_version("gda-balancing"),
        supported_schema_line=f"{newest[0]}.{newest[1]}",
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
    schema_major=2,
    structured_params=True,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "unknown_argument",
    ),
)
