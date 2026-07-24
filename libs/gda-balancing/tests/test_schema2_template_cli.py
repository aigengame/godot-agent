"""Public Template release and instantiation tracer for Standard Schema 2.0 (#553)."""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
import gda_balancing.commands.template as template_command_module
import gda_balancing.schema2.model as schema2_model
from gda_balancing.commands.template import (
    TEMPLATE_GET,
    TEMPLATE_INSTANTIATE,
    _minimal_release,
    template_get_handler,
    template_instantiate_handler,
)
from gda_balancing.schema2.authority import authority_set
from gda_balancing.schema2.canonical import canonical_bytes, content_identity
from gda_balancing.schema2.diagnostics import Schema2RefusalReport
from gda_balancing.schema2.model import (
    CheckedModel,
    check_model_source_value,
    checked_model_template_facts,
)


def _reidentify_release(release):
    release["manifest"] = []
    for member in release["members"]:
        member["content_identity"] = content_identity(
            "template-member-v2",
            {key: value for key, value in member.items() if key != "content_identity"},
        )
        release["manifest"].append(
            {
                key: member[key]
                for key in (
                    "logical_name",
                    "member_kind",
                    "member_schema_identity",
                    "content_identity",
                )
            }
        )
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    return release


def _replace_json_value(value: Any, old: Any, new: Any) -> Any:
    if isinstance(value, dict):
        return {key: _replace_json_value(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_json_value(item, old, new) for item in value]
    return new if value == old else value


class _ReferenceBudgetExhausted(Exception):
    pass


_REFERENCE_EXECUTION_LAWS = {
    "content-identity": {
        "kind": "content-identity",
        "selector": "selector",
        "selection_cardinality": "exactly-one",
        "domain": "identity_domain",
        "result": "result",
        "canonical_encoding": "kernel.canonical_encoding",
    },
    "concatenate-selections": {
        "kind": "concatenate-selections",
        "selectors": "selectors",
        "order": "selector-order-then-member-order",
        "result": "result",
    },
    "model-source-admission": {
        "kind": "model-source-admission",
        "role": "role",
        "role_cardinality": "exactly-one",
        "authority": "exact-caller-pair",
        "bindings": "fact_bindings",
    },
    "canonical-unique": {
        "kind": "canonical-unique",
        "selector": "selector",
        "selection_cardinality": "one-or-more",
        "equality": "kernel-canonical-bytes",
    },
    "canonical-inventory": {
        "kind": "canonical-inventory",
        "selector": "selector",
        "selection_cardinality": "one-or-more",
        "inventory": "inventory",
        "relation": "subset",
        "equality": "kernel-canonical-bytes",
    },
    "canonical-set-relation": {
        "kind": "canonical-set-relation",
        "left": "left",
        "right": "right",
        "relation": "relation",
        "relations": ["equal", "subset"],
        "equality": "kernel-canonical-bytes",
    },
    "canonical-scoped-relation": {
        "kind": "canonical-scoped-relation",
        "source": "source",
        "source_scope_path": "source_scope_path",
        "source_values_path": "source_values_path",
        "target": "target",
        "target_scope_path": "target_scope_path",
        "target_values_path": "target_values_path",
        "row_scope_cardinality": "exactly-one",
        "row_values_cardinality": "one-or-more",
        "relation": "relation",
        "relations": ["equal", "subset"],
        "equality": "kernel-canonical-bytes",
    },
    "canonical-scoped-unique": {
        "kind": "canonical-scoped-unique",
        "selector": "selector",
        "scope_path": "scope_path",
        "values_path": "values_path",
        "row_scope_cardinality": "exactly-one",
        "row_values_cardinality": "one-or-more",
        "equality": "kernel-canonical-bytes",
    },
    "closed-int64-interval": {
        "kind": "closed-int64-interval",
        "selector": "selector",
        "selection_cardinality": "one-or-more",
        "minimum_member": "minimum_member",
        "maximum_member": "maximum_member",
        "integer_domain": "signed-int64-excluding-boolean",
    },
    "closed-int64-interval-join": {
        "kind": "closed-int64-interval-join",
        "source": "source",
        "source_key_path": "source_key_path",
        "source_value_path": "source_value_path",
        "target": "target",
        "target_key_path": "target_key_path",
        "target_interval_path": "target_interval_path",
        "target_key_cardinality": "exactly-one",
        "target_interval_cardinality": "exactly-one",
        "source_key_cardinality": "exactly-one",
        "source_value_cardinality": "exactly-one",
        "minimum_member": "minimum_member",
        "maximum_member": "maximum_member",
        "integer_domain": "signed-int64-excluding-boolean",
        "key_equality": "kernel-canonical-bytes",
    },
    "model-source-vector": {
        "kind": "model-source-vector",
        "role": "role",
        "pointer_path": "pointer_path",
        "value_path": "value_path",
        "outcome": "outcome",
        "diagnostic_path": "diagnostic_path",
        "expected_path": "expected_path",
        "expected_value": "expected_value",
        "pointer_encoding": "RFC6901-existing-target",
        "mutation": "deep-copy-single-replacement",
        "admission": "exact-caller-pair",
        "refused_diagnostic_cardinality": "exactly-one",
    },
}
_REFERENCE_CHARGES = {
    "content-identity": ["judgment", "selected-value"],
    "concatenate-selections": ["judgment", "selected-value"],
    "model-source-admission": ["judgment"],
    "canonical-unique": ["judgment", "selected-value"],
    "canonical-inventory": ["judgment", "selected-value"],
    "canonical-set-relation": ["judgment", "selected-value"],
    "canonical-scoped-relation": ["judgment", "selected-value", "scoped-row"],
    "canonical-scoped-unique": ["judgment", "selected-value", "scoped-row"],
    "closed-int64-interval": ["judgment", "selected-value"],
    "closed-int64-interval-join": ["judgment", "selected-value"],
    "model-source-vector": ["judgment", "selected-value", "vector-execution"],
}
_REFERENCE_ARGUMENT_TYPES = [
    {"id": "selector", "kind": "selector"},
    {"id": "selector-list", "item": "selector", "kind": "non-empty-list"},
    {"id": "role", "kind": "role-name"},
    {"empty": True, "id": "path", "kind": "string-list"},
    {"empty": False, "id": "non-empty-string", "kind": "string"},
    {"fresh": True, "id": "fresh-derived-name", "kind": "derived-name"},
    {
        "cardinality": "one-or-more",
        "id": "fact-bindings",
        "kind": "model-fact-bindings",
    },
    {"id": "relation", "kind": "enum", "values": ["equal", "subset"]},
    {"id": "outcome", "kind": "enum", "values": ["admitted", "refused"]},
    {"id": "json-value", "kind": "canonical-json"},
]


class _ReferenceBudget:
    def __init__(self, limit, rules):
        self.remaining = limit
        self.rules = {row["event"]: row["amount"] for row in rules}
        self.allowed = {"member-role"}

    def begin(self, charges):
        if (
            not charges
            or "judgment" not in charges
            or not set(charges) <= set(self.rules)
        ):
            raise ValueError("invalid primitive charge contract")
        self.allowed = set(charges)

    def charge(self, event, amount=1):
        if event not in self.allowed or event not in self.rules:
            raise ValueError("undeclared primitive charge")
        self.remaining -= amount
        if self.remaining < 0:
            raise _ReferenceBudgetExhausted


def _reference_primitive_is_supported(primitive):
    evaluation = primitive.get("evaluation")
    if not isinstance(evaluation, dict):
        return False
    kind = evaluation.get("kind")
    if not isinstance(kind, str):
        return False
    effect = (
        "bind-derived"
        if kind in {"content-identity", "concatenate-selections"}
        else "bind-model-facts"
        if kind == "model-source-admission"
        else "preserve-graph"
    )
    return (
        evaluation == _REFERENCE_EXECUTION_LAWS.get(kind)
        and primitive.get("result_effect") == effect
        and primitive.get("failure")
        == {"mode": "judgment-diagnostic", "short_circuit": True}
        and primitive.get("charges") == _REFERENCE_CHARGES.get(kind)
        and (
            kind != "model-source-admission"
            or primitive.get("result_members")
            == ["root_requirements", "resolved_packages", "source_symbols"]
        )
    )


def _reference_argument_is_typed(
    value,
    contract,
    *,
    argument_types,
    roles,
    derived,
    roots,
    result_members,
):
    kind = contract["kind"]
    if kind == "selector":
        return (
            isinstance(value, dict)
            and set(value) == {"name", "path", "root"}
            and isinstance(value.get("root"), str)
            and value["root"] in roots
            and isinstance(value.get("name"), str)
            and isinstance(value.get("path"), list)
            and all(isinstance(part, str) and part for part in value["path"])
            and (value["root"] != "role" or value["name"] in roles)
            and (value["root"] != "derived" or value["name"] in derived)
        )
    if kind == "non-empty-list":
        item_contract = argument_types.get(contract.get("item"))
        return (
            isinstance(value, list)
            and bool(value)
            and item_contract is not None
            and all(
                _reference_argument_is_typed(
                    item,
                    item_contract,
                    argument_types=argument_types,
                    roles=roles,
                    derived=derived,
                    roots=roots,
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
            and (contract.get("fresh") is not True or value not in derived)
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
                and binding["result"] not in derived
                for binding in value
            )
            and len({binding["source"] for binding in value}) == len(value)
            and len({binding["result"] for binding in value}) == len(value)
        )
    if kind == "enum":
        return value in contract.get("values", [])
    if kind == "canonical-json":
        try:
            canonical_bytes(value)
        except (TypeError, ValueError, UnicodeEncodeError):
            return False
        return True
    return False


def _reference_project(values, path, budget):
    current = list(values)
    for segment in path:
        projected = []
        for value in current:
            if segment == "*":
                if not isinstance(value, list):
                    raise ValueError("wildcard input is not a list")
                budget.charge("selected-value", len(value))
                projected.extend(value)
            else:
                if not isinstance(value, dict) or segment not in value:
                    raise ValueError("selector path is absent")
                budget.charge("selected-value")
                projected.append(value[segment])
        current = projected
    return current


def _reference_json_pointer(source, pointer, replacement):
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        return None
    parts = [
        part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")
    ]
    result = deepcopy(source)
    current = result
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
    last = parts[-1]
    if isinstance(current, dict) and last in current:
        current[last] = replacement
    elif isinstance(current, list) and last.isdecimal():
        index = int(last)
        if index >= len(current):
            return None
        current[index] = replacement
    else:
        return None
    return result


def _reference_template_admission(release, kernel, language_bundle):
    """Second Template graph interpreter; imports no production Template helpers."""
    profile = language_bundle["language"]["template_admission_profiles"][0]
    meta = kernel["meta_format"]["template_admission"]
    diagnostics = {row["code"]: row["stage"] for row in language_bundle["diagnostics"]}
    structural = profile["structural_diagnostic"]
    resource = profile["resource_diagnostic"]
    try:
        limit = language_bundle
        for part in profile["max_steps_path"].split("."):
            limit = limit[part]
        budget = _ReferenceBudget(limit, meta["resource_accounting"]["charge_rules"])
        specifications = {row["member_kind"]: row for row in profile["member_roles"]}
        roles = {row["role"]: [] for row in profile["member_roles"]}
        for member in release["members"]:
            budget.charge("member-role")
            spec = specifications.get(member["member_kind"])
            if spec is None:
                raise ValueError("undeclared member kind")
            roles[spec["role"]].append(member["payload"])
        for row in profile["member_roles"]:
            count = len(roles[row["role"]])
            if (
                row["cardinality"] == "exactly-one"
                and count != 1
                or row["cardinality"] == "one-or-more"
                and count < 1
            ):
                raise ValueError("role cardinality failed")

        derived = {}
        admitted_source = None
        checked_source = None
        operations = {row["id"]: row for row in meta["operations"]}
        primitives = {row["id"]: row for row in meta["primitive_spec"]["primitives"]}
        argument_types = {
            row["id"]: row for row in meta["primitive_spec"]["argument_types"]
        }
        if meta["primitive_spec"]["argument_types"] != _REFERENCE_ARGUMENT_TYPES:
            raise ValueError("unknown Template primitive argument type system")

        def select(selector):
            root = selector["root"]
            if root == "kernel":
                values = [kernel]
            elif root == "language-bundle":
                values = [language_bundle]
            elif root == "release":
                values = [release]
            elif root == "role":
                values = roles[selector["name"]]
            elif root == "derived":
                values = [derived[selector["name"]]]
            else:
                raise ValueError("unknown selector root")
            return _reference_project(values, selector["path"], budget)

        def key_set(values):
            return {canonical_bytes(value) for value in values}

        def scoped(rows, scope_path, values_path):
            grouped = {}
            for row in rows:
                budget.charge("scoped-row")
                scope = _reference_project([row], scope_path, budget)
                values = _reference_project([row], values_path, budget)
                if len(scope) != 1 or not values:
                    raise ValueError("ambiguous scoped row")
                grouped.setdefault(canonical_bytes(scope[0]), set()).update(
                    key_set(values)
                )
            return grouped

        for judgment in profile["judgments"]:
            operation = operations[judgment["operation"]]
            law = operation["law"]
            primitive = primitives[law["primitive"]]
            evaluation = primitive["evaluation"]
            arguments = judgment["arguments"]
            if (
                not _reference_primitive_is_supported(primitive)
                or law["operator"] != operation["id"]
                or set(arguments) != set(primitive["argument_members"])
                or any(
                    not _reference_argument_is_typed(
                        arguments[name],
                        argument_types[type_id],
                        argument_types=argument_types,
                        roles=roles,
                        derived=derived,
                        roots=set(meta["selector"]["roots"]),
                        result_members=set(primitive.get("result_members", [])),
                    )
                    for name, type_id in primitive["argument_types"].items()
                )
            ):
                raise ValueError("judgment does not instantiate its typed Kernel law")
            budget.begin(primitive["charges"])
            budget.charge("judgment")
            kind = evaluation["kind"]
            holds = True
            derived_before = set(derived)

            if kind == "content-identity":
                selected = select(arguments[evaluation["selector"]])
                result_name = arguments[evaluation["result"]]
                if len(selected) != 1 or result_name in derived:
                    raise ValueError("ambiguous identity derivation")
                derived[result_name] = content_identity(
                    arguments[evaluation["domain"]], selected[0]
                )
            elif kind == "concatenate-selections":
                result_name = arguments[evaluation["result"]]
                if result_name in derived:
                    raise ValueError("duplicate derived result")
                concatenated = []
                for selector in arguments[evaluation["selectors"]]:
                    concatenated.extend(select(selector))
                derived[result_name] = concatenated
            elif kind == "model-source-admission":
                candidates = roles[arguments[evaluation["role"]]]
                if len(candidates) != 1:
                    raise ValueError("ambiguous Model Source")
                admitted_source = candidates[0]
                result = check_model_source_value(
                    admitted_source,
                    kernel=kernel,
                    language_bundle=language_bundle,
                )
                if isinstance(result, Schema2RefusalReport):
                    return False, result.diagnostics[0].code
                checked_source = result
                facts = checked_model_template_facts(result)
                if set(facts) != set(primitive["result_members"]):
                    raise ValueError("Model Source result shape drifted")
                for binding in arguments[evaluation["bindings"]]:
                    if binding["result"] in derived:
                        raise ValueError("duplicate Model Source result binding")
                    derived[binding["result"]] = facts[binding["source"]]
            elif kind == "canonical-unique":
                values = select(arguments[evaluation["selector"]])
                holds = bool(values) and len(values) == len(key_set(values))
            elif kind == "canonical-inventory":
                values = key_set(select(arguments[evaluation["selector"]]))
                holds = bool(values) and values <= key_set(
                    select(arguments[evaluation["inventory"]])
                )
            elif kind == "canonical-set-relation":
                left = key_set(select(arguments[evaluation["left"]]))
                right = key_set(select(arguments[evaluation["right"]]))
                holds = (
                    left == right
                    if arguments[evaluation["relation"]] == "equal"
                    else left <= right
                )
            elif kind == "canonical-scoped-relation":
                left = scoped(
                    select(arguments[evaluation["source"]]),
                    arguments[evaluation["source_scope_path"]],
                    arguments[evaluation["source_values_path"]],
                )
                right = scoped(
                    select(arguments[evaluation["target"]]),
                    arguments[evaluation["target_scope_path"]],
                    arguments[evaluation["target_values_path"]],
                )
                holds = (
                    left == right
                    if arguments[evaluation["relation"]] == "equal"
                    else set(left) <= set(right)
                    and all(left[key] <= right[key] for key in left)
                )
            elif kind == "canonical-scoped-unique":
                grouped = {}
                for row in select(arguments[evaluation["selector"]]):
                    budget.charge("scoped-row")
                    scope = _reference_project(
                        [row], arguments[evaluation["scope_path"]], budget
                    )
                    values = _reference_project(
                        [row], arguments[evaluation["values_path"]], budget
                    )
                    if len(scope) != 1 or not values:
                        raise ValueError("ambiguous scoped uniqueness row")
                    grouped.setdefault(canonical_bytes(scope[0]), []).extend(
                        canonical_bytes(value) for value in values
                    )
                holds = bool(grouped) and all(
                    len(values) == len(set(values)) for values in grouped.values()
                )
            elif kind == "closed-int64-interval":
                intervals = select(arguments[evaluation["selector"]])
                minimum = arguments[evaluation["minimum_member"]]
                maximum = arguments[evaluation["maximum_member"]]
                holds = bool(intervals)
                for interval in intervals:
                    holds = holds and (
                        isinstance(interval, dict)
                        and set(interval) == {minimum, maximum}
                        and isinstance(interval[minimum], int)
                        and not isinstance(interval[minimum], bool)
                        and isinstance(interval[maximum], int)
                        and not isinstance(interval[maximum], bool)
                        and interval[minimum] <= interval[maximum]
                    )
            elif kind == "closed-int64-interval-join":
                targets = {}
                for row in select(arguments[evaluation["target"]]):
                    key = _reference_project(
                        [row], arguments[evaluation["target_key_path"]], budget
                    )
                    interval = _reference_project(
                        [row], arguments[evaluation["target_interval_path"]], budget
                    )
                    if len(key) != 1 or len(interval) != 1:
                        raise ValueError("ambiguous interval target")
                    encoded = canonical_bytes(key[0])
                    if encoded in targets:
                        raise ValueError("duplicate interval target")
                    targets[encoded] = interval[0]
                minimum = arguments[evaluation["minimum_member"]]
                maximum = arguments[evaluation["maximum_member"]]
                for row in select(arguments[evaluation["source"]]):
                    key = _reference_project(
                        [row], arguments[evaluation["source_key_path"]], budget
                    )
                    value = _reference_project(
                        [row], arguments[evaluation["source_value_path"]], budget
                    )
                    if len(key) != 1 or len(value) != 1:
                        raise ValueError("ambiguous interval source")
                    interval = targets.get(canonical_bytes(key[0]))
                    holds = holds and (
                        isinstance(interval, dict)
                        and isinstance(value[0], int)
                        and not isinstance(value[0], bool)
                        and interval[minimum] <= value[0] <= interval[maximum]
                    )
            elif kind == "model-source-vector":
                if admitted_source is None:
                    raise ValueError("vectors precede Model Source admission")
                for vector in roles[arguments[evaluation["role"]]]:
                    budget.charge("vector-execution")
                    pointer = _reference_project(
                        [vector], arguments[evaluation["pointer_path"]], budget
                    )
                    value = _reference_project(
                        [vector], arguments[evaluation["value_path"]], budget
                    )
                    if arguments[evaluation["expected_path"]] and _reference_project(
                        [vector], arguments[evaluation["expected_path"]], budget
                    ) != [arguments[evaluation["expected_value"]]]:
                        holds = False
                        break
                    if len(pointer) != 1 or len(value) != 1:
                        raise ValueError("ambiguous vector")
                    mutated = _reference_json_pointer(
                        admitted_source, pointer[0], value[0]
                    )
                    outcome = (
                        check_model_source_value(
                            mutated,
                            kernel=kernel,
                            language_bundle=language_bundle,
                        )
                        if mutated is not None
                        else None
                    )
                    if arguments[evaluation["outcome"]] == "admitted":
                        holds = isinstance(outcome, CheckedModel)
                    else:
                        expected = _reference_project(
                            [vector], arguments[evaluation["diagnostic_path"]], budget
                        )
                        holds = (
                            len(expected) == 1
                            and isinstance(outcome, Schema2RefusalReport)
                            and len(outcome.diagnostics) == 1
                            and outcome.diagnostics[0].code == expected[0]
                        )
                    if not holds:
                        break
            else:
                raise ValueError("unknown Template primitive")

            added = set(derived) - derived_before
            effect = primitive["result_effect"]
            if (
                effect == "preserve-graph"
                and added
                or effect == "bind-derived"
                and added != {arguments["result"]}
                or effect == "bind-model-facts"
                and added
                != {binding["result"] for binding in arguments["fact_bindings"]}
            ):
                raise ValueError("primitive result effect drifted")
            if not holds:
                return False, judgment["diagnostic"]
        if checked_source is None:
            return False, structural
        return True, None
    except _ReferenceBudgetExhausted:
        return False, resource
    except (KeyError, TypeError, ValueError):
        assert diagnostics[structural] == "static"
        return False, structural


def _with_secondary_vertical_slice(release, metric_id="secondary-value"):
    def original(name):
        return next(item for item in release["members"] if item["logical_name"] == name)

    experiment = deepcopy(original("experiment-specification"))
    experiment["logical_name"] = "experiment-secondary"
    experiment["payload"]["id"] = "standard.quantity-minimal.experiment.secondary"
    experiment["payload"]["scenarios"] = ["standard.quantity-minimal.golden.secondary"]
    experiment["payload"]["metrics"][0]["id"] = metric_id
    golden = deepcopy(original("golden-scenario"))
    golden["logical_name"] = "golden-secondary"
    golden["payload"]["id"] = "standard.quantity-minimal.golden.secondary"
    golden["payload"]["experiment"] = experiment["payload"]["id"]
    negative = deepcopy(original("negative-vector"))
    negative["logical_name"] = "negative-secondary"
    negative["payload"]["id"] = "standard.quantity-minimal.invalid-domain.secondary"
    negative["payload"]["mutation"] = {
        "pointer": "/modules/0/symbols/0/domain",
        "value": {"minimum": 2, "maximum": 1},
    }
    boundary = deepcopy(original("boundary-vector"))
    boundary["logical_name"] = "boundary-secondary"
    boundary["payload"]["id"] = "standard.quantity-minimal.minimum-boundary"
    boundary["payload"]["pointer"] = "/modules/0/symbols/0/domain/minimum"
    boundary["payload"]["value"] = 0
    release["members"].extend((experiment, golden, negative, boundary))
    coverage = original("coverage-matrix")["payload"]["rows"]
    coverage.append(
        {
            "id": "template.quantity.secondary",
            "requirement": "A second Experiment closes independently.",
            "capabilities": ["quantity.declare", "quantity.lower"],
            "operations": ["quantity.identity"],
            "packages": ["core.quantity"],
            "experiment": experiment["payload"]["id"],
            "golden_scenario": golden["payload"]["id"],
            "vectors": [negative["payload"]["id"], boundary["payload"]["id"]],
            "observables": [metric_id],
        }
    )
    return _reidentify_release(release)


def _template_invocation_directory(invocation_key):
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "invocations").glob(
            f"*/{invocation_key}"
        )
    )
    assert len(matches) == 1
    return matches[0]


