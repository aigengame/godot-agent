"""Model checking, compilation, admission, and inspection Interface."""

from ._admission import admit_resolved_model
from ._checking import check_model_source, check_model_source_value
from ._compilation import (
    authority_context_for_checked,
    compile_checked_model,
    model_build_command_input_identity,
    validate_compiled_artifacts,
    verify_checked_model,
)
from ._inspection import read_model_explanation
from ._inspection_types import ModelInspectAdmissionError
from ._lowering import checked_model_template_facts
from ._resolution import (
    MODEL_INSPECT_REFUSAL_CATALOG,
    MODEL_REFUSAL_CATALOG,
    CheckedModel,
    model_source_identity_domain,
)

__all__ = (
    "MODEL_INSPECT_REFUSAL_CATALOG",
    "MODEL_REFUSAL_CATALOG",
    "CheckedModel",
    "ModelInspectAdmissionError",
    "admit_resolved_model",
    "authority_context_for_checked",
    "check_model_source",
    "check_model_source_value",
    "checked_model_template_facts",
    "compile_checked_model",
    "model_build_command_input_identity",
    "model_source_identity_domain",
    "read_model_explanation",
    "validate_compiled_artifacts",
    "verify_checked_model",
)
