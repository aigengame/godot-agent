"""Evaluator B: separately implemented kernel-machine and RNG mapping.

This file does not import evaluator A or any shared semantic helper.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from typing import Any

from canonical import artifact, clone, identity


class StopB(Exception):
    def __init__(self, diagnostic: str, subject: str) -> None:
        super().__init__(diagnostic)
        self.diagnostic = diagnostic
        self.subject = subject


class EvaluatorB:
    implementation = "evaluator-b-environment-v1"

    def run(
        self,
        kernel: dict[str, Any],
        bundle: dict[str, Any],
        package_lock: dict[str, Any],
        rir: dict[str, Any],
        profile: dict[str, Any],
        scenario: dict[str, Any],
    ) -> dict[str, Any]:
        self.ks = kernel
        self.ldb = bundle
        self.lock = package_lock
        self.limits = clone(profile)
        self.before = clone(scenario["initial_state"])
        self.working = clone(self.before)
        self.pending_writes: dict[str, Any] = {}
        self.observations: list[dict[str, Any]] = []
        self.random_observations: list[dict[str, Any]] = []
        self.stream_positions: dict[str, int] = {}
        self.random_uses = 0
        self.fuel = 0
        self.seed_value = scenario["seed"]
        self.programs: dict[str, dict[str, Any]] = {}
        for program in rir["operations"]:
            self.programs[program["id"]] = program
        definition = dict(profile)
        self.budget_values = clone(definition.pop("concrete_budgets", {}))
        semantic_profile = identity("runtime-profile-definition", definition)
        resolved_profile = artifact(
            "resolved-runtime-profile",
            {
                "semantic_profile": semantic_profile,
                "evaluator": self.implementation,
                "kernel": kernel["identity"],
                "language_bundle": bundle["identity"],
                "package_lock": package_lock["identity"],
                "rir": rir["identity"],
                "platform": {
                    "implementation": sys.implementation.name,
                    "python": platform.python_version(),
                    "system": sys.platform,
                    "machine": platform.machine(),
                },
                "primitive_implementation": "environment-python-separate-v1",
                "numeric": profile["numeric_profile"],
                "rng": profile["rng_profile"],
                "concrete_budgets": self.budget_values,
            },
        )
        try:
            self._profile_check(rir)
            entry = rir["entries"][0]
            returned = self._call(entry["operation"], clone(entry["arguments"]))
            if (
                type(returned) is dict
                and set(returned) == {"tag", "fields"}
                and type(returned["tag"]) is str
                and type(returned["fields"]) is dict
            ):
                outcome = str(returned["tag"])
                payload = clone(returned["fields"])
            else:
                raise StopB("runtime.outcome-invalid", "entry")
            self._commit_pending()
            run = artifact(
                "evaluation-run",
                {
                    "status": "completed",
                    "rir": rir["identity"],
                    "scenario": scenario["id"],
                    "evaluator": self.implementation,
                    "resolved_runtime_profile": resolved_profile["identity"],
                    "semantic_runtime_profile": semantic_profile,
                    "outcome": outcome,
                    "payload": payload,
                    "initial_state": self.before,
                    "final_state": self.working,
                    "metrics": self.observations,
                    "rng_trace": self.random_observations,
                    "committed_writes": [
                        {"path": path, "value": self.pending_writes[path]}
                        for path in sorted(self.pending_writes)
                    ],
                    "steps": self.fuel,
                },
            )
            return {"status": "completed", "run": run, "profile": resolved_profile}
        except StopB as stopped:
            self.working = clone(self.before)
            terminal = artifact(
                "terminal-audit",
                {
                    "status": "refused",
                    "rir": rir["identity"],
                    "scenario": scenario["id"],
                    "evaluator": self.implementation,
                    "resolved_runtime_profile": resolved_profile["identity"],
                    "diagnostic": {
                        "code": stopped.diagnostic,
                        "detail": stopped.subject,
                    },
                    "rolled_back_state": self.working,
                    "attempted_metrics": self.observations,
                    "rng_trace": self.random_observations,
                    "discarded_writes": [
                        {"path": path, "value": self.pending_writes[path]}
                        for path in sorted(self.pending_writes)
                    ],
                    "steps": self.fuel,
                },
            )
            return {
                "status": "refused",
                "terminal_audit": terminal,
                "profile": resolved_profile,
            }

    def _profile_check(self, rir: dict[str, Any]) -> None:
        kernel_material: dict[str, Any] = {}
        for key, value in self.ks.items():
            if key != "identity":
                kernel_material[key] = value
        if identity("kernel", kernel_material) != self.ks.get("identity"):
            raise StopB("runtime.kernel-identity-invalid", "kernel")
        rir_payload = {key: value for key, value in rir.items() if key != "identity"}
        if identity("resolved-model", rir_payload) != rir.get("identity"):
            raise StopB("runtime.rir-identity-invalid", "rir")
        bundle_payload = {
            key: value for key, value in self.ldb.items() if key != "identity"
        }
        if identity("ldb", bundle_payload) != self.ldb.get("identity"):
            raise StopB("runtime.bundle-identity-invalid", "language_bundle")
        lock_payload = {
            key: value for key, value in self.lock.items() if key != "identity"
        }
        if identity("package-lock", lock_payload) != self.lock.get("identity"):
            raise StopB("runtime.package-lock-identity-invalid", "package_lock")
        if rir.get("kernel") != self.ks.get("identity"):
            raise StopB("runtime.kernel-binding-mismatch", "rir")
        if rir.get("language_bundle") != self.ldb.get("identity"):
            raise StopB("runtime.bundle-binding-mismatch", "rir")
        if rir.get("package_lock") != self.lock.get("identity"):
            raise StopB("runtime.package-lock-binding-mismatch", "rir")
        if self.lock.get("kernel") != self.ks.get("identity"):
            raise StopB("runtime.kernel-binding-mismatch", "package_lock")
        if self.lock.get("language_bundle") != self.ldb.get("identity"):
            raise StopB("runtime.bundle-binding-mismatch", "package_lock")
        candidates: list[dict[str, Any]] = []
        for fact in self.ldb.get("facts", []):
            if fact.get("kind") == "runtime_profile" and fact.get(
                "id"
            ) == self.limits.get("id"):
                candidates.append(fact)
        selected_definition = dict(self.limits)
        selected_definition.pop("concrete_budgets", None)
        if len(candidates) != 1 or candidates[0] != selected_definition:
            raise StopB(
                "runtime.profile-definition-mismatch", str(self.limits.get("id"))
            )
        if rir.get("runtime_profile") != self.limits.get("id"):
            raise StopB("runtime.profile-binding-mismatch", "rir")
        if set(self.budget_values) != {"max_draws", "max_steps"}:
            raise StopB("runtime.budget-invalid", "shape")
        for budget_name in ("max_draws", "max_steps"):
            budget_value = self.budget_values[budget_name]
            if (
                type(budget_value) is not int
                or budget_value < 0
                or budget_value > selected_definition[budget_name]
            ):
                raise StopB("runtime.budget-invalid", budget_name)
        if (
            type(self.seed_value) is not int
            or self.seed_value < 0
            or self.seed_value >= 1 << 64
        ):
            raise StopB("runtime.rng-seed-invalid", str(self.seed_value))
        if self.limits.get("numeric_profile") != self.ks["numeric"].get("profile"):
            raise StopB("runtime.profile-incompatible", "numeric")
        if self.limits.get("rng_profile") != self.ks["rng"].get("profile"):
            raise StopB("runtime.profile-incompatible", "rng")
        permitted = dict.fromkeys(self.limits["allowed_effects"])
        for program in rir["operations"]:
            for effect in program["effects"]:
                if effect not in permitted:
                    raise StopB("runtime.effect-not-admitted", program["id"])

    def _call(self, program_id: str, supplied: dict[str, Any]) -> Any:
        if program_id not in self.programs:
            raise StopB("runtime.unknown-operation", program_id)
        program = self.programs[program_id]
        if sorted(supplied) != sorted(program["parameters"]):
            raise StopB("runtime.arguments-invalid", program_id)
        for item in supplied.values():
            self._exact(item)
        result = self._walk(program["body"], supplied, {})
        expected_tags = program["result"].split("|")
        if (
            type(result) is not dict
            or set(result) != {"tag", "fields"}
            or type(result["tag"]) is not str
            or type(result["fields"]) is not dict
        ):
            raise StopB("runtime.outcome-payload-invalid", program_id)
        if result["tag"] not in expected_tags:
            raise StopB("runtime.outcome-tag-invalid", str(result["tag"]))
        return result

    def _walk(
        self,
        term: dict[str, Any],
        supplied: dict[str, Any],
        environment: dict[str, Any],
    ) -> Any:
        self.fuel += 1
        if self.fuel > self.budget_values["max_steps"]:
            raise StopB("runtime.limit-exceeded", "steps")
        form = term.get("node")
        if form in ("literal", "arg", "local"):
            if form == "literal":
                return clone(term["value"])
            if form == "arg":
                return supplied[term["name"]]
            return environment[term["name"]]
        if form == "state_read":
            cursor: Any = self.before
            for component in term["path"].split("."):
                if type(cursor) is not dict or component not in cursor:
                    raise StopB("runtime.state-path-missing", term["path"])
                cursor = cursor[component]
            return clone(cursor)
        if form == "calculate":
            operands: list[Any] = []
            for operand in term["arguments"]:
                operands.append(self._walk(operand, supplied, environment))
            name = term["operator"]
            if name == "gte_int":
                return self._exact(operands[0]) >= self._exact(operands[1])
            if name == "add_int":
                answer = self._exact(operands[0]) + self._exact(operands[1])
                return self._exact(answer)
            if name == "sub_int":
                answer = self._exact(operands[0]) - self._exact(operands[1])
                return self._exact(answer)
            raise StopB("runtime.unknown-primitive", str(name))
        if form == "let":
            bound = self._walk(term["value"], supplied, environment)
            child_environment = {key: value for key, value in environment.items()}
            child_environment[term["name"]] = bound
            return self._walk(term["then"], supplied, child_environment)
        if form == "if":
            predicate = self._walk(term["condition"], supplied, environment)
            if type(predicate) is not bool:
                raise StopB("runtime.condition-not-bool", "if")
            selected = term["then"] if predicate is True else term["else"]
            return self._walk(selected, supplied, environment)
        if form in ("record", "variant"):
            result_fields: dict[str, Any] = {}
            for name in sorted(term["fields"]):
                result_fields[name] = self._walk(
                    term["fields"][name], supplied, environment
                )
            if form == "record":
                return result_fields
            return {"tag": term["tag"], "fields": result_fields}
        if form == "field":
            record = self._walk(term["value"], supplied, environment)
            if type(record) is not dict or term["field"] not in record:
                raise StopB("runtime.field-missing", term["field"])
            return record[term["field"]]
        if form == "call":
            next_arguments: dict[str, Any] = {}
            for name in term["arguments"]:
                next_arguments[name] = self._walk(
                    term["arguments"][name], supplied, environment
                )
            return self._call(term["operation"], next_arguments)
        if form == "match":
            discriminant = self._walk(term["value"], supplied, environment)
            if type(discriminant) is not dict or set(discriminant) != {"tag", "fields"}:
                raise StopB("runtime.match-not-variant", "match")
            if discriminant["tag"] not in term["cases"]:
                raise StopB("runtime.match-non-exhaustive", str(discriminant["tag"]))
            arm = term["cases"][discriminant["tag"]]
            arm_environment = dict(environment)
            arm_environment[arm["bind"]] = discriminant["fields"]
            return self._walk(arm["body"], supplied, arm_environment)
        if form == "sample_bounded":
            ceiling = self._exact(self._walk(term["bound"], supplied, environment))
            return self._random(term["stream"], ceiling)
        if form == "transition_set":
            replacement = self._walk(term["value"], supplied, environment)
            if term["path"] in self.pending_writes:
                raise StopB("runtime.duplicate-state-write", term["path"])
            components = term["path"].split(".")
            owner = self.before
            for component in components[:-1]:
                if component not in owner or type(owner[component]) is not dict:
                    raise StopB("runtime.state-path-missing", term["path"])
                owner = owner[component]
            if components[-1] not in owner:
                raise StopB("runtime.state-path-missing", term["path"])
            self.pending_writes[term["path"]] = clone(replacement)
            return replacement
        if form == "emit_metric":
            observed = self._walk(term["value"], supplied, environment)
            self.observations.append({"metric": term["metric"], "value": observed})
            return observed
        if form == "sequence":
            last: Any = None
            for child in term["items"]:
                last = self._walk(child, supplied, environment)
            return last
        raise StopB("runtime.unknown-primitive", str(form))

    def _random(self, stream_name: str, upper_bound: int) -> int:
        if stream_name not in dict.fromkeys(self.limits["allowed_streams"]):
            raise StopB("runtime.stream-not-admitted", stream_name)
        if upper_bound < 1 or upper_bound > (1 << 64):
            raise StopB("runtime.rng-bound-invalid", str(upper_bound))
        acceptance_ceiling = (1 << 64) - ((1 << 64) % upper_bound)
        while True:
            if self.random_uses >= self.budget_values["max_draws"]:
                raise StopB("runtime.limit-exceeded", "draws")
            position = self.stream_positions.get(stream_name, 0)
            if position >= 1 << 64:
                raise StopB("runtime.rng-counter-overflow", stream_name)
            encoded_stream = stream_name.encode("utf-8")
            message = bytearray.fromhex(self.ks["rng"]["domain_prefix_hex"])
            message.extend(
                int(self.seed_value).to_bytes(8, byteorder="big", signed=False)
            )
            message.extend(
                len(encoded_stream).to_bytes(2, byteorder="big", signed=False)
            )
            message.extend(encoded_stream)
            message.extend(position.to_bytes(8, byteorder="big", signed=False))
            first_eight = hashlib.sha256(bytes(message)).digest()[0:8]
            candidate = 0
            for octet in first_eight:
                candidate = candidate * 256 + octet
            self.stream_positions[stream_name] = position + 1
            self.random_uses += 1
            accepted = candidate < acceptance_ceiling
            self.random_observations.append(
                {
                    "accepted": accepted,
                    "candidate": candidate,
                    "counter": position,
                    "stream": stream_name,
                }
            )
            if accepted:
                return candidate % upper_bound

    def _exact(self, candidate: Any) -> int:
        if type(candidate) is not int:
            raise StopB("runtime.numeric-type-invalid", type(candidate).__name__)
        lower = self.ks["numeric"]["minimum"]
        upper = self.ks["numeric"]["maximum"]
        if candidate < lower or candidate > upper:
            raise StopB("runtime.numeric-overflow", str(candidate))
        return candidate

    def _commit_pending(self) -> None:
        self.working = clone(self.before)
        for path in sorted(self.pending_writes):
            components = path.split(".")
            owner = self.working
            for component in components[:-1]:
                owner = owner[component]
            owner[components[-1]] = clone(self.pending_writes[path])
