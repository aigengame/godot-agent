"""Candidate priority content built entirely from the current admitted language.

Operation-contract vectors below close admission declarations only. The public
protocol tests own actual execution evidence; these fixtures do not claim complete
package conformance or install game.action/game.turn as maintained authorities.
"""

from copy import deepcopy
from typing import Any

from gda_balancing.domain.experiment import derive_scenario_program_requirements
from schema2_authority_support import mutable_authorities
from schema2_bootstrap_conformance_support import _bind_package_vector_set
from schema2_bootstrap_production_support import _reidentify_graph_root

A = "game.action"
T = "game.turn"
# One bounded window permits seven authored choice boundaries, then resolution.
RESOLUTION_TIME = 7
Q = {"package": "core.quantity", "id": "Quantity"}
EFFECTS = ["event.commit", "metric.observe", "snapshot.commit"]
BASE_REFUSALS = ["runtime.reason.step-limit", "runtime.reason.numeric-overflow"]


def q(name, access="read"):
    return {
        "id": name,
        "access": access,
        "type": deepcopy(Q),
        "kind": "scalar",
        "representation": "Int",
        "unit": "1",
        "domain": {"kind": "actual"},
        "numeric_policy": "exact-int64",
    }


def typed(name, typ, access="read"):
    return {
        "id": name,
        "access": access,
        "type": {"package": A, "id": typ},
        "value_kind": "nominal-structured",
    }


def constant(name, value):
    return {"node": "constant", "target": name, "literal": value}


def ar(node, target, left, right):
    return {"node": node, "target": target, "left": left, "right": right}


def write(name, value):
    return {"node": "write-state", "symbol": name, "value": value}


def lookup(name, value, key):
    return {"node": "lookup", "target": name, "value": value, "key": key}


def check(left, right, outcome):
    return {
        "node": "precondition-greater-than-or-equal",
        "left": left,
        "right": right,
        "outcome": outcome,
    }


def result(port, name):
    return {
        **deepcopy(port),
        "id": "result",
        "discardable": False,
        "source": {"kind": "local", "name": name},
    }


def unit():
    return {
        "id": "result",
        "access": "read",
        "discardable": True,
        "type": {"package": "kernel", "id": "Unit"},
        "kind": "unit",
        "representation": "Unit",
        "unit": "1",
        "domain": {"kind": "unit"},
        "numeric_policy": "exact-unit",
        "source": {"kind": "unit"},
    }


def env(names):
    return [{"port": name, "operand": {"kind": "port", "port": name}} for name in names]


def fold(site, target, value, initial, step, acc, item, args=()):
    return {
        "node": "fold",
        "site": site,
        "target": target,
        "value": value,
        "initial": initial,
        "operation": {"package": A, "id": step},
        "accumulator_port": acc,
        "item_port": item,
        "arguments": env(args),
    }


def invoke(site, owner, name, args, *, propagate=()):
    return {
        "node": "invoke",
        "site": site,
        "operation": {"package": owner, "id": name},
        "arguments": env(args),
        "result": {"kind": "discard"},
        "outcomes": [{"outcome": "committed", "action": {"kind": "continue"}}]
        + [
            {"outcome": outcome, "action": {"kind": "propagate", "outcome": outcome}}
            for outcome in propagate
        ],
    }


def op(
    name,
    inputs,
    body,
    *,
    pure=False,
    res=None,
    extra=(),
    outcomes=(),
    default="committed",
):
    value = {
        "id": name,
        "rule": "structured.lower",
        "operation_kind": "pure-expression" if pure else "event-program",
        "purity": "pure" if pure else "event",
        "inputs": inputs,
        "body": body,
        "effects": [] if pure else list(EFFECTS),
        "refusals": sorted(set(BASE_REFUSALS) | set(extra)),
        "result": res or unit(),
        "numeric_policy": "exact-int64",
        "runtime_profile": "standard.exact-int64-event-v1",
        "resource_bounds": {"max_steps": 512},
        "alias_policy": {"read_only": "share", "writable_groups": []},
        "unit_rules": {"inputs": "preserve", "result": "preserve"},
        "kind_rules": {"inputs": "preserve", "result": "preserve"},
    }
    if not pure:
        value.update(
            default_outcome=default,
            outcomes=[{"id": default, "kind": "success", "state_policy": "commit"}]
            + [
                {"id": n, "kind": "gameplay-alternative", "state_policy": "rollback"}
                for n in outcomes
            ],
        )
    return value


