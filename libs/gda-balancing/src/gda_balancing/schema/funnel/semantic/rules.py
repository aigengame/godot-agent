"""The semantic rule **registry** — one frozen rule object per rule (bADR-0005).

The semantic phase's rules are declared here as a single tuple of
:class:`SemanticRule` objects. That registry is the one authority; both the
published rule catalog (:func:`gda_balancing.schema.artifacts.generate_catalog`)
and the conformance walk are **projections** of it, never parallel copies
(bADR-0005 anti-drift). A rule's ``code`` is simultaneously its stable refusal
code, its catalog id, and the semantic rule id bADR-0004 refers to — one
identity.

Every rule carries a ``check`` closing over the typed :class:`DesignDocument`
plus the raw parsed dict (the ``$schema`` and reserved-section rules read raw
keys the model excludes/aliases), and a ``violation_fixture`` — a complete
Design document that is valid **except** for this one rule, so the conformance
harness can assert each rule refuses exactly its fixture (bADR-0004).

Scope note: reference-integrity (undefined ``attr``/``param``) applies to
attribute **base formulas** and effect **magnitudes** alike — both share the one
walker (:func:`gda_balancing.schema.funnel.semantic.graph.iter_references`),
which each caller drives with its own root-pointer tokens. Effect magnitudes join
the reference walk but **not** the base-formula acyclicity graph (a magnitude may
reference its own target — bADR-0003/0006).
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from gda_balancing.envelope import Refusal
from gda_balancing.schema import pointer
from gda_balancing.schema.funnel.semantic.graph import (
    Tokens,
    cyclic_components,
    iter_references,
)
from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema.model.effects import Effect, TimedDuration
from gda_balancing.schema.model.formula import (
    BinaryOp,
    DirectBase,
    ExponentialForm,
    Formula,
    FormulaBase,
    LinearForm,
    LookupTableForm,
    NaryOp,
    ParamRef,
    PiecewiseLinearForm,
    PolynomialForm,
    UnaryOp,
)
from gda_balancing.schema.version import STRUCTURAL_SCHEMA_ID

# v1 normative expression-tree limits (bADR-0003); raising either is a minor bump.
MAX_TREE_DEPTH = 32
MAX_TREE_NODES = 256

# v1 effect temporal bounds (bADR-0006): the minimum tick granularity in seconds
# and the per-instance tick budget (duration / period) any timed effect declaring
# a period must respect. Raising either is a minor bump.
MIN_PERIOD_SECONDS = 0.05
MAX_TICK_BUDGET = 10_000

# The line the whole v1 rule set appeared in — line granularity, matching
# bADR-0001's acceptance granularity (a validator serving X.Y ships every rule
# of X.0..X.Y). Not the full patch version.
_SINCE = "1.0"

# The reserved top-level sections (bADR-0001): present in a v1 document ⇒ refused
# until the owning issue lands the section's shape (V12).
RESERVED_SECTIONS = ("combat", "encounters", "builds", "growth", "economy", "targets")

# Concrete operator-node classes — the ``Node``/``OpNode`` aliases are subscripted
# generics, so ``isinstance`` names the members.
_OP_TYPES = (NaryOp, BinaryOp, UnaryOp)
# The v1 named-form classes — a formula that is one of these is a form, else a tree.
_FORM_TYPES = (
    LinearForm,
    PiecewiseLinearForm,
    PolynomialForm,
    ExponentialForm,
    LookupTableForm,
)

Check = Callable[[DesignDocument, dict[str, Any]], list[Refusal]]


@dataclass(frozen=True)
class SemanticRule:
    """One semantic rule — its own catalog entry, refusal-code owner, and check.

    ``code`` is the stable id (== refusal code == catalog id); ``scope`` is the
    JSON Pointer *template* it applies to (``{id}``/``{section}`` placeholders);
    ``description`` is the human catalog line; ``since_version`` is the schema
    line the rule appeared in; ``check`` collects this rule's refusals over a
    document; ``violation_fixture`` is a complete Design document refusing with
    exactly this code.
    """

    code: str
    scope: str
    description: str
    since_version: str
    check: Check
    violation_fixture: dict[str, Any]


# --- Pointer helpers -------------------------------------------------------


def _attr_tokens(attr_id: str) -> tuple[str, ...]:
    return ("attributes", "items", attr_id)


def _base_tokens(attr_id: str) -> tuple[str, ...]:
    return (*_attr_tokens(attr_id), "base")


def _bounds_tokens(attr_id: str) -> tuple[str, ...]:
    return (*_attr_tokens(attr_id), "bounds")


def _formula_tokens(attr_id: str) -> tuple[str, ...]:
    return (*_attr_tokens(attr_id), "base", "formula")


def _effect_tokens(effect_id: str) -> tuple[str, ...]:
    return ("effects", "items", effect_id)


def _modifier_tokens(effect_id: str, index: int) -> tuple[str | int, ...]:
    return (*_effect_tokens(effect_id), "modifiers", index)


def _magnitude_tokens(effect_id: str, index: int) -> tuple[str | int, ...]:
    return (*_modifier_tokens(effect_id, index), "magnitude")


def _refuse(code: str, tokens: tuple[str | int, ...], detail: str) -> Refusal:
    return Refusal(code=code, path=pointer.build(*tokens), detail=detail)


def _is_instant(effect: Effect) -> bool:
    """An ``instant`` duration leaves no persistent instance (bADR-0006)."""
    return effect.duration == "instant"


def _timed_seconds(effect: Effect) -> float | None:
    """The seconds of a ``timed`` duration, or ``None`` for instant/infinite."""
    duration = effect.duration
    return duration.timed if isinstance(duration, TimedDuration) else None


# --- Tree shape helpers ----------------------------------------------------


def _is_tree(formula: object) -> bool:
    """A base formula is an expression tree iff it is not a named form."""
    return not isinstance(formula, _FORM_TYPES)


def _tree_depth(node: object) -> int:
    if isinstance(node, _OP_TYPES):
        return 1 + max(_tree_depth(arg) for arg in node.args)
    return 1


def _tree_size(node: object) -> int:
    if isinstance(node, _OP_TYPES):
        return 1 + sum(_tree_size(arg) for arg in node.args)
    return 1


def _strictly_increasing(pairs: tuple[tuple[float, float], ...]) -> bool:
    xs = [x for x, _y in pairs]
    return all(a < b for a, b in zip(xs, xs[1:]))


# --- Rule checks -----------------------------------------------------------


def _iter_reference_formulas(
    doc: DesignDocument,
) -> Iterator[tuple[Formula, Tokens]]:
    """Every formula whose references the integrity rules must check, paired with
    its RFC 6901 root tokens: each attribute **base formula** (bADR-0002/0003)
    and each effect-**magnitude** formula (bADR-0006). A magnitude that is a bare
    scalar number carries no references and is skipped — only a named form or an
    expression tree (both pydantic models) yields references. Effect magnitudes
    join the reference-integrity walk but **not** the base-formula acyclicity
    graph: a magnitude may reference its own target (bADR-0003), so it adds no
    dependency edge."""
    for attr_id, attribute in doc.attributes.items.items():
        base = attribute.base
        if isinstance(base, FormulaBase):
            yield base.formula, _formula_tokens(attr_id)
    for effect_id, effect in doc.effects.items.items():
        for index, modifier in enumerate(effect.modifiers):
            magnitude = modifier.magnitude
            if isinstance(magnitude, BaseModel):  # a formula, not a bare scalar
                yield magnitude, _magnitude_tokens(effect_id, index)


def _reference_undefined(
    doc: DesignDocument, want_kind: str, code: str, is_declared: Callable[[str], bool]
) -> list[Refusal]:
    """Shared driver for the two reference-integrity rules: walk every base
    formula's and effect magnitude's references of ``want_kind`` and refuse each
    undeclared id at its own node pointer."""
    refusals: list[Refusal] = []
    for formula, base_tokens in _iter_reference_formulas(doc):
        for kind, ref_id, tokens in iter_references(formula, base_tokens):
            if kind == want_kind and not is_declared(ref_id):
                refusals.append(
                    _refuse(code, tokens, f"undefined {want_kind} reference {ref_id!r}")
                )
    return refusals


def _check_attribute_reference_undefined(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    items = doc.attributes.items
    return _reference_undefined(
        doc, "attr", "attribute_reference_undefined", lambda ref: ref in items
    )


def _check_parameter_reference_undefined(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    params = doc.parameters
    return _reference_undefined(
        doc, "param", "parameter_reference_undefined", lambda ref: ref in params
    )


def _check_tier_reference_undefined(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    tiers = doc.attributes.tiers
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        if attribute.tier is not None and attribute.tier not in tiers:
            refusals.append(
                _refuse(
                    "tier_reference_undefined",
                    (*_attr_tokens(attr_id), "tier"),
                    f"tier label {attribute.tier!r} names no declared tier",
                )
            )
    return refusals


def _check_base_formula_cycle(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for component in cyclic_components(doc):
        detail = "base-formula reference cycle among: " + ", ".join(component)
        for attr_id in component:
            refusals.append(
                _refuse("base_formula_cycle", (*_attr_tokens(attr_id), "base"), detail)
            )
    return refusals


def _check_allocation_requires_direct_base(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        if "allocation" in attribute.accepts and isinstance(
            attribute.base, FormulaBase
        ):
            refusals.append(
                _refuse(
                    "allocation_requires_direct_base",
                    _attr_tokens(attr_id),
                    "accepts 'allocation' but has a formula base "
                    "(allocation is legal only on a direct base)",
                )
            )
    return refusals


def _check_bounds_required_for_domain(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        if (
            attribute.domain in ("percentage", "probability")
            and attribute.bounds is None
        ):
            refusals.append(
                _refuse(
                    "bounds_required_for_domain",
                    _attr_tokens(attr_id),
                    f"domain {attribute.domain!r} requires declared bounds",
                )
            )
    return refusals


def _check_bounds_empty(doc: DesignDocument, _raw: dict[str, Any]) -> list[Refusal]:
    """A declared ``bounds`` object must declare at least one of ``floor``/``cap``
    (bADR-0002): an empty ``bounds`` narrows nothing, and on the mandatory
    domains it would void the domain's bounds obligation. Domain-independent — a
    ``bounds: {}`` is meaningless in every domain."""
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        bounds = attribute.bounds
        if bounds is not None and bounds.floor is None and bounds.cap is None:
            refusals.append(
                _refuse(
                    "bounds_empty",
                    _bounds_tokens(attr_id),
                    "declared bounds must declare at least one of floor/cap",
                )
            )
    return refusals


def _check_bounds_inverted(doc: DesignDocument, _raw: dict[str, Any]) -> list[Refusal]:
    """With both sides present, ``floor`` must not exceed ``cap`` (bADR-0002):
    an inverted interval clamps every value to an empty range."""
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        bounds = attribute.bounds
        if (
            bounds is not None
            and bounds.floor is not None
            and bounds.cap is not None
            and bounds.floor > bounds.cap
        ):
            refusals.append(
                _refuse(
                    "bounds_inverted",
                    _bounds_tokens(attr_id),
                    f"bounds floor {bounds.floor} exceeds cap {bounds.cap}",
                )
            )
    return refusals


def _check_bounds_outside_domain(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    """A ``probability`` attribute's bounds declare *design* limits narrowing
    within the domain's representable ``[0, 1]`` space (bADR-0002); a declared
    side outside ``[0, 1]`` is not a narrowing but a contradiction of the domain.
    ``percentage`` fractions are unbounded above, and ``number`` is unbounded —
    neither carries a range rule."""
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        if attribute.domain != "probability":
            continue
        bounds = attribute.bounds
        if bounds is None:
            continue
        sides = [side for side in (bounds.floor, bounds.cap) if side is not None]
        if any(side < 0 or side > 1 for side in sides):
            refusals.append(
                _refuse(
                    "bounds_outside_domain",
                    _bounds_tokens(attr_id),
                    "probability bounds must lie within the domain's [0, 1] space",
                )
            )
    return refusals


def _check_base_outside_domain(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    """A ``probability`` domain pins the representable value space to ``[0, 1]``
    (bADR-0002); a ``direct`` base outside it is a static design error. Only the
    direct scalar is statically checkable — a formula base evaluates at
    definition time and is clamped by the pipeline (bADR-0002/0003), so it
    carries no static rule."""
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        if attribute.domain != "probability":
            continue
        base = attribute.base
        if isinstance(base, DirectBase) and (base.direct < 0 or base.direct > 1):
            refusals.append(
                _refuse(
                    "base_outside_domain",
                    _base_tokens(attr_id),
                    "a probability direct base must lie within the domain's "
                    "[0, 1] space",
                )
            )
    return refusals


def _check_tier_pattern_unsatisfied(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    tiers = doc.attributes.tiers
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        tier_name = attribute.tier
        # An undefined tier is `tier_reference_undefined`'s job — no cascade.
        if tier_name is None or tier_name not in tiers:
            continue
        pattern = tiers[tier_name]
        if _violates_tier_pattern(attribute, pattern):
            refusals.append(
                _refuse(
                    "tier_pattern_unsatisfied",
                    _attr_tokens(attr_id),
                    f"does not satisfy the facet pattern of tier {tier_name!r}",
                )
            )
    return refusals


def _violates_tier_pattern(attribute: Any, pattern: Any) -> bool:
    """Tier-pattern satisfaction (bADR-0002): omitted facet unconstrained;
    ``domain`` by equality; ``base`` by declared kind; ``accepts`` by EXACT set
    equality (V4)."""
    if pattern.domain is not None and pattern.domain != attribute.domain:
        return True
    base_kind = "direct" if isinstance(attribute.base, DirectBase) else "formula"
    if pattern.base is not None and pattern.base != base_kind:
        return True
    if pattern.accepts is not None and set(pattern.accepts) != set(attribute.accepts):
        return True
    return False


def _iter_formula_bases(doc: DesignDocument):
    """Yield ``(attr_id, formula)`` for every attribute with a formula base."""
    for attr_id, attribute in doc.attributes.items.items():
        base = attribute.base
        if isinstance(base, FormulaBase):
            yield attr_id, base.formula


def _check_form_points_not_increasing(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, formula in _iter_formula_bases(doc):
        if isinstance(formula, PiecewiseLinearForm) and not _strictly_increasing(
            formula.points
        ):
            refusals.append(
                _refuse(
                    "form_points_not_increasing",
                    (*_formula_tokens(attr_id), "points"),
                    "piecewise_linear points must have strictly increasing x",
                )
            )
        elif isinstance(formula, LookupTableForm) and not _strictly_increasing(
            formula.table
        ):
            refusals.append(
                _refuse(
                    "form_points_not_increasing",
                    (*_formula_tokens(attr_id), "table"),
                    "lookup_table entries must have strictly increasing x",
                )
            )
    return refusals


def _check_form_points_insufficient(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, formula in _iter_formula_bases(doc):
        if isinstance(formula, PiecewiseLinearForm) and len(formula.points) < 2:
            refusals.append(
                _refuse(
                    "form_points_insufficient",
                    (*_formula_tokens(attr_id), "points"),
                    "piecewise_linear requires at least 2 points",
                )
            )
        elif isinstance(formula, LookupTableForm) and len(formula.table) < 1:
            refusals.append(
                _refuse(
                    "form_points_insufficient",
                    (*_formula_tokens(attr_id), "table"),
                    "lookup_table requires at least 1 entry",
                )
            )
    return refusals


def _check_form_coefficients_count_invalid(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, formula in _iter_formula_bases(doc):
        if (
            isinstance(formula, PolynomialForm)
            and not 1 <= len(formula.coefficients) <= 8
        ):
            refusals.append(
                _refuse(
                    "form_coefficients_count_invalid",
                    (*_formula_tokens(attr_id), "coefficients"),
                    "polynomial requires 1 to 8 coefficients",
                )
            )
    return refusals


def _check_exponential_growth_rate_positive(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, formula in _iter_formula_bases(doc):
        if not isinstance(formula, ExponentialForm):
            continue
        rate = formula.growth_rate
        if isinstance(rate, ParamRef):
            # Undeclared param ⇒ `parameter_reference_undefined` already fires;
            # skip so this rule adds no cascade noise.
            if rate.param not in doc.parameters:
                continue
            value = doc.parameters[rate.param]
        else:
            value = rate
        if value <= 0:
            refusals.append(
                _refuse(
                    "exponential_growth_rate_positive",
                    (*_formula_tokens(attr_id), "growth_rate"),
                    "exponential growth_rate must be positive",
                )
            )
    return refusals


def _check_expression_tree_too_deep(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, formula in _iter_formula_bases(doc):
        if _is_tree(formula) and _tree_depth(formula) > MAX_TREE_DEPTH:
            refusals.append(
                _refuse(
                    "expression_tree_too_deep",
                    _formula_tokens(attr_id),
                    f"expression tree depth exceeds {MAX_TREE_DEPTH}",
                )
            )
    return refusals


def _check_expression_tree_too_large(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for attr_id, formula in _iter_formula_bases(doc):
        if _is_tree(formula) and _tree_size(formula) > MAX_TREE_NODES:
            refusals.append(
                _refuse(
                    "expression_tree_too_large",
                    _formula_tokens(attr_id),
                    f"expression tree exceeds {MAX_TREE_NODES} nodes",
                )
            )
    return refusals


def _schema_reference_disagreement_check(structural_schema_id: str) -> Check:
    """The ``$schema``-agreement check for one line, closing over *that line's*
    structural-schema ``$id``. This is the only line-specific rule (bADR-0001):
    a document's ``$schema`` must resolve to the ``$id`` of the version it
    declares, so the comparison target is the resolved bundle's id — never a
    process-global 'current' id. The check keeps the ``(doc, raw)`` signature
    every other rule has; the id is captured, not passed."""

    def check(_doc: DesignDocument, raw: dict[str, Any]) -> list[Refusal]:
        reference = raw.get("$schema")
        if reference is not None and reference != structural_schema_id:
            return [
                _refuse(
                    "schema_reference_disagreement",
                    ("$schema",),
                    "$schema does not match the versioned structural schema $id",
                )
            ]
        return []

    return check


def _check_reserved_section_present(
    _doc: DesignDocument, raw: dict[str, Any]
) -> list[Refusal]:
    return [
        _refuse(
            "reserved_section_present",
            (section,),
            f"reserved section {section!r} is refused until designed",
        )
        for section in RESERVED_SECTIONS
        if section in raw
    ]


# --- Effect rule checks (bADR-0006) ----------------------------------------


def _check_modifier_target_undefined(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    items = doc.attributes.items
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        for index, modifier in enumerate(effect.modifiers):
            if modifier.target not in items:
                refusals.append(
                    _refuse(
                        "modifier_target_undefined",
                        _modifier_tokens(effect_id, index),
                        f"modifier target {modifier.target!r} names no declared "
                        "attribute",
                    )
                )
    return refusals


def _check_stacking_type_undefined(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    types = doc.effects.stacking_types
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        stacking = effect.stacking
        if stacking is not None and stacking.type not in types:
            refusals.append(
                _refuse(
                    "stacking_type_undefined",
                    (*_effect_tokens(effect_id), "stacking"),
                    f"stacking type {stacking.type!r} names no declared stacking type",
                )
            )
    return refusals


def _check_application_duration_illegal(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    """An ``instant`` effect admits only ``one_shot`` modifiers; ``continuous``/
    ``periodic`` require ``timed``/``infinite`` (bADR-0006)."""
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        if not _is_instant(effect):
            continue
        for index, modifier in enumerate(effect.modifiers):
            if modifier.application != "one_shot":
                refusals.append(
                    _refuse(
                        "application_duration_illegal",
                        _modifier_tokens(effect_id, index),
                        f"application {modifier.application!r} is illegal on an "
                        "instant effect (instant admits only one_shot)",
                    )
                )
    return refusals


def _check_instant_effect_forbids_stacking(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        if _is_instant(effect) and effect.stacking is not None:
            refusals.append(
                _refuse(
                    "instant_effect_forbids_stacking",
                    (*_effect_tokens(effect_id), "stacking"),
                    "an instant effect leaves no persistent instance to stack "
                    "or refresh",
                )
            )
    return refusals


def _check_persistent_effect_requires_stacking(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        if not _is_instant(effect) and effect.stacking is None:
            refusals.append(
                _refuse(
                    "persistent_effect_requires_stacking",
                    _effect_tokens(effect_id),
                    "a timed/infinite effect must declare stacking",
                )
            )
    return refusals


def _check_override_forbidden_on_delta(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    """``override`` is a set, not a delta — illegal on ``one_shot``/``periodic``
    (delta) modifiers (bADR-0006)."""
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        for index, modifier in enumerate(effect.modifiers):
            if modifier.operation == "override" and modifier.application in (
                "one_shot",
                "periodic",
            ):
                refusals.append(
                    _refuse(
                        "override_forbidden_on_delta",
                        _modifier_tokens(effect_id, index),
                        "override is illegal on a one_shot/periodic (delta) modifier",
                    )
                )
    return refusals


def _check_period_required_for_periodic(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        has_periodic = any(m.application == "periodic" for m in effect.modifiers)
        if has_periodic and effect.period is None:
            refusals.append(
                _refuse(
                    "period_required_for_periodic",
                    _effect_tokens(effect_id),
                    "a periodic modifier requires the effect to declare a period",
                )
            )
    return refusals


def _check_period_forbidden_when_all_one_shot(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        all_one_shot = all(m.application == "one_shot" for m in effect.modifiers)
        if effect.period is not None and all_one_shot:
            refusals.append(
                _refuse(
                    "period_forbidden_when_all_one_shot",
                    (*_effect_tokens(effect_id), "period"),
                    "period is forbidden when every modifier is one_shot "
                    "(nothing ticks)",
                )
            )
    return refusals


def _check_temporal_value_not_positive(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    """A ``timed`` duration and any ``period`` must be positive (finiteness is an
    ingress guarantee; bADR-0006)."""
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        seconds = _timed_seconds(effect)
        if seconds is not None and not seconds > 0:
            refusals.append(
                _refuse(
                    "temporal_value_not_positive",
                    (*_effect_tokens(effect_id), "duration"),
                    "a timed duration must be positive",
                )
            )
        if effect.period is not None and not effect.period > 0:
            refusals.append(
                _refuse(
                    "temporal_value_not_positive",
                    (*_effect_tokens(effect_id), "period"),
                    "a period must be positive",
                )
            )
    return refusals


def _check_period_below_minimum_granularity(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    """``period ≥ 0.05`` seconds — the v1 minimum tick granularity (bADR-0006). A
    non-positive period is ``temporal_value_not_positive``'s job; this rule fires
    only on a positive-but-too-small period, so the two never cascade."""
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        period = effect.period
        if period is not None and 0 < period < MIN_PERIOD_SECONDS:
            refusals.append(
                _refuse(
                    "period_below_minimum_granularity",
                    (*_effect_tokens(effect_id), "period"),
                    f"period must be at least {MIN_PERIOD_SECONDS} seconds "
                    "(v1 minimum granularity)",
                )
            )
    return refusals


def _check_tick_budget_exceeded(
    doc: DesignDocument, _raw: dict[str, Any]
) -> list[Refusal]:
    """For any ``timed`` effect declaring ``period`` — whether its ticks drive
    periodic deltas or continuous re-evaluation — ``duration / period ≤ 10 000``
    (bADR-0006). Infinite effects are bounded by the simulation horizon, not
    here. A non-positive duration or period is another rule's job; this one
    guards ``> 0`` before dividing but does **not** skip a granularity violation,
    so the report-all dual case (V6) lists both."""
    refusals: list[Refusal] = []
    for effect_id, effect in doc.effects.items.items():
        seconds = _timed_seconds(effect)
        period = effect.period
        if (
            seconds is not None
            and seconds > 0
            and period is not None
            and period > 0
            and seconds / period > MAX_TICK_BUDGET
        ):
            refusals.append(
                _refuse(
                    "tick_budget_exceeded",
                    (*_effect_tokens(effect_id), "period"),
                    f"duration / period exceeds the per-instance tick budget of "
                    f"{MAX_TICK_BUDGET}",
                )
            )
    return refusals


# --- Violation-fixture builders --------------------------------------------


def _base_document() -> dict[str, Any]:
    """The smallest valid document, ready to receive one violating section."""
    return {"schema_version": "1.0.0", "meta": {"name": "fixture"}}


def _with(**sections: Any) -> dict[str, Any]:
    return {**_base_document(), **sections}


def _nested_floor(depth: int) -> dict[str, Any]:
    """A unary ``floor`` chain of expression-tree depth ``depth`` (``depth - 1``
    ops around a literal leaf)."""
    node: dict[str, Any] = {"literal": 1}
    for _ in range(depth - 1):
        node = {"op": "floor", "args": [node]}
    return node


def _wide_add(leaves: int) -> dict[str, Any]:
    """A single ``add`` over ``leaves`` literal args — ``leaves + 1`` nodes, but
    only depth 2 (so it exercises the node-count limit, not the depth limit)."""
    return {"op": "add", "args": [{"literal": 1} for _ in range(leaves)]}


def _effects_fixture(effects: dict[str, Any]) -> dict[str, Any]:
    """A valid document with a ``power`` target attribute plus the given
    ``effects`` section — the enclosing document for the effect-rule fixtures."""
    return _with(
        attributes={
            "items": {
                "power": {
                    "domain": "number",
                    "base": {"direct": 10},
                    "accepts": ["effects"],
                }
            }
        },
        effects=effects,
    )


def _modifier(
    application: str,
    *,
    operation: str = "add",
    target: str = "power",
    magnitude: Any = 5,
) -> dict[str, Any]:
    """One modifier — ``continuous`` ``add`` on ``power`` with a literal
    magnitude by default; each field overridable for a specific fixture."""
    return {
        "target": target,
        "operation": operation,
        "application": application,
        "magnitude": magnitude,
    }


# A stacking-type catalog + reference every persistent-effect fixture reuses.
_STACKING_TYPES = {"combine": {"aggregation": "stack"}}
_STACKING = {"type": "combine", "lifetime": "independent"}


# --- The one registry ------------------------------------------------------

# Every rule whose behavior does not depend on the resolved line — all but
# `schema_reference_disagreement`, which compares against the line's own
# structural-schema `$id` and so is spliced in per-line by `build_semantic_rules`.
_LINE_INDEPENDENT_RULES: tuple[SemanticRule, ...] = (
    SemanticRule(
        code="attribute_reference_undefined",
        scope=(
            "/attributes/items/{id}/base/formula, "
            "/effects/items/{id}/modifiers/{index}/magnitude"
        ),
        description=(
            "An attr node — in an attribute base formula or an effect magnitude "
            "— references an id not declared in attributes.items."
        ),
        since_version=_SINCE,
        check=_check_attribute_reference_undefined,
        violation_fixture=_with(
            attributes={
                "items": {
                    "strike": {
                        "domain": "number",
                        "base": {"formula": {"attr": "missing"}},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="parameter_reference_undefined",
        scope=(
            "/attributes/items/{id}/base/formula, "
            "/effects/items/{id}/modifiers/{index}/magnitude"
        ),
        description=(
            "A param node — in an attribute base formula or an effect magnitude "
            "— references an id not declared in parameters."
        ),
        since_version=_SINCE,
        check=_check_parameter_reference_undefined,
        violation_fixture=_with(
            attributes={
                "items": {
                    "strike": {
                        "domain": "number",
                        "base": {"formula": {"param": "missing"}},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="tier_reference_undefined",
        scope="/attributes/items/{id}",
        description="An attribute's tier label names no declared tier.",
        since_version=_SINCE,
        check=_check_tier_reference_undefined,
        violation_fixture=_with(
            attributes={
                "items": {
                    "vigor": {
                        "domain": "number",
                        "base": {"direct": 5},
                        "tier": "ghost",
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="base_formula_cycle",
        scope="/attributes/items/{id}/base",
        description=(
            "An attribute participates in a cycle of the base-formula dependency graph."
        ),
        since_version=_SINCE,
        check=_check_base_formula_cycle,
        violation_fixture=_with(
            attributes={
                "items": {
                    "alpha": {
                        "domain": "number",
                        "base": {"formula": {"attr": "beta"}},
                    },
                    "beta": {
                        "domain": "number",
                        "base": {"formula": {"attr": "alpha"}},
                    },
                }
            }
        ),
    ),
    SemanticRule(
        code="allocation_requires_direct_base",
        scope="/attributes/items/{id}",
        description=(
            "An attribute accepts 'allocation' but declares a formula base "
            "(allocation is legal only on a direct base)."
        ),
        since_version=_SINCE,
        check=_check_allocation_requires_direct_base,
        violation_fixture=_with(
            attributes={
                "items": {
                    "power": {
                        "domain": "number",
                        "base": {"formula": {"literal": 5}},
                        "accepts": ["allocation"],
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="bounds_required_for_domain",
        scope="/attributes/items/{id}",
        description=(
            "A percentage/probability attribute declares no bounds (bounds are "
            "mandatory for those domains)."
        ),
        since_version=_SINCE,
        check=_check_bounds_required_for_domain,
        violation_fixture=_with(
            attributes={
                "items": {"crit": {"domain": "probability", "base": {"direct": 0.3}}}
            }
        ),
    ),
    SemanticRule(
        code="bounds_empty",
        scope="/attributes/items/{id}/bounds",
        description=(
            "A declared bounds object declares neither floor nor cap "
            "(it narrows nothing)."
        ),
        since_version=_SINCE,
        check=_check_bounds_empty,
        violation_fixture=_with(
            attributes={
                "items": {
                    "span": {
                        "domain": "number",
                        "base": {"direct": 5},
                        "bounds": {},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="bounds_inverted",
        scope="/attributes/items/{id}/bounds",
        description="A bounds object declares floor greater than cap.",
        since_version=_SINCE,
        check=_check_bounds_inverted,
        violation_fixture=_with(
            attributes={
                "items": {
                    "span": {
                        "domain": "number",
                        "base": {"direct": 5},
                        "bounds": {"floor": 100, "cap": 0},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="bounds_outside_domain",
        scope="/attributes/items/{id}/bounds",
        description=(
            "A probability attribute's bounds declare a side outside the "
            "domain's [0, 1] space."
        ),
        since_version=_SINCE,
        check=_check_bounds_outside_domain,
        violation_fixture=_with(
            attributes={
                "items": {
                    "crit": {
                        "domain": "probability",
                        "base": {"direct": 0.3},
                        "bounds": {"floor": -1, "cap": 2},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="base_outside_domain",
        scope="/attributes/items/{id}/base",
        description=(
            "A probability attribute's direct base is outside the domain's "
            "[0, 1] space."
        ),
        since_version=_SINCE,
        check=_check_base_outside_domain,
        violation_fixture=_with(
            attributes={
                "items": {
                    "crit": {
                        "domain": "probability",
                        "base": {"direct": 2},
                        "bounds": {"floor": 0, "cap": 0.5},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="tier_pattern_unsatisfied",
        scope="/attributes/items/{id}",
        description=(
            "A labeled attribute violates its tier's facet pattern (accepts by "
            "exact set equality)."
        ),
        since_version=_SINCE,
        check=_check_tier_pattern_unsatisfied,
        violation_fixture=_with(
            attributes={
                "tiers": {
                    "primary": {"base": "direct", "accepts": ["allocation", "effects"]}
                },
                "items": {
                    "agi": {
                        "domain": "number",
                        "base": {"direct": 8},
                        "accepts": ["allocation"],
                        "tier": "primary",
                    }
                },
            }
        ),
    ),
    SemanticRule(
        code="form_points_not_increasing",
        scope="/attributes/items/{id}/base/formula/points",
        description=(
            "A piecewise_linear/lookup_table form's x-values are not strictly "
            "increasing."
        ),
        since_version=_SINCE,
        check=_check_form_points_not_increasing,
        violation_fixture=_with(
            attributes={
                "items": {
                    "level": {"domain": "number", "base": {"direct": 3}},
                    "curve": {
                        "domain": "number",
                        "base": {
                            "formula": {
                                "form": "piecewise_linear",
                                "input": {"attr": "level"},
                                "points": [[5, 30], [1, 10]],
                            }
                        },
                    },
                }
            }
        ),
    ),
    SemanticRule(
        code="form_points_insufficient",
        scope="/attributes/items/{id}/base/formula/points",
        description=(
            "A piecewise_linear form has fewer than 2 points, or a lookup_table "
            "fewer than 1 entry."
        ),
        since_version=_SINCE,
        check=_check_form_points_insufficient,
        violation_fixture=_with(
            attributes={
                "items": {
                    "level": {"domain": "number", "base": {"direct": 3}},
                    "curve": {
                        "domain": "number",
                        "base": {
                            "formula": {
                                "form": "piecewise_linear",
                                "input": {"attr": "level"},
                                "points": [[1, 10]],
                            }
                        },
                    },
                }
            }
        ),
    ),
    SemanticRule(
        code="form_coefficients_count_invalid",
        scope="/attributes/items/{id}/base/formula/coefficients",
        description="A polynomial form has 0 or more than 8 coefficients.",
        since_version=_SINCE,
        check=_check_form_coefficients_count_invalid,
        violation_fixture=_with(
            attributes={
                "items": {
                    "level": {"domain": "number", "base": {"direct": 3}},
                    "poly": {
                        "domain": "number",
                        "base": {
                            "formula": {
                                "form": "polynomial",
                                "input": {"attr": "level"},
                                "coefficients": [1, 2, 3, 4, 5, 6, 7, 8, 9],
                            }
                        },
                    },
                }
            }
        ),
    ),
    SemanticRule(
        code="exponential_growth_rate_positive",
        scope="/attributes/items/{id}/base/formula/growth_rate",
        description=(
            "An exponential form's resolved growth_rate is not strictly positive."
        ),
        since_version=_SINCE,
        check=_check_exponential_growth_rate_positive,
        violation_fixture=_with(
            attributes={
                "items": {
                    "level": {"domain": "number", "base": {"direct": 3}},
                    "escalation": {
                        "domain": "number",
                        "base": {
                            "formula": {
                                "form": "exponential",
                                "input": {"attr": "level"},
                                "coefficient": 1,
                                "growth_rate": 0,
                            }
                        },
                    },
                }
            }
        ),
    ),
    SemanticRule(
        code="expression_tree_too_deep",
        scope="/attributes/items/{id}/base/formula",
        description="A base-formula expression tree is deeper than 32.",
        since_version=_SINCE,
        check=_check_expression_tree_too_deep,
        violation_fixture=_with(
            attributes={
                "items": {
                    "deep": {"domain": "number", "base": {"formula": _nested_floor(33)}}
                }
            }
        ),
    ),
    SemanticRule(
        code="expression_tree_too_large",
        scope="/attributes/items/{id}/base/formula",
        description="A base-formula expression tree has more than 256 nodes.",
        since_version=_SINCE,
        check=_check_expression_tree_too_large,
        violation_fixture=_with(
            attributes={
                "items": {
                    "wide": {"domain": "number", "base": {"formula": _wide_add(256)}}
                }
            }
        ),
    ),
    SemanticRule(
        code="reserved_section_present",
        scope="/{section}",
        description=(
            "A reserved top-level section is present (refused until its owning "
            "issue designs it)."
        ),
        since_version=_SINCE,
        check=_check_reserved_section_present,
        violation_fixture={**_base_document(), "builds": {}},
    ),
    # --- Effects (bADR-0006) -----------------------------------------------
    SemanticRule(
        code="modifier_target_undefined",
        scope="/effects/items/{id}/modifiers/{index}",
        description=(
            "A modifier's target names no attribute declared in attributes.items."
        ),
        since_version=_SINCE,
        check=_check_modifier_target_undefined,
        violation_fixture=_effects_fixture(
            {
                "stacking_types": _STACKING_TYPES,
                "items": {
                    "buff": {
                        "modifiers": [_modifier("continuous", target="missing")],
                        "duration": "infinite",
                        "stacking": _STACKING,
                    }
                },
            }
        ),
    ),
    SemanticRule(
        code="stacking_type_undefined",
        scope="/effects/items/{id}/stacking",
        description=(
            "A persistent effect's stacking.type names no declared stacking type."
        ),
        since_version=_SINCE,
        check=_check_stacking_type_undefined,
        violation_fixture=_effects_fixture(
            {
                "items": {
                    "buff": {
                        "modifiers": [_modifier("continuous")],
                        "duration": "infinite",
                        "stacking": {"type": "ghost", "lifetime": "independent"},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="application_duration_illegal",
        scope="/effects/items/{id}/modifiers/{index}",
        description=(
            "An instant effect carries a non-one_shot modifier "
            "(continuous/periodic require a timed/infinite duration)."
        ),
        since_version=_SINCE,
        check=_check_application_duration_illegal,
        violation_fixture=_effects_fixture(
            {
                "items": {
                    "burst": {
                        "modifiers": [_modifier("continuous")],
                        "duration": "instant",
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="instant_effect_forbids_stacking",
        scope="/effects/items/{id}/stacking",
        description="An instant effect declares stacking (it leaves no instance).",
        since_version=_SINCE,
        check=_check_instant_effect_forbids_stacking,
        violation_fixture=_effects_fixture(
            {
                "stacking_types": _STACKING_TYPES,
                "items": {
                    "burst": {
                        "modifiers": [_modifier("one_shot")],
                        "duration": "instant",
                        "stacking": _STACKING,
                    }
                },
            }
        ),
    ),
    SemanticRule(
        code="persistent_effect_requires_stacking",
        scope="/effects/items/{id}",
        description="A timed/infinite effect declares no stacking.",
        since_version=_SINCE,
        check=_check_persistent_effect_requires_stacking,
        violation_fixture=_effects_fixture(
            {
                "items": {
                    "buff": {
                        "modifiers": [_modifier("continuous")],
                        "duration": {"timed": 10},
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="override_forbidden_on_delta",
        scope="/effects/items/{id}/modifiers/{index}",
        description=(
            "An override modifier is applied as a one_shot/periodic delta "
            "(override replaces, it is not a delta)."
        ),
        since_version=_SINCE,
        check=_check_override_forbidden_on_delta,
        violation_fixture=_effects_fixture(
            {
                "items": {
                    "strike": {
                        "modifiers": [_modifier("one_shot", operation="override")],
                        "duration": "instant",
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="period_required_for_periodic",
        scope="/effects/items/{id}",
        description="An effect with a periodic modifier declares no period.",
        since_version=_SINCE,
        check=_check_period_required_for_periodic,
        violation_fixture=_effects_fixture(
            {
                "stacking_types": _STACKING_TYPES,
                "items": {
                    "dot": {
                        "modifiers": [_modifier("periodic")],
                        "duration": {"timed": 10},
                        "stacking": _STACKING,
                    }
                },
            }
        ),
    ),
    SemanticRule(
        code="period_forbidden_when_all_one_shot",
        scope="/effects/items/{id}/period",
        description="An effect whose modifiers are all one_shot declares a period.",
        since_version=_SINCE,
        check=_check_period_forbidden_when_all_one_shot,
        violation_fixture=_effects_fixture(
            {
                "items": {
                    "strike": {
                        "modifiers": [_modifier("one_shot")],
                        "duration": "instant",
                        "period": 1,
                    }
                }
            }
        ),
    ),
    SemanticRule(
        code="temporal_value_not_positive",
        scope="/effects/items/{id}/duration",
        description="A timed duration or a period is not strictly positive.",
        since_version=_SINCE,
        check=_check_temporal_value_not_positive,
        violation_fixture=_effects_fixture(
            {
                "stacking_types": _STACKING_TYPES,
                "items": {
                    "buff": {
                        "modifiers": [_modifier("continuous")],
                        "duration": {"timed": 0},
                        "stacking": _STACKING,
                    }
                },
            }
        ),
    ),
    SemanticRule(
        code="period_below_minimum_granularity",
        scope="/effects/items/{id}/period",
        description="A period is below the v1 minimum tick granularity (0.05 s).",
        since_version=_SINCE,
        check=_check_period_below_minimum_granularity,
        violation_fixture=_effects_fixture(
            {
                "stacking_types": _STACKING_TYPES,
                "items": {
                    "aura": {
                        "modifiers": [_modifier("continuous")],
                        "duration": {"timed": 10},
                        "period": 0.01,
                        "stacking": _STACKING,
                    }
                },
            }
        ),
    ),
    SemanticRule(
        code="tick_budget_exceeded",
        scope="/effects/items/{id}/period",
        description=(
            "A timed effect's duration / period exceeds the per-instance tick "
            "budget (10 000)."
        ),
        since_version=_SINCE,
        check=_check_tick_budget_exceeded,
        violation_fixture=_effects_fixture(
            {
                "stacking_types": _STACKING_TYPES,
                "items": {
                    "aura": {
                        "modifiers": [_modifier("continuous")],
                        "duration": {"timed": 600},
                        "period": 0.05,
                        "stacking": _STACKING,
                    }
                },
            }
        ),
    ),
)


def _schema_reference_rule(structural_schema_id: str) -> SemanticRule:
    """The one line-specific rule, bound to ``structural_schema_id`` — the
    ``$id`` a document declaring this line's version must point ``$schema`` at."""
    return SemanticRule(
        code="schema_reference_disagreement",
        scope="/$schema",
        description=(
            "The document's $schema disagrees with the versioned structural schema $id."
        ),
        since_version=_SINCE,
        check=_schema_reference_disagreement_check(structural_schema_id),
        violation_fixture={**_base_document(), "$schema": "urn:disagrees"},
    )


def build_semantic_rules(structural_schema_id: str) -> tuple[SemanticRule, ...]:
    """The full v1 semantic rule set for one line — the line-independent rules
    plus the ``$schema``-agreement rule bound to this line's structural-schema
    ``$id``. One builder, so a bundle's rules and the ``$schema`` target it
    compares against cannot drift (bADR-0001/0005). Registry order is
    insignificant: the catalog sorts by id, the namespace is a set, and the
    report sorts by ``(path, code)``."""
    return (*_LINE_INDEPENDENT_RULES, _schema_reference_rule(structural_schema_id))


# The v1 line's rule registry — the one authority the catalog and the
# conformance walk project from (bADR-0005). It is the 1.0 bundle's
# `semantic_rules`; the funnel runs the *resolved bundle's* rules, never this
# global directly.
SEMANTIC_RULES: tuple[SemanticRule, ...] = build_semantic_rules(STRUCTURAL_SCHEMA_ID)