def _template_anchor_path(invocation_key):
    matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors").glob(
            f"*/{invocation_key}.json"
        )
    )
    assert len(matches) == 1
    return matches[0]


def test_template_list_exposes_the_packaged_content_addressed_release(run_cli):
    exit_code, stdout, stderr = run_cli(["template", "list"])

    assert (exit_code, stderr) == (0, "")
    result = json.loads(stdout)
    assert result == {
        "templates": [
            {
                "id": "standard.quantity-minimal",
                "version": "2.0.0",
                "content_identity": (
                    "sha256:cb3b1777bbf8816874fb1610e69c01938a149265aaadd775407d9361ac75fb87"
                ),
            }
        ]
    }
    assert result["templates"][0]["content_identity"].startswith("sha256:")


def test_minimal_release_derives_every_authority_identity_from_its_inputs():
    authority = authority_set()
    kernel = authority["kernel"]
    language_bundle = authority["language_bundle"]
    language = cast(Any, language_bundle["language"])
    kernel["content_identity"] = "sha256:" + "a" * 64
    language_bundle["content_identity"] = "sha256:" + "b" * 64
    package = language["packages"][0]
    package["content_identity"] = "sha256:" + "c" * 64
    schema = next(
        row["schema"]
        for collection in ("wire_schemas", "artifact_wire_schemas")
        for row in language[collection]
        if row["artifact_kind"] == "boundary-vector"
    )
    schema["title"] = "Changed boundary vector schema"

    release = cast(Any, _minimal_release(kernel, language_bundle))

    assert release["kernel_identity"] == kernel["content_identity"]
    assert release["language_bundle_identity"] == language_bundle["content_identity"]
    dependencies = next(
        member
        for member in release["members"]
        if member["member_kind"] == "declared-package-dependencies"
    )
    assert (
        dependencies["payload"]["packages"][0]["content_identity"]
        == (package["content_identity"])
    )
    boundary = next(
        member
        for member in release["members"]
        if member["member_kind"] == "boundary-vector"
    )
    assert boundary["member_schema_identity"] == content_identity(
        "boundary-vector-wire-schema-v2", schema
    )


