"""Bootstrap interpreter B: table-driven premises and iterative expressions.

No rule-selection, premise, binding, or expression-validation code is shared with A.
"""

from __future__ import annotations

from typing import Any

from canonical import identity


class BootstrapB:
    implementation = "bootstrap-b-stack-v1"

    def admit(self, kernel: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._admit(kernel, bundle)
        except (AttributeError, IndexError, KeyError, TypeError):
            content = (
                {key: value for key, value in bundle.items() if key != "identity"}
                if type(bundle) is dict
                else {}
            )
            return self._finish(
                identity("ldb", content),
                [],
                [],
                [self._error("bundle.malformed-container", "$", "container")],
            )

    def _admit(self, kernel: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        kernel_content: dict[str, Any] = {}
        for key in kernel:
            if key != "identity":
                kernel_content[key] = kernel[key]
        if kernel.get("identity") != identity("kernel", kernel_content):
            errors.append(
                self._error("kernel.identity-mismatch", "$.kernel", "identity")
            )
        content: dict[str, Any] = {}
        for key in bundle:
            if key != "identity":
                content[key] = bundle[key]
        computed = identity("ldb", content)
        if bundle.get("identity") != computed:
            errors.append(self._error("bundle.identity-mismatch", "$", "identity"))
        if bundle.get("kernel") != kernel.get("identity"):
            errors.append(self._error("bundle.kernel-mismatch", "$.kernel", "kernel"))
        declared = bundle.get("ontology")
        closed = {
            "fact_kinds": kernel["fact_kinds"],
            "premise_operators": kernel["premise_operators"],
        }
        if declared != closed:
            errors.append(
                self._error("bundle.ontology-mismatch", "$.ontology", "ontology")
            )

        rules = bundle.get("rules")
        facts = bundle.get("facts")
        admitted: list[dict[str, str]] = []
        seen_rules: list[str] = []
        if type(rules) is not list or type(facts) is not list:  # noqa: E721 - intentional strictness
            errors.append(self._error("bundle.shape-invalid", "$", "rules/facts"))
            return self._finish(computed, admitted, seen_rules, errors)

        operator_inventory = {name: True for name in kernel["premise_operators"]}
        for rule_number in range(len(rules)):
            premises = rules[rule_number].get("premises", [])
            for premise_number in range(len(premises)):
                name = premises[premise_number].get("op")
                if name not in operator_inventory:
                    errors.append(
                        self._error(
                            "bundle.premise-operator-unknown",
                            f"$.rules[{rule_number}].premises[{premise_number}]",
                            str(name),
                        )
                    )
        if errors:
            return self._finish(computed, admitted, seen_rules, errors)

        fact_inventory = {name: True for name in kernel["fact_kinds"]}
        for fact_number in range(len(facts)):
            fact = facts[fact_number]
            kind = fact.get("kind") if type(fact) is dict else None  # noqa: E721
            location = f"$.facts[{fact_number}]"
            if kind not in fact_inventory:
                errors.append(
                    self._error("bundle.fact-kind-unknown", location, str(kind))
                )
                continue
            candidates: list[dict[str, Any]] = []
            for candidate in rules:
                selector = candidate.get("select", {})
                if (
                    candidate.get("phase") == "admission"
                    and selector.get("fact_kind") == kind
                ):
                    candidates.append(candidate)
            if len(candidates) != 1:
                errors.append(
                    self._error(
                        "bundle.rule-selection-ambiguous"
                        if len(candidates) > 1
                        else "bundle.rule-selection-none",
                        location,
                        str(kind),
                    )
                )
                continue
            rule = candidates[0]
            seen_rules.append(str(rule["id"]))
            valid = True
            substitutions: dict[str, Any] = {}
            for premise in rule["premises"]:
                name = premise["op"]
                field = premise.get("field")
                if name == "field_equals":
                    valid = fact.get(field) == premise.get("value")
                elif name == "required_fields":
                    valid = not [
                        item for item in premise.get("fields", []) if item not in fact
                    ]
                elif name == "field_type":
                    valid = (
                        premise.get("type") == "str" and type(fact.get(field)) is str
                    )
                elif name == "field_in":
                    valid = fact.get(field) in premise.get("values", [])
                elif name == "bind_field":
                    variable = premise.get("name")
                    valid = (
                        type(variable) is str
                        and field in fact
                        and (
                            variable not in substitutions
                            or substitutions[variable] == fact[field]
                        )
                    )
                    if valid:
                        substitutions[variable] = fact[field]
                else:
                    valid = self._expression_is_closed(kernel, fact.get(field))
                if not valid:
                    errors.append(
                        self._error(str(rule["refusal"]), location, str(rule["id"]))
                    )
                    break
            if valid:
                admitted.append(
                    {
                        "fact_id": str(
                            substitutions[rule["conclusion"]["subject_binding"]]
                        ),
                        "judgment": str(rule["conclusion"]["judgment"]),
                        "rule": str(rule["id"]),
                    }
                )
        return self._finish(computed, admitted, seen_rules, errors)

    def _expression_is_closed(self, kernel: dict[str, Any], root: Any) -> bool:
        pending = [root]
        while pending:
            current = pending.pop()
            if type(current) is not dict:  # noqa: E721
                return False
            tag = current.get("node")
            if tag not in kernel["expression_nodes"]:
                return False
            if tag == "literal":
                if "value" not in current:
                    return False
            elif tag in ("arg", "local"):
                if type(current.get("name")) is not str:  # noqa: E721
                    return False
            elif tag == "state_read":
                if type(current.get("path")) is not str:  # noqa: E721
                    return False
            elif tag == "calculate":
                if current.get("operator") not in kernel["calculate_operators"]:
                    return False
                pending += list(current.get("arguments", []))
            elif tag == "call":
                if type(current.get("operation")) is not str:  # noqa: E721
                    return False
                pending += list(current.get("arguments", {}).values())
            elif tag == "let":
                if type(current.get("name")) is not str:  # noqa: E721
                    return False
                pending += [current.get("then"), current.get("value")]
            elif tag == "if":
                pending += [
                    current.get("else"),
                    current.get("then"),
                    current.get("condition"),
                ]
            elif tag in ("record", "variant"):
                if tag == "variant" and type(current.get("tag")) is not str:  # noqa: E721
                    return False
                values = list(current.get("fields", {}).values())
                if not values:
                    return False
                pending += values
            elif tag == "match":
                cases = current.get("cases")
                if type(cases) is not dict or not cases:  # noqa: E721
                    return False
                pending.append(current.get("value"))
                for case in cases.values():
                    if type(case) is not dict or type(case.get("bind")) is not str:  # noqa: E721
                        return False
                    pending.append(case.get("body"))
            elif tag == "field":
                if type(current.get("field")) is not str:  # noqa: E721
                    return False
                pending.append(current.get("value"))
            elif tag == "sample_bounded":
                pending.append(current.get("bound"))
            elif tag in ("transition_set", "emit_metric"):
                pending.append(current.get("value"))
            elif tag == "sequence":
                items = list(current.get("items", []))
                if not items:
                    return False
                pending += items
        return True

    @staticmethod
    def _error(code: str, path: str, detail: str) -> dict[str, str]:
        return {"code": code, "detail": detail, "path": path}

    def _finish(
        self,
        bundle_identity: str,
        admitted: list[dict[str, str]],
        seen_rules: list[str],
        errors: list[dict[str, str]],
    ) -> dict[str, Any]:
        admitted.sort(key=lambda row: (row["judgment"], row["fact_id"]))
        seen_rules.sort()
        return {
            "admitted": len(errors) == 0,
            "bundle_identity": bundle_identity,
            "consulted_rules": seen_rules,
            "diagnostics": errors,
            "implementation": self.implementation,
            "judgments": admitted,
        }
