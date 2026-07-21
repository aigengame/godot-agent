"""Generic interpreter with explicit pre-dispatch and post-dispatch boundaries."""

from __future__ import annotations

import platform
import sys
from typing import Any

from authority import (
    DIAGNOSTIC_AUTHORITY,
    EVENT_LAW,
    KERNEL,
    NUMERIC_PROFILE,
    RUNTIME_PROFILE_DEFINITION,
)
from canonical import artifact, clone, identity, verify_artifact
from projections import release_map


class PreDispatchRefusal(Exception):
    def __init__(self, stage: str, code: str, location: str) -> None:
        super().__init__(code)
        self.stage = stage
        self.code = code
        self.location = location

    def diagnostic(self) -> dict[str, str]:
        return {"stage": self.stage, "code": self.code, "location": self.location}


class RuntimeRefusal(Exception):
    def __init__(
        self,
        code: str,
        location: str,
        *,
        discarded_writes: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.location = location
        self.discarded_writes = {} if discarded_writes is None else discarded_writes


EVALUATOR_ID = "generic-closed-node-probe-v3"


def actual_platform() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "system": platform.system(),
        "sys_implementation": sys.implementation.name,
    }


def resolved_runtime_profile(
    bundle: dict[str, Any],
    built: dict[str, Any],
    *,
    max_event_writes: int = 32,
    max_events: int = 32,
) -> dict[str, Any]:
    return artifact(
        "resolved-runtime-profile",
        {
            "kernel": KERNEL["identity"],
            "language_bundle": bundle["identity"],
            "package_lock": built["lock"]["identity"],
            "rir": built["rir"]["identity"],
            "definition": RUNTIME_PROFILE_DEFINITION["identity"],
            "definition_id": RUNTIME_PROFILE_DEFINITION["id"],
            "numeric_profile": NUMERIC_PROFILE,
            "event_law": EVENT_LAW,
            "budgets": {
                "max_event_writes": max_event_writes,
                "max_events": max_events,
            },
            "evaluator": EVALUATOR_ID,
            "platform": actual_platform(),
        },
    )


def _read(state: dict[str, Any], path: str) -> Any:
    if path not in state:
        raise RuntimeRefusal("runtime.state-missing", f"$.state.{path}")
    return state[path]


def _expression(node: Any, snapshot: dict[str, Any]) -> Any:
    if not isinstance(node, dict) or not isinstance(node.get("node"), str):
        raise RuntimeRefusal("runtime.node-invalid", "$.program.expression")
    kind = node["node"]
    if kind == "literal":
        return clone(node["value"])
    if kind == "read":
        return clone(_read(snapshot, node["path"]))
    if kind in {"add", "sub", "gte", "eq", "min"}:
        left = _expression(node["left"], snapshot)
        right = _expression(node["right"], snapshot)
        if kind in {"add", "sub", "min", "gte"} and (
            type(left) is not int or type(right) is not int
        ):
            raise RuntimeRefusal("runtime.numeric-type-invalid", f"$.program.{kind}")
        if kind == "add":
            return left + right
        if kind == "sub":
            return left - right
        if kind == "gte":
            return left >= right
        if kind == "eq":
            return left == right
        return min(left, right)
    raise RuntimeRefusal("runtime.kernel-node-unknown", f"$.program.{kind}")


def _outcome(node: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag": node["tag"],
        "fields": {
            key: _expression(value, snapshot)
            for key, value in sorted(node["fields"].items())
        },
    }


