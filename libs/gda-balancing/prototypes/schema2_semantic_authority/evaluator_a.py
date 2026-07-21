"""Evaluator A: recursive kernel-machine implementation.

It has no RPG/domain dispatch.  Domain operation ids only select LDB-authored programs;
all observable behavior is composed from closed Kernel Specification nodes.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from typing import Any

from canonical import artifact, clone, identity


class RefusalA(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


class EvaluatorA:
    implementation = "evaluator-a-recursive-v1"

    def run(
        self,
        kernel: dict[str, Any],
        bundle: dict[str, Any],
        package_lock: dict[str, Any],
        rir: dict[str, Any],
        profile: dict[str, Any],
        scenario: dict[str, Any],
    ) -> dict[str, Any]:
        self.kernel = kernel
        self.bundle = bundle
        self.package_lock = package_lock
        self.profile = clone(profile)
        self.initial_state = clone(scenario["initial_state"])
        self.snapshot = clone(self.initial_state)
        self.state = clone(self.initial_state)
        self.write_buffer: dict[str, Any] = {}
        self.metrics: list[dict[str, Any]] = []
        self.rng_trace: list[dict[str, Any]] = []
        self.counters: dict[str, int] = {}
        self.draws = 0
        self.steps = 0
        self.seed = scenario["seed"]
        self.operations = {
            operation["id"]: operation for operation in rir["operations"]
        }
        profile_definition = {
            key: value for key, value in profile.items() if key != "concrete_budgets"
        }
        self.budgets = clone(profile.get("concrete_budgets", {}))
        self.semantic_profile_identity = identity(
            "runtime-profile-definition", profile_definition
        )
        self.resolved_profile = artifact(
            "resolved-runtime-profile",
            {
                "semantic_profile": self.semantic_profile_identity,
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
                "primitive_implementation": "recursive-python-separate-v1",
                "numeric": profile["numeric_profile"],
                "rng": profile["rng_profile"],
                "concrete_budgets": self.budgets,
            },
        )
        try:
            self._admit_runtime(rir)
            entry = rir["entries"][0]
            value = self._invoke(entry["operation"], clone(entry["arguments"]))
            outcome, payload = self._outcome(value)
            self._commit_writes()
            run = artifact(
                "evaluation-run",
                {
                    "status": "completed",
                    "rir": rir["identity"],
                    "scenario": scenario["id"],
                    "evaluator": self.implementation,
                    "resolved_runtime_profile": self.resolved_profile["identity"],
                    "semantic_runtime_profile": self.semantic_profile_identity,
                    "outcome": outcome,
                    "payload": payload,
                    "initial_state": self.initial_state,
                    "final_state": self.state,
                    "metrics": self.metrics,
                    "rng_trace": self.rng_trace,
                    "committed_writes": [
                        {"path": path, "value": self.write_buffer[path]}
                        for path in sorted(self.write_buffer)
                    ],
                    "steps": self.steps,
                },
            )
            return {"status": "completed", "run": run, "profile": self.resolved_profile}
        except RefusalA as refusal:
            self.state = clone(self.initial_state)
            audit = artifact(
                "terminal-audit",
                {
                    "status": "refused",
                    "rir": rir["identity"],
                    "scenario": scenario["id"],
                    "evaluator": self.implementation,
                    "resolved_runtime_profile": self.resolved_profile["identity"],
                    "diagnostic": {"code": refusal.code, "detail": refusal.detail},
                    "rolled_back_state": self.state,
                    "attempted_metrics": self.metrics,
                    "rng_trace": self.rng_trace,
                    "discarded_writes": [
                        {"path": path, "value": self.write_buffer[path]}
                        for path in sorted(self.write_buffer)
                    ],
                    "steps": self.steps,
                },
            )
            return {
                "status": "refused",
                "terminal_audit": audit,
                "profile": self.resolved_profile,
            }

    def _admit_runtime(self, rir: dict[str, Any]) -> None:
        if identity(
            "kernel",
            {key: value for key, value in self.kernel.items() if key != "identity"},
        ) != self.kernel.get("identity"):
            raise RefusalA("runtime.kernel-identity-invalid", "kernel")
        if identity(
            "resolved-model",
            {key: value for key, value in rir.items() if key != "identity"},
        ) != rir.get("identity"):
            raise RefusalA("runtime.rir-identity-invalid", "rir")
        if identity(
            "ldb",
            {key: value for key, value in self.bundle.items() if key != "identity"},
        ) != self.bundle.get("identity"):
            raise RefusalA("runtime.bundle-identity-invalid", "language_bundle")
        if identity(
            "package-lock",
            {
                key: value
                for key, value in self.package_lock.items()
                if key != "identity"
            },
        ) != self.package_lock.get("identity"):
            raise RefusalA("runtime.package-lock-identity-invalid", "package_lock")
        if rir.get("kernel") != self.kernel.get("identity"):
            raise RefusalA("runtime.kernel-binding-mismatch", "rir")
        if rir.get("language_bundle") != self.bundle.get("identity"):
            raise RefusalA("runtime.bundle-binding-mismatch", "rir")
        if rir.get("package_lock") != self.package_lock.get("identity"):
            raise RefusalA("runtime.package-lock-binding-mismatch", "rir")
        if self.package_lock.get("kernel") != self.kernel.get("identity"):
            raise RefusalA("runtime.kernel-binding-mismatch", "package_lock")
        if self.package_lock.get("language_bundle") != self.bundle.get("identity"):
            raise RefusalA("runtime.bundle-binding-mismatch", "package_lock")
        definitions = [
            fact
            for fact in self.bundle.get("facts", [])
            if fact.get("kind") == "runtime_profile"
            and fact.get("id") == self.profile.get("id")
        ]
        profile_definition = {
            key: value
            for key, value in self.profile.items()
            if key != "concrete_budgets"
        }
        if len(definitions) != 1 or definitions[0] != profile_definition:
            raise RefusalA(
                "runtime.profile-definition-mismatch", str(self.profile.get("id"))
            )
        if rir.get("runtime_profile") != self.profile.get("id"):
            raise RefusalA("runtime.profile-binding-mismatch", "rir")
        if set(self.budgets) != {"max_draws", "max_steps"}:
            raise RefusalA("runtime.budget-invalid", "shape")
        for budget in ("max_draws", "max_steps"):
            value = self.budgets[budget]
            if (
                type(value) is not int
                or value < 0
                or value > profile_definition[budget]
            ):
                raise RefusalA("runtime.budget-invalid", budget)
        if type(self.seed) is not int or self.seed < 0 or self.seed > 2**64 - 1:
            raise RefusalA("runtime.rng-seed-invalid", str(self.seed))
        if self.profile["numeric_profile"] != self.kernel["numeric"]["profile"]:
            raise RefusalA("runtime.profile-incompatible", "numeric")
        if self.profile["rng_profile"] != self.kernel["rng"]["profile"]:
            raise RefusalA("runtime.profile-incompatible", "rng")
        allowed = set(self.profile["allowed_effects"])
        for operation in rir["operations"]:
            if not set(operation["effects"]).issubset(allowed):
                raise RefusalA("runtime.effect-not-admitted", operation["id"])

    def _invoke(self, operation_name: str, arguments: dict[str, Any]) -> Any:
        operation = self.operations.get(operation_name)
        if operation is None:
            raise RefusalA("runtime.unknown-operation", operation_name)
        if set(arguments) != set(operation["parameters"]):
            raise RefusalA("runtime.arguments-invalid", operation_name)
        for value in arguments.values():
            self._integer(value)
        result = self._evaluate(operation["body"], arguments, {})
        variants = operation["result"].split("|")
        if (
            not isinstance(result, dict)
            or set(result) != {"tag", "fields"}
            or not isinstance(result["tag"], str)
            or not isinstance(result["fields"], dict)
        ):
            raise RefusalA("runtime.outcome-payload-invalid", operation_name)
        if result["tag"] not in variants:
            raise RefusalA("runtime.outcome-tag-invalid", str(result["tag"]))
        return result

    def _evaluate(
        self,
        expression: dict[str, Any],
        arguments: dict[str, Any],
        locals_: dict[str, Any],
    ) -> Any:
        self.steps += 1
        if self.steps > self.budgets["max_steps"]:
            raise RefusalA("runtime.limit-exceeded", "steps")
        node = expression.get("node")
        if node == "literal":
            return clone(expression["value"])
        if node == "arg":
            return arguments[expression["name"]]
        if node == "local":
            return locals_[expression["name"]]
        if node == "state_read":
            return self._read_path(expression["path"])
        if node == "calculate":
            values = [
                self._evaluate(item, arguments, locals_)
                for item in expression["arguments"]
            ]
            operator = expression["operator"]
            if operator == "add_int":
                return self._integer(
                    self._integer(values[0]) + self._integer(values[1])
                )
            if operator == "sub_int":
                return self._integer(
                    self._integer(values[0]) - self._integer(values[1])
                )
            if operator == "gte_int":
                return self._integer(values[0]) >= self._integer(values[1])
            raise RefusalA("runtime.unknown-primitive", str(operator))
        if node == "let":
            value = self._evaluate(expression["value"], arguments, locals_)
            nested = dict(locals_)
            nested[expression["name"]] = value
            return self._evaluate(expression["then"], arguments, nested)
        if node == "if":
            condition = self._evaluate(expression["condition"], arguments, locals_)
            if type(condition) is not bool:
                raise RefusalA("runtime.condition-not-bool", "if")
            branch = expression["then"] if condition else expression["else"]
            return self._evaluate(branch, arguments, locals_)
        if node == "variant":
            return {
                "tag": expression["tag"],
                "fields": {
                    name: self._evaluate(child, arguments, locals_)
                    for name, child in sorted(expression["fields"].items())
                },
            }
        if node == "record":
            return {
                name: self._evaluate(child, arguments, locals_)
                for name, child in sorted(expression["fields"].items())
            }
        if node == "field":
            value = self._evaluate(expression["value"], arguments, locals_)
            if not isinstance(value, dict) or expression["field"] not in value:
                raise RefusalA("runtime.field-missing", expression["field"])
            return value[expression["field"]]
        if node == "call":
            call_arguments = {
                name: self._evaluate(child, arguments, locals_)
                for name, child in expression["arguments"].items()
            }
            return self._invoke(expression["operation"], call_arguments)
        if node == "match":
            value = self._evaluate(expression["value"], arguments, locals_)
            if (
                not isinstance(value, dict)
                or "tag" not in value
                or "fields" not in value
            ):
                raise RefusalA("runtime.match-not-variant", "match")
            case = expression["cases"].get(value["tag"])
            if case is None:
                raise RefusalA("runtime.match-non-exhaustive", str(value["tag"]))
            nested = dict(locals_)
            nested[case["bind"]] = value["fields"]
            return self._evaluate(case["body"], arguments, nested)
        if node == "sample_bounded":
            bound = self._integer(
                self._evaluate(expression["bound"], arguments, locals_)
            )
            return self._sample(expression["stream"], bound)
        if node == "transition_set":
            value = self._evaluate(expression["value"], arguments, locals_)
            self._write_path(expression["path"], value)
            return value
        if node == "emit_metric":
            value = self._evaluate(expression["value"], arguments, locals_)
            self.metrics.append({"metric": expression["metric"], "value": value})
            return value
        if node == "sequence":
            value: Any = None
            for item in expression["items"]:
                value = self._evaluate(item, arguments, locals_)
            return value
        raise RefusalA("runtime.unknown-primitive", str(node))

    def _sample(self, stream: str, bound: int) -> int:
        if stream not in self.profile["allowed_streams"]:
            raise RefusalA("runtime.stream-not-admitted", stream)
        if bound <= 0 or bound > 2**64:
            raise RefusalA("runtime.rng-bound-invalid", str(bound))
        threshold = 2**64 - ((2**64) % bound)
        while True:
            if self.draws >= self.budgets["max_draws"]:
                raise RefusalA("runtime.limit-exceeded", "draws")
            counter = self.counters.get(stream, 0)
            if counter > 2**64 - 1:
                raise RefusalA("runtime.rng-counter-overflow", stream)
            stream_bytes = stream.encode("utf-8")
            material = (
                bytes.fromhex(self.kernel["rng"]["domain_prefix_hex"])
                + self.seed.to_bytes(8, "big", signed=False)
                + len(stream_bytes).to_bytes(2, "big")
                + stream_bytes
                + counter.to_bytes(8, "big")
            )
            candidate = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
            self.counters[stream] = counter + 1
            self.draws += 1
            accepted = candidate < threshold
            self.rng_trace.append(
                {
                    "accepted": accepted,
                    "candidate": candidate,
                    "counter": counter,
                    "stream": stream,
                }
            )
            if accepted:
                return candidate % bound

    def _integer(self, value: Any) -> int:
        if type(value) is not int:
            raise RefusalA("runtime.numeric-type-invalid", type(value).__name__)
        if (
            value < self.kernel["numeric"]["minimum"]
            or value > self.kernel["numeric"]["maximum"]
        ):
            raise RefusalA("runtime.numeric-overflow", str(value))
        return value

    def _read_path(self, path: str) -> Any:
        value: Any = self.snapshot
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise RefusalA("runtime.state-path-missing", path)
            value = value[part]
        return clone(value)

    def _write_path(self, path: str, value: Any) -> None:
        if path in self.write_buffer:
            raise RefusalA("runtime.duplicate-state-write", path)
        parts = path.split(".")
        target = self.snapshot
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                raise RefusalA("runtime.state-path-missing", path)
            target = target[part]
        if parts[-1] not in target:
            raise RefusalA("runtime.state-path-missing", path)
        self.write_buffer[path] = clone(value)

    def _commit_writes(self) -> None:
        self.state = clone(self.snapshot)
        for path in sorted(self.write_buffer):
            parts = path.split(".")
            target = self.state
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = clone(self.write_buffer[path])

    @staticmethod
    def _outcome(value: Any) -> tuple[str, dict[str, Any]]:
        if (
            isinstance(value, dict)
            and set(value) == {"tag", "fields"}
            and isinstance(value["tag"], str)
            and isinstance(value["fields"], dict)
        ):
            return value["tag"], clone(value["fields"])
        raise RefusalA("runtime.outcome-invalid", "entry")
