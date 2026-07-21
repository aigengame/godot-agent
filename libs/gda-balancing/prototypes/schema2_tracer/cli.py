from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from bundle import load_bundle, parse_bundle_document
from canonical import canonical_line, identified
from compiler import compile_model, load_experiment
from refusals import Refusal
from runtime import run_experiment, validate_experiment_envelope
from store import PrototypeStore


Handler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class CommandDescriptor:
    path: tuple[str, ...]
    description: str
    input_schema: dict[str, Any]
    success_schema: dict[str, Any]
    refusal_stages: tuple[str, ...]
    handler: Handler
    artifact_behavior: dict[str, Any]

    def projected_schema(self) -> dict[str, Any]:
        return {
            "error": {
                "internal": {"category": "internal", "exit": 4, "channel": "stderr"},
                "refusal": {
                    "category": "refusal",
                    "diagnostic_location_union": [
                        "invocation",
                        "source",
                        "artifact",
                        "symbol",
                        "runtime",
                    ],
                    "exit": 2,
                    "channel": "stdout",
                    "stages": list(self.refusal_stages),
                },
                "usage": {"category": "usage", "exit": 3, "channel": "stderr"},
            },
            "input": self.input_schema,
            "success": self.success_schema,
        }


def _model_build(params: dict[str, Any]) -> dict[str, Any]:
    bundle = load_bundle(Path(params["bundle_path"]))
    compiled = compile_model(Path(params["model_path"]), bundle)
    store = PrototypeStore(Path(params["prototype_store"]))

    bundle_artifact = identified("language-definition-bundle", bundle.document)
    operations_used = sorted(
        {
            call["operation"]
            for handler in compiled.rir["content"]["handlers"]
            for call in handler["calls"]
        }
    )
    capability_manifest = identified(
        "capability-manifest",
        {
            "bundle_identity": bundle.identity,
            "numeric_profiles": [
                profile["id"] for profile in bundle.document["numeric_profiles"]
            ],
            "operations": operations_used,
            "package_lock_identity": compiled.package_lock["identity"],
            "packages": compiled.package_lock["content"]["packages"],
            "resolved_model_identity": compiled.rir["identity"],
            "runtime_profiles": [
                profile["id"] for profile in bundle.document["runtime_profiles"]
            ],
        },
    )
    receipts = store.publish_batch(
        [bundle_artifact, compiled.package_lock, compiled.rir, capability_manifest]
    )
    return {
        "category": "success",
        "result": {
            "ast_identity": compiled.ast["identity"],
            "capability_manifest_identity": capability_manifest["identity"],
            "hir_identity": compiled.hir["identity"],
            "package_lock_identity": compiled.package_lock["identity"],
            "prototype_only": True,
            "receipts": sorted(receipts, key=lambda item: item["identity"]),
            "resolved_model_identity": compiled.rir["identity"],
        },
    }


def _experiment_run(params: dict[str, Any]) -> dict[str, Any]:
    experiment = load_experiment(Path(params["experiment_path"]))
    validate_experiment_envelope(experiment)
    store = PrototypeStore(Path(params["prototype_store"]))
    rir = store.get(experiment["resolved_model_identity"], "resolved-model-rir")
    package_lock = store.get(rir["content"]["package_lock_identity"], "package-lock")
    bundle_artifact = store.get(
        rir["content"]["bundle_identity"], "language-definition-bundle"
    )
    bundle = parse_bundle_document(bundle_artifact["content"])
    if package_lock["content"]["bundle_identity"] != bundle.identity:
        raise Refusal(
            "resolution",
            "schema2.artifact.lock-bundle-mismatch",
            "RIR Package Lock and Language Definition Bundle identities disagree",
            {
                "artifact_identity": package_lock["identity"],
                "kind": "artifact",
                "pointer": "/content/bundle_identity",
            },
        )
    artifacts = run_experiment(
        rir=rir,
        bundle=bundle,
        experiment=experiment,
        seed=experiment["effective_seed"],
    )
    stored = [
        artifacts.trace,
        artifacts.final_snapshot,
        artifacts.metric_dataset,
        artifacts.evaluation_run,
        *artifacts.evidence_assertions,
    ]
    receipts = store.publish_batch(stored)
    return {
        "category": "success",
        "result": {
            "evaluation_run_identity": artifacts.evaluation_run["identity"],
            "evidence_assertion_identities": [
                assertion["identity"] for assertion in artifacts.evidence_assertions
            ],
            "final_snapshot_identity": artifacts.final_snapshot["identity"],
            "metric_dataset_identity": artifacts.metric_dataset["identity"],
            "prototype_only": True,
            "receipts": sorted(receipts, key=lambda item: item["identity"]),
            "trace_identity": artifacts.trace["identity"],
        },
    }


def _manifest(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": "success",
        "result": {
            "commands": [
                {
                    "artifact_behavior": descriptor.artifact_behavior,
                    "description": descriptor.description,
                    "path": list(descriptor.path),
                    "schema": descriptor.projected_schema(),
                }
                for descriptor in sorted(
                    DESCRIPTORS.values(), key=lambda item: item.path
                )
            ],
            "prototype_only": True,
            "surface_version": "schema2-tracer-surface@1",
        },
    }


def _object_schema(
    required: list[str], property_types: dict[str, str] | None = None
) -> dict[str, Any]:
    types = property_types or {}
    return {
        "additionalProperties": False,
        "properties": {
            name: ({"type": types[name]} if name in types else {}) for name in required
        },
        "required": required,
        "type": "object",
    }


