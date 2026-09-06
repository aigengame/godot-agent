"""Template release construction, admission, and semantic validation."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast
import jsonschema

from gda_balancing.domain.artifacts import identified_artifact, verify_artifact
from gda_balancing.domain.publication import PublicationMember
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    AuthorityContextProvider,
    AuthorityLoadError,
    resolve_authority_context,
)
from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.diagnostics import (
    ArtifactLocation,
    Schema2Diagnostic,
    Schema2RefusalReport,
    bootstrap_refusal,
    ingress_refusal,
)
from gda_balancing.domain.model import (
    CheckedModel,
    check_model_source_value,
    checked_model_template_facts,
    model_source_identity_domain,
)
from gda_balancing.domain.template_contract import (
    TEMPLATE_PRIMITIVE_CHARGES,
    TEMPLATE_PRIMITIVE_EVALUATIONS,
    TEMPLATE_RESOURCE_ACCOUNTING,
    TEMPLATE_SELECTOR_CONTRACT,
)
from gda_balancing.domain.wire_schema import (
    wire_schema_for_kind,
    wire_schema_identity,
    wire_schema_identity_for_kind,
)


TemplateProvider = Callable[
    [AdmittedAuthorityContext],
    dict[str, JsonValue],
]


def template_refusal(
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
    *,
    identity_domain: str,
) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = {
        "logical_name": logical_name,
        "member_kind": member_kind,
        "member_schema_identity": member_schema_identity,
        "payload": payload,
    }
    return {
        **body,
        "content_identity": content_identity(identity_domain, body),
    }


def _artifact_identity_domain(
    language_bundle: dict[str, JsonValue],
    artifact_kind: str,
) -> str:
    language = cast(dict[str, JsonValue], language_bundle["language"])
    matches = [
        cast(str, item["identity_domain"])
        for item in cast(list[dict[str, JsonValue]], language["artifact_contracts"])
        if item["artifact_kind"] == artifact_kind
    ]
    if len(matches) != 1 or not matches[0]:
        raise ValueError(f"exact identity domain is unavailable for {artifact_kind}")
    return matches[0]


def _member_schema_identities(
    language_bundle: dict[str, JsonValue],
) -> dict[str, str]:
    language = cast(dict[str, JsonValue], language_bundle["language"])
    definitions = [
        item
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for item in cast(list[dict[str, JsonValue]], language[collection])
    ]
    for item in definitions:
        wire_schema_identity(
            language_bundle,
            cast(str, item["artifact_kind"]),
        )
    standalone_kinds = {
        cast(str, item["artifact_kind"])
        for item in definitions
        if "wire_schema_identity_domain" in item
    }
    artifact_kinds = {
        cast(str, item["artifact_kind"])
        for item in cast(list[dict[str, JsonValue]], language["artifact_contracts"])
    }
    return {
        kind: wire_schema_identity_for_kind(language_bundle, kind)
        for kind in standalone_kinds | artifact_kinds
    }


def _template_contract_refusal(
    release: dict[str, JsonValue],
    pointer: str,
    message: str,
) -> Schema2RefusalReport:
    identity = release.get("content_identity", "unidentified")
    return template_refusal(
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


def _template_model_source_member_kind(
    kernel: dict[str, JsonValue],
    profile: dict[str, JsonValue],
) -> str:
    template_contract = cast(
        dict[str, JsonValue],
        cast(dict[str, JsonValue], kernel["meta_format"])["template_admission"],
    )
    primitives = {
        cast(str, primitive["id"]): primitive
        for primitive in cast(
            list[dict[str, JsonValue]],
            cast(dict[str, JsonValue], template_contract["primitive_spec"])[
                "primitives"
            ],
        )
    }
    operations = {
        cast(str, operation["id"]): operation
        for operation in cast(
            list[dict[str, JsonValue]], template_contract["operations"]
        )
    }
    role_specs = {
        cast(str, spec["role"]): spec
        for spec in cast(list[dict[str, JsonValue]], profile["member_roles"])
    }
    member_kinds: list[str] = []
    for judgment in cast(list[dict[str, JsonValue]], profile["judgments"]):
        operation = operations[cast(str, judgment["operation"])]
        primitive = primitives[
            cast(str, cast(dict[str, JsonValue], operation["law"])["primitive"])
        ]
        evaluation = cast(dict[str, JsonValue], primitive["evaluation"])
        if evaluation["kind"] != "model-source-admission":
            continue
        role_argument = cast(str, evaluation["role"])
        role = cast(
            str, cast(dict[str, JsonValue], judgment["arguments"])[role_argument]
        )
        member_kinds.append(cast(str, role_specs[role]["member_kind"]))
    if len(member_kinds) != 1:
        raise ValueError("Template profile must declare one Model Source admission")
    return member_kinds[0]


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
        elif isinstance(current, list):
            index = _json_pointer_array_index(part)
            if index is None or index >= len(current):
                return None
            current = current[index]
        else:
            return None
    final = parts[-1]
    if isinstance(current, dict) and final in current:
        current[final] = value
    elif isinstance(current, list):
        index = _json_pointer_array_index(final)
        if index is None or index >= len(current):
            return None
        current[index] = value
    else:
        return None
    return mutated


def _json_pointer_array_index(token: str) -> int | None:
    """Parse the RFC 6901 array-index grammar without Unicode coercion."""
    if token == "0":
        return 0
    if (
        not token
        or token[0] not in "123456789"
        or any(character not in "0123456789" for character in token[1:])
    ):
        return None
    return int(token)


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
    return template_refusal(
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


def _template_primitive_execution_is_supported(
    primitive: dict[str, JsonValue],
) -> bool:
    evaluation = primitive.get("evaluation")
    if not isinstance(evaluation, dict):
        return False
    kind = evaluation.get("kind")
    expected_effect = (
        "bind-derived"
        if kind in {"content-identity", "concatenate-selections"}
        else "bind-model-facts"
        if kind == "model-source-admission"
        else "preserve-graph"
    )
    return (
        isinstance(kind, str)
        and evaluation == TEMPLATE_PRIMITIVE_EVALUATIONS.get(kind)
        and primitive.get("result_effect") == expected_effect
        and primitive.get("failure")
        == {"mode": "judgment-diagnostic", "short_circuit": True}
        and primitive.get("charges") == TEMPLATE_PRIMITIVE_CHARGES.get(kind)
        and (
            kind != "model-source-admission"
            or primitive.get("result_members")
            == ["root_requirements", "resolved_packages", "source_symbols"]
        )
    )


def _template_argument_is_typed(
    value: Any,
    contract: dict[str, JsonValue],
    *,
    argument_types: dict[str, dict[str, JsonValue]],
    roles: dict[str, list[dict[str, JsonValue]]],
    state: _TemplateGraphState,
    admitted_roots: set[str],
    result_members: set[str],
) -> bool:
    kind = contract["kind"]
    if kind == "selector":
        return (
            isinstance(value, dict)
            and set(value) == {"root", "name", "path"}
            and isinstance(value.get("root"), str)
            and value["root"] in admitted_roots
            and isinstance(value.get("name"), str)
            and isinstance(value.get("path"), list)
            and all(isinstance(part, str) and part for part in value["path"])
            and (value["root"] != "role" or value["name"] in roles)
            and (value["root"] != "derived" or value["name"] in state.derived)
        )
    if kind == "non-empty-list":
        item_contract = argument_types.get(cast(str, contract.get("item")))
        return (
            isinstance(value, list)
            and bool(value)
            and item_contract is not None
            and all(
                _template_argument_is_typed(
                    item,
                    item_contract,
                    argument_types=argument_types,
                    roles=roles,
                    state=state,
                    admitted_roots=admitted_roots,
                    result_members=result_members,
                )
                for item in value
            )
        )
    if kind == "role-name":
        return isinstance(value, str) and value in roles
    if kind == "string-list":
        return (
            isinstance(value, list)
            and (contract.get("empty") is True or bool(value))
            and all(isinstance(part, str) and part for part in value)
        )
    if kind == "string":
        return isinstance(value, str) and (contract.get("empty") is True or bool(value))
    if kind == "derived-name":
        return (
            isinstance(value, str)
            and bool(value)
            and (contract.get("fresh") is not True or value not in state.derived)
        )
    if kind == "model-fact-bindings":
        return (
            isinstance(value, list)
            and (contract.get("cardinality") != "one-or-more" or bool(value))
            and all(
                isinstance(binding, dict)
                and set(binding) == {"result", "source"}
                and isinstance(binding.get("source"), str)
                and binding["source"] in result_members
                and isinstance(binding.get("result"), str)
                and bool(binding["result"])
                and binding["result"] not in state.derived
                for binding in value
            )
            and len({binding["source"] for binding in value}) == len(value)
            and len({binding["result"] for binding in value}) == len(value)
        )
    if kind == "enum":
        return value in cast(list[JsonValue], contract.get("values", []))
    if kind == "canonical-json":
        try:
            canonical_bytes(cast(JsonValue, value))
        except (TypeError, ValueError, UnicodeEncodeError):
            return False
        return True
    return False


def _template_arguments_are_typed(
    arguments: dict[str, JsonValue],
    primitive: dict[str, JsonValue],
    argument_types: dict[str, dict[str, JsonValue]],
    *,
    roles: dict[str, list[dict[str, JsonValue]]],
    state: _TemplateGraphState,
    admitted_roots: set[str],
) -> bool:
    declared = primitive.get("argument_types")
    result_members = primitive.get("result_members", [])
    return (
        isinstance(declared, dict)
        and isinstance(result_members, list)
        and set(arguments) == set(cast(list[str], primitive["argument_members"]))
        and all(
            isinstance(type_id, str)
            and type_id in argument_types
            and _template_argument_is_typed(
                arguments[name],
                argument_types[type_id],
                argument_types=argument_types,
                roles=roles,
                state=state,
                admitted_roots=admitted_roots,
                result_members=set(cast(list[str], result_members)),
            )
            for name, type_id in declared.items()
        )
    )


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
    authority_context: AdmittedAuthorityContext,
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
        authority_context=authority_context,
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
    authority_context: AdmittedAuthorityContext,
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
        if expected_path:
            expected = _project_template_path([vector], expected_path, budget)
            declared = arguments[cast(str, evaluation["expected_value"])]
            if len(expected) != 1 or canonical_bytes(
                cast(JsonValue, expected[0])
            ) != canonical_bytes(declared):
                return False
        if len(pointer) != 1 or len(values) != 1:
            raise ValueError("Template vector mutation is ambiguous")
        mutated = _apply_template_vector(
            state.source, cast(str, pointer[0]), cast(JsonValue, values[0])
        )
        result = (
            check_model_source_value(
                mutated,
                authority_context=authority_context,
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
    authority_context: AdmittedAuthorityContext,
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
            selector_contract != TEMPLATE_SELECTOR_CONTRACT
            or accounting != TEMPLATE_RESOURCE_ACCOUNTING
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
    kernel_argument_types = {
        cast(str, row["id"]): row
        for row in cast(
            list[dict[str, JsonValue]],
            primitive_spec["argument_types"],
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
            if primitive is None or not _template_primitive_execution_is_supported(
                primitive
            ):
                raise ValueError(f"unknown Kernel Template primitive: {primitive_id}")
            evaluation = cast(dict[str, JsonValue], primitive["evaluation"])
            kind = cast(str, evaluation["kind"])
            charges = cast(list[str], primitive["charges"])
            budget.begin(charges)
            budget.consume("judgment")
            arguments = cast(dict[str, JsonValue], judgment["arguments"])
            if operator != operation_id or not _template_arguments_are_typed(
                arguments,
                primitive,
                kernel_argument_types,
                roles=roles,
                state=state,
                admitted_roots=admitted_roots,
            ):
                raise ValueError(
                    "LDB Template judgment arguments do not match its typed law"
                )
            derived_before = set(state.derived)
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
                    authority_context,
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
                    authority_context,
                )
            else:
                raise ValueError(
                    f"Template primitive has no Schema-major interpreter: {kind}"
                )

            added_derived = set(state.derived) - derived_before
            result_effect = primitive["result_effect"]
            if (
                result_effect == "preserve-graph"
                and added_derived
                or result_effect == "bind-derived"
                and added_derived != {cast(str, arguments["result"])}
                or result_effect == "bind-model-facts"
                and added_derived
                != {
                    cast(str, binding["result"])
                    for binding in cast(
                        list[dict[str, JsonValue]], arguments["fact_bindings"]
                    )
                }
            ):
                raise ValueError(
                    "Template primitive violated its declared result effect"
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


def validate_template_release(
    release: dict[str, JsonValue],
    kernel: dict[str, JsonValue],
    language_bundle: dict[str, JsonValue],
    authority_context: AdmittedAuthorityContext,
) -> Schema2RefusalReport | None:
    """Admit one packaged release against its exact Kernel/LDB authority."""
    schema_identities = _member_schema_identities(language_bundle)
    schemas = {
        kind: cast(dict[str, JsonValue], wire_schema_for_kind(language_bundle, kind))
        for kind in schema_identities
    }
    try:
        profile = _template_admission_profile(language_bundle)
        member_identity_domain = cast(str, profile["member_identity_domain"])
        release_identity_domain = _artifact_identity_domain(
            language_bundle, "template-release"
        )
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
            release_identity_domain, release_body
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
                member_identity_domain, member_body
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
        return template_refusal(
            "language.package_unavailable",
            "resolution",
            release_identity,
            "/kernel_identity",
            "Template release is incompatible with the admitted Kernel",
        )
    if release["language_bundle_identity"] != language_bundle["content_identity"]:
        return template_refusal(
            "language.package_unavailable",
            "resolution",
            release_identity,
            "/language_bundle_identity",
            "Template release is incompatible with the admitted LDB",
        )
    return _validate_template_semantics(
        release,
        kernel,
        language_bundle,
        authority_context,
    )


@dataclass(frozen=True)
class AdmittedTemplate:
    release: dict[str, JsonValue]
    kernel: dict[str, JsonValue]
    language_bundle: dict[str, JsonValue]
    profile: dict[str, JsonValue]
    schema_identities: dict[str, str]


def load_admitted_template(
    provider: TemplateProvider,
    authority_context_provider: AuthorityContextProvider,
) -> AdmittedTemplate | Schema2RefusalReport:
    try:
        context = resolve_authority_context(authority_context_provider)
    except AuthorityLoadError as err:
        return ingress_refusal(err.code, err.subject, err.message)
    if isinstance(context, BootstrapAdmission):
        return bootstrap_refusal(context)
    kernel = context.kernel
    language_bundle = context.language_bundle
    release = provider(context)
    refusal = validate_template_release(
        release,
        cast(dict[str, JsonValue], kernel),
        cast(dict[str, JsonValue], language_bundle),
        context,
    )
    if refusal is not None:
        return refusal
    return AdmittedTemplate(
        release=release,
        kernel=cast(dict[str, JsonValue], kernel),
        language_bundle=cast(dict[str, JsonValue], language_bundle),
        profile=_template_admission_profile(language_bundle),
        schema_identities=_member_schema_identities(language_bundle),
    )


@dataclass(frozen=True)
class TemplateInstantiationPlan:
    """Authenticated Template-derived members ready for publication."""

    artifacts: dict[str, PublicationMember]
    command_input_identity: str
    language_bundle: dict[str, JsonValue]
    source_schema: dict[str, JsonValue]
    source_identity_domain: str
    source_identity: str

    def member_is_admitted(self, name: str, value: dict[str, Any]) -> bool:
        """Re-admit one planned publication member."""
        if name == "model-source-package":
            try:
                jsonschema.validate(value, self.source_schema)
            except jsonschema.ValidationError:
                return False
            return (
                content_identity(
                    self.source_identity_domain,
                    cast(JsonValue, value),
                )
                == self.source_identity
            )
        return verify_artifact(value, self.language_bundle)


def prepare_template_instantiation(
    template_id: str,
    package_id: str,
    provider: TemplateProvider,
    authority_context_provider: AuthorityContextProvider,
) -> TemplateInstantiationPlan | Schema2RefusalReport:
    """Admit one release and derive its editable Model Source publication."""
    admitted = load_admitted_template(provider, authority_context_provider)
    if isinstance(admitted, Schema2RefusalReport):
        return admitted
    release = admitted.release
    kernel = admitted.kernel
    language_bundle = admitted.language_bundle
    if template_id != release["id"]:
        return template_refusal(
            "language.package_unavailable",
            "resolution",
            cast(str, release["content_identity"]),
            "/id",
            f"Template {template_id} is unavailable",
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
    starter = cast(dict[str, JsonValue], starter_members[0]["payload"])
    source = cast(dict[str, JsonValue], deepcopy(starter))
    source_identity_domain = model_source_identity_domain(language_bundle)
    starter_identity = content_identity(source_identity_domain, starter)
    manifest = cast(dict[str, JsonValue], source["manifest"])
    manifest["id"] = package_id
    manifest["template_provenance"] = {
        "template_id": release["id"],
        "template_identity": release["content_identity"],
        "starter_identity": starter_identity,
    }
    source_identity = content_identity(source_identity_domain, source)
    command_input = identified_artifact(
        language_bundle,
        "template-instantiate-command-input",
        {
            "template_identity": release["content_identity"],
            "package_id": package_id,
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
            "package_id": package_id,
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
    return TemplateInstantiationPlan(
        artifacts={
            "model-source-package": PublicationMember(
                value=cast(dict[str, Any], source),
                artifact_kind="model-source-package",
                wire_schema_identity=admitted.schema_identities["model-source-package"],
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
        },
        command_input_identity=cast(str, command_input["content_identity"]),
        language_bundle=language_bundle,
        source_schema=source_schema,
        source_identity_domain=source_identity_domain,
        source_identity=source_identity,
    )