def test_template_get_returns_the_complete_content_addressed_release(run_cli):
    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ]
    )

    assert (exit_code, stderr) == (0, "")
    release = json.loads(stdout)
    assert release["artifact_kind"] == "template-release"
    assert (release["id"], release["version"]) == (
        "standard.quantity-minimal",
        "2.0.0",
    )
    assert [item["logical_name"] for item in release["manifest"]] == [
        "starter-model-source",
        "experiment-specification",
        "declared-package-dependencies",
        "defaults",
        "compatibility",
        "documentation",
        "coverage-matrix",
        "golden-scenario",
        "negative-vector",
        "boundary-vector",
    ]
    assert len(release["members"]) == len(release["manifest"])
    for entry, member in zip(release["manifest"], release["members"], strict=True):
        assert {
            key: member[key]
            for key in (
                "logical_name",
                "member_kind",
                "member_schema_identity",
                "content_identity",
            )
        } == entry
        assert member["content_identity"] == content_identity(
            "template-member-v2",
            {key: value for key, value in member.items() if key != "content_identity"},
        )
    assert release["content_identity"] == content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )


def test_every_template_member_is_admitted_by_the_exact_kernel_and_ldb(
    tmp_path, run_cli
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    members = {item["logical_name"]: item for item in release["members"]}
    authority = json.loads(run_cli(["schema", "get", "language-bundle"])[1])
    schemas = {
        item["artifact_kind"]: item["schema"]
        for item in json.loads(run_cli(["schema", "get", "wire-schema"])[1])["schemas"]
    }

    for member in members.values():
        schema = schemas[member["member_kind"]]
        assert member["member_schema_identity"] == (
            "sha256:" + schema["$id"].rsplit(":", 1)[-1]
        )
        jsonschema.validate(member["payload"], schema)

    starter = members["starter-model-source"]["payload"]
    source = tmp_path / "starter.json"
    source.write_text(json.dumps(starter), encoding="utf-8")
    assert run_cli(["model", "check", str(source)])[0] == 0
    starter_identity = content_identity("model-source-package-v2", starter)

    language = authority["language_bundle"]["language"]
    package_inventory = {
        (item["id"], item["version"], item["content_identity"])
        for item in language["packages"]
    }
    dependencies = members["declared-package-dependencies"]["payload"]
    assert {
        (item["id"], item["version"], item["content_identity"])
        for item in dependencies["packages"]
    } <= package_inventory

    experiment = members["experiment-specification"]["payload"]
    assert experiment["kernel_identity"] == release["kernel_identity"]
    assert experiment["language_bundle_identity"] == release["language_bundle_identity"]
    assert experiment["model_source_identity"] == starter_identity

    coverage = members["coverage-matrix"]["payload"]["rows"][0]
    assert set(coverage["capabilities"]) <= {
        item["id"] for item in language["capabilities"]
    }
    known_operations = {item["id"] for item in language["operations"]}
    assert set(coverage["operations"]) <= known_operations
    assert set(coverage["packages"]) <= {item["id"] for item in language["packages"]}
    assert set(coverage["observables"]) <= {
        item["id"] for item in experiment["metrics"]
    }
    assert coverage["experiment"] == experiment["id"]

    golden = members["golden-scenario"]["payload"]
    negative = members["negative-vector"]["payload"]
    boundary = members["boundary-vector"]["payload"]
    assert golden["id"] == coverage["golden_scenario"]
    assert golden["experiment"] == experiment["id"]
    assert golden["model_source_identity"] == starter_identity
    assert {negative["id"], boundary["id"]} == set(coverage["vectors"])

    refused = deepcopy(starter)
    refused["modules"][0]["symbols"][0]["domain"] = negative["mutation"]["value"]
    refused_path = tmp_path / "negative.json"
    refused_path.write_text(json.dumps(refused), encoding="utf-8")
    exit_code, stdout, stderr = run_cli(["model", "check", str(refused_path)])
    assert (exit_code, stderr) == (2, "")
    assert (
        json.loads(stdout)["error"]["diagnostics"][0]["code"] == negative["diagnostic"]
    )

    accepted = deepcopy(starter)
    accepted["modules"][0]["symbols"][0]["domain"]["minimum"] = boundary["value"]
    accepted_path = tmp_path / "boundary.json"
    accepted_path.write_text(json.dumps(accepted), encoding="utf-8")
    assert run_cli(["model", "check", str(accepted_path)])[0] == 0


def test_template_get_refuses_an_unknown_release_with_a_stable_ldb_diagnostic(
    run_cli,
):
    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "missing.template",
            "--version",
            "9.9.9",
        ]
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert [item["code"] for item in error["diagnostics"]] == [
        "language.package_version_unavailable"
    ]