DESCRIPTORS: dict[tuple[str, ...], CommandDescriptor] = {}


def _register(descriptor: CommandDescriptor) -> None:
    if descriptor.path in DESCRIPTORS:
        raise RuntimeError(f"duplicate descriptor {descriptor.path}")
    DESCRIPTORS[descriptor.path] = descriptor


_register(
    CommandDescriptor(
        path=("model", "build"),
        description="Compile one Model Source Package and persist prototype artifacts.",
        input_schema=_object_schema(
            ["bundle_path", "model_path", "prototype_store"],
            {
                "bundle_path": "string",
                "model_path": "string",
                "prototype_store": "string",
            },
        ),
        success_schema=_object_schema(
            [
                "ast_identity",
                "hir_identity",
                "package_lock_identity",
                "resolved_model_identity",
                "capability_manifest_identity",
                "receipts",
                "prototype_only",
            ]
        ),
        refusal_stages=("ingress", "parse", "static", "resolution"),
        handler=_model_build,
        artifact_behavior={
            "inputs": ["language-definition-bundle", "model-source-package"],
            "outputs": ["package-lock", "resolved-model-rir", "capability-manifest"],
            "store": "prototype-only-content-addressed",
        },
    )
)
_register(
    CommandDescriptor(
        path=("experiment", "run"),
        description="Execute an Experiment Specification from stored RIR identity.",
        input_schema=_object_schema(
            ["experiment_path", "prototype_store"],
            {"experiment_path": "string", "prototype_store": "string"},
        ),
        success_schema=_object_schema(
            [
                "evaluation_run_identity",
                "metric_dataset_identity",
                "trace_identity",
                "final_snapshot_identity",
                "evidence_assertion_identities",
                "receipts",
                "prototype_only",
            ]
        ),
        refusal_stages=("ingress", "resolution", "runtime", "evaluation"),
        handler=_experiment_run,
        artifact_behavior={
            "inputs": ["resolved-model-rir", "experiment-specification"],
            "outputs": [
                "evaluation-run",
                "metric-dataset",
                "ordered-runtime-trace",
                "evidence-assertion",
            ],
            "store": "prototype-only-content-addressed",
        },
    )
)
_register(
    CommandDescriptor(
        path=("manifest",),
        description="Project the live prototype Command descriptor registry.",
        input_schema=_object_schema([]),
        success_schema=_object_schema(
            ["commands", "prototype_only", "surface_version"]
        ),
        refusal_stages=("ingress",),
        handler=_manifest,
        artifact_behavior={
            "inputs": [],
            "outputs": ["surface-manifest"],
            "store": "none",
        },
    )
)


def _usage(code: str, message: str) -> int:
    sys.stderr.buffer.write(
        canonical_line(
            {"error": {"category": "usage", "code": code, "message": message}}
        )
    )
    return 3


def _params_error(schema: dict[str, Any], params: dict[str, Any]) -> str | None:
    properties = schema["properties"]
    required = set(schema["required"])
    actual = set(params)
    missing = sorted(required - actual)
    extra = sorted(actual - set(properties))
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"extra: {', '.join(extra)}")
        return "; ".join(details)
    for name, property_schema in properties.items():
        expected_type = property_schema.get("type")
        if expected_type == "string" and not isinstance(params.get(name), str):
            return f"{name} must be a string"
    return None


def _parse(argv: list[str]) -> tuple[CommandDescriptor, bool, dict[str, Any]] | int:
    descriptor: CommandDescriptor | None = None
    consumed = 0
    for width in (2, 1):
        candidate = tuple(argv[:width])
        if candidate in DESCRIPTORS:
            descriptor = DESCRIPTORS[candidate]
            consumed = width
            break
    if descriptor is None:
        return _usage(
            "unknown_command", "expected model build, experiment run, or manifest"
        )
    tail = argv[consumed:]
    if "--schema" in tail:
        if tail != ["--schema"]:
            return _usage(
                "schema_argument_conflict", "--schema is a bare precedence option"
            )
        return descriptor, True, {}
    if not tail:
        if descriptor.path == ("manifest",):
            return descriptor, False, {}
        return _usage(
            "missing_params_json", "command requires --params-json <json | ->"
        )
    if len(tail) != 2 or tail[0] != "--params-json":
        return _usage("invalid_arguments", "use exactly --params-json <json | ->")
    raw = sys.stdin.read() if tail[1] == "-" else tail[1]
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _usage("invalid_params_json", str(exc))
    if not isinstance(params, dict):
        return _usage(
            "invalid_params_json", "structured params must be one JSON object"
        )
    return descriptor, False, params


def main(argv: list[str] | None = None) -> int:
    parsed = _parse(list(sys.argv[1:] if argv is None else argv))
    if isinstance(parsed, int):
        return parsed
    descriptor, schema_only, params = parsed
    if not schema_only:
        params_error = _params_error(descriptor.input_schema, params)
        if params_error is not None:
            return _usage("invalid_params", params_error)
    try:
        output = (
            {
                "category": "success",
                "result": {
                    "command": list(descriptor.path),
                    "schema": descriptor.projected_schema(),
                },
            }
            if schema_only
            else descriptor.handler(params)
        )
        sys.stdout.buffer.write(canonical_line(output))
        return 0
    except Refusal as refusal:
        sys.stdout.buffer.write(canonical_line(refusal.envelope()))
        return 2
    except Exception:
        sys.stderr.buffer.write(
            canonical_line(
                {
                    "error": {
                        "category": "internal",
                        "code": "internal_error",
                        "message": "prototype implementation failed unexpectedly",
                    }
                }
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