def authorities():
    kernel, language = mutable_authorities()
    nominal = [
        {
            "id": "Counter",
            "constructor": "standard.schema.record",
            "definition": {
                "kind": "record",
                "fields": [
                    {"name": x, "type": deepcopy(Q)} for x in ("actor", "target")
                ],
            },
        },
        {
            "id": "Counters",
            "constructor": "standard.schema.list",
            "definition": {
                "kind": "list",
                "element": {"package": A, "id": "Counter"},
                "maximum_length": 2,
            },
        },
        {
            "id": "PendingIds",
            "constructor": "standard.schema.list",
            "definition": {"kind": "list", "element": deepcopy(Q), "maximum_length": 2},
        },
        {
            "id": "Outcome",
            "constructor": "standard.schema.enum",
            "definition": {
                "kind": "enum",
                "members": ["pending", "resolved", "canceled"],
            },
        },
    ]
    empty = {"type": {"package": A, "id": "PendingIds"}, "value": []}
    action = []
    action.append(
        op(
            "count-match",
            [q("matches"), q("item"), q("needle")],
            [
                constant("zero", 0),
                constant("one", 1),
                ar("equal", "same", "item", "needle"),
                {
                    "node": "if",
                    "target": "increment",
                    "condition": "same",
                    "when_true": "one",
                    "when_false": "zero",
                },
                ar("add", "next", "matches", "increment"),
            ],
            pure=True,
            res=result(q("x"), "next"),
        )
    )
    action.append(
        op(
            "cancel-reverse-step",
            [
                typed("canceled", "PendingIds"),
                q("cursor"),
                typed("counters", "Counters"),
                typed("ids", "PendingIds"),
                q("next_id"),
            ],
            [
                ar("subtract", "reverse_index", "next_id", "cursor"),
                lookup("current_id", "ids", "reverse_index"),
                lookup("counter", "counters", "reverse_index"),
                lookup("target", "counter", "target"),
                constant("zero", 0),
                {
                    **fold(
                        "already-canceled",
                        "matches",
                        "canceled",
                        "zero",
                        "count-match",
                        "matches",
                        "item",
                    ),
                    "arguments": [
                        {
                            "port": "needle",
                            "operand": {"kind": "local", "local": "current_id"},
                        }
                    ],
                },
                ar("equal", "active", "matches", "zero"),
                {
                    "node": "list-append",
                    "target": "appended",
                    "value": "canceled",
                    "item": "target",
                },
                {
                    "node": "if",
                    "target": "next_canceled",
                    "condition": "active",
                    "when_true": "appended",
                    "when_false": "canceled",
                },
            ],
            pure=True,
            res=result(typed("x", "PendingIds"), "next_canceled"),
            extra=[
                "structured.reason.list-capacity-exceeded",
                "structured.reason.lookup-out-of-range",
            ],
        )
    )
    action.append(
        op(
            "propose",
            [
                q("next_id", "read-write"),
                q("root_id", "read-write"),
                q("power", "read-write"),
                q("authored_power"),
            ],
            [
                constant("zero", 0),
                check("zero", "next_id", "already-used"),
                constant("one", 1),
                ar("add", "created", "next_id", "one"),
                write("next_id", "created"),
                write("root_id", "created"),
                write("power", "authored_power"),
            ],
            outcomes=["already-used"],
        )
    )
    action.append(
        op(
            "append-counter",
            [
                q("root_id"),
                q("next_id", "read-write"),
                typed("counters", "Counters", "read-write"),
                typed("ids", "PendingIds", "read-write"),
                typed("counter", "Counter"),
            ],
            [
                constant("one", 1),
                check("root_id", "one", "unknown-target"),
                lookup("target", "counter", "target"),
                check("target", "root_id", "unknown-target"),
                check("next_id", "target", "unknown-target"),
                ar("add", "created", "next_id", "one"),
                {
                    "node": "list-append",
                    "target": "new_counters",
                    "value": "counters",
                    "item": "counter",
                },
                {
                    "node": "list-append",
                    "target": "new_ids",
                    "value": "ids",
                    "item": "created",
                },
                write("counters", "new_counters"),
                write("ids", "new_ids"),
                write("next_id", "created"),
            ],
            extra=[
                "structured.reason.list-capacity-exceeded",
                "structured.reason.lookup-out-of-range",
            ],
            outcomes=["unknown-target"],
        )
    )
    resolve_inputs = [
        q("root_id"),
        q("next_id"),
        q("power"),
        typed("counters", "Counters"),
        typed("ids", "PendingIds"),
        typed("canceled_ids", "PendingIds", "read-write"),
        q("final_power", "read-write"),
        typed("status", "Outcome", "read-write"),
    ]
    resolve_body = [
        constant("empty", empty),
        constant("zero", 0),
        fold(
            "resolve-counters",
            "canceled",
            "ids",
            "empty",
            "cancel-reverse-step",
            "canceled",
            "cursor",
            ("counters", "ids", "next_id"),
        ),
        write("canceled_ids", "canceled"),
        {
            **fold(
                "root-canceled",
                "matches",
                "canceled",
                "zero",
                "count-match",
                "matches",
                "item",
            ),
            "arguments": [
                {"port": "needle", "operand": {"kind": "port", "port": "root_id"}}
            ],
        },
        ar("equal", "survives", "matches", "zero"),
        constant(
            "resolved", {"type": {"package": A, "id": "Outcome"}, "value": "resolved"}
        ),
        constant(
            "canceled_status",
            {"type": {"package": A, "id": "Outcome"}, "value": "canceled"},
        ),
        {
            "node": "if",
            "target": "resolved_power",
            "condition": "survives",
            "when_true": "power",
            "when_false": "zero",
        },
        {
            "node": "if",
            "target": "resolved_status",
            "condition": "survives",
            "when_true": "resolved",
            "when_false": "canceled_status",
        },
        write("final_power", "resolved_power"),
        write("status", "resolved_status"),
    ]
    action.append(
        op(
            "resolve",
            resolve_inputs,
            resolve_body,
            extra=[
                "structured.reason.list-capacity-exceeded",
                "structured.reason.lookup-out-of-range",
            ],
        )
    )
    # The window owns priority and pass rules; the Action owner alone creates IDs
    # and resolves the pending target graph. No prospective action is undone.
    turn = []
    turn.append(
        op(
            "open",
            [
                q("next_id", "read-write"),
                q("root_id", "read-write"),
                q("power", "read-write"),
                q("authored_power"),
                q("actor"),
                q("priority", "read-write"),
                q("passes", "read-write"),
                q("window_open", "read-write"),
            ],
            [
                constant("zero", 0),
                constant("one", 1),
                check("zero", "window_open", "already-open"),
                invoke(
                    "create-proposal",
                    A,
                    "propose",
                    ("next_id", "root_id", "power", "authored_power"),
                    propagate=("already-used",),
                ),
                ar("subtract", "other", "one", "actor"),
                write("priority", "other"),
                write("passes", "zero"),
                write("window_open", "one"),
            ],
            outcomes=["already-open", "already-used"],
        )
    )
    response_inputs = [
        q("root_id"),
        q("next_id", "read-write"),
        typed("counters", "Counters", "read-write"),
        typed("ids", "PendingIds", "read-write"),
        typed("counter", "Counter"),
        q("priority", "read-write"),
        q("passes", "read-write"),
        q("window_open"),
    ]
    turn.append(
        op(
            "respond",
            response_inputs,
            [
                constant("zero", 0),
                constant("one", 1),
                check("window_open", "one", "closed-window"),
                lookup("actor", "counter", "actor"),
                check("actor", "priority", "wrong-priority"),
                check("priority", "actor", "wrong-priority"),
                invoke(
                    "create-counter",
                    A,
                    "append-counter",
                    ("root_id", "next_id", "counters", "ids", "counter"),
                    propagate=("unknown-target",),
                ),
                ar("subtract", "other", "one", "actor"),
                write("priority", "other"),
                write("passes", "zero"),
            ],
            extra=[
                "structured.reason.list-capacity-exceeded",
                "structured.reason.lookup-out-of-range",
            ],
            outcomes=["closed-window", "wrong-priority", "unknown-target"],
        )
    )
    pass_inputs = [
        q("actor"),
        q("priority", "read-write"),
        q("passes", "read-write"),
        q("window_open", "read-write"),
        *resolve_inputs,
    ]
    pass_body = [
        constant("zero", 0),
        constant("one", 1),
        constant("two", 2),
        check("window_open", "one", "closed-window"),
        check("actor", "priority", "wrong-priority"),
        check("priority", "actor", "wrong-priority"),
        ar("add", "new_passes", "passes", "one"),
        ar("subtract", "other", "one", "actor"),
        write("passes", "new_passes"),
        write("priority", "other"),
        ar("equal", "closing", "new_passes", "two"),
        {
            "node": "guard-block",
            "condition": "closing",
            "outcome": "closed",
            "body": [
                write("window_open", "zero"),
                {
                    "node": "schedule",
                    "site": "final-resolution",
                    "operation": {"package": A, "id": "resolve"},
                    "arguments": env([p["id"] for p in resolve_inputs]),
                    "logical_time": RESOLUTION_TIME,
                    "priority": 0,
                    "result": {"kind": "local", "name": "resolution_event"},
                },
            ],
        },
    ]
    turn.append(
        op(
            "pass",
            pass_inputs,
            pass_body,
            extra=[
                "runtime.reason.schedule-backward",
                "runtime.reason.schedule-hidden-input",
                "runtime.reason.schedule-illegal-same-time-priority",
                "runtime.reason.queue-limit",
                "runtime.reason.zero-time-depth-limit",
                "runtime.reason.event-limit",
                "runtime.reason.logical-time-limit",
            ],
            outcomes=["closed-window", "wrong-priority"],
        )
    )
    turn[-1]["outcomes"].append(
        {"id": "closed", "kind": "success", "state_policy": "commit"}
    )
    turn[-1]["effects"].append("event.schedule")
    for owner, operations, types in ((A, action, nominal), (T, turn, [])):
        package = deepcopy(
            next(p for p in language.package_releases if p["id"] == "standard.compiler")
        )
        package["id"] = owner
        package["dependencies"] = {
            "optional": [],
            "required": sorted(
                ["core.quantity", "standard.runtime", "standard.schema"]
                + ([A] if owner == T else [])
            ),
        }
        package["capabilities"] = {
            "provided": [owner + ".priority-protocol"],
            "required": ["quantity.lower", "structured.lower"],
        }
        package["exports"] = {k: [] for k in package["exports"]}
        package["exports"]["operations"] = [o["id"] for o in operations]
        package["exports"]["nominal_types"] = [t["id"] for t in types]
        package["exports"]["types"] = [
            {"id": t["id"], "constructor": t["constructor"]} for t in types
        ]
        package["profiles"] = {k: [] for k in package["profiles"]}
        package["runtime_semantic_paths"] = [
            "language.capabilities",
            "language.nominal_types",
            "language.operations",
        ]
        defs = {
            "language.capabilities": [
                {"id": owner + ".priority-protocol", "rule": "structured.lower"}
            ],
            "language.nominal_types": types,
            "language.operations": operations,
        }
        for entry in package["semantic_closure"]:
            entry["definitions"] = defs.get(entry["authority_path"], [])
        vectors = []
        for operation in operations:
            operation["vectors"] = []
            for suffix, path, category in (
                ("body", "body", "positive"),
                ("effects", "effects", "effects"),
                ("bound", "resource_bounds.max_steps", "resource"),
            ):
                vid = f"{owner}.{operation['id']}.{suffix}"
                operation["vectors"].append(vid)
                expect = operation
                for key in path.split("."):
                    expect = expect[key]
                vectors.append(
                    {
                        "id": vid,
                        "kind": "operation-contract",
                        "operation": operation["id"],
                        "probe": {"path": path},
                        "category": category,
                        "expect": deepcopy(expect),
                    }
                )
        vector_set = {
            "artifact_kind": "package-conformance-vector-set",
            "package_id": owner,
            "vectors": [v["id"] for v in vectors],
            "vector_definitions": vectors,
        }
        _bind_package_vector_set(package, vector_set, kernel=kernel)
        language["language"]["packages"].append(package)
        language.package_conformance_vector_sets.append(vector_set)
    _reidentify_graph_root(language)
    return (
        kernel,
        language,
        {(T, o["id"]): o for o in turn}
        | {
            (A, name): next(o for o in action if o["id"] == name)
            for name in ("append-counter", "propose")
        },
    )


