"""Model Source checking against one admitted authority context."""

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

from gda_balancing.domain.authority.admission import BootstrapAdmission
from gda_balancing.domain.authority.context import (
    AdmittedAuthorityContext,
    admit_authority_context,
    packaged_authority_context,
)
from gda_balancing.domain.canonical import JsonValue, canonical_bytes, content_identity
from gda_balancing.domain.diagnostics import (
    Schema2RefusalReport,
    bootstrap_refusal,
    reason_by_id,
)
from gda_balancing.domain.errors import UnreadableInputError
from gda_balancing.domain.model.resolution import (
    CheckedModel,
    _EntrypointBindingError,
    _FormulaResolutionError,
    _RuntimeProjectionResourceExhausted,
    _bounded_refusal,
    _composition_policy,
    _formula_failure_pointer,
    _formula_pair_diagnostics,
    _invalid_source_value_policy_pointer,
    _language,
    _model_check_diagnostics,
    _model_lowering,
    _path_value,
    _refusal,
    _resolution_diagnostics,
    _resolution_profile,
    _resolved_call_sites,
    _resolved_entrypoints,
    _resolved_formulas_and_bindings,
    _resolved_source_symbols,
    _runtime_projection,
    _runtime_projection_budget,
    _schema_error_diagnostics,
    _strict_object,
    _unique_reason,
)
from gda_balancing.domain.model.compilation import _lowering_inputs

def check_model_source(path: str) -> CheckedModel | Schema2RefusalReport:
    """Admit and check one Model Source Package without publishing artifacts."""
    try:
        data = Path(path).read_bytes()
    except OSError as err:
        raise UnreadableInputError(f"cannot read input document: {path}") from err

    return _check_model_source_bytes(data)


def check_model_source_value(
    source: dict[str, Any],
    *,
    authority_context: AdmittedAuthorityContext | None = None,
    kernel: dict[str, Any] | None = None,
    language_bundle: dict[str, Any] | None = None,
    authority_admission: BootstrapAdmission | None = None,
) -> CheckedModel | Schema2RefusalReport:
    """Admit an in-memory Model Source through the same authority path as a file."""
    try:
        data = canonical_bytes(cast(JsonValue, source))
    except (TypeError, ValueError, UnicodeEncodeError):
        data = b"null\n"
    return _check_model_source_bytes(
        data,
        authority_context=authority_context,
        kernel=kernel,
        language_bundle=language_bundle,
        authority_admission=authority_admission,
    )


