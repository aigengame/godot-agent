from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from canonical import content_identity
from refusals import Refusal


_PHASES = {"resolution", "typing", "effects", "lowering", "runtime"}
_REFUSAL_STAGES = {
    "ingress",
    "parse",
    "static",
    "resolution",
    "runtime",
    "evaluation",
    "migration",
    "approval",
}


@dataclass(frozen=True)
class LanguageBundle:
    document: dict[str, Any]
    identity: str
    rules: dict[str, dict[str, Any]]
    operations: dict[str, dict[str, Any]]
    packages: dict[str, dict[str, Any]]
    signals: dict[str, dict[str, Any]]
    types: frozenset[str]

    def diagnostic_code(self, rule_id: str) -> str:
        return str(self.rules[rule_id]["diagnostic"]["code"])

    @staticmethod
    def _term(term: dict[str, Any], facts: dict[str, Any]) -> Any:
        if set(term) == {"fact"}:
            return facts.get(str(term["fact"]))
        if set(term) == {"constant"}:
            return term["constant"]
        raise Refusal(
            "ingress",
            "schema2.bundle.invalid-rule-term",
            "rule term must be one fact or constant reference",
            _invocation_location(),
        )

    def require(
        self,
        rule_id: str,
        facts: dict[str, Any],
        *,
        message: str,
        location: dict[str, Any],
    ) -> None:
        """Execute one bundle rule through the prototype bootstrap interpreter."""

        rule = self.rules.get(rule_id)
        if rule is None:
            raise Refusal(
                "ingress",
                "schema2.bundle.missing-rule",
                f"required Language rule is absent: {rule_id}",
                _invocation_location(),
            )
        for premise in rule["premises"]:
            operation = premise.get("op")
            if operation == "truthy":
                satisfied = bool(self._term(premise["value"], facts))
            elif operation == "equal":
                satisfied = self._term(premise["left"], facts) == self._term(
                    premise["right"], facts
                )
            elif operation == "set_equal":
                satisfied = set(self._term(premise["left"], facts)) == set(
                    self._term(premise["right"], facts)
                )
            elif operation == "contains":
                satisfied = self._term(premise["item"], facts) in self._term(
                    premise["container"], facts
                )
            else:
                raise Refusal(
                    "ingress",
                    "schema2.bundle.unknown-premise",
                    f"rule {rule_id} uses unknown premise operator {operation}",
                    _invocation_location(),
                )
            if not satisfied:
                diagnostic = rule["diagnostic"]
                raise Refusal(
                    str(diagnostic["stage"]),
                    str(diagnostic["code"]),
                    message,
                    location,
                )
        if rule["conclusion"].get("result") != "accept":
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid-conclusion",
                f"rule {rule_id} has no accepting conclusion",
                _invocation_location(),
            )


def _invocation_location() -> dict[str, str]:
    return {"kind": "invocation"}


def _unique(
    items: list[dict[str, Any]], field: str, owner: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        item_id = item.get(field)
        if not isinstance(item_id, str) or not item_id:
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid",
                f"{owner}[{index}] requires non-empty {field}",
                _invocation_location(),
            )
        if item_id in result:
            raise Refusal(
                "ingress",
                "schema2.bundle.duplicate-id",
                f"duplicate {owner} id: {item_id}",
                _invocation_location(),
            )
        result[item_id] = item
    return result


def load_bundle(path: Path) -> LanguageBundle:
    try:
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Refusal(
            "ingress" if isinstance(exc, OSError) else "parse",
            "schema2.bundle.unreadable"
            if isinstance(exc, OSError)
            else "schema2.bundle.invalid-json",
            str(exc),
            _invocation_location(),
        ) from exc

    return parse_bundle_document(document)


def parse_bundle_document(document: dict[str, Any]) -> LanguageBundle:
    """Interpret an already content-verified bundle artifact."""

    required = {
        "artifact_kind",
        "bundle_format",
        "schema_line",
        "semantic_kernel",
        "types",
        "rules",
        "operations",
        "packages",
        "signals",
        "runtime_profiles",
        "numeric_profiles",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise Refusal(
            "ingress",
            "schema2.bundle.invalid",
            "bundle root must contain exactly the closed bootstrap fields",
            _invocation_location(),
        )
    if document["artifact_kind"] != "language-definition-bundle":
        raise Refusal(
            "ingress",
            "schema2.bundle.invalid-kind",
            "artifact_kind must be language-definition-bundle",
            _invocation_location(),
        )

    rules = _unique(document["rules"], "id", "rules")
    operations = _unique(document["operations"], "id", "operations")
    packages = _unique(document["packages"], "id", "packages")
    signals = _unique(document["signals"], "id", "signals")

    # This is the non-self-hosted bootstrap interpreter boundary from bADR-0022.
    # It validates the structured rule meta-format before those rules can drive
    # the compiler/runtime below.
    for rule in rules.values():
        if set(rule) != {"id", "phase", "premises", "conclusion", "diagnostic"}:
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid-rule",
                f"rule {rule.get('id')} does not match the closed meta-format",
                _invocation_location(),
            )
        if rule["phase"] not in _PHASES:
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid-rule",
                f"rule {rule['id']} has unknown phase {rule['phase']}",
                _invocation_location(),
            )
        if not isinstance(rule["premises"], list) or not isinstance(
            rule["conclusion"], dict
        ):
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid-rule",
                f"rule {rule['id']} has invalid premises or conclusion",
                _invocation_location(),
            )
        diagnostic = rule["diagnostic"]
        if not isinstance(diagnostic, dict) or set(diagnostic) != {"code", "stage"}:
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid-rule",
                f"rule {rule['id']} has invalid diagnostic template",
                _invocation_location(),
            )
        if diagnostic["stage"] not in _REFUSAL_STAGES:
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid-diagnostic-stage",
                f"rule {rule['id']} has unknown diagnostic stage {diagnostic['stage']}",
                _invocation_location(),
            )
        conclusion = rule["conclusion"]
        if set(conclusion) != {"judgment", "result"}:
            raise Refusal(
                "ingress",
                "schema2.bundle.invalid-rule",
                f"rule {rule['id']} has invalid conclusion",
                _invocation_location(),
            )
        for premise in rule["premises"]:
            if not isinstance(premise, dict) or "op" not in premise:
                raise Refusal(
                    "ingress",
                    "schema2.bundle.invalid-rule",
                    f"rule {rule['id']} has invalid premise",
                    _invocation_location(),
                )

    phases = document["runtime_profiles"][0]["scheduler"]["phase_order"]
    if phases != ["input", "transition", "observation"]:
        raise Refusal(
            "ingress",
            "schema2.bundle.invalid-phase-order",
            "prototype accepts only the decided input/transition/observation order",
            _invocation_location(),
        )
    primitive_names = set(document["semantic_kernel"]["runtime_primitives"])
    for operation in operations.values():
        if operation["primitive"] not in primitive_names:
            raise Refusal(
                "ingress",
                "schema2.bundle.unknown-primitive",
                f"operation {operation['id']} names an unadmitted kernel primitive",
                _invocation_location(),
            )

    return LanguageBundle(
        document=document,
        identity=content_identity(
            {"artifact_kind": "language-definition-bundle", "content": document}
        ),
        rules=rules,
        operations=operations,
        packages=packages,
        signals=signals,
        types=frozenset(document["types"]),
    )
