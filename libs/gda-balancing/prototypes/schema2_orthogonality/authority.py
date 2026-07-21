"""Fixture authorities for the disposable orthogonality probe.

Every extension is one complete content-addressed ``domain-package-release``.
There is no second package/mechanic assembly registry.
"""

from __future__ import annotations

from typing import Any

from canonical import artifact, clone, identity


EVENT_LAW = "snapshot-read-buffered-single-final-write-v1"
NUMERIC_PROFILE = "exact-int-v1"
RUNTIME_PROFILE_DEFINITION = artifact(
    "runtime-profile-definition",
    {
        "id": "sequential-atomic-v1",
        "numeric_profile": NUMERIC_PROFILE,
        "event_law": EVENT_LAW,
        "budget_names": ["max_event_writes", "max_events"],
    },
)

KERNEL = artifact(
    "kernel-specification",
    {
        "schema_major": 2,
        "constructors": ["Bool", "Enum", "Int", "List", "Quantity", "Record"],
        "nodes": [
            "add",
            "branch",
            "eq",
            "gte",
            "literal",
            "min",
            "outcome",
            "read",
            "sub",
            "transaction",
            "write",
        ],
        "event_laws": [EVENT_LAW],
        "canonical_profile": "probe-canonical-json-v1",
    },
)

DIAGNOSTIC_AUTHORITY = artifact(
    "prototype-diagnostic-authority",
    {
        "diagnostics": {
            "runtime.condition-type-invalid": {
                "stage": "runtime",
                "message": "A branch condition did not produce Bool.",
            },
            "runtime.event-budget": {
                "stage": "runtime",
                "message": "The Experiment event count exceeded the resolved Runtime budget.",
            },
            "runtime.event-write-budget": {
                "stage": "runtime",
                "message": "The Event write set exceeded the resolved Runtime budget.",
            },
            "runtime.kernel-node-unknown": {
                "stage": "runtime",
                "message": "The RIR contains an unknown Kernel node.",
            },
            "runtime.numeric-type-invalid": {
                "stage": "runtime",
                "message": "A numeric Kernel node received a non-Int value.",
            },
            "runtime.outcome-invalid": {
                "stage": "runtime",
                "message": "The completed operation produced an invalid outcome shape.",
            },
            "runtime.outcome-type-invalid": {
                "stage": "runtime",
                "message": "The completed operation produced an invalid outcome payload type.",
            },
            "runtime.state-missing": {
                "stage": "runtime",
                "message": "The Event attempted to read an unavailable state slot.",
            },
        },
        "location_tags": ["runtime-event", "runtime-profile"],
    },
)


def _operation(
    operation_id: str,
    *,
    result: dict[str, Any],
    state_contract: dict[str, str],
    kind_rules: dict[str, str],
    unit_rules: dict[str, str | None],
    reads: list[str],
    writes: list[str],
    body: dict[str, Any],
    max_reads: int,
    max_writes: int,
) -> dict[str, Any]:
    return {
        "id": operation_id,
        "version": 1,
        "parameters": {},
        "result": result,
        "state_contract": state_contract,
        "kind_rules": kind_rules,
        "unit_rules": unit_rules,
        "permitted_numeric_profiles": [NUMERIC_PROFILE],
        "purity": "effectful",
        "effects": {
            "state_reads": reads,
            "state_writes": writes,
            "emitted_signals": [],
            "scheduled_events": [],
            "canceled_events": [],
            "named_random_streams": [],
        },
        "resource_bounds": {"max_reads": max_reads, "max_writes": max_writes},
        "body": body,
    }


RESOURCE_OPERATION = _operation(
    "game.resource.reserve",
    result={
        "kind": "ResourceReservationOutcome",
        "variants": {
            "insufficient": {"available": "Int", "required": "Int"},
            "reserved": {"amount": "Int"},
        },
    },
    state_contract={"reservation.amount": "Int", "resource.current": "Int"},
    kind_rules={
        "reservation.amount": "game.resource.generic",
        "resource.current": "game.resource.generic",
    },
    unit_rules={"reservation.amount": "game:point", "resource.current": "game:point"},
    reads=["resource.current"],
    writes=["reservation.amount", "resource.current"],
    max_reads=1,
    max_writes=2,
    body={
        "node": "branch",
        "condition": {
            "node": "gte",
            "left": {"node": "read", "path": "resource.current"},
            "right": {"node": "literal", "value": 3},
        },
        "then": {
            "node": "transaction",
            "writes": [
                {
                    "node": "write",
                    "path": "resource.current",
                    "value": {
                        "node": "sub",
                        "left": {"node": "read", "path": "resource.current"},
                        "right": {"node": "literal", "value": 3},
                    },
                },
                {
                    "node": "write",
                    "path": "reservation.amount",
                    "value": {"node": "literal", "value": 3},
                },
            ],
            "outcome": {
                "node": "outcome",
                "tag": "reserved",
                "fields": {"amount": {"node": "literal", "value": 3}},
            },
        },
        "else": {
            "node": "outcome",
            "tag": "insufficient",
            "fields": {
                "available": {"node": "read", "path": "resource.current"},
                "required": {"node": "literal", "value": 3},
            },
        },
    },
)

