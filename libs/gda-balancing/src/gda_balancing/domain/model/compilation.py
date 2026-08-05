"""Resolution and lowering of an already checked Model Source Package."""

from typing import Any, cast

from gda_balancing.domain.artifacts import _identified_artifact
from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
)
from gda_balancing.domain.canonical import JsonValue
from gda_balancing.domain.model.resolution import (
    CheckedModel,
    _LOWERER_IMPLEMENTATION_IDENTITY,
    _RESOLVER_IMPLEMENTATION_IDENTITY,
    _apply_language_rule,
    _compile_initialization_programs,
    _composition_policy,
    _formula_operation_identity,
    _formula_policy,
    _identified_rir_artifact,
    _language,
    _model_explanation_pairs_are_admitted,
    _model_lowering,
    _package_lock,
    _pointer,
    _resolution_profile,
    _resolved_call_sites,
    _resolved_entrypoints,
    _resolved_formulas_and_bindings,
    _resolved_source_symbols,
    _runtime_projection,
    _runtime_projection_budget,
    _specialize_operation_formula_slots,
    admit_resolved_model,
)


def compile_checked_model(
    checked: CheckedModel,
) -> dict[str, dict[str, JsonValue]]:
    """Lower one checked source into its semantic and provenance artifacts."""
    artifacts = lower_checked_model(checked)
    validate_compiled_artifacts(
        artifacts,
        checked.source_identity,
        authority_context_for_checked(checked),
    )
    return artifacts


def authority_context_for_checked(checked: CheckedModel) -> AdmittedAuthorityContext:
    """Return the exact admitted authority carried by a checked Model."""
    if checked.authority_context is not None:
        return checked.authority_context
    context = admit_authority_context(checked.kernel, checked.language_bundle)
    if isinstance(context, BootstrapAdmission):
        raise RuntimeError("checked Model authorities failed admission")
    return context


def model_build_command_input_identity(checked: CheckedModel) -> str:
    """Identify the semantic input bound to one Model build invocation."""
    command_input = _identified_artifact(
        checked.language_bundle,
        "model-build-command-input",
        {
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
        },
    )
    return cast(str, command_input["content_identity"])


def validate_compiled_artifacts(
    artifacts: dict[str, dict[str, JsonValue]],
    source_identity: str,
    authority_context: AdmittedAuthorityContext,
    *,
    validate_explanation_projection: bool = True,
) -> None:
    """Require one compiled Model set to match its exact authority and source."""
    kernel = authority_context.kernel
    language_bundle = authority_context.language_bundle
    semantic_artifacts = {
        name: cast(dict[str, Any], artifacts[name])
        for name in ("package-lock", "rir-semantic-payload", "resolved-model")
    }
    if not admit_resolved_model(
        semantic_artifacts, authority_context=authority_context
    ).admitted:
        raise RuntimeError("Resolved Model failed exact-authority admission")
    lock = artifacts["package-lock"]
    rir = artifacts["rir-semantic-payload"]
    resolved = artifacts["resolved-model"]
    if artifacts["capability-manifest"] != _capability_manifest(
        cast(dict[str, Any], lock),
        cast(dict[str, Any], rir),
        cast(dict[str, Any], resolved),
        language_bundle,
    ):
        raise RuntimeError("Capability manifest is not an exact projection")
    if validate_explanation_projection and artifacts[
        "model-explanation"
    ] != _model_explanation(
        authority_context,
        lock,
        rir,
        artifacts["debug-map"],
    ):
        raise RuntimeError("Model explanation is not an exact projection")
    build_receipt = artifacts["build-receipt"]
    debug_map = artifacts["debug-map"]
    resolution_receipt = artifacts["resolution-receipt"]
    lowering = _model_lowering(language_bundle)
    profile = _resolution_profile(
        language_bundle, cast(str, lowering["resolution_profile"])
    )
    expected_build_bindings = {
        "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
        "source_identity": source_identity,
        "kernel_identity": kernel["content_identity"],
        "language_bundle_identity": language_bundle["content_identity"],
        "package_lock_identity": lock["content_identity"],
        "rir_identity": rir["content_identity"],
        "resolved_model_identity": resolved["content_identity"],
        "capability_manifest_identity": artifacts["capability-manifest"][
            "content_identity"
        ],
        "debug_map_identity": debug_map["content_identity"],
        "model_explanation_identity": artifacts["model-explanation"][
            "content_identity"
        ],
        "resolution_receipt_identity": resolution_receipt["content_identity"],
    }
    if any(
        build_receipt.get(key) != value
        for key, value in expected_build_bindings.items()
    ):
        raise RuntimeError("build receipt has invalid bindings")
    if (
        debug_map.get("source_identity") != source_identity
        or debug_map.get("rir_identity") != rir["content_identity"]
        or resolution_receipt.get("resolver") != _RESOLVER_IMPLEMENTATION_IDENTITY
        or resolution_receipt.get("resolution_profile") != profile["id"]
        or resolution_receipt.get("source_identity") != source_identity
        or resolution_receipt.get("kernel_identity") != kernel["content_identity"]
        or resolution_receipt.get("language_bundle_identity")
        != language_bundle["content_identity"]
        or resolution_receipt.get("package_lock_identity") != lock["content_identity"]
        or resolution_receipt.get("diagnostics") != []
    ):
        raise RuntimeError("provenance artifacts have invalid bindings")