def source(turn):
    quantities = {
        "next_id": "state",
        "root_id": "state",
        "power": "state",
        "authored_power": "input",
        "actor": "input",
        "priority": "state",
        "passes": "state",
        "window_open": "state",
        "final_power": "state",
    }
    symbols = [
        {
            "symbol": name,
            "type": "quantity",
            "role": role,
            "kind": "scalar",
            "representation": "Int",
            "unit": "1",
            "domain_kind": "closed-interval",
            "domain": {"minimum": 0, "maximum": 1 if name == "actor" else 10},
            "numeric_policy": "exact-int64",
            "value_policy": {"mode": "experiment-required"},
        }
        for name, role in quantities.items()
    ]
    symbols += [
        {
            "symbol": name,
            "type": typ,
            "role": role,
            "value_policy": {"mode": "experiment-required"},
        }
        for name, typ, role in (
            ("counter", "Counter", "input"),
            ("counters", "Counters", "state"),
            ("ids", "PendingIds", "state"),
            ("canceled_ids", "PendingIds", "state"),
            ("status", "Outcome", "state"),
        )
    ]
    entries = [
        {
            "id": name,
            "operation": {"package": owner, "id": name},
            "arguments": [
                {
                    "port": p["id"],
                    "operand": {"kind": "symbol", "module": "main", "symbol": p["id"]},
                }
                for p in operation["inputs"]
            ],
            "result": {"kind": "discard"},
        }
        for (owner, name), operation in turn.items()
    ]
    return {
        "schema_version": "2.0.0",
        "manifest": {"id": "example.priority-window", "entry_module": "main"},
        "package_requirements": ["core.quantity", A, T],
        "modules": [
            {
                "id": "main",
                "imports": [
                    {
                        "alias": "quantity",
                        "package": "core.quantity",
                        "symbol": "Quantity",
                    }
                ]
                + [
                    {"alias": n, "package": A, "symbol": n}
                    for n in ("Counter", "Counters", "PendingIds", "Outcome")
                ],
                "symbols": symbols,
            }
        ],
        "entrypoints": entries,
    }