def test_template_get_refuses_a_release_for_an_incompatible_ldb(run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    release["language_bundle_identity"] = "sha256:" + "0" * 64
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda _kernel, _ldb: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "resolution"
    assert error["diagnostics"][0]["code"] == ("language.package_version_unavailable")
    assert error["diagnostics"][0]["primary"]["pointer"] == (
        "/language_bundle_identity"
    )


def test_template_get_refuses_a_member_outside_its_ldb_wire_schema(run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    documentation = next(
        item for item in release["members"] if item["logical_name"] == "documentation"
    )
    documentation["payload"]["host_customization_hook"] = "forbidden"
    documentation["content_identity"] = content_identity(
        "template-member-v2",
        {
            key: value
            for key, value in documentation.items()
            if key != "content_identity"
        },
    )
    manifest_entry = next(
        item for item in release["manifest"] if item["logical_name"] == "documentation"
    )
    manifest_entry["content_identity"] = documentation["content_identity"]
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda _kernel, _ldb: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == ("language.source_contract_mismatch")


def test_template_get_refuses_semantically_unbound_companion_evidence(run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    experiment = next(
        item
        for item in release["members"]
        if item["logical_name"] == "experiment-specification"
    )
    experiment["payload"]["model_source_identity"] = "sha256:" + "0" * 64
    experiment["content_identity"] = content_identity(
        "template-member-v2",
        {key: value for key, value in experiment.items() if key != "content_identity"},
    )
    manifest_entry = next(
        item
        for item in release["manifest"]
        if item["logical_name"] == "experiment-specification"
    )
    manifest_entry["content_identity"] = experiment["content_identity"]
    release["content_identity"] = content_identity(
        "template-release-v2",
        {key: value for key, value in release.items() if key != "content_identity"},
    )
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda _kernel, _ldb: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    error = json.loads(stdout)["error"]
    assert error["stage"] == "static"
    assert error["diagnostics"][0]["code"] == ("language.source_contract_mismatch")


def test_template_get_refuses_every_reidentified_semantic_admission_mutation(
    run_cli,
):
    pristine = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )

    def member(release, name):
        return next(
            item for item in release["members"] if item["logical_name"] == name
        )["payload"]

    mutations = []

    missing_operation = deepcopy(pristine)
    extra_row = deepcopy(member(missing_operation, "coverage-matrix")["rows"][0])
    extra_row["id"] = "template.quantity.unbound"
    extra_row["operations"] = ["missing.operation"]
    member(missing_operation, "coverage-matrix")["rows"].append(extra_row)
    mutations.append(missing_operation)

    missing_pointer = deepcopy(pristine)
    member(missing_pointer, "boundary-vector")["pointer"] = "/does/not/exist"
    mutations.append(missing_pointer)

    false_negative = deepcopy(pristine)
    member(false_negative, "negative-vector")["mutation"]["value"] = {
        "minimum": 0,
        "maximum": 100,
    }
    mutations.append(false_negative)

    unavailable_source_package = deepcopy(pristine)
    starter = member(unavailable_source_package, "starter-model-source")
    starter["package_requirements"][0]["version"] = "9.9.9"
    starter["modules"][0]["imports"][0]["version"] = "9.9.9"
    mutated_source_identity = content_identity("model-source-package-v2", starter)
    member(unavailable_source_package, "experiment-specification")[
        "model_source_identity"
    ] = mutated_source_identity
    member(unavailable_source_package, "golden-scenario")["model_source_identity"] = (
        mutated_source_identity
    )
    mutations.append(unavailable_source_package)

    missing_role = deepcopy(pristine)
    missing_role["members"] = [
        item
        for item in missing_role["members"]
        if item["logical_name"] != "documentation"
    ]
    mutations.append(missing_role)

    unknown_metric_unit = deepcopy(pristine)
    member(unknown_metric_unit, "experiment-specification")["metrics"][0]["unit"] = (
        "missing-unit"
    )
    mutations.append(unknown_metric_unit)

    invalid_default = deepcopy(pristine)
    member(invalid_default, "defaults")["symbol_values"][0]["value"] = 101
    mutations.append(invalid_default)

    unbound_dependency = deepcopy(pristine)
    member(unbound_dependency, "declared-package-dependencies")["packages"][0][
        "content_identity"
    ] = "sha256:" + "f" * 64
    mutations.append(unbound_dependency)

    for release in mutations:
        descriptor = replace(
            TEMPLATE_GET,
            handler=template_get_handler(
                lambda _kernel, _ldb, release=_reidentify_release(release): release
            ),
        )
        exit_code, stdout, stderr = run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ],
            registry=(descriptor,),
        )
        assert (exit_code, stderr) == (2, "")
        assert json.loads(stdout)["error"]["diagnostics"][0]["code"] in {
            "language.source_contract_mismatch",
            "language.package_version_unavailable",
        }