def _check_model_source_bytes(
    data: bytes,
    *,
    authority_context: AdmittedAuthorityContext | None = None,
    kernel: dict[str, Any] | None = None,
    language_bundle: dict[str, Any] | None = None,
    authority_admission: BootstrapAdmission | None = None,
) -> CheckedModel | Schema2RefusalReport:
    if authority_context is not None and (
        kernel is not None
        or language_bundle is not None
        or authority_admission is not None
    ):
        raise ValueError(
            "authority_context cannot be combined with separate authority inputs"
        )
    if (kernel is None) != (language_bundle is None):
        raise ValueError("Kernel and LDB must be supplied together")
    if authority_context is None:
        if kernel is None or language_bundle is None:
            authority_context = packaged_authority_context()
        else:
            resolved_context = admit_authority_context(
                kernel,
                language_bundle,
                admission=authority_admission,
            )
            if isinstance(resolved_context, BootstrapAdmission):
                return bootstrap_refusal(resolved_context)
            authority_context = resolved_context
    kernel = authority_context.kernel
    ldb = authority_context.language_bundle
    source_size_reason = _unique_reason(
        ldb,
        stage="ingress",
        operation="greater-than",
        limit_path="resources.max_source_bytes",
    )
    max_source_bytes = _path_value(
        ldb, cast(str, source_size_reason["predicate"]["limit_path"])
    )
    if len(data) > max_source_bytes:
        return _refusal(
            cast(str, source_size_reason["diagnostic"]),
            "unidentified",
            "",
            "Model Source Package exceeds the admitted byte bound",
            ldb,
        )
    try:
        source = _strict_object(data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as err:
        default_profiles = [
            profile
            for profile in cast(
                list[dict[str, Any]], _language(ldb)["resolution_profiles"]
            )
            if profile.get("default") is True
        ]
        if len(default_profiles) != 1:
            raise ValueError("Model Source parsing requires one default profile")
        source_boundary = cast(dict[str, Any], default_profiles[0]["extensions"]).get(
            "standard.source-boundary"
        )
        if not isinstance(source_boundary, dict) or not isinstance(
            source_boundary.get("parse_reason"), str
        ):
            raise ValueError("default profile has no Model Source parse reason")
        parse_reason = reason_by_id(ldb, cast(str, source_boundary["parse_reason"]))
        return _refusal(
            cast(str, parse_reason["diagnostic"]),
            "unidentified",
            "",
            f"Model Source Package is outside canonical JSON: {err}",
            ldb,
        )

    lowering = _model_lowering(ldb)
    profile = _resolution_profile(ldb, cast(str, lowering["resolution_profile"]))
    source_identity = content_identity(
        cast(str, profile["source_identity_domain"]), cast(JsonValue, source)
    )
    language = _language(ldb)
    source_schema = next(
        item["schema"]
        for item in cast(list[dict[str, Any]], language["wire_schemas"])
        if item["artifact_kind"] == "model-source-package"
    )
    errors = sorted(
        jsonschema.Draft202012Validator(source_schema).iter_errors(source),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    structural_diagnostics = [
        diagnostic
        for error in errors
        for diagnostic in _schema_error_diagnostics(error, source_identity, ldb)
    ]
    model_diagnostics = _model_check_diagnostics(source, source_identity, ldb)
    static_diagnostics = [
        *structural_diagnostics,
        *model_diagnostics,
    ]
    resolution_contract = cast(
        dict[str, Any],
        cast(dict[str, Any], kernel["meta_format"])["resolution_judgment"],
    )
    for stage in cast(list[str], resolution_contract["stage_order"]):
        diagnostics = list(static_diagnostics) if stage == "static" else []
        try:
            diagnostics.extend(
                _resolution_diagnostics(
                    source,
                    source_identity,
                    kernel,
                    ldb,
                    stage=stage,
                )
            )
        except (KeyError, TypeError, ValueError):
            if not structural_diagnostics:
                raise
        refusal = _bounded_refusal(diagnostics, ldb)
        if refusal is not None:
            return refusal
    try:
        _resolved_source_symbols(source, ldb)
    except (KeyError, TypeError, ValueError) as err:
        source_contract_reason = reason_by_id(
            ldb,
            cast(str, profile["structural_reason"]),
        )
        return _refusal(
            cast(str, source_contract_reason["diagnostic"]),
            source_identity,
            "",
            f"Model Source name resolution failed: {err}",
            ldb,
        )
    checked = CheckedModel(
        source=source,
        source_identity=source_identity,
        kernel=kernel,
        language_bundle=ldb,
        authority_context=authority_context,
    )
    invalid_policy_pointer = _invalid_source_value_policy_pointer(source, ldb)
    if invalid_policy_pointer is not None:
        source_contract_reason = reason_by_id(
            ldb,
            cast(str, profile["structural_reason"]),
        )
        return _refusal(
            cast(str, source_contract_reason["diagnostic"]),
            source_identity,
            invalid_policy_pointer,
            "Model Symbol does not close the LDB assignment policy",
            ldb,
        )
    try:
        _lock, formula_declarations, _lowering, _rows = _lowering_inputs(checked)
        (
            resolved_formulas,
            resolved_formula_bindings,
            _formula_debug_entries,
        ) = _resolved_formulas_and_bindings(
            checked,
            cast(list[dict[str, Any]], formula_declarations),
        )
    except (KeyError, TypeError, ValueError) as err:
        message = str(err)
        formula_reason = (
            reason_by_id(ldb, err.reason_id)
            if isinstance(err, _FormulaResolutionError)
            else reason_by_id(
                ldb,
                cast(str, profile["structural_reason"]),
            )
        )
        return _refusal(
            cast(str, formula_reason["diagnostic"]),
            source_identity,
            (
                err.pointer
                if isinstance(err, _FormulaResolutionError)
                else _formula_failure_pointer(source, message)
            ),
            f"Model Formula resolution failed: {message}",
            ldb,
        )
    formula_pair_refusal = _bounded_refusal(
        _formula_pair_diagnostics(source, source_identity, authority_context),
        ldb,
    )
    if formula_pair_refusal is not None:
        return formula_pair_refusal
    try:
        lock, declarations, admitted_lowering, _source_rows = _lowering_inputs(checked)
        selected_semantics = _runtime_projection(
            lock,
            declarations,
            admitted_lowering,
            _runtime_projection_budget(kernel, ldb),
        )
        _resolved_entrypoints(
            checked,
            cast(list[dict[str, Any]], declarations),
            selected_semantics,
            cast(list[dict[str, Any]], resolved_formulas),
            cast(list[dict[str, Any]], resolved_formula_bindings),
        )
        _resolved_call_sites(
            kernel,
            selected_semantics,
            _composition_policy(admitted_lowering),
        )
    except _RuntimeProjectionResourceExhausted:
        resource_reason = _unique_reason(
            ldb,
            stage="static",
            operation="greater-than",
            limit_path="resources.max_runtime_projection_steps",
        )
        return _refusal(
            cast(str, resource_reason["diagnostic"]),
            source_identity,
            "",
            "Model Source runtime projection exhausted its admitted step budget",
            ldb,
        )
    except _EntrypointBindingError as err:
        source_contract_reason = reason_by_id(
            ldb,
            cast(str, profile["structural_reason"]),
        )
        return _refusal(
            cast(str, source_contract_reason["diagnostic"]),
            source_identity,
            err.pointer,
            f"Model entrypoint resolution failed: {err}",
            ldb,
        )
    except (KeyError, TypeError, ValueError) as err:
        source_contract_reason = reason_by_id(
            ldb,
            cast(str, profile["structural_reason"]),
        )
        return _refusal(
            cast(str, source_contract_reason["diagnostic"]),
            source_identity,
            "/entrypoints",
            f"Model entrypoint resolution failed: {err}",
            ldb,
        )
    return checked
