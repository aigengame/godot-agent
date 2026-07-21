"""Generic Source → AST → Typed HIR → canonical RIR probe compiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from authority import KERNEL
from canonical import artifact, clone, identity, verify_artifact
from projections import generate, operation_map, release_map, reverse_conformance


class CompileRefusal(Exception):
    def __init__(self, stage: str, code: str, location: str) -> None:
        super().__init__(code)
        self.stage = stage
        self.code = code
        self.location = location

    def diagnostic(self) -> dict[str, str]:
        return {"stage": self.stage, "code": self.code, "location": self.location}


def _resolve(bundle: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    if not verify_artifact(bundle) or bundle.get("kernel") != KERNEL["identity"]:
        raise CompileRefusal("ingress", "bundle.identity-or-kernel-invalid", "$.bundle")
    if not verify_artifact(source):
        raise CompileRefusal("ingress", "source.identity-invalid", "$.source")
    packages = release_map(bundle)
    for package_id, release in packages.items():
        if not verify_artifact(release):
            raise CompileRefusal(
                "ingress", "bundle.package-release-identity-invalid", package_id
            )
    selected: dict[str, dict[str, Any]] = {}
    pending = [
        (clone(requirement), f"$.source.requires[{index}]")
        for index, requirement in enumerate(source["requires"])
    ]
    while pending:
        requirement, location = pending.pop(0)
        release = packages.get(requirement["package"])
        if release is None or requirement["version"] != f"={release['version']}":
            raise CompileRefusal("resolution", "resolution.package-mismatch", location)
        prior = selected.get(release["id"])
        if prior is not None:
            if prior["identity"] != release["identity"]:
                raise CompileRefusal(
                    "resolution", "resolution.package-release-conflict", release["id"]
                )
            continue
        selected[release["id"]] = release
        pending.extend(
            (clone(dependency), f"{release['id']}.dependencies[{index}]")
            for index, dependency in enumerate(release["dependencies"])
        )
    capabilities: dict[str, str] = {}
    quantity_kinds: dict[str, dict[str, Any]] = {}
    units: set[str] = set()
    numeric_profiles: set[str] = set()
    runtime_profiles: dict[str, str] = {}
    operation_bindings: dict[str, dict[str, Any]] = {}
    for release in selected.values():
        for capability in release["provides"]:
            if capability in capabilities:
                raise CompileRefusal(
                    "resolution", "resolution.capability-ambiguous", capability
                )
            capabilities[capability] = release["identity"]
        for quantity_kind in release["quantity_kinds"]:
            quantity_kinds[quantity_kind["id"]] = clone(quantity_kind)
        units.update(release["units"])
        numeric_profiles.update(release["numeric_profiles"])
        for profile in release["runtime_profiles"]:
            runtime_profiles[profile["id"]] = profile["identity"]
        for operation in release["operations"]:
            operation_bindings[operation["id"]] = {
                "package_release": release["identity"],
                "version": operation["version"],
                "program_identity": identity("operation-program", operation["body"]),
                "operation_identity": identity(
                    "operation-specification",
                    {"package_release": release["identity"], **operation},
                ),
            }
    for release in selected.values():
        missing = sorted(set(release["requires_capabilities"]) - set(capabilities))
        if missing:
            raise CompileRefusal(
                "resolution", "resolution.capability-mismatch", missing[0]
            )
    lock = artifact(
        "package-lock",
        {
            "kernel": KERNEL["identity"],
            "resolution_profile": "probe-selected-content-closure-v2",
            "selected": [
                {
                    "id": release["id"],
                    "version": release["version"],
                    "release_identity": release["identity"],
                }
                for release in sorted(selected.values(), key=lambda item: item["id"])
            ],
            "capability_providers": dict(sorted(capabilities.items())),
            "quantity_kinds": dict(sorted(quantity_kinds.items())),
            "units": sorted(units),
            "numeric_profiles": sorted(numeric_profiles),
            "runtime_profiles": dict(sorted(runtime_profiles.items())),
            "operation_bindings": dict(sorted(operation_bindings.items())),
            "constructor_closure": clone(KERNEL["constructors"]),
        },
    )
    return lock


def _validate_quantity(
    symbol: dict[str, Any], index: int, lock: dict[str, Any]
) -> None:
    location = f"$.symbols[{index}]"
    symbol_type = symbol.get("type")
    if (
        not isinstance(symbol_type, dict)
        or symbol_type.get("constructor") != "Quantity"
    ):
        raise CompileRefusal("static", "static.symbol-type-invalid", location)
    required = {
        "constructor",
        "representation",
        "kind",
        "unit",
        "support",
        "numeric_profile",
    }
    if set(symbol_type) != required:
        raise CompileRefusal("static", "static.quantity-facets-invalid", location)
    if not all(
        isinstance(symbol_type[field], str) and symbol_type[field]
        for field in ("representation", "kind", "unit", "numeric_profile")
    ):
        raise CompileRefusal("static", "static.quantity-facets-invalid", location)
    authority = lock["quantity_kinds"].get(symbol_type["kind"])
    if authority is None:
        raise CompileRefusal("static", "static.quantity-kind-unknown", location)
    for field in ("representation", "unit", "numeric_profile"):
        if symbol_type[field] != authority[field]:
            raise CompileRefusal(
                "static", f"static.quantity-{field.replace('_', '-')}-unknown", location
            )
    if symbol_type["unit"] not in lock["units"]:
        raise CompileRefusal("static", "static.quantity-unit-unknown", location)
    if symbol_type["numeric_profile"] not in lock["numeric_profiles"]:
        raise CompileRefusal("static", "static.quantity-profile-unknown", location)
    if type(symbol.get("initial")) is not int:
        raise CompileRefusal("static", "static.quantity-value-invalid", location)
    support = symbol_type["support"]
    if (
        not isinstance(support, dict)
        or set(support) != {"minimum", "maximum"}
        or type(support["minimum"]) is not int
        or type(support["maximum"]) is not int
        or support["minimum"] > support["maximum"]
        or not support["minimum"] <= symbol["initial"] <= support["maximum"]
    ):
        raise CompileRefusal("static", "static.quantity-support-invalid", location)
    if symbol.get("role") not in {"input", "state"}:
        raise CompileRefusal("static", "static.symbol-role-invalid", location)
    if not isinstance(symbol.get("state_path"), str):
        raise CompileRefusal("static", "static.symbol-state-path-invalid", location)


@dataclass
class ProgramAnalysis:
    reads: set[str]
    writes: set[str]
    outcomes: dict[str, dict[str, str]]


def _require_fields(node: dict[str, Any], fields: set[str], location: str) -> None:
    if set(node) != fields:
        raise CompileRefusal("static", "static.program-node-shape-invalid", location)


def _merge(first: ProgramAnalysis, second: ProgramAnalysis) -> ProgramAnalysis:
    outcomes = clone(first.outcomes)
    for tag, fields in second.outcomes.items():
        if tag in outcomes and outcomes[tag] != fields:
            raise CompileRefusal("static", "static.program-outcome-conflict", tag)
        outcomes[tag] = clone(fields)
    return ProgramAnalysis(
        reads=first.reads | second.reads,
        writes=first.writes | second.writes,
        outcomes=outcomes,
    )


def _expression_type(
    node: Any, state_types: dict[str, str], location: str
) -> tuple[str, set[str]]:
    if not isinstance(node, dict) or not isinstance(node.get("node"), str):
        raise CompileRefusal("static", "static.program-node-invalid", location)
    kind = node["node"]
    if kind == "literal":
        _require_fields(node, {"node", "value"}, location)
        value = node.get("value")
        if type(value) is int:
            return "Int", set()
        if isinstance(value, str):
            return "Enum", set()
        raise CompileRefusal("static", "static.program-literal-type-invalid", location)
    if kind == "read":
        _require_fields(node, {"node", "path"}, location)
        path = node.get("path")
        if not isinstance(path, str) or path not in state_types:
            raise CompileRefusal("static", "static.program-read-unknown", location)
        return state_types[path], {path}
    if kind in {"add", "sub", "min", "gte", "eq"}:
        _require_fields(node, {"node", "left", "right"}, location)
        left_type, left_reads = _expression_type(
            node.get("left"), state_types, f"{location}.left"
        )
        right_type, right_reads = _expression_type(
            node.get("right"), state_types, f"{location}.right"
        )
        if kind in {"add", "sub", "min", "gte"} and (
            left_type != "Int" or right_type != "Int"
        ):
            raise CompileRefusal(
                "static", "static.program-numeric-type-invalid", location
            )
        if kind == "eq" and left_type != right_type:
            raise CompileRefusal(
                "static", "static.program-equality-type-invalid", location
            )
        result_type = "Bool" if kind in {"gte", "eq"} else "Int"
        return result_type, left_reads | right_reads
    raise CompileRefusal("static", "static.program-node-unknown", f"{location}.{kind}")


def _analyze_program(
    node: Any, state_types: dict[str, str], location: str
) -> ProgramAnalysis:
    if not isinstance(node, dict) or not isinstance(node.get("node"), str):
        raise CompileRefusal("static", "static.program-node-invalid", location)
    kind = node["node"]
    if kind == "branch":
        _require_fields(node, {"node", "condition", "then", "else"}, location)
        condition_type, condition_reads = _expression_type(
            node.get("condition"), state_types, f"{location}.condition"
        )
        if condition_type != "Bool":
            raise CompileRefusal(
                "static", "static.program-condition-type-invalid", location
            )
        result = _merge(
            _analyze_program(node.get("then"), state_types, f"{location}.then"),
            _analyze_program(node.get("else"), state_types, f"{location}.else"),
        )
        result.reads |= condition_reads
        return result
    if kind == "outcome":
        _require_fields(node, {"node", "tag", "fields"}, location)
        tag = node.get("tag")
        fields = node.get("fields")
        if not isinstance(tag, str) or not isinstance(fields, dict):
            raise CompileRefusal("static", "static.program-outcome-invalid", location)
        reads: set[str] = set()
        payload: dict[str, str] = {}
        for field, expression in fields.items():
            if not isinstance(field, str):
                raise CompileRefusal(
                    "static", "static.program-outcome-invalid", location
                )
            field_type, field_reads = _expression_type(
                expression, state_types, f"{location}.fields.{field}"
            )
            payload[field] = field_type
            reads |= field_reads
        return ProgramAnalysis(reads=reads, writes=set(), outcomes={tag: payload})
    if kind == "transaction":
        _require_fields(node, {"node", "writes", "outcome"}, location)
        writes_value = node.get("writes")
        if not isinstance(writes_value, list):
            raise CompileRefusal("static", "static.program-write-invalid", location)
        reads: set[str] = set()
        writes: set[str] = set()
        for index, write in enumerate(writes_value):
            write_location = f"{location}.writes[{index}]"
            if (
                not isinstance(write, dict)
                or write.get("node") != "write"
                or not isinstance(write.get("path"), str)
            ):
                raise CompileRefusal(
                    "static", "static.program-write-invalid", write_location
                )
            _require_fields(write, {"node", "path", "value"}, write_location)
            path = write["path"]
            if path not in state_types:
                raise CompileRefusal(
                    "static", "static.program-write-unknown", write_location
                )
            if path in writes:
                raise CompileRefusal(
                    "static", "static.program-write-duplicate", write_location
                )
            value_type, value_reads = _expression_type(
                write.get("value"), state_types, f"{write_location}.value"
            )
            if value_type != state_types[path]:
                raise CompileRefusal(
                    "static", "static.program-write-type-invalid", write_location
                )
            writes.add(path)
            reads |= value_reads
        outcome = _analyze_program(
            node.get("outcome"), state_types, f"{location}.outcome"
        )
        return ProgramAnalysis(
            reads=reads | outcome.reads,
            writes=writes | outcome.writes,
            outcomes=outcome.outcomes,
        )
    raise CompileRefusal("static", "static.program-node-unknown", f"{location}.{kind}")


def _validate_operation(
    operation: dict[str, Any],
    state_types: dict[str, str],
    lock: dict[str, Any],
    location: str,
) -> None:
    required = {
        "id",
        "version",
        "parameters",
        "result",
        "state_contract",
        "kind_rules",
        "unit_rules",
        "permitted_numeric_profiles",
        "purity",
        "effects",
        "resource_bounds",
        "body",
    }
    if set(operation) - {"package_release"} != required:
        raise CompileRefusal("static", "static.operation-shape-invalid", location)
    if (
        not isinstance(operation["id"], str)
        or not operation["id"]
        or type(operation["version"]) is not int
        or operation["version"] < 1
    ):
        raise CompileRefusal("static", "static.operation-signature-invalid", location)
    parameters = operation["parameters"]
    if not isinstance(parameters, dict) or not all(
        isinstance(name, str)
        and name
        and isinstance(parameter_type, str)
        and parameter_type in {"Enum", "Int"}
        for name, parameter_type in parameters.items()
    ):
        raise CompileRefusal("static", "static.operation-parameters-invalid", location)
    if parameters:
        raise CompileRefusal(
            "static", "static.operation-parameter-unconsumed", location
        )
    result = operation["result"]
    if (
        not isinstance(result, dict)
        or set(result) != {"kind", "variants"}
        or not isinstance(result["kind"], str)
        or not result["kind"]
        or not isinstance(result["variants"], dict)
        or not result["variants"]
    ):
        raise CompileRefusal("static", "static.operation-result-invalid", location)
    for tag, payload in result["variants"].items():
        if (
            not isinstance(tag, str)
            or not tag
            or not isinstance(payload, dict)
            or not all(
                isinstance(name, str)
                and name
                and isinstance(payload_type, str)
                and payload_type in {"Enum", "Int"}
                for name, payload_type in payload.items()
            )
        ):
            raise CompileRefusal("static", "static.operation-result-invalid", location)
    operation_state_types = operation["state_contract"]
    if not isinstance(operation_state_types, dict) or not all(
        isinstance(path, str)
        and path
        and isinstance(value_type, str)
        and value_type in {"Enum", "Int"}
        for path, value_type in operation_state_types.items()
    ):
        raise CompileRefusal(
            "static", "static.operation-state-contract-invalid", location
        )
    for path, value_type in operation_state_types.items():
        if state_types.get(path) != value_type:
            raise CompileRefusal(
                "static", "static.operation-model-state-mismatch", path
            )
    kind_rules = operation["kind_rules"]
    unit_rules = operation["unit_rules"]
    if (
        not isinstance(kind_rules, dict)
        or set(kind_rules) != set(operation_state_types)
        or not all(isinstance(kind, str) and kind for kind in kind_rules.values())
        or not isinstance(unit_rules, dict)
        or set(unit_rules) != set(operation_state_types)
    ):
        raise CompileRefusal(
            "static", "static.operation-kind-unit-rules-invalid", location
        )
    for path, value_type in operation_state_types.items():
        kind = kind_rules[path]
        unit = unit_rules[path]
        kind_authority = lock["quantity_kinds"].get(kind)
        if value_type == "Int" and (
            not isinstance(unit, str)
            or unit not in lock["units"]
            or kind_authority is None
            or kind_authority["representation"] != "Int"
            or kind_authority["unit"] != unit
        ):
            raise CompileRefusal(
                "static", "static.operation-kind-unit-rules-invalid", path
            )
        if value_type == "Enum" and (kind != "Enum" or unit is not None):
            raise CompileRefusal(
                "static", "static.operation-kind-unit-rules-invalid", path
            )
    numeric_profiles = operation["permitted_numeric_profiles"]
    if (
        not isinstance(numeric_profiles, list)
        or not numeric_profiles
        or not all(isinstance(profile, str) for profile in numeric_profiles)
        or len(numeric_profiles) != len(set(numeric_profiles))
        or any(profile not in lock["numeric_profiles"] for profile in numeric_profiles)
        or any(
            lock["quantity_kinds"][kind_rules[path]]["numeric_profile"]
            not in numeric_profiles
            for path, value_type in operation_state_types.items()
            if value_type == "Int"
        )
    ):
        raise CompileRefusal(
            "static", "static.operation-numeric-profiles-invalid", location
        )
    effects = operation["effects"]
    effect_fields = {
        "state_reads",
        "state_writes",
        "emitted_signals",
        "scheduled_events",
        "canceled_events",
        "named_random_streams",
    }
    if (
        not isinstance(effects, dict)
        or set(effects) != effect_fields
        or any(
            not isinstance(values, list)
            or not all(isinstance(value, str) for value in values)
            or len(values) != len(set(values))
            for values in effects.values()
        )
        or not set(effects["state_reads"]).issubset(operation_state_types)
        or not set(effects["state_writes"]).issubset(operation_state_types)
        or any(
            effects[field]
            for field in (
                "emitted_signals",
                "scheduled_events",
                "canceled_events",
                "named_random_streams",
            )
        )
    ):
        raise CompileRefusal("static", "static.operation-effects-invalid", location)
    purity = operation["purity"]
    if (
        not isinstance(purity, str)
        or purity not in {"effectful", "pure"}
        or (purity == "pure" and any(effects.values()))
    ):
        raise CompileRefusal("static", "static.operation-purity-invalid", location)
    bounds = operation["resource_bounds"]
    if (
        not isinstance(bounds, dict)
        or set(bounds) != {"max_reads", "max_writes"}
        or any(type(value) is not int or value < 0 for value in bounds.values())
    ):
        raise CompileRefusal(
            "static", "static.operation-resource-bound-invalid", location
        )
    analysis = _analyze_program(
        operation["body"], operation_state_types, f"{location}.body"
    )
    declared_reads = set(effects["state_reads"])
    declared_writes = set(effects["state_writes"])
    if analysis.reads != declared_reads:
        raise CompileRefusal("static", "static.operation-read-effects-drift", location)
    if analysis.writes != declared_writes:
        raise CompileRefusal("static", "static.operation-write-effects-drift", location)
    if bounds != {
        "max_reads": len(analysis.reads),
        "max_writes": len(analysis.writes),
    }:
        raise CompileRefusal(
            "static", "static.operation-resource-bound-invalid", location
        )
    if analysis.outcomes != result["variants"]:
        raise CompileRefusal("static", "static.operation-result-drift", location)


def _validate_match(
    use_site: dict[str, Any], operation: dict[str, Any], use_index: int
) -> None:
    location = f"$.use_sites[{use_index}].match"
    arms = use_site.get("match")
    if not isinstance(arms, list):
        raise CompileRefusal("static", "static.variant-match-invalid", location)
    tags: list[str] = []
    for arm in arms:
        if not isinstance(arm, dict) or not isinstance(arm.get("tag"), str):
            raise CompileRefusal("static", "static.variant-arm-invalid", location)
        tags.append(arm["tag"])
    if len(tags) != len(set(tags)):
        raise CompileRefusal("static", "static.variant-arm-duplicate", location)
    variants = operation["result"]["variants"]
    unknown = sorted(set(tags) - set(variants))
    if unknown:
        raise CompileRefusal(
            "static", "static.variant-arm-unknown", f"{location}.{unknown[0]}"
        )
    missing = sorted(set(variants) - set(tags))
    if missing:
        raise CompileRefusal(
            "static", "static.variant-arm-missing", f"{location}.{missing[0]}"
        )
    for arm in arms:
        if arm.get("payload") != variants[arm["tag"]]:
            raise CompileRefusal(
                "static",
                "static.variant-payload-type-invalid",
                f"{location}.{arm['tag']}",
            )


def compile_model(
    bundle: dict[str, Any],
    source: dict[str, Any],
    *,
    supplied_projections: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    projections = (
        generate(bundle) if supplied_projections is None else supplied_projections
    )
    try:
        reverse_conformance(bundle, projections)
    except Exception as error:
        raise CompileRefusal(
            "static",
            getattr(error, "code", "projection.invalid"),
            getattr(error, "detail", "projection"),
        ) from error
    lock = _resolve(bundle, source)
    ast = artifact(
        "authoring-ast", {"source": source["identity"], "document": clone(source)}
    )
    seen_symbols: set[str] = set()
    state_types: dict[str, str] = {
        path: value["type"] for path, value in source["state_literals"].items()
    }
    hir_symbols: list[dict[str, Any]] = []
    for index, symbol in enumerate(source["symbols"]):
        _validate_quantity(symbol, index, lock)
        if symbol["id"] in seen_symbols or symbol["state_path"] in state_types:
            raise CompileRefusal(
                "static", "static.symbol-duplicate", f"$.symbols[{index}]"
            )
        seen_symbols.add(symbol["id"])
        state_types[symbol["state_path"]] = "Int"
        hir_symbols.append(
            {
                "symbol": f"{source['package']['id']}@{source['package']['version']}::model::{symbol['id']}",
                "type": clone(symbol["type"]),
                "role": symbol["role"],
                "state_path": symbol["state_path"],
                "initial": symbol["initial"],
                "export": symbol["export"],
            }
        )
    operations = operation_map(bundle)
    selected_release_ids = {
        selected["release_identity"] for selected in lock["selected"]
    }
    for index, operation in enumerate(operations.values()):
        if operation["package_release"] in selected_release_ids:
            _validate_operation(
                operation, state_types, lock, f"$.selected_operations[{index}]"
            )
    hir_use_sites: list[dict[str, Any]] = []
    seen_use_sites: set[str] = set()
    for index, use_site in enumerate(source["use_sites"]):
        operation = operations.get(use_site.get("operation"))
        if operation is None:
            raise CompileRefusal(
                "static", "static.operation-unknown", f"$.use_sites[{index}].operation"
            )
        binding = lock["operation_bindings"].get(operation["id"])
        if (
            binding is None
            or binding["package_release"] != operation["package_release"]
        ):
            raise CompileRefusal(
                "resolution", "resolution.operation-unbound", f"$.use_sites[{index}]"
            )
        if use_site["id"] in seen_use_sites:
            raise CompileRefusal(
                "static", "static.use-site-duplicate", f"$.use_sites[{index}]"
            )
        seen_use_sites.add(use_site["id"])
        _validate_match(use_site, operation, index)
        hir_use_sites.append(
            {
                "id": use_site["id"],
                "operation": operation["id"],
                "package_release": operation["package_release"],
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
                "operation_identity": binding["operation_identity"],
                "match": sorted(clone(use_site["match"]), key=lambda arm: arm["tag"]),
            }
        )
    hir = artifact(
        "typed-hir",
        {
            "ast": ast["identity"],
            "symbols": sorted(hir_symbols, key=lambda symbol: symbol["symbol"]),
            "use_sites": hir_use_sites,
            "effects_checked": True,
            "variants_exhaustive": True,
            "package_programs_checked": True,
        },
    )
    runtime_programs = {
        program["operation"]: program for program in projections["runtime"]["programs"]
    }
    rir_use_sites = [
        {
            "id": use_site["id"],
            "operation": use_site["operation"],
            "package_release": use_site["package_release"],
            "version": use_site["version"],
            "parameters": clone(use_site["parameters"]),
            "result": clone(use_site["result"]),
            "state_contract": clone(use_site["state_contract"]),
            "kind_rules": clone(use_site["kind_rules"]),
            "unit_rules": clone(use_site["unit_rules"]),
            "permitted_numeric_profiles": clone(use_site["permitted_numeric_profiles"]),
            "purity": use_site["purity"],
            "effects": clone(use_site["effects"]),
            "resource_bounds": clone(use_site["resource_bounds"]),
            "operation_identity": use_site["operation_identity"],
            "program": clone(runtime_programs[use_site["operation"]]["body"]),
            "program_identity": identity(
                "operation-program", runtime_programs[use_site["operation"]]["body"]
            ),
        }
        for use_site in hir_use_sites
    ]
    rir = artifact(
        "resolved-model",
        {
            "kernel": KERNEL["identity"],
            "language_bundle": bundle["identity"],
            "package_lock": lock["identity"],
            "symbols": sorted(hir_symbols, key=lambda item: item["symbol"]),
            "initial_literals": {
                path: clone(value["value"])
                for path, value in source["state_literals"].items()
            },
            "use_sites": rir_use_sites,
        },
    )
    capability_manifest = artifact(
        "capability-manifest",
        {
            "package_lock": lock["identity"],
            "rir": rir["identity"],
            "packages": clone(lock["selected"]),
            "capabilities": sorted(lock["capability_providers"]),
            "quantity_kinds": sorted(lock["quantity_kinds"]),
            "numeric_profiles": clone(lock["numeric_profiles"]),
            "runtime_profiles": clone(lock["runtime_profiles"]),
            "operations": [use_site["operation"] for use_site in rir_use_sites],
            "symbols": [symbol["symbol"] for symbol in rir["symbols"]],
        },
    )
    resolution_receipt = artifact(
        "resolution-receipt",
        {
            "source": source["identity"],
            "language_bundle": bundle["identity"],
            "package_lock": lock["identity"],
            "resolver": "orthogonality-probe-resolver-v2",
        },
    )
    build_receipt = artifact(
        "build-receipt",
        {
            "source": source["identity"],
            "ast": ast["identity"],
            "hir": hir["identity"],
            "rir": rir["identity"],
            "compiler": "orthogonality-probe-compiler-v2",
        },
    )
    debug_map = artifact(
        "debug-map",
        {
            "rir": rir["identity"],
            "source": source["identity"],
            "use_site_locations": [
                f"$.use_sites[{index}]" for index in range(len(hir_use_sites))
            ],
        },
    )
    return {
        "source": clone(source),
        "ast": ast,
        "hir": hir,
        "rir": rir,
        "lock": lock,
        "resolution_receipt": resolution_receipt,
        "build_receipt": build_receipt,
        "debug_map": debug_map,
        "capability_manifest": capability_manifest,
        "projections": clone(projections),
    }