def test_template_admission_accepts_multiple_experiments_scenarios_and_vectors(
    run_cli,
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )

    release = _with_secondary_vertical_slice(release)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda _kernel, _ldb: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (0, ""), stdout
    admitted = json.loads(stdout)
    assert len(admitted["members"]) == 14


def test_metric_identifiers_are_unique_within_each_experiment_not_globally(
    run_cli,
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    release = _with_secondary_vertical_slice(release, metric_id="value")
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda _kernel, _ldb: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (0, ""), stdout


def test_template_admission_refuses_resource_exhaustion_from_coverage_rows(
    run_cli,
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    coverage = next(
        item for item in release["members"] if item["logical_name"] == "coverage-matrix"
    )["payload"]["rows"]
    prototype = coverage[0]
    coverage[:] = [
        {**deepcopy(prototype), "id": f"template.quantity.row-{index:03d}"}
        for index in range(300)
    ]
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(
            lambda _kernel, _ldb: _reidentify_release(release)
        ),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    refusal = json.loads(stdout)
    assert refusal["error"]["diagnostics"][0]["code"] == "language.resource_exhausted"


def test_independent_template_graph_interpreter_agrees_on_admission_and_refusal(
    run_cli,
):
    pristine = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )

    def payload(release, kind):
        return next(
            member["payload"]
            for member in release["members"]
            if member["member_kind"] == kind
        )

    multiple = _with_secondary_vertical_slice(deepcopy(pristine))

    invalid_unit = deepcopy(pristine)
    payload(invalid_unit, "experiment-specification")["metrics"][0]["unit"] = (
        "missing-unit"
    )
    _reidentify_release(invalid_unit)

    false_negative = deepcopy(pristine)
    payload(false_negative, "negative-vector")["mutation"]["value"] = {
        "minimum": 0,
        "maximum": 100,
    }
    _reidentify_release(false_negative)

    exhausted = deepcopy(pristine)
    coverage = payload(exhausted, "genre-coverage-matrix")["rows"]
    row = coverage[0]
    coverage[:] = [
        {**deepcopy(row), "id": f"template.quantity.reference-{index:03d}"}
        for index in range(300)
    ]
    _reidentify_release(exhausted)

    authority = authority_set()
    cases = (
        (pristine, (True, None)),
        (multiple, (True, None)),
        (invalid_unit, (False, "language.source_contract_mismatch")),
        (false_negative, (False, "language.source_contract_mismatch")),
        (exhausted, (False, "language.resource_exhausted")),
    )
    for release, expected in cases:
        reference = _reference_template_admission(
            release,
            authority["kernel"],
            authority["language_bundle"],
        )
        descriptor = replace(
            TEMPLATE_GET,
            handler=template_get_handler(
                lambda _kernel, _ldb, release=release: release
            ),
        )
        exit_code, stdout, stderr = run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ],
            registry=(descriptor,),
        )
        production = (
            (True, None)
            if exit_code == 0
            else (
                False,
                json.loads(stdout)["error"]["diagnostics"][0]["code"],
            )
        )

        assert stderr == ""
        assert reference == production == expected


