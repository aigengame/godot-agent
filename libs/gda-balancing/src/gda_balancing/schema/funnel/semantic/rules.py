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

Scope note: PR1 reference-integrity (undefined ``attr``/``param``) applies to
**base formulas only** — no effects section exists yet — but the walker
(:func:`gda_balancing.schema.funnel.semantic.graph.iter_references`) is written
so the effects stage reuses it by passing its own base-pointer tokens.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gda_balancing.envelope import Refusal
from gda_balancing.schema import pointer
from gda_balancing.schema.funnel.semantic.graph import (
    cyclic_components,
    iter_references,
)
from gda_balancing.schema.model.document import DesignDocument
from gda_balancing.schema.model.formula import (
    BinaryOp,
    DirectBase,
    ExponentialForm,
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


def _formula_tokens(attr_id: str) -> tuple[str, ...]:
    return (*_attr_tokens(attr_id), "base", "formula")


def _refuse(code: str, tokens: tuple[str | int, ...], detail: str) -> Refusal:
    return Refusal(code=code, path=pointer.build(*tokens), detail=detail)


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


def _reference_undefined(
    doc: DesignDocument, want_kind: str, code: str, is_declared: Callable[[str], bool]
) -> list[Refusal]:
    """Shared driver for the two reference-integrity rules: walk every base
    formula's references of ``want_kind`` and refuse each undeclared id at its
    own node pointer."""
    refusals: list[Refusal] = []
    for attr_id, attribute in doc.attributes.items.items():
        base = attribute.base
        if not isinstance(base, FormulaBase):
            continue
        for kind, ref_id, tokens in iter_references(
            base.formula, _formula_tokens(attr_id)
        ):
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


def _check_schema_reference_disagreement(
    _doc: DesignDocument, raw: dict[str, Any]
) -> list[Refusal]:
    reference = raw.get("$schema")
    if reference is not None and reference != STRUCTURAL_SCHEMA_ID:
        return [
            _refuse(
                "schema_reference_disagreement",
                ("$schema",),
                "$schema does not match the versioned structural schema $id",
            )
        ]
    return []


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


# --- The one registry ------------------------------------------------------

SEMANTIC_RULES: tuple[SemanticRule, ...] = (
    SemanticRule(
        code="attribute_reference_undefined",
        scope="/attributes/items/{id}/base/formula",
        description=(
            "A base-formula attr node references an id not declared in "
            "attributes.items."
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
        scope="/attributes/items/{id}/base/formula",
        description=(
            "A base-formula param node references an id not declared in parameters."
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
        code="schema_reference_disagreement",
        scope="/$schema",
        description=(
            "The document's $schema disagrees with the versioned structural schema $id."
        ),
        since_version=_SINCE,
        check=_check_schema_reference_disagreement,
        violation_fixture={**_base_document(), "$schema": "urn:disagrees"},
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
)
