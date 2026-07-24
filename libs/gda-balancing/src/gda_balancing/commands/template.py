"""Standard Schema 2.0 Template release commands."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any, cast

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, RootModel

from gda_balancing.descriptors import (
    ArtifactSetMemberSpec,
    CommandDescriptor,
    ConformanceFixtures,
)
from gda_balancing.schema2.authority import load_authorities
from gda_balancing.schema2.bootstrap import (
    BOOTSTRAP_REFUSAL_CATALOG,
    admit_authorities,
)
from gda_balancing.schema2.canonical import JsonValue, content_identity
from gda_balancing.schema2.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bootstrap_refusal,
)
from gda_balancing.schema2.model import (
    PublicationMember,
    identified_artifact,
    publication_authentication_key,
    publish_artifact_set,
    verify_artifact,
)
from gda_balancing.schema2.surface import descriptor_identity


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


TEMPLATE_REFUSAL_CATALOG = BOOTSTRAP_REFUSAL_CATALOG + (
    ("language.source_contract_mismatch", "static"),
    ("language.package_version_unavailable", "resolution"),
)
TemplateProvider = Callable[[], dict[str, JsonValue]]
_TEMPLATE_KERNEL_IDENTITY = (
    "sha256:f7292a80ae07b695d0caec14432352f24584c3cd405fd79b11661cfac958109a"
)
_TEMPLATE_LDB_IDENTITY = (
    "sha256:97468f52ce6d86bcdb59123b3e745b2da85b47aaf10f8828004f8821b99b9912"
)
_TEMPLATE_PACKAGE_IDENTITY = (
    "sha256:bfbd3e228fde85773b8804e7c632cca4f2771bc896aa4a54ab59efed52c99a58"
)
_TEMPLATE_MEMBER_SCHEMA_IDENTITIES = {
    "boundary-vector": (
        "sha256:fe2760287e98d687b19228a6ed998cb61c0439fbe2b25e51f033ede81ed981ac"
    ),
    "declared-package-dependencies": (
        "sha256:6968a0aeb190221b4ace0b023a0974bce350aa03b6d060e19f0cb4a2a365b2bf"
    ),
    "experiment-specification": (
        "sha256:98272c6c0ee29ea45f3a9f1a3d5ed1e668b5d94d8eb58cabbbc709e03497deda"
    ),
    "genre-coverage-matrix": (
        "sha256:05791006bf7bd006b4a1a4c47b49853f301eea02f2dd754a1a278bbd599df0bd"
    ),
    "golden-scenario": (
        "sha256:be1c523755066def1500c813be49461e8b25a0714fd3ae6c496cab677c8bdbe4"
    ),
    "model-source-package": (
        "sha256:f847b949b31a052f73ac3618c767b62cbc629d13bb16d7ce2b2d68510c5cfd14"
    ),
    "negative-vector": (
        "sha256:d6341070227307e4960e44ab8400a9b639242db417d0576227d5cc6ae0b5290e"
    ),
    "template-compatibility": (
        "sha256:57f17f8e50e8ad2ea93f6a3146ed23b394fb68abcbd18a1418f650771ac177e7"
    ),
    "template-defaults": (
        "sha256:c14c61d257f2bc211e6cdc0c5c0c805cc5fbb28f88756f9fa2fdd94f62b05eea"
    ),
    "template-documentation": (
        "sha256:7ace33c84f9cfe98376cefdced5798bcd7af9e064b827c06a1cfca20be333a43"
    ),
    "template-release": (
        "sha256:44f936f697540095b7587035ad4999366dbae29b140cbef8bd2d77b611428bb2"
    ),
}
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


def _template_refusal(
    code: str,
    stage: str,
    identity: str,
    pointer: str,
    message: str,
) -> Schema2RefusalReport:
    return Schema2RefusalReport(
        stage=cast(Any, stage),
        diagnostics=(
            Schema2Diagnostic(
                code=code,
                message=message,
                primary=ArtifactLocation(
                    content_identity=identity,
                    pointer=pointer,
                ),
            ),
        ),
        truncated=False,
    )


def _member(
    logical_name: str,
    member_kind: str,
    member_schema_identity: str,
    payload: JsonValue,
) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "logical_name": logical_name,
        "member_kind": member_kind,
        "member_schema_identity": member_schema_identity,
        "payload": payload,
    }
    return {
        **body,
        "content_identity": content_identity("template-member-v2", body),
    }


def _member_schema_identities(
    language_bundle: dict[str, JsonValue],
) -> dict[str, str]:
    language = cast(dict[str, JsonValue], language_bundle["language"])
    contracts = {
        cast(str, item["artifact_kind"]): cast(str, item["wire_schema_identity_domain"])
        for item in cast(list[dict[str, JsonValue]], language["artifact_contracts"])
    }
    identities: dict[str, str] = {}
    for collection in ("wire_schemas", "artifact_wire_schemas"):
        for item in cast(list[dict[str, JsonValue]], language[collection]):
            kind = cast(str, item["artifact_kind"])
            schema = cast(dict[str, JsonValue], item["schema"])
            identities[kind] = content_identity(
                contracts.get(kind, f"{kind}-wire-schema-v2"),
                schema,
            )
    return identities


def _template_contract_refusal(
    release: dict[str, JsonValue],
    pointer: str,
    message: str,
) -> Schema2RefusalReport:
    identity = release.get("content_identity", "unidentified")
    return _template_refusal(
        "language.source_contract_mismatch",
        "static",
        identity if isinstance(identity, str) else "unidentified",
        pointer,
        message,
    )


def _validate_template_release(
    release: dict[str, JsonValue],
    kernel: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
) -> Schema2RefusalReport | None:
    """Admit one packaged release against its exact Kernel/LDB authority."""
    schema_identities = _member_schema_identities(language_bundle)
    language = cast(dict[str, JsonValue], language_bundle["language"])
    schemas = {
        cast(str, item["artifact_kind"]): cast(dict[str, JsonValue], item["schema"])
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for item in cast(list[dict[str, JsonValue]], language[collection])
    }
    try:
        jsonschema.validate(release, schemas["template-release"])
        if release["wire_schema_identity"] != schema_identities["template-release"]:
            return _template_contract_refusal(
                release,
                "/wire_schema_identity",
                "Template release does not bind its admitted wire schema",
            )
        release_body = {
            key: value for key, value in release.items() if key != "content_identity"
        }
        if release["content_identity"] != content_identity(
            "template-release-v2", release_body
        ):
            return _template_contract_refusal(
                release,
                "/content_identity",
                "Template release content identity does not authenticate its body",
            )

        members = cast(list[dict[str, JsonValue]], release["members"])
        manifest = cast(list[dict[str, JsonValue]], release["manifest"])
        projected_manifest = [
            {
                key: member[key]
                for key in (
                    "logical_name",
                    "member_kind",
                    "member_schema_identity",
                    "content_identity",
                )
            }
            for member in members
        ]
        if manifest != projected_manifest or len(
            {cast(str, member["logical_name"]) for member in members}
        ) != len(members):
            return _template_contract_refusal(
                release,
                "/manifest",
                "Template manifest is not a unique exact projection of its members",
            )
        for index, member in enumerate(members):
            kind = cast(str, member["member_kind"])
            if member["member_schema_identity"] != schema_identities.get(kind):
                return _template_contract_refusal(
                    release,
                    f"/members/{index}/member_schema_identity",
                    "Template member does not bind its admitted wire schema",
                )
            jsonschema.validate(member["payload"], schemas[kind])
            member_body = {
                key: value for key, value in member.items() if key != "content_identity"
            }
            if member["content_identity"] != content_identity(
                "template-member-v2", member_body
            ):
                return _template_contract_refusal(
                    release,
                    f"/members/{index}/content_identity",
                    "Template member content identity does not authenticate its body",
                )
    except (KeyError, TypeError, ValueError, jsonschema.ValidationError) as err:
        return _template_contract_refusal(
            release,
            "/members",
            f"Template release failed its admitted structural contract: {err}",
        )

    release_identity = cast(str, release["content_identity"])
    if release["kernel_identity"] != kernel["content_identity"]:
        return _template_refusal(
            "language.package_version_unavailable",
            "resolution",
            release_identity,
            "/kernel_identity",
            "Template release is incompatible with the admitted Kernel",
        )
    if release["language_bundle_identity"] != language_bundle["content_identity"]:
        return _template_refusal(
            "language.package_version_unavailable",
            "resolution",
            release_identity,
            "/language_bundle_identity",
            "Template release is incompatible with the admitted LDB",
        )

    members_by_name = {
        cast(str, member["logical_name"]): member
        for member in cast(list[dict[str, JsonValue]], release["members"])
    }
    packages = {
        (
            item["id"],
            item["version"],
            item["content_identity"],
        )
        for item in cast(list[dict[str, JsonValue]], language["packages"])
    }
    dependencies = cast(
        dict[str, JsonValue],
        members_by_name["declared-package-dependencies"]["payload"],
    )
    declared = {
        (
            item["id"],
            item["version"],
            item["content_identity"],
        )
        for item in cast(list[dict[str, JsonValue]], dependencies["packages"])
    }
    if not declared <= packages:
        return _template_refusal(
            "language.package_version_unavailable",
            "resolution",
            release_identity,
            "/members/declared-package-dependencies",
            "Template release declares an unavailable package release",
        )
    compatibility = cast(
        dict[str, JsonValue], members_by_name["compatibility"]["payload"]
    )
    if (
        compatibility["kernel_identity"] != kernel["content_identity"]
        or compatibility["language_bundle_identity"]
        != language_bundle["content_identity"]
    ):
        return _template_refusal(
            "language.package_version_unavailable",
            "resolution",
            release_identity,
            "/members/compatibility",
            "Template compatibility member does not bind the admitted authorities",
        )

    starter = cast(
        dict[str, JsonValue],
        members_by_name["starter-model-source"]["payload"],
    )
    starter_identity = content_identity("model-source-package-v2", starter)
    experiment = cast(
        dict[str, JsonValue],
        members_by_name["experiment-specification"]["payload"],
    )
    if (
        experiment["kernel_identity"] != kernel["content_identity"]
        or experiment["language_bundle_identity"] != language_bundle["content_identity"]
        or experiment["model_source_identity"] != starter_identity
    ):
        return _template_contract_refusal(
            release,
            "/members/experiment-specification",
            "Template Experiment is not bound to its exact authorities and starter",
        )

    coverage = cast(
        dict[str, JsonValue],
        cast(
            list[dict[str, JsonValue]],
            cast(
                dict[str, JsonValue],
                members_by_name["coverage-matrix"]["payload"],
            )["rows"],
        )[0],
    )
    golden = cast(dict[str, JsonValue], members_by_name["golden-scenario"]["payload"])
    negative = cast(dict[str, JsonValue], members_by_name["negative-vector"]["payload"])
    boundary = cast(dict[str, JsonValue], members_by_name["boundary-vector"]["payload"])
    known_operations = {
        cast(str, item["id"])
        for item in cast(list[dict[str, JsonValue]], language["operations"])
    }
    known_diagnostics = {
        cast(str, item["code"])
        for item in cast(list[dict[str, JsonValue]], language_bundle["diagnostics"])
    }
    semantic_links_hold = (
        set(cast(list[str], coverage["operations"])) <= known_operations
        and coverage["experiment"] == experiment["id"]
        and coverage["golden_scenario"] == golden["id"]
        and set(cast(list[str], coverage["vectors"]))
        == {cast(str, negative["id"]), cast(str, boundary["id"])}
        and golden["experiment"] == experiment["id"]
        and golden["model_source_identity"] == starter_identity
        and golden["id"] in cast(list[str], experiment["scenarios"])
        and cast(str, negative["diagnostic"]) in known_diagnostics
    )
    if not semantic_links_hold:
        return _template_contract_refusal(
            release,
            "/members",
            "Template companion evidence is not semantically closed over the exact LDB",
        )
    return None


def _minimal_release() -> dict[str, JsonValue]:
    kernel_identity = _TEMPLATE_KERNEL_IDENTITY
    language_bundle_identity = _TEMPLATE_LDB_IDENTITY
    starter: dict[str, JsonValue] = {
        "schema_version": "2.0.0",
        "manifest": {
            "id": "standard.quantity-minimal.starter",
            "version": "1.0.0",
            "entry_module": "main",
        },
        "package_requirements": [{"id": "core.quantity", "version": "2.0.0"}],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "version": "2.0.0",
                        "symbol": "Quantity",
                    }
                ],
                "symbols": [
                    {
                        "symbol": "value",
                        "type": "quantity",
                        "role": "parameter",
                        "representation": "Int",
                        "kind": "scalar",
                        "unit": "1",
                        "domain_kind": "closed-interval",
                        "domain": {"minimum": 0, "maximum": 100},
                        "numeric_policy": "exact-int64",
                    }
                ],
            }
        ],
    }
    starter_identity = content_identity("model-source-package-v2", starter)
    experiment_id = "standard.quantity-minimal.experiment"
    golden_id = "standard.quantity-minimal.golden"
    negative_id = "standard.quantity-minimal.invalid-domain"
    boundary_id = "standard.quantity-minimal.maximum-boundary"
    schema_identities = _TEMPLATE_MEMBER_SCHEMA_IDENTITIES
    members = [
        _member(
            "starter-model-source",
            "model-source-package",
            schema_identities["model-source-package"],
            starter,
        ),
        _member(
            "experiment-specification",
            "experiment-specification",
            schema_identities["experiment-specification"],
            {
                "schema_version": "2.0.0",
                "id": experiment_id,
                "version": "1.0.0",
                "kernel_identity": kernel_identity,
                "language_bundle_identity": language_bundle_identity,
                "model_source_identity": starter_identity,
                "scenarios": [golden_id],
                "metrics": [
                    {
                        "id": "value",
                        "kind": "scalar",
                        "unit": "1",
                        "target": {"minimum": 0, "maximum": 100},
                    }
                ],
            },
        ),
        _member(
            "declared-package-dependencies",
            "declared-package-dependencies",
            schema_identities["declared-package-dependencies"],
            {
                "schema_version": "2.0.0",
                "packages": [
                    {
                        "id": "core.quantity",
                        "version": "2.0.0",
                        "content_identity": _TEMPLATE_PACKAGE_IDENTITY,
                    }
                ],
            },
        ),
        _member(
            "defaults",
            "template-defaults",
            schema_identities["template-defaults"],
            {
                "schema_version": "2.0.0",
                "symbol_values": [{"symbol": "main.value", "value": 50}],
            },
        ),
        _member(
            "compatibility",
            "template-compatibility",
            schema_identities["template-compatibility"],
            {
                "schema_version": "2.0.0",
                "kernel_identity": kernel_identity,
                "language_bundle_identity": language_bundle_identity,
                "packages": [{"id": "core.quantity", "version": "2.0.0"}],
            },
        ),
        _member(
            "documentation",
            "template-documentation",
            schema_identities["template-documentation"],
            {
                "schema_version": "2.0.0",
                "media_type": "text/markdown",
                "text": "A minimal editable Quantity Model Source Package.",
            },
        ),
        _member(
            "coverage-matrix",
            "genre-coverage-matrix",
            schema_identities["genre-coverage-matrix"],
            {
                "schema_version": "2.0.0",
                "rows": [
                    {
                        "id": "template.quantity.tracer",
                        "requirement": "An editable Quantity source builds through model build.",
                        "operations": ["quantity.identity"],
                        "experiment": experiment_id,
                        "golden_scenario": golden_id,
                        "vectors": [negative_id, boundary_id],
                    }
                ],
            },
        ),
        _member(
            "golden-scenario",
            "golden-scenario",
            schema_identities["golden-scenario"],
            {
                "schema_version": "2.0.0",
                "id": golden_id,
                "experiment": experiment_id,
                "model_source_identity": starter_identity,
                "symbol": "main.value",
                "value": 50,
            },
        ),
        _member(
            "negative-vector",
            "negative-vector",
            schema_identities["negative-vector"],
            {
                "schema_version": "2.0.0",
                "id": negative_id,
                "diagnostic": "language.invalid_domain",
                "mutation": {
                    "pointer": "/modules/0/symbols/0/domain",
                    "value": {"minimum": 1, "maximum": 0},
                },
            },
        ),
        _member(
            "boundary-vector",
            "boundary-vector",
            schema_identities["boundary-vector"],
            {
                "schema_version": "2.0.0",
                "id": boundary_id,
                "pointer": "/modules/0/symbols/0/domain/maximum",
                "value": 100,
                "expected": "accepted",
            },
        ),
    ]
    manifest = [
        {
            key: member[key]
            for key in (
                "logical_name",
                "member_kind",
                "member_schema_identity",
                "content_identity",
            )
        }
        for member in members
    ]
    body: dict[str, JsonValue] = {
        "artifact_kind": "template-release",
        "artifact_version": "2.0.0",
        "wire_schema_identity": schema_identities["template-release"],
        "id": "standard.quantity-minimal",
        "version": "2.0.0",
        "kernel_identity": kernel_identity,
        "language_bundle_identity": language_bundle_identity,
        "manifest": cast(JsonValue, manifest),
        "members": cast(JsonValue, members),
    }
    return {
        **body,
        "content_identity": content_identity("template-release-v2", body),
    }


def template_list_handler(
    provider: TemplateProvider,
) -> Callable[[TemplateListInput], TemplateListResult | Schema2RefusalReport]:
    def _run(
        _inp: TemplateListInput,
    ) -> TemplateListResult | Schema2RefusalReport:
        release = provider()
        kernel, language_bundle = load_authorities()
        admission = admit_authorities(kernel, language_bundle)
        if not admission.admitted:
            return bootstrap_refusal(admission)
        refusal = _validate_template_release(release, kernel, language_bundle)
        if refusal is not None:
            return refusal
        return TemplateListResult(
            templates=[
                TemplateSummary(
                    id=cast(str, release["id"]),
                    version=cast(str, release["version"]),
                    content_identity=cast(str, release["content_identity"]),
                )
            ]
        )

    return _run


run_template_list = template_list_handler(_minimal_release)


def template_get_handler(
    provider: TemplateProvider,
) -> Callable[[TemplateGetInput], TemplateReleaseResult | Schema2RefusalReport]:
    def _run(
        inp: TemplateGetInput,
    ) -> TemplateReleaseResult | Schema2RefusalReport:
        release = provider()
        kernel, language_bundle = load_authorities()
        admission = admit_authorities(kernel, language_bundle)
        if not admission.admitted:
            return bootstrap_refusal(admission)
        refusal = _validate_template_release(release, kernel, language_bundle)
        if refusal is not None:
            return refusal
        if (inp.id, inp.version) != (release["id"], release["version"]):
            return _template_refusal(
                "language.package_version_unavailable",
                "resolution",
                cast(str, release["content_identity"]),
                "/id",
                f"Template release {inp.id}@{inp.version} is unavailable",
            )
        return TemplateReleaseResult(root=cast(dict[str, Any], release))

    return _run


run_template_get = template_get_handler(_minimal_release)


def template_instantiate_handler(
    provider: TemplateProvider,
    *,
    publication_fault: str | None = None,
) -> Callable[
    [TemplateInstantiateInput],
    TemplateInstantiateResult | Schema2RefusalReport,
]:
    """Build the public instantiation handler around an injectable release."""

    def _run(
        inp: TemplateInstantiateInput,
    ) -> TemplateInstantiateResult | Schema2RefusalReport:
        release = provider()
        kernel, language_bundle = load_authorities()
        admission = admit_authorities(kernel, language_bundle)
        if not admission.admitted:
            return bootstrap_refusal(admission)
        refusal = _validate_template_release(release, kernel, language_bundle)
        if refusal is not None:
            return refusal
        if (inp.id, inp.version) != (release["id"], release["version"]):
            return _template_refusal(
                "language.package_version_unavailable",
                "resolution",
                cast(str, release["content_identity"]),
                "/id",
                f"Template release {inp.id}@{inp.version} is unavailable",
            )

        members = {
            cast(str, member["logical_name"]): member
            for member in cast(list[dict[str, JsonValue]], release["members"])
        }
        starter = cast(
            dict[str, JsonValue],
            members["starter-model-source"]["payload"],
        )
        source = cast(dict[str, JsonValue], deepcopy(starter))
        starter_identity = content_identity("model-source-package-v2", starter)
        manifest = cast(dict[str, JsonValue], source["manifest"])
        manifest["id"] = inp.package_id
        manifest["template_provenance"] = {
            "template_id": release["id"],
            "template_version": release["version"],
            "template_identity": release["content_identity"],
            "starter_identity": starter_identity,
        }
        source_identity = content_identity("model-source-package-v2", source)
        schema_identities = _member_schema_identities(language_bundle)
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
                    content_identity("model-source-package-v2", cast(JsonValue, value))
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


run_template_instantiate = template_instantiate_handler(_minimal_release)


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
    refusal_catalog=TEMPLATE_REFUSAL_CATALOG,
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
            "2.0.0",
        )
    ),
    schema_major=2,
    structured_params=True,
    refusal_catalog=TEMPLATE_REFUSAL_CATALOG,
    usage_codes=("argument_conflict", "invalid_argument", "unknown_argument"),
    success_schema=template_get_success_schema,
)


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
            "2.0.0",
            "--package-id",
            "example.instantiated",
        )
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
