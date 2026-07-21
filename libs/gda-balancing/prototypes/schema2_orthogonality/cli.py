"""Descriptor-driven structured command boundary for the disposable probe."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from authority import (
    DIAGNOSTIC_AUTHORITY,
    KERNEL,
    experiment,
    full_bundle,
    model_source,
)
from compiler import CompileRefusal, compile_model
from descriptor import (
    BindingError,
    DescriptorViolation,
    RUN_DESCRIPTOR,
    SURFACE_MANIFEST,
    bind,
    outcome_transport,
    reverse_conform_handlers,
    validate_artifact_set,
    validate_handler_result,
    validate_public_envelope,
)
from projections import release_map
from runtime import execute, resolved_runtime_profile
from store import ArtifactStore, InvocationConflict, PublicationError


Handler = Callable[[dict[str, Any]], dict[str, Any]]
HANDLER_CALLS: list[str] = []


def _build_members(
    bundle: dict[str, Any], built: dict[str, Any]
) -> list[dict[str, Any]]:
    packages = {
        release["identity"]: release for release in release_map(bundle).values()
    }
    selected_releases = [
        packages[selected["release_identity"]] for selected in built["lock"]["selected"]
    ]
    return [
        KERNEL,
        DIAGNOSTIC_AUTHORITY,
        bundle,
        *selected_releases,
        RUN_DESCRIPTOR,
        SURFACE_MANIFEST,
        built["source"],
        built["ast"],
        built["hir"],
        built["rir"],
        built["lock"],
        built["resolution_receipt"],
        built["build_receipt"],
        built["debug_map"],
        built["capability_manifest"],
        *built["projections"].values(),
    ]


def _run_handler(bound: dict[str, Any]) -> dict[str, Any]:
    HANDLER_CALLS.append(bound["canonical_input_identity"])
    params = bound["params"]
    bundle = full_bundle()
    source = model_source(extra_attribute=params["extra_attribute"])
    built = compile_model(bundle, source)
    experiment_spec = experiment(params["scenario"], built["rir"]["identity"])
    profile = resolved_runtime_profile(
        bundle, built, max_event_writes=params["max_event_writes"]
    )
    result = execute(bundle, built, experiment_spec, profile=profile)
    if result["status"] == "completed":
        members = _build_members(bundle, built) + [
            result["profile"],
            *result["snapshots"],
            result["run"],
            result["experiment"],
            result["experiment_binding"],
            result["metrics"],
            result["evaluation"],
        ]
        return {
            "outcome_name": "completed",
            "envelope": {
                "outcome": "completed",
                "semantic_authority_gate": "unvalidated",
                "normative_replay_or_evidence_issued": False,
            },
            "members": members,
        }
    if result["phase"] == "pre-dispatch":
        return {
            "outcome_name": "predispatch_refused",
            "envelope": {
                "outcome": "refused",
                "phase": "pre-dispatch",
                "diagnostic": result["diagnostic"],
                "terminal_audit": None,
            },
            "members": [],
        }
    members = _build_members(bundle, built) + [
        result["profile"],
        result["experiment"],
        result["experiment_binding"],
        *result["snapshots"],
        result["terminal_audit"],
    ]
    return {
        "outcome_name": "runtime_refused",
        "envelope": {
            "outcome": "refused",
            "phase": "post-dispatch",
            "diagnostic": result["terminal_audit"]["diagnostic"],
            "terminal_audit": result["terminal_audit"]["identity"],
        },
        "members": members,
    }


HANDLERS: dict[str, Handler] = {RUN_DESCRIPTOR["handler"]: _run_handler}


def _transport(
    outcome_name: str, envelope: dict[str, Any]
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
    exit_code, channel = outcome_transport(outcome_name)
    validate_public_envelope(outcome_name, envelope)
    return (
        exit_code,
        envelope if channel == "stdout" else None,
        envelope if channel == "stderr" else None,
    )


def dispatch(
    request: Any,
    *,
    handlers: dict[str, Handler] | None = None,
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None]:
    active_handlers = HANDLERS if handlers is None else handlers
    try:
        reverse_conform_handlers(active_handlers)
        bound = bind(request)
    except BindingError as error:
        return _transport(
            "usage_error",
            {"outcome": "usage_error", "code": error.code, "field": error.field},
        )
    except DescriptorViolation as error:
        return _transport(
            "internal_error", {"outcome": "internal_error", "code": str(error)}
        )
    store = ArtifactStore(Path(bound["store"]))
    try:
        prior = store.lookup(bound["invocation_key"])
        if prior is not None:
            if (
                prior["descriptor_identity"] != bound["descriptor_identity"]
                or prior["canonical_input_identity"]
                != bound["canonical_input_identity"]
            ):
                return _transport(
                    "usage_error",
                    {
                        "outcome": "usage_error",
                        "code": "invocation.key-conflict",
                        "field": "invocation_key",
                    },
                )
            validate_artifact_set(prior["outcome_name"], prior["members"])
            replay_envelope = {
                **prior["envelope"],
                "artifact_set": prior["set_kind"],
                "publication_receipt": prior["receipt"]["identity"],
                "idempotent_replay": True,
            }
            return _transport(prior["outcome_name"], replay_envelope)
        handler = active_handlers[bound["descriptor"]["handler"]]
        result = handler(bound)
        validate_handler_result(result)
        outcome_name = result["outcome_name"]
        outcome = bound["descriptor"]["outcomes"][outcome_name]
        if outcome["artifact_set"] is None:
            return _transport(outcome_name, result["envelope"])
        set_kind = validate_artifact_set(outcome_name, result["members"])
        published = store.publish(
            bound["descriptor_identity"],
            bound["invocation_key"],
            bound["canonical_input_identity"],
            outcome_name,
            set_kind,
            result["envelope"],
            result["members"],
            fault=bound["params"]["fault"],
        )
        envelope = {
            **result["envelope"],
            "artifact_set": set_kind,
            "publication_receipt": published["receipt"]["identity"],
            "idempotent_replay": False,
        }
        return _transport(outcome_name, envelope)
    except InvocationConflict:
        return _transport(
            "usage_error",
            {
                "outcome": "usage_error",
                "code": "invocation.key-conflict",
                "field": "invocation_key",
            },
        )
    except CompileRefusal as error:
        return _transport(
            "predispatch_refused",
            {
                "outcome": "refused",
                "phase": "pre-dispatch",
                "diagnostic": error.diagnostic(),
                "terminal_audit": None,
            },
        )
    except (DescriptorViolation, PublicationError) as error:
        return _transport(
            "internal_error", {"outcome": "internal_error", "code": str(error)}
        )
    except Exception as error:
        return _transport(
            "internal_error",
            {"outcome": "internal_error", "code": type(error).__name__},
        )


def main() -> int:
    if len(sys.argv) != 2:
        exit_code, _, stderr = _transport(
            "usage_error",
            {"outcome": "usage_error", "code": "argv.count", "field": "$argv"},
        )
        sys.stderr.write(
            json.dumps(stderr, sort_keys=True, separators=(",", ":")) + "\n"
        )
        return exit_code
    try:
        request = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        exit_code, _, stderr = _transport(
            "usage_error",
            {"outcome": "usage_error", "code": "argv.json", "field": "$argv"},
        )
        sys.stderr.write(
            json.dumps(stderr, sort_keys=True, separators=(",", ":")) + "\n"
        )
        return exit_code
    exit_code, stdout, stderr = dispatch(request)
    if stdout is not None:
        sys.stdout.write(
            json.dumps(stdout, sort_keys=True, separators=(",", ":")) + "\n"
        )
    if stderr is not None:
        sys.stderr.write(
            json.dumps(stderr, sort_keys=True, separators=(",", ":")) + "\n"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
