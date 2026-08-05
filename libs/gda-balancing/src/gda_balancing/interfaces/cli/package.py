"""Standard Schema 2.0 Package Release CLI contracts (bADR-0021/0023)."""

import re
from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationInfo,
    field_validator,
)
from pydantic.json_schema import (
    DEFAULT_REF_TEMPLATE,
    GenerateJsonSchema,
    JsonSchemaMode,
)

from gda_balancing.application.package_get import get_package
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.domain.authority.package_projection import (
    package_coordinate_contracts,
    package_release_success_schema as package_release_success_schema,
    package_vector_set_success_schema as package_vector_set_success_schema,
)
from gda_balancing.interfaces.cli.package_list import (
    package_list_success_schema as package_list_success_schema,
)
from gda_balancing.domain.authority.context import (
    AuthorityContextProvider,
    AuthorityLoadError,
    packaged_authority_context,
)
from gda_balancing.domain.authority.admission import BOOTSTRAP_REFUSAL_CATALOG
from gda_balancing.domain.diagnostics import Schema2RefusalReport


class PackageGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    member: Literal["release", "conformance-vectors"] = "release"

    @field_validator("id", "version")
    @classmethod
    def _validate_kernel_coordinate(cls, value: str, info: ValidationInfo) -> str:
        field_name = info.field_name
        if field_name not in {"id", "version"}:
            raise ValueError("package-coordinate validator reached an unknown field")
        try:
            contract = package_coordinate_contracts()[field_name]
        except AuthorityLoadError:
            return value
        if re.fullmatch(cast(str, contract["pattern"]), value) is None:
            raise ValueError(f"value does not match the Kernel {field_name} contract")
        return value

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            union_format=union_format,
        )
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("PackageGetInput schema has no properties")
        for name, contract in package_coordinate_contracts().items():
            field_schema = properties.get(name)
            if not isinstance(field_schema, dict):
                raise ValueError(f"PackageGetInput schema has no {name} field")
            field_schema["pattern"] = contract["pattern"]
        return schema


class PackageArtifact(RootModel[dict[str, Any]]):
    """One admitted package inventory or exact Package Release."""


def package_get_success_schema() -> dict[str, object]:
    """Project the two authority-owned Package member shapes into CLI output."""
    return {
        "oneOf": [
            package_release_success_schema(),
            package_vector_set_success_schema(),
        ]
    }


def package_get_handler(
    provider: AuthorityContextProvider,
) -> Callable[[PackageGetInput], PackageArtifact | Schema2RefusalReport]:
    def _run(inp: PackageGetInput) -> PackageArtifact | Schema2RefusalReport:
        result = get_package(provider, inp.id, inp.version, inp.member)
        if isinstance(result, Schema2RefusalReport):
            return result
        return PackageArtifact(root=result.root)

    return _run


PACKAGE_GET = CommandDescriptor(
    group="package",
    command="get",
    description="Get one exact member of a Package Release.",
    input_model=PackageGetInput,
    output_model=PackageArtifact,
    handler=package_get_handler(packaged_authority_context),
    fixtures=ConformanceFixtures(
        valid_args=("--id", "core.quantity", "--version", "2.1.0"),
        refusing_args=("--id", "missing.package", "--version", "1.0.0"),
    ),
    schema_major=2,
    structured_params=True,
    refusal_catalog=BOOTSTRAP_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=package_get_success_schema,
)
