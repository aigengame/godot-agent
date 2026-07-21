"""Independent implementation A: recursive Kernel VM and rule pipeline.

This module intentionally imports no prototype helper.  The only shared inputs are
JSON bytes.  Domain, operation, diagnostic, phase, and source tokens are read from
the supplied authority artifacts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable


IMPLEMENTATION = "python-recursive-a-v1"
REQUIRED_ADMISSION_REASONS = {
    "identity_mismatch",
    "kernel_binding_mismatch",
    "malformed_artifact",
    "unknown_opcode",
    "node_shape_invalid",
    "law_missing",
    "law_contract",
    "resource_exhausted",
}
HOST_POST_ADMISSION_REASONS = {
    "compile_resource_exhausted",
    "cross_authority_mismatch",
    "effect_not_allowed",
    "operation_projection_mismatch",
    "parse_invalid",
    "profile_mismatch",
    "replay_profile_mismatch",
    "rng_draw_budget",
    "runtime_profile_projection_mismatch",
    "runtime_resource_exhausted",
    "schedule_backward",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def content_identity(domain: str, payload: Any) -> str:
    digest = hashlib.sha256(domain.encode("utf-8") + b"\x00" + canonical_bytes(payload))
    return f"sha256:{digest.hexdigest()}"


def decimal_integer(value: Any) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.removeprefix("-").isdigit():
        return int(value)
    return None


def exact_numeric_result(value: int, left: Any, right: Any) -> int | str:
    return str(value) if isinstance(left, str) or isinstance(right, str) else value


def value_matches(value: Any, kind: str) -> bool:
    checks = {
        "Any": lambda item: True,
        "Value": lambda item: True,
        "Unit": lambda item: item is None,
        "Int": lambda item: decimal_integer(item) is not None,
        "Str": lambda item: type(item) is str,
        "Bool": lambda item: type(item) is bool,
        "Record": lambda item: type(item) is dict,
        "List": lambda item: type(item) is list,
    }
    return kind in checks and checks[kind](value)


@dataclass
class SemanticFailure(Exception):
    reason: str
    arguments: dict[str, Any]


def artifact_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise SemanticFailure("malformed_artifact", {})
    return payload


class VM:
    def __init__(
        self,
        kernel: dict[str, Any],
        *,
        effect_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.kernel = kernel
        self.effect_handler = effect_handler
        self.consulted_laws: list[str] = []
        self.steps = 0

    def run_law(self, law_id: str, arguments: dict[str, Any]) -> Any:
        law = self.kernel.get("laws", {}).get(law_id)
        if not isinstance(law, dict):
            raise SemanticFailure("law_missing", {"law": law_id})
        if set(arguments) != set(law["parameters"]) or not all(
            value_matches(arguments[name], kind)
            for name, kind in law["parameters"].items()
        ):
            raise SemanticFailure(
                "law_contract", {"law": law_id, "surface": "parameters"}
            )
        self.consulted_laws.append(law_id)
        start = self.steps
        result = self.evaluate(law["body"], dict(arguments))
        accounting = law["resource_accounting"]
        if (
            accounting["unit"] != "vm_step"
            or self.steps - start > accounting["maximum"]
        ):
            raise SemanticFailure(
                "law_contract", {"law": law_id, "surface": "resource_accounting"}
            )
        if not value_matches(result, law["result"]):
            raise SemanticFailure("law_contract", {"law": law_id, "surface": "result"})
        return result

    def evaluate(self, node: Any, environment: dict[str, Any]) -> Any:
        self.steps += 1
        if self.steps > self.kernel["limits"]["max_vm_steps"]:
            raise SemanticFailure("resource_exhausted", {"resource": "vm_steps"})
        if not isinstance(node, dict):
            raise SemanticFailure("node_shape_invalid", {})
        operation = node.get("op")
        if operation == "literal":
            return copy.deepcopy(node["value"])
        if operation == "var":
            name = node["name"]
            if name not in environment:
                raise SemanticFailure("node_shape_invalid", {"binding": name})
            return environment[name]
        if operation == "get":
            current = self.evaluate(node["value"], environment)
            for part in node["path"]:
                current = current[part]
            return copy.deepcopy(current)
        if operation == "object":
            return {
                key: self.evaluate(value, environment)
                for key, value in sorted(node["fields"].items())
            }
        if operation == "list":
            return [self.evaluate(item, environment) for item in node["items"]]
        if operation == "sequence":
            result: Any = None
            for item in node["items"]:
                result = self.evaluate(item, environment)
            return result
        if operation == "let":
            nested = dict(environment)
            nested[node["name"]] = self.evaluate(node["value"], environment)
            return self.evaluate(node["then"], nested)
        if operation == "if":
            condition = self.evaluate(node["condition"], environment)
            branch = node["then"] if condition else node["else"]
            return self.evaluate(branch, environment)
        if operation == "require":
            if not self.evaluate(node["condition"], environment):
                arguments = {
                    key: self.evaluate(value, environment)
                    for key, value in sorted(node.get("arguments", {}).items())
                }
                raise SemanticFailure(str(node["reason"]), arguments)
            return None
        if operation == "eq":
            return self.evaluate(node["left"], environment) == self.evaluate(
                node["right"], environment
            )
        if operation == "not":
            return not self.evaluate(node["value"], environment)
        if operation == "and":
            return all(self.evaluate(item, environment) for item in node["items"])
        if operation == "or":
            return any(self.evaluate(item, environment) for item in node["items"])
        if operation in {
            "lt",
            "le",
            "ge",
            "add",
            "sub",
            "mod",
            "bit_xor",
            "bit_and",
            "shift_left",
            "shift_right",
        }:
            left = self.evaluate(node["left"], environment)
            right = self.evaluate(node["right"], environment)
            left_number = decimal_integer(left)
            right_number = decimal_integer(right)
            if left_number is None or right_number is None:
                raise SemanticFailure("node_shape_invalid", {"operand": "bool"})
            if operation == "lt":
                return left_number < right_number
            if operation == "le":
                return left_number <= right_number
            if operation == "ge":
                return left_number >= right_number
            if operation == "add":
                return exact_numeric_result(left_number + right_number, left, right)
            if operation == "sub":
                return exact_numeric_result(left_number - right_number, left, right)
            if operation == "mod":
                return exact_numeric_result(left_number % right_number, left, right)
            if operation == "bit_xor":
                return exact_numeric_result(left_number ^ right_number, left, right)
            if operation == "bit_and":
                return exact_numeric_result(left_number & right_number, left, right)
            if operation == "shift_left":
                return exact_numeric_result(left_number << right_number, left, right)
            return exact_numeric_result(left_number >> right_number, left, right)
        if operation == "concat":
            return "".join(
                str(self.evaluate(item, environment)) for item in node["items"]
            )
        if operation == "to_string":
            return str(self.evaluate(node["value"], environment))
        if operation == "sha256_u32":
            raw = str(self.evaluate(node["value"], environment)).encode("utf-8")
            return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")
        if operation == "has_key":
            mapping = self.evaluate(node["map"], environment)
            key = self.evaluate(node["key"], environment)
            return isinstance(mapping, dict) and key in mapping
        if operation == "lookup":
            mapping = self.evaluate(node["map"], environment)
            key = self.evaluate(node["key"], environment)
            if not isinstance(mapping, dict) or key not in mapping:
                raise SemanticFailure("node_shape_invalid", {"lookup": key})
            return copy.deepcopy(mapping[key])
        if operation == "keys_equal":
            left = self.evaluate(node["left"], environment)
            right = self.evaluate(node["right"], environment)
            return (
                isinstance(left, dict)
                and isinstance(right, dict)
                and set(left) == set(right)
            )
        if operation == "type_map_matches":
            values = self.evaluate(node["values"], environment)
            signature = self.evaluate(node["signature"], environment)
            if (
                not isinstance(values, dict)
                or not isinstance(signature, dict)
                or set(values) != set(signature)
            ):
                return False
            return all(
                kind in self.kernel["wire_types"] and value_matches(values[name], kind)
                for name, kind in signature.items()
            )
        if operation == "set_equal":
            left = self.evaluate(node["left"], environment)
            right = self.evaluate(node["right"], environment)
            return (
                isinstance(left, list)
                and isinstance(right, list)
                and set(left) == set(right)
            )
        if operation == "program_effects":
            program = self.evaluate(node["program"], environment)
            effects: set[str] = set()
            pending = [program]
            while pending:
                current = pending.pop()
                if isinstance(current, dict):
                    if current.get("op") == "effect" and isinstance(
                        current.get("kind"), str
                    ):
                        effects.add(current["kind"])
                    if current.get("op") == "call_kernel":
                        called = self.kernel.get("laws", {}).get(current.get("law"))
                        if not isinstance(called, dict):
                            raise SemanticFailure(
                                "law_missing", {"law": current.get("law")}
                            )
                        effects.update(called["effects"])
                    pending.extend(current.values())
                elif isinstance(current, list):
                    pending.extend(current)
            return sorted(effects)
        if operation == "evaluate_program":
            program = self.evaluate(node["program"], environment)
            nested_environment = self.evaluate(node["environment"], environment)
            if not isinstance(nested_environment, dict):
                raise SemanticFailure(
                    "node_shape_invalid", {"environment": "not-record"}
                )
            return self.evaluate(program, nested_environment)
        if operation == "select_unique":
            candidates = self.evaluate(node["candidates"], environment)
            direction = self.evaluate(node["direction"], environment)
            if not isinstance(candidates, list) or not candidates:
                raise SemanticFailure("rule_none", {})
            priorities = [candidate["priority"] for candidate in candidates]
            extreme = max(priorities) if direction == "max" else min(priorities)
            selected = [
                candidate
                for candidate in candidates
                if candidate["priority"] == extreme
            ]
            if len(selected) != 1:
                raise SemanticFailure("rule_ambiguous", {})
            return copy.deepcopy(selected[0]["rule"])
        if operation == "lex_gt":
            left = self.evaluate(node["left"], environment)
            right = self.evaluate(node["right"], environment)
            if not isinstance(left, list) or not isinstance(right, list):
                raise SemanticFailure("node_shape_invalid", {"operand": "not-list"})
            return tuple(left) > tuple(right)
        if operation == "assoc_path":
            result = copy.deepcopy(self.evaluate(node["map"], environment))
            raw_path = self.evaluate(node["path"], environment)
            path = raw_path.split(".") if isinstance(raw_path, str) else list(raw_path)
            current = result
            for part in path[:-1]:
                current = current.setdefault(part, {})
            current[path[-1]] = self.evaluate(node["value"], environment)
            return result
        if operation == "call_kernel":
            arguments = {
                key: self.evaluate(value, environment)
                for key, value in sorted(node["arguments"].items())
            }
            return self.run_law(str(node["law"]), arguments)
        if operation == "effect":
            if self.effect_handler is None:
                raise SemanticFailure(
                    "node_shape_invalid", {"effect": node.get("kind")}
                )
            arguments = {
                key: self.evaluate(value, environment)
                for key, value in sorted(node["arguments"].items())
            }
            return self.effect_handler(str(node["kind"]), arguments)
        raise SemanticFailure("unknown_opcode", {"opcode": operation})


def kernel_diagnostic(
    kernel: dict[str, Any], event: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    definition = kernel.get("admission_diagnostics", {}).get(event)
    if not isinstance(definition, dict):
        return {
            "code": "unavailable",
            "stage": "internal",
            "arguments": arguments,
            "location": {"kind": "artifact", "value": "$"},
        }
    return {
        "code": definition["code"],
        "stage": definition["stage"],
        "arguments": arguments,
        "location": {"kind": "artifact", "value": "$"},
    }


def ldb_diagnostic(
    ldb: dict[str, Any],
    reason: str,
    arguments: dict[str, Any],
    location: dict[str, Any],
) -> dict[str, Any]:
    code = ldb["reason_diagnostics"][reason]
    definition = ldb["diagnostics"][code]
    return {
        "code": code,
        "stage": definition["stage"],
        "arguments": arguments,
        "location": location,
    }


def semantic_diagnostic(
    kernel: dict[str, Any],
    ldb: dict[str, Any],
    failure: SemanticFailure,
    location: dict[str, Any],
) -> dict[str, Any]:
    if failure.reason in kernel.get("admission_diagnostics", {}):
        return kernel_diagnostic(kernel, failure.reason, failure.arguments)
    return ldb_diagnostic(ldb, failure.reason, failure.arguments, location)


def program_contract(
    program: Any, kernel: dict[str, Any] | None = None
) -> tuple[set[str], set[str]]:
    effects: set[str] = set()
    refusals: set[str] = set()
    pending = [program]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            if current.get("op") == "effect" and isinstance(current.get("kind"), str):
                effects.add(current["kind"])
            if current.get("op") == "require" and isinstance(
                current.get("reason"), str
            ):
                refusals.add(current["reason"])
            if current.get("op") == "select_unique":
                refusals.update({"rule_none", "rule_ambiguous"})
            if current.get("op") == "call_kernel" and kernel is not None:
                called = kernel.get("laws", {}).get(current.get("law"))
                if not isinstance(called, dict):
                    raise SemanticFailure("law_missing", {"law": current.get("law")})
                effects.update(called["effects"])
                refusals.update(called["refusals"])
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)
    return effects, refusals


def validate_program(kernel: dict[str, Any], node: Any, count: list[int]) -> None:
    count[0] += 1
    if count[0] > kernel["limits"]["max_program_nodes"]:
        raise SemanticFailure("resource_exhausted", {"resource": "program_nodes"})
    if not isinstance(node, dict) or not isinstance(node.get("op"), str):
        raise SemanticFailure("node_shape_invalid", {})
    opcode = node["op"]
    schema = kernel["meta_opcodes"].get(opcode)
    if not isinstance(schema, dict):
        raise SemanticFailure("unknown_opcode", {"opcode": opcode})
    if set(node) != set(schema["fields"]):
        raise SemanticFailure(
            "node_shape_invalid", {"opcode": opcode, "fields": sorted(node)}
        )
    if opcode == "call_kernel" and node["law"] not in kernel["laws"]:
        raise SemanticFailure("law_missing", {"law": node["law"]})
    if opcode == "effect" and node["kind"] not in kernel["effect_kinds"]:
        raise SemanticFailure("node_shape_invalid", {"effect": node["kind"]})
    child_fields = {
        "value",
        "then",
        "else",
        "condition",
        "left",
        "right",
        "map",
        "key",
        "values",
        "signature",
        "program",
        "environment",
        "candidates",
        "direction",
        "path",
    }
    for key, value in node.items():
        if key in child_fields and isinstance(value, dict):
            validate_program(kernel, value, count)
        elif key in {"items"} and isinstance(value, list):
            for item in value:
                validate_program(kernel, item, count)
        elif key in {"fields", "arguments"} and isinstance(value, dict):
            for child in value.values():
                validate_program(kernel, child, count)


def admit(
    kernel_envelope: dict[str, Any], ldb_envelope: dict[str, Any]
) -> dict[str, Any]:
    try:
        kernel = artifact_payload(kernel_envelope)
    except SemanticFailure:
        return {
            "admitted": False,
            "diagnostic": {"code": "unavailable", "stage": "ingress"},
            "implementation": IMPLEMENTATION,
        }
    actual_kernel = content_identity("kernel", kernel)
    if kernel_envelope.get("identity") != actual_kernel:
        return {
            "admitted": False,
            "diagnostic": kernel_diagnostic(
                kernel, "identity_mismatch", {"artifact": "kernel"}
            ),
            "implementation": IMPLEMENTATION,
        }
    if set(kernel.get("admission_diagnostics", {})) != REQUIRED_ADMISSION_REASONS:
        return {
            "admitted": False,
            "diagnostic": kernel_diagnostic(
                kernel,
                "malformed_artifact",
                {"artifact": "kernel.admission_diagnostics"},
            ),
            "implementation": IMPLEMENTATION,
        }
    try:
        ldb = artifact_payload(ldb_envelope)
    except SemanticFailure:
        return {
            "admitted": False,
            "diagnostic": kernel_diagnostic(
                kernel, "malformed_artifact", {"artifact": "ldb"}
            ),
            "implementation": IMPLEMENTATION,
        }
    actual_ldb = content_identity("ldb", ldb)
    if ldb_envelope.get("identity") != actual_ldb:
        return {
            "admitted": False,
            "diagnostic": kernel_diagnostic(
                kernel, "identity_mismatch", {"artifact": "ldb"}
            ),
            "implementation": IMPLEMENTATION,
        }
    if ldb.get("kernel_identity") != actual_kernel:
        return {
            "admitted": False,
            "diagnostic": kernel_diagnostic(kernel, "kernel_binding_mismatch", {}),
            "implementation": IMPLEMENTATION,
        }
    try:
        kernel_refusals: set[str] = set()
        for law in kernel["laws"].values():
            validate_program(kernel, law["body"], [0])
            if set(law) != {
                "parameters",
                "result",
                "effects",
                "refusals",
                "resource_accounting",
                "body",
            }:
                raise SemanticFailure("law_contract", {"surface": "shape"})
            if law["result"] not in kernel["wire_types"] or any(
                kind not in kernel["wire_types"] for kind in law["parameters"].values()
            ):
                raise SemanticFailure("law_contract", {"surface": "types"})
            if (
                law["resource_accounting"].get("unit") != "vm_step"
                or type(law["resource_accounting"].get("maximum")) is not int
                or law["resource_accounting"]["maximum"] < 1
            ):
                raise SemanticFailure(
                    "law_contract", {"surface": "resource_accounting"}
                )
            derived_effects, derived_refusals = program_contract(law["body"], kernel)
            if (
                set(law["effects"]) != derived_effects
                or set(law["refusals"]) != derived_refusals
            ):
                raise SemanticFailure("law_contract", {"surface": "effects/refusals"})
            kernel_refusals.update(derived_refusals)
        for effect in kernel["effect_kinds"].values():
            if effect.get("law") not in kernel["laws"]:
                raise SemanticFailure("law_missing", {"law": effect.get("law")})
        language_refusals: set[str] = set()
        for rule in ldb["rules"]:
            validate_program(kernel, rule["when"], [0])
            validate_program(kernel, rule["body"], [0])
            _, when_refusals = program_contract(rule["when"], kernel)
            _, body_refusals = program_contract(rule["body"], kernel)
            if not (when_refusals | body_refusals) <= set(ldb["reason_diagnostics"]):
                raise SemanticFailure(
                    "law_contract", {"surface": "rule_diagnostic_authority"}
                )
            language_refusals.update(when_refusals | body_refusals)
        for operation in ldb["operations"].values():
            validate_program(kernel, operation["body"], [0])
            if any(
                kind not in kernel["wire_types"]
                for kind in operation["signature"].values()
            ):
                raise SemanticFailure(
                    "law_contract", {"surface": "operation_signature"}
                )
            _, operation_refusals = program_contract(operation["body"], kernel)
            if not operation_refusals <= set(ldb["reason_diagnostics"]):
                raise SemanticFailure(
                    "law_contract", {"surface": "operation_diagnostic_authority"}
                )
            language_refusals.update(operation_refusals)
        for law_id in ldb["required_kernel_laws"]:
            if law_id not in kernel["laws"]:
                raise SemanticFailure("law_missing", {"law": law_id})
        for reason, code in ldb["reason_diagnostics"].items():
            if code not in ldb["diagnostics"] or not isinstance(reason, str):
                raise SemanticFailure("node_shape_invalid", {"diagnostic": code})
        if not kernel_refusals <= set(ldb["reason_diagnostics"]):
            raise SemanticFailure(
                "law_contract", {"surface": "kernel_diagnostic_authority"}
            )
        reachable_post_reasons = (
            HOST_POST_ADMISSION_REASONS | kernel_refusals | language_refusals
        )
        if set(ldb["reason_diagnostics"]) != reachable_post_reasons or set(
            ldb["reason_diagnostics"].values()
        ) != set(ldb["diagnostics"]):
            raise SemanticFailure(
                "law_contract", {"surface": "post_diagnostic_reverse_closure"}
            )
        default_profile = ldb["default_runtime_profile"]
        if default_profile not in ldb["runtime_profiles"]:
            raise SemanticFailure(
                "law_contract", {"surface": "default_runtime_profile"}
            )
        profile = ldb["runtime_profiles"][default_profile]
        if (
            set(profile)
            != {"allowed_effects", "budgets", "phase_order", "rng_mapping", "numeric"}
            or not set(profile["allowed_effects"]) <= set(kernel["effect_kinds"])
            or set(profile["budgets"]) != {"max_draws", "max_events", "max_queue"}
            or any(
                type(limit) is not int or limit < 0
                for limit in profile["budgets"].values()
            )
            or not profile["phase_order"]
            or any(type(rank) is not int for rank in profile["phase_order"].values())
        ):
            raise SemanticFailure("law_contract", {"surface": "runtime_profile"})
        for package in ldb["packages"].values():
            if not isinstance(package.get("operations"), dict) or any(
                selected is not True or name not in ldb["operations"]
                for name, selected in package["operations"].items()
            ):
                raise SemanticFailure(
                    "law_contract", {"surface": "package_operation_closure"}
                )
        configured_phases = {
            ldb["source_package_phase"],
            ldb["source_collection_phase"],
            *ldb["compiler_pipeline"],
        }
        if not configured_phases <= {rule["phase"] for rule in ldb["rules"]} or set(
            ldb["compiler_artifacts"].values()
        ) - set(ldb["compiler_pipeline"]):
            raise SemanticFailure("law_contract", {"surface": "compiler_pipeline"})
    except (KeyError, TypeError, SemanticFailure) as error:
        failure = (
            error
            if isinstance(error, SemanticFailure)
            else SemanticFailure("node_shape_invalid", {})
        )
        event = (
            failure.reason
            if failure.reason in kernel["admission_diagnostics"]
            else "node_shape_invalid"
        )
        return {
            "admitted": False,
            "diagnostic": kernel_diagnostic(kernel, event, failure.arguments),
            "implementation": IMPLEMENTATION,
        }
    receipt_payload = {
        "artifact_kind": "kernel-ldb-admission",
        "kernel_identity": actual_kernel,
        "ldb_identity": actual_ldb,
        "implementation": IMPLEMENTATION,
        "diagnostic_inventory": sorted(ldb["diagnostics"]),
    }
    return {
        "admitted": True,
        **receipt_payload,
        "admission_identity": content_identity("admission-receipt", receipt_payload),
    }


def select_rule(
    vm: VM,
    ldb: dict[str, Any],
    phase: str,
    subject: dict[str, Any],
    source: dict[str, Any],
    sequence: int,
) -> tuple[Any, str]:
    candidates: list[dict[str, Any]] = []
    environment = {
        "authority": ldb,
        "source": source,
        "subject": subject,
        "sequence": sequence,
    }
    for rule in ldb["rules"]:
        if vm.run_law(
            "rule.applicable",
            {"rule": rule, "phase": phase, "environment": environment},
        ):
            candidates.append(
                {"priority": vm.run_law("rule.priority", {"rule": rule}), "rule": rule}
            )
    try:
        rule = vm.run_law("rule.choose", {"candidates": candidates})
    except SemanticFailure as failure:
        failure.arguments.setdefault("phase", phase)
        raise
    return vm.evaluate(rule["body"], environment), str(rule["id"])


def compile_model(request: dict[str, Any]) -> dict[str, Any]:
    admission = admit(request["kernel"], request["ldb"])
    if not admission["admitted"]:
        return {
            "status": "refused",
            "diagnostic": admission["diagnostic"],
            "implementation": IMPLEMENTATION,
        }
    kernel = artifact_payload(request["kernel"])
    ldb = artifact_payload(request["ldb"])
    peer = request.get("peer_admission")
    peer_fields = {
        "admitted",
        "artifact_kind",
        "kernel_identity",
        "ldb_identity",
        "implementation",
        "diagnostic_inventory",
        "admission_identity",
    }
    peer_payload = (
        {key: peer[key] for key in peer_fields - {"admitted", "admission_identity"}}
        if isinstance(peer, dict) and set(peer) == peer_fields
        else None
    )
    if (
        peer_payload is None
        or peer.get("admitted") is not True
        or peer.get("admission_identity")
        != content_identity("admission-receipt", peer_payload)
        or peer.get("artifact_kind") != "kernel-ldb-admission"
        or peer.get("kernel_identity") != admission["kernel_identity"]
        or peer.get("ldb_identity") != admission["ldb_identity"]
        or peer.get("diagnostic_inventory") != sorted(ldb["diagnostics"])
        or not isinstance(peer.get("implementation"), str)
    ):
        return {
            "status": "refused",
            "diagnostic": kernel_diagnostic(
                kernel, "kernel_binding_mismatch", {"artifact": "peer_admission"}
            ),
            "implementation": IMPLEMENTATION,
        }
    source = request["source"]
    vm = VM(kernel)
    consulted_rules: list[str] = []
    ast: list[dict[str, Any]] = []
    hir: list[dict[str, Any]] = []
    lowered: list[dict[str, Any]] = []
    try:
        package_selection, package_rule = select_rule(
            vm, ldb, ldb["source_package_phase"], source, source, -1
        )
        consulted_rules.append(package_rule)
        if not isinstance(package_selection, dict) or set(package_selection) != {
            "package",
            "release",
        }:
            raise SemanticFailure("parse_invalid", {"surface": "source_package"})
        source_events, collection_rule = select_rule(
            vm, ldb, ldb["source_collection_phase"], source, source, -1
        )
        consulted_rules.append(collection_rule)
        if not isinstance(source_events, list):
            raise SemanticFailure("parse_invalid", {"surface": "source_collection"})
        rule_steps = 2
        for index, source_event in enumerate(source_events):
            current = source_event
            stage_outputs: dict[str, dict[str, Any]] = {}
            for phase in ldb["compiler_pipeline"]:
                rule_steps += 1
                if rule_steps > kernel["limits"]["max_rule_steps"]:
                    raise SemanticFailure(
                        "compile_resource_exhausted", {"resource": "rule_steps"}
                    )
                current, rule_id = select_rule(vm, ldb, phase, current, source, index)
                consulted_rules.append(rule_id)
                stage_outputs[phase] = copy.deepcopy(current)
            ast.append(stage_outputs[ldb["compiler_artifacts"]["ast"]])
            hir.append(stage_outputs[ldb["compiler_artifacts"]["typed_hir"]])
            lowered.append(stage_outputs[ldb["compiler_artifacts"]["rir"]])
    except (KeyError, TypeError, SemanticFailure) as error:
        failure = (
            error
            if isinstance(error, SemanticFailure)
            else SemanticFailure("parse_invalid", {})
        )
        return {
            "status": "refused",
            "diagnostic": semantic_diagnostic(
                kernel,
                ldb,
                failure,
                {"kind": "source", "value": source.get("artifact_kind", "source")},
            ),
            "consulted_kernel_laws": sorted(set(vm.consulted_laws)),
            "consulted_ldb_rules": consulted_rules,
            "implementation": IMPLEMENTATION,
        }
    package = package_selection["release"]
    operation_table = {
        name: copy.deepcopy(ldb["operations"][name]) for name in package["operations"]
    }
    lock_payload = {
        "artifact_kind": "package-lock",
        "package": source["package"],
        "release": package,
    }
    lock = {"payload": lock_payload, "identity": content_identity("lock", lock_payload)}
    rir_payload = {
        "artifact_kind": "rir-semantic-payload",
        "events": lowered,
        "operation_table": operation_table,
        "package": source["package"],
        "runtime_profile_definition": copy.deepcopy(
            ldb["runtime_profiles"][ldb["default_runtime_profile"]]
        ),
        "diagnostics": copy.deepcopy(ldb["diagnostics"]),
        "reason_diagnostics": copy.deepcopy(ldb["reason_diagnostics"]),
        "comparison_policy": copy.deepcopy(ldb["comparison_policy"]),
    }
    rir = {"payload": rir_payload, "identity": content_identity("rir", rir_payload)}
    resolved_payload = {
        "artifact_kind": "resolved-model",
        "kernel_identity": admission["kernel_identity"],
        "ldb_identity": admission["ldb_identity"],
        "lock_identity": lock["identity"],
        "rir_identity": rir["identity"],
    }
    resolved_model = {
        "payload": resolved_payload,
        "identity": content_identity("resolved-model", resolved_payload),
    }
    debug_payload = {
        "artifact_kind": "debug-map",
        "source_identity": content_identity("source", source),
        "ast": ast,
        "implementation": IMPLEMENTATION,
    }
    return {
        "status": "compiled",
        "ast": ast,
        "typed_hir": hir,
        "package_lock": lock,
        "rir": rir,
        "resolved_model": resolved_model,
        "debug_map": {
            "payload": debug_payload,
            "identity": content_identity("debug-map", debug_payload),
        },
        "consulted_kernel_laws": sorted(set(vm.consulted_laws)),
        "consulted_ldb_rules": sorted(set(consulted_rules)),
        "implementation": IMPLEMENTATION,
    }


class Transaction:
    def __init__(self, snapshot: dict[str, Any], rng: dict[str, int]) -> None:
        self.snapshot = copy.deepcopy(snapshot)
        self.rng_before = copy.deepcopy(rng)
        self.rng_after = copy.deepcopy(rng)
        self.writes: dict[str, Any] = {}
        self.metrics: list[dict[str, Any]] = []
        self.signals: list[dict[str, Any]] = []
        self.children: list[dict[str, Any]] = []
        self.draws: list[dict[str, Any]] = []


def get_path(value: dict[str, Any], raw_path: str) -> Any:
    current: Any = value
    for part in raw_path.split("."):
        current = current[part]
    return copy.deepcopy(current)


def seal_run(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result["run_identity"] = content_identity("evaluation-run", payload)
    return result


def seal_comparison(
    *,
    admission: dict[str, Any],
    policy: dict[str, Any],
    left: dict[str, Any],
    right: dict[str, Any],
    left_profile: dict[str, Any],
    right_profile: dict[str, Any],
    experiment: dict[str, Any],
    scenario: dict[str, Any],
    artifact_kind: str,
    matches: bool,
    consulted_laws: list[str],
) -> dict[str, Any]:
    payload = {
        "artifact_kind": artifact_kind,
        "kernel_identity": admission["kernel_identity"],
        "ldb_identity": admission["ldb_identity"],
        "left_run_identity": left["run_identity"],
        "right_run_identity": right["run_identity"],
        "left_profile_identity": left_profile["identity"],
        "right_profile_identity": right_profile["identity"],
        "left_resolved_model_identity": left_profile["payload"][
            "resolved_model_identity"
        ],
        "right_resolved_model_identity": right_profile["payload"][
            "resolved_model_identity"
        ],
        "experiment_identity": content_identity("experiment", experiment),
        "scenario_identity": content_identity("scenario", scenario),
        "policy_identity": content_identity("comparison-policy", policy),
        "portable_fields": copy.deepcopy(policy["portable_fields"]),
        "matches": matches,
        "consulted_kernel_laws": sorted(set(consulted_laws)),
        "producer": IMPLEMENTATION,
    }
    return {
        "status": "completed",
        "artifact_kind": artifact_kind,
        "matches": matches,
        "consulted_kernel_laws": sorted(set(consulted_laws)),
        "payload": payload,
        "identity": content_identity("comparison-artifact", payload),
        "implementation": IMPLEMENTATION,
    }


def evaluate_model(request: dict[str, Any]) -> dict[str, Any]:
    admission = admit(request["kernel"], request["ldb"])
    if not admission["admitted"]:
        return {
            "status": "refused",
            "diagnostic": admission["diagnostic"],
            "implementation": IMPLEMENTATION,
        }
    kernel = artifact_payload(request["kernel"])
    ldb = artifact_payload(request["ldb"])
    rir = request["rir"]
    resolved = request["resolved_model"]
    if not isinstance(rir.get("payload"), dict) or rir.get(
        "identity"
    ) != content_identity("rir", rir.get("payload")):
        return {
            "status": "refused",
            "diagnostic": kernel_diagnostic(
                kernel, "identity_mismatch", {"artifact": "rir"}
            ),
            "implementation": IMPLEMENTATION,
        }
    if (
        not isinstance(resolved.get("payload"), dict)
        or resolved.get("identity")
        != content_identity("resolved-model", resolved.get("payload"))
        or resolved["payload"].get("rir_identity") != rir["identity"]
        or resolved["payload"].get("kernel_identity") != admission["kernel_identity"]
        or resolved["payload"].get("ldb_identity") != admission["ldb_identity"]
    ):
        return {
            "status": "refused",
            "diagnostic": kernel_diagnostic(
                kernel, "identity_mismatch", {"artifact": "resolved_model"}
            ),
            "implementation": IMPLEMENTATION,
        }
    payload = rir["payload"]
    if payload.get("package") not in ldb["packages"]:
        return {
            "status": "refused",
            "diagnostic": ldb_diagnostic(
                ldb,
                "operation_projection_mismatch",
                {"surface": "package"},
                {"kind": "artifact", "value": rir["identity"]},
            ),
            "implementation": IMPLEMENTATION,
        }
    package = ldb["packages"][payload["package"]]
    expected_ops = {name: ldb["operations"][name] for name in package["operations"]}
    if payload.get("operation_table") != expected_ops:
        return {
            "status": "refused",
            "diagnostic": ldb_diagnostic(
                ldb,
                "operation_projection_mismatch",
                {},
                {"kind": "artifact", "value": rir["identity"]},
            ),
            "implementation": IMPLEMENTATION,
        }
    expected_runtime_profile = ldb["runtime_profiles"][ldb["default_runtime_profile"]]
    if (
        payload.get("runtime_profile_definition") != expected_runtime_profile
        or payload.get("diagnostics") != ldb["diagnostics"]
        or payload.get("reason_diagnostics") != ldb["reason_diagnostics"]
        or payload.get("comparison_policy") != ldb["comparison_policy"]
    ):
        return {
            "status": "refused",
            "diagnostic": ldb_diagnostic(
                ldb,
                "runtime_profile_projection_mismatch",
                {},
                {"kind": "artifact", "value": rir["identity"]},
            ),
            "implementation": IMPLEMENTATION,
        }
    profile = request["resolved_profile"]
    if not isinstance(profile.get("payload"), dict) or profile.get(
        "identity"
    ) != content_identity("resolved-profile", profile.get("payload")):
        return {
            "status": "refused",
            "diagnostic": kernel_diagnostic(
                kernel, "identity_mismatch", {"artifact": "resolved_profile"}
            ),
            "implementation": IMPLEMENTATION,
        }
    profile_payload = profile["payload"]
    if (
        set(profile_payload)
        != {
            "artifact_kind",
            "definition_identity",
            "evaluator",
            "kernel_identity",
            "ldb_identity",
            "resolved_model_identity",
        }
        or profile_payload.get("artifact_kind") != "resolved-runtime-profile"
        or profile_payload.get("definition_identity")
        != content_identity("runtime-profile-definition", expected_runtime_profile)
        or profile_payload.get("kernel_identity") != admission["kernel_identity"]
        or profile_payload.get("ldb_identity") != admission["ldb_identity"]
        or profile_payload.get("resolved_model_identity") != resolved["identity"]
        or profile_payload.get("evaluator") != IMPLEMENTATION
    ):
        return {
            "status": "refused",
            "diagnostic": ldb_diagnostic(
                ldb,
                "profile_mismatch",
                {},
                {"kind": "artifact", "value": profile["identity"]},
            ),
            "implementation": IMPLEMENTATION,
        }
    runtime_profile = expected_runtime_profile
    scenario = request["scenario"]
    experiment = request["experiment"]
    state = copy.deepcopy(scenario["initial_state"])
    rng_states: dict[str, int] = {}
    queue = copy.deepcopy(payload["events"])
    next_sequence = max((event["sequence"] for event in queue), default=-1) + 1
    trace: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    all_draws: list[dict[str, Any]] = []
    consulted: list[str] = []
    committed_snapshots: list[dict[str, Any]] = [copy.deepcopy(state)]
    events_dispatched = 0
    while queue:
        scheduling_vm = VM(kernel)
        try:
            queue.sort(
                key=lambda event: scheduling_vm.run_law(
                    "scheduler.key",
                    {"event": event, "phase_order": runtime_profile["phase_order"]},
                )
            )
        except SemanticFailure as failure:
            return {
                "status": "refused",
                "diagnostic": semantic_diagnostic(
                    kernel, ldb, failure, {"kind": "artifact", "value": rir["identity"]}
                ),
                "implementation": IMPLEMENTATION,
            }
        consulted.extend(scheduling_vm.consulted_laws)
        event = queue.pop(0)
        events_dispatched += 1
        transaction = Transaction(state, rng_states)
        event_vm: VM

        def effect_handler(kind: str, arguments: dict[str, Any]) -> Any:
            if kind not in runtime_profile["allowed_effects"]:
                raise SemanticFailure("effect_not_allowed", {"effect": kind})
            definition = kernel["effect_kinds"].get(kind)
            if not isinstance(definition, dict):
                raise SemanticFailure("effect_not_allowed", {"effect": kind})
            intent = event_vm.run_law(definition["law"], arguments)
            disposition = intent["disposition"]
            if disposition == "read_snapshot":
                return get_path(transaction.snapshot, intent["path"])
            if disposition == "buffer_write":
                transaction.writes = event_vm.run_law(
                    "transaction.accept_write",
                    {
                        "writes": transaction.writes,
                        "path": intent["path"],
                        "value": intent["value"],
                    },
                )
                return None
            if disposition == "sample":
                if not event_vm.run_law(
                    "budget.within",
                    {
                        "used": len(all_draws) + len(transaction.draws) + 1,
                        "limit": runtime_profile["budgets"]["max_draws"],
                    },
                ):
                    raise SemanticFailure("rng_draw_budget", {})
                stream = intent["stream"]
                rng_vm = event_vm
                if stream not in transaction.rng_after:
                    transaction.rng_after[stream] = rng_vm.run_law(
                        "rng.seed_stream",
                        {"seed": experiment["seed"], "stream": stream},
                    )
                result = rng_vm.run_law(
                    "rng.bounded",
                    {"state": transaction.rng_after[stream], "bound": intent["bound"]},
                )
                transaction.rng_after[stream] = result["state"]
                transaction.draws.append(
                    {
                        "stream": stream,
                        "candidate": result["candidate"],
                        "accepted": result["accepted"],
                        "value": result["value"],
                    }
                )
                return result["value"]
            if disposition == "buffer_metric":
                transaction.metrics.append(
                    {
                        "metric": intent["metric"],
                        "value": copy.deepcopy(intent["value"]),
                    }
                )
                return None
            if disposition == "buffer_signal":
                transaction.signals.append(
                    {
                        "signal": intent["signal"],
                        "value": copy.deepcopy(intent["value"]),
                    }
                )
                return None
            if disposition == "buffer_child":
                child = copy.deepcopy(intent["event"])
                child["sequence"] = next_sequence + len(transaction.children)
                current_vm = event_vm
                child_key = current_vm.run_law(
                    "scheduler.key",
                    {"event": child, "phase_order": runtime_profile["phase_order"]},
                )
                active_key = current_vm.run_law(
                    "scheduler.key",
                    {"event": event, "phase_order": runtime_profile["phase_order"]},
                )
                if not current_vm.run_law(
                    "scheduler.child_allowed",
                    {"child_key": child_key, "active_key": active_key},
                ):
                    raise SemanticFailure("schedule_backward", {"event": child["id"]})
                if not current_vm.run_law(
                    "budget.within",
                    {
                        "used": len(queue) + len(transaction.children) + 1,
                        "limit": runtime_profile["budgets"]["max_queue"],
                    },
                ):
                    raise SemanticFailure(
                        "runtime_resource_exhausted", {"resource": "queue"}
                    )
                transaction.children.append(child)
                return None
            raise SemanticFailure("effect_not_allowed", {"effect": kind})

        event_vm = VM(kernel, effect_handler=effect_handler)
        try:
            if not event_vm.run_law(
                "budget.within",
                {
                    "used": events_dispatched,
                    "limit": runtime_profile["budgets"]["max_events"],
                },
            ):
                raise SemanticFailure(
                    "runtime_resource_exhausted", {"resource": "events"}
                )
            operation = payload["operation_table"][event["operation"]]
            event_vm.evaluate(operation["body"], dict(event["arguments"]))
            next_state = copy.deepcopy(state)
            for path, value in transaction.writes.items():
                next_state = event_vm.run_law(
                    "transition.apply",
                    {"snapshot": next_state, "path": path, "value": value},
                )
        except (KeyError, TypeError, SemanticFailure) as error:
            semantic = (
                error
                if isinstance(error, SemanticFailure)
                else SemanticFailure("operation_projection_mismatch", {})
            )
            consulted.extend(event_vm.consulted_laws)
            diagnostic = semantic_diagnostic(
                kernel, ldb, semantic, {"kind": "event", "value": event["id"]}
            )
            audit = {
                "artifact_kind": "terminal-audit",
                "committed_trace_prefix": trace,
                "last_committed_snapshot": state,
                "refusing_event": event,
                "discarded": {
                    "writes": transaction.writes,
                    "rng_draws": transaction.draws,
                    "signals": transaction.signals,
                    "children": transaction.children,
                },
                "diagnostic": diagnostic,
                "resolved_profile_identity": profile["identity"],
                "resolved_model_identity": resolved["identity"],
            }
            return seal_run(
                {
                    "status": "runtime_refusal",
                    "final_state": state,
                    "metrics": metrics,
                    "signals": signals,
                    "rng_trace": all_draws,
                    "trace": trace,
                    "diagnostic": diagnostic,
                    "terminal_audit": {
                        "payload": audit,
                        "identity": content_identity("terminal-audit", audit),
                    },
                    "resolved_profile_identity": profile["identity"],
                    "reproduction_identity": [
                        admission["kernel_identity"],
                        admission["ldb_identity"],
                        resolved["identity"],
                        profile["identity"],
                        content_identity("experiment", experiment),
                        content_identity("scenario", scenario),
                    ],
                    "consulted_kernel_laws": sorted(set(consulted)),
                    "implementation": IMPLEMENTATION,
                }
            )
        state = next_state
        rng_states = transaction.rng_after
        metrics.extend(transaction.metrics)
        signals.extend(transaction.signals)
        all_draws.extend(transaction.draws)
        queue.extend(transaction.children)
        next_sequence += len(transaction.children)
        trace.append(
            {
                "event": event["id"],
                "state": copy.deepcopy(state),
                "metrics": copy.deepcopy(transaction.metrics),
                "signals": copy.deepcopy(transaction.signals),
            }
        )
        committed_snapshots.append(copy.deepcopy(state))
        consulted.extend(event_vm.consulted_laws)
    return seal_run(
        {
            "status": "completed",
            "final_state": state,
            "metrics": metrics,
            "signals": signals,
            "rng_trace": all_draws,
            "trace": trace,
            "diagnostic": None,
            "resolved_profile_identity": profile["identity"],
            "reproduction_identity": [
                admission["kernel_identity"],
                admission["ldb_identity"],
                resolved["identity"],
                profile["identity"],
                content_identity("experiment", experiment),
                content_identity("scenario", scenario),
            ],
            "consulted_kernel_laws": sorted(set(consulted)),
            "implementation": IMPLEMENTATION,
        }
    )


def compare_runs(request: dict[str, Any], cross: bool) -> dict[str, Any]:
    admission = admit(request["kernel"], request["ldb"])
    if not admission["admitted"]:
        return {
            "status": "refused",
            "diagnostic": admission["diagnostic"],
            "implementation": IMPLEMENTATION,
        }
    kernel = artifact_payload(request["kernel"])
    ldb = artifact_payload(request["ldb"])
    left = request["left"]
    right = request["right"]
    left_profile = request["left_profile"]
    right_profile = request["right_profile"]
    reason = "cross_authority_mismatch" if cross else "replay_profile_mismatch"
    expected_definition_identity = content_identity(
        "runtime-profile-definition",
        ldb["runtime_profiles"][ldb["default_runtime_profile"]],
    )
    profile_fields = {
        "artifact_kind",
        "definition_identity",
        "evaluator",
        "kernel_identity",
        "ldb_identity",
        "resolved_model_identity",
    }
    for run, profile in ((left, left_profile), (right, right_profile)):
        run_payload = {
            key: value for key, value in run.items() if key != "run_identity"
        }
        if run.get("run_identity") != content_identity("evaluation-run", run_payload):
            return {
                "status": "refused",
                "diagnostic": ldb_diagnostic(
                    ldb,
                    reason,
                    {"artifact": "run"},
                    {"kind": "artifact", "value": "comparison"},
                ),
                "implementation": IMPLEMENTATION,
            }
        profile_payload = profile.get("payload")
        if (
            not isinstance(profile_payload, dict)
            or set(profile_payload) != profile_fields
            or profile.get("identity")
            != content_identity("resolved-profile", profile_payload)
            or run.get("resolved_profile_identity") != profile.get("identity")
            or profile_payload.get("artifact_kind") != "resolved-runtime-profile"
            or profile_payload.get("definition_identity")
            != expected_definition_identity
            or profile_payload.get("evaluator") != run.get("implementation")
        ):
            return {
                "status": "refused",
                "diagnostic": ldb_diagnostic(
                    ldb,
                    reason,
                    {"artifact": "profile"},
                    {"kind": "artifact", "value": "comparison"},
                ),
                "implementation": IMPLEMENTATION,
            }
        reproduction = run.get("reproduction_identity", [])
        expected = [
            admission["kernel_identity"],
            admission["ldb_identity"],
            profile_payload.get("resolved_model_identity"),
            profile["identity"],
            content_identity("experiment", request["experiment"]),
            content_identity("scenario", request["scenario"]),
        ]
        if (
            reproduction != expected
            or profile_payload.get("kernel_identity") != admission["kernel_identity"]
            or profile_payload.get("ldb_identity") != admission["ldb_identity"]
        ):
            return {
                "status": "refused",
                "diagnostic": ldb_diagnostic(
                    ldb,
                    reason,
                    {"artifact": "binding"},
                    {"kind": "artifact", "value": "comparison"},
                ),
                "implementation": IMPLEMENTATION,
            }
    policy = ldb["comparison_policy"]
    fields = policy["portable_fields"]
    vm = VM(kernel)
    if not cross:
        try:
            compatible = vm.run_law(
                "comparison.replay_compatible",
                {
                    "left_profile": left["resolved_profile_identity"],
                    "right_profile": right["resolved_profile_identity"],
                },
            )
        except SemanticFailure as failure:
            return {
                "status": "refused",
                "diagnostic": semantic_diagnostic(
                    kernel, ldb, failure, {"kind": "artifact", "value": "comparison"}
                ),
                "implementation": IMPLEMENTATION,
                "consulted_kernel_laws": vm.consulted_laws,
            }
        if (
            not compatible
            or left["reproduction_identity"] != right["reproduction_identity"]
        ):
            return {
                "status": "refused",
                "diagnostic": ldb_diagnostic(
                    ldb,
                    "replay_profile_mismatch",
                    {},
                    {"kind": "artifact", "value": "comparison"},
                ),
                "implementation": IMPLEMENTATION,
                "consulted_kernel_laws": vm.consulted_laws,
            }
        matches = all(left.get(field) == right.get(field) for field in fields)
        return seal_comparison(
            admission=admission,
            policy=policy,
            left=left,
            right=right,
            left_profile=left_profile,
            right_profile=right_profile,
            experiment=request["experiment"],
            scenario=request["scenario"],
            artifact_kind=policy["replay_artifact_kind"],
            matches=matches,
            consulted_laws=vm.consulted_laws,
        )
    common_left = [
        item for index, item in enumerate(left["reproduction_identity"]) if index != 3
    ]
    common_right = [
        item for index, item in enumerate(right["reproduction_identity"]) if index != 3
    ]
    if (
        left["resolved_profile_identity"] == right["resolved_profile_identity"]
        or common_left != common_right
    ):
        return {
            "status": "refused",
            "diagnostic": ldb_diagnostic(
                ldb,
                "cross_authority_mismatch",
                {},
                {"kind": "artifact", "value": "comparison"},
            ),
            "implementation": IMPLEMENTATION,
        }
    matches = all(left.get(field) == right.get(field) for field in fields)
    return seal_comparison(
        admission=admission,
        policy=policy,
        left=left,
        right=right,
        left_profile=left_profile,
        right_profile=right_profile,
        experiment=request["experiment"],
        scenario=request["scenario"],
        artifact_kind=policy["cross_artifact_kind"],
        matches=matches,
        consulted_laws=[],
    )


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    command = request.get("command")
    if command == "bootstrap":
        return admit(request["kernel"], request["ldb"])
    if command == "compile":
        return compile_model(request)
    if command == "evaluate":
        return evaluate_model(request)
    if command == "compare_replay":
        return compare_runs(request, False)
    if command == "compare_cross":
        return compare_runs(request, True)
    return {"status": "internal_error", "implementation": IMPLEMENTATION}


if __name__ == "__main__":
    try:
        response = dispatch(json.load(sys.stdin))
    except Exception as error:  # pragma: no cover - surfaced by the gate as failure
        response = {
            "status": "internal_error",
            "implementation": IMPLEMENTATION,
            "exception": type(error).__name__,
            "detail": str(error),
        }
    sys.stdout.write(
        json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