def test_template_instantiate_publishes_a_new_editable_model_source_identity(
    tmp_path, run_cli
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    starter = next(
        item["payload"]
        for item in release["members"]
        if item["logical_name"] == "starter-model-source"
    )
    starter_identity = content_identity("model-source-package-v2", starter)
    out = tmp_path / "my-quantity.json"

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.my-quantity",
            "--out",
            str(out),
            "--invocation-key",
            "1" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    receipt = json.loads(stdout)
    assert receipt["artifact_kind"] == "artifact-set-receipt"
    assert [item["logical_name"] for item in receipt["member_locators"]] == [
        "model-source-package",
        "template-instantiation-receipt",
    ]
    source = json.loads(out.read_text(encoding="utf-8"))
    assert source["manifest"]["id"] == "example.my-quantity"
    assert source["manifest"]["template_provenance"] == {
        "template_id": release["id"],
        "template_version": release["version"],
        "template_identity": release["content_identity"],
        "starter_identity": starter_identity,
    }
    source_identity = content_identity("model-source-package-v2", source)
    assert source_identity != starter_identity
    instantiation_locator = next(
        item["locator"]
        for item in receipt["member_locators"]
        if item["logical_name"] == "template-instantiation-receipt"
    )
    instantiation_receipt = json.loads(
        Path(instantiation_locator).read_text(encoding="utf-8")
    )
    assert {
        key: instantiation_receipt[key]
        for key in (
            "template_identity",
            "starter_identity",
            "model_source_identity",
            "package_id",
            "kernel_identity",
            "language_bundle_identity",
        )
    } == {
        "template_identity": release["content_identity"],
        "starter_identity": starter_identity,
        "model_source_identity": source_identity,
        "package_id": "example.my-quantity",
        "kernel_identity": release["kernel_identity"],
        "language_bundle_identity": release["language_bundle_identity"],
    }
    assert run_cli(["model", "check", str(out)])[0] == 0

    unchanged_release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    assert (
        next(
            item["payload"]
            for item in unchanged_release["members"]
            if item["logical_name"] == "starter-model-source"
        )
        == starter
    )


def test_template_instantiation_selects_the_starter_by_admitted_role_not_name(
    tmp_path, run_cli
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    starter = next(
        member
        for member in release["members"]
        if member["member_kind"] == "model-source-package"
    )
    starter["logical_name"] = "renamed-starter"
    _reidentify_release(release)
    descriptor = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(lambda _kernel, _ldb: release),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.role-selected",
            "--out",
            str(tmp_path / "role-selected.json"),
            "--invocation-key",
            "0" * 64,
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (0, ""), stdout


def test_template_instantiation_uses_the_ldb_owned_source_role_name(
    tmp_path, run_cli, monkeypatch
):
    authority = authority_set()
    kernel = authority["kernel"]
    language_bundle = authority["language_bundle"]
    profile = language_bundle["language"]["template_admission_profiles"][0]
    source_role = next(
        row for row in profile["member_roles"] if row["role"] == "source"
    )
    source_role["role"] = "starter"
    profile["judgments"] = _replace_json_value(
        profile["judgments"], "source", "starter"
    )
    old_ldb_identity = language_bundle["content_identity"]
    language_bundle["content_identity"] = content_identity(
        "language-definition-bundle-v2",
        {
            key: value
            for key, value in language_bundle.items()
            if key != "content_identity"
        },
    )
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    release = _replace_json_value(
        release, old_ldb_identity, language_bundle["content_identity"]
    )
    _reidentify_release(release)
    monkeypatch.setattr(
        template_command_module,
        "load_authorities",
        lambda: (deepcopy(kernel), deepcopy(language_bundle)),
    )
    descriptor = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(lambda _kernel, _ldb: deepcopy(release)),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.renamed-role",
            "--out",
            str(tmp_path / "renamed-role.json"),
            "--invocation-key",
            "a" * 64,
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (0, ""), (stdout, stderr)


def test_template_vector_expected_value_uses_canonical_equality(run_cli, monkeypatch):
    authority = authority_set()
    kernel = authority["kernel"]
    language_bundle = authority["language_bundle"]
    profile = language_bundle["language"]["template_admission_profiles"][0]
    judgment = next(
        row for row in profile["judgments"] if row["id"] == "template.boundary-vectors"
    )
    judgment["arguments"]["expected_path"] = ["value"]
    judgment["arguments"]["expected_value"] = True
    old_ldb_identity = language_bundle["content_identity"]
    language_bundle["content_identity"] = content_identity(
        "language-definition-bundle-v2",
        {
            key: value
            for key, value in language_bundle.items()
            if key != "content_identity"
        },
    )
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    release = _replace_json_value(
        release, old_ldb_identity, language_bundle["content_identity"]
    )
    boundary = next(
        member
        for member in release["members"]
        if member["member_kind"] == "boundary-vector"
    )
    boundary["payload"]["value"] = 1
    _reidentify_release(release)
    monkeypatch.setattr(
        template_command_module,
        "load_authorities",
        lambda: (deepcopy(kernel), deepcopy(language_bundle)),
    )
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda _kernel, _ldb: deepcopy(release)),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    assert json.loads(stdout)["error"]["diagnostics"][0]["code"] == (
        "language.source_contract_mismatch"
    )


@pytest.mark.parametrize("array_index", ("00", "０"))
def test_template_vector_refuses_non_rfc6901_array_indexes(array_index, run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    boundary = next(
        member
        for member in release["members"]
        if member["member_kind"] == "boundary-vector"
    )
    boundary["payload"]["pointer"] = f"/modules/{array_index}/symbols/0/domain/maximum"
    _reidentify_release(release)
    descriptor = replace(
        TEMPLATE_GET,
        handler=template_get_handler(lambda _kernel, _ldb: deepcopy(release)),
    )

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "get",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
        ],
        registry=(descriptor,),
    )

    assert (exit_code, stderr) == (2, "")
    assert json.loads(stdout)["error"]["diagnostics"][0]["code"] == (
        "language.source_contract_mismatch"
    )


