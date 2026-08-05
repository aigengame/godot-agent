"""Standard Schema 2.0 Template release commands."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any, cast

import jsonschema
from pydantic import BaseModel, ConfigDict, Field

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.schema2.authority import (
    AuthorityContextProvider,
    packaged_authority_context,
)
from gda_balancing.schema2.canonical import JsonValue, content_identity
from gda_balancing.schema2.diagnostics import (
    Schema2RefusalReport,
)
from gda_balancing.domain.publication import (
    PublicationMember,
    publication_authentication_key,
    publish_artifact_set,
)
from gda_balancing.domain.template import (
    TemplateProvider,
    load_admitted_template,
    minimal_release,
    _template_contract_refusal,
    _template_model_source_member_kind,
    template_refusal,
)
from gda_balancing.domain.artifacts import (
    identified_artifact,
    verify_artifact,
)
from gda_balancing.schema2.model import (
    MODEL_REFUSAL_CATALOG,
    model_source_identity_domain,
)
from gda_balancing.schema2.surface import descriptor_identity


class TemplateInstantiateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    out: str = Field(min_length=1)
    invocation_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class TemplateArtifactSetMemberLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_name: str
    locator: str


class TemplateInstantiateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_kind: str
    artifact_version: str
    wire_schema_identity: str
    descriptor_identity: str
    invocation_key: str
    manifest_identity: str
    manifest_locator: str
    member_locators: list[TemplateArtifactSetMemberLocator]
    content_identity: str


TEMPLATE_REFUSAL_CATALOG = MODEL_REFUSAL_CATALOG
_TEMPLATE_INSTANTIATE_ARTIFACT_SET = (
    ArtifactSetMemberSpec(
        "model-source-package",
        "model-source-package",
        role="primary",
    ),
    ArtifactSetMemberSpec(
        "template-instantiation-receipt",
        "template-instantiation-receipt",
    ),
)


def template_instantiate_handler(
    provider: TemplateProvider,
    *,
    publication_fault: str | None = None,
    authority_context_provider: AuthorityContextProvider = packaged_authority_context,
) -> Callable[
    [TemplateInstantiateInput],
    TemplateInstantiateResult | Schema2RefusalReport,
]:
    """Build the public instantiation handler around an injectable release."""

    def _run(
        inp: TemplateInstantiateInput,
    ) -> TemplateInstantiateResult | Schema2RefusalReport:
        admitted = load_admitted_template(provider, authority_context_provider)
        if isinstance(admitted, Schema2RefusalReport):
            return admitted
        release = admitted.release
        kernel = admitted.kernel
        language_bundle = admitted.language_bundle
        if (inp.id, inp.version) != (release["id"], release["version"]):
            return template_refusal(
                "language.package_version_unavailable",
                "resolution",
                cast(str, release["content_identity"]),
                "/id",
                f"Template release {inp.id}@{inp.version} is unavailable",
            )

        source_kind = _template_model_source_member_kind(kernel, admitted.profile)
        starter_members = [
            member
            for member in cast(list[dict[str, JsonValue]], release["members"])
            if member["member_kind"] == source_kind
        ]
        if len(starter_members) != 1:
            return _template_contract_refusal(
                release,
                "/members",
                "Template release must contain one LDB-profiled Model Source member",
            )
        starter_member = starter_members[0]
        starter = cast(
            dict[str, JsonValue],
            starter_member["payload"],
        )
        source = cast(dict[str, JsonValue], deepcopy(starter))
        source_identity_domain = model_source_identity_domain(language_bundle)
        starter_identity = content_identity(source_identity_domain, starter)
        manifest = cast(dict[str, JsonValue], source["manifest"])
        manifest["id"] = inp.package_id
        manifest["template_provenance"] = {
            "template_id": release["id"],
            "template_version": release["version"],
            "template_identity": release["content_identity"],
            "starter_identity": starter_identity,
        }
        source_identity = content_identity(source_identity_domain, source)
        schema_identities = admitted.schema_identities
        command_input = identified_artifact(
            language_bundle,
            "template-instantiate-command-input",
            {
                "template_identity": release["content_identity"],
                "package_id": inp.package_id,
                "kernel_identity": kernel["content_identity"],
                "language_bundle_identity": language_bundle["content_identity"],
            },
        )
        instantiation_receipt = identified_artifact(
            language_bundle,
            "template-instantiation-receipt",
            {
                "template_identity": release["content_identity"],
                "starter_identity": starter_identity,
                "model_source_identity": source_identity,
                "package_id": inp.package_id,
                "kernel_identity": kernel["content_identity"],
                "language_bundle_identity": language_bundle["content_identity"],
            },
        )
        language = cast(dict[str, JsonValue], language_bundle["language"])
        source_schema = next(
            cast(dict[str, JsonValue], item["schema"])
            for item in cast(list[dict[str, JsonValue]], language["wire_schemas"])
            if item["artifact_kind"] == "model-source-package"
        )

        def member_is_admitted(name: str, value: dict[str, Any]) -> bool:
            if name == "model-source-package":
                try:
                    jsonschema.validate(value, source_schema)
                except jsonschema.ValidationError:
                    return False
                return (
                    content_identity(source_identity_domain, cast(JsonValue, value))
                    == source_identity
                )
            return verify_artifact(value, language_bundle)

        artifacts = {
            "model-source-package": PublicationMember(
                value=cast(dict[str, Any], source),
                artifact_kind="model-source-package",
                wire_schema_identity=schema_identities["model-source-package"],
                content_identity=source_identity,
            ),
            "template-instantiation-receipt": PublicationMember(
                value=cast(dict[str, Any], instantiation_receipt),
                artifact_kind="template-instantiation-receipt",
                wire_schema_identity=cast(
                    str, instantiation_receipt["wire_schema_identity"]
                ),
                content_identity=cast(str, instantiation_receipt["content_identity"]),
            ),
        }
        authentication_key = publication_authentication_key()
        receipt = publish_artifact_set(
            artifacts,
            inp.out,
            inp.invocation_key,
            descriptor_identity(TEMPLATE_INSTANTIATE),
            cast(str, command_input["content_identity"]),
            language_bundle,
            _TEMPLATE_INSTANTIATE_ARTIFACT_SET,
            member_is_admitted,
            publication_fault,
            authentication_key=authentication_key,
        )
        return TemplateInstantiateResult.model_validate(receipt)

    return _run


run_template_instantiate = template_instantiate_handler(minimal_release)


TEMPLATE_INSTANTIATE = CommandDescriptor(
    group="template",
    command="instantiate",
    description=(
        "Instantiate a packaged Template as a new editable Model Source Package."
    ),
    input_model=TemplateInstantiateInput,
    output_model=TemplateInstantiateResult,
    handler=run_template_instantiate,
    fixtures=ConformanceFixtures(
        valid_args=(
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.1.0",
            "--package-id",
            "example.instantiated",
        ),
        refusing_args=(
            "--id",
            "missing.template",
            "--version",
            "2.1.0",
            "--package-id",
            "example.instantiated",
        ),
    ),
    artifact_set=_TEMPLATE_INSTANTIATE_ARTIFACT_SET,
    schema_major=2,
    structured_params=True,
    refusal_catalog=TEMPLATE_REFUSAL_CATALOG,
    usage_codes=(
        "argument_conflict",
        "invalid_argument",
        "invocation_key_conflict",
        "unknown_argument",
        "unwritable_output",
    ),
)
