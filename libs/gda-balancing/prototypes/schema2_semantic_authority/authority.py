"""The probe's explicit Kernel Specification, LDB, sources, and profiles.

This module contains authored wire data only.  It intentionally contains no evaluator,
compiler, rule-selection, arithmetic, RNG, or transition implementation.
"""

from __future__ import annotations

from typing import Any

from canonical import clone, identity


KERNEL_SPEC: dict[str, Any] = {
    "kind": "schema-major-kernel-specification",
    "schema_major": 2,
    "kernel_version": "probe-kernel-1",
    "fact_kinds": ["diagnostic", "operation", "package", "runtime_profile"],
    "premise_operators": [
        "bind_field",
        "expression_well_formed",
        "field_equals",
        "field_in",
        "field_type",
        "required_fields",
    ],
    "expression_nodes": [
        "arg",
        "call",
        "calculate",
        "emit_metric",
        "field",
        "if",
        "let",
        "literal",
        "local",
        "match",
        "record",
        "sample_bounded",
        "sequence",
        "state_read",
        "transition_set",
        "variant",
    ],
    "calculate_operators": ["add_int", "gte_int", "sub_int"],
    "numeric": {
        "profile": "exact-int64-v1",
        "minimum": -(2**63),
        "maximum": 2**63 - 1,
        "overflow": "runtime-refusal",
        "bool_is_int": False,
    },
    "rng": {
        "profile": "sha256-named-stream-unbiased-u64-v1",
        "seed_encoding": "unsigned-u64-big-endian",
        "domain_prefix_hex": "736368656d61322d726e672d763100",
        "stream_encoding": "u16-byte-length-plus-utf8",
        "counter_encoding": "unsigned-u64-big-endian",
        "byte_extraction": "sha256-first-u64-big-endian",
        "bounded_mapping": "reject-x-gte-2^64-(2^64-mod-bound)-then-x-mod-bound",
        "draw_consumption": "each-candidate-consumes-one-counter",
        "counter_overflow": "runtime-refusal",
        "invalid_bound": "runtime-refusal",
    },
    "event": {
        "transition_visibility": "working-state-until-event-commit",
        "refusal": "rollback-current-event-and-publish-terminal-audit-set",
    },
}
KERNEL_SPEC["identity"] = identity("kernel", KERNEL_SPEC)


def _rules() -> list[dict[str, Any]]:
    common = {
        "diagnostic": ["id", "stage"],
        "operation": ["id", "parameters", "result", "effects", "body"],
        "package": ["id", "version", "provides", "requires", "operations"],
        "runtime_profile": [
            "id",
            "numeric_profile",
            "rng_profile",
            "max_steps",
            "max_draws",
            "allowed_effects",
            "allowed_streams",
        ],
    }
    rules: list[dict[str, Any]] = []
    for fact_kind, fields in common.items():
        premises: list[dict[str, Any]] = [
            {"op": "field_equals", "field": "kind", "value": fact_kind},
            {"op": "required_fields", "fields": fields},
            {"op": "field_type", "field": "id", "type": "str"},
            {"op": "bind_field", "field": "id", "name": "subject"},
        ]
        if fact_kind == "operation":
            premises.append({"op": "expression_well_formed", "field": "body"})
        rules.append(
            {
                "id": f"admit.{fact_kind}.v1",
                "phase": "admission",
                "select": {"fact_kind": fact_kind},
                "premises": premises,
                "conclusion": {
                    "judgment": f"admitted.{fact_kind}",
                    "subject_binding": "subject",
                },
                "refusal": "bundle.fact-invalid",
            }
        )
    return rules


