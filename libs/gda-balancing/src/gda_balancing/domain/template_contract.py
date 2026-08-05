"""Host-supported contract for Schema-major Template graph primitives.

The packaged Kernel remains the machine authority.  These constants describe
the closed contract implemented by this host so bootstrap admission and runtime
execution cannot drift into separate copies of that support boundary.
"""

from typing import Any


TEMPLATE_SELECTOR_CONTRACT: dict[str, Any] = {
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

TEMPLATE_RESOURCE_ACCOUNTING: dict[str, Any] = {
    "charge_rules": [
        {"amount": "one-per-member", "event": "member-role"},
        {"amount": "one-per-judgment", "event": "judgment"},
        {"amount": "one-per-projected-value", "event": "selected-value"},
        {"amount": "one-per-input-row", "event": "scoped-row"},
        {"amount": "one-per-vector", "event": "vector-execution"},
    ],
    "counter_scope": "per-template-release-admission",
    "exhaustion_diagnostic": "language.resource_exhausted",
    "limit_path": "resources.max_template_admission_steps",
}

TEMPLATE_ARGUMENT_TYPES: list[dict[str, Any]] = [
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

TEMPLATE_PRIMITIVE_EVALUATIONS: dict[str, dict[str, Any]] = {
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

TEMPLATE_PRIMITIVE_RESULT_EFFECTS = {
    "content-identity": "bind-derived",
    "concatenate-selections": "bind-derived",
    "model-source-admission": "bind-model-facts",
    "canonical-unique": "preserve-graph",
    "canonical-inventory": "preserve-graph",
    "canonical-set-relation": "preserve-graph",
    "canonical-scoped-relation": "preserve-graph",
    "canonical-scoped-unique": "preserve-graph",
    "closed-int64-interval": "preserve-graph",
    "closed-int64-interval-join": "preserve-graph",
    "model-source-vector": "preserve-graph",
}

TEMPLATE_PRIMITIVE_CHARGES = {
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
