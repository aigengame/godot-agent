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
    MODEL_REFUSAL_CATALOG,
    CheckedModel,
    PublicationMember,
    check_model_source_value,
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


TEMPLATE_REFUSAL_CATALOG = MODEL_REFUSAL_CATALOG
TemplateProvider = Callable[[], dict[str, JsonValue]]
_TEMPLATE_KERNEL_IDENTITY = (
    "sha256:dec04c51d45fc39cdcebdb29ba5b5b39e18ce76b4f4779663013017c4db59c5f"
)
_TEMPLATE_LDB_IDENTITY = (
    "sha256:2b7fabc914a0bd53941897221e53cc01c02602b1d38dada51a53c0d00a77f390"
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
        "sha256:90ca0e184ed384a95c1401e8865252a1fc47ada82c75385472dfc1087b5c6c17"
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


def _template_admission_profile(
    language_bundle: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    language = cast(dict[str, JsonValue], language_bundle["language"])
    profiles = cast(list[dict[str, JsonValue]], language["template_admission_profiles"])
    if len(profiles) != 1:
        raise ValueError("exactly one Template admission profile is required")
    return profiles[0]


def _template_members_by_role(
    release: dict[str, JsonValue],
    profile: dict[str, JsonValue],
) -> dict[str, dict[str, JsonValue]]:
    members = {
        cast(str, member["logical_name"]): member
        for member in cast(list[dict[str, JsonValue]], release["members"])
    }
    result: dict[str, dict[str, JsonValue]] = {}
    for row in cast(list[dict[str, JsonValue]], profile["member_roles"]):
        logical_name = cast(str, row["logical_name"])
        member = members.get(logical_name)
        if member is None or member["member_kind"] != row["member_kind"]:
            raise ValueError(f"missing exact Template member role: {row['role']}")
        result[cast(str, row["role"])] = member
    return result


def _apply_template_vector(
    source: dict[str, Any],
    pointer: str,
    value: JsonValue,
) -> dict[str, Any] | None:
    if not pointer.startswith("/") or pointer == "/":
        return None
    parts = [
        part.replace("~1", "/").replace("~0", "~")
        for part in pointer.removeprefix("/").split("/")
    ]
    mutated = deepcopy(source)
    current: Any = mutated
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    final = parts[-1]
    if isinstance(current, dict) and final in current:
        current[final] = value
    elif isinstance(current, list) and final.isdecimal():
        index = int(final)
        if index >= len(current):
            return None
        current[index] = value
    else:
        return None
    return mutated


def _template_source_symbols(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        f"{module['id']}.{symbol['symbol']}": symbol
        for module in cast(list[dict[str, Any]], source["modules"])
        for symbol in cast(list[dict[str, Any]], module["symbols"])
    }


def _validate_template_semantics(
    release: dict[str, JsonValue],
    kernel: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
) -> Schema2RefusalReport | None:
    """Execute the LDB-selected Template judgments defined by the Kernel."""
    try:
        profile = _template_admission_profile(language_bundle)
        roles = _template_members_by_role(release, profile)
    except (KeyError, TypeError, ValueError) as err:
        return _template_contract_refusal(
            release,
            "/members",
            f"Template release cannot satisfy its LDB member-role profile: {err}",
        )
    language = cast(dict[str, JsonValue], language_bundle["language"])
    kernel_operations = {
        cast(str, row["id"]): row
        for row in cast(
            list[dict[str, JsonValue]],
            cast(
                dict[str, JsonValue],
                cast(dict[str, JsonValue], kernel["meta_format"])["template_admission"],
            )["operations"],
        )
    }
    source = cast(dict[str, Any], roles["source"]["payload"])
    source_identity = content_identity(
        cast(str, profile["source_identity_domain"]),
        cast(JsonValue, source),
    )
    checked_source: CheckedModel | None = None

    def refuse(pointer: str, message: str) -> Schema2RefusalReport:
        return _template_contract_refusal(release, pointer, message)

    for judgment in cast(list[dict[str, JsonValue]], profile["judgment_chain"]):
        operation_id = cast(str, judgment["operation"])
        operation = kernel_operations.get(operation_id)
        if operation is None:
            return refuse(
                "/members",
                f"Template admission judgment uses unknown Kernel operation: {operation_id}",
            )
        law = cast(dict[str, JsonValue], operation["law"])
        operator = cast(str, law["operator"])

        if operator == "require-exact-member-roles":
            expected = {
                (row["logical_name"], row["member_kind"])
                for row in cast(list[dict[str, JsonValue]], profile["member_roles"])
            }
            actual = {
                (member["logical_name"], member["member_kind"])
                for member in cast(list[dict[str, JsonValue]], release["members"])
            }
            if actual != expected or len(actual) != len(expected):
                return refuse(
                    "/members",
                    "Template release does not contain the exact LDB member roles",
                )

        elif operator == "admit-starter-model-source":
            checked = check_model_source_value(source)
            if isinstance(checked, Schema2RefusalReport):
                return checked
            if (
                checked.kernel["content_identity"] != kernel["content_identity"]
                or checked.language_bundle["content_identity"]
                != language_bundle["content_identity"]
            ):
                return refuse(
                    "/members/starter-model-source",
                    "Template starter was admitted by different authorities",
                )
            checked_source = checked

        elif operator == "bind-authorities-and-source":
            experiment = cast(dict[str, Any], roles["experiment"]["payload"])
            golden = cast(dict[str, Any], roles["golden"]["payload"])
            metrics = cast(list[dict[str, Any]], experiment["metrics"])
            quantity = cast(dict[str, JsonValue], language["quantity"])
            known_kinds = set(cast(list[str], quantity["kinds"]))
            known_units = {
                cast(str, row["id"])
                for row in cast(
                    list[dict[str, JsonValue]],
                    quantity["units"],
                )
            }
            metric_ids = [cast(str, row["id"]) for row in metrics]
            if (
                experiment["kernel_identity"] != kernel["content_identity"]
                or experiment["language_bundle_identity"]
                != language_bundle["content_identity"]
                or experiment["model_source_identity"] != source_identity
                or golden["experiment"] != experiment["id"]
                or golden["model_source_identity"] != source_identity
                or cast(list[str], experiment["scenarios"]) != [golden["id"]]
                or len(metric_ids) != len(set(metric_ids))
                or any(
                    row["kind"] not in known_kinds
                    or row["unit"] not in known_units
                    or row["target"]["minimum"] > row["target"]["maximum"]
                    for row in metrics
                )
            ):
                return refuse(
                    "/members/experiment-specification",
                    "Template Experiment and Golden Scenario are not closed over the exact authorities and source",
                )

        elif operator == "close-package-dependencies":
            dependencies = cast(dict[str, Any], roles["dependencies"]["payload"])
            compatibility = cast(dict[str, Any], roles["compatibility"]["payload"])
            available = {
                (row["id"], row["version"]): row
                for row in cast(list[dict[str, Any]], language["packages"])
            }
            requirements = {
                (row["id"], row["version"])
                for row in cast(list[dict[str, Any]], source["package_requirements"])
            }
            declared = {
                (row["id"], row["version"]): row
                for row in cast(list[dict[str, Any]], dependencies["packages"])
            }
            compatible = {
                (row["id"], row["version"])
                for row in cast(list[dict[str, Any]], compatibility["packages"])
            }
            expected = set(requirements)
            pending = list(requirements)
            while pending:
                package_key = pending.pop()
                package = available.get(package_key)
                if package is None:
                    return _template_refusal(
                        "language.package_version_unavailable",
                        "resolution",
                        cast(str, release["content_identity"]),
                        "/members/declared-package-dependencies",
                        "Template starter requires an unavailable package release",
                    )
                for dependency_id in cast(
                    list[str], package["dependencies"]["required"]
                ):
                    matches = [key for key in available if key[0] == dependency_id]
                    if len(matches) != 1:
                        return _template_refusal(
                            "language.package_version_unavailable",
                            "resolution",
                            cast(str, release["content_identity"]),
                            "/members/declared-package-dependencies",
                            "Template dependency closure is not exact",
                        )
                    if matches[0] not in expected:
                        expected.add(matches[0])
                        pending.append(matches[0])
            if (
                set(declared) != expected
                or compatible != requirements
                or compatibility["kernel_identity"] != kernel["content_identity"]
                or compatibility["language_bundle_identity"]
                != language_bundle["content_identity"]
                or any(
                    declared[key]["content_identity"]
                    != available[key]["content_identity"]
                    for key in declared
                )
            ):
                return _template_refusal(
                    "language.package_version_unavailable",
                    "resolution",
                    cast(str, release["content_identity"]),
                    "/members/declared-package-dependencies",
                    "Template package declarations are not the exact source dependency closure",
                )

        elif operator == "admit-defaults":
            symbols = _template_source_symbols(source)
            defaults = cast(
                list[dict[str, Any]],
                cast(dict[str, Any], roles["defaults"]["payload"])["symbol_values"],
            )
            golden = cast(dict[str, Any], roles["golden"]["payload"])
            values = {row["symbol"]: row["value"] for row in defaults}
            if (
                len(values) != len(defaults)
                or any(
                    name not in symbols
                    or value < symbols[name]["domain"]["minimum"]
                    or value > symbols[name]["domain"]["maximum"]
                    for name, value in values.items()
                )
                or golden["symbol"] not in symbols
                or golden["value"] != values.get(golden["symbol"])
            ):
                return refuse(
                    "/members/defaults",
                    "Template defaults and Golden Scenario are not admitted source values",
                )

        elif operator == "close-coverage":
            coverage = cast(dict[str, Any], roles["coverage"]["payload"])
            experiment = cast(dict[str, Any], roles["experiment"]["payload"])
            golden = cast(dict[str, Any], roles["golden"]["payload"])
            negative = cast(dict[str, Any], roles["negative-vector"]["payload"])
            boundary = cast(dict[str, Any], roles["boundary-vector"]["payload"])
            known_capabilities = {
                row["id"]
                for row in cast(list[dict[str, Any]], language["capabilities"])
            }
            known_operations = {
                row["id"] for row in cast(list[dict[str, Any]], language["operations"])
            }
            known_packages = {
                row["id"] for row in cast(list[dict[str, Any]], language["packages"])
            }
            known_observables = {
                row["id"] for row in cast(list[dict[str, Any]], experiment["metrics"])
            }
            rows = cast(list[dict[str, Any]], coverage["rows"])
            row_ids = [row["id"] for row in rows]
            vector_ids: set[str] = set()
            observable_ids: set[str] = set()
            for row in rows:
                vector_ids.update(cast(list[str], row["vectors"]))
                observable_ids.update(cast(list[str], row["observables"]))
                repeated = any(
                    len(values) != len(set(values))
                    for values in (
                        cast(list[str], row["capabilities"]),
                        cast(list[str], row["operations"]),
                        cast(list[str], row["packages"]),
                        cast(list[str], row["vectors"]),
                        cast(list[str], row["observables"]),
                    )
                )
                if (
                    repeated
                    or not set(cast(list[str], row["capabilities"]))
                    <= known_capabilities
                    or not set(cast(list[str], row["operations"])) <= known_operations
                    or not set(cast(list[str], row["packages"])) <= known_packages
                    or not set(cast(list[str], row["observables"])) <= known_observables
                    or row["experiment"] != experiment["id"]
                    or row["golden_scenario"] != golden["id"]
                ):
                    return refuse(
                        "/members/coverage-matrix",
                        "Every Template coverage row must resolve through the exact LDB and Experiment",
                    )
            if (
                len(row_ids) != len(set(row_ids))
                or vector_ids != {negative["id"], boundary["id"]}
                or observable_ids != known_observables
            ):
                return refuse(
                    "/members/coverage-matrix",
                    "Template coverage does not close its unique evidence vectors",
                )

        elif operator == "execute-negative-vectors":
            vector = cast(dict[str, Any], roles["negative-vector"]["payload"])
            mutation = cast(dict[str, Any], vector["mutation"])
            mutated = _apply_template_vector(
                source,
                cast(str, mutation["pointer"]),
                cast(JsonValue, mutation["value"]),
            )
            result = check_model_source_value(mutated) if mutated is not None else None
            if (
                not isinstance(result, Schema2RefusalReport)
                or len(result.diagnostics) != 1
                or result.diagnostics[0].code != vector["diagnostic"]
            ):
                return refuse(
                    "/members/negative-vector",
                    "Template negative vector does not produce its declared LDB refusal",
                )

        elif operator == "execute-boundary-vectors":
            vector = cast(dict[str, Any], roles["boundary-vector"]["payload"])
            mutated = _apply_template_vector(
                source,
                cast(str, vector["pointer"]),
                cast(JsonValue, vector["value"]),
            )
            result = check_model_source_value(mutated) if mutated is not None else None
            if vector["expected"] != "accepted" or not isinstance(result, CheckedModel):
                return refuse(
                    "/members/boundary-vector",
                    "Template boundary vector does not produce its declared admitted outcome",
                )
        else:
            return refuse(
                "/members",
                f"Template admission law has no host implementation: {operator}",
            )

    if checked_source is None:
        return refuse(
            "/members/starter-model-source",
            "Template admission profile did not admit its starter source",
        )
    return None


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
    return _validate_template_semantics(release, kernel, language_bundle)


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
                        "capabilities": ["quantity.declare", "quantity.lower"],
                        "operations": ["quantity.identity"],
                        "packages": ["core.quantity"],
                        "experiment": experiment_id,
                        "golden_scenario": golden_id,
                        "vectors": [negative_id, boundary_id],
                        "observables": ["value"],
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
        ),
        refusing_args=(
            "--id",
            "missing.template",
            "--version",
            "2.0.0",
        ),
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
        ),
        refusing_args=(
            "--id",
            "missing.template",
            "--version",
            "2.0.0",
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