INTERRUPT_OPERATION = _operation(
    "game.action.interrupt",
    result={
        "kind": "InterruptionOutcome",
        "variants": {
            "interrupted": {"refunded": "Int"},
            "not_interruptible": {"reason": "Enum"},
        },
    },
    state_contract={
        "action.status": "Enum",
        "reservation.amount": "Int",
        "resource.current": "Int",
    },
    kind_rules={
        "action.status": "Enum",
        "reservation.amount": "game.resource.generic",
        "resource.current": "game.resource.generic",
    },
    unit_rules={
        "action.status": None,
        "reservation.amount": "game:point",
        "resource.current": "game:point",
    },
    reads=["reservation.amount", "resource.current"],
    writes=["action.status", "reservation.amount", "resource.current"],
    max_reads=2,
    max_writes=3,
    body={
        "node": "branch",
        "condition": {
            "node": "gte",
            "left": {"node": "read", "path": "reservation.amount"},
            "right": {"node": "literal", "value": 1},
        },
        "then": {
            "node": "transaction",
            "writes": [
                {
                    "node": "write",
                    "path": "resource.current",
                    "value": {
                        "node": "add",
                        "left": {"node": "read", "path": "resource.current"},
                        "right": {"node": "read", "path": "reservation.amount"},
                    },
                },
                {
                    "node": "write",
                    "path": "reservation.amount",
                    "value": {"node": "literal", "value": 0},
                },
                {
                    "node": "write",
                    "path": "action.status",
                    "value": {"node": "literal", "value": "interrupted"},
                },
            ],
            "outcome": {
                "node": "outcome",
                "tag": "interrupted",
                "fields": {"refunded": {"node": "read", "path": "reservation.amount"}},
            },
        },
        "else": {
            "node": "outcome",
            "tag": "not_interruptible",
            "fields": {"reason": {"node": "literal", "value": "no-reservation"}},
        },
    },
)


def _effect_operation(
    operation_id: str,
    tag: str,
    result_kind: str,
    fields: dict[str, Any],
    writes: list[dict[str, Any]],
    reads: list[str],
) -> dict[str, Any]:
    return _operation(
        operation_id,
        result={
            "kind": result_kind,
            "variants": {tag: {name: "Int" for name in fields}},
        },
        state_contract={
            "effect.duration": "Int",
            "effect.stacks": "Int",
        },
        kind_rules={
            "effect.duration": "game.stat.generic",
            "effect.stacks": "game.stat.generic",
        },
        unit_rules={"effect.duration": "game:point", "effect.stacks": "game:point"},
        reads=reads,
        writes=["effect.duration", "effect.stacks"],
        max_reads=len(reads),
        max_writes=2,
        body={
            "node": "transaction",
            "writes": writes,
            "outcome": {"node": "outcome", "tag": tag, "fields": fields},
        },
    )


READ_STACKS = {"node": "read", "path": "effect.stacks"}
READ_DURATION = {"node": "read", "path": "effect.duration"}
EFFECT_OPERATIONS = [
    _effect_operation(
        "game.effect.apply",
        "applied",
        "EffectApplyOutcome",
        {"stacks": {"node": "literal", "value": 1}},
        [
            {
                "node": "write",
                "path": "effect.stacks",
                "value": {"node": "literal", "value": 1},
            },
            {
                "node": "write",
                "path": "effect.duration",
                "value": {"node": "literal", "value": 3},
            },
        ],
        [],
    ),
    _effect_operation(
        "game.effect.reapply",
        "reapplied",
        "EffectReapplyOutcome",
        {"previous_duration": READ_DURATION, "previous_stacks": READ_STACKS},
        [
            {
                "node": "write",
                "path": "effect.stacks",
                "value": {
                    "node": "min",
                    "left": {
                        "node": "add",
                        "left": READ_STACKS,
                        "right": {"node": "literal", "value": 1},
                    },
                    "right": {"node": "literal", "value": 3},
                },
            },
            {
                "node": "write",
                "path": "effect.duration",
                "value": {"node": "literal", "value": 5},
            },
        ],
        ["effect.duration", "effect.stacks"],
    ),
    _effect_operation(
        "game.effect.remove",
        "removed",
        "EffectRemovalOutcome",
        {"removed_stacks": READ_STACKS},
        [
            {
                "node": "write",
                "path": "effect.stacks",
                "value": {"node": "literal", "value": 0},
            },
            {
                "node": "write",
                "path": "effect.duration",
                "value": {"node": "literal", "value": 0},
            },
        ],
        ["effect.stacks"],
    ),
]