def test_instantiated_source_can_be_edited_and_built_without_a_toolkit_fork(
    tmp_path, run_cli
):
    source_path = tmp_path / "editable.json"
    assert (
        run_cli(
            [
                "template",
                "instantiate",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
                "--package-id",
                "example.edited-quantity",
                "--out",
                str(source_path),
                "--invocation-key",
                "2" * 64,
            ]
        )[0]
        == 0
    )
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["modules"][0]["symbols"][0]["domain"]["maximum"] = 250
    source_path.write_text(json.dumps(source), encoding="utf-8")
    resolved_path = tmp_path / "resolved.json"

    exit_code, stdout, stderr = run_cli(
        [
            "model",
            "build",
            str(source_path),
            "--out",
            str(resolved_path),
            "--invocation-key",
            "3" * 64,
        ]
    )

    assert (exit_code, stderr) == (0, "")
    assert json.loads(stdout)["artifact_kind"] == "artifact-set-receipt"
    assert json.loads(resolved_path.read_text())["artifact_kind"] == ("resolved-model")


def test_template_instantiation_is_atomic_retry_safe_and_input_bound(tmp_path, run_cli):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    invocation_key = "4" * 64
    base = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        "example.retry-safe",
        "--invocation-key",
        invocation_key,
    ]
    failed_out = tmp_path / "failed.json"
    faulting = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(
            lambda _kernel, _ldb: release,
            publication_fault="before-anchor-commit",
        ),
    )

    exit_code, stdout, stderr = run_cli(
        [*base, "--out", str(failed_out)],
        registry=(faulting,),
    )

    assert exit_code == 4
    assert stdout == ""
    assert json.loads(stderr)["error"]["category"] == "internal"
    assert not failed_out.exists()

    first_out = tmp_path / "first.json"
    first = run_cli([*base, "--out", str(first_out)])
    assert (first[0], first[2]) == (0, "")
    second_out = tmp_path / "second.json"
    second = run_cli([*base, "--out", str(second_out)])
    assert (second[0], second[2]) == (0, "")
    assert json.loads(first[1]) == json.loads(second[1])
    assert first_out.read_bytes() == second_out.read_bytes()

    conflict_out = tmp_path / "conflict.json"
    conflict = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.different-input",
            "--out",
            str(conflict_out),
            "--invocation-key",
            invocation_key,
        ]
    )
    assert (conflict[0], conflict[1]) == (3, "")
    assert json.loads(conflict[2])["error"]["code"] == ("invocation_key_conflict")
    assert not conflict_out.exists()