def _program(
    node: dict[str, Any], snapshot: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    kind = node["node"]
    if kind == "branch":
        condition = _expression(node["condition"], snapshot)
        if type(condition) is not bool:
            raise RuntimeRefusal("runtime.condition-type-invalid", "$.program.branch")
        return _program(node["then"] if condition else node["else"], snapshot)
    if kind == "outcome":
        return _outcome(node, snapshot), {}
    if kind == "transaction":
        writes = {
            write["path"]: _expression(write["value"], snapshot)
            for write in node["writes"]
        }
        return _outcome(node["outcome"], snapshot), writes
    raise RuntimeRefusal("runtime.kernel-node-unknown", f"$.program.{kind}")


def _validate_outcome(outcome: dict[str, Any], result: dict[str, Any]) -> None:
    variants = result["variants"]
    tag = outcome["tag"]
    if tag not in variants or set(outcome["fields"]) != set(variants[tag]):
        raise RuntimeRefusal("runtime.outcome-invalid", f"$.outcome.{tag}")
    for name, expected in variants[tag].items():
        value = outcome["fields"][name]
        if expected == "Int" and type(value) is not int:
            raise RuntimeRefusal(
                "runtime.outcome-type-invalid", f"$.outcome.{tag}.{name}"
            )
        if expected == "Enum" and not isinstance(value, str):
            raise RuntimeRefusal(
                "runtime.outcome-type-invalid", f"$.outcome.{tag}.{name}"
            )


def _admit(
    bundle: dict[str, Any],
    built: dict[str, Any],
    experiment: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    lock = built["lock"]
    rir = built["rir"]
    for value, label in (
        (bundle, "bundle"),
        (lock, "lock"),
        (rir, "rir"),
        (experiment, "experiment"),
        (profile, "profile"),
    ):
        if not verify_artifact(value):
            raise PreDispatchRefusal(
                "ingress", "runtime.artifact-identity-invalid", f"$.{label}"
            )
    expected_profile_fields = {
        "kind",
        "identity",
        "kernel",
        "language_bundle",
        "package_lock",
        "rir",
        "definition",
        "definition_id",
        "numeric_profile",
        "event_law",
        "budgets",
        "evaluator",
        "platform",
    }
    if set(profile) != expected_profile_fields:
        raise PreDispatchRefusal(
            "runtime", "runtime.profile-shape-invalid", "$.profile"
        )
    budgets = profile.get("budgets")
    if (
        not isinstance(budgets, dict)
        or set(budgets) != {"max_event_writes", "max_events"}
        or any(type(value) is not int or value < 0 for value in budgets.values())
    ):
        raise PreDispatchRefusal(
            "runtime", "runtime.profile-budget-invalid", "$.profile.budgets"
        )
    expected_profile = {
        "kernel": KERNEL["identity"],
        "language_bundle": bundle["identity"],
        "package_lock": lock["identity"],
        "rir": rir["identity"],
        "definition": RUNTIME_PROFILE_DEFINITION["identity"],
        "definition_id": RUNTIME_PROFILE_DEFINITION["id"],
        "numeric_profile": NUMERIC_PROFILE,
        "event_law": EVENT_LAW,
    }
    for field, expected in expected_profile.items():
        if profile.get(field) != expected:
            raise PreDispatchRefusal(
                "runtime", "runtime.profile-binding-invalid", f"$.profile.{field}"
            )
    if profile["evaluator"] != EVALUATOR_ID:
        raise PreDispatchRefusal(
            "runtime", "runtime.profile-evaluator-mismatch", "$.profile.evaluator"
        )
    if profile["platform"] != actual_platform():
        raise PreDispatchRefusal(
            "runtime", "runtime.profile-platform-mismatch", "$.profile.platform"
        )
    if profile["definition_id"] not in lock["runtime_profiles"] or (
        lock["runtime_profiles"][profile["definition_id"]] != profile["definition"]
    ):
        raise PreDispatchRefusal(
            "runtime", "runtime.profile-definition-unselected", "$.profile.definition"
        )
    if profile["numeric_profile"] not in lock["numeric_profiles"]:
        raise PreDispatchRefusal(
            "runtime", "runtime.profile-numeric-unselected", "$.profile.numeric_profile"
        )
    if profile["event_law"] not in KERNEL["event_laws"]:
        raise PreDispatchRefusal(
            "runtime", "runtime.profile-event-law-unknown", "$.profile.event_law"
        )
    if (
        bundle["kernel"] != KERNEL["identity"]
        or lock["kernel"] != KERNEL["identity"]
        or rir["kernel"] != KERNEL["identity"]
    ):
        raise PreDispatchRefusal(
            "runtime", "runtime.kernel-binding-mismatch", "$.rir.kernel"
        )
    if (
        rir["language_bundle"] != bundle["identity"]
        or rir["package_lock"] != lock["identity"]
    ):
        raise PreDispatchRefusal("runtime", "runtime.rir-binding-mismatch", "$.rir")
    packages_by_identity = {
        release["identity"]: release for release in release_map(bundle).values()
    }
    use_sites: dict[str, dict[str, Any]] = {}
    for index, use_site in enumerate(rir["use_sites"]):
        binding = lock["operation_bindings"].get(use_site["operation"])
        if binding is None:
            raise PreDispatchRefusal(
                "runtime", "runtime.operation-unselected", f"$.rir.use_sites[{index}]"
            )
        if (
            binding["package_release"] != use_site["package_release"]
            or binding["version"] != use_site["version"]
            or binding["program_identity"] != use_site["program_identity"]
            or binding["operation_identity"] != use_site["operation_identity"]
        ):
            raise PreDispatchRefusal(
                "runtime",
                "runtime.operation-lock-mismatch",
                f"$.rir.use_sites[{index}]",
            )
        release = packages_by_identity.get(binding["package_release"])
        if release is None or not verify_artifact(release):
            raise PreDispatchRefusal(
                "runtime",
                "runtime.package-release-unavailable",
                f"$.rir.use_sites[{index}]",
            )
        operation = next(
            (
                item
                for item in release["operations"]
                if item["id"] == use_site["operation"]
            ),
            None,
        )
        if operation is None:
            raise PreDispatchRefusal(
                "runtime",
                "runtime.program-projection-mismatch",
                f"$.rir.use_sites[{index}]",
            )
        expected_use_site = {
            "id": use_site["id"],
            "operation": operation["id"],
            "package_release": release["identity"],
            "version": operation["version"],
            "parameters": clone(operation["parameters"]),
            "result": clone(operation["result"]),
            "state_contract": clone(operation["state_contract"]),
            "kind_rules": clone(operation["kind_rules"]),
            "unit_rules": clone(operation["unit_rules"]),
            "permitted_numeric_profiles": clone(
                operation["permitted_numeric_profiles"]
            ),
            "purity": operation["purity"],
            "effects": clone(operation["effects"]),
            "resource_bounds": clone(operation["resource_bounds"]),
            "operation_identity": identity(
                "operation-specification",
                {"package_release": release["identity"], **operation},
            ),
            "program": clone(operation["body"]),
            "program_identity": identity("operation-program", operation["body"]),
        }
        if use_site != expected_use_site:
            raise PreDispatchRefusal(
                "runtime",
                "runtime.operation-projection-mismatch",
                f"$.rir.use_sites[{index}]",
            )
        if profile["numeric_profile"] not in operation["permitted_numeric_profiles"]:
            raise PreDispatchRefusal(
                "runtime",
                "runtime.operation-numeric-profile-incompatible",
                f"$.rir.use_sites[{index}].permitted_numeric_profiles",
            )
        use_sites[use_site["id"]] = use_site
    expected_experiment_fields = {
        "kind",
        "identity",
        "id",
        "model_binding",
        "inputs",
        "event_sequence",
        "metric_selectors",
        "acceptance",
    }
    if set(experiment) != expected_experiment_fields or experiment.get(
        "model_binding"
    ) != {"policy": "exact-rir", "rir": rir["identity"]}:
        raise PreDispatchRefusal(
            "evaluation",
            "experiment.rir-binding-mismatch",
            "$.experiment.model_binding",
        )
    input_paths = {
        symbol["state_path"]: clone(symbol["type"])
        for symbol in rir["symbols"]
        if symbol["role"] == "input"
    }
    inputs = experiment.get("inputs")
    if not isinstance(inputs, dict):
        raise PreDispatchRefusal(
            "evaluation", "experiment.inputs-invalid", "$.experiment.inputs"
        )
    unknown_inputs = sorted(set(inputs) - set(input_paths))
    if unknown_inputs:
        raise PreDispatchRefusal(
            "evaluation",
            "experiment.input-not-declared",
            f"$.experiment.inputs.{unknown_inputs[0]}",
        )
    for path, value in inputs.items():
        symbol_type = input_paths[path]
        if symbol_type["representation"] == "Int" and type(value) is not int:
            raise PreDispatchRefusal(
                "evaluation",
                "experiment.input-type-invalid",
                f"$.experiment.inputs.{path}",
            )
        support = symbol_type["support"]
        if not support["minimum"] <= value <= support["maximum"]:
            raise PreDispatchRefusal(
                "evaluation",
                "experiment.input-support-invalid",
                f"$.experiment.inputs.{path}",
            )
    event_sequence = experiment.get("event_sequence")
    if not isinstance(event_sequence, list):
        raise PreDispatchRefusal(
            "evaluation",
            "experiment.event-sequence-invalid",
            "$.experiment.event_sequence",
        )
    for index, event in enumerate(event_sequence, start=1):
        if (
            not isinstance(event, dict)
            or set(event) != {"sequence", "use_site"}
            or event.get("sequence") != index
            or event.get("use_site") not in use_sites
        ):
            raise PreDispatchRefusal(
                "evaluation",
                "experiment.event-sequence-invalid",
                "$.experiment.event_sequence",
            )
    admitted_selectors = {"all-exported-quantities", "all-operation-outcomes"}
    selectors = experiment.get("metric_selectors")
    if not isinstance(selectors, list):
        raise PreDispatchRefusal(
            "evaluation",
            "experiment.selector-invalid",
            "$.experiment.metric_selectors",
        )
    for index, selector in enumerate(selectors):
        if (
            not isinstance(selector, dict)
            or set(selector) != {"kind"}
            or selector.get("kind") not in admitted_selectors
        ):
            raise PreDispatchRefusal(
                "evaluation",
                "experiment.selector-unknown",
                f"$.experiment.metric_selectors[{index}]",
            )
    acceptance = experiment.get("acceptance")
    if not isinstance(acceptance, dict) or acceptance.get("kind") not in {
        "terminal-status",
        "final-value",
    }:
        raise PreDispatchRefusal(
            "evaluation", "experiment.acceptance-unknown", "$.experiment.acceptance"
        )
    if acceptance["kind"] == "terminal-status":
        if set(acceptance) != {"kind", "equals"} or not isinstance(
            acceptance.get("equals"), str
        ):
            raise PreDispatchRefusal(
                "evaluation",
                "experiment.acceptance-invalid",
                "$.experiment.acceptance",
            )
    else:
        all_state_paths = set(rir["initial_literals"]) | {
            symbol["state_path"] for symbol in rir["symbols"]
        }
        if (
            set(acceptance) != {"kind", "path", "equals"}
            or acceptance.get("path") not in all_state_paths
        ):
            raise PreDispatchRefusal(
                "evaluation",
                "experiment.acceptance-invalid",
                "$.experiment.acceptance",
            )
    binding = artifact(
        "experiment-final-binding-receipt",
        {
            "experiment": experiment["identity"],
            "rir": rir["identity"],
            "exact_binding_verified": True,
            "validated_inputs": sorted(experiment["inputs"]),
            "validated_use_sites": [
                event["use_site"] for event in experiment["event_sequence"]
            ],
        },
    )
    return {"use_sites": use_sites, "binding": binding}


def _initial_state(rir: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
    state = clone(rir["initial_literals"])
    for symbol in rir["symbols"]:
        state[symbol["state_path"]] = symbol["initial"]
    state.update(clone(experiment["inputs"]))
    return state


def _select_metrics(
    selectors: list[dict[str, Any]],
    rir: dict[str, Any],
    state: dict[str, Any],
    outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for selector in selectors:
        if selector["kind"] == "all-exported-quantities":
            samples.extend(
                {
                    "metric": f"symbol.final.{symbol['symbol'].rsplit('::', 1)[-1]}",
                    "value": state[symbol["state_path"]],
                    "type": clone(symbol["type"]),
                }
                for symbol in rir["symbols"]
                if symbol["export"]
            )
        elif selector["kind"] == "all-operation-outcomes":
            samples.extend(
                {
                    "metric": "operation.outcome",
                    "operation": outcome["operation"],
                    "tag": outcome["tag"],
                    "payload": clone(outcome["fields"]),
                }
                for outcome in outcomes
            )
    return samples


def _verdict(acceptance: dict[str, Any], state: dict[str, Any]) -> str:
    if acceptance["kind"] == "terminal-status":
        accepted = acceptance.get("equals") == "completed"
    else:
        path = acceptance.get("path")
        accepted = isinstance(path, str) and state.get(path) == acceptance.get("equals")
    return "satisfied" if accepted else "unsatisfied"


def _validate_runtime_diagnostic(diagnostic: dict[str, Any]) -> None:
    if set(diagnostic) != {
        "code",
        "message",
        "primary_location",
        "related_locations",
    }:
        raise RuntimeError("runtime-diagnostic-shape-invalid")
    definition = DIAGNOSTIC_AUTHORITY["diagnostics"].get(diagnostic["code"])
    if definition is None or diagnostic["message"] != definition["message"]:
        raise RuntimeError("runtime-diagnostic-authority-mismatch")
    related = diagnostic["related_locations"]
    if not isinstance(related, list):
        raise RuntimeError("runtime-diagnostic-location-invalid")
    for location in [diagnostic["primary_location"], *related]:
        if (
            not isinstance(location, dict)
            or set(location) != {"kind", "sequence", "use_site", "path"}
            or location["kind"] != "runtime-event"
            or location["kind"] not in DIAGNOSTIC_AUTHORITY["location_tags"]
            or type(location["sequence"]) is not int
            or location["sequence"] < 1
            or not isinstance(location["use_site"], str)
            or not location["use_site"]
            or not isinstance(location["path"], str)
            or not location["path"]
        ):
            raise RuntimeError("runtime-diagnostic-location-invalid")


def _runtime_diagnostic(
    refusal: RuntimeRefusal, current_event: dict[str, Any]
) -> dict[str, Any]:
    if not verify_artifact(DIAGNOSTIC_AUTHORITY):
        raise RuntimeError("prototype-diagnostic-authority-invalid")
    definition = DIAGNOSTIC_AUTHORITY["diagnostics"].get(refusal.code)
    if definition is None or definition["stage"] != "runtime":
        raise RuntimeError("runtime-diagnostic-code-unauthorized")
    diagnostic = {
        "code": refusal.code,
        "message": definition["message"],
        "primary_location": {
            "kind": "runtime-event",
            "sequence": current_event["sequence"],
            "use_site": current_event["use_site"],
            "path": refusal.location,
        },
        "related_locations": [],
    }
    _validate_runtime_diagnostic(diagnostic)
    return diagnostic


def execute(
    bundle: dict[str, Any],
    built: dict[str, Any],
    experiment: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_profile = (
        resolved_runtime_profile(bundle, built) if profile is None else clone(profile)
    )
    rir = built["rir"]
    try:
        admitted = _admit(bundle, built, experiment, selected_profile)
    except PreDispatchRefusal as refusal:
        return {
            "status": "refused",
            "phase": "pre-dispatch",
            "stage": refusal.stage,
            "diagnostic": refusal.diagnostic(),
            "terminal_audit": None,
            "replay": None,
            "evidence": None,
        }
    state = _initial_state(rir, experiment)
    initial = clone(state)
    snapshots = [artifact("runtime-snapshot", {"sequence": 0, "state": clone(state)})]
    trace: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    budgets = selected_profile["budgets"]
    if len(experiment["event_sequence"]) > budgets["max_events"]:
        current_event = clone(experiment["event_sequence"][budgets["max_events"]])
        refusal = RuntimeRefusal(
            "runtime.event-budget",
            f"$.experiment.event_sequence[{budgets['max_events']}]",
        )
    else:
        refusal = None
        current_event = None
        for event_spec in experiment["event_sequence"]:
            current_event = clone(event_spec)
            use_site = admitted["use_sites"][event_spec["use_site"]]
            snapshot = clone(state)
            try:
                outcome, writes = _program(use_site["program"], snapshot)
                _validate_outcome(outcome, use_site["result"])
                if len(writes) > budgets["max_event_writes"]:
                    raise RuntimeRefusal(
                        "runtime.event-write-budget",
                        f"$.experiment.event_sequence[{event_spec['sequence'] - 1}]",
                        discarded_writes=clone(writes),
                    )
                state.update(writes)
                trace.append(
                    {
                        "sequence": event_spec["sequence"],
                        "use_site": event_spec["use_site"],
                        "operation": use_site["operation"],
                        "snapshot_reads_from": snapshots[-1]["identity"],
                        "outcome": clone(outcome),
                        "committed_writes": clone(writes),
                    }
                )
                outcomes.append({"operation": use_site["operation"], **clone(outcome)})
                snapshots.append(
                    artifact(
                        "runtime-snapshot",
                        {"sequence": event_spec["sequence"], "state": clone(state)},
                    )
                )
            except RuntimeRefusal as error:
                refusal = error
                break
    if refusal is not None:
        if current_event is None:
            raise RuntimeError("runtime-refusal-event-missing")
        audit = artifact(
            "terminal-audit",
            {
                "committed_trace_prefix": clone(trace),
                "last_snapshot": clone(snapshots[-1]),
                "refusing_event": current_event,
                "rollback": {
                    "discarded_writes": clone(refusal.discarded_writes),
                    "state_unchanged_from_last_snapshot": state
                    == snapshots[-1]["state"],
                },
                "refusal_stage": "runtime",
                "diagnostic_authority": DIAGNOSTIC_AUTHORITY["identity"],
                "diagnostic": _runtime_diagnostic(refusal, current_event),
                "resolved_runtime_profile": selected_profile["identity"],
                "reproduction": {
                    "kernel": KERNEL["identity"],
                    "language_bundle": bundle["identity"],
                    "package_lock": built["lock"]["identity"],
                    "rir": rir["identity"],
                    "experiment": experiment["identity"],
                    "profile": selected_profile["identity"],
                    "diagnostic_authority": DIAGNOSTIC_AUTHORITY["identity"],
                },
                "partial_success_artifacts": [],
            },
        )
        return {
            "status": "refused",
            "phase": "post-dispatch",
            "stage": "runtime",
            "profile": selected_profile,
            "experiment": clone(experiment),
            "experiment_binding": admitted["binding"],
            "snapshots": snapshots,
            "terminal_audit": audit,
            "replay": None,
            "evidence": None,
        }
    run = artifact(
        "runtime-run",
        {
            "rir": rir["identity"],
            "experiment": experiment["identity"],
            "profile": selected_profile["identity"],
            "initial_state": initial,
            "final_state": clone(state),
            "trace": trace,
            "snapshots": [snapshot["identity"] for snapshot in snapshots],
            "outcomes": outcomes,
            "terminal_status": "completed",
        },
    )
    samples = _select_metrics(experiment["metric_selectors"], rir, state, outcomes)
    metrics = artifact(
        "metric-dataset",
        {
            "experiment_binding": admitted["binding"]["identity"],
            "run": run["identity"],
            "samples": samples,
            "selector_identity": identity(
                "metric-selectors", experiment["metric_selectors"]
            ),
        },
    )
    evaluation = artifact(
        "evaluation-run",
        {
            "experiment_binding": admitted["binding"]["identity"],
            "rir": rir["identity"],
            "runtime_run": run["identity"],
            "metrics": metrics["identity"],
            "acceptance": clone(experiment["acceptance"]),
            "verdict": _verdict(experiment["acceptance"], state),
            "semantic_authority_gate": "unvalidated",
            "normative_evidence_issued": False,
        },
    )
    return {
        "status": "completed",
        "phase": "post-dispatch",
        "profile": selected_profile,
        "snapshots": snapshots,
        "run": run,
        "experiment": clone(experiment),
        "experiment_binding": admitted["binding"],
        "metrics": metrics,
        "evaluation": evaluation,
        "replay": None,
        "evidence": None,
    }