DOMAIN_PACKAGE_RELEASES: dict[str, dict[str, Any]] = {
    "foundation": artifact(
        "domain-package-release",
        {
            "id": "game.foundation",
            "version": "2.0.0-probe",
            "dependencies": [],
            "provides": ["game.model"],
            "requires_capabilities": [],
            "quantity_kinds": [
                {
                    "id": "game.resource.generic",
                    "representation": "Int",
                    "unit": "game:point",
                    "numeric_profile": NUMERIC_PROFILE,
                },
                {
                    "id": "game.stat.generic",
                    "representation": "Int",
                    "unit": "game:point",
                    "numeric_profile": NUMERIC_PROFILE,
                },
            ],
            "units": ["game:point"],
            "numeric_profiles": [NUMERIC_PROFILE],
            "runtime_profiles": [clone(RUNTIME_PROFILE_DEFINITION)],
            "operations": [],
            "vectors": [
                {"id": "foundation.quantity.support", "minimum": 0, "maximum": 999}
            ],
            "diagnostics": [
                "static.quantity-authority-invalid",
                "runtime.profile-binding-invalid",
            ],
        },
    ),
    "resource": artifact(
        "domain-package-release",
        {
            "id": "game.resource",
            "version": "1.0.0",
            "dependencies": [{"package": "game.foundation", "version": "=2.0.0-probe"}],
            "provides": ["game.resource.reservation@1"],
            "requires_capabilities": ["game.model"],
            "quantity_kinds": [],
            "units": [],
            "numeric_profiles": [],
            "runtime_profiles": [],
            "operations": [RESOURCE_OPERATION],
            "vectors": [
                {"id": "resource.reserved", "input": 10, "tag": "reserved"},
                {"id": "resource.insufficient", "input": 2, "tag": "insufficient"},
            ],
            "diagnostics": ["runtime.resource-state-missing"],
        },
    ),
    "interruption": artifact(
        "domain-package-release",
        {
            "id": "game.action",
            "version": "1.0.0",
            "dependencies": [{"package": "game.resource", "version": "=1.0.0"}],
            "provides": ["game.action.interruption@1"],
            "requires_capabilities": ["game.resource.reservation@1"],
            "quantity_kinds": [],
            "units": [],
            "numeric_profiles": [],
            "runtime_profiles": [],
            "operations": [INTERRUPT_OPERATION],
            "vectors": [
                {"id": "interrupt.refund", "reservation": 3, "tag": "interrupted"},
                {
                    "id": "interrupt.absent",
                    "reservation": 0,
                    "tag": "not_interruptible",
                },
            ],
            "diagnostics": ["runtime.interruption-state-missing"],
        },
    ),
    "effect": artifact(
        "domain-package-release",
        {
            "id": "game.effect",
            "version": "1.0.0",
            "dependencies": [{"package": "game.foundation", "version": "=2.0.0-probe"}],
            "provides": ["game.effect.lifecycle@1"],
            "requires_capabilities": ["game.model"],
            "quantity_kinds": [],
            "units": [],
            "numeric_profiles": [],
            "runtime_profiles": [],
            "operations": EFFECT_OPERATIONS,
            "vectors": [
                {"id": "effect.apply", "before": 0, "after": 1},
                {"id": "effect.reapply", "before": 1, "after": 2},
                {"id": "effect.remove", "before": 2, "after": 0},
            ],
            "diagnostics": ["runtime.effect-state-missing"],
        },
    ),
}


def base_bundle() -> dict[str, Any]:
    return artifact(
        "language-definition-bundle",
        {
            "kernel": KERNEL["identity"],
            "version": "2.0.0-orthogonality-probe",
            "packages": [clone(DOMAIN_PACKAGE_RELEASES["foundation"])],
        },
    )


def extend_bundle(bundle: dict[str, Any], extension: str) -> dict[str, Any]:
    if extension == "foundation" or extension not in DOMAIN_PACKAGE_RELEASES:
        raise ValueError("bundle.extension-unknown")
    extended = clone(bundle)
    release = clone(DOMAIN_PACKAGE_RELEASES[extension])
    if any(item["id"] == release["id"] for item in extended["packages"]):
        raise ValueError("bundle.extension-duplicate")
    extended["packages"].append(release)
    extended["packages"].sort(key=lambda item: item["id"])
    extended["identity"] = identity(
        extended["kind"],
        {key: value for key, value in extended.items() if key != "identity"},
    )
    return extended


def full_bundle() -> dict[str, Any]:
    bundle = base_bundle()
    for extension in ("resource", "interruption", "effect"):
        bundle = extend_bundle(bundle, extension)
    return bundle


