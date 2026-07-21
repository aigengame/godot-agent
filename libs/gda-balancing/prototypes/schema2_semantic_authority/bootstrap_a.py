"""Bootstrap interpreter A: recursive premises and expressions."""

from __future__ import annotations

from typing import Any

from canonical import identity


class BootstrapA:
    implementation = "bootstrap-a-recursive-v1"

    def admit(self, kernel: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._admit(kernel, bundle)
        except (AttributeError, IndexError, KeyError, TypeError):
            bare = (
                {key: value for key, value in bundle.items() if key != "identity"}
                if isinstance(bundle, dict)
                else {}
            )
            return self._result(
                identity("ldb", bare),
                [],
                [],
                [self._diagnostic("bundle.malformed-container", "$", "container")],
            )

    def _admit(self, kernel: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
        diagnostics: list[dict[str, str]] = []
        kernel_bare = {key: value for key, value in kernel.items() if key != "identity"}
        if kernel.get("identity") != identity("kernel", kernel_bare):
            diagnostics.append(
                self._diagnostic("kernel.identity-mismatch", "$.kernel", "identity")
            )
        bare = {key: value for key, value in bundle.items() if key != "identity"}
        actual_identity = identity("ldb", bare)
        if bundle.get("identity") != actual_identity:
            diagnostics.append(
                self._diagnostic("bundle.identity-mismatch", "$", "identity")
            )
        if bundle.get("kernel") != kernel.get("identity"):
            diagnostics.append(
                self._diagnostic("bundle.kernel-mismatch", "$.kernel", "kernel")
            )
        ontology = bundle.get("ontology")
        expected_ontology = {
            "fact_kinds": kernel["fact_kinds"],
            "premise_operators": kernel["premise_operators"],
        }
        if ontology != expected_ontology:
            diagnostics.append(
                self._diagnostic("bundle.ontology-mismatch", "$.ontology", "ontology")
            )

        judgments: list[dict[str, str]] = []
        consulted: list[str] = []
        rules = bundle.get("rules")
        facts = bundle.get("facts")
        if not isinstance(rules, list) or not isinstance(facts, list):
            diagnostics.append(
                self._diagnostic("bundle.shape-invalid", "$", "rules/facts")
            )
            return self._result(actual_identity, judgments, consulted, diagnostics)

        allowed_premises = set(kernel["premise_operators"])
        for rule_index, rule in enumerate(rules):
            for premise_index, premise in enumerate(rule.get("premises", [])):
                if premise.get("op") not in allowed_premises:
                    diagnostics.append(
                        self._diagnostic(
                            "bundle.premise-operator-unknown",
                            f"$.rules[{rule_index}].premises[{premise_index}]",
                            str(premise.get("op")),
                        )
                    )

        if diagnostics:
            return self._result(actual_identity, judgments, consulted, diagnostics)

        allowed_facts = set(kernel["fact_kinds"])
        for index, fact in enumerate(facts):
            fact_kind = fact.get("kind") if isinstance(fact, dict) else None
            path = f"$.facts[{index}]"
            if fact_kind not in allowed_facts:
                diagnostics.append(
                    self._diagnostic("bundle.fact-kind-unknown", path, str(fact_kind))
                )
                continue
            selected = [
                rule
                for rule in rules
                if rule.get("phase") == "admission"
                and rule.get("select", {}).get("fact_kind") == fact_kind
            ]
            if len(selected) != 1:
                code = (
                    "bundle.rule-selection-ambiguous"
                    if selected
                    else "bundle.rule-selection-none"
                )
                diagnostics.append(self._diagnostic(code, path, str(fact_kind)))
                continue
            rule = selected[0]
            consulted.append(str(rule["id"]))
            failed = False
            bindings: dict[str, Any] = {}
            for premise in rule["premises"]:
                if not self._premise(kernel, fact, premise, bindings):
                    failed = True
                    diagnostics.append(
                        self._diagnostic(str(rule["refusal"]), path, str(rule["id"]))
                    )
                    break
            if not failed:
                judgments.append(
                    {
                        "fact_id": str(bindings[rule["conclusion"]["subject_binding"]]),
                        "judgment": str(rule["conclusion"]["judgment"]),
                        "rule": str(rule["id"]),
                    }
                )
        return self._result(actual_identity, judgments, consulted, diagnostics)

    def _premise(
        self,
        kernel: dict[str, Any],
        fact: dict[str, Any],
        premise: dict[str, Any],
        bindings: dict[str, Any],
    ) -> bool:
        operation = premise["op"]
        if operation == "field_equals":
            field = premise.get("field")
            return isinstance(field, str) and fact.get(field) == premise.get("value")
        if operation == "required_fields":
            return all(field in fact for field in premise.get("fields", []))
        if operation == "field_type":
            field = premise.get("field")
            value = fact.get(field) if isinstance(field, str) else None
            expected = premise.get("type")
            return expected == "str" and isinstance(value, str)
        if operation == "field_in":
            field = premise.get("field")
            return isinstance(field, str) and fact.get(field) in premise.get(
                "values", []
            )
        if operation == "bind_field":
            field = premise.get("field")
            name = premise.get("name")
            if not isinstance(name, str) or field not in fact:
                return False
            if name in bindings and bindings[name] != fact[field]:
                return False
            bindings[name] = fact[field]
            return True
        if operation == "expression_well_formed":
            field = premise.get("field")
            return isinstance(field, str) and self._expression(kernel, fact.get(field))
        return False

    def _expression(self, kernel: dict[str, Any], expression: Any) -> bool:
        if (
            not isinstance(expression, dict)
            or expression.get("node") not in kernel["expression_nodes"]
        ):
            return False
        node = expression["node"]
        children: list[Any] = []
        if node in {"arg", "local", "state_read", "literal"}:
            return (
                "value" in expression
                if node == "literal"
                else isinstance(
                    expression.get("name" if node in {"arg", "local"} else "path"), str
                )
            )
        if node == "calculate":
            if expression.get("operator") not in kernel["calculate_operators"]:
                return False
            children.extend(expression.get("arguments", []))
        elif node == "call":
            if not isinstance(expression.get("operation"), str):
                return False
            children.extend(expression.get("arguments", {}).values())
        elif node in {"let"}:
            if not isinstance(expression.get("name"), str):
                return False
            children.extend([expression.get("value"), expression.get("then")])
        elif node == "if":
            children.extend(
                [
                    expression.get("condition"),
                    expression.get("then"),
                    expression.get("else"),
                ]
            )
        elif node in {"record", "variant"}:
            if node == "variant" and not isinstance(expression.get("tag"), str):
                return False
            children.extend(expression.get("fields", {}).values())
        elif node == "match":
            children.append(expression.get("value"))
            cases = expression.get("cases", {})
            if not isinstance(cases, dict) or not cases:
                return False
            for case in cases.values():
                if not isinstance(case, dict) or not isinstance(case.get("bind"), str):
                    return False
                children.append(case.get("body"))
        elif node == "field":
            if not isinstance(expression.get("field"), str):
                return False
            children.append(expression.get("value"))
        elif node in {"sample_bounded", "transition_set", "emit_metric"}:
            key = "bound" if node == "sample_bounded" else "value"
            children.append(expression.get(key))
        elif node == "sequence":
            children.extend(expression.get("items", []))
        return bool(children) and all(
            self._expression(kernel, child) for child in children
        )

    @staticmethod
    def _diagnostic(code: str, path: str, detail: str) -> dict[str, str]:
        return {"code": code, "detail": detail, "path": path}

    def _result(
        self,
        bundle_identity: str,
        judgments: list[dict[str, str]],
        consulted: list[str],
        diagnostics: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "admitted": not diagnostics,
            "bundle_identity": bundle_identity,
            "consulted_rules": sorted(consulted),
            "diagnostics": diagnostics,
            "implementation": self.implementation,
            "judgments": sorted(
                judgments, key=lambda item: (item["judgment"], item["fact_id"])
            ),
        }
