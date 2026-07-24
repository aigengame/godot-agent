"""Standard Schema 2.0 Template release commands."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
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
from gda_balancing.schema2.canonical import JsonValue, canonical_bytes, content_identity
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
    checked_model_template_facts,
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
    "sha256:14e0beab3a25ae79b51c2fd922d8372143a7ede77284491820b54689c12dab74"
)
_TEMPLATE_LDB_IDENTITY = (
    "sha256:334f0c8a9b1e65193d68f65ec93d36a62bebbf234475b0ecefb4d818619b1e78"
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


class _TemplateAdmissionExhausted(Exception):
    pass


class _TemplateAdmissionBudget:
    def __init__(self, limit: int, charge_rules: list[dict[str, JsonValue]]) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Template admission budget must be a positive integer")
        self._rules = {
            cast(str, row["event"]): cast(str, row["amount"]) for row in charge_rules
        }
        if len(self._rules) != len(charge_rules):
            raise ValueError("Template admission charge events must be unique")
        self._allowed = {"member-role"}
        self._remaining = limit

    def begin(self, charges: list[str]) -> None:
        if (
            not charges
            or "judgment" not in charges
            or not set(charges) <= set(self._rules)
        ):
            raise ValueError("Template primitive declares unknown charge events")
        self._allowed = set(charges)

    def consume(self, event: str, amount: int = 1) -> None:
        if event not in self._allowed or event not in self._rules:
            raise ValueError(
                f"Template primitive did not declare charge event: {event}"
            )
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError("Template admission charge must be a natural number")
        self._remaining -= amount
        if self._remaining < 0:
            raise _TemplateAdmissionExhausted


def _dotted_value(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"undeclared Template admission path: {path}")
        current = current[part]
    return current


def _template_members_by_role(
    release: dict[str, JsonValue],
    profile: dict[str, JsonValue],
    budget: _TemplateAdmissionBudget,
) -> dict[str, list[dict[str, JsonValue]]]:
    role_specs = cast(list[dict[str, JsonValue]], profile["member_roles"])
    by_kind = {cast(str, row["member_kind"]): row for row in role_specs}
    if len(by_kind) != len(role_specs):
        raise ValueError("Template member kinds must map to unique roles")
    result = {cast(str, row["role"]): [] for row in role_specs}
    for member in cast(list[dict[str, JsonValue]], release["members"]):
        budget.consume("member-role")
        spec = by_kind.get(cast(str, member["member_kind"]))
        if spec is None:
            raise ValueError("Template release contains an undeclared member kind")
        result[cast(str, spec["role"])].append(member)
    for spec in role_specs:
        count = len(result[cast(str, spec["role"])])
        cardinality = spec["cardinality"]
        if (cardinality == "exactly-one" and count != 1) or (
            cardinality == "one-or-more" and count < 1
        ):
            raise ValueError(
                f"Template member role violates {cardinality}: {spec['role']}"
            )
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


def _project_template_path(
    values: list[Any],
    path: list[str],
    budget: _TemplateAdmissionBudget,
) -> list[Any]:
    projected = values
    for segment in path:
        next_values: list[Any] = []
        if segment == "*":
            for value in projected:
                if not isinstance(value, list):
                    raise ValueError("Template selector wildcard requires a list")
                budget.consume("selected-value", len(value))
                next_values.extend(value)
        else:
            for value in projected:
                if not isinstance(value, dict) or segment not in value:
                    raise ValueError(
                        f"Template selector cannot resolve member: {segment}"
                    )
                budget.consume("selected-value")
                next_values.append(value[segment])
        projected = next_values
    return projected


def _template_selector_values(
    selector: Any,
    *,
    kernel: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
    release: dict[str, JsonValue],
    roles: dict[str, list[dict[str, JsonValue]]],
    derived: dict[str, JsonValue],
    admitted_roots: set[str],
    budget: _TemplateAdmissionBudget,
) -> list[Any]:
    if (
        not isinstance(selector, dict)
        or set(selector) != {"root", "name", "path"}
        or selector.get("root") not in admitted_roots
        or not isinstance(selector.get("name"), str)
        or not isinstance(selector.get("path"), list)
        or not all(isinstance(part, str) and part for part in selector["path"])
    ):
        raise ValueError("Template selector is outside the Kernel selector contract")
    root = selector["root"]
    name = selector["name"]
    if root == "kernel":
        initial: list[Any] = [kernel]
    elif root == "language-bundle":
        initial = [language_bundle]
    elif root == "release":
        initial = [release]
    elif root == "role":
        if name not in roles:
            raise ValueError(f"Template selector names unknown role: {name}")
        initial = [
            cast(dict[str, JsonValue], member["payload"]) for member in roles[name]
        ]
    else:
        if name not in derived:
            raise ValueError(f"Template selector names unknown derived fact: {name}")
        initial = [derived[name]]
    return _project_template_path(initial, selector["path"], budget)


def _canonical_value_set(values: list[Any]) -> set[bytes]:
    return {canonical_bytes(cast(JsonValue, value)) for value in values}


def _template_scoped_values(
    rows: list[Any],
    scope_path: list[str],
    values_path: list[str],
    budget: _TemplateAdmissionBudget,
) -> dict[bytes, set[bytes]]:
    groups: dict[bytes, set[bytes]] = {}
    for row in rows:
        budget.consume("scoped-row")
        scopes = _project_template_path([row], scope_path, budget)
        values = _project_template_path([row], values_path, budget)
        if len(scopes) != 1 or not values:
            raise ValueError("Template scoped relation has an empty or ambiguous row")
        key = canonical_bytes(cast(JsonValue, scopes[0]))
        groups.setdefault(key, set()).update(_canonical_value_set(values))
    return groups


def _template_relation_holds(
    left: set[bytes],
    right: set[bytes],
    relation: Any,
) -> bool:
    if relation == "equal":
        return left == right
    if relation == "subset":
        return left <= right
    raise ValueError(f"unknown Template set relation: {relation}")


def _template_diagnostic_stage(
    language_bundle: dict[str, JsonValue],
    code: str,
) -> str:
    matches = [
        cast(str, row["stage"])
        for row in cast(list[dict[str, JsonValue]], language_bundle["diagnostics"])
        if row["code"] == code
    ]
    if len(matches) != 1:
        raise ValueError(f"Template judgment diagnostic is not unique: {code}")
    return matches[0]


def _template_judgment_refusal(
    release: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
    code: str,
    judgment_id: str,
    message: str,
) -> Schema2RefusalReport:
    identity = release.get("content_identity", "unidentified")
    return _template_refusal(
        code,
        _template_diagnostic_stage(language_bundle, code),
        identity if isinstance(identity, str) else "unidentified",
        "/members",
        f"Template admission judgment {judgment_id} failed: {message}",
    )


@dataclass
class _TemplateGraphState:
    derived: dict[str, JsonValue]
    source: dict[str, Any] | None = None
    checked_source: CheckedModel | None = None


def _execute_template_derivation(
    kind: str,
    evaluation: dict[str, JsonValue],
    primitive: dict[str, JsonValue],
    arguments: dict[str, JsonValue],
    state: _TemplateGraphState,
    roles: dict[str, list[dict[str, JsonValue]]],
    select: Callable[[Any], list[Any]],
    kernel: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
) -> Schema2RefusalReport | None:
    if kind == "content-identity":
        values = select(arguments[cast(str, evaluation["selector"])])
        result = cast(str, arguments[cast(str, evaluation["result"])])
        identity_domain = cast(str, arguments[cast(str, evaluation["domain"])])
        if (
            len(values) != 1
            or not identity_domain
            or not result
            or result in state.derived
        ):
            raise ValueError("Template content-identity derivation is ambiguous")
        state.derived[result] = content_identity(
            identity_domain, cast(JsonValue, values[0])
        )
        return None
    if kind == "concatenate-selections":
        selectors = cast(
            list[JsonValue],
            arguments[cast(str, evaluation["selectors"])],
        )
        result = cast(str, arguments[cast(str, evaluation["result"])])
        if not selectors or not result or result in state.derived:
            raise ValueError("Template concatenation derivation is ambiguous")
        values: list[Any] = []
        for selector in selectors:
            values.extend(select(selector))
        state.derived[result] = cast(JsonValue, values)
        return None
    role = cast(str, arguments[cast(str, evaluation["role"])])
    if role not in roles or len(roles[role]) != 1:
        raise ValueError("Model Source judgment requires one role member")
    state.source = cast(dict[str, Any], roles[role][0]["payload"])
    checked = check_model_source_value(
        state.source,
        kernel=cast(dict[str, Any], kernel),
        language_bundle=cast(dict[str, Any], language_bundle),
    )
    if isinstance(checked, Schema2RefusalReport):
        return checked
    state.checked_source = checked
    facts = checked_model_template_facts(checked)
    result_members = primitive.get("result_members")
    if not isinstance(result_members, list) or set(facts) != set(
        cast(list[str], result_members)
    ):
        raise ValueError("Model Source result does not match the Kernel Template law")
    bindings = cast(
        list[dict[str, JsonValue]],
        arguments[cast(str, evaluation["bindings"])],
    )
    if not bindings:
        raise ValueError("Model Source fact bindings cannot be empty")
    for binding in bindings:
        source_name = cast(str, binding["source"])
        result_name = cast(str, binding["result"])
        if (
            set(binding) != {"result", "source"}
            or source_name not in facts
            or not result_name
            or result_name in state.derived
        ):
            raise ValueError("Model Source fact binding is not closed")
        state.derived[result_name] = cast(JsonValue, facts[source_name])
    return None


def _execute_template_relation(
    kind: str,
    evaluation: dict[str, JsonValue],
    arguments: dict[str, JsonValue],
    select: Callable[[Any], list[Any]],
    budget: _TemplateAdmissionBudget,
) -> bool:
    if kind == "canonical-unique":
        selected_values = select(arguments[cast(str, evaluation["selector"])])
        return bool(selected_values) and len(selected_values) == len(
            _canonical_value_set(selected_values)
        )
    if kind == "canonical-inventory":
        selected_keys = _canonical_value_set(
            select(arguments[cast(str, evaluation["selector"])])
        )
        inventory = _canonical_value_set(
            select(arguments[cast(str, evaluation["inventory"])])
        )
        return bool(selected_keys) and selected_keys <= inventory
    if kind == "canonical-set-relation":
        return _template_relation_holds(
            _canonical_value_set(select(arguments[cast(str, evaluation["left"])])),
            _canonical_value_set(select(arguments[cast(str, evaluation["right"])])),
            arguments[cast(str, evaluation["relation"])],
        )
    if kind == "canonical-scoped-relation":
        source_groups = _template_scoped_values(
            select(arguments[cast(str, evaluation["source"])]),
            cast(
                list[str],
                arguments[cast(str, evaluation["source_scope_path"])],
            ),
            cast(
                list[str],
                arguments[cast(str, evaluation["source_values_path"])],
            ),
            budget,
        )
        target_groups = _template_scoped_values(
            select(arguments[cast(str, evaluation["target"])]),
            cast(
                list[str],
                arguments[cast(str, evaluation["target_scope_path"])],
            ),
            cast(
                list[str],
                arguments[cast(str, evaluation["target_values_path"])],
            ),
            budget,
        )
        relation = arguments[cast(str, evaluation["relation"])]
        if relation == "equal":
            return source_groups == target_groups
        if relation == "subset":
            return set(source_groups) <= set(target_groups) and all(
                source_groups[key] <= target_groups[key] for key in source_groups
            )
        raise ValueError("unknown Template scoped relation")
    groups: dict[bytes, list[bytes]] = {}
    for row in select(arguments[cast(str, evaluation["selector"])]):
        budget.consume("scoped-row")
        scopes = _project_template_path(
            [row],
            cast(list[str], arguments[cast(str, evaluation["scope_path"])]),
            budget,
        )
        values = _project_template_path(
            [row],
            cast(list[str], arguments[cast(str, evaluation["values_path"])]),
            budget,
        )
        if len(scopes) != 1 or not values:
            raise ValueError("Template scoped uniqueness has an empty or ambiguous row")
        groups.setdefault(canonical_bytes(cast(JsonValue, scopes[0])), []).extend(
            canonical_bytes(cast(JsonValue, value)) for value in values
        )
    return bool(groups) and all(
        len(values) == len(set(values)) for values in groups.values()
    )


def _execute_template_interval(
    kind: str,
    evaluation: dict[str, JsonValue],
    arguments: dict[str, JsonValue],
    select: Callable[[Any], list[Any]],
    budget: _TemplateAdmissionBudget,
) -> bool:
    minimum_member = cast(str, arguments[cast(str, evaluation["minimum_member"])])
    maximum_member = cast(str, arguments[cast(str, evaluation["maximum_member"])])
    if kind == "closed-int64-interval":
        intervals = select(arguments[cast(str, evaluation["selector"])])
        return bool(intervals) and all(
            isinstance(interval, dict)
            and set(interval) == {minimum_member, maximum_member}
            and not isinstance(interval[minimum_member], bool)
            and isinstance(interval[minimum_member], int)
            and not isinstance(interval[maximum_member], bool)
            and isinstance(interval[maximum_member], int)
            and interval[minimum_member] <= interval[maximum_member]
            for interval in intervals
        )
    targets: dict[bytes, Any] = {}
    for row in select(arguments[cast(str, evaluation["target"])]):
        keys = _project_template_path(
            [row],
            cast(list[str], arguments[cast(str, evaluation["target_key_path"])]),
            budget,
        )
        intervals = _project_template_path(
            [row],
            cast(
                list[str],
                arguments[cast(str, evaluation["target_interval_path"])],
            ),
            budget,
        )
        if len(keys) != 1 or len(intervals) != 1:
            raise ValueError("Template interval target is ambiguous")
        key = canonical_bytes(cast(JsonValue, keys[0]))
        if key in targets:
            raise ValueError("Template interval target key is duplicate")
        targets[key] = intervals[0]
    for row in select(arguments[cast(str, evaluation["source"])]):
        keys = _project_template_path(
            [row],
            cast(list[str], arguments[cast(str, evaluation["source_key_path"])]),
            budget,
        )
        values = _project_template_path(
            [row],
            cast(list[str], arguments[cast(str, evaluation["source_value_path"])]),
            budget,
        )
        if len(keys) != 1 or len(values) != 1:
            raise ValueError("Template interval source is ambiguous")
        interval = targets.get(canonical_bytes(cast(JsonValue, keys[0])))
        value = values[0]
        if (
            not isinstance(interval, dict)
            or minimum_member not in interval
            or maximum_member not in interval
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < interval[minimum_member]
            or value > interval[maximum_member]
        ):
            return False
    return True


def _execute_template_vector(
    evaluation: dict[str, JsonValue],
    arguments: dict[str, JsonValue],
    state: _TemplateGraphState,
    roles: dict[str, list[dict[str, JsonValue]]],
    budget: _TemplateAdmissionBudget,
    kernel: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
) -> bool:
    role = cast(str, arguments[cast(str, evaluation["role"])])
    if state.source is None:
        raise ValueError("Template vector execution precedes Model Source admission")
    for member in roles[role]:
        budget.consume("vector-execution")
        vector = cast(dict[str, Any], member["payload"])
        pointer = _project_template_path(
            [vector],
            cast(list[str], arguments[cast(str, evaluation["pointer_path"])]),
            budget,
        )
        values = _project_template_path(
            [vector],
            cast(list[str], arguments[cast(str, evaluation["value_path"])]),
            budget,
        )
        expected_path = cast(
            list[str], arguments[cast(str, evaluation["expected_path"])]
        )
        if expected_path and _project_template_path(
            [vector], expected_path, budget
        ) != [arguments[cast(str, evaluation["expected_value"])]]:
            return False
        if len(pointer) != 1 or len(values) != 1:
            raise ValueError("Template vector mutation is ambiguous")
        mutated = _apply_template_vector(
            state.source, cast(str, pointer[0]), cast(JsonValue, values[0])
        )
        result = (
            check_model_source_value(
                mutated,
                kernel=cast(dict[str, Any], kernel),
                language_bundle=cast(dict[str, Any], language_bundle),
            )
            if mutated is not None
            else None
        )
        outcome = arguments[cast(str, evaluation["outcome"])]
        if outcome == "admitted":
            holds = isinstance(result, CheckedModel)
        elif outcome == "refused":
            expected_diagnostic = _project_template_path(
                [
                    vector,
                ],
                cast(
                    list[str],
                    arguments[cast(str, evaluation["diagnostic_path"])],
                ),
                budget,
            )
            holds = (
                len(expected_diagnostic) == 1
                and isinstance(result, Schema2RefusalReport)
                and len(result.diagnostics) == 1
                and result.diagnostics[0].code == expected_diagnostic[0]
            )
        else:
            raise ValueError("unknown Template vector outcome")
        if not holds:
            return False
    return True


def _validate_template_semantics(
    release: dict[str, JsonValue],
    kernel: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
) -> Schema2RefusalReport | None:
    """Interpret the LDB Template artifact-graph program under Kernel primitives."""
    try:
        profile = _template_admission_profile(language_bundle)
        meta = cast(
            dict[str, JsonValue],
            cast(dict[str, JsonValue], kernel["meta_format"])["template_admission"],
        )
        accounting = cast(dict[str, JsonValue], meta["resource_accounting"])
        primitive_spec = cast(dict[str, JsonValue], meta["primitive_spec"])
        selector_contract = cast(dict[str, JsonValue], meta["selector"])
        if (
            selector_contract
            != {
                "path_semantics": "ordered-flatten",
                "roots": [
                    "kernel",
                    "language-bundle",
                    "release",
                    "role",
                    "derived",
                ],
                "wildcard_segment": "*",
            }
            or accounting
            != {
                "charge_rules": [
                    {"amount": "one-per-member", "event": "member-role"},
                    {"amount": "one-per-judgment", "event": "judgment"},
                    {
                        "amount": "one-per-projected-value",
                        "event": "selected-value",
                    },
                    {"amount": "one-per-input-row", "event": "scoped-row"},
                    {"amount": "one-per-vector", "event": "vector-execution"},
                ],
                "counter_scope": "per-template-release-admission",
                "exhaustion_diagnostic": "language.resource_exhausted",
                "limit_path": "resources.max_template_admission_steps",
            }
            or set(primitive_spec)
            != {
                "argument_types",
                "canonical_equality",
                "closed",
                "evaluation_order",
                "primitives",
                "version",
            }
            or primitive_spec["closed"] is not True
            or primitive_spec["version"] != "template-graph-primitives-v1"
            or primitive_spec["evaluation_order"] != "profile-order-first-failure"
            or primitive_spec["canonical_equality"] != "kernel-canonical-bytes"
            or profile["max_steps_path"] != accounting["limit_path"]
            or profile["resource_diagnostic"] != accounting["exhaustion_diagnostic"]
        ):
            raise ValueError("Template admission resource contract is not exact")
        limit = _dotted_value(language_bundle, cast(str, profile["max_steps_path"]))
        budget = _TemplateAdmissionBudget(
            cast(int, limit),
            cast(list[dict[str, JsonValue]], accounting["charge_rules"]),
        )
        roles = _template_members_by_role(release, profile, budget)
    except _TemplateAdmissionExhausted:
        return _template_judgment_refusal(
            release,
            language_bundle,
            cast(str, profile["resource_diagnostic"]),
            "template.resource-accounting",
            "declared step budget was exhausted",
        )
    except (KeyError, TypeError, ValueError) as err:
        return _template_contract_refusal(
            release,
            "/members",
            f"Template release cannot satisfy its LDB member-role profile: {err}",
        )
    kernel_operations = {
        cast(str, row["id"]): row
        for row in cast(
            list[dict[str, JsonValue]],
            meta["operations"],
        )
    }
    kernel_primitives = {
        cast(str, row["id"]): row
        for row in cast(
            list[dict[str, JsonValue]],
            primitive_spec["primitives"],
        )
    }
    state = _TemplateGraphState(derived={})
    admitted_roots = set(cast(list[str], selector_contract["roots"]))

    def select(selector: Any) -> list[Any]:
        return _template_selector_values(
            selector,
            kernel=kernel,
            language_bundle=language_bundle,
            release=release,
            roles=roles,
            derived=state.derived,
            admitted_roots=admitted_roots,
            budget=budget,
        )

    try:
        for judgment in cast(list[dict[str, JsonValue]], profile["judgments"]):
            judgment_id = cast(str, judgment["id"])
            diagnostic = cast(str, judgment["diagnostic"])
            operation_id = cast(str, judgment["operation"])
            operation = kernel_operations.get(operation_id)
            if operation is None:
                raise ValueError(f"unknown Kernel Template operation: {operation_id}")
            if (
                operation.get("input") != {"fact_kind": "template-graph"}
                or operation.get("result") != {"fact_kind": "template-graph"}
                or operation.get("effects") != []
                or operation.get("refusals") != ["reason-bound-diagnostic"]
                or "max_template_admission_steps"
                not in cast(list[str], operation.get("resources", []))
            ):
                raise ValueError("Kernel Template operation contract is incomplete")
            law = cast(dict[str, JsonValue], operation["law"])
            operator = cast(str, law["operator"])
            primitive_id = cast(str, law["primitive"])
            primitive = kernel_primitives.get(primitive_id)
            if primitive is None:
                raise ValueError(f"unknown Kernel Template primitive: {primitive_id}")
            evaluation = cast(dict[str, JsonValue], primitive["evaluation"])
            kind = cast(str, evaluation["kind"])
            charges = cast(list[str], primitive["charges"])
            budget.begin(charges)
            budget.consume("judgment")
            arguments = cast(dict[str, JsonValue], judgment["arguments"])
            if operator != operation_id or set(arguments) != set(
                cast(list[str], primitive["argument_members"])
            ):
                raise ValueError("LDB Template judgment arguments do not match its law")
            holds = True
            if kind in {
                "content-identity",
                "concatenate-selections",
                "model-source-admission",
            }:
                refusal = _execute_template_derivation(
                    kind,
                    evaluation,
                    primitive,
                    arguments,
                    state,
                    roles,
                    select,
                    kernel,
                    language_bundle,
                )
                if refusal is not None:
                    return refusal
            elif kind in {
                "canonical-unique",
                "canonical-inventory",
                "canonical-set-relation",
                "canonical-scoped-relation",
                "canonical-scoped-unique",
            }:
                holds = _execute_template_relation(
                    kind, evaluation, arguments, select, budget
                )
            elif kind in {
                "closed-int64-interval",
                "closed-int64-interval-join",
            }:
                holds = _execute_template_interval(
                    kind, evaluation, arguments, select, budget
                )
            elif kind == "model-source-vector":
                holds = _execute_template_vector(
                    evaluation,
                    arguments,
                    state,
                    roles,
                    budget,
                    kernel,
                    language_bundle,
                )
            else:
                raise ValueError(
                    f"Template primitive has no Schema-major interpreter: {kind}"
                )

            if not holds:
                return _template_judgment_refusal(
                    release,
                    language_bundle,
                    diagnostic,
                    judgment_id,
                    "declared relation did not hold",
                )
    except _TemplateAdmissionExhausted:
        return _template_judgment_refusal(
            release,
            language_bundle,
            cast(str, profile["resource_diagnostic"]),
            "template.resource-accounting",
            "declared step budget was exhausted",
        )
    except (KeyError, TypeError, ValueError) as err:
        return _template_judgment_refusal(
            release,
            language_bundle,
            cast(str, profile["structural_diagnostic"]),
            "template.program",
            str(err),
        )
    if state.checked_source is None:
        return _template_judgment_refusal(
            release,
            language_bundle,
            cast(str, profile["structural_diagnostic"]),
            "template.admit-source",
            "program did not admit a Model Source",
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

        profile = _template_admission_profile(language_bundle)
        source_kind = next(
            cast(str, row["member_kind"])
            for row in cast(list[dict[str, JsonValue]], profile["member_roles"])
            if row["role"] == "source"
        )
        starter_member = next(
            member
            for member in cast(list[dict[str, JsonValue]], release["members"])
            if member["member_kind"] == source_kind
        )
        starter = cast(
            dict[str, JsonValue],
            starter_member["payload"],
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