def verify_checked_model(checked: CheckedModel) -> None:
    """Compile and self-admit a checked Model under the same authority."""
    compile_checked_model(checked)


def _lowering_inputs(
    checked: CheckedModel,
) -> tuple[
    dict[str, Any],
    list[dict[str, JsonValue]],
    dict[str, Any],
    list[tuple[dict[str, Any], tuple[object, ...]]],
]:
    lock = _package_lock(checked)
    language = _language(checked.language_bundle)
    lowering = _model_lowering(checked.language_bundle)
    source_rows = _resolved_source_symbols(checked.source, checked.language_bundle)
    declarations: list[dict[str, JsonValue]] = []
    for fields, _source_pointer in source_rows:
        fact = {
            "kind": lowering["initial_fact_kind"],
            "fields": fields,
        }
        for invocation in cast(list[dict[str, str]], lowering["rule_chain"]):
            fact = _apply_language_rule(
                language,
                rule_id=invocation["rule"],
                phase=invocation["phase"],
                judgment=invocation["judgment"],
                facts=[fact],
            )
        declarations.append(cast(dict[str, JsonValue], fact["fields"]))
    return lock, declarations, lowering, source_rows


def _model_explanation(
    authority_context: AdmittedAuthorityContext,
    lock: dict[str, JsonValue],
    rir: dict[str, JsonValue],
    debug_map: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Project the immutable human inspection companion from exact build data."""
    language_bundle = authority_context.language_bundle
    formulas = cast(list[dict[str, Any]], rir["formulas"])
    bindings = cast(list[dict[str, Any]], rir["formula_bindings"])
    selected_semantics = cast(dict[str, Any], rir["selected_semantics"])
    formula_explanations: list[dict[str, JsonValue]] = []
    for formula in formulas:
        identity = cast(str, formula["identity"])
        evaluation_sites = [
            {
                "identity": cast(dict[str, Any], binding["site"])["identity"],
                "binding_identity": binding["identity"],
                "context": cast(dict[str, Any], binding["site"])["context"],
                "operands": binding["arguments"],
                "result": formula["result"],
            }
            for binding in bindings
            if cast(dict[str, Any], binding["formula"]).get("identity") == identity
        ]
        formula_explanations.append(
            cast(
                dict[str, JsonValue],
                {
                    "module": formula["module"],
                    "id": formula["id"],
                    "identity": identity,
                    "parameters": formula["parameters"],
                    "result": formula["result"],
                    "body": formula["body"],
                    "expression": formula["expression"],
                    "closure": formula["closure"],
                    "evaluation_sites": evaluation_sites,
                },
            )
        )
    formula_explanations.sort(
        key=lambda row: (cast(str, row["module"]), cast(str, row["id"]))
    )

    formula_domains = cast(
        dict[str, str],
        _formula_policy(language_bundle)["identity_domains"],
    )
    operation_explanations: list[dict[str, JsonValue]] = []
    for row in cast(list[dict[str, Any]], selected_semantics["operations"]):
        package = cast(str, row["package"])
        definition = cast(dict[str, Any], row["definition"])
        operation_identity = _formula_operation_identity(
            formula_domains,
            package,
            cast(str, definition["version"]),
            cast(str, definition["id"]),
        )
        body = cast(list[dict[str, Any]], definition["body"])
        outcomes = cast(list[dict[str, Any]], definition.get("outcomes", []))
        operation_explanations.append(
            cast(
                dict[str, JsonValue],
                {
                    "package": package,
                    "version": definition["version"],
                    "id": definition["id"],
                    "identity": operation_identity,
                    "operation_kind": definition["operation_kind"],
                    "purity": definition["purity"],
                    "effects": definition["effects"],
                    "refusals": definition["refusals"],
                    "resource_bounds": definition["resource_bounds"],
                    "control_nodes": sorted(
                        {cast(str, instruction["node"]) for instruction in body}
                    ),
                    "rng_streams": sorted(
                        {
                            cast(str, instruction["stream"])
                            for instruction in body
                            if instruction["node"] == "draw"
                        }
                    ),
                    "outcomes": [
                        {
                            "id": outcome["id"],
                            "kind": outcome["kind"],
                            "state_policy": outcome["state_policy"],
                        }
                        for outcome in outcomes
                    ],
                    "default_outcome": definition.get("default_outcome"),
                    "formula_evaluation_sites": [
                        cast(dict[str, Any], binding["site"])["identity"]
                        for binding in bindings
                        if cast(dict[str, Any], binding["site"]).get("kind")
                        == "operation-slot"
                        and cast(
                            dict[str, Any],
                            cast(dict[str, Any], binding["site"]).get("operation", {}),
                        ).get("identity")
                        == operation_identity
                    ],
                },
            )
        )
    operation_explanations.sort(
        key=lambda row: (
            cast(str, row["package"]),
            cast(str, row["version"]),
            cast(str, row["id"]),
        )
    )
    payload = {
        "rir_identity": rir["content_identity"],
        "debug_map_identity": debug_map["content_identity"],
        "formula_explanations": cast(JsonValue, formula_explanations),
        "operation_explanations": cast(JsonValue, operation_explanations),
    }
    if not _model_explanation_pairs_are_admitted(
        cast(dict[str, Any], payload),
        cast(dict[str, Any], rir),
        cast(dict[str, Any], lock),
        authority_context,
    ):
        raise ValueError("Model explanation Formula pairs failed admission")
    return _identified_artifact(language_bundle, "model-explanation", payload)


def _capability_manifest(
    lock: dict[str, Any],
    rir: dict[str, Any],
    resolved: dict[str, Any],
    language_bundle: dict[str, Any],
) -> dict[str, JsonValue]:
    return _identified_artifact(
        language_bundle,
        "capability-manifest",
        {
            "resolved_model_identity": cast(str, resolved["content_identity"]),
            "package_lock_identity": cast(str, lock["content_identity"]),
            "rir_identity": cast(str, rir["content_identity"]),
            "packages": [
                {
                    "id": item["id"],
                    "version": item["version"],
                    "content_identity": item["content_identity"],
                }
                for item in cast(list[dict[str, str]], lock["packages"])
            ],
            "capability_bindings": cast(JsonValue, lock["capability_bindings"]),
            "types": cast(JsonValue, lock["types"]),
            "components": cast(JsonValue, lock["components"]),
            "conversions": cast(JsonValue, lock["conversions"]),
            "operations": cast(JsonValue, lock["operations"]),
            "numeric_profiles": cast(JsonValue, lock["numeric_profiles"]),
            "runtime_profiles": cast(JsonValue, lock["runtime_profiles"]),
            "language_rules": cast(JsonValue, lock["language_rules"]),
        },
    )


def lower_checked_model(checked: CheckedModel) -> dict[str, dict[str, JsonValue]]:
    """Lower one checked source to the semantic and provenance artifacts."""
    context = checked.authority_context
    if (
        context is None
        or context.kernel is not checked.kernel
        or context.language_bundle is not checked.language_bundle
    ):
        resolved_context = admit_authority_context(
            checked.kernel,
            checked.language_bundle,
        )
        if isinstance(resolved_context, BootstrapAdmission):
            raise ValueError("lowerer received authorities that failed admission")
        context = resolved_context
        checked = CheckedModel(
            source=checked.source,
            source_identity=checked.source_identity,
            kernel=context.kernel,
            language_bundle=context.language_bundle,
            authority_context=context,
        )
    if not context.admission.admitted:
        raise ValueError("lowerer received authorities that failed admission")
    lock, declarations, lowering, source_rows = _lowering_inputs(checked)
    formulas, formula_bindings, formula_debug_entries = _resolved_formulas_and_bindings(
        checked, cast(list[dict[str, Any]], declarations)
    )
    profile = _resolution_profile(
        checked.language_bundle, cast(str, lowering["resolution_profile"])
    )
    output_member = cast(str, lowering["output_member"])
    selected_semantics = _runtime_projection(
        lock,
        declarations,
        lowering,
        _runtime_projection_budget(checked.kernel, checked.language_bundle),
    )
    initialization_programs = _compile_initialization_programs(
        selected_semantics,
        cast(list[dict[str, JsonValue]], formulas),
        cast(list[dict[str, JsonValue]], formula_bindings),
        _formula_policy(checked.language_bundle),
    )
    selected_semantics = _specialize_operation_formula_slots(
        selected_semantics,
        cast(list[dict[str, JsonValue]], formulas),
        cast(list[dict[str, JsonValue]], formula_bindings),
    )
    entrypoints = _resolved_entrypoints(
        checked,
        cast(list[dict[str, Any]], declarations),
        selected_semantics,
        cast(list[dict[str, Any]], formulas),
        cast(list[dict[str, Any]], formula_bindings),
    )
    call_sites = _resolved_call_sites(
        checked.kernel,
        selected_semantics,
        _composition_policy(lowering),
    )
    rir = _identified_rir_artifact(
        checked.language_bundle,
        {
            output_member: cast(JsonValue, declarations),
            "formulas": cast(JsonValue, formulas),
            "formula_bindings": cast(JsonValue, formula_bindings),
            "initialization_programs": cast(JsonValue, initialization_programs),
            "entrypoints": cast(JsonValue, entrypoints),
            "call_sites": cast(JsonValue, call_sites),
            "selected_semantics": cast(JsonValue, selected_semantics),
        },
    )
    resolved = _identified_artifact(
        checked.language_bundle,
        "resolved-model",
        {
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_content_identity": rir["content_identity"],
            "rir_semantic_identity": rir["semantic_identity"],
        },
    )
    debug_map = _identified_artifact(
        checked.language_bundle,
        "debug-map",
        {
            "source_identity": checked.source_identity,
            "rir_identity": rir["content_identity"],
            "entries": cast(
                JsonValue,
                [
                    {
                        "rir_pointer": _pointer((output_member, index)),
                        "source_pointer": _pointer(source_rows[index][1]),
                    }
                    for index in range(len(declarations))
                ]
                + [
                    {
                        "rir_pointer": _pointer(("formulas", index)),
                        "source_pointer": source_pointer,
                    }
                    for index, (source_pointer, _identity) in enumerate(
                        formula_debug_entries
                    )
                ],
            ),
        },
    )
    model_explanation = _model_explanation(
        context,
        lock,
        rir,
        debug_map,
    )
    resolution_receipt = _identified_artifact(
        checked.language_bundle,
        "resolution-receipt",
        {
            "resolver": _RESOLVER_IMPLEMENTATION_IDENTITY,
            "resolution_profile": cast(str, profile["id"]),
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "diagnostics": [],
        },
    )
    capability_manifest = _capability_manifest(
        lock, rir, resolved, checked.language_bundle
    )
    build_receipt = _identified_artifact(
        checked.language_bundle,
        "build-receipt",
        {
            "compiler": _LOWERER_IMPLEMENTATION_IDENTITY,
            "source_identity": checked.source_identity,
            "kernel_identity": checked.kernel["content_identity"],
            "language_bundle_identity": checked.language_bundle["content_identity"],
            "package_lock_identity": lock["content_identity"],
            "rir_identity": rir["content_identity"],
            "resolved_model_identity": resolved["content_identity"],
            "capability_manifest_identity": capability_manifest["content_identity"],
            "debug_map_identity": debug_map["content_identity"],
            "model_explanation_identity": model_explanation["content_identity"],
            "resolution_receipt_identity": resolution_receipt["content_identity"],
        },
    )
    return {
        "package-lock": lock,
        "rir-semantic-payload": rir,
        "resolved-model": resolved,
        "capability-manifest": capability_manifest,
        "debug-map": debug_map,
        "model-explanation": model_explanation,
        "resolution-receipt": resolution_receipt,
        "build-receipt": build_receipt,
    }
