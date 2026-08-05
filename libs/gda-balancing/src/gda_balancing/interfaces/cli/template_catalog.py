"""CLI adapters for packaged Template catalog retrieval."""

from collections.abc import Callable
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel

from gda_balancing.application.template_catalog import get_template, list_templates
from gda_balancing.interfaces.cli.descriptors import (
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.domain.template import TemplateProvider, minimal_release
from gda_balancing.domain.authority.context import (
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.domain.diagnostics import Schema2RefusalReport
from gda_balancing.domain.model.resolution import MODEL_REFUSAL_CATALOG


class TemplateListInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TemplateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: str
    content_identity: str


class TemplateListResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    templates: list[TemplateSummary]


class TemplateGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class TemplateReleaseResult(RootModel[dict[str, Any]]):
    pass


def template_list_handler(
    provider: TemplateProvider,
    *,
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> Callable[[TemplateListInput], TemplateListResult | Schema2RefusalReport]:
    """Bind one Template provider to the list presentation contract."""

    def _run(
        _inp: TemplateListInput,
    ) -> TemplateListResult | Schema2RefusalReport:
        result = list_templates(
            provider,
            authority_context_provider=authority_context_provider,
        )
        if isinstance(result, Schema2RefusalReport):
            return result
        return TemplateListResult(
            templates=[
                TemplateSummary(
                    id=release.id,
                    version=release.version,
                    content_identity=release.content_identity,
                )
                for release in result
            ]
        )

    return _run


def template_get_handler(
    provider: TemplateProvider,
    *,
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> Callable[[TemplateGetInput], TemplateReleaseResult | Schema2RefusalReport]:
    """Bind one Template provider to the get presentation contract."""

    def _run(
        inp: TemplateGetInput,
    ) -> TemplateReleaseResult | Schema2RefusalReport:
        result = get_template(
            inp.id,
            inp.version,
            provider,
            authority_context_provider=authority_context_provider,
        )
        if isinstance(result, Schema2RefusalReport):
            return result
        return TemplateReleaseResult(root=result)

    return _run


def template_get_success_schema() -> dict[str, object]:
    """Closed release framing; member payload precision is LDB-owned."""
    identity = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    manifest_entry = {
        "type": "object",
        "properties": {
            "logical_name": {"type": "string", "minLength": 1},
            "member_kind": {"type": "string", "minLength": 1},
            "member_schema_identity": identity,
            "content_identity": identity,
        },
        "required": [
            "logical_name",
            "member_kind",
            "member_schema_identity",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }
    member = {
        "type": "object",
        "properties": {
            **cast(dict[str, object], manifest_entry["properties"]),
            "payload": {},
        },
        "required": [
            "logical_name",
            "member_kind",
            "member_schema_identity",
            "payload",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "artifact_kind": {"const": "template-release"},
            "artifact_version": {"const": "2.0.0"},
            "wire_schema_identity": identity,
            "id": {"type": "string", "minLength": 1},
            "version": {"type": "string", "minLength": 1},
            "kernel_identity": identity,
            "language_bundle_identity": identity,
            "manifest": {
                "type": "array",
                "minItems": 1,
                "items": manifest_entry,
            },
            "members": {
                "type": "array",
                "minItems": 1,
                "items": member,
            },
            "content_identity": identity,
        },
        "required": [
            "artifact_kind",
            "artifact_version",
            "wire_schema_identity",
            "id",
            "version",
            "kernel_identity",
            "language_bundle_identity",
            "manifest",
            "members",
            "content_identity",
        ],
        "unevaluatedProperties": False,
    }


run_template_list = template_list_handler(minimal_release)
run_template_get = template_get_handler(minimal_release)

TEMPLATE_LIST = CommandDescriptor(
    group="template",
    command="list",
    description="List packaged Standard Schema 2.0 Template releases.",
    input_model=TemplateListInput,
    output_model=TemplateListResult,
    handler=run_template_list,
    fixtures=ConformanceFixtures(),
    schema_major=2,
    structured_params=True,
    refusal_catalog=MODEL_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
)

TEMPLATE_GET = CommandDescriptor(
    group="template",
    command="get",
    description="Get one packaged Standard Schema 2.0 Template release.",
    input_model=TemplateGetInput,
    output_model=TemplateReleaseResult,
    handler=run_template_get,
    fixtures=ConformanceFixtures(
        valid_args=(
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.1.0",
        ),
        refusing_args=(
            "--id",
            "missing.template",
            "--version",
            "2.1.0",
        ),
    ),
    schema_major=2,
    structured_params=True,
    refusal_catalog=MODEL_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=template_get_success_schema,
)