def _quantity(
    symbol_id: str,
    kind: str,
    role: str,
    initial: int,
    state_path: str,
) -> dict[str, Any]:
    return {
        "id": symbol_id,
        "type": {
            "constructor": "Quantity",
            "representation": "Int",
            "kind": kind,
            "unit": "game:point",
            "support": {"minimum": 0, "maximum": 999},
            "numeric_profile": NUMERIC_PROFILE,
        },
        "role": role,
        "initial": initial,
        "state_path": state_path,
        "export": True,
    }


USE_SITES: dict[str, dict[str, Any]] = {
    "reserve": {
        "operation": "game.resource.reserve",
        "match": [
            {"tag": "insufficient", "payload": {"available": "Int", "required": "Int"}},
            {"tag": "reserved", "payload": {"amount": "Int"}},
        ],
    },
    "interrupt": {
        "operation": "game.action.interrupt",
        "match": [
            {"tag": "interrupted", "payload": {"refunded": "Int"}},
            {"tag": "not_interruptible", "payload": {"reason": "Enum"}},
        ],
    },
    "effect_apply": {
        "operation": "game.effect.apply",
        "match": [{"tag": "applied", "payload": {"stacks": "Int"}}],
    },
    "effect_reapply": {
        "operation": "game.effect.reapply",
        "match": [
            {
                "tag": "reapplied",
                "payload": {"previous_duration": "Int", "previous_stacks": "Int"},
            }
        ],
    },
    "effect_remove": {
        "operation": "game.effect.remove",
        "match": [{"tag": "removed", "payload": {"removed_stacks": "Int"}}],
    },
}


def model_source(
    *,
    extra_attribute: bool = False,
    extensions: tuple[str, ...] = ("resource", "interruption", "effect"),
) -> dict[str, Any]:
    symbols = [
        _quantity("health", "game.stat.generic", "state", 12, "attributes.health"),
        _quantity("resource", "game.resource.generic", "input", 10, "resource.current"),
    ]
    if extra_attribute:
        symbols.append(
            _quantity("focus", "game.stat.generic", "state", 7, "attributes.focus")
        )
    requirements = [{"package": "game.foundation", "version": "=2.0.0-probe"}]
    extension_requirements = {
        "resource": {"package": "game.resource", "version": "=1.0.0"},
        "interruption": {"package": "game.action", "version": "=1.0.0"},
        "effect": {"package": "game.effect", "version": "=1.0.0"},
    }
    for extension in extensions:
        requirements.append(clone(extension_requirements[extension]))
    use_names: list[str] = []
    if "resource" in extensions:
        use_names.append("reserve")
    if "interruption" in extensions:
        use_names.append("interrupt")
    if "effect" in extensions:
        use_names.extend(["effect_apply", "effect_reapply", "effect_remove"])
    return artifact(
        "model-source-package",
        {
            "package": {"id": "probe.game", "version": "1.0.0"},
            "requires": requirements,
            "symbols": symbols,
            "state_literals": {
                "action.status": {"type": "Enum", "value": "ready"},
                "effect.duration": {"type": "Int", "value": 0},
                "effect.stacks": {"type": "Int", "value": 0},
                "reservation.amount": {"type": "Int", "value": 0},
            },
            "use_sites": [{"id": name, **clone(USE_SITES[name])} for name in use_names],
        },
    )


def experiment(
    scenario: str,
    rir_identity: str,
    *,
    selectors: list[dict[str, Any]] | None = None,
    acceptance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenarios = {
        "success": {"inputs": {"resource.current": 10}, "events": ["reserve"]},
        "insufficient": {"inputs": {"resource.current": 2}, "events": ["reserve"]},
        "interrupted": {
            "inputs": {"resource.current": 10},
            "events": ["reserve", "interrupt"],
        },
        "effect_lifecycle": {
            "inputs": {},
            "events": ["effect_apply", "effect_reapply", "effect_remove"],
        },
    }
    if scenario not in scenarios:
        raise ValueError("experiment.fixture-unknown")
    chosen_selectors = (
        [
            {"kind": "all-exported-quantities"},
            {"kind": "all-operation-outcomes"},
        ]
        if selectors is None
        else clone(selectors)
    )
    chosen_acceptance = (
        {"kind": "terminal-status", "equals": "completed"}
        if acceptance is None
        else clone(acceptance)
    )
    fixture = scenarios[scenario]
    return artifact(
        "experiment-specification",
        {
            "id": f"orthogonality.{scenario}",
            "model_binding": {"policy": "exact-rir", "rir": rir_identity},
            "inputs": clone(fixture["inputs"]),
            "event_sequence": [
                {"sequence": index, "use_site": use_site}
                for index, use_site in enumerate(fixture["events"], start=1)
            ],
            "metric_selectors": chosen_selectors,
            "acceptance": chosen_acceptance,
        },
    )
