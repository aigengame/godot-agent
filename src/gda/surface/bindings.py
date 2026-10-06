"""The argv form a command publishes in its schema (ADR-0045 §2).

Split out of the headless descriptor module: :func:`command_argv_bindings` and its
three helpers. The per-command ``--schema`` (:mod:`gda.surface.descriptor`) and the
manifest builder (:mod:`gda.surface.manifest`) both call it, so it imports neither.
"""

from typing import Any, Optional

from pydantic import BaseModel

from gda.core.contract.schema import ArgvBinding, ArgvKind
from gda.surface.options import _GLOBAL_OPTION_NAMES


def command_argv_bindings(
    command: object, input_model: type[BaseModel]
) -> list[ArgvBinding]:
    """Project ``command``'s live Click parameters into their CLI spelling (#669).

    The one place a command's argv form is derived, shared by the per-command
    ``--schema`` (``gda.surface.descriptor``) and the aggregate manifest builder
    (``gda.surface.manifest``) so the two forms cannot drift — the same shape
    :func:`~gda.surface.descriptor.command_constraints` gives the live-stack
    precondition. The rationale, the boundaries and the case inventory live in the
    ADR-0004 amendment (#669); this is the derivation.

    Which parameters are operational reuses a rule ``gda.surface.options`` already owns:
    :data:`~gda.surface.options._GLOBAL_OPTION_NAMES`, the same set ``--params-json``
    treats as cross-cutting (ADR-0015). The ``expose_value`` arm has no case on today's
    surface — Click appends its own ``--help`` in ``get_params``, not here — and guards
    a future unexposed parameter, which by definition reaches no params model.

    Click is duck-typed through ``getattr``, as the surface walker does: it is a
    transitive dependency through Typer, not a direct one.
    """
    properties = input_model.model_json_schema().get("properties", {})
    bindings: list[ArgvBinding] = []
    position = 0
    for param in getattr(command, "params", []):
        if not getattr(param, "expose_value", True):
            continue
        name = getattr(param, "name", None)
        if not isinstance(name, str) or name in _GLOBAL_OPTION_NAMES:
            continue
        opts = [str(opt) for opt in getattr(param, "opts", [])]
        is_argument = getattr(param, "param_type_name", "") == "argument"
        long_opts = [opt for opt in opts if opt.startswith("--")]
        option = None if is_argument else next(iter(long_opts or opts), None)
        # A variadic positional (``nargs=-1``) is repeated the same way a
        # repeatable option is, so both report ``multiple``: Click spells the
        # two differently, an argv author writes both by repeating.
        nargs = getattr(param, "nargs", 1)
        multiple = bool(getattr(param, "multiple", False)) or nargs == -1
        bound = _bound_property(name, option, properties)
        bindings.append(
            ArgvBinding(
                name=name,
                input_property=bound,
                kind=ArgvKind.ARGUMENT if is_argument else ArgvKind.OPTION,
                option=option,
                position=position if is_argument else None,
                required=bool(getattr(param, "required", False)),
                flag=bool(getattr(param, "is_flag", False)),
                multiple=multiple,
                json_value=_takes_a_json_value(bound, properties, multiple),
            )
        )
        if is_argument:
            position += 1
    return bindings


def _bound_property(
    name: str, option: Optional[str], properties: "dict[str, Any]"
) -> Optional[str]:
    """The ``input`` property this parameter fills, or ``None`` if undecidable."""
    if name in properties:
        return name
    if option is not None:
        spelled = option.lstrip("-").replace("-", "_")
        if spelled in properties:
            return spelled
    return None


def _takes_a_json_value(
    bound: Optional[str], properties: "dict[str, Any]", multiple: bool
) -> bool:
    """Whether the parameter's one token is the property's JSON encoding (#669).

    A compound property reaches argv as a REPEATED token, which ``multiple``
    already reports, or as a single token carrying its JSON. ``False`` without a
    property link: unknown, and a wrong ``true`` would send a caller to encode a
    plain string. Sees a declared ``type`` and a compound behind an ``anyOf`` /
    ``oneOf`` — the nullable-compound shape (``list | null``) that
    ``--await-events`` introduced (#661); a registration test keeps this
    detector and the published bindings agreeing
    (``tests/meta/test_schema_command.py``).
    """
    spec = properties.get(bound or "")
    if not isinstance(spec, dict) or multiple:
        return False
    return _is_compound_spec(spec)


def _is_compound_spec(spec: "dict[str, Any]") -> bool:
    """Whether a property schema is an array/object, INCLUDING behind an anyOf."""
    if spec.get("type") in ("array", "object"):
        return True
    branches = spec.get("anyOf") or spec.get("oneOf") or []
    return any(
        _is_compound_spec(branch) for branch in branches if isinstance(branch, dict)
    )