@pytest.mark.parametrize(
    "publication_fault",
    (
        "after-member-write",
        "before-commit",
        "before-anchor-commit",
        "after-commit",
    ),
)
def test_every_template_publication_fault_is_all_or_nothing_and_retryable(
    publication_fault, tmp_path, run_cli
):
    release = json.loads(
        run_cli(
            [
                "template",
                "get",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
            ]
        )[1]
    )
    invocation_key = {
        "after-member-write": "5",
        "before-commit": "6",
        "before-anchor-commit": "7",
        "after-commit": "8",
    }[publication_fault] * 64
    argv = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        f"example.{publication_fault}",
        "--out",
        str(tmp_path / "failed.json"),
        "--invocation-key",
        invocation_key,
    ]
    faulting = replace(
        TEMPLATE_INSTANTIATE,
        handler=template_instantiate_handler(
            lambda _kernel, _ldb: release,
            publication_fault=publication_fault,
        ),
    )

    exit_code, stdout, stderr = run_cli(argv, registry=(faulting,))

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"
    assert not (tmp_path / "failed.json").exists()
    invocation_matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "invocations").glob(
            f"*/{invocation_key}"
        )
    )
    anchor_matches = list(
        (Path(os.environ["GDA_BALANCING_STORE_DIR"]) / "anchors").glob(
            f"*/{invocation_key}.json"
        )
    )
    if publication_fault == "after-commit":
        assert len(invocation_matches) == len(anchor_matches) == 1
    else:
        assert invocation_matches == []
        assert anchor_matches == []

    recovered_out = tmp_path / "recovered.json"
    recovered = run_cli(
        [
            *argv[:-4],
            "--out",
            str(recovered_out),
            "--invocation-key",
            invocation_key,
        ]
    )
    assert (recovered[0], recovered[2]) == (0, "")
    assert recovered_out.is_file()


def test_template_publication_recovers_when_anchor_directory_fsync_fails(
    tmp_path, run_cli, monkeypatch
):
    store = Path(os.environ["GDA_BALANCING_STORE_DIR"])
    real_fsync_directory = schema2_model._fsync_directory
    injected = False

    def fail_after_anchor_link(path):
        nonlocal injected
        if (
            not injected
            and store / "anchors" in (path, *path.parents)
            and list(path.glob("*.json"))
        ):
            injected = True
            raise OSError("injected anchor directory fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(schema2_model, "_fsync_directory", fail_after_anchor_link)
    invocation_key = "b" * 64
    argv = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        "example.anchor-fsync",
        "--out",
        str(tmp_path / "first.json"),
        "--invocation-key",
        invocation_key,
    ]

    failed_exit, failed_stdout, failed_stderr = run_cli(argv)

    assert (failed_exit, failed_stdout) == (4, "")
    assert json.loads(failed_stderr)["error"]["code"] == "internal_error"
    assert injected

    recovered_out = tmp_path / "recovered.json"
    recovered_exit, recovered_stdout, recovered_stderr = run_cli(
        [
            *argv[:-4],
            "--out",
            str(recovered_out),
            "--invocation-key",
            invocation_key,
        ]
    )

    assert (recovered_exit, recovered_stderr) == (0, "")
    assert json.loads(recovered_stdout)["invocation_key"] == invocation_key
    assert recovered_out.is_file()


def test_template_publication_rejects_output_symlinks(tmp_path, run_cli):
    target = tmp_path / "target.json"
    target.write_text("unchanged", encoding="utf-8")
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)

    exit_code, stdout, stderr = run_cli(
        [
            "template",
            "instantiate",
            "--id",
            "standard.quantity-minimal",
            "--version",
            "2.0.0",
            "--package-id",
            "example.alias",
            "--out",
            str(alias),
            "--invocation-key",
            "9" * 64,
        ]
    )

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_template_recovery_rejects_a_coherently_reidentified_anchor_rewrite(
    tmp_path, run_cli
):
    invocation_key = "a" * 64
    argv = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        "example.anchor-rewrite",
        "--out",
        str(tmp_path / "first.json"),
        "--invocation-key",
        invocation_key,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    invocation = _template_invocation_directory(invocation_key)
    index_path = invocation / "publication-index.json"
    index = json.loads(index_path.read_text())
    index["command_input_identity"] = "sha256:" + "f" * 64
    index["content_identity"] = content_identity(
        "publication-index-v2",
        {key: value for key, value in index.items() if key != "content_identity"},
    )
    index_path.write_bytes(canonical_bytes(index))
    anchor_path = _template_anchor_path(invocation_key)
    anchor = json.loads(anchor_path.read_text())
    anchor["publication_index"] = index
    anchor_path.unlink()
    anchor_path.write_bytes(canonical_bytes(anchor))
    anchor_path.chmod(0o444)
    (tmp_path / "first.json").unlink()

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (4, "")
    assert json.loads(stderr)["error"]["code"] == "internal_error"


def test_template_recovery_rejects_a_symlinked_committed_member(tmp_path, run_cli):
    invocation_key = "b" * 64
    argv = [
        "template",
        "instantiate",
        "--id",
        "standard.quantity-minimal",
        "--version",
        "2.0.0",
        "--package-id",
        "example.member-alias",
        "--out",
        str(tmp_path / "first.json"),
        "--invocation-key",
        invocation_key,
    ]
    first = run_cli(argv)
    assert first[0] == 0
    invocation = _template_invocation_directory(invocation_key)
    member = invocation / "model-source-package.json"
    preserved = tmp_path / "preserved-member.json"
    preserved.write_bytes(member.read_bytes())
    member.unlink()
    member.symlink_to(preserved)
    (tmp_path / "first.json").unlink()

    exit_code, stdout, stderr = run_cli(argv)

    assert (exit_code, stdout) == (3, "")
    assert json.loads(stderr)["error"]["code"] == "argument_conflict"


def test_concurrent_template_retries_recover_one_committed_set(tmp_path, run_cli):
    invocation_key = "c" * 64
    barrier = threading.Barrier(2)

    def instantiate(name):
        barrier.wait(timeout=10)
        return run_cli(
            [
                "template",
                "instantiate",
                "--id",
                "standard.quantity-minimal",
                "--version",
                "2.0.0",
                "--package-id",
                "example.concurrent",
                "--out",
                str(tmp_path / f"{name}.json"),
                "--invocation-key",
                invocation_key,
            ]
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(instantiate, "first")
        second = executor.submit(instantiate, "second")
        first_result = first.result(timeout=20)
        second_result = second.result(timeout=20)

    assert (first_result[0], first_result[2]) == (0, "")
    assert (second_result[0], second_result[2]) == (0, "")
    assert json.loads(first_result[1]) == json.loads(second_result[1])
    assert (tmp_path / "first.json").read_bytes() == (
        tmp_path / "second.json"
    ).read_bytes()
    assert _template_anchor_path(invocation_key).is_file()