def specification(rir, variant=False, *, choices=None):
    def value(name, supplied):
        return {
            "target": {
                "model": "example.priority-window",
                "module": "main",
                "name": name,
            },
            "value": supplied,
        }

    default_choices = [
        ("open", {"actor": 0, "authored_power": 7}),
        (
            "respond",
            {
                "counter": {
                    "type": {"package": A, "id": "Counter"},
                    "value": {"actor": 1, "target": 1},
                }
            },
        ),
    ]
    default_choices += (
        [("pass", {"actor": 0}), ("pass", {"actor": 1})]
        if variant
        else [
            (
                "respond",
                {
                    "counter": {
                        "type": {"package": A, "id": "Counter"},
                        "value": {"actor": 0, "target": 2},
                    }
                },
            ),
            ("pass", {"actor": 1}),
            ("pass", {"actor": 0}),
        ]
    )
    choices = default_choices if choices is None else choices
    events = []
    for t, (entry, facts) in enumerate(choices):
        events.append(
            {
                "kind": "external-input",
                "root_event_ref": f"choice-{t}",
                "logical_time": t,
                "priority": 0,
                "source_identity": "sha256:" + "a" * 64,
                "source_sequence": t,
                "facts": [value(k, v) for k, v in facts.items()],
            }
        )
        events.append(
            {
                "kind": "transition-invocation",
                "root_event_ref": f"advance-{t}",
                "logical_time": t,
                "priority": 0,
                "entrypoint": entry,
                "payload": [],
            }
        )
    initial: dict[str, Any] = {
        name: 0
        for name in (
            "next_id",
            "root_id",
            "power",
            "actor",
            "priority",
            "passes",
            "window_open",
            "final_power",
        )
    }
    initial["authored_power"] = 7
    initial.update(
        counter={
            "type": {"package": A, "id": "Counter"},
            "value": {"actor": 1, "target": 1},
        },
        counters={"type": {"package": A, "id": "Counters"}, "value": []},
        ids={"type": {"package": A, "id": "PendingIds"}, "value": []},
        canceled_ids={"type": {"package": A, "id": "PendingIds"}, "value": []},
        status={"type": {"package": A, "id": "Outcome"}, "value": "pending"},
    )
    reqs = [
        derive_scenario_program_requirements(
            rir, e, "standard.exact-int64-event-v1", "splitmix64-v1"
        )[0]
        for e in dict.fromkeys(entry for entry, _facts in choices)
    ]
    requirements = {k: sorted({x for r in reqs for x in r[k]}) for k in reqs[0]}
    metric = {
        "id": "resolved-power",
        "kind": "scalar",
        "unit": "1",
        "dimensions": [],
        "window": {"kind": "scenario", "name": "terminal-event"},
        "aggregation": "single",
        "replication": {"unit": "scenario"},
        "missing": "refuse",
        "censoring": "none",
        "observation": {
            "source": "snapshot",
            "name": "terminal",
            "member": "final_power",
        },
        "target": {"minimum": 0 if variant else 7, "maximum": 0 if variant else 7},
    }
    return {
        "schema_version": "2.0.0",
        "id": "example.priority-window.variant"
        if variant
        else "example.priority-window.baseline",
        "model": {"rir_semantic_identity": rir["semantic_identity"]},
        "runtime": {
            "profile": "standard.exact-int64-event-v1",
            "required_evaluator": requirements,
        },
        "seed": {"algorithm": "splitmix64-v1", "value": 1},
        "scenarios": [
            {
                "id": "priority",
                "event_plan": events,
                "assignments": [value(k, v) for k, v in initial.items()],
                "named_streams": [],
                "terminal_condition": {"kind": "queue-drained"},
            }
        ],
        "metrics": [metric],
        "acceptance": {"policy": "all-metrics-within-target"},
    }