def language_bundle(*, damage_operator: str = "add_int") -> dict[str, Any]:
    reserve_body = {
        "node": "let",
        "name": "available",
        "value": {"node": "state_read", "path": "actor.resource"},
        "then": {
            "node": "if",
            "condition": {
                "node": "calculate",
                "operator": "gte_int",
                "arguments": [
                    {"node": "local", "name": "available"},
                    {"node": "arg", "name": "amount"},
                ],
            },
            "then": {
                "node": "variant",
                "tag": "Reserved",
                "fields": {
                    "remaining": {
                        "node": "calculate",
                        "operator": "sub_int",
                        "arguments": [
                            {"node": "local", "name": "available"},
                            {"node": "arg", "name": "amount"},
                        ],
                    }
                },
            },
            "else": {
                "node": "variant",
                "tag": "Insufficient",
                "fields": {
                    "available": {"node": "local", "name": "available"},
                    "required": {"node": "arg", "name": "amount"},
                },
            },
        },
    }
    action_body = {
        "node": "let",
        "name": "reservation",
        "value": {
            "node": "call",
            "operation": "rpg.resource.reserve@1",
            "arguments": {"amount": {"node": "arg", "name": "cost"}},
        },
        "then": {
            "node": "match",
            "value": {"node": "local", "name": "reservation"},
            "cases": {
                "Reserved": {
                    "bind": "reserved",
                    "body": {
                        "node": "let",
                        "name": "roll",
                        "value": {
                            "node": "sample_bounded",
                            "stream": "combat.damage",
                            "bound": {"node": "arg", "name": "roll_bound"},
                        },
                        "then": {
                            "node": "let",
                            "name": "damage",
                            "value": {
                                "node": "calculate",
                                "operator": damage_operator,
                                "arguments": [
                                    {"node": "arg", "name": "base_damage"},
                                    {"node": "local", "name": "roll"},
                                ],
                            },
                            "then": {
                                "node": "let",
                                "name": "new_hp",
                                "value": {
                                    "node": "calculate",
                                    "operator": "sub_int",
                                    "arguments": [
                                        {"node": "state_read", "path": "target.hp"},
                                        {"node": "local", "name": "damage"},
                                    ],
                                },
                                "then": {
                                    "node": "sequence",
                                    "items": [
                                        {
                                            "node": "transition_set",
                                            "path": "actor.resource",
                                            "value": {
                                                "node": "field",
                                                "value": {
                                                    "node": "local",
                                                    "name": "reserved",
                                                },
                                                "field": "remaining",
                                            },
                                        },
                                        {
                                            "node": "transition_set",
                                            "path": "target.hp",
                                            "value": {
                                                "node": "local",
                                                "name": "new_hp",
                                            },
                                        },
                                        {
                                            "node": "emit_metric",
                                            "metric": "damage.dealt",
                                            "value": {
                                                "node": "local",
                                                "name": "damage",
                                            },
                                        },
                                        {
                                            "node": "variant",
                                            "tag": "Resolved",
                                            "fields": {
                                                "damage": {
                                                    "node": "local",
                                                    "name": "damage",
                                                }
                                            },
                                        },
                                    ],
                                },
                            },
                        },
                    },
                },
                "Insufficient": {
                    "bind": "shortage",
                    "body": {
                        "node": "variant",
                        "tag": "Insufficient",
                        "fields": {
                            "available": {
                                "node": "field",
                                "value": {"node": "local", "name": "shortage"},
                                "field": "available",
                            },
                        },
                    },
                },
            },
        },
    }
    facts: list[dict[str, Any]] = [
        {
            "kind": "diagnostic",
            "id": "runtime.limit-exceeded",
            "stage": "runtime",
        },
        {
            "kind": "operation",
            "id": "rpg.resource.reserve@1",
            "parameters": {"amount": "Int"},
            "result": "Reserved|Insufficient",
            "effects": ["state.read"],
            "body": reserve_body,
        },
        {
            "kind": "operation",
            "id": "rpg.action.resolve@1",
            "parameters": {"base_damage": "Int", "cost": "Int", "roll_bound": "Int"},
            "result": "Resolved|Insufficient",
            "effects": ["metric.emit", "random.sample", "state.read", "state.write"],
            "body": action_body,
        },
        {
            "kind": "package",
            "id": "rpg.combat",
            "version": "2.0.0-probe",
            "provides": ["rpg.action", "rpg.damage", "rpg.resource"],
            "requires": [],
            "operations": ["rpg.action.resolve@1", "rpg.resource.reserve@1"],
        },
        {
            "kind": "runtime_profile",
            "id": "portable-exact-v1",
            "numeric_profile": "exact-int64-v1",
            "rng_profile": "sha256-named-stream-unbiased-u64-v1",
            "max_steps": 512,
            "max_draws": 8,
            "allowed_effects": [
                "metric.emit",
                "random.sample",
                "state.read",
                "state.write",
            ],
            "allowed_streams": ["combat.damage"],
        },
    ]
    bundle = {
        "kind": "language-definition-bundle",
        "schema_major": 2,
        "kernel": KERNEL_SPEC["identity"],
        "ontology": {
            "fact_kinds": KERNEL_SPEC["fact_kinds"],
            "premise_operators": KERNEL_SPEC["premise_operators"],
        },
        "rules": _rules(),
        "facts": facts,
    }
    bundle["identity"] = identity("ldb", bundle)
    return bundle


def source_package(variant: str = "a", *, base_damage: int = 4) -> dict[str, Any]:
    declarations = [
        {"kind": "constant", "name": "base", "value": base_damage},
        {"kind": "constant", "name": "cost", "value": 3},
        {"kind": "constant", "name": "roll_bound", "value": 3},
        {
            "kind": "entry",
            "name": "turn",
            "operation": "combat" if variant == "b" else "rpg.action.resolve@1",
            "arguments": {
                "base_damage": {"ref": "base"},
                "cost": {"ref": "cost"},
                "roll_bound": {"ref": "roll_bound"},
            },
        },
    ]
    if variant == "b":
        declarations = [
            declarations[2],
            declarations[0],
            declarations[3],
            declarations[1],
        ]
    return {
        "kind": "model-source-package",
        "name": "authority-probe",
        "version": "0.0.0",
        "comment": "different provenance" if variant == "b" else "canonical fixture",
        "imports": {"combat": "rpg.action.resolve@1"} if variant == "b" else {},
        "requires": [{"package": "rpg.combat", "constraint": "=2.0.0-probe"}],
        "modules": [{"name": "battle", "declarations": declarations}],
    }


def experiment() -> dict[str, Any]:
    return {
        "kind": "experiment-specification",
        "id": "authority-cross-evaluator-v1",
        "metric_definitions": [{"id": "damage.dealt", "aggregation": "exact-sequence"}],
        "acceptance": {
            "required_outcome": "Resolved",
            "required_comparison": "exact-resolved-runtime-profile-v1",
        },
        "replay_policy": {
            "id": "exact-resolved-runtime-profile-v1",
            "resolved_profile_identity": "must-be-identical",
            "compare": ["outcome", "final_state", "metrics", "rng_trace"],
        },
    }


def scenario(kind: str = "success") -> dict[str, Any]:
    resource = 2 if kind == "insufficient" else 5
    return {
        "kind": "scenario",
        "id": kind,
        "seed": 7,
        "initial_state": {"actor": {"resource": resource}, "target": {"hp": 12}},
    }


def runtime_profile(*, max_steps: int = 512, max_draws: int = 8) -> dict[str, Any]:
    bundle = language_bundle()
    profile = next(
        fact for fact in bundle["facts"] if fact["kind"] == "runtime_profile"
    )
    result = clone(profile)
    result["concrete_budgets"] = {
        "max_steps": max_steps,
        "max_draws": max_draws,
    }
    return result
