"""Descriptor-routed structured subprocess surface for the disposable probe."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from authority import language_bundle, runtime_profile
from canonical import identity
from descriptor import BindingRefusal, COMMANDS, bind
from pipeline import build, build_members, compare_cross_evaluator, execute
from store import ArtifactStore, DeliveryFailure, InvocationConflict, PublicationError


Handler = Callable[[dict[str, Any], ArtifactStore], dict[str, Any]]


def _handle_build(bound: dict[str, Any], _store: ArtifactStore) -> dict[str, Any]:
    parameters = bound["params"]
    selected_bundle = None
    if parameters["bundle_fixture"] != "valid":
        selected_bundle = language_bundle()
        if parameters["bundle_fixture"] == "malformed-rule":
            selected_bundle["rules"][0]["premises"] = {"not": "a-list"}
            selected_bundle["identity"] = identity(
                "ldb",
                {
                    key: value
                    for key, value in selected_bundle.items()
                    if key != "identity"
                },
            )
        else:
            selected_bundle["identity"] = f"sha256:ldb:{'0' * 64}"
    result = build(
        parameters["compiler"],
        parameters["source_variant"],
        bundle=selected_bundle,
        base_damage=parameters["base_damage"],
    )
    if result["status"] != "completed":
        return {
            "outcome": "refused",
            "stage": result["admission"]["refusal_stage"],
            "diagnostics": result["admission"]["diagnostics"],
        }
    return {
        "outcome": "completed",
        "set_kind": "build-artifact-set",
        "members": build_members(result),
    }


def _handle_run(bound: dict[str, Any], _store: ArtifactStore) -> dict[str, Any]:
    parameters = bound["params"]
    profile = runtime_profile(
        max_steps=parameters["max_steps"], max_draws=parameters["max_draws"]
    )
    result = execute(
        parameters["compiler"],
        parameters["evaluator"],
        parameters["source_variant"],
        parameters["scenario"],
        profile,
        base_damage=parameters["base_damage"],
    )
    if result["status"] == "refused":
        if "runtime" not in result:
            return {
                "outcome": "refused",
                "stage": result["admission"]["refusal_stage"],
                "diagnostics": result["admission"]["diagnostics"],
            }
        terminal = result["runtime"]["terminal_audit"]
        members = build_members(result["build"])
        members.extend([result["runtime"]["profile"], terminal])
        return {
            "outcome": "refused",
            "stage": "runtime",
            "diagnostics": [terminal["diagnostic"]],
            "set_kind": "terminal-audit-artifact-set",
            "members": members,
        }
    members = build_members(result["build"])
    members.extend([result["runtime"]["profile"], result["runtime"]["run"]])
    return {
        "outcome": "completed",
        "set_kind": "evaluation-artifact-set",
        "members": members,
    }


def _handle_compare(bound: dict[str, Any], _store: ArtifactStore) -> dict[str, Any]:
    result = compare_cross_evaluator()
    if result["status"] != "completed":
        return {
            "outcome": "refused",
            "stage": result["stage"],
            "diagnostics": result["diagnostics"],
            "gate_report": result["gate_report"],
        }
    raise PublicationError("comparison.unexpected-positive-without-evidence-handler")


def _handle_inspect(bound: dict[str, Any], store: ArtifactStore) -> dict[str, Any]:
    target = COMMANDS[bound["params"]["target_command"]]
    recorded = store.lookup(target["identity"], bound["invocation_key"])
    if recorded is None:
        return {
            "outcome": "refused",
            "stage": "ingress",
            "diagnostics": [{"code": "artifact.not-found", "detail": "invocation_key"}],
        }
    return {
        "outcome": "completed",
        "result": {
            "stored_outcome": recorded["outcome"],
            "set_kind": recorded["set_kind"],
            "receipt": recorded["receipt"],
            "locator": _locator(recorded),
        },
    }


HANDLER_IMPLEMENTATIONS: dict[str, Handler] = {
    "build.v1": _handle_build,
    "run.v1": _handle_run,
    "compare.v1": _handle_compare,
    "inspect.v1": _handle_inspect,
}


def dispatch(bound: dict[str, Any]) -> dict[str, Any]:
    descriptor = bound["descriptor"]
    store = ArtifactStore(Path(bound["store"]))
    if descriptor["artifact_producing"]:
        replay = store.preflight(
            bound["descriptor_identity"],
            bound["invocation_key"],
            bound["canonical_input_identity"],
        )
        if replay is not None:
            return _record_envelope(replay, retry=True)
    handler_id = descriptor["handler"]
    handler = HANDLER_IMPLEMENTATIONS.get(handler_id)
    if handler is None:
        raise PublicationError("descriptor.handler-unimplemented")
    result = handler(bound, store)
    _validate_declared_outcome(descriptor, result)
    if result["outcome"] == "refused" and "set_kind" not in result:
        return _refusal_envelope(
            result["stage"], result["diagnostics"], result.get("gate_report")
        )
    if not descriptor["artifact_producing"]:
        if result["outcome"] == "completed":
            return {"outcome": "completed", "result": result["result"]}
        return _refusal_envelope(result["stage"], result["diagnostics"])
    committed_outcome = {
        "outcome": result["outcome"],
        **(
            {"stage": result["stage"], "diagnostics": result["diagnostics"]}
            if result["outcome"] == "refused"
            else {}
        ),
    }
    record = store.publish(
        bound["descriptor_identity"],
        bound["invocation_key"],
        bound["canonical_input_identity"],
        result["set_kind"],
        committed_outcome,
        result["members"],
        fault=bound["params"].get("fault", "none"),
    )
    return _record_envelope(record, retry=bool(record.get("_idempotent_replay", False)))


def _validate_declared_outcome(
    descriptor: dict[str, Any], result: dict[str, Any]
) -> None:
    if result.get("outcome") == "completed":
        success = descriptor["outcomes"].get("success")
        if success is None:
            raise PublicationError("descriptor.success-undeclared")
        declared = success["artifact_set_kinds"]
        actual = result.get("set_kind")
        if descriptor["artifact_producing"] and actual not in declared:
            raise PublicationError("descriptor.success-set-kind-undeclared")
        if not descriptor["artifact_producing"] and actual is not None:
            raise PublicationError("descriptor.nonproducing-command-published")
        return
    if result.get("outcome") != "refused":
        raise PublicationError("descriptor.outcome-undeclared")
    stage = result.get("stage")
    declared_refusals = {
        item["stage"]: item["artifact_set_kinds"]
        for item in descriptor["outcomes"]["refusals"]
    }
    if stage not in declared_refusals:
        raise PublicationError("descriptor.refusal-stage-undeclared")
    actual = result.get("set_kind")
    if actual is not None and actual not in declared_refusals[stage]:
        raise PublicationError("descriptor.refusal-set-kind-undeclared")
    if actual is None and declared_refusals[stage]:
        raise PublicationError("descriptor.refusal-publication-missing")


def _record_envelope(record: dict[str, Any], *, retry: bool) -> dict[str, Any]:
    outcome = record["outcome"]
    if outcome["outcome"] == "refused":
        return {
            "outcome": "refused",
            "error": {
                "category": "refusal",
                "stage": outcome["stage"],
                "diagnostics": outcome["diagnostics"],
                "truncated": False,
                "terminal_audit": record["receipt"],
            },
            "invocation_key": record["invocation_key"],
            "set_kind": record["set_kind"],
            "locator": _locator(record),
            "idempotent_replay": retry,
        }
    return {
        "outcome": "completed",
        "invocation_key": record["invocation_key"],
        "set_kind": record["set_kind"],
        "receipt": record["receipt"],
        "locator": _locator(record),
        "idempotent_replay": retry,
    }


def _refusal_envelope(
    stage: str,
    diagnostics: list[dict[str, Any]],
    gate_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "category": "refusal",
        "stage": stage,
        "diagnostics": diagnostics,
        "truncated": False,
    }
    if gate_report is not None:
        error["gate_report"] = gate_report
    return {"outcome": "refused", "error": error}


def _locator(record: dict[str, Any]) -> str:
    return f"invocation:{record['descriptor']}:{record['invocation_key']}"


def _write_json(value: dict[str, Any], stream: Any) -> None:
    stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 2:
            raise BindingRefusal("invocation.argv-invalid", "expected-one-json-request")
        request = json.loads(argv[1])
        output = dispatch(bind(request))
        _write_json(output, sys.stdout)
        return 0 if output["outcome"] == "completed" else 2
    except (json.JSONDecodeError, BindingRefusal, InvocationConflict) as error:
        if isinstance(error, BindingRefusal):
            code, detail = error.code, error.detail
        elif isinstance(error, InvocationConflict):
            code, detail = "invocation_key_conflict", str(error)
        else:
            code, detail = "invocation.json-malformed", str(error)
        _write_json(
            {
                "outcome": "usage_error",
                "error": {"category": "usage", "code": code, "detail": detail},
            },
            sys.stderr,
        )
        return 3
    except DeliveryFailure as error:
        _write_json(
            {
                "outcome": "internal_error",
                "error": {
                    "category": "internal",
                    "code": "internal_error",
                    "recovery_invocation_key": str(error),
                },
            },
            sys.stderr,
        )
        return 4
    except Exception:  # sanitized implementation boundary
        _write_json(
            {
                "outcome": "internal_error",
                "error": {"category": "internal", "code": "internal_error"},
            },
            sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
