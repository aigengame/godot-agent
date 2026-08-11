"""Template release admission, validation, instantiation, and built-in content."""

from ._release_semantics import (
    TemplateProvider,
    load_admitted_template,
    prepare_template_instantiation,
    template_refusal,
    validate_template_release,
)
from .quantity_minimal import minimal_release

__all__ = (
    "TemplateProvider",
    "load_admitted_template",
    "minimal_release",
    "prepare_template_instantiation",
    "template_refusal",
    "validate_template_release",
)
