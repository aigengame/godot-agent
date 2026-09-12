"""Adapt the selected inline Source input to the Kernel Formula operand."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InlineParameter:
    """One admitted Source selector and its existing normalized operand roles."""

    source_member: str
    kind_member: str
    kind: str
    parameter_member: str

    def operand(self, body: object) -> dict[str, Any] | None:
        if not isinstance(body, dict) or set(body) != {"node", self.source_member}:
            return None
        if body["node"] != self.kind:
            return None
        return {
            self.kind_member: self.kind,
            self.parameter_member: body[self.source_member],
        }

    def source_body(self, operand: dict[str, Any]) -> dict[str, Any] | None:
        if set(operand) != {self.kind_member, self.parameter_member}:
            return None
        if operand[self.kind_member] != self.kind:
            return None
        return {"node": self.kind, self.source_member: operand[self.parameter_member]}


def inline_parameter_contract(
    policy: dict[str, Any], kernel: dict[str, Any]
) -> InlineParameter:
    """Read the genuine input selector; never use it as an output field name."""
    rows = policy["inline_body_normalizations"]
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or set(rows[0]) != {"parameter_member"}
        or not isinstance(rows[0]["parameter_member"], str)
        or not rows[0]["parameter_member"]
        or rows[0]["parameter_member"] == "node"
    ):
        raise ValueError("Formula inline parameter selector is malformed")
    contract = kernel["meta_format"]["language_definitions"][
        "wire_schema_protocol_roles"
    ]["rir_structure"]["containers"]["formula_parameter_operand"]
    fields = contract["field_types"]
    constants = [name for name, value in fields.items() if "const" in value]
    # RIR identity is generated after resolution. The remaining string member is
    # the parameter reference, not a second authored Source-field selector.
    references = [
        name
        for name in contract["required_members"]
        if name not in constants and name != "identity"
    ]
    if len(constants) != 1 or len(references) != 1:
        raise ValueError("Kernel Formula parameter operand is malformed")
    kind_member, parameter_member = constants[0], references[0]
    kind = fields[kind_member]["const"]
    if not isinstance(kind, str) or fields[parameter_member] != {
        "type": "non-empty-string"
    }:
        raise ValueError("Kernel Formula parameter operand has no reference role")
    return InlineParameter(
        rows[0]["parameter_member"], kind_member, kind, parameter_member
    )
